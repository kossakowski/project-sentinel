"""Tests for Phase 4: Migration Script and Seed Data.

Tests both scripts/migrate_sqlite_to_pg.py and scripts/create_initial_user.py
against real PostgreSQL (testcontainers) and real SQLite.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import psycopg
import pytest
from psycopg.rows import dict_row

# The migration and create_initial_user modules live in scripts/
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from migrate_sqlite_to_pg import migrate, _convert_iso_to_datetime, _convert_int_bool, _convert_json_text
from create_initial_user import create_user, DEFAULT_ALERT_RULES
from seed_tiers import PREMIUM_TIER_ID, STANDARD_TIER_ID, seed_tiers


# ---------------------------------------------------------------------------
# Helper: create and populate an SQLite database matching the old schema
# ---------------------------------------------------------------------------

def _create_sqlite_db(path: str) -> sqlite3.Connection:
    """Create a SQLite database with the 4 original tables and sample data."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE articles (
            id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            language TEXT NOT NULL,
            published_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url_hash TEXT NOT NULL UNIQUE,
            title_normalized TEXT NOT NULL,
            raw_metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE classifications (
            id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
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
        )
    """)
    conn.execute("""
        CREATE TABLE events (
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
        )
    """)
    conn.execute("""
        CREATE TABLE alert_records (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            twilio_sid TEXT,
            status TEXT NOT NULL,
            duration_seconds INTEGER,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            sent_at TEXT NOT NULL,
            message_body TEXT
        )
    """)
    conn.commit()
    return conn


def _populate_sqlite(conn: sqlite3.Connection, n_articles: int = 3) -> dict:
    """Insert sample data into all 4 tables. Returns IDs for reference."""
    now_iso = datetime.now(timezone.utc).isoformat()
    article_ids = []
    classification_ids = []
    event_ids = []
    alert_ids = []

    for i in range(n_articles):
        art_id = str(uuid.uuid4())
        article_ids.append(art_id)
        conn.execute(
            "INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                art_id,
                f"Source{i}",
                f"https://example.com/art/{i}",
                "rss",
                f"Test headline {i}",
                f"Summary {i}",
                "en",
                now_iso,
                now_iso,
                f"hash_{i}_{uuid.uuid4().hex[:8]}",
                f"test headline {i}",
                json.dumps({"key": f"val{i}"}),
            ),
        )

        cls_id = str(uuid.uuid4())
        classification_ids.append(cls_id)
        conn.execute(
            "INSERT INTO classifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cls_id,
                art_id,
                1,  # is_military_event as int
                "troop_movement",
                7,
                json.dumps(["PL"]),
                "RU",
                1,  # is_new_event as int
                0.85,
                "Rosja ...",
                now_iso,
                "claude-haiku-4-5",
                287,
                94,
            ),
        )

    # Create one event referencing all articles
    evt_id = str(uuid.uuid4())
    event_ids.append(evt_id)
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            evt_id,
            "troop_movement",
            8,
            json.dumps(["PL", "LT"]),
            "RU",
            "Military operation near border",
            now_iso,
            now_iso,
            n_articles,
            json.dumps(article_ids),
            "pending",
            None,
        ),
    )

    # Create alert records
    for i in range(2):
        alert_id = str(uuid.uuid4())
        alert_ids.append(alert_id)
        conn.execute(
            "INSERT INTO alert_records VALUES (?,?,?,?,?,?,?,?,?)",
            (
                alert_id,
                evt_id,
                "phone_call",
                f"CA{i}abc",
                "initiated",
                None,
                i + 1,
                now_iso,
                "Alert message",
            ),
        )

    conn.commit()
    return {
        "article_ids": article_ids,
        "classification_ids": classification_ids,
        "event_ids": event_ids,
        "alert_ids": alert_ids,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(tmp_path):
    """Create a populated SQLite database file."""
    db_path = str(tmp_path / "test_sentinel.db")
    conn = _create_sqlite_db(db_path)
    ids = _populate_sqlite(conn)
    conn.close()
    return db_path, ids


@pytest.fixture
def empty_sqlite_db(tmp_path):
    """Create an empty SQLite database file (tables exist, no data)."""
    db_path = str(tmp_path / "empty_sentinel.db")
    conn = _create_sqlite_db(db_path)
    conn.close()
    return db_path


@pytest.fixture
def pg_url_for_migration(pg_url, _db_tables):
    """Provide a clean PostgreSQL database URL for migration tests.

    Uses the session-scoped container + tables, but truncates before each test.
    """
    with _db_tables.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE confirmation_codes, alert_records, user_alert_rules, "
                "user_countries, classifications, events, articles, users, tiers CASCADE"
            )
    return pg_url


# ---------------------------------------------------------------------------
# Type conversion unit tests
# ---------------------------------------------------------------------------

class TestTypeConversions:
    """Test the type conversion helper functions."""

    def test_convert_iso_to_datetime_valid(self):
        dt = _convert_iso_to_datetime("2026-03-28T10:30:00+00:00")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_convert_iso_to_datetime_naive(self):
        """Naive ISO strings should get UTC timezone."""
        dt = _convert_iso_to_datetime("2026-03-28T10:30:00")
        assert dt.tzinfo is not None

    def test_convert_iso_to_datetime_none(self):
        assert _convert_iso_to_datetime(None) is None

    def test_convert_int_bool_true(self):
        assert _convert_int_bool(1) is True

    def test_convert_int_bool_false(self):
        assert _convert_int_bool(0) is False

    def test_convert_int_bool_none(self):
        assert _convert_int_bool(None) is None

    def test_convert_json_text_list(self):
        result = _convert_json_text('["PL", "LT"]')
        # Result should be a Jsonb wrapper
        assert result is not None

    def test_convert_json_text_dict(self):
        result = _convert_json_text('{"key": "value"}')
        assert result is not None

    def test_convert_json_text_none(self):
        assert _convert_json_text(None) is None


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------

class TestMigration:
    """Test the full migration from SQLite to PostgreSQL."""

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333", "ALERT_USER_NAME": "Test Migrator"})
    def test_migrate_copies_all_rows(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.2 + 4.6: All rows from 4 tables are copied and counts match."""
        db_path, ids = sqlite_db

        # Create a minimal config.yaml in tmp_path for country loading
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({
                "monitoring": {
                    "target_countries": [
                        {"code": "PL", "name": "Poland", "name_native": "Polska"},
                        {"code": "LT", "name": "Lithuania", "name_native": "Litwa"},
                    ]
                }
            }, f)

        report = migrate(db_path, pg_url_for_migration, config_path)

        assert report["articles"]["source"] == 3
        assert report["articles"]["destination"] >= 3
        assert report["classifications"]["source"] == 3
        assert report["classifications"]["destination"] >= 3
        assert report["events"]["source"] == 1
        assert report["events"]["destination"] >= 1
        assert report["alert_records"]["source"] == 2
        assert report["alert_records"]["destination"] >= 2

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333", "ALERT_USER_NAME": "Test Migrator"})
    def test_migrate_type_conversions(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.2: ISO dates -> TIMESTAMPTZ, int booleans -> BOOLEAN, JSON text -> JSONB."""
        db_path, ids = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        migrate(db_path, pg_url_for_migration, config_path)

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Check articles: published_at should be a datetime, raw_metadata should be dict
                cur.execute("SELECT published_at, fetched_at, raw_metadata FROM articles LIMIT 1")
                row = cur.fetchone()
                assert isinstance(row["published_at"], datetime)
                assert isinstance(row["fetched_at"], datetime)
                assert isinstance(row["raw_metadata"], dict)

                # Check classifications: booleans should be bool, affected_countries JSONB
                cur.execute(
                    "SELECT is_military_event, is_new_event, affected_countries "
                    "FROM classifications LIMIT 1"
                )
                row = cur.fetchone()
                assert isinstance(row["is_military_event"], bool)
                assert row["is_military_event"] is True
                assert isinstance(row["is_new_event"], bool)
                assert isinstance(row["affected_countries"], list)

                # Check events: JSONB columns
                cur.execute("SELECT affected_countries, article_ids FROM events LIMIT 1")
                row = cur.fetchone()
                assert isinstance(row["affected_countries"], list)
                assert isinstance(row["article_ids"], list)

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333"})
    def test_migrate_idempotent(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.7: Running migration twice does not create duplicates."""
        db_path, ids = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        report1 = migrate(db_path, pg_url_for_migration, config_path)
        report2 = migrate(db_path, pg_url_for_migration, config_path)

        # Destination counts should not double
        assert report2["articles"]["destination"] == report1["articles"]["destination"]
        assert report2["classifications"]["destination"] == report1["classifications"]["destination"]
        assert report2["events"]["destination"] == report1["events"]["destination"]
        assert report2["alert_records"]["destination"] == report1["alert_records"]["destination"]

    def test_migrate_missing_sqlite_file(self, pg_url_for_migration, tmp_path):
        """4.8: Missing SQLite file prints error and exits 1."""
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": []}}, f)

        with pytest.raises(SystemExit) as exc_info:
            migrate("/nonexistent/path/sentinel.db", pg_url_for_migration, config_path)
        assert exc_info.value.code == 1

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333", "ALERT_USER_NAME": "Test User"})
    def test_migrate_creates_primary_user(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.4: Migration creates user from env vars with Premium tier."""
        db_path, _ = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({
                "monitoring": {
                    "target_countries": [
                        {"code": "PL", "name": "Poland", "name_native": "Polska"},
                        {"code": "LT", "name": "Lithuania", "name_native": "Litwa"},
                    ]
                }
            }, f)

        migrate(db_path, pg_url_for_migration, config_path)

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE phone_number = %s", ("+48111222333",))
                user = cur.fetchone()
                assert user is not None
                assert user["name"] == "Test User"
                assert user["tier_id"] == PREMIUM_TIER_ID

                # Check countries
                cur.execute(
                    "SELECT country_code FROM user_countries WHERE user_id = %s ORDER BY country_code",
                    (user["id"],),
                )
                countries = [r["country_code"] for r in cur.fetchall()]
                assert "PL" in countries
                assert "LT" in countries

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333"})
    def test_migrate_backfills_user_id(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.5: alert_records.user_id is set to the migrated primary user."""
        db_path, _ = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        migrate(db_path, pg_url_for_migration, config_path)

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM alert_records")
                rows = cur.fetchall()
                assert len(rows) == 2
                for row in rows:
                    assert row["user_id"] is not None

                # Verify user_id matches the created user
                cur.execute("SELECT id FROM users LIMIT 1")
                user = cur.fetchone()
                for row in rows:
                    assert row["user_id"] == user["id"]

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333"})
    def test_migrate_seeds_tiers(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.3: Tiers are seeded before data migration."""
        db_path, _ = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        migrate(db_path, pg_url_for_migration, config_path)

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM tiers ORDER BY name")
                tiers = [r["name"] for r in cur.fetchall()]
                assert "Standard" in tiers
                assert "Premium" in tiers

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333"})
    def test_migrate_empty_sqlite(self, empty_sqlite_db, pg_url_for_migration, tmp_path):
        """Migration works with an empty SQLite database (0 rows)."""
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        report = migrate(empty_sqlite_db, pg_url_for_migration, config_path)
        assert report["articles"]["source"] == 0
        assert report["articles"]["destination"] == 0

    @patch.dict(os.environ, {"ALERT_PHONE_NUMBER": "+48111222333"})
    def test_migrate_creates_default_alert_rules(self, sqlite_db, pg_url_for_migration, tmp_path):
        """4.4/4.9: Premium user gets default alert rules."""
        db_path, _ = sqlite_db
        config_path = str(tmp_path / "config.yaml")
        import yaml
        with open(config_path, "w") as f:
            yaml.dump({"monitoring": {"target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}]}}, f)

        migrate(db_path, pg_url_for_migration, config_path)

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users LIMIT 1")
                user = cur.fetchone()
                cur.execute(
                    "SELECT min_urgency, max_urgency, channel FROM user_alert_rules "
                    "WHERE user_id = %s ORDER BY priority DESC",
                    (user["id"],),
                )
                rules = cur.fetchall()
                assert len(rules) == 4
                # Highest priority: phone_call for 9-10
                assert rules[0]["min_urgency"] == 9
                assert rules[0]["max_urgency"] == 10
                assert rules[0]["channel"] == "phone_call"
                # Lowest priority: log_only for 1-4
                assert rules[3]["min_urgency"] == 1
                assert rules[3]["max_urgency"] == 4
                assert rules[3]["channel"] == "log_only"


# ---------------------------------------------------------------------------
# create_initial_user tests
# ---------------------------------------------------------------------------

class TestCreateInitialUser:
    """Tests for scripts/create_initial_user.py."""

    def test_create_user_premium(self, pg_url_for_migration):
        """4.9: Create a Premium user with default alert rules."""
        seed_tiers(pg_url_for_migration)

        user_id = create_user(
            name="Premium User",
            phone="+48999888777",
            tier_name="Premium",
            countries=["PL", "LT", "LV", "EE"],
            pg_url=pg_url_for_migration,
        )

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()
                assert user["name"] == "Premium User"
                assert user["phone_number"] == "+48999888777"
                assert user["tier_id"] == PREMIUM_TIER_ID

                cur.execute(
                    "SELECT country_code FROM user_countries WHERE user_id = %s ORDER BY country_code",
                    (user_id,),
                )
                countries = [r["country_code"] for r in cur.fetchall()]
                assert countries == ["EE", "LT", "LV", "PL"]

                cur.execute(
                    "SELECT * FROM user_alert_rules WHERE user_id = %s ORDER BY priority DESC",
                    (user_id,),
                )
                rules = cur.fetchall()
                assert len(rules) == 4

    def test_create_user_standard(self, pg_url_for_migration):
        """4.9: Standard tier user gets no user_alert_rules (preset mode)."""
        seed_tiers(pg_url_for_migration)

        user_id = create_user(
            name="Standard User",
            phone="+48111000111",
            tier_name="Standard",
            countries=["PL"],
            pg_url=pg_url_for_migration,
        )

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM user_alert_rules WHERE user_id = %s",
                    (user_id,),
                )
                rules = cur.fetchall()
                assert len(rules) == 0  # preset mode -> no custom rules

    def test_create_user_tier_not_found(self, pg_url_for_migration):
        """4.9: Non-existent tier causes exit(1)."""
        seed_tiers(pg_url_for_migration)

        with pytest.raises(SystemExit) as exc_info:
            create_user(
                name="Nobody",
                phone="+48000000000",
                tier_name="NonExistentTier",
                countries=["PL"],
                pg_url=pg_url_for_migration,
            )
        assert exc_info.value.code == 1

    def test_create_user_country_limit_exceeded(self, pg_url_for_migration):
        """4.9: Standard tier max_countries=1; requesting 3 causes exit(1)."""
        seed_tiers(pg_url_for_migration)

        with pytest.raises(SystemExit) as exc_info:
            create_user(
                name="Too Many Countries",
                phone="+48000000000",
                tier_name="Standard",
                countries=["PL", "LT", "LV"],
                pg_url=pg_url_for_migration,
            )
        assert exc_info.value.code == 1

    def test_create_user_premium_unlimited_countries(self, pg_url_for_migration):
        """4.9: Premium tier has max_countries=NULL (unlimited)."""
        seed_tiers(pg_url_for_migration)

        # Should not raise even with many countries
        user_id = create_user(
            name="Global Watcher",
            phone="+48222333444",
            tier_name="Premium",
            countries=["PL", "LT", "LV", "EE", "DE", "FR", "UA"],
            pg_url=pg_url_for_migration,
        )

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM user_countries WHERE user_id = %s",
                    (user_id,),
                )
                assert cur.fetchone()["cnt"] == 7

    def test_create_user_default_rules_match_config(self, pg_url_for_migration):
        """4.9: Default rules for Premium match current urgency level config."""
        seed_tiers(pg_url_for_migration)

        user_id = create_user(
            name="Config Verifier",
            phone="+48555666777",
            tier_name="Premium",
            countries=["PL"],
            pg_url=pg_url_for_migration,
        )

        with psycopg.connect(pg_url_for_migration, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT min_urgency, max_urgency, channel "
                    "FROM user_alert_rules WHERE user_id = %s "
                    "ORDER BY min_urgency",
                    (user_id,),
                )
                rules = cur.fetchall()
                expected = [
                    (1, 4, "log_only"),
                    (5, 6, "whatsapp"),
                    (7, 8, "sms"),
                    (9, 10, "phone_call"),
                ]
                for rule, (min_u, max_u, channel) in zip(rules, expected):
                    assert rule["min_urgency"] == min_u
                    assert rule["max_urgency"] == max_u
                    assert rule["channel"] == channel
