"""Lint of the tracked keyword lists: no high keyword is cancelled by an exclude keyword.

An article with only a high keyword (no critical one) is dropped when an exclude keyword
matches, so a high keyword that itself contains an exclude keyword can never pass on its
own. Critical keywords are not checked: the filter never excludes a critical match.
"""

from datetime import UTC, datetime

import pytest

from sentinel.models import Article
from sentinel.processing.keyword_filter import KeywordFilter

# (language, high keyword) pairs that an exclude keyword still cancels. Each one is an
# open owner item in TODO.md ("Findings from the 2026-10-16 refactor audit").
KNOWN_CONFLICTS = frozenset({("pl", "podejrzane manewry")})

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _title_only(keyword: str, language: str) -> Article:
    return Article(
        source_name="KeywordLint",
        source_url="https://example.test/lint",
        source_type="rss",
        title=keyword,
        summary="",
        language=language,
        published_at=NOW,
        fetched_at=NOW,
    )


def test_live_keywords_not_cancelled_by_excludes(prod_config):
    keyword_filter = KeywordFilter(prod_config)
    keyword_lists = prod_config.monitoring.keywords
    assert keyword_lists, "the tracked config has no keyword lists"

    cancelled = []
    for language, keyword_set in keyword_lists.items():
        assert keyword_set.high, f"no high keywords for {language}"
        for keyword in keyword_set.high:
            if (language, keyword) in KNOWN_CONFLICTS:
                continue
            result = keyword_filter.matches(_title_only(keyword, language))
            if result is None or result["level"] != "high" or keyword not in result["matched_keywords"]:
                cancelled.append((language, keyword, keyword_filter.diagnose(_title_only(keyword, language))))
    assert cancelled == []


@pytest.mark.parametrize("language,keyword", sorted(KNOWN_CONFLICTS))
def test_known_conflicts_are_still_live(prod_config, language, keyword):
    """A resolved conflict must leave KNOWN_CONFLICTS (and the owner item in TODO.md)."""
    assert keyword in prod_config.monitoring.keywords[language].high
    diagnosis = KeywordFilter(prod_config).diagnose(_title_only(keyword, language))
    assert keyword in diagnosis["high"] and diagnosis["excluded_by"]
    assert diagnosis["passed"] is False
