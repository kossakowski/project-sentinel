# Phase 3: Processing Pipeline

> STATUS: COMPLETE — implemented in production
> KEY FILES: `sentinel/processing/normalizer.py`, `sentinel/processing/deduplicator.py`, `sentinel/processing/keyword_filter.py`

## Objective
Normalize articles from all fetchers into a consistent format, deduplicate them (both exact and fuzzy), and apply keyword pre-filtering to reduce the volume sent to the LLM classifier.

## Deliverables

### 3.1 Normalizer (`sentinel/processing/normalizer.py`)

Converts raw fetcher output into clean, consistent `Article` objects ready for dedup and filtering.

#### Normalization Steps

1. **Title cleaning**
   - Strip leading/trailing whitespace
   - Collapse multiple whitespace into single space
   - Remove HTML entities (`&amp;` → `&`, `&#39;` → `'`, etc.)
   - Strip any remaining HTML tags
   - Truncate to 500 characters (with `...` suffix if truncated)

2. **Summary cleaning**
   - Same as title cleaning
   - Truncate to 1000 characters
   - If empty, use title as summary

3. **URL normalization**
   - Strip tracking parameters (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `fbclid`, `gclid`)
   - Strip trailing slashes
   - Lowercase the domain portion
   - Remove `www.` prefix from domain
   - This ensures the same article linked from different campaigns deduplicates correctly

4. **Timestamp normalization**
   - Convert all timestamps to UTC `datetime` objects
   - If no timezone info, assume UTC
   - If timestamp is in the future (clock skew), cap at current UTC time
   - If timestamp is missing, use `fetched_at`

5. **Language detection**
   - If language is set by the fetcher config, trust it
   - If language is unknown (e.g., GDELT maps "English" → "en"), map it
   - Language mapping table:
     ```
     "English" → "en"
     "Polish" → "pl"
     "Ukrainian" → "uk"
     "Russian" → "ru"
     "German" → "de"
     "French" → "fr"
     "Lithuanian" → "lt"
     "Latvian" → "lv"
     "Estonian" → "et"
     ```
   - Languages not in the keyword lists ("de", "fr", etc.) are still stored but will pass through keyword filtering only if they match English keywords (many international articles about military events use English military terminology even in other languages)

6. **Generate derived fields**
   - `url_hash` = SHA-256 hex digest of the normalized URL
   - `title_normalized` = lowercase, strip accents (unicodedata NFKD), remove punctuation, collapse whitespace

#### Interface

```python
class Normalizer:
    def normalize(self, article: Article) -> Article:
        """Return a new Article with normalized fields."""

    def normalize_batch(self, articles: list[Article]) -> list[Article]:
        """Normalize a list of articles."""
```

### 3.2 Deduplicator (`sentinel/processing/deduplicator.py`)

Removes duplicate articles using two strategies:

#### Strategy 1: Exact URL Dedup
- Compute `url_hash` (SHA-256 of normalized URL)
- Check against SQLite `articles.url_hash` column
- If hash exists → duplicate, skip

#### Strategy 2: Fuzzy Title Dedup
- For articles that pass URL dedup, compare `title_normalized` against recent articles (last 60 minutes) using `rapidfuzz.fuzz.ratio`
- If similarity > 85% AND same `source_type` is different (i.e., same story from different sources) → NOT a duplicate (we want cross-source corroboration)
- If similarity > 85% AND same `source_name` → duplicate, skip (same source republished)
- If similarity > 95% regardless of source → likely exact duplicate, skip
- The thresholds (85%, 95%) must be configurable in config

#### Interface

```python
class Deduplicator:
    def __init__(self, db: Database, config: SentinelConfig):
        self.db = db
        self.config = config

    def is_duplicate(self, article: Article) -> bool:
        """Check if article is a duplicate. Returns True if it should be skipped."""

    def deduplicate_batch(self, articles: list[Article]) -> list[Article]:
        """Filter out duplicates from a batch. Non-duplicates are inserted into DB."""
```

#### Dedup Configuration
```yaml
processing:
  dedup:
    same_source_title_threshold: 85  # fuzzy match % to consider same-source duplicate
    cross_source_title_threshold: 95  # fuzzy match % to consider cross-source exact duplicate
    lookback_minutes: 60  # how far back to check for fuzzy matches
```

### 3.3 Keyword Filter (`sentinel/processing/keyword_filter.py`)

Filters articles to only those matching military/conflict keywords, while excluding known false positive patterns.

#### Matching Algorithm

1. **Determine article language** from `article.language`
2. **Get keyword lists** for that language from `config.monitoring.keywords[language]`
3. **Check critical keywords** -- if any critical keyword appears in title OR summary, mark as `keyword_match="critical"`
4. **Check high keywords** -- if any high keyword appears, mark as `keyword_match="high"`
5. **Check exclude keywords** -- if any exclude keyword appears AND no critical keyword matched, skip the article
6. **Cross-language fallback** -- if article language is not in the keyword config (e.g., German article), check against English keywords
7. **Return** only articles with a keyword match, annotated with match level

#### Matching Rules
- Case-insensitive matching
- Match whole words only where possible (avoid "game" matching "gamer"), but be flexible with inflected languages (Polish, Ukrainian, Russian have many word forms)
- For Slavic languages (PL, UK, RU), use substring matching (stems) because word endings change with grammatical case
- For English, prefer word-boundary matching

#### Keyword Match Annotation
Add to `Article.raw_metadata`:
```python
article.raw_metadata["keyword_match"] = {
    "level": "critical",  # or "high"
    "matched_keywords": ["inwazja", "atak zbrojny"],
    "language_matched": "pl",
}
```

#### Interface

```python
class KeywordFilter:
    def __init__(self, config: SentinelConfig):
        self.config = config

    def matches(self, article: Article) -> dict | None:
        """Check if article matches any keywords.
        Returns match info dict if matched, None if not matched."""

    def filter_batch(self, articles: list[Article]) -> list[Article]:
        """Filter articles to only those matching keywords.
        Annotates matched articles with keyword info in raw_metadata."""
```

#### Keyword Lists (from config)

The keyword lists are defined in `config/config.yaml` under `monitoring.keywords`. Example structure:

**English critical:**
`military attack`, `invasion`, `troops crossed border`, `missile strike`, `aerial bombardment`, `declaration of war`, `Article 5`, `armed attack`, `act of war`, `offensive operation`, `ground invasion`, `amphibious assault`, `nuclear strike`, `carpet bombing`, `total war`

**English high:**
`military buildup`, `troops massing`, `airspace violation`, `shots fired`, `border incident`, `mobilization`, `military escalation`, `no-fly zone violated`, `naval confrontation`, `cyberattack on infrastructure`, `martial law declared`, `reservists called up`, `border closed`

**Polish critical:**
`atak militarny`, `atak wojskowy`, `inwazja`, `wojska przekroczyły granicę`, `uderzenie rakietowe`, `bombardowanie`, `stan wojenny`, `Artykuł 5`, `atak zbrojny`, `akt wojny`, `operacja ofensywna`, `inwazja lądowa`, `nalot`, `ostrzał`

**Polish high:**
`koncentracja wojsk`, `naruszenie przestrzeni powietrznej`, `strzały`, `incydent graniczny`, `mobilizacja`, `eskalacja`, `zamknięcie granicy`, `postawienie w gotowość`, `stan wyjątkowy`, `alarm`, `zagrożenie`

**Ukrainian critical:**
`військовий напад`, `вторгнення`, `ракетний удар`, `перетин кордону`, `бомбардування`, `оголошення війни`, `збройний напад`, `наступальна операція`

**Ukrainian high:**
`порушення повітряного простору`, `обстріл`, `мобілізація`, `ескалація`, `концентрація військ`

**Russian critical:**
`военная операция`, `вторжение`, `ракетный удар`, `пересечение границы`, `бомбардировка`, `объявление войны`, `вооруженное нападение`

**Russian high:**
`провокация`, `угроза`, `нарушение границы`, `мобилизация`, `эскалация`, `концентрация войск`, `специальная операция`

**Exclude keywords (English):**
`exercise`, `drill`, `simulation`, `memorial`, `anniversary`, `museum`, `movie`, `film`, `game`, `book`, `historical`, `World War II`, `WWII`, `Cold War`, `veteran`, `parade`, `remembrance`, `documentary`, `fiction`, `novel`, `series`, `recap`, `review`, `opinion`, `editorial`, `analysis` (note: `analysis` only in exclude, not in critical/high)

**Exclude keywords (Polish):**
`ćwiczenia`, `manewry`, `symulacja`, `rocznica`, `muzeum`, `film`, `gra`, `historyczny`, `II wojna światowa`, `zimna wojna`, `weteran`, `parada`, `dokumentalny`, `recenzja`, `opinia`, `felieton`

## Pipeline Integration

The three components chain together:

```python
async def process_articles(raw_articles: list[Article]) -> list[Article]:
    """Full processing pipeline."""
    # Step 1: Normalize
    normalized = normalizer.normalize_batch(raw_articles)

    # Step 2: Deduplicate
    unique = deduplicator.deduplicate_batch(normalized)

    # Step 3: Keyword filter
    relevant = keyword_filter.filter_batch(unique)

    return relevant
```

Expected reduction at each stage:
- Raw fetch: ~200-500 articles per cycle
- After dedup: ~20-100 new articles
- After keyword filter: ~5-20 relevant articles
- These ~5-20 go to the LLM classifier (Phase 4)

## Acceptance Tests

### test_normalizer.py
1. `test_strip_html_from_title` -- `<b>Breaking</b> news` → `Breaking news`
2. `test_strip_html_entities` -- `AT&amp;T` → `AT&T`
3. `test_collapse_whitespace` -- `Breaking   news  here` → `Breaking news here`
4. `test_truncate_long_title` -- title > 500 chars truncated with `...`
5. `test_url_tracking_params_stripped` -- UTM params removed
6. `test_url_www_removed` -- `www.example.com` → `example.com`
7. `test_timestamp_future_capped` -- future timestamp capped to now
8. `test_timestamp_missing_uses_fetched` -- missing pubdate uses fetched_at
9. `test_url_hash_consistent` -- same URL always produces same hash
10. `test_title_normalized_lowercase` -- normalized title is lowercase
11. `test_title_normalized_no_accents` -- accented chars normalized (ó→o, ą→a)
12. `test_language_mapping` -- "English" → "en", "Polish" → "pl"

### test_deduplicator.py
1. `test_exact_url_duplicate_rejected` -- same URL → rejected
2. `test_different_url_passes` -- different URL → not duplicate
3. `test_fuzzy_title_same_source_rejected` -- 90% similar title from same source → rejected
4. `test_fuzzy_title_different_source_passes` -- 90% similar title from different source → passes (corroboration)
5. `test_very_similar_title_cross_source_rejected` -- 98% similar from different source → rejected (exact duplicate syndicated)
6. `test_old_article_not_checked` -- article from 2 hours ago not compared (outside lookback window)
7. `test_empty_db_all_pass` -- first run, all articles pass
8. `test_batch_internal_dedup` -- two identical articles in same batch, only first passes

### test_keyword_filter.py
1. `test_critical_keyword_matches` -- article with "inwazja" in title matches as critical
2. `test_high_keyword_matches` -- article with "mobilizacja" matches as high
3. `test_no_keyword_rejected` -- article about weather → rejected
4. `test_exclude_keyword_filters` -- article with "ćwiczenia wojskowe" (military exercise) → rejected
5. `test_exclude_overridden_by_critical` -- article with both "inwazja" and "ćwiczenia" → passes (critical overrides exclude)
6. `test_english_keywords_on_english_article` -- English article matches English keywords
7. `test_polish_keywords_on_polish_article` -- Polish article matches Polish keywords
8. `test_unknown_language_falls_back_to_english` -- German article checked against English keywords
9. `test_case_insensitive` -- "INWAZJA" matches "inwazja"
10. `test_match_annotation_added` -- matched keywords stored in raw_metadata
11. `test_multiple_keywords_all_recorded` -- article matching 3 keywords has all 3 in annotation
12. `test_russian_provocation_keyword` -- "провокация" (provocation) matches as high -- important counter-indicator
