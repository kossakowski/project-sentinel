#!/usr/bin/env python3
"""Seed the tiers table with Standard and Premium tier definitions.

Usage:
    python scripts/seed_tiers.py --database-url postgresql://sentinel:sentinel@localhost:5432/sentinel

Or set DATABASE_URL environment variable:
    DATABASE_URL=postgresql://... python scripts/seed_tiers.py

Idempotent: safe to run multiple times (uses INSERT ... ON CONFLICT DO NOTHING).
"""

import argparse
import json
import os
import sys
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


# Deterministic UUIDs based on tier names so every import/call produces the same IDs.
STANDARD_TIER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentinel-tier-standard"))
PREMIUM_TIER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "sentinel-tier-premium"))

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


def seed_tiers(database_url: str) -> None:
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
    print("Tier seeding complete. Standard and Premium tiers ensured.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed tier definitions into the database.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string (default: DATABASE_URL env var)",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: No database URL provided. Use --database-url or set DATABASE_URL.", file=sys.stderr)
        sys.exit(1)

    seed_tiers(args.database_url)


if __name__ == "__main__":
    main()
