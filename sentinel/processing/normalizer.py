"""Article normalizer -- cleans and standardizes fetcher output."""

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sentinel.models import Article


# Tracking query parameters to strip from URLs
_TRACKING_PARAMS = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "fbclid",
    "gclid",
})

# Language name -> ISO 639-1 code
_LANGUAGE_MAP = {
    "english": "en",
    "polish": "pl",
    "ukrainian": "uk",
    "russian": "ru",
    "german": "de",
    "french": "fr",
    "lithuanian": "lt",
    "latvian": "lv",
    "estonian": "et",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class Normalizer:
    """Converts raw fetcher output into clean, consistent Article objects."""

    def normalize(self, article: Article) -> Article:
        """Return a new Article with normalized fields."""
        title = self._clean_text(article.title, max_length=500)
        summary = self._clean_text(article.summary, max_length=1000)
        if not summary:
            summary = title

        source_url = self._normalize_url(article.source_url)
        published_at = self._normalize_timestamp(
            article.published_at, article.fetched_at
        )
        language = self._normalize_language(article.language)

        return Article(
            source_name=article.source_name,
            source_url=source_url,
            source_type=article.source_type,
            title=title,
            summary=summary,
            language=language,
            published_at=published_at,
            fetched_at=article.fetched_at,
            raw_metadata=dict(article.raw_metadata),
            id=article.id,
        )

    def normalize_batch(self, articles: list[Article]) -> list[Article]:
        """Normalize a list of articles."""
        return [self.normalize(a) for a in articles]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(text: str, max_length: int) -> str:
        """Strip whitespace, decode HTML entities, remove tags, truncate."""
        if not text:
            return ""
        # Decode HTML entities
        cleaned = html.unescape(text)
        # Strip HTML tags
        cleaned = _HTML_TAG_RE.sub("", cleaned)
        # Strip leading/trailing whitespace
        cleaned = cleaned.strip()
        # Collapse multiple whitespace into single space
        cleaned = _WHITESPACE_RE.sub(" ", cleaned)
        # Truncate
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "..."
        return cleaned

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Strip tracking params, www prefix, trailing slashes; lowercase domain."""
        parsed = urlparse(url)

        # Lowercase domain and remove www. prefix
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Strip tracking query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        filtered_params = {
            k: v for k, v in query_params.items() if k.lower() not in _TRACKING_PARAMS
        }
        new_query = urlencode(filtered_params, doseq=True)

        # Strip trailing slash from path
        path = parsed.path.rstrip("/")

        normalized = urlunparse((
            parsed.scheme,
            netloc,
            path,
            parsed.params,
            new_query,
            "",  # drop fragment
        ))
        return normalized

    @staticmethod
    def _normalize_timestamp(
        published_at: datetime | None, fetched_at: datetime
    ) -> datetime:
        """Ensure UTC, cap future timestamps, fallback to fetched_at."""
        if published_at is None:
            return fetched_at

        # Ensure timezone-aware (assume UTC if naive)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        if published_at > now:
            return now

        return published_at

    @staticmethod
    def _normalize_language(language: str) -> str:
        """Map full language names to ISO codes."""
        lowered = language.lower().strip()
        return _LANGUAGE_MAP.get(lowered, language)
