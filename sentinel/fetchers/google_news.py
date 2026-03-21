import urllib.parse
from datetime import datetime, timezone

import feedparser
import httpx

from sentinel.config import GoogleNewsQuery, SentinelConfig
from sentinel.fetchers.base import BaseFetcher
from sentinel.fetchers.rss import strip_html
from sentinel.models import Article

# Language to (hl, gl) mapping for Google News RSS
LANG_MAP = {
    "en": ("en", "US"),
    "pl": ("pl", "PL"),
    "uk": ("uk", "UA"),
    "ru": ("ru", "RU"),
}


class GoogleNewsFetcher(BaseFetcher):
    """Generates Google News RSS URLs from configured queries and polls them."""

    def __init__(self, config: SentinelConfig):
        super().__init__(config)

    @property
    def name(self) -> str:
        return "google_news"

    def is_enabled(self) -> bool:
        return self.config.sources.google_news.enabled

    def build_feed_url(self, query: GoogleNewsQuery) -> str:
        """Build Google News RSS URL from a query config."""
        encoded_query = urllib.parse.quote(query.query)
        hl, gl = LANG_MAP.get(query.language, ("en", "US"))
        return (
            f"https://news.google.com/rss/search"
            f"?q={encoded_query}+when:1h"
            f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
        )

    async def fetch(self) -> list[Article]:
        """Fetch articles from all configured Google News queries."""
        if not self.is_enabled():
            return []

        all_articles: list[Article] = []

        for query in self.config.sources.google_news.queries:
            try:
                articles = await self._fetch_query(query)
                all_articles.extend(articles)
            except Exception as exc:
                self.logger.error(
                    "Google News query '%s' failed: %s", query.query, exc
                )

        return all_articles

    async def _fetch_query(self, query: GoogleNewsQuery) -> list[Article]:
        """Fetch and parse results for a single Google News query."""
        url = self.build_feed_url(query)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                url,
                timeout=30.0,
                headers={
                    "User-Agent": "ProjectSentinel/1.0 (military-alert-monitor)",
                    "Accept": "application/rss+xml, application/xml, text/xml",
                },
            )

        if response.status_code == 429:
            self.logger.warning(
                "Google News query '%s': rate limited (429)", query.query
            )
            return []

        if response.status_code >= 500:
            self.logger.warning(
                "Google News query '%s': server error (%d)",
                query.query,
                response.status_code,
            )
            return []

        response.raise_for_status()

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            self.logger.error(
                "Google News query '%s': malformed XML", query.query
            )
            return []

        now = datetime.now(timezone.utc)
        articles: list[Article] = []

        for entry in feed.entries:
            try:
                article = self._entry_to_article(entry, query, now)
                articles.append(article)
            except Exception as exc:
                self.logger.warning(
                    "Google News query '%s': failed to parse entry: %s",
                    query.query,
                    exc,
                )

        self.logger.info(
            "Google News query '%s': fetched %d articles",
            query.query,
            len(articles),
        )
        return articles

    @staticmethod
    def _entry_to_article(
        entry, query: GoogleNewsQuery, now: datetime
    ) -> Article:
        """Convert a feedparser entry to an Article."""
        import calendar

        title = entry.get("title", "")
        # Use the Google News link as-is (Option B from spec)
        link = entry.get("link", "")

        # Parse published date
        published_at = None
        for attr in ("published_parsed", "updated_parsed"):
            parsed = entry.get(attr)
            if parsed:
                try:
                    ts = calendar.timegm(parsed)
                    published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                    break
                except (ValueError, OverflowError, TypeError):
                    continue
        if published_at is None:
            published_at = now

        summary_raw = entry.get("summary", "")
        summary = strip_html(summary_raw) if summary_raw else ""

        return Article(
            source_name=f"GoogleNews:{query.query}",
            source_url=link,
            source_type="google_news",
            title=title,
            summary=summary,
            language=query.language,
            published_at=published_at,
            fetched_at=now,
        )
