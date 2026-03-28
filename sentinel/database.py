import logging
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from sentinel.models import (
    AlertRecord,
    Article,
    ClassificationResult,
    ConfirmationCode,
    Event,
    Tier,
    User,
    UserAlertRule,
)


def _adapt_values(values: list) -> list:
    """Wrap dict/list values with Jsonb() for PostgreSQL JSONB columns."""
    adapted = []
    for v in values:
        if isinstance(v, (dict, list)):
            adapted.append(Jsonb(v))
        else:
            adapted.append(v)
    return adapted


class Database:
    """PostgreSQL database access layer for Project Sentinel."""

    def __init__(self, url: str) -> None:
        """Create a connection pool and initialize tables if they don't exist."""
        self.logger = logging.getLogger("sentinel.database")

        self.pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
        )
        self._create_tables()
        self.logger.debug("Database initialized: %s", url)

    def _create_tables(self) -> None:
        """Create all tables and indexes if they don't exist."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS articles (
                        id TEXT PRIMARY KEY,
                        source_name TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT,
                        language TEXT NOT NULL,
                        published_at TIMESTAMPTZ NOT NULL,
                        fetched_at TIMESTAMPTZ NOT NULL,
                        url_hash TEXT NOT NULL UNIQUE,
                        title_normalized TEXT NOT NULL,
                        raw_metadata JSONB
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_articles_title_normalized ON articles(title_normalized)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS classifications (
                        id TEXT PRIMARY KEY,
                        article_id TEXT NOT NULL REFERENCES articles(id),
                        is_military_event BOOLEAN NOT NULL,
                        event_type TEXT,
                        urgency_score INTEGER NOT NULL,
                        affected_countries JSONB,
                        aggressor TEXT,
                        is_new_event BOOLEAN NOT NULL,
                        confidence REAL NOT NULL,
                        summary_pl TEXT,
                        classified_at TIMESTAMPTZ NOT NULL,
                        model_used TEXT NOT NULL,
                        input_tokens INTEGER,
                        output_tokens INTEGER
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_classifications_article_id ON classifications(article_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_classifications_urgency ON classifications(urgency_score)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        urgency_score INTEGER NOT NULL,
                        affected_countries JSONB NOT NULL,
                        aggressor TEXT,
                        summary_pl TEXT NOT NULL,
                        first_seen_at TIMESTAMPTZ NOT NULL,
                        last_updated_at TIMESTAMPTZ NOT NULL,
                        source_count INTEGER NOT NULL DEFAULT 1,
                        article_ids JSONB NOT NULL,
                        alert_status TEXT NOT NULL DEFAULT 'pending',
                        acknowledged_at TIMESTAMPTZ
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_alert_status ON events(alert_status)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_first_seen ON events(first_seen_at)
                """)

                # --- Tiers table (must be created before users) ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tiers (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        available_channels JSONB NOT NULL,
                        max_countries INTEGER,
                        preference_mode TEXT NOT NULL CHECK (preference_mode IN ('preset', 'customizable')),
                        preset_rules JSONB,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # --- Users table ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        phone_number TEXT NOT NULL,
                        language TEXT NOT NULL DEFAULT 'pl',
                        tier_id TEXT NOT NULL REFERENCES tiers(id),
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # --- User countries table ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_countries (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        country_code TEXT NOT NULL,
                        UNIQUE(user_id, country_code)
                    )
                """)

                # --- User alert rules table ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_alert_rules (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        min_urgency INTEGER NOT NULL,
                        max_urgency INTEGER NOT NULL,
                        channel TEXT NOT NULL,
                        corroboration_required INTEGER NOT NULL DEFAULT 1,
                        priority INTEGER NOT NULL DEFAULT 0,
                        CHECK(min_urgency <= max_urgency)
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_records (
                        id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL REFERENCES events(id),
                        alert_type TEXT NOT NULL,
                        twilio_sid TEXT,
                        status TEXT NOT NULL,
                        duration_seconds INTEGER,
                        attempt_number INTEGER NOT NULL DEFAULT 1,
                        sent_at TIMESTAMPTZ NOT NULL,
                        message_body TEXT,
                        user_id TEXT REFERENCES users(id)
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_alerts_event_id ON alert_records(event_id)
                """)

                # --- Confirmation codes table (depends on users and events) ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS confirmation_codes (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES users(id),
                        event_id TEXT NOT NULL REFERENCES events(id),
                        code TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        used_at TIMESTAMPTZ
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_confirmation_codes_lookup
                        ON confirmation_codes(user_id, event_id, code)
                """)

    def insert_article(self, article: Article) -> bool:
        """Insert an article. Returns False if URL hash already exists (duplicate)."""
        data = article.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO articles ({columns}) VALUES ({placeholders}) "
                    "ON CONFLICT (url_hash) DO NOTHING RETURNING id",
                    _adapt_values(list(data.values())),
                )
                result = cur.fetchone()

        if result is None:
            self.logger.debug("Duplicate article skipped: %s", article.url_hash)
            return False

        self.logger.debug("Article inserted: %s", article.title[:60])
        return True

    def article_exists(self, url_hash: str) -> bool:
        """Check if an article with this URL hash exists."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM articles WHERE url_hash = %s LIMIT 1",
                    (url_hash,),
                )
                return cur.fetchone() is not None

    def get_recent_titles(self, since_minutes: int) -> list[tuple[str, str]]:
        """Return (source_name, title_normalized) tuples for articles fetched within last N minutes.

        Used by the deduplicator for fuzzy title matching.
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT source_name, title_normalized FROM articles "
                    "WHERE fetched_at > NOW() - make_interval(mins => %s)",
                    (since_minutes,),
                )
                return [(row["source_name"], row["title_normalized"]) for row in cur.fetchall()]

    def insert_classification(self, result: ClassificationResult) -> None:
        """Insert a classification result."""
        data = result.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO classifications ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("Classification inserted for article: %s", result.article_id)

    def insert_event(self, event: Event) -> None:
        """Insert a new event."""
        data = event.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO events ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("Event inserted: %s", event.id)

    def update_event(self, event_id: str, **kwargs: object) -> None:
        """Update specific fields of an event.

        Only update the fields passed as kwargs.
        Always update last_updated_at to current time.
        """
        kwargs["last_updated_at"] = datetime.now(timezone.utc)

        set_clause = ", ".join(f"{key} = %s" for key in kwargs)
        values = _adapt_values(list(kwargs.values()))
        values.append(event_id)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE events SET {set_clause} WHERE id = %s",
                    values,
                )
        self.logger.debug("Event updated: %s", event_id)

    def get_active_events(self, within_hours: int) -> list[Event]:
        """Get events with alert_status != 'expired' from the last N hours."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM events "
                    "WHERE alert_status != 'expired' "
                    "AND first_seen_at > NOW() - make_interval(hours => %s)",
                    (within_hours,),
                )
                return [Event.from_row(row) for row in cur.fetchall()]

    def insert_alert_record(self, record: AlertRecord) -> None:
        """Insert an alert record."""
        data = record.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO alert_records ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("Alert record inserted: %s", record.id)

    def get_alert_records(self, event_id: str) -> list[AlertRecord]:
        """Get all alert records for an event, ordered by sent_at."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM alert_records WHERE event_id = %s ORDER BY sent_at",
                    (event_id,),
                )
                return [AlertRecord.from_row(row) for row in cur.fetchall()]

    def get_pending_call_records(self) -> list[AlertRecord]:
        """Get alert records of type 'phone_call' with status 'initiated' or 'ringing'.

        Used to check call completion status.
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM alert_records "
                    "WHERE alert_type = 'phone_call' AND status IN ('initiated', 'ringing')"
                )
                return [AlertRecord.from_row(row) for row in cur.fetchall()]

    def get_article_by_id(self, article_id: str) -> Article | None:
        """Return the Article with the given ID, or None if not found."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM articles WHERE id = %s LIMIT 1",
                    (article_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return Article.from_row(row)

    def get_event_by_id(self, event_id: str) -> Event | None:
        """Return the Event with the given ID, or None if not found."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM events WHERE id = %s LIMIT 1",
                    (event_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return Event.from_row(row)

    def update_alert_record(self, record_id: str, **kwargs: object) -> None:
        """Update specific fields of an alert record.

        Only update the fields passed as kwargs.
        """
        if not kwargs:
            return

        set_clause = ", ".join(f"{key} = %s" for key in kwargs)
        values = list(kwargs.values())
        values.append(record_id)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE alert_records SET {set_clause} WHERE id = %s",
                    values,
                )
        self.logger.debug("Alert record updated: %s", record_id)

    def cleanup_old_records(self, article_days: int, event_days: int) -> int:
        """Delete articles older than article_days and events older than event_days.

        Returns total number of records deleted.
        Also deletes classifications and alert_records for deleted articles/events.
        """
        total_deleted = 0

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                # Delete classifications for old articles
                cur.execute(
                    "DELETE FROM classifications WHERE article_id IN "
                    "(SELECT id FROM articles WHERE fetched_at < NOW() - make_interval(days => %s))",
                    (article_days,),
                )
                total_deleted += cur.rowcount

                # Delete old articles
                cur.execute(
                    "DELETE FROM articles WHERE fetched_at < NOW() - make_interval(days => %s)",
                    (article_days,),
                )
                total_deleted += cur.rowcount

                # Delete alert_records for old events
                cur.execute(
                    "DELETE FROM alert_records WHERE event_id IN "
                    "(SELECT id FROM events WHERE first_seen_at < NOW() - make_interval(days => %s))",
                    (event_days,),
                )
                total_deleted += cur.rowcount

                # Delete old events
                cur.execute(
                    "DELETE FROM events WHERE first_seen_at < NOW() - make_interval(days => %s)",
                    (event_days,),
                )
                total_deleted += cur.rowcount

        self.logger.info("Cleanup: deleted %d old records", total_deleted)
        return total_deleted

    # ------------------------------------------------------------------
    # Tier methods
    # ------------------------------------------------------------------

    def insert_tier(self, tier: Tier) -> bool:
        """Insert a tier. Returns False if tier name already exists (duplicate), True if inserted."""
        data = tier.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO tiers ({columns}) VALUES ({placeholders}) "
                    "ON CONFLICT (name) DO NOTHING RETURNING id",
                    _adapt_values(list(data.values())),
                )
                result = cur.fetchone()

        if result is None:
            self.logger.debug("Duplicate tier skipped: %s", tier.name)
            return False

        self.logger.debug("Tier inserted: %s", tier.name)
        return True

    def get_tier_by_id(self, tier_id: str) -> Tier | None:
        """Return the Tier with the given ID, or None if not found."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM tiers WHERE id = %s LIMIT 1",
                    (tier_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return Tier.from_row(row)

    def get_all_tiers(self) -> list[Tier]:
        """Return all tiers ordered by name."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tiers ORDER BY name")
                return [Tier.from_row(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # User methods
    # ------------------------------------------------------------------

    def insert_user(self, user: User) -> None:
        """Insert a user."""
        data = user.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO users ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("User inserted: %s", user.name)

    def get_user_by_id(self, user_id: str) -> User | None:
        """Return the User with the given ID, or None if not found."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE id = %s LIMIT 1",
                    (user_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return User.from_row(row)

    def get_active_users(self) -> list[User]:
        """Return all active users."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE is_active = TRUE ORDER BY name"
                )
                return [User.from_row(row) for row in cur.fetchall()]

    def get_users_by_country(self, country_code: str) -> list[User]:
        """Return active users whose monitored countries include the given code."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT u.* FROM users u "
                    "JOIN user_countries uc ON u.id = uc.user_id "
                    "WHERE u.is_active = TRUE AND uc.country_code = %s "
                    "ORDER BY u.name",
                    (country_code,),
                )
                return [User.from_row(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # User country methods
    # ------------------------------------------------------------------

    def insert_user_country(self, user_id: str, country_code: str) -> None:
        """Associate a country with a user (idempotent)."""
        row_id = str(uuid4())
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_countries (id, user_id, country_code) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (user_id, country_code) DO NOTHING",
                    (row_id, user_id, country_code),
                )
        self.logger.debug("User country added: user=%s country=%s", user_id, country_code)

    def get_user_countries(self, user_id: str) -> list[str]:
        """Return country codes associated with a user."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT country_code FROM user_countries "
                    "WHERE user_id = %s ORDER BY country_code",
                    (user_id,),
                )
                return [row["country_code"] for row in cur.fetchall()]

    def delete_user_countries(self, user_id: str) -> None:
        """Delete all country associations for a user."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_countries WHERE user_id = %s",
                    (user_id,),
                )
        self.logger.debug("User countries deleted for user: %s", user_id)

    # ------------------------------------------------------------------
    # User alert rule methods
    # ------------------------------------------------------------------

    def insert_user_alert_rule(self, rule: UserAlertRule) -> None:
        """Insert a user alert rule."""
        data = rule.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO user_alert_rules ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("User alert rule inserted: %s", rule.id)

    def get_user_alert_rules(self, user_id: str) -> list[UserAlertRule]:
        """Return alert rules for a user, ordered by priority descending."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM user_alert_rules "
                    "WHERE user_id = %s ORDER BY priority DESC",
                    (user_id,),
                )
                return [UserAlertRule.from_row(row) for row in cur.fetchall()]

    def delete_user_alert_rules(self, user_id: str) -> None:
        """Delete all alert rules for a user (bulk delete for rule replacement)."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_alert_rules WHERE user_id = %s",
                    (user_id,),
                )
        self.logger.debug("User alert rules deleted for user: %s", user_id)

    # ------------------------------------------------------------------
    # Confirmation code methods
    # ------------------------------------------------------------------

    def insert_confirmation_code(self, code: ConfirmationCode) -> None:
        """Insert a confirmation code."""
        data = code.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("%s" for _ in data)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO confirmation_codes ({columns}) VALUES ({placeholders})",
                    _adapt_values(list(data.values())),
                )
        self.logger.debug("Confirmation code inserted: %s", code.id)

    def get_active_confirmation_code(
        self, user_id: str, event_id: str
    ) -> ConfirmationCode | None:
        """Return the most recent unused confirmation code for a user+event, or None."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM confirmation_codes "
                    "WHERE user_id = %s AND event_id = %s AND used_at IS NULL "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, event_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return ConfirmationCode.from_row(row)

    def mark_confirmation_code_used(self, code_id: str) -> None:
        """Mark a confirmation code as used (set used_at to NOW())."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE confirmation_codes SET used_at = NOW() WHERE id = %s",
                    (code_id,),
                )
        self.logger.debug("Confirmation code marked used: %s", code_id)

    def close(self) -> None:
        """Close the connection pool."""
        self.pool.close()
        self.logger.debug("Database connection pool closed")
