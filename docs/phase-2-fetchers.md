# Phase 2: Source Fetchers

## Objective
Implement fetchers for all configured media sources. Each fetcher produces a list of `Article` objects in a unified format. Fetchers must handle network errors, timeouts, malformed responses, and rate limiting gracefully.

## Deliverables

### 2.1 Base Fetcher (`sentinel/fetchers/base.py`)

Abstract base class that all fetchers inherit from:

```python
from abc import ABC, abstractmethod

class BaseFetcher(ABC):
    def __init__(self, config: SentinelConfig):
        self.config = config
        self.logger = logging.getLogger(f"sentinel.fetcher.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        """Fetcher identifier, e.g. 'rss', 'gdelt'."""

    @abstractmethod
    async def fetch(self) -> list[Article]:
        """Fetch articles from the source. Returns empty list on failure."""

    def is_enabled(self) -> bool:
        """Check if this fetcher is enabled in config."""
```

All fetchers:
- Return `list[Article]` (empty list on failure, never raise)
- Log errors but don't crash
- Respect timeouts (configurable, default 30 seconds per HTTP request)
- Set `source_type` on every Article they produce
- Set `fetched_at` to current UTC time

### 2.2 RSS Fetcher (`sentinel/fetchers/rss.py`)

Polls all RSS feeds defined in `config.sources.rss` where `enabled: true`.

#### Behavior
1. All enabled RSS sources are fetched **concurrently** using `asyncio.gather()`. Each source is wrapped in a safe handler so one timeout or failure doesn't block others -- total fetch time is the time of the slowest source, not the sum of all.
2. For each enabled RSS source in config:
   - Send HTTP GET with `If-Modified-Since` / `If-None-Match` headers (cache previous ETag/Last-Modified per source)
   - Parse response with `feedparser`
   - For each entry in the feed:
     - Extract `title`, `link`, `published` (or `updated`), `summary`
     - Create an `Article` with `source_type="rss"`, `source_name` from config, `language` from config
     - Store GDELT-style metadata if available (tone, themes) in `raw_metadata`
3. Handle errors per source (one broken feed shouldn't skip all others)
4. Return all collected articles

#### `max_priority` Parameter

```python
async def fetch(self, *, max_priority: int | None = None) -> list[Article]:
    """Fetch articles from all enabled RSS sources.

    Args:
        max_priority: When set (e.g., max_priority=1), only fetches RSS sources
                      with priority <= max_priority. Used by the fast-lane
                      scheduler job to fetch only priority-1 (critical) sources.
    """
```

#### RSS Source Priority Field

Each RSS source in config has an integer `priority` field:
- **Priority 1**: Fast-lane sources -- checked every 3 minutes (e.g., major national news agencies, military-focused feeds)
- **Priority 2-3**: Slow-lane only -- checked every 15 minutes (e.g., regional sources, less critical feeds)

Example config:
```yaml
sources:
  rss:
    - name: "PAP"
      url: "https://www.pap.pl/rss.xml"
      language: "pl"
      priority: 1
      enabled: true
    - name: "Gazeta Wyborcza"
      url: "https://wyborcza.pl/0,0.rss"
      language: "pl"
      priority: 2
      enabled: true
```

#### HTTP Headers
```python
headers = {
    "User-Agent": "ProjectSentinel/1.0 (military-alert-monitor)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}
# Add conditional headers if cached:
if etag:
    headers["If-None-Match"] = etag
if last_modified:
    headers["If-Modified-Since"] = last_modified
```

#### Feed Parsing Notes
- `feedparser` returns `entries` list; each entry has `title`, `link`, `published_parsed` (or `updated_parsed`), `summary`
- `published_parsed` is a `time.struct_time` -- convert to `datetime` UTC
- Some feeds may not have `summary` -- use empty string
- Some feeds may have HTML in `summary` -- strip tags (use `html.parser` or `bleach`)

#### ETag/Last-Modified Cache
Store in memory (dict keyed by source URL). No persistence needed -- on restart, we'll refetch everything and dedup will handle it.

### 2.3 GDELT Fetcher (`sentinel/fetchers/gdelt.py`)

Queries the GDELT DOC 2.0 API for articles matching configured themes and geographic filters.

#### API Endpoint
```
https://api.gdeltproject.org/api/v2/doc/doc
```

#### Query Construction

Build the query from config values:

```python
def build_query(self) -> str:
    """Build GDELT query string from config."""
    parts = []

    # Theme filter
    themes = self.config.sources.gdelt.themes
    if themes:
        theme_query = " OR ".join(f'theme:{t}' for t in themes)
        parts.append(f"({theme_query})")

    # Country filter (target countries)
    countries = self.config.monitoring.target_countries
    if countries:
        country_codes = [c["code"] for c in countries]
        # GDELT uses FIPS country codes; PL=PL, LT=LH, LV=LG, EE=EN
        fips_map = {"PL": "PL", "LT": "LH", "LV": "LG", "EE": "EN"}
        fips_codes = [fips_map.get(c, c) for c in country_codes]
        country_query = " OR ".join(f'sourcecountry:{c}' for c in fips_codes)
        parts.append(f"({country_query})")

    return " ".join(parts)
```

#### Request Parameters
```python
params = {
    "query": self.build_query(),
    "mode": "ArtList",
    "maxrecords": 250,
    "format": "json",
    "TIMESPAN": f"{self.config.sources.gdelt.update_interval_minutes}min",
    "sort": "DateDesc",
}
```

#### Response Parsing
GDELT returns JSON with an `articles` array:
```json
{
  "articles": [
    {
      "url": "https://...",
      "title": "...",
      "seendate": "20250910T034800Z",
      "socialimage": "...",
      "domain": "reuters.com",
      "language": "English",
      "sourcecountry": "United States"
    }
  ]
}
```

Map each article to our `Article` model:
- `source_url` = `url`
- `title` = `title`
- `published_at` = parse `seendate` (format: `%Y%m%dT%H%M%SZ`)
- `language` = map GDELT language name to ISO code
- `source_name` = `"GDELT:{domain}"` (e.g., `"GDELT:reuters.com"`)
- `source_type` = `"gdelt"`
- `raw_metadata` = full GDELT record (tone, themes, etc.)

#### Rate Limiting
GDELT DOC 2.0 API has no published rate limits but be respectful:
- No more than 1 request per poll cycle
- Minimum 5-second delay if making multiple queries

### 2.4 Google News Fetcher (`sentinel/fetchers/google_news.py`)

Generates Google News RSS URLs from configured keyword queries and polls them.

#### URL Construction
```python
def build_feed_url(self, query: GoogleNewsQuery) -> str:
    """Build Google News RSS URL from a query config."""
    encoded_query = urllib.parse.quote(query.query)
    lang_map = {"en": ("en", "US"), "pl": ("pl", "PL"), "uk": ("uk", "UA"), "ru": ("ru", "RU")}
    hl, gl = lang_map.get(query.language, ("en", "US"))
    return (
        f"https://news.google.com/rss/search"
        f"?q={encoded_query}+when:1h"
        f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    )
```

The `when:1h` parameter limits results to the last hour, ensuring freshness.

#### Behavior
1. All queries are fetched **concurrently** using `asyncio.gather()`. Each query is wrapped in a safe handler so one timeout or failure doesn't block others -- total fetch time is the time of the slowest query, not the sum of all.
2. For each query in `config.sources.google_news.queries`:
   - Build the RSS URL
   - Fetch and parse with `feedparser`
   - Extract articles same as RSS fetcher
   - Set `source_type = "google_news"`, `source_name = f"GoogleNews:{query.query}"`
3. Google News entries often link to the original source article -- extract the actual URL from the redirect if possible
4. Handle HTTP 429 (rate limited) by backing off

#### Google News Redirect Resolution
Google News RSS links are redirects (`https://news.google.com/rss/articles/...`). To get the actual article URL:
- Option A: Follow the redirect (adds latency but gets real URL)
- Option B: Use the link as-is (faster, works for dedup purposes)

Recommendation: Use Option B (link as-is) for speed. The dedup layer handles URL-based dedup, and Google News URLs are unique per article.

### 2.5 Telegram Fetcher (`sentinel/fetchers/telegram.py`)

Listens to configured Telegram channels for new messages using `telethon`.

#### Architecture
Unlike other fetchers, Telegram works via a persistent connection. The Telegram fetcher:
1. On startup: connects to Telegram, joins/monitors configured channels
2. Runs a background listener that buffers incoming messages
3. On `fetch()` call: returns and clears the buffer

```python
class TelegramFetcher(BaseFetcher):
    def __init__(self, config):
        super().__init__(config)
        self.buffer: list[Article] = []
        self.client: TelegramClient | None = None
        self._running = False

    async def start(self):
        """Start the Telegram client and message listener."""
        self.client = TelegramClient(
            session=self.config.sources.telegram.session_name,
            api_id=self.config.sources.telegram.api_id,
            api_hash=self.config.sources.telegram.api_hash,
        )
        await self.client.start()

        # Register handler for new messages in monitored channels
        channel_ids = [ch.channel_id for ch in self.config.sources.telegram.channels]

        @self.client.on(events.NewMessage(chats=channel_ids))
        async def handler(event):
            article = self._message_to_article(event.message)
            if article:
                self.buffer.append(article)

        self._running = True

    async def fetch(self) -> list[Article]:
        """Return buffered messages and clear buffer."""
        articles = self.buffer.copy()
        self.buffer.clear()
        return articles

    async def stop(self):
        """Disconnect from Telegram."""
        if self.client:
            await self.client.disconnect()
        self._running = False
```

#### Message to Article Mapping
- `title` = first 200 chars of message text
- `summary` = full message text (up to 500 chars)
- `source_url` = construct from channel and message ID: `https://t.me/{channel}/{msg_id}`
- `language` = from channel config
- `source_name` = channel name from config
- `published_at` = message date (UTC)
- `raw_metadata` = `{"channel_id": ..., "message_id": ..., "views": ..., "forwards": ...}`

#### First-Time Authentication
Telegram requires phone number verification on first run. The session file persists the auth so subsequent runs don't need it. Document this in [api-setup.md](api-setup.md).

#### Handling Disabled Telegram
If `config.sources.telegram.enabled` is `false`, the Telegram fetcher should not start the client. The `fetch()` method should return an empty list.

## Error Handling (All Fetchers)

| Error | Handling |
|---|---|
| Network timeout | Log warning, return empty list for that source |
| HTTP 429 (rate limited) | Log warning, skip this cycle for that source |
| HTTP 5xx | Log warning, return empty list |
| Malformed XML/JSON | Log error with response snippet, return empty list |
| Connection refused | Log error, return empty list |
| Telegram disconnected | Log error, attempt reconnect on next cycle |

Errors in one source must never prevent other sources from being polled.

## Acceptance Tests

### test_rss.py
1. `test_parse_valid_rss` -- parse a sample RSS XML file from fixtures, verify Article fields
2. `test_handle_missing_summary` -- entry without `<summary>` produces Article with empty summary
3. `test_handle_missing_date` -- entry without `<pubDate>` uses current time
4. `test_handle_malformed_xml` -- returns empty list, logs error
5. `test_conditional_get_304` -- server returns 304 Not Modified, returns empty list (no new articles)
6. `test_multiple_feeds` -- polls 3 feeds, returns combined articles
7. `test_disabled_feed_skipped` -- feed with `enabled: false` not polled
8. `test_timeout_handling` -- request timeout returns empty list for that feed
9. `test_html_stripped_from_summary` -- HTML tags removed from summary text
10. `test_concurrent_fetch` -- multiple feeds fetched concurrently via asyncio.gather
11. `test_max_priority_filters_sources` -- `fetch(max_priority=1)` only fetches priority-1 sources
12. `test_max_priority_none_fetches_all` -- `fetch()` without max_priority fetches all sources

### test_gdelt.py
1. `test_parse_valid_response` -- parse sample GDELT JSON, verify Article fields
2. `test_query_construction` -- verify query string built correctly from config
3. `test_date_parsing` -- GDELT `seendate` format parsed correctly
4. `test_empty_response` -- no articles returned, returns empty list
5. `test_network_error` -- connection error returns empty list
6. `test_language_mapping` -- GDELT language names mapped to ISO codes

### test_google_news.py
1. `test_url_construction` -- verify feed URL built correctly for each language
2. `test_parse_results` -- parse Google News RSS entries
3. `test_polish_query` -- Polish-language query URL constructed correctly
4. `test_rate_limit_handling` -- HTTP 429 handled gracefully
5. `test_concurrent_fetch` -- multiple queries fetched concurrently via asyncio.gather

### test_telegram.py
1. `test_message_to_article` -- Telegram message converted to Article correctly
2. `test_buffer_cleared_on_fetch` -- buffer emptied after `fetch()` call
3. `test_disabled_telegram` -- returns empty list when disabled
4. `test_long_message_truncated` -- message longer than 500 chars truncated in summary

## Dependencies Added

```
httpx>=0.27
feedparser>=6.0
telethon>=1.36
rapidfuzz>=3.0
```
