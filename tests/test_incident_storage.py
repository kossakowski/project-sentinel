"""Persistence coverage for incident-memory metadata and legacy SQLite files."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone

from sentinel.database import Database
from sentinel.models import AlertRecord, Article, ClassificationResult, Event


def _article(suffix: str, published_at: datetime | None = None) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_name="Test source",
        source_url=f"https://example.test/{suffix}",
        source_type="rss",
        title=f"Article {suffix}",
        summary="Source summary",
        language="en",
        published_at=published_at or now,
        fetched_at=now,
    )


def _classification(article_id: str, summary: str = "Polskie podsumowanie") -> ClassificationResult:
    return ClassificationResult(
        article_id=article_id,
        is_military_event=True,
        event_type="airspace_violation",
        urgency_score=7,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.9,
        summary_pl=summary,
        classified_at=datetime.now(UTC),
        model_used="test-model",
        input_tokens=1,
        output_tokens=1,
    )


def _event(article_ids: list[str], *, last_updated_at: datetime | None = None, status: str = "pending") -> Event:
    now = datetime.now(UTC)
    return Event(
        event_type="airspace_violation",
        urgency_score=7,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Incydent",
        first_seen_at=now,
        last_updated_at=last_updated_at or now,
        source_count=len(article_ids),
        article_ids=article_ids,
        alert_status=status,
    )


def _create_legacy_database(db_path: str) -> None:
    """Create a populated pre-incident-memory schema, as a deployed DB would have."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE articles (
            id TEXT PRIMARY KEY, source_name TEXT NOT NULL, source_url TEXT NOT NULL,
            source_type TEXT NOT NULL, title TEXT NOT NULL, summary TEXT,
            language TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
            url_hash TEXT NOT NULL, title_normalized TEXT NOT NULL, raw_metadata TEXT
        );
        CREATE TABLE classifications (
            id TEXT PRIMARY KEY, article_id TEXT NOT NULL, is_military_event INTEGER NOT NULL,
            event_type TEXT, urgency_score INTEGER NOT NULL, affected_countries TEXT,
            aggressor TEXT, is_new_event INTEGER NOT NULL, confidence REAL NOT NULL,
            summary_pl TEXT, classified_at TEXT NOT NULL, model_used TEXT NOT NULL,
            input_tokens INTEGER, output_tokens INTEGER
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY, event_type TEXT NOT NULL, urgency_score INTEGER NOT NULL,
            affected_countries TEXT NOT NULL, aggressor TEXT, summary_pl TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_updated_at TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 1, article_ids TEXT NOT NULL,
            alert_status TEXT NOT NULL DEFAULT 'pending', acknowledged_at TEXT
        );
        CREATE TABLE alert_records (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL, alert_type TEXT NOT NULL,
            twilio_sid TEXT, status TEXT NOT NULL, duration_seconds INTEGER,
            attempt_number INTEGER NOT NULL DEFAULT 1, sent_at TEXT NOT NULL, message_body TEXT
        );
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-article",
            "Legacy",
            "https://example.test/legacy",
            "rss",
            "Legacy article",
            "",
            "en",
            now,
            now,
            "hash",
            "legacy article",
            "{}",
        ),
    )
    conn.execute(
        "INSERT INTO classifications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-classification",
            "legacy-article",
            1,
            "airspace_violation",
            7,
            '["PL"]',
            "RU",
            1,
            0.8,
            "Legacy summary",
            now,
            "legacy-model",
            5,
            2,
        ),
    )
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-event",
            "airspace_violation",
            7,
            '["PL"]',
            "RU",
            "Legacy event",
            now,
            now,
            1,
            '["legacy-article"]',
            "sms_sent",
            None,
        ),
    )
    conn.execute(
        "INSERT INTO alert_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy-alert", "legacy-event", "sms", "SMlegacy", "sent", None, 1, now, "Legacy alert"),
    )
    conn.commit()
    conn.close()


def test_fresh_database_stores_incident_memory_and_revisions(tmp_path):
    db = Database(str(tmp_path / "fresh.db"))
    article = _article("fresh")
    result = _classification(article.id)
    result.incident_memory = {"decision": "new", "reason": "No candidate matched"}
    event = _event([article.id])
    event.notification_revision = 2
    alert = AlertRecord(
        event_id=event.id,
        alert_type="sms",
        twilio_sid="SM123",
        status="sent",
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="Alert",
        event_revision=2,
    )

    db.insert_article(article)
    db.insert_classification(result)
    db.insert_classification(result)  # Exact replays must not create a second decision.
    db.insert_event(event)
    db.insert_alert_record(alert)

    assert (
        ClassificationResult.from_row(db.conn.execute("SELECT * FROM classifications").fetchone()).incident_memory
        == result.incident_memory
    )
    assert db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0] == 1
    assert db.get_event_by_id(event.id).notification_revision == 2
    assert db.get_alert_records(event.id)[0].event_revision == 2
    db.close()


def test_legacy_populated_database_migrates_idempotently(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _create_legacy_database(db_path)

    first = Database(db_path)
    # A second initialization must neither fail nor rewrite delivery history.
    first._create_tables()
    columns = {
        table: {row["name"] for row in first.conn.execute(f"PRAGMA table_info({table})")}
        for table in ("classifications", "events", "alert_records")
    }
    assert "incident_memory" in columns["classifications"]
    assert "notification_revision" in columns["events"]
    assert "event_revision" in columns["alert_records"]
    assert (
        ClassificationResult.from_row(
            first.conn.execute("SELECT * FROM classifications WHERE id = 'legacy-classification'").fetchone()
        ).incident_memory
        == {}
    )
    assert first.get_event_by_id("legacy-event").notification_revision == 1
    legacy_alert = first.get_alert_records("legacy-event")[0]
    assert legacy_alert.event_revision == 1
    assert legacy_alert.status == "sent"
    first.close()

    second = Database(db_path)
    assert second.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert second.get_alert_records("legacy-event")[0].event_revision == 1
    second.close()


def test_memory_events_include_all_statuses_and_compare_utc_instants(tmp_path):
    db = Database(str(tmp_path / "memory.db"))
    statuses = ("acknowledged", "resolved", "expired")
    recent_ids = []
    for index, status in enumerate(statuses):
        # 12:00+02:00 is 10:00 UTC. julianday, unlike lexical TEXT comparison,
        # correctly treats this as a recent UTC instant.
        activity = datetime.now(timezone(timedelta(hours=2))) - timedelta(minutes=(index + 1) * 10)
        event = _event([f"article-{index}"], last_updated_at=activity, status=status)
        db.insert_event(event)
        recent_ids.append(event.id)

    inside = _event(["inside"], last_updated_at=datetime.now(UTC), status="pending")
    outside = _event(["outside"], last_updated_at=datetime.now(UTC), status="pending")
    db.insert_event(inside)
    db.insert_event(outside)
    db.conn.execute(
        "UPDATE events SET last_updated_at = datetime('now', '-2 hours', '+1 second') WHERE id = ?", (inside.id,)
    )
    db.conn.execute(
        "UPDATE events SET last_updated_at = datetime('now', '-2 hours', '-1 second') WHERE id = ?", (outside.id,)
    )
    db.conn.commit()

    memory_events = db.get_memory_events(within_hours=2, limit=10)
    memory_ids = [event.id for event in memory_events]
    assert all(event_id in memory_ids for event_id in recent_ids)
    assert memory_ids[:3] == recent_ids
    assert inside.id in memory_ids
    assert outside.id not in memory_ids
    db.close()


def test_event_evidence_uses_distinct_persisted_article_ids_and_latest_summary(tmp_path):
    db = Database(str(tmp_path / "evidence.db"))
    older = _article("older", datetime.now(UTC) - timedelta(hours=2))
    newer = _article("newer", datetime.now(UTC) - timedelta(hours=1))
    for article in (older, newer):
        db.insert_article(article)
    first = _classification(older.id, "First version")
    latest = _classification(older.id, "Latest version")
    latest.classified_at = datetime.now(UTC) + timedelta(seconds=1)
    db.insert_classification(first)
    db.insert_classification(latest)
    db.insert_classification(_classification(newer.id, "Newer article summary"))
    event = _event([older.id, newer.id, older.id])
    db.insert_event(event)

    evidence = db.get_event_evidence(event.id, limit=2)
    assert [item["article_id"] for item in evidence] == [newer.id, older.id]
    assert evidence[0]["title"] == newer.title
    assert evidence[1]["summary_pl"] == "Latest version"
    db.close()
