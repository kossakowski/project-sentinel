"""Tests for sentinel.processing.keyword_filter."""

from datetime import datetime, timezone

from sentinel.models import Article
from sentinel.processing.keyword_filter import KeywordFilter


def _make_article(**overrides) -> Article:
    """Helper to build an Article with sensible defaults."""
    defaults = {
        "source_name": "TestSource",
        "source_url": "https://example.com/article/1",
        "source_type": "rss",
        "title": "Test Title",
        "summary": "Test summary.",
        "language": "en",
        "published_at": datetime.now(timezone.utc),
        "fetched_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Article(**defaults)


def _make_config_with_keywords(sample_config_dict):
    """Build a SentinelConfig with full keyword sets for testing."""
    from sentinel.config import SentinelConfig

    cfg = dict(sample_config_dict)
    cfg["monitoring"] = dict(cfg["monitoring"])
    cfg["monitoring"]["keywords"] = {
        "en": {
            "critical": [
                "military attack",
                "invasion",
                "missile strike",
                "Article 5",
                "armed attack",
            ],
            "high": [
                "military buildup",
                "troops massing",
                "mobilization",
                "border incident",
            ],
        },
        "pl": {
            "critical": [
                "atak wojskowy",
                "inwazja",
                "uderzenie rakietowe",
                "atak zbrojny",
            ],
            "high": [
                "mobilizacja",
                "eskalacja",
                "koncentracja wojsk",
            ],
        },
        "uk": {
            "critical": [
                "військовий напад",
                "вторгнення",
                "ракетний удар",
            ],
            "high": [
                "мобілізація",
                "ескалація",
            ],
        },
        "ru": {
            "critical": [
                "военная операция",
                "вторжение",
                "ракетный удар",
            ],
            "high": [
                "провокация",
                "мобилизация",
                "эскалация",
            ],
        },
    }
    cfg["monitoring"]["exclude_keywords"] = {
        "en": ["exercise", "drill", "game", "historical", "movie", "film"],
        "pl": ["ćwiczenia", "manewry", "historyczny", "film"],
    }
    return SentinelConfig(**cfg)


class TestKeywordFilter:
    """Acceptance tests for the KeywordFilter."""

    def test_critical_keyword_matches(self, sample_config_dict):
        """Article with 'inwazja' in title matches as critical."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Inwazja na Polskę - alarm w całym kraju",
            language="pl",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "critical"
        assert "inwazja" in result["matched_keywords"]

    def test_high_keyword_matches(self, sample_config_dict):
        """Article with 'mobilizacja' matches as high."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Mobilizacja w regionie - wojsko w gotowości",
            language="pl",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "high"
        assert "mobilizacja" in result["matched_keywords"]

    def test_no_keyword_rejected(self, sample_config_dict):
        """Article about weather has no keyword match."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Sunny weather expected across Poland this weekend",
            summary="Temperatures will rise to 25 degrees.",
            language="en",
        )
        result = kf.matches(article)
        assert result is None

    def test_exclude_keyword_filters(self, sample_config_dict):
        """Article with exclude keyword and no critical match is rejected."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Ćwiczenia wojskowe na poligonie",
            summary="Kolejne manewry sił zbrojnych.",
            language="pl",
        )
        result = kf.matches(article)
        assert result is None

    def test_exclude_overridden_by_critical(self, sample_config_dict):
        """Article with both critical keyword and exclude keyword passes."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Inwazja podczas ćwiczenia wojskowego",
            summary="Niespodziewana inwazja w trakcie manewrów.",
            language="pl",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "critical"

    def test_english_keywords_on_english_article(self, sample_config_dict):
        """English article matches English keywords."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Military attack reported on NATO border",
            language="en",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "critical"
        assert result["language_matched"] == "en"

    def test_polish_keywords_on_polish_article(self, sample_config_dict):
        """Polish article matches Polish keywords."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Atak wojskowy na granicy wschodniej",
            language="pl",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "critical"
        assert result["language_matched"] == "pl"

    def test_unknown_language_falls_back_to_english(self, sample_config_dict):
        """German article is checked against English keywords as fallback."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Missile strike near Baltic region reported",
            language="de",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["language_matched"] == "en"

    def test_case_insensitive(self, sample_config_dict):
        """INWAZJA matches inwazja (case-insensitive)."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="INWAZJA NA POLSKĘ",
            language="pl",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "critical"

    def test_match_annotation_added(self, sample_config_dict):
        """Matched keywords are stored in raw_metadata."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Military attack on eastern flank",
            language="en",
        )
        filtered = kf.filter_batch([article])
        assert len(filtered) == 1
        assert "keyword_match" in filtered[0].raw_metadata
        match_info = filtered[0].raw_metadata["keyword_match"]
        assert match_info["level"] == "critical"
        assert "military attack" in match_info["matched_keywords"]

    def test_multiple_keywords_all_recorded(self, sample_config_dict):
        """Article matching multiple keywords has all of them in the annotation."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Military attack and missile strike reported",
            summary="An armed attack coincided with the missile strike.",
            language="en",
        )
        result = kf.matches(article)
        assert result is not None
        assert len(result["matched_keywords"]) >= 3
        kws = result["matched_keywords"]
        assert "military attack" in kws
        assert "missile strike" in kws
        assert "armed attack" in kws

    def test_bypass_source_passes_without_keywords(self, sample_config_dict):
        """Articles from keyword_bypass sources pass without keyword matching."""
        cfg = dict(sample_config_dict)
        cfg["sources"] = dict(cfg["sources"])
        cfg["sources"]["rss"] = [
            {
                "name": "Defence24",
                "url": "https://defence24.pl/_rss",
                "language": "pl",
                "enabled": True,
                "priority": 1,
                "keyword_bypass": True,
            },
        ]
        from sentinel.config import SentinelConfig

        config = _make_config_with_keywords(cfg)
        kf = KeywordFilter(config)
        article = _make_article(
            source_name="Defence24",
            title="Nowy okręt dla Marynarki Wojennej",
            summary="Podpisano kontrakt na budowę fregaty.",
            language="pl",
        )
        filtered = kf.filter_batch([article])
        assert len(filtered) == 1
        assert filtered[0].raw_metadata["keyword_match"]["level"] == "bypass"

    def test_bypass_does_not_affect_other_sources(self, sample_config_dict):
        """Non-bypass sources still require keyword matching."""
        cfg = dict(sample_config_dict)
        cfg["sources"] = dict(cfg["sources"])
        cfg["sources"]["rss"] = [
            {
                "name": "Defence24",
                "url": "https://defence24.pl/_rss",
                "language": "pl",
                "enabled": True,
                "priority": 1,
                "keyword_bypass": True,
            },
            {
                "name": "Onet",
                "url": "https://wiadomosci.onet.pl/.feed",
                "language": "pl",
                "enabled": True,
                "priority": 2,
            },
        ]
        from sentinel.config import SentinelConfig

        config = _make_config_with_keywords(cfg)
        kf = KeywordFilter(config)
        article = _make_article(
            source_name="Onet",
            title="Nowy okręt dla Marynarki Wojennej",
            summary="Podpisano kontrakt na budowę fregaty.",
            language="pl",
        )
        filtered = kf.filter_batch([article])
        assert len(filtered) == 0

    def test_bypass_diagnose(self, sample_config_dict):
        """Diagnose returns bypass=True for bypass sources."""
        cfg = dict(sample_config_dict)
        cfg["sources"] = dict(cfg["sources"])
        cfg["sources"]["rss"] = [
            {
                "name": "Defence24",
                "url": "https://defence24.pl/_rss",
                "language": "pl",
                "enabled": True,
                "priority": 1,
                "keyword_bypass": True,
            },
        ]
        from sentinel.config import SentinelConfig

        config = _make_config_with_keywords(cfg)
        kf = KeywordFilter(config)
        article = _make_article(
            source_name="Defence24",
            title="Pogoda na poligonie",
            language="pl",
        )
        result = kf.diagnose(article)
        assert result["passed"] is True
        assert result["bypass"] is True

    def test_russian_provocation_keyword(self, sample_config_dict):
        """Russian 'провокация' matches as high."""
        config = _make_config_with_keywords(sample_config_dict)
        kf = KeywordFilter(config)
        article = _make_article(
            title="Провокация на границе с Польшей",
            summary="Инцидент расценен как провокация.",
            language="ru",
        )
        result = kf.matches(article)
        assert result is not None
        assert result["level"] == "high"
        assert "провокация" in result["matched_keywords"]
