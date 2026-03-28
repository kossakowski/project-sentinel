#!/usr/bin/env python3
"""Create an initial user in the Project Sentinel PostgreSQL database.

Usage:
    python scripts/create_initial_user.py --name "Jan Kowalski" --phone "+48123456789" \\
        --tier Premium --countries PL,LT,LV,EE --pg-url postgresql://...

Or set DATABASE_URL:
    DATABASE_URL=postgresql://... python scripts/create_initial_user.py \\
        --name "Jan" --phone "+48123456789" --tier Premium --countries PL

Validates:
  - Tier exists in the database
  - Country count does not exceed tier.max_countries
  - For Premium (customizable) tier, creates default user_alert_rules
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


# Default alert rules matching the current urgency level config:
# 9-10: phone_call, 7-8: sms, 5-6: whatsapp, 1-4: log_only
DEFAULT_ALERT_RULES = [
    {"min_urgency": 9, "max_urgency": 10, "channel": "phone_call", "corroboration_required": 1, "priority": 40},
    {"min_urgency": 7, "max_urgency": 8, "channel": "sms", "corroboration_required": 1, "priority": 30},
    {"min_urgency": 5, "max_urgency": 6, "channel": "whatsapp", "corroboration_required": 1, "priority": 20},
    {"min_urgency": 1, "max_urgency": 4, "channel": "log_only", "corroboration_required": 1, "priority": 10},
]


def create_user(
    name: str,
    phone: str,
    tier_name: str,
    countries: list[str],
    pg_url: str,
) -> str:
    """Create a user with the given parameters.

    Returns the user ID on success.
    Raises SystemExit on validation failure.
    """
    with psycopg.connect(pg_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Validate tier exists
            cur.execute(
                "SELECT id, name, max_countries, preference_mode FROM tiers "
                "WHERE name = %s AND is_active = TRUE LIMIT 1",
                (tier_name,),
            )
            tier_row = cur.fetchone()
            if tier_row is None:
                print(
                    f"ERROR: Tier '{tier_name}' not found or not active. "
                    "Run seed_tiers.py first.",
                    file=sys.stderr,
                )
                sys.exit(1)

            tier_id = tier_row["id"]
            max_countries = tier_row["max_countries"]
            preference_mode = tier_row["preference_mode"]

            # Validate country count
            if max_countries is not None and len(countries) > max_countries:
                print(
                    f"ERROR: Tier '{tier_name}' allows at most {max_countries} "
                    f"countries, but {len(countries)} were requested: {countries}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Create user
            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            cur.execute(
                "INSERT INTO users (id, name, phone_number, language, tier_id, "
                "is_active, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, name, phone, "pl", tier_id, True, now, now),
            )
            print(f"Created user '{name}' (id={user_id}) on tier '{tier_name}'")

            # Insert user_countries
            for code in countries:
                cur.execute(
                    "INSERT INTO user_countries (id, user_id, country_code) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (user_id, country_code) DO NOTHING",
                    (str(uuid.uuid4()), user_id, code),
                )
            print(f"  Countries: {', '.join(countries)}")

            # For customizable tiers, create default alert rules
            if preference_mode == "customizable":
                for rule in DEFAULT_ALERT_RULES:
                    cur.execute(
                        "INSERT INTO user_alert_rules "
                        "(id, user_id, min_urgency, max_urgency, channel, "
                        "corroboration_required, priority) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            str(uuid.uuid4()),
                            user_id,
                            rule["min_urgency"],
                            rule["max_urgency"],
                            rule["channel"],
                            rule["corroboration_required"],
                            rule["priority"],
                        ),
                    )
                print("  Default alert rules created (customizable tier).")
            else:
                print(f"  Tier uses preset rules (mode={preference_mode}), no user_alert_rules needed.")

        conn.commit()

    print()
    print("User created successfully.")
    return user_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an initial user in the Project Sentinel database."
    )
    parser.add_argument(
        "--name",
        required=True,
        help="User display name",
    )
    parser.add_argument(
        "--phone",
        required=True,
        help="Phone number in E.164 format (e.g. +48123456789)",
    )
    parser.add_argument(
        "--tier",
        required=True,
        help="Tier name (e.g. 'Standard' or 'Premium'). Must exist in database.",
    )
    parser.add_argument(
        "--countries",
        required=True,
        help="Comma-separated country codes (e.g. PL,LT,LV,EE)",
    )
    parser.add_argument(
        "--pg-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string (default: DATABASE_URL env var)",
    )
    args = parser.parse_args()

    if not args.pg_url:
        print(
            "ERROR: No PostgreSQL URL provided. Use --pg-url or set DATABASE_URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    if not countries:
        print("ERROR: No countries provided.", file=sys.stderr)
        sys.exit(1)

    create_user(args.name, args.phone, args.tier, countries, args.pg_url)


if __name__ == "__main__":
    main()
