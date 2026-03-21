"""Tests for sentinel.database Database access layer."""

from datetime import datetime, timedelta, timezone

from sentinel.database import Database
from sentinel.models import Article, ClassificationResult, Event


def test_create_tables(tmp_path):
    """Database init creates tables; calling init again doesn't error (idempotent)."""
    db_path = str(tmp_path / "test_idempotent.db")
    db1 = Database(db_path)
    # Verify tables exist by querying sqlite_master
    cursor = db1.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    assert "articles" in tables
    assert "classifications" in tables
    assert "events" in tables
    assert "alert_records" in tables

    # Calling _create_tables again should not raise
    db1._create_tables()

    # Opening a second connection to the same DB should also work
    db2 = Database(db_path)
    cursor2 = db2.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables2 = {row["name"] for row in cursor2.fetchall()}
    assert tables2 == tables

    db1.close()
    db2.close()


def test_insert_article(db, sample_article):
    """Insert article, verify it's retrievable."""
    result = db.insert_article(sample_article)
    assert result is True

    # Verify it exists
    assert db.article_exists(sample_article.url_hash) is True


def test_duplicate_article_rejected(db, sample_article):
    """Insert same article twice -- second returns False."""
    assert db.insert_article(sample_article) is True
    assert db.insert_article(sample_article) is False


def test_get_recent_titles(db):
    """Insert articles with different timestamps, verify only recent ones returned."""
    now = datetime.now(timezone.utc)

    # Insert a recent article
    recent = Article(
        source_name="RecentSource",
        source_url="https://example.com/recent",
        source_type="rss",
        title="Recent Article",
        summary="",
        language="en",
        published_at=now,
        fetched_at=now,
    )
    db.insert_article(recent)
    # Fix fetched_at to use SQLite-compatible format (datetime('now') returns 'YYYY-MM-DD HH:MM:SS')
    db.conn.execute(
        "UPDATE articles SET fetched_at = datetime('now') WHERE id = ?",
        (recent.id,),
    )

    # Insert an old article
    old = Article(
        source_name="OldSource",
        source_url="https://example.com/old",
        source_type="rss",
        title="Old Article",
        summary="",
        language="en",
        published_at=now - timedelta(hours=2),
        fetched_at=now - timedelta(hours=2),
    )
    db.insert_article(old)
    # Override fetched_at to be 2 hours ago using SQLite-compatible format
    db.conn.execute(
        "UPDATE articles SET fetched_at = datetime('now', '-2 hours') WHERE id = ?",
        (old.id,),
    )
    db.conn.commit()

    # Get recent titles (last 5 minutes)
    titles = db.get_recent_titles(since_minutes=5)
    source_names = [t[0] for t in titles]
    assert "RecentSource" in source_names
    assert "OldSource" not in source_names


def test_insert_classification(db, sample_article, sample_classification):
    """Insert classification linked to article, verify stored correctly."""
    db.insert_article(sample_article)
    db.insert_classification(sample_classification)

    cursor = db.conn.execute(
        "SELECT * FROM classifications WHERE article_id = ?",
        (sample_article.id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["article_id"] == sample_article.id
    assert row["urgency_score"] == sample_classification.urgency_score
    assert row["model_used"] == sample_classification.model_used


def test_insert_event(db, sample_event):
    """Insert event with article_ids list, verify stored."""
    db.insert_event(sample_event)

    cursor = db.conn.execute(
        "SELECT * FROM events WHERE id = ?",
        (sample_event.id,),
    )
    row = cursor.fetchone()
    assert row is not None

    restored = Event.from_row(row)
    assert restored.event_type == sample_event.event_type
    assert restored.article_ids == sample_event.article_ids
    assert restored.urgency_score == sample_event.urgency_score


def test_update_event(db, sample_event):
    """Update event urgency_score and source_count, verify changed."""
    db.insert_event(sample_event)

    db.update_event(sample_event.id, urgency_score=10, source_count=5)

    cursor = db.conn.execute(
        "SELECT * FROM events WHERE id = ?",
        (sample_event.id,),
    )
    row = cursor.fetchone()
    assert row["urgency_score"] == 10
    assert row["source_count"] == 5


def test_get_active_events(db):
    """Insert events with different statuses and times, verify filtering."""
    now = datetime.now(timezone.utc)

    # Active pending event (recent)
    active = Event(
        event_type="troop_movement",
        urgency_score=8,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Aktywne zdarzenie",
        first_seen_at=now,
        last_updated_at=now,
        source_count=2,
        article_ids=["art-1"],
        alert_status="pending",
    )
    db.insert_event(active)

    # Expired event (recent but expired status)
    expired = Event(
        event_type="cyberattack",
        urgency_score=5,
        affected_countries=["LT"],
        aggressor="RU",
        summary_pl="Wygasłe zdarzenie",
        first_seen_at=now,
        last_updated_at=now,
        source_count=1,
        article_ids=["art-2"],
        alert_status="expired",
    )
    db.insert_event(expired)

    # Old event (beyond the window)
    old = Event(
        event_type="airspace_violation",
        urgency_score=6,
        affected_countries=["EE"],
        aggressor="RU",
        summary_pl="Stare zdarzenie",
        first_seen_at=now - timedelta(hours=100),
        last_updated_at=now - timedelta(hours=100),
        source_count=1,
        article_ids=["art-3"],
        alert_status="pending",
    )
    db.insert_event(old)
    # Override first_seen_at to be well in the past
    old_first_seen = (now - timedelta(hours=100)).isoformat()
    db.conn.execute(
        "UPDATE events SET first_seen_at = ? WHERE id = ?",
        (old_first_seen, old.id),
    )
    db.conn.commit()

    active_events = db.get_active_events(within_hours=24)
    active_ids = [e.id for e in active_events]

    # Only the active pending event should be returned
    assert active.id in active_ids
    assert expired.id not in active_ids
    assert old.id not in active_ids


def test_cleanup_old_records(db):
    """Insert old articles/events, run cleanup, verify deleted."""
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=60)

    # Insert an old article
    old_article = Article(
        source_name="OldSource",
        source_url="https://example.com/old-cleanup",
        source_type="rss",
        title="Very Old Article",
        summary="",
        language="en",
        published_at=old_date,
        fetched_at=old_date,
    )
    db.insert_article(old_article)

    # Insert a classification for that article
    old_classification = ClassificationResult(
        article_id=old_article.id,
        is_military_event=False,
        event_type="",
        urgency_score=1,
        affected_countries=[],
        aggressor="",
        is_new_event=False,
        confidence=0.1,
        summary_pl="",
        classified_at=old_date,
        model_used="test",
        input_tokens=10,
        output_tokens=5,
    )
    db.insert_classification(old_classification)

    # Override fetched_at in DB to be 60 days ago
    old_fetched = old_date.isoformat()
    db.conn.execute(
        "UPDATE articles SET fetched_at = ? WHERE id = ?",
        (old_fetched, old_article.id),
    )
    db.conn.commit()

    # Insert a recent article that should NOT be deleted
    recent_article = Article(
        source_name="RecentSource",
        source_url="https://example.com/recent-cleanup",
        source_type="rss",
        title="Recent Article",
        summary="",
        language="en",
        published_at=now,
        fetched_at=now,
    )
    db.insert_article(recent_article)

    # Run cleanup with article_days=30 (anything older than 30 days gets deleted)
    deleted = db.cleanup_old_records(article_days=30, event_days=30)
    assert deleted >= 2  # at least the old article + its classification

    # Old article should be gone
    assert db.article_exists(old_article.url_hash) is False
    # Recent article should still be there
    assert db.article_exists(recent_article.url_hash) is True

    # Classification for old article should also be gone
    cursor = db.conn.execute(
        "SELECT * FROM classifications WHERE article_id = ?",
        (old_article.id,),
    )
    assert cursor.fetchone() is None


def test_concurrent_access(db):
    """Rapid sequential inserts don't corrupt data."""
    inserted_count = 0
    for i in range(100):
        article = Article(
            source_name=f"Source_{i}",
            source_url=f"https://example.com/article/{i}",
            source_type="rss",
            title=f"Article number {i}",
            summary="",
            language="en",
            published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
        )
        if db.insert_article(article):
            inserted_count += 1

    assert inserted_count == 100

    # Verify all 100 are stored
    cursor = db.conn.execute("SELECT COUNT(*) as cnt FROM articles")
    count = cursor.fetchone()["cnt"]
    assert count == 100
