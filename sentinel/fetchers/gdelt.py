from datetime import datetime, timezone

import httpx

from sentinel.config import SentinelConfig
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import Article

# GDELT DOC 2.0 API endpoint
GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Mapping from GDELT full language names to ISO 639-1 codes
GDELT_LANGUAGE_MAP = {
    "English": "en",
    "Polish": "pl",
    "Ukrainian": "uk",
    "Russian": "ru",
    "German": "de",
    "French": "fr",
    "Spanish": "es",
    "Italian": "it",
    "Portuguese": "pt",
    "Dutch": "nl",
    "Swedish": "sv",
    "Norwegian": "no",
    "Danish": "da",
    "Finnish": "fi",
    "Czech": "cs",
    "Slovak": "sk",
    "Hungarian": "hu",
    "Romanian": "ro",
    "Bulgarian": "bg",
    "Croatian": "hr",
    "Serbian": "sr",
    "Slovenian": "sl",
    "Lithuanian": "lt",
    "Latvian": "lv",
    "Estonian": "et",
    "Turkish": "tr",
    "Arabic": "ar",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
}

# ISO 3166-1 alpha-2 to FIPS 10-4 country codes used by GDELT
FIPS_MAP = {
    "PL": "PL",
    "LT": "LH",
    "LV": "LG",
    "EE": "EN",
}


class GDELTFetcher(BaseFetcher):
    """Queries the GDELT DOC 2.0 API for matching articles."""

    def __init__(self, config: SentinelConfig):
        super().__init__(config)

    @property
    def name(self) -> str:
        return "gdelt"

    def is_enabled(self) -> bool:
        return self.config.sources.gdelt.enabled

    def build_query(self) -> str:
        """Build GDELT query string from config."""
        parts = []

        # Theme filter
        themes = self.config.sources.gdelt.themes
        if themes:
            theme_query = " OR ".join(f"theme:{t}" for t in themes)
            parts.append(f"({theme_query})")

        # Country filter (target countries)
        countries = self.config.monitoring.target_countries
        if countries:
            country_codes = [c["code"] for c in countries]
            fips_codes = [FIPS_MAP.get(c, c) for c in country_codes]
            country_query = " OR ".join(
                f"sourcecountry:{c}" for c in fips_codes
            )
            parts.append(f"({country_query})")

        return " ".join(parts)

    async def fetch(self) -> list[Article]:
        """Fetch articles from GDELT DOC 2.0 API."""
        if not self.is_enabled():
            return []

        try:
            return await self._do_fetch()
        except Exception as exc:
            self.logger.error("GDELT fetch failed: %s", exc)
            return []

    async def _do_fetch(self) -> list[Article]:
        """Execute the GDELT API request and parse results."""
        query = self.build_query()
        if not query:
            self.logger.warning("GDELT: empty query, skipping")
            return []

        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": 250,
            "format": "json",
            "TIMESPAN": f"{self.config.sources.gdelt.update_interval_minutes}min",
            "sort": "DateDesc",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                GDELT_API_URL,
                params=params,
                timeout=30.0,
                headers={
                    "User-Agent": "ProjectSentinel/1.0 (military-alert-monitor)",
                },
            )

        if response.status_code == 429:
            self.logger.warning("GDELT: rate limited (429)")
            return []

        if response.status_code >= 500:
            self.logger.warning(
                "GDELT: server error (%d)", response.status_code
            )
            return []

        response.raise_for_status()

        data = response.json()
        raw_articles = data.get("articles", [])

        if not raw_articles:
            self.logger.debug("GDELT: no articles returned")
            return []

        now = datetime.now(timezone.utc)
        articles: list[Article] = []

        for raw in raw_articles:
            try:
                article = self._parse_article(raw, now)
                articles.append(article)
            except Exception as exc:
                self.logger.warning("GDELT: failed to parse article: %s", exc)

        self.logger.info("GDELT: fetched %d articles", len(articles))
        return articles

    def _parse_article(self, raw: dict, now: datetime) -> Article:
        """Convert a GDELT article dict to an Article model."""
        url = raw.get("url", "")
        title = raw.get("title", "")
        domain = raw.get("domain", "unknown")
        language_name = raw.get("language", "English")
        seendate = raw.get("seendate", "")

        published_at = self._parse_seendate(seendate) if seendate else now
        language = GDELT_LANGUAGE_MAP.get(language_name, "en")

        return Article(
            source_name=f"GDELT:{domain}",
            source_url=url,
            source_type="gdelt",
            title=title,
            summary="",
            language=language,
            published_at=published_at,
            fetched_at=now,
            raw_metadata=raw,
        )

    @staticmethod
    def _parse_seendate(seendate: str) -> datetime:
        """Parse GDELT seendate format: 20250910T034800Z."""
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
