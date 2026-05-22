"""Tests for the content enrichment module."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentinel.models import Article
from sentinel.processing.enricher import ArticleEnricher


def _make_article(title: str, summary: str, source_type: str = "google_news",
                  source_name: str = "GoogleNews:test", url: str = "https://example.com") -> Article:
    return Article(
        source_name=source_name,
        source_url=url,
        source_type=source_type,
        title=title,
        summary=summary,
        language="pl",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )


# ------------------------------------------------------------------
# Heuristic gate tests
# ------------------------------------------------------------------

class TestIsGarbageSummary:
    """Test the heuristic gate for detecting summary ≈ title."""

    def test_exact_duplicate(self):
        a = _make_article("Breaking news headline", "Breaking news headline")
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_title_with_outlet_appended(self):
        a = _make_article(
            "Alarm w kraju NATO - Radio Zet",
            "Alarm w kraju NATO Radio Zet",
        )
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_google_news_dash_removed(self):
        a = _make_article(
            "Drony spadły na Łotwę! Smutne słowa dowódcy armii - MSN",
            "Drony spadły na Łotwę! Smutne słowa dowódcy armii MSN",
        )
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_google_news_real_example_1(self):
        a = _make_article(
            "Zawalone budynki, ludzie pod gruzami. Wśród rannych dzieci, dramatyczny atak Rosji - NewMedia24",
            "Zawalone budynki, ludzie pod gruzami. Wśród rannych dzieci, dramatyczny atak Rosji NewMedia24",
        )
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_google_news_real_example_english(self):
        a = _make_article(
            "Two drones from Russia crash in Latvia, army says - The Straits Times",
            "Two drones from Russia crash in Latvia, army says The Straits Times",
        )
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_real_summary_defence24(self):
        a = _make_article(
            "Dwa obce drony, które wleciały z Rosji, rozbiły się na Łotwie",
            "Dwa obce drony wleciały na Łotwę z Rosji i rozbiły się – podała w czwartek rano "
            "agencja Reutera, powołując się na siły zbrojne. Według publicznego nadawcy LSM "
            "jeden z dronów uderzył w skład ropy naftowej.",
            source_type="rss",
            source_name="Defence24",
        )
        assert ArticleEnricher.is_garbage_summary(a) is False

    def test_real_summary_onet(self):
        a = _make_article(
            "Alarm w Wilnie. Zamknięte zostało lotnisko, władze ewakuowane do schronów",
            "W Wilnie został ogłoszony alarm z powodu zagrożenia z powietrza. Nie kursuje "
            "transport publiczny, zamknięte jest lotnisko — informuje AFP.",
            source_type="rss",
            source_name="Onet Wiadomości",
        )
        assert ArticleEnricher.is_garbage_summary(a) is False

    def test_telegram_is_not_garbage(self):
        a = _make_article(
            "Уже 36 стран поддержали создание спецтрибунала против Путина",
            "Уже 36 стран поддержали создание спецтрибунала против Путина "
            "Совет Европы официально запускает в Гааге специальный трибунал "
            "по преступлению агрессии России против Украины. К инициативе "
            "присоединились Андорра, Австрия, Бельгия, Хорватия...",
            source_type="telegram",
            source_name="Ukrainian Air Force",
        )
        assert ArticleEnricher.is_garbage_summary(a) is False

    def test_empty_summary(self):
        a = _make_article("Some title", "")
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_short_rss_summary_that_partially_repeats(self):
        a = _make_article(
            "Alarm powietrzny na Litwie. Rządzący udali się do schronów",
            "Rządzący udali się do schronów.",
            source_type="rss",
            source_name="RMF24",
        )
        assert ArticleEnricher.is_garbage_summary(a) is True

    def test_different_content_entirely(self):
        a = _make_article(
            "NATO jets scramble as drone breaches Latvian airspace for 3rd day in a row",
            "Residents in affected areas were urged to remain indoors and seek shelter. "
            "The Latvian military confirmed the airspace violation around 02:30 local time.",
            source_type="rss",
            source_name="Kyiv Independent",
        )
        assert ArticleEnricher.is_garbage_summary(a) is False

    def test_clickbait_title_but_good_summary(self):
        a = _make_article(
            "Horror w kraju NATO! Dron eksplodował w centrum miasta!",
            "Na Łotwie, w mieście Daugavpils, dron typu Shahed-136 eksplodował na parkingu "
            "w pobliżu centrum handlowego. Odłamki uszkodziły 4 samochody, jedna osoba ranna.",
            source_type="rss",
            source_name="Fakt",
        )
        assert ArticleEnricher.is_garbage_summary(a) is False


# ------------------------------------------------------------------
# enrich_batch integration tests (mocked LLM + HTTP)
# ------------------------------------------------------------------

class TestEnrichBatch:

    @pytest.fixture
    def enricher(self):
        config = MagicMock()
        config.classification.model = "claude-haiku-4-5-20251001"
        return ArticleEnricher(config)

    def test_garbage_summary_article_gets_heuristic_flag(self, enricher):
        article = _make_article(
            "Alarm w kraju NATO - Radio Zet",
            "Alarm w kraju NATO Radio Zet",
        )
        with patch.object(enricher, '_fetch_body', new_callable=AsyncMock, return_value="Real body text here with lots of details about what happened in Latvia."):
            result = asyncio.get_event_loop().run_until_complete(
                enricher.enrich_batch([article])
            )
        assert result[0].raw_metadata["enrichment"]["method"] == "heuristic"
        assert result[0].raw_metadata["enrichment"]["fetched"] is True
        assert "Real body text" in result[0].summary

    def test_good_summary_skips_heuristic(self, enricher):
        article = _make_article(
            "Dwa obce drony rozbiły się na Łotwie",
            "Dwa obce drony wleciały na Łotwę z Rosji i rozbiły się – podała agencja Reutera. "
            "Jeden z dronów uderzył w skład ropy naftowej w mieście 40 km od granicy z Rosją.",
            source_type="rss",
            source_name="Defence24",
        )
        with patch.object(enricher, '_check_vagueness_llm', return_value=False):
            result = asyncio.get_event_loop().run_until_complete(
                enricher.enrich_batch([article])
            )
        assert result[0].raw_metadata["enrichment"]["method"] == "none"
        assert "agencja Reutera" in result[0].summary

    def test_llm_flagged_article_gets_enriched(self, enricher):
        article = _make_article(
            "Alarm powietrzny na Litwie. Rządzący udali się do schronów",
            "Bardzo krótkie i mało informacyjne podsumowanie artykułu z innym tekstem.",
            source_type="rss",
            source_name="RMF24",
        )
        with patch.object(enricher, '_check_vagueness_llm', return_value=True), \
             patch.object(enricher, '_fetch_body', new_callable=AsyncMock, return_value="Detailed body about Lithuania drone alert with specific details."):
            result = asyncio.get_event_loop().run_until_complete(
                enricher.enrich_batch([article])
            )
        assert result[0].raw_metadata["enrichment"]["method"] == "llm"
        assert result[0].raw_metadata["enrichment"]["fetched"] is True

    def test_failed_fetch_preserves_original_summary(self, enricher):
        article = _make_article(
            "Alarm w kraju NATO - Radio Zet",
            "Alarm w kraju NATO Radio Zet",
        )
        original_summary = article.summary
        with patch.object(enricher, '_fetch_body', new_callable=AsyncMock, return_value=None):
            result = asyncio.get_event_loop().run_until_complete(
                enricher.enrich_batch([article])
            )
        assert result[0].summary == original_summary
        assert result[0].raw_metadata["enrichment"]["fetched"] is False

    def test_empty_list_returns_empty(self, enricher):
        result = asyncio.get_event_loop().run_until_complete(
            enricher.enrich_batch([])
        )
        assert result == []

    def test_mixed_batch(self, enricher):
        garbage = _make_article(
            "Zawalone budynki - NewMedia24",
            "Zawalone budynki NewMedia24",
        )
        good = _make_article(
            "Latvia drone incident details",
            "Two drones entered Latvian airspace from Russia and crashed near Rezekne. "
            "One struck an oil depot causing minor damage. The military confirmed the incident.",
            source_type="rss",
            source_name="Defence24 EN",
        )
        with patch.object(enricher, '_check_vagueness_llm', return_value=False), \
             patch.object(enricher, '_fetch_body', new_callable=AsyncMock, return_value="Body of the garbage article."):
            result = asyncio.get_event_loop().run_until_complete(
                enricher.enrich_batch([garbage, good])
            )
        assert result[0].raw_metadata["enrichment"]["method"] == "heuristic"
        assert result[1].raw_metadata["enrichment"]["method"] == "none"
