import logging
import os
import sqlite3
from datetime import datetime, timezone

from sentinel.models import AlertRecord, Article, ClassificationResult, Event


class Database:
    """SQLite database access layer for Project Sentinel."""

    def __init__(self, db_path: str) -> None:
        """Create the database file (and parent dirs) and tables if they don't exist."""
        self.logger = logging.getLogger("sentinel.database")

        if db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self.logger.debug("Database initialized: %s", db_path)

    def _create_tables(self) -> None:
        """Create all tables and indexes if they don't exist."""
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    language TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    title_normalized TEXT NOT NULL,
                    raw_metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
                CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at);
                CREATE INDEX IF NOT EXISTS idx_articles_title_normalized ON articles(title_normalized);

                CREATE TABLE IF NOT EXISTS classifications (
                    id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL REFERENCES articles(id),
                    is_military_event INTEGER NOT NULL,
                    event_type TEXT,
                    urgency_score INTEGER NOT NULL,
                    affected_countries TEXT,
                    aggressor TEXT,
                    is_new_event INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    summary_pl TEXT,
                    classified_at TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_classifications_article_id ON classifications(article_id);
                CREATE INDEX IF NOT EXISTS idx_classifications_urgency ON classifications(urgency_score);

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    urgency_score INTEGER NOT NULL,
                    affected_countries TEXT NOT NULL,
                    aggressor TEXT,
                    summary_pl TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL,
                    source_count INTEGER NOT NULL DEFAULT 1,
                    article_ids TEXT NOT NULL,
                    alert_status TEXT NOT NULL DEFAULT 'pending',
                    acknowledged_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_events_alert_status ON events(alert_status);
                CREATE INDEX IF NOT EXISTS idx_events_first_seen ON events(first_seen_at);

                CREATE TABLE IF NOT EXISTS alert_records (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(id),
                    alert_type TEXT NOT NULL,
                    twilio_sid TEXT,
                    status TEXT NOT NULL,
                    duration_seconds INTEGER,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    sent_at TEXT NOT NULL,
                    message_body TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_event_id ON alert_records(event_id);
            """)

    def insert_article(self, article: Article) -> bool:
        """Insert an article. Returns False if URL hash already exists (duplicate)."""
        if self.article_exists(article.url_hash):
            self.logger.debug("Duplicate article skipped: %s", article.url_hash)
            return False

        data = article.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)

        try:
            with self.conn:
                self.conn.execute(
                    f"INSERT INTO articles ({columns}) VALUES ({placeholders})",
                    list(data.values()),
                )
            self.logger.debug("Article inserted: %s", article.title[:60])
            return True
        except sqlite3.IntegrityError:
            self.logger.debug("Duplicate article (integrity): %s", article.url_hash)
            return False

    def article_exists(self, url_hash: str) -> bool:
        """Check if an article with this URL hash exists."""
        cursor = self.conn.execute(
            "SELECT 1 FROM articles WHERE url_hash = ? LIMIT 1",
            (url_hash,),
        )
        return cursor.fetchone() is not None

    def get_recent_titles(self, since_minutes: int) -> list[tuple[str, str]]:
        """Return (source_name, title_normalized) tuples for articles fetched within last N minutes.

        Used by the deduplicator for fuzzy title matching.
        """
        cursor = self.conn.execute(
            "SELECT source_name, title_normalized FROM articles "
            "WHERE fetched_at > datetime('now', ? || ' minutes')",
            (str(-since_minutes),),
        )
        return [(row["source_name"], row["title_normalized"]) for row in cursor.fetchall()]

    def insert_classification(self, result: ClassificationResult) -> None:
        """Insert a classification result."""
        data = result.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)

        with self.conn:
            self.conn.execute(
                f"INSERT INTO classifications ({columns}) VALUES ({placeholders})",
                list(data.values()),
            )
        self.logger.debug("Classification inserted for article: %s", result.article_id)

    def insert_event(self, event: Event) -> None:
        """Insert a new event."""
        data = event.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)

        with self.conn:
            self.conn.execute(
                f"INSERT INTO events ({columns}) VALUES ({placeholders})",
                list(data.values()),
            )
        self.logger.debug("Event inserted: %s", event.id)

    def update_event(self, event_id: str, **kwargs: object) -> None:
        """Update specific fields of an event.

        Only update the fields passed as kwargs.
        Always update last_updated_at to current time.
        """
        kwargs["last_updated_at"] = datetime.now(timezone.utc).isoformat()

        set_clause = ", ".join(f"{key} = ?" for key in kwargs)
        values = list(kwargs.values())
        values.append(event_id)

        with self.conn:
            self.conn.execute(
                f"UPDATE events SET {set_clause} WHERE id = ?",
                values,
            )
        self.logger.debug("Event updated: %s", event_id)

    def get_active_events(self, within_hours: int) -> list[Event]:
        """Get events with alert_status != 'expired' from the last N hours."""
        cursor = self.conn.execute(
            "SELECT * FROM events "
            "WHERE alert_status != 'expired' "
            "AND first_seen_at > datetime('now', ? || ' hours')",
            (str(-within_hours),),
        )
        return [Event.from_row(row) for row in cursor.fetchall()]

    def insert_alert_record(self, record: AlertRecord) -> None:
        """Insert an alert record."""
        data = record.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)

        with self.conn:
            self.conn.execute(
                f"INSERT INTO alert_records ({columns}) VALUES ({placeholders})",
                list(data.values()),
            )
        self.logger.debug("Alert record inserted: %s", record.id)

    def get_alert_records(self, event_id: str) -> list[AlertRecord]:
        """Get all alert records for an event, ordered by sent_at."""
        cursor = self.conn.execute(
            "SELECT * FROM alert_records WHERE event_id = ? ORDER BY sent_at",
            (event_id,),
        )
        return [AlertRecord.from_row(row) for row in cursor.fetchall()]

    def get_pending_call_records(self) -> list[AlertRecord]:
        """Get alert records of type 'phone_call' with status 'initiated' or 'ringing'.

        Used to check call completion status.
        """
        cursor = self.conn.execute(
            "SELECT * FROM alert_records "
            "WHERE alert_type = 'phone_call' AND status IN ('initiated', 'ringing')"
        )
        return [AlertRecord.from_row(row) for row in cursor.fetchall()]

    def get_article_by_id(self, article_id: str) -> Article | None:
        """Return the Article with the given ID, or None if not found."""
        cursor = self.conn.execute(
            "SELECT * FROM articles WHERE id = ? LIMIT 1",
            (article_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Article.from_row(row)

    def get_event_by_id(self, event_id: str) -> Event | None:
        """Return the Event with the given ID, or None if not found."""
        cursor = self.conn.execute(
            "SELECT * FROM events WHERE id = ? LIMIT 1",
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Event.from_row(row)

    def update_alert_record(self, record_id: str, **kwargs: object) -> None:
        """Update specific fields of an alert record.

        Only update the fields passed as kwargs.
        """
        if not kwargs:
            return

        set_clause = ", ".join(f"{key} = ?" for key in kwargs)
        values = list(kwargs.values())
        values.append(record_id)

        with self.conn:
            self.conn.execute(
                f"UPDATE alert_records SET {set_clause} WHERE id = ?",
                values,
            )
        self.logger.debug("Alert record updated: %s", record_id)

    def cleanup_old_records(self, article_days: int, event_days: int) -> int:
        """Delete articles older than article_days and events older than event_days.

        Returns total number of records deleted.
        Also deletes classifications and alert_records for deleted articles/events.
        """
        total_deleted = 0

        with self.conn:
            # Delete classifications for old articles
            cursor = self.conn.execute(
                "DELETE FROM classifications WHERE article_id IN "
                "(SELECT id FROM articles WHERE fetched_at < datetime('now', ? || ' days'))",
                (str(-article_days),),
            )
            total_deleted += cursor.rowcount

            # Delete old articles
            cursor = self.conn.execute(
                "DELETE FROM articles WHERE fetched_at < datetime('now', ? || ' days')",
                (str(-article_days),),
            )
            total_deleted += cursor.rowcount

            # Delete alert_records for old events
            cursor = self.conn.execute(
                "DELETE FROM alert_records WHERE event_id IN "
                "(SELECT id FROM events WHERE first_seen_at < datetime('now', ? || ' days'))",
                (str(-event_days),),
            )
            total_deleted += cursor.rowcount

            # Delete old events
            cursor = self.conn.execute(
                "DELETE FROM events WHERE first_seen_at < datetime('now', ? || ' days')",
                (str(-event_days),),
            )
            total_deleted += cursor.rowcount

        self.logger.info("Cleanup: deleted %d old records", total_deleted)
        return total_deleted

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
        self.logger.debug("Database connection closed")
