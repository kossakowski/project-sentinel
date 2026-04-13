# Phase 3: Processing Pipeline

> STATUS: COMPLETE — implemented in production
> KEY FILES: `sentinel/processing/normalizer.py`, `sentinel/processing/deduplicator.py`, `sentinel/processing/keyword_filter.py`

## Objective
Normalize articles from all fetchers into a consistent format, deduplicate them (both exact and fuzzy), and apply keyword pre-filtering to reduce the volume sent to the LLM classifier.

## Deliverables

### 3.1 Normalizer (`sentinel/processing/normalizer.py`)

Converts raw fetcher output into clean, consistent `Article` objects ready for dedup and filtering.

#### Normalization Steps

Anchor: `sentinel/processing/normalizer.py`.

| Field | Rule | Limit | Fallback |
|---|---|---|---|
| `title` | Strip whitespace, collapse spaces, decode HTML entities, strip tags | 500 chars, `...` suffix on truncation | — |
| `summary` | Same cleaning as title | 1000 chars, `...` suffix on truncation | Set to `title` if empty after cleaning (`normalizer.py:46-47`) |
| `url` | Lowercase domain, strip `www.`, drop params (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `fbclid`, `gclid`), strip trailing slash, drop fragment | — | — |
| `published_at` | Ensure UTC; assume UTC if naive; cap future timestamps at `now` | — | `fetched_at` if None |
| `language` | Full-name → ISO map | — | Passthrough for unknown values |
| `url_hash` | SHA-256 hex digest of normalized URL | — | — |
| `title_normalized` | Lowercase, NFKD strip accents, remove punctuation, collapse whitespace | — | — |

**Language map (full name → ISO):**

| Input | Output |
|---|---|
| English | en |
| Polish | pl |
| Ukrainian | uk |
| Russian | ru |
| German | de |
| French | fr |
| Lithuanian | lt |
| Latvian | lv |
| Estonian | et |

Languages outside keyword config (`de`, `fr`, `lt`, `lv`, `et`) fall back to English keyword set at filter stage.

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

Compares `title_normalized` against recent articles within `processing.dedup.lookback_minutes` (default/live 60) using `rapidfuzz.fuzz.ratio`. Anchor: `sentinel/processing/deduplicator.py`.

| Comparison | Threshold | Outcome |
|---|---|---|
| Same `source_name`, fuzz.ratio(title_normalized) | >= `processing.dedup.same_source_title_threshold` (default/live 85) | Duplicate (drop) |
| Different source, fuzz.ratio(title_normalized) | >= `processing.dedup.cross_source_title_threshold` (default/live 95) | Duplicate (drop, syndication) |
| Different source, between same and cross thresholds | — | Not duplicate (potential corroboration) |

#### Side Effects
- `deduplicate_batch` inserts non-duplicates into the DB mid-iteration so later items in the same batch dedup against them (`deduplicator.py:93`).
- Internal `seen_hashes` set provides batch-internal dedup before DB lookup.

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

Anchor: `sentinel/processing/keyword_filter.py`.

#### Matching Algorithm

| Step | Behavior | Anchor |
|---|---|---|
| 1 | Search text = `f"{title} {summary}".lower()` | `keyword_filter.py:51` |
| 2 | Resolve keyword set by `article.language`; unknown → fall back to `en` | `keyword_filter.py:46-48` |
| 3 | Source with `keyword_bypass: true` skips filter entirely; annotated `level="bypass"` | `keyword_filter.py:103-111` |
| 4 | Check `critical` keywords → `level="critical"` if any hit | — |
| 5 | Else check `high` keywords → `level="high"` if any hit | — |
| 6 | `exclude` keywords drop the article ONLY when no `critical` match | `keyword_filter.py:64-73` |
| 7 | Slavic (`pl`, `uk`, `ru`): plain substring match (`kw_lower in text`) | `keyword_filter.py:188` |
| 8 | English and all other langs: word-boundary regex `\b<kw>\b` via `re.search` | `keyword_filter.py:192` |
| 9 | Multi-word phrases matched as whole phrase (no token splitting) | — |

#### Keyword Match Annotation

Written to `article.raw_metadata["keyword_match"]`:

| Key | Value |
|---|---|
| `level` | `"critical"`, `"high"`, or `"bypass"` |
| `matched_keywords` | list[str] of all matched keywords |
| `language_matched` | ISO code of the keyword set actually used (may differ from `article.language` on fallback) |

```python
article.raw_metadata["keyword_match"] = {
    "level": "critical",
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

## Known Quirks

| Quirk | Impact |
|---|---|
| GDELT articles have empty `summary` | Keyword filter scans title only for GDELT items |
| Same-source threshold (85) < cross-source threshold (95) | Same source repeating itself is caught more aggressively than cross-source syndication |
| `deduplicate_batch` inserts non-duplicates into DB mid-batch | Order-sensitive within a single fetch cycle — later items dedup against earlier items of the same batch |
