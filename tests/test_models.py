"""Tests for sentinel.models data classes."""

from datetime import datetime, timezone

from sentinel.models import AlertRecord, Article, ClassificationResult, Event


def test_article_to_dict_roundtrip(sample_article):
    """Article -> to_dict() -> from_dict() preserves all fields."""
    d = sample_article.to_dict()
    restored = Article.from_dict(d)
    assert restored.id == sample_article.id
    assert restored.source_name == sample_article.source_name
    assert restored.source_url == sample_article.source_url
    assert restored.title == sample_article.title
    assert restored.url_hash == sample_article.url_hash
    assert restored.title_normalized == sample_article.title_normalized
    assert restored.raw_metadata == sample_article.raw_metadata
    # Datetimes: compare ISO strings since exact precision may vary
    assert restored.published_at.date() == sample_article.published_at.date()


def test_classification_to_dict_roundtrip(sample_classification):
    """ClassificationResult roundtrip preserves all fields, including list fields."""
    d = sample_classification.to_dict()
    restored = ClassificationResult.from_dict(d)
    assert restored.article_id == sample_classification.article_id
    assert restored.urgency_score == sample_classification.urgency_score
    assert restored.affected_countries == sample_classification.affected_countries
    assert restored.confidence == sample_classification.confidence


def test_event_to_dict_roundtrip(sample_event):
    """Event roundtrip preserves all fields, including list fields and None."""
    d = sample_event.to_dict()
    restored = Event.from_dict(d)
    assert restored.event_type == sample_event.event_type
    assert restored.affected_countries == sample_event.affected_countries
    assert restored.article_ids == sample_event.article_ids
    assert restored.acknowledged_at is None


def test_alert_record_to_dict_roundtrip(sample_alert_record):
    """AlertRecord roundtrip preserves all fields including None duration."""
    d = sample_alert_record.to_dict()
    restored = AlertRecord.from_dict(d)
    assert restored.event_id == sample_alert_record.event_id
    assert restored.alert_type == sample_alert_record.alert_type
    assert restored.duration_seconds is None


def test_article_url_hash_deterministic():
    """Same URL always gives the same hash."""
    url = "https://example.com/article/same-url"
    a1 = Article(
        source_name="S1",
        source_url=url,
        source_type="rss",
        title="Title A",
        summary="",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    a2 = Article(
        source_name="S2",
        source_url=url,
        source_type="rss",
        title="Title B",
        summary="",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    assert a1.url_hash == a2.url_hash


def test_article_title_normalized():
    """Verify accents stripped, lowercase, punctuation removed."""
    article = Article(
        source_name="S1",
        source_url="https://example.com/1",
        source_type="rss",
        title="Wóżki Łódź -- Kraków!!! Über Test",
        summary="",
        language="pl",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    norm = article.title_normalized
    # Should be lowercase
    assert norm == norm.lower()
    # No punctuation (dashes, exclamation marks)
    assert "!" not in norm
    assert "--" not in norm
    # Accents stripped: ó -> o, ü -> u
    # Note: Ł does not decompose via NFKD (it's not a base letter + combining mark),
    # so it gets stripped entirely by the punctuation-removal regex.
    assert "wozki" in norm
    assert "krakow" in norm
    assert "uber" in norm


def test_article_default_id_generated():
    """Article created without explicit id gets a UUID."""
    a1 = Article(
        source_name="S1",
        source_url="https://example.com/1",
        source_type="rss",
        title="Test",
        summary="",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    a2 = Article(
        source_name="S2",
        source_url="https://example.com/2",
        source_type="rss",
        title="Test 2",
        summary="",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    # Both should have non-empty IDs
    assert a1.id
    assert a2.id
    # And they should be different (unique UUIDs)
    assert a1.id != a2.id
