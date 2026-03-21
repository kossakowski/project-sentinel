"""Tests for sentinel.processing.normalizer."""

from datetime import datetime, timedelta, timezone

from sentinel.models import Article
from sentinel.processing.normalizer import Normalizer


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


class TestNormalizer:
    """Acceptance tests for the Normalizer."""

    def setup_method(self):
        self.normalizer = Normalizer()

    def test_strip_html_from_title(self):
        """<b>Breaking</b> news -> Breaking news."""
        article = _make_article(title="<b>Breaking</b> news")
        result = self.normalizer.normalize(article)
        assert result.title == "Breaking news"

    def test_strip_html_entities(self):
        """AT&amp;T -> AT&T."""
        article = _make_article(title="AT&amp;T reports &amp; &#39;quotes&#39;")
        result = self.normalizer.normalize(article)
        assert "AT&T" in result.title
        assert "'" in result.title
        assert "&amp;" not in result.title

    def test_collapse_whitespace(self):
        """Multiple whitespace collapsed to single space."""
        article = _make_article(title="Breaking   news  here")
        result = self.normalizer.normalize(article)
        assert result.title == "Breaking news here"

    def test_truncate_long_title(self):
        """Title longer than 500 chars is truncated with '...' suffix."""
        long_title = "A" * 600
        article = _make_article(title=long_title)
        result = self.normalizer.normalize(article)
        assert len(result.title) == 503  # 500 + len("...")
        assert result.title.endswith("...")

    def test_url_tracking_params_stripped(self):
        """UTM and tracking parameters are removed from URLs."""
        url = "https://example.com/article/1?utm_source=twitter&utm_medium=social&fbclid=abc123&id=42"
        article = _make_article(source_url=url)
        result = self.normalizer.normalize(article)
        assert "utm_source" not in result.source_url
        assert "utm_medium" not in result.source_url
        assert "fbclid" not in result.source_url
        assert "id=42" in result.source_url

    def test_url_www_removed(self):
        """www. prefix is stripped from domain."""
        article = _make_article(source_url="https://www.example.com/article/1")
        result = self.normalizer.normalize(article)
        assert "www." not in result.source_url
        assert "example.com" in result.source_url

    def test_timestamp_future_capped(self):
        """Future timestamp is capped to current UTC time."""
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        article = _make_article(published_at=future)
        result = self.normalizer.normalize(article)
        now = datetime.now(timezone.utc)
        assert result.published_at <= now + timedelta(seconds=5)

    def test_timestamp_missing_uses_fetched(self):
        """When published_at is None, fetched_at is used."""
        fetched = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        article = _make_article(published_at=None, fetched_at=fetched)
        result = self.normalizer.normalize(article)
        assert result.published_at == fetched

    def test_url_hash_consistent(self):
        """Same URL always produces the same hash after normalization."""
        url_a = "https://www.example.com/article/1?utm_source=twitter"
        url_b = "https://www.example.com/article/1?utm_campaign=summer"
        a = self.normalizer.normalize(_make_article(source_url=url_a))
        b = self.normalizer.normalize(_make_article(source_url=url_b))
        assert a.url_hash == b.url_hash

    def test_title_normalized_lowercase(self):
        """Normalized title is lowercase."""
        article = _make_article(title="BREAKING NEWS")
        result = self.normalizer.normalize(article)
        assert result.title_normalized == result.title_normalized.lower()
        assert "breaking news" == result.title_normalized

    def test_title_normalized_no_accents(self):
        """Accented characters are decomposed (o-acute -> o, a-ogonek stripped)."""
        article = _make_article(title="Kraków Łódź café über")
        result = self.normalizer.normalize(article)
        norm = result.title_normalized
        assert "krakow" in norm
        assert "cafe" in norm
        assert "uber" in norm

    def test_language_mapping(self):
        """Full language names are mapped to ISO codes."""
        en = self.normalizer.normalize(_make_article(language="English"))
        pl = self.normalizer.normalize(_make_article(language="Polish"))
        uk = self.normalizer.normalize(_make_article(language="Ukrainian"))
        ru = self.normalizer.normalize(_make_article(language="Russian"))
        assert en.language == "en"
        assert pl.language == "pl"
        assert uk.language == "uk"
        assert ru.language == "ru"
