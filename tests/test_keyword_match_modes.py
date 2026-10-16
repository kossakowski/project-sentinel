"""Keyword match modes: whole-word exclude keywords, case-sensitive GRU.

Exclude keywords match whole words in every language. Critical and high keywords keep
substring matching for pl/uk/ru and word-boundary matching otherwise, except the high
acronyms GRU / ГРУ, which match only as a whole word in that exact case.
"""

from datetime import UTC, datetime

import pytest

from sentinel.config import SentinelConfig
from sentinel.models import Article
from sentinel.processing.keyword_filter import KeywordFilter

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _article(title: str, language: str, summary: str = "") -> Article:
    return Article(
        source_name="KeywordModes",
        source_url="https://example.test/news/1",
        source_type="rss",
        title=title,
        summary=summary,
        language=language,
        published_at=NOW,
        fetched_at=NOW,
    )


@pytest.fixture
def live_filter(prod_config) -> KeywordFilter:
    """The filter on the tracked keyword and exclude lists."""
    return KeywordFilter(prod_config)


# ---------------------------------------------------------------------------
# Exclude keywords: whole words in every language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Rosyjskie drony nad granicą z Polską",
        "Kaliningrad: rosyjskie wojska w gotowości",
        "Chmura dymu setki kilometrów od granicy. Rosja ogłosiła alarm – PolsatNews.pl",
        "Rosja: ukraińskie drony uderzyły w obiekty od granicy",
        "Nagranie: dron nad lotniskiem w Rzeszowie",
        "Wojsko ogranicza ruch po incydencie z dronem",
        "Zagraniczny dron spadł pod Lublinem",
    ],
)
def test_exclude_gra_does_not_drop_granicy_or_kaliningrad(live_filter, title):
    result = live_filter.matches(_article(title, "pl"))
    assert result is not None, live_filter.diagnose(_article(title, "pl"))
    assert result["level"] == "high"
    assert live_filter.diagnose(_article(title, "pl"))["excluded_by"] == []


@pytest.mark.parametrize(
    "title,exclude",
    [
        ("Nowa gra o dronach trafiła do sklepów", "gra"),
        ("Film o dronach nad Polską", "film"),
        ("Manewry z udziałem dronów na poligonie", "manewry"),
    ],
)
def test_whole_word_exclude_still_drops_a_high_match(live_filter, title, exclude):
    diagnosis = live_filter.diagnose(_article(title, "pl"))
    assert diagnosis["high"] and exclude in diagnosis["excluded_by"]
    assert live_filter.matches(_article(title, "pl")) is None


def test_english_excludes_match_whole_words_in_polish_text(live_filter):
    # "film" (an English exclude also applied to Polish articles) is not a word in "Filmik".
    article = _article("Filmik: rosyjski dron nad Rzeszowem", "pl")
    assert live_filter.diagnose(article)["excluded_by"] == []
    assert live_filter.matches(article)["level"] == "high"


def test_critical_match_still_ignores_excludes(live_filter):
    result = live_filter.matches(_article("Nalot na Rzeszów podczas ćwiczenia, nowa gra Rosji", "pl"))
    assert result is not None and result["level"] == "critical"


def test_slavic_critical_and_high_keep_substring_matching(live_filter):
    critical = live_filter.matches(_article("Seria nalotów na przygraniczne miasta", "pl"))
    assert critical["level"] == "critical" and "nalot" in critical["matched_keywords"]
    high = live_filter.matches(_article("Drony nad Lubelszczyzną", "pl"))
    assert high["level"] == "high" and "dron" in high["matched_keywords"]


def test_exclude_whole_word_in_cyrillic_languages(sample_config_dict):
    config = dict(sample_config_dict)
    config["monitoring"] = {
        **config["monitoring"],
        "keywords": {"uk": {"critical": ["вторгнення"], "high": ["дрони"]}},
        "exclude_keywords": {"uk": ["гра"]},
    }
    keyword_filter = KeywordFilter(SentinelConfig(**config))
    # "гра" (game) inside "графік" is not the word "гра".
    passed = keyword_filter.matches(_article("Дрони над Києвом: графік відключень", "uk"))
    assert passed is not None and passed["level"] == "high"
    assert keyword_filter.matches(_article("Нова гра про дрони", "uk")) is None


# ---------------------------------------------------------------------------
# GRU / ГРУ: whole word, exact case, original-case text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,language",
    [
        ("Grupa turystów zatrzymana na przejściu", "pl"),
        ("Spotkanie przywódców 12 grudnia", "pl"),
        ("Gruzja zamyka granicę z Rosją", "pl"),
        ("Gru and the minions return to cinemas", "en"),
        ("Група волонтерів зібрала кошти", "uk"),
        ("Группа туристов застряла на границе", "ru"),
        ("Груз доставлен в порт", "ru"),
    ],
)
def test_gru_does_not_match_grupa(live_filter, title, language):
    diagnosis = live_filter.diagnose(_article(title, language))
    assert "GRU" not in diagnosis["high"] and "ГРУ" not in diagnosis["high"]


@pytest.mark.parametrize(
    "title,language,keyword",
    [
        ("Za sabotażem stoi rosyjskie GRU", "pl", "GRU"),
        ("GRU officers charged in Poland", "en", "GRU"),
        ("Britain sanctions GRU's unit 29155", "en", "GRU"),
        ("Агенти ГРУ затримані в Польщі", "uk", "ГРУ"),
        ("ГРУ готовило поджоги в Европе", "ru", "ГРУ"),
    ],
)
def test_gru_matches_as_an_exact_case_whole_word(live_filter, title, language, keyword):
    result = live_filter.matches(_article(title, language))
    assert result is not None and keyword in result["matched_keywords"]


def test_gru_is_checked_against_the_original_case_text(live_filter):
    # Lower-case "gru" is no match, in the title or the summary; upper-case GRU in the summary is.
    assert "GRU" not in live_filter.diagnose(_article("gru", "pl", summary="Gru w grudniu"))["high"]
    found = live_filter.matches(_article("Zatrzymano dwóch mężczyzn", "pl", summary="Pracowali dla GRU."))
    assert found is not None and found["matched_keywords"] == ["GRU"]


def test_matches_and_diagnose_agree(live_filter):
    for title in ("Kaliningrad: alarm", "Nowa gra o dronach", "Grupa GRU", "Pogoda na weekend"):
        article = _article(title, "pl")
        assert (live_filter.matches(article) is not None) == live_filter.diagnose(article)["passed"]
