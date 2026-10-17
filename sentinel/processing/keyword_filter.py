"""Keyword filter -- matches articles against military/conflict keywords."""

import logging
import re
from functools import lru_cache

from sentinel.config import SentinelConfig
from sentinel.models import Article

# Languages whose critical and high keywords use substring matching (inflected
# Slavic languages). Exclude keywords always match whole words.
_SLAVIC_LANGUAGES = frozenset({"pl", "uk", "ru"})

# High keywords that match only as a whole word in this exact case, checked
# against the original-case text: the acronym GRU would otherwise match inside
# ordinary words such as "grupa", "grudnia" or "группа".
_CASE_SENSITIVE_HIGH_KEYWORDS = frozenset({"GRU", "ГРУ"})


@lru_cache(maxsize=2048)
def _whole_word(keyword: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(keyword) + r"\b")


class KeywordFilter:
    """Filters articles to only those matching military/conflict keywords."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("sentinel.keyword_filter")
        self._bypass_sources = self._build_bypass_sources()

    def _build_bypass_sources(self) -> frozenset[str]:
        """Build set of source names that bypass keyword filtering."""
        names: set[str] = set()
        for src in self.config.sources.rss:
            if src.keyword_bypass:
                names.add(src.name)
        if self.config.sources.telegram.enabled:
            for ch in self.config.sources.telegram.channels:
                if ch.keyword_bypass:
                    names.add(ch.name)
        return frozenset(names)

    def matches(self, article: Article) -> dict | None:
        """Check if article matches any keywords.

        Returns match info dict if matched, None if not matched.
        """
        evaluation = self._evaluate(article)
        if evaluation is None:
            return None
        lang, critical_matches, high_matches, excluded_by = evaluation

        # Exclude keywords apply only when there is no critical match
        if excluded_by:
            self.logger.debug(
                "Excluded by keyword: %s (matched: %s)",
                article.title[:60],
                excluded_by,
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

        Articles from keyword_bypass sources skip keyword matching and go
        straight to the classifier.  All others require a keyword match.
        Annotates matched articles with keyword info in raw_metadata.
        """
        result: list[Article] = []
        for article in articles:
            if article.source_name in self._bypass_sources:
                article.raw_metadata["keyword_match"] = {
                    "level": "bypass",
                    "matched_keywords": [],
                    "language_matched": article.language,
                }
                result.append(article)
                continue
            match_info = self.matches(article)
            if match_info is not None:
                article.raw_metadata["keyword_match"] = match_info
                result.append(article)
        return result

    def diagnose(self, article: Article) -> dict:
        """Return detailed keyword filter analysis for diagnostic purposes.

        Always returns a dict with keys: passed, critical, high, excluded_by, bypass.
        """
        if article.source_name in self._bypass_sources:
            return {
                "passed": True,
                "critical": [],
                "high": [],
                "excluded_by": [],
                "bypass": True,
            }

        evaluation = self._evaluate(article)
        if evaluation is None:
            return {
                "passed": False,
                "critical": [],
                "high": [],
                "excluded_by": [],
            }
        _, critical, high, excluded_by = evaluation

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

    def _evaluate(self, article: Article) -> tuple[str, list[str], list[str], list[str]] | None:
        """Match ``article`` against its language's keyword lists.

        Returns ``(language, critical, high, excluded_by)``, or None when neither the
        article's language nor English has keywords. Exclude keywords are checked
        only when no critical keyword matched (``excluded_by`` is empty otherwise).
        """
        lang = article.language
        keywords_cfg = self.config.monitoring.keywords

        if lang in keywords_cfg:
            keyword_set = keywords_cfg[lang]
        else:
            # Fallback to English for unknown languages
            keyword_set = keywords_cfg.get("en")
            if keyword_set is None:
                return None
            lang = "en"

        original = f"{article.title} {article.summary}"
        searchable = original.lower()

        critical = self._find_matches(searchable, keyword_set.critical, lang)
        high = self._find_matches(
            searchable, keyword_set.high, lang, exact_case=_CASE_SENSITIVE_HIGH_KEYWORDS, original_text=original
        )

        excluded_by: list[str] = []
        if not critical:
            exclude_lists = self.config.monitoring.exclude_keywords
            exclude_kws = exclude_lists.get(lang, [])
            # Also check English excludes for non-English articles
            if lang != "en":
                exclude_kws = exclude_kws + exclude_lists.get("en", [])
            excluded_by = self._find_exclude_matches(searchable, exclude_kws)

        return lang, critical, high, excluded_by

    @staticmethod
    def _find_matches(
        text: str,
        keywords: list[str],
        language: str,
        *,
        exact_case: frozenset[str] = frozenset(),
        original_text: str = "",
    ) -> list[str]:
        """Find the critical or high keywords that occur in ``text`` (lowercased).

        Uses substring matching for Slavic languages and word-boundary matching
        for English and other languages. A keyword in ``exact_case`` (the high
        list passes ``_CASE_SENSITIVE_HIGH_KEYWORDS``) matches only as a whole
        word in its exact case in ``original_text``.
        """
        matched: list[str] = []
        for keyword in keywords:
            if keyword in exact_case:
                if _whole_word(keyword).search(original_text):
                    matched.append(keyword)
                continue
            kw_lower = keyword.lower()
            if language in _SLAVIC_LANGUAGES:
                # Substring match for inflected Slavic languages
                if kw_lower in text:
                    matched.append(keyword)
            elif _whole_word(kw_lower).search(text):
                # Word-boundary match for English and other languages
                matched.append(keyword)
        return matched

    @staticmethod
    def _find_exclude_matches(text: str, keywords: list[str]) -> list[str]:
        """Find the exclude keywords that occur in ``text`` (lowercased) as whole words, in every language.

        A substring match would let a short exclude such as ``gra`` drop articles
        about ``granicy`` or ``Kaliningrad``.
        """
        return [keyword for keyword in keywords if _whole_word(keyword.lower()).search(text)]
