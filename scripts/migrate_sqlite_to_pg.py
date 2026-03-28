#!/usr/bin/env python3
"""One-shot migration script: SQLite (data/sentinel.db) -> PostgreSQL.

Copies all data from the 4 existing SQLite tables (articles, classifications,
events, alert_records) to their PostgreSQL equivalents, converting types along
the way (ISO dates -> TIMESTAMPTZ, integer booleans -> BOOLEAN, JSON text ->
JSONB).

Also seeds tiers, creates the primary user from env vars, and backfills
alert_records.user_id to point at that user.

Usage:
    python scripts/migrate_sqlite_to_pg.py
    python scripts/migrate_sqlite_to_pg.py --sqlite-path data/sentinel.db --pg-url postgresql://...

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING for all inserts.
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# ---------------------------------------------------------------------------
# Re-use tier seeding from seed_tiers.py
# ---------------------------------------------------------------------------

# Deterministic UUIDs -- must match seed_tiers.py
PREMIUM_TIER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentinel-tier-premium"))

# Inline the seed_tiers logic so the script is self-contained.
# We import if available, otherwise define locally.
try:
    from seed_tiers import seed_tiers
except ImportError:
    # Running from project root or another location -- define inline
    STANDARD_TIER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentinel-tier-standard"))

    TIERS = [
        {
            "id": STANDARD_TIER_ID,
            "name": "Standard",
            "available_channels": ["phone_call", "sms", "whatsapp"],
            "max_countries": 1,
            "preference_mode": "preset",
            "preset_rules": {
                "9-10": "phone_call",
                "7-8": "sms",
                "5-6": "whatsapp",
                "1-4": "log_only",
            },
            "is_active": True,
        },
        {
            "id": PREMIUM_TIER_ID,
            "name": "Premium",
            "available_channels": ["phone_call", "sms", "whatsapp"],
            "max_countries": None,
            "preference_mode": "customizable",
            "preset_rules": None,
            "is_active": True,
        },
    ]

    def seed_tiers(database_url: str) -> None:  # noqa: F811
        """Insert Standard and Premium tiers (idempotent)."""
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                for tier in TIERS:
                    cur.execute(
                        "INSERT INTO tiers (id, name, available_channels, max_countries, "
                        "preference_mode, preset_rules, is_active) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (name) DO NOTHING",
                        (
                            tier["id"],
                            tier["name"],
                            Jsonb(tier["available_channels"]),
                            tier["max_countries"],
                            tier["preference_mode"],
                            Jsonb(tier["preset_rules"]) if tier["preset_rules"] is not None else None,
                            tier["is_active"],
                        ),
                    )
            conn.commit()
        print("  Tier seeding complete.")


# ---------------------------------------------------------------------------
# Type conversion helpers
# ---------------------------------------------------------------------------

def _convert_iso_to_datetime(value: str | None) -> datetime | None:
    """Convert an ISO date string to a timezone-aware datetime, or None."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _convert_int_bool(value: int | None) -> bool | None:
    """Convert an integer boolean (0/1) to a native Python bool."""
    if value is None:
        return None
    return bool(int(value))


def _convert_json_text(value: str | None) -> Jsonb | None:
    """Convert a JSON text string to a psycopg Jsonb wrapper."""
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return Jsonb(value)
    return Jsonb(parsed)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_target_countries(config_path: str = "config/config.yaml") -> list[str]:
    """Load target country codes from config.yaml."""
    # Try a few common locations
    search_paths = [
        config_path,
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config_path),
    ]
    for path in search_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            countries = raw.get("monitoring", {}).get("target_countries", [])
            return [c["code"] for c in countries]

    # Fallback: return the known defaults
    print(f"  WARNING: Could not find {config_path}. Using default countries: PL, LT, LV, EE", file=sys.stderr)
    return ["PL", "LT", "LV", "EE"]


# ---------------------------------------------------------------------------
# Table migration definitions
# ---------------------------------------------------------------------------

# Column metadata: (column_name, conversion_function_or_None)
# None means pass-through (no conversion needed)

ARTICLES_COLUMNS = [
    ("id", None),
    ("source_name", None),
    ("source_url", None),
    ("source_type", None),
    ("title", None),
    ("summary", None),
    ("language", None),
    ("published_at", _convert_iso_to_datetime),
    ("fetched_at", _convert_iso_to_datetime),
    ("url_hash", None),
    ("title_normalized", None),
    ("raw_metadata", _convert_json_text),
]

CLASSIFICATIONS_COLUMNS = [
    ("id", None),
    ("article_id", None),
    ("is_military_event", _convert_int_bool),
    ("event_type", None),
    ("urgency_score", None),
    ("affected_countries", _convert_json_text),
    ("aggressor", None),
    ("is_new_event", _convert_int_bool),
    ("confidence", None),
    ("summary_pl", None),
    ("classified_at", _convert_iso_to_datetime),
    ("model_used", None),
    ("input_tokens", None),
    ("output_tokens", None),
]

EVENTS_COLUMNS = [
    ("id", None),
    ("event_type", None),
    ("urgency_score", None),
    ("affected_countries", _convert_json_text),
    ("aggressor", None),
    ("summary_pl", None),
    ("first_seen_at", _convert_iso_to_datetime),
    ("last_updated_at", _convert_iso_to_datetime),
    ("source_count", None),
    ("article_ids", _convert_json_text),
    ("alert_status", None),
    ("acknowledged_at", _convert_iso_to_datetime),
]

ALERT_RECORDS_COLUMNS = [
    ("id", None),
    ("event_id", None),
    ("alert_type", None),
    ("twilio_sid", None),
    ("status", None),
    ("duration_seconds", None),
    ("attempt_number", None),
    ("sent_at", _convert_iso_to_datetime),
    ("message_body", None),
    # user_id is not in old SQLite schema; we backfill separately
]


# ---------------------------------------------------------------------------
# Core migration logic
# ---------------------------------------------------------------------------

def _migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg.Connection,
    table_name: str,
    columns: list[tuple[str, object]],
    conflict_column: str,
) -> int:
    """Migrate one table from SQLite to PostgreSQL.

    Returns the number of rows read from SQLite.
    """
    col_names = [c[0] for c in columns]
    converters = [c[1] for c in columns]

    # Read all rows from SQLite
    sqlite_cursor = sqlite_conn.execute(f"SELECT {', '.join(col_names)} FROM {table_name}")
    rows = sqlite_cursor.fetchall()

    if not rows:
        return 0

    # Build the INSERT statement
    placeholders = ", ".join("%s" for _ in col_names)
    col_list = ", ".join(col_names)
    insert_sql = (
        f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_column}) DO NOTHING"
    )

    with pg_conn.cursor() as cur:
        for row in rows:
            converted = []
            for i, value in enumerate(row):
                converter = converters[i]
                if converter is not None and value is not None:
                    converted.append(converter(value))
                else:
                    converted.append(value)
            cur.execute(insert_sql, converted)

    return len(rows)


def migrate(sqlite_path: str, pg_url: str, config_path: str = "config/config.yaml") -> dict:
    """Run the full migration from SQLite to PostgreSQL.

    Returns a dict with source and destination row counts per table.
    """
    # 4.8: Handle missing SQLite file
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite file not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Migration: {sqlite_path} -> PostgreSQL")
    print()

    # 4.3: Seed tiers first
    print("Step 1: Seeding tiers...")
    seed_tiers(pg_url)
    print()

    # 4.4: Create primary user
    print("Step 2: Creating primary user...")
    phone = os.environ.get("ALERT_PHONE_NUMBER", "")
    name = os.environ.get("ALERT_USER_NAME", "Primary User")
    user_id = str(uuid.uuid4())

    if not phone:
        print("  WARNING: ALERT_PHONE_NUMBER not set. Using empty string for phone.")

    target_countries = _load_target_countries(config_path)
    print(f"  User: {name}, Phone: {phone}, Tier: Premium")
    print(f"  Countries: {', '.join(target_countries)}")

    with psycopg.connect(pg_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Insert user (idempotent by phone number -- use a deterministic ID based on phone)
            # For idempotency, we use ON CONFLICT on the primary key.
            # Since we don't have a unique constraint on phone, we check first.
            cur.execute(
                "SELECT id FROM users WHERE phone_number = %s LIMIT 1",
                (phone,),
            )
            existing = cur.fetchone()
            if existing:
                user_id = existing["id"]
                print(f"  User already exists with id={user_id}")
            else:
                now = datetime.now(timezone.utc)
                cur.execute(
                    "INSERT INTO users (id, name, phone_number, language, tier_id, "
                    "is_active, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (user_id, name, phone, "pl", PREMIUM_TIER_ID, True, now, now),
                )
                print(f"  Created user with id={user_id}")

            # Insert user_countries (idempotent via UNIQUE constraint)
            for code in target_countries:
                cur.execute(
                    "INSERT INTO user_countries (id, user_id, country_code) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (user_id, country_code) DO NOTHING",
                    (str(uuid.uuid4()), user_id, code),
                )
            print(f"  User countries ensured: {target_countries}")

            # Create default alert rules for Premium customizable tier
            cur.execute(
                "SELECT id FROM user_alert_rules WHERE user_id = %s LIMIT 1",
                (user_id,),
            )
            if cur.fetchone() is None:
                default_rules = [
                    (9, 10, "phone_call", 1, 40),
                    (7, 8, "sms", 1, 30),
                    (5, 6, "whatsapp", 1, 20),
                    (1, 4, "log_only", 1, 10),
                ]
                for min_u, max_u, channel, corr, prio in default_rules:
                    cur.execute(
                        "INSERT INTO user_alert_rules "
                        "(id, user_id, min_urgency, max_urgency, channel, "
                        "corroboration_required, priority) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (str(uuid.uuid4()), user_id, min_u, max_u, channel, corr, prio),
                    )
                print("  Default alert rules created.")
            else:
                print("  Alert rules already exist, skipping.")
        conn.commit()
    print()

    # Connect to both databases
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    report = {}

    print("Step 3: Migrating data...")
    tables = [
        ("articles", ARTICLES_COLUMNS, "id"),
        ("classifications", CLASSIFICATIONS_COLUMNS, "id"),
        ("events", EVENTS_COLUMNS, "id"),
        ("alert_records", ALERT_RECORDS_COLUMNS, "id"),
    ]

    with psycopg.connect(pg_url, row_factory=dict_row) as pg_conn:
        for table_name, columns, conflict_col in tables:
            source_count = _migrate_table(sqlite_conn, pg_conn, table_name, columns, conflict_col)
            report[table_name] = {"source": source_count}
            print(f"  {table_name}: {source_count} rows read from SQLite")
        pg_conn.commit()

    # 4.5: Backfill alert_records.user_id to the primary user
    print()
    print("Step 4: Backfilling alert_records.user_id...")
    with psycopg.connect(pg_url, row_factory=dict_row) as pg_conn:
        with pg_conn.cursor() as cur:
            cur.execute(
                "UPDATE alert_records SET user_id = %s WHERE user_id IS NULL",
                (user_id,),
            )
            backfilled = cur.rowcount
        pg_conn.commit()
    print(f"  Backfilled {backfilled} alert records with user_id={user_id}")

    # 4.6: Validate row counts
    print()
    print("Step 5: Validating data integrity...")
    with psycopg.connect(pg_url, row_factory=dict_row) as pg_conn:
        with pg_conn.cursor() as cur:
            for table_name, _, _ in tables:
                cur.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
                pg_count = cur.fetchone()["cnt"]
                report[table_name]["destination"] = pg_count

    sqlite_conn.close()

    # Print summary report
    print()
    print("=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    all_ok = True
    for table_name in ["articles", "classifications", "events", "alert_records"]:
        src = report[table_name]["source"]
        dst = report[table_name]["destination"]
        if dst == src:
            status = "OK"
        elif dst > src:
            status = "EXTRA"
            all_ok = False
        else:
            status = "MISMATCH"
            all_ok = False
        print(f"  {table_name:20s}  SQLite: {src:6d}  PostgreSQL: {dst:6d}  [{status}]")
    print("=" * 60)
    if all_ok:
        print("All row counts match. Migration successful.")
    else:
        print("WARNING: Some row counts do not match. Check for errors above.")
    print()

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate data from SQLite to PostgreSQL for Project Sentinel."
    )
    parser.add_argument(
        "--sqlite-path",
        default="data/sentinel.db",
        help="Path to the SQLite database file (default: data/sentinel.db)",
    )
    parser.add_argument(
        "--pg-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--config-path",
        default="config/config.yaml",
        help="Path to config.yaml for reading target_countries (default: config/config.yaml)",
    )
    args = parser.parse_args()

    if not args.pg_url:
        print(
            "ERROR: No PostgreSQL URL provided. Use --pg-url or set DATABASE_URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    migrate(args.sqlite_path, args.pg_url, args.config_path)


if __name__ == "__main__":
    main()
