"""Keyword filter -- matches articles against military/conflict keywords."""

import logging
import re

from sentinel.config import SentinelConfig
from sentinel.models import Article

# Languages that use substring matching (Slavic inflected languages)
_SLAVIC_LANGUAGES = frozenset({"pl", "uk", "ru"})


class KeywordFilter:
    """Filters articles to only those matching military/conflict keywords."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("sentinel.keyword_filter")

    def matches(self, article: Article) -> dict | None:
        """Check if article matches any keywords.

        Returns match info dict if matched, None if not matched.
        """
        lang = article.language
        keywords_cfg = self.config.monitoring.keywords

        # Determine which keyword sets to check
        if lang in keywords_cfg:
            keyword_set = keywords_cfg[lang]
        else:
            # Fallback to English for unknown languages
            keyword_set = keywords_cfg.get("en")
            if keyword_set is None:
                return None
            lang = "en"

        searchable = f"{article.title} {article.summary}".lower()

        # Check critical keywords
        critical_matches = self._find_matches(
            searchable, keyword_set.critical, lang
        )

        # Check high keywords
        high_matches = self._find_matches(
            searchable, keyword_set.high, lang
        )

        # Check exclude keywords (only if no critical match)
        if not critical_matches:
            exclude_lists = self.config.monitoring.exclude_keywords
            exclude_kws = exclude_lists.get(lang, [])
            # Also check English excludes for non-English articles
            if lang != "en":
                exclude_kws = exclude_kws + exclude_lists.get("en", [])

            has_exclude = self._find_matches(searchable, exclude_kws, lang)
            if has_exclude:
                self.logger.debug(
                    "Excluded by keyword: %s (matched: %s)",
                    article.title[:60],
                    has_exclude,
                )
                return None

        if critical_matches:
            return {
                "level": "critical",
                "matched_keywords": critical_matches,
                "language_matched": lang,
            }
        elif high_matches:
            return {
                "level": "high",
                "matched_keywords": high_matches,
                "language_matched": lang,
            }

        return None

    def filter_batch(self, articles: list[Article]) -> list[Article]:
        """Filter articles to only those matching keywords.

        Annotates matched articles with keyword info in raw_metadata.
        """
        result: list[Article] = []
        for article in articles:
            match_info = self.matches(article)
            if match_info is not None:
                article.raw_metadata["keyword_match"] = match_info
                result.append(article)
        return result

    def diagnose(self, article: Article) -> dict:
        """Return detailed keyword filter analysis for diagnostic purposes.

        Always returns a dict with keys: passed, critical, high, excluded_by.
        """
        lang = article.language
        keywords_cfg = self.config.monitoring.keywords

        if lang in keywords_cfg:
            keyword_set = keywords_cfg[lang]
        else:
            keyword_set = keywords_cfg.get("en")
            if keyword_set is None:
                return {
                    "passed": False,
                    "critical": [],
                    "high": [],
                    "excluded_by": [],
                }
            lang = "en"

        searchable = f"{article.title} {article.summary}".lower()

        critical = self._find_matches(searchable, keyword_set.critical, lang)
        high = self._find_matches(searchable, keyword_set.high, lang)

        excluded_by: list[str] = []
        if not critical:
            exclude_lists = self.config.monitoring.exclude_keywords
            exclude_kws = exclude_lists.get(lang, [])
            if lang != "en":
                exclude_kws = exclude_kws + exclude_lists.get("en", [])
            excluded_by = self._find_matches(searchable, exclude_kws, lang)

        passed = bool(critical or (high and not excluded_by))

        return {
            "passed": passed,
            "critical": critical,
            "high": high,
            "excluded_by": excluded_by,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_matches(
        text: str, keywords: list[str], language: str
    ) -> list[str]:
        """Find all matching keywords in text.

        Uses substring matching for Slavic languages and word-boundary
        matching for English and other languages.
        """
        matched: list[str] = []
        for keyword in keywords:
            kw_lower = keyword.lower()
            if language in _SLAVIC_LANGUAGES:
                # Substring match for inflected Slavic languages
                if kw_lower in text:
                    matched.append(keyword)
            else:
                # Word-boundary match for English and other languages
                pattern = r"\b" + re.escape(kw_lower) + r"\b"
                if re.search(pattern, text):
                    matched.append(keyword)
        return matched
