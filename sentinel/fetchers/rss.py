import calendar
import html.parser
import time
from datetime import datetime, timezone

import feedparser
import httpx

from sentinel.config import SentinelConfig
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import Article


class _HTMLStripper(html.parser.HTMLParser):
    """Simple HTML tag stripper using stdlib html.parser."""

    def __init__(self):
        super().__init__()
        self.reset()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces)


def strip_html(text: str) -> str:
    """Remove HTML tags from text, returning plain text."""
    stripper = _HTMLStripper()
    try:
        stripper.feed(text)
        return stripper.get_text()
    except Exception:
        return text


class RSSFetcher(BaseFetcher):
    """Polls all RSS feeds defined in config.sources.rss where enabled is true."""

    def __init__(self, config: SentinelConfig):
        super().__init__(config)
        # In-memory cache for conditional GET headers, keyed by source URL string
        self._etag_cache: dict[str, str] = {}
        self._last_modified_cache: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "rss"

    def is_enabled(self) -> bool:
        return len(self.config.sources.rss) > 0

    async def fetch(self) -> list[Article]:
        """Fetch articles from all enabled RSS sources."""
        all_articles: list[Article] = []

        for source in self.config.sources.rss:
            if not source.enabled:
                continue

            try:
                articles = await self._fetch_source(source)
                all_articles.extend(articles)
            except Exception as exc:
                self.logger.error(
                    "Failed to fetch RSS source %s: %s", source.name, exc
                )

        return all_articles

    async def _fetch_source(self, source) -> list[Article]:
        """Fetch and parse a single RSS source."""
        url = str(source.url)

        headers = {
            "User-Agent": "ProjectSentinel/1.0 (military-alert-monitor)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }

        etag = self._etag_cache.get(url)
        last_modified = self._last_modified_cache.get(url)
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)

        if response.status_code == 304:
            self.logger.debug("RSS source %s: not modified (304)", source.name)
            return []

        if response.status_code == 429:
            self.logger.warning(
                "RSS source %s: rate limited (429)", source.name
            )
            return []

        if response.status_code >= 500:
            self.logger.warning(
                "RSS source %s: server error (%d)", source.name, response.status_code
            )
            return []

        response.raise_for_status()

        # Update conditional GET cache
        if "etag" in response.headers:
            self._etag_cache[url] = response.headers["etag"]
        if "last-modified" in response.headers:
            self._last_modified_cache[url] = response.headers["last-modified"]

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            self.logger.error(
                "RSS source %s: malformed XML: %s",
                source.name,
                str(getattr(feed, "bozo_exception", "unknown error")),
            )
            return []

        articles: list[Article] = []
        now = datetime.now(timezone.utc)

        for entry in feed.entries:
            try:
                article = self._entry_to_article(entry, source, now)
                articles.append(article)
            except Exception as exc:
                self.logger.warning(
                    "RSS source %s: failed to parse entry: %s",
                    source.name,
                    exc,
                )

        self.logger.info(
            "RSS source %s: fetched %d articles", source.name, len(articles)
        )
        return articles

    def _entry_to_article(self, entry, source, now: datetime) -> Article:
        """Convert a feedparser entry to an Article."""
        title = entry.get("title", "")
        link = entry.get("link", "")

        # Parse published date
        published_at = self._parse_date(entry) or now

        # Extract and clean summary
        summary_raw = entry.get("summary", "")
        summary = strip_html(summary_raw) if summary_raw else ""

        # Build raw_metadata from any extra fields
        raw_metadata = {}
        if hasattr(entry, "tags"):
            raw_metadata["tags"] = [
                tag.get("term", "") for tag in entry.tags
            ]

        return Article(
            source_name=source.name,
            source_url=link,
            source_type="rss",
            title=title,
            summary=summary,
            language=source.language,
            published_at=published_at,
            fetched_at=now,
            raw_metadata=raw_metadata,
        )

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        """Parse published or updated date from a feedparser entry."""
        for attr in ("published_parsed", "updated_parsed"):
            parsed = entry.get(attr)
            if parsed:
                try:
                    ts = calendar.timegm(parsed)
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (ValueError, OverflowError, TypeError):
                    continue
        return None
