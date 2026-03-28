# CHANGE-SPEC: Multi-Tenant Evolution

## Overview

Migrate Project Sentinel from a single-user SQLite system to a multi-tenant PostgreSQL system. This involves four phases: replacing the database driver and SQL dialect, adding multi-tenant schema with a data-driven tier system, reworking alert routing to iterate over matching users per event, and building a one-shot migration script with seed data. The fetch/classify/corroborate pipeline is untouched — changes are confined to the database layer, models, config, alert routing, and tests.

## Current State

- **Database**: SQLite via `sqlite3` module. Single connection, WAL mode. File-based (`data/sentinel.db`). 4 tables: `articles`, `classifications`, `events`, `alert_records`. All SQL uses SQLite-specific functions: `datetime('now', ...)`, `PRAGMA journal_mode=WAL`, `sqlite_master`, `?` parameter placeholders.
- **Models**: 4 dataclasses in `models.py` with `from_row(sqlite3.Row)` class methods. Boolean fields stored as INTEGER (0/1). Dates stored as ISO text strings.
- **Config**: `DatabaseConfig` has a `path: str` field. `AlertsConfig` has a single `phone_number: str`.
- **Alerts**: `AlertStateMachine` reads `config.alerts.phone_number` (one user) for every alert method. Confirmation codes stored in-memory as `self._confirmation_code` (lost on restart). `AlertDispatcher` calls `state_machine.process_event(event)` for each event. `TwilioClient` already takes `phone_number` as a parameter — it is decoupled.
- **Tests**: 163 passing. `conftest.py` creates `Database(tmp_path / "test.db")`. Several tests do raw `db.conn.execute(...)` with SQLite SQL. Test fixtures use `sample_config_dict` with `database.path`.

## Desired State

- **Database**: PostgreSQL via `psycopg` (v3). Connection pooling via `psycopg_pool.ConnectionPool`. All SQL uses PostgreSQL syntax: `NOW() - INTERVAL`, `%s` placeholders, `BOOLEAN` type, `TIMESTAMPTZ` type, `JSONB` type. No SQLite dependency anywhere.
- **Models**: `from_row()` accepts `psycopg.rows.DictRow` instead of `sqlite3.Row`. Booleans stored as native BOOLEAN. Dates stored as TIMESTAMPTZ. JSON columns use JSONB.
- **Config**: `DatabaseConfig` has `url: str` (PostgreSQL connection string, e.g. `postgresql://sentinel:pass@localhost:5432/sentinel`). `AlertsConfig.phone_number` removed. Single-user phone number replaced by per-user phone numbers in `users` table.
- **Schema**: 5 new tables (`users`, `tiers`, `user_countries`, `user_alert_rules`, `confirmation_codes`). `alert_records` gains a `user_id` column.
- **Alerts**: `AlertStateMachine.process_event(event)` queries matching users (by country overlap), iterates over each, and applies per-user rules from their tier/custom config. Confirmation codes stored in `confirmation_codes` table (persistent, per-user, per-event). Per-user cooldowns and acknowledgment tracking.
- **Tests**: All 163 tests pass against PostgreSQL via `testcontainers-python`. No SQLite in the test suite.

## Non-Goals

- No billing, payment, or subscription management.
- No REST API, admin dashboard, or web UI.
- No authentication or authorization layer.
- No changes to fetchers, normalizer, deduplicator, keyword filter, classifier, or corroborator.
- No Alembic or migration framework — one-shot script only.
- No SQLite fallback or backward compatibility mode.
- No execution on production server — all work is local.
- No multi-language alert templates (Polish only for now; `language` field is stored for future use).

## Phase 1: Database Migration (SQLite to PostgreSQL)

### Deliverables

- `sentinel/database.py` — rewritten to use `psycopg` (v3) with `psycopg_pool.ConnectionPool`, PostgreSQL SQL syntax, and `%s` placeholders
- `sentinel/models.py` — `from_row()` methods updated to accept `dict` (from `psycopg` `DictRow` via `row_factory=dict_row`)
- `sentinel/config.py` — `DatabaseConfig.path` replaced with `DatabaseConfig.url`
- `config/config.example.yaml` — `database.path` replaced with `database.url` example
- `tests/conftest.py` — `db` fixture rewritten to use `testcontainers.postgres.PostgresContainer`
- `tests/test_database.py` — all raw SQL updated from SQLite to PostgreSQL syntax
- `tests/test_corroborator.py`, `tests/test_deduplicator.py`, `tests/test_integration.py`, `tests/test_state_machine.py`, `tests/test_scheduler.py` — adapted for PostgreSQL where they touch the database
- `requirements.txt` — `psycopg[binary]`, `psycopg_pool`, `testcontainers[postgres]` added; `sqlite3` references removed (stdlib, no package to remove)

### Requirements

**1.1** `Database.__init__` MUST accept a `url: str` parameter (PostgreSQL connection string) instead of `db_path: str`. It MUST create a `psycopg_pool.ConnectionPool` with `min_size=1, max_size=5` and configure `row_factory=dict_row` on the pool.

**1.2** `Database._create_tables()` MUST use PostgreSQL DDL. Columns that were `TEXT` for ISO dates MUST become `TIMESTAMPTZ`. Columns that were `INTEGER` for booleans MUST become `BOOLEAN`. The `raw_metadata` column MUST become `JSONB`. The `affected_countries` and `article_ids` columns MUST become `JSONB`. All `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements MUST use valid PostgreSQL syntax.

**1.3** All query methods MUST use `%s` parameter placeholders instead of `?`. All date arithmetic MUST use PostgreSQL `INTERVAL` syntax (e.g., `NOW() - INTERVAL '%s minutes'` or parameterized `NOW() - make_interval(mins => %s)`) instead of SQLite `datetime('now', ...)`.

**1.4** `insert_article` MUST use `INSERT ... ON CONFLICT (url_hash) DO NOTHING` with a `RETURNING id` check instead of the current pre-check + `try/except IntegrityError` pattern. It MUST return `False` when the row already exists.

**1.5** All database methods MUST acquire connections from the pool using `with self.pool.connection() as conn:` context managers. No method SHOULD hold a connection outside its own scope.

**1.6** `Database.close()` MUST call `self.pool.close()` to shut down the connection pool.

**1.7** `cleanup_old_records` MUST use PostgreSQL interval syntax for date comparisons (e.g., `fetched_at < NOW() - make_interval(days => %s)`).

**1.8** The `models.py` `from_row()` class methods MUST accept a plain `dict` (since `psycopg` `dict_row` returns dicts). The `sqlite3` import MUST be removed from `models.py`. The existing `from_dict()` logic already works with dicts, so `from_row` MAY simply delegate to `from_dict`.

**1.9** Boolean fields (`is_military_event`, `is_new_event`) in `ClassificationResult.to_dict()` MUST return native Python `bool` values, not `int(...)`. PostgreSQL BOOLEAN columns accept Python bools directly.

**1.10** `DatabaseConfig` in `config.py` MUST replace `path: str` with `url: str`. The default SHOULD be `postgresql://sentinel:sentinel@localhost:5432/sentinel`. The `article_retention_days` and `event_retention_days` fields MUST remain unchanged.

**1.11** `config/config.example.yaml` MUST replace the `database.path` entry with `database.url: ${DATABASE_URL}` and include a comment showing the expected format.

**1.12** The `conftest.py` `db` fixture MUST spin up a PostgreSQL container using `testcontainers.postgres.PostgresContainer` (image `postgres:16-alpine`). The fixture scope MUST be `session` for the container and `function` for the `db` instance (tables truncated between tests). The fixture MUST call `_create_tables()` once per session and `TRUNCATE ... CASCADE` all tables before each test.

**1.13** The `conftest.py` `sample_config_dict` fixture MUST replace `database.path` with `database.url` pointing to the testcontainers PostgreSQL instance.

**1.14** `tests/test_database.py` MUST NOT use `sqlite_master`, `datetime('now', ...)`, `db.conn.execute(...)`, or `db.conn.commit()`. All raw SQL checks MUST use PostgreSQL syntax via `db.pool.connection()` context managers. The table-existence check MUST query `information_schema.tables` instead of `sqlite_master`.

**1.15** `requirements.txt` MUST add `psycopg[binary]>=3.1`, `psycopg_pool>=3.1`, and `testcontainers[postgres]>=4.0`.

**1.16** The `get_recent_titles` method MUST use `NOW() - make_interval(mins => %s)` or equivalent PostgreSQL interval arithmetic for the `since_minutes` parameter.

**1.17** The `get_active_events` method MUST use `NOW() - make_interval(hours => %s)` or equivalent PostgreSQL interval arithmetic for the `within_hours` parameter.

### Gate Criteria

- All 4 existing tables (`articles`, `classifications`, `events`, `alert_records`) are created in PostgreSQL with correct types.
- All existing `Database` methods pass their tests against a real PostgreSQL instance (via testcontainers).
- All 163 existing tests pass (adapted for PostgreSQL). Zero SQLite references remain in application code or test code.
- `models.py` has no `import sqlite3`.
- `database.py` has no `import sqlite3`.
- `psycopg`, `psycopg_pool`, and `testcontainers` are in `requirements.txt`.

## Phase 2: Multi-Tenant Schema and Tier System

### Deliverables

- `sentinel/database.py` — new tables (`users`, `tiers`, `user_countries`, `user_alert_rules`, `confirmation_codes`) added to `_create_tables()`, plus new CRUD methods for tiers, users, user rules, and confirmation codes
- `sentinel/models.py` — new dataclasses: `User`, `Tier`, `UserCountry`, `UserAlertRule`, `ConfirmationCode`
- `alert_records` table — gains `user_id TEXT REFERENCES users(id)` column
- `sentinel/models.py` — `AlertRecord` dataclass gains `user_id: str | None` field
- `scripts/seed_tiers.py` — standalone script that inserts Standard and Premium tier definitions

### Requirements

**2.1** The `tiers` table MUST have columns: `id TEXT PRIMARY KEY`, `name TEXT NOT NULL UNIQUE`, `available_channels JSONB NOT NULL` (list of allowed alert types, e.g. `["sms", "whatsapp", "phone_call"]`), `max_countries INTEGER NOT NULL`, `preference_mode TEXT NOT NULL CHECK (preference_mode IN ('preset', 'customizable'))`, `preset_rules JSONB` (urgency-to-channel mapping for preset mode, NULL for customizable), `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.

**2.2** The `users` table MUST have columns: `id TEXT PRIMARY KEY`, `name TEXT NOT NULL`, `phone_number TEXT NOT NULL`, `language TEXT NOT NULL DEFAULT 'pl'`, `tier_id TEXT NOT NULL REFERENCES tiers(id)`, `is_active BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.

**2.3** The `user_countries` table MUST have columns: `id TEXT PRIMARY KEY`, `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `country_code TEXT NOT NULL`. A UNIQUE constraint MUST exist on `(user_id, country_code)`.

**2.4** The `user_alert_rules` table MUST have columns: `id TEXT PRIMARY KEY`, `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `min_urgency INTEGER NOT NULL`, `max_urgency INTEGER NOT NULL`, `channel TEXT NOT NULL`, `corroboration_required INTEGER NOT NULL DEFAULT 1`, `priority INTEGER NOT NULL DEFAULT 0` (higher = checked first). A CHECK constraint MUST enforce `min_urgency <= max_urgency`.

**2.5** The `confirmation_codes` table MUST have columns: `id TEXT PRIMARY KEY`, `user_id TEXT NOT NULL REFERENCES users(id)`, `event_id TEXT NOT NULL REFERENCES events(id)`, `code TEXT NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `used_at TIMESTAMPTZ`. An index MUST exist on `(user_id, event_id, code)`.

**2.6** The `alert_records` table MUST gain a `user_id TEXT REFERENCES users(id)` column. Existing rows (migrated data) MAY have `user_id = NULL`. New rows MUST populate `user_id`.

**2.7** The `AlertRecord` dataclass MUST add a `user_id: str | None = None` field. `to_dict()` and `from_dict()` MUST handle this field. Existing tests that create `AlertRecord` without `user_id` MUST continue to work (default None).

**2.8** `Database` MUST provide these new methods: `insert_tier(tier) -> None`, `get_tier_by_id(tier_id) -> Tier | None`, `get_all_tiers() -> list[Tier]`, `insert_user(user) -> None`, `get_user_by_id(user_id) -> User | None`, `get_active_users() -> list[User]`, `get_users_by_country(country_code) -> list[User]`.

**2.9** `Database` MUST provide these methods for user rules: `insert_user_alert_rule(rule) -> None`, `get_user_alert_rules(user_id) -> list[UserAlertRule]`, `delete_user_alert_rules(user_id) -> None` (bulk delete for rule replacement).

**2.10** `Database` MUST provide these methods for user countries: `insert_user_country(user_id, country_code) -> None`, `get_user_countries(user_id) -> list[str]`, `delete_user_countries(user_id) -> None`.

**2.11** `Database` MUST provide these methods for confirmation codes: `insert_confirmation_code(code) -> None`, `get_active_confirmation_code(user_id, event_id) -> ConfirmationCode | None` (most recent unused code), `mark_confirmation_code_used(code_id) -> None`.

**2.12** The `Tier` dataclass MUST have fields: `id`, `name`, `available_channels` (list[str]), `max_countries` (int), `preference_mode` (str), `preset_rules` (dict | None), `created_at` (datetime). It MUST have `to_dict()` and `from_dict()` methods.

**2.13** The `User` dataclass MUST have fields: `id`, `name`, `phone_number`, `language`, `tier_id`, `is_active` (bool), `created_at`, `updated_at`. It MUST have `to_dict()` and `from_dict()` methods.

**2.14** The `UserAlertRule` dataclass MUST have fields: `id`, `user_id`, `min_urgency`, `max_urgency`, `channel`, `corroboration_required`, `priority`. It MUST have `to_dict()` and `from_dict()` methods.

**2.15** The `ConfirmationCode` dataclass MUST have fields: `id`, `user_id`, `event_id`, `code`, `created_at`, `used_at` (datetime | None). It MUST have `to_dict()` and `from_dict()` methods.

**2.16** The tier system MUST be fully data-driven. The `preference_mode` field determines behavior: `'preset'` means the tier's `preset_rules` dict maps urgency ranges to channels (the user cannot customize); `'customizable'` means the user's own `user_alert_rules` rows determine routing. Adding a new tier MUST require zero code changes — only a database insert.

**2.17** `scripts/seed_tiers.py` MUST insert two tiers. **Standard**: `available_channels=["sms", "whatsapp"]`, `max_countries=2`, `preference_mode="preset"`, `preset_rules={"7-8": "sms", "9-10": "sms", "5-6": "whatsapp", "1-4": "log_only"}`. **Premium**: `available_channels=["sms", "whatsapp", "phone_call"]`, `max_countries=10`, `preference_mode="customizable"`, `preset_rules=None`.

**2.18** `scripts/seed_tiers.py` MUST accept a `--database-url` argument (or read `DATABASE_URL` env var) for the PostgreSQL connection string. It MUST be idempotent — running it twice MUST NOT fail or create duplicates (use `INSERT ... ON CONFLICT (name) DO NOTHING`).

**2.19** Tests MUST verify: tier insert/retrieve, user insert/retrieve, user country association, user alert rules CRUD, confirmation code insert/retrieve/mark-used, and the `user_id` field on `AlertRecord`.

### Gate Criteria

- All 5 new tables are created with correct constraints and indexes.
- Tier seed script runs idempotently and creates Standard + Premium tiers.
- All new CRUD methods have passing tests.
- `AlertRecord` backward compatibility: existing tests still pass with `user_id=None`.
- `get_users_by_country` returns only active users whose `user_countries` includes the given country code.
- Confirmation code lifecycle works: insert, retrieve active, mark used, retrieve returns None after used.

## Phase 3: Per-User Alert Routing

### Deliverables

- `sentinel/alerts/state_machine.py` — rewritten to iterate over matching users per event, apply per-user tier rules, use DB-backed confirmation codes, per-user cooldowns
- `sentinel/alerts/dispatcher.py` — updated to pass user context through the alert pipeline
- `tests/test_state_machine.py` — rewritten for multi-user scenarios
- `tests/test_dispatcher.py` — updated for multi-user dispatch

### Requirements

**3.1** `AlertStateMachine.process_event(event)` MUST query all active users whose monitored countries overlap with `event.affected_countries` (via `db.get_users_by_country()`). It MUST iterate over each matching user and call a new `_process_event_for_user(event, user)` method.

**3.2** `_process_event_for_user(event, user)` MUST determine the alert action by resolving the user's tier. If `tier.preference_mode == 'preset'`, it MUST look up the action from `tier.preset_rules` based on `event.urgency_score`. If `tier.preference_mode == 'customizable'`, it MUST look up the action from the user's `user_alert_rules` (sorted by priority descending, first matching rule wins based on urgency range).

**3.3** The resolved channel MUST be validated against `tier.available_channels`. If the resolved channel is not in the tier's allowed list, the system MUST fall back to the highest-priority channel in `available_channels` that is below the resolved channel in severity (phone_call > sms > whatsapp > log_only). If no fallback is available, MUST use `log_only`.

**3.4** All alert execution methods (`_execute_phone_call`, `_execute_sms`, `_execute_whatsapp`) MUST accept a `User` parameter and use `user.phone_number` instead of `config.alerts.phone_number`. The `AlertRecord` created MUST include `user.id` as `user_id`.

**3.5** `_send_confirmation_whatsapp(event, user)` MUST generate a confirmation code and store it in the `confirmation_codes` table via `db.insert_confirmation_code()` instead of `self._confirmation_code`. The `self._confirmation_code` instance variable MUST be removed.

**3.6** `_check_whatsapp_confirmation(since, user)` MUST look up the active confirmation code from the database via `db.get_active_confirmation_code(user.id, event.id)`. On match, it MUST call `db.mark_confirmation_code_used(code.id)`. This fixes the existing bug where confirmation codes were lost on restart.

**3.7** Cooldown tracking MUST be per-user. `_is_in_cooldown(event, user)` MUST check the user's most recent acknowledged alert record for this event, not the event's `acknowledged_at` field. The event-level `acknowledged_at` field MAY be retained for backward compatibility but MUST NOT be the sole source of truth for per-user cooldown.

**3.8** `_is_acknowledged(event, user)` MUST check alert records filtered by both `event_id` and `user_id`. One user acknowledging an event MUST NOT suppress alerts to other users for the same event.

**3.9** The `config.alerts.phone_number` field MUST be removed from `AlertsConfig`. The `config.alerts.language` field MUST be retained as a system default. All references to `config.alerts.phone_number` in `state_machine.py` MUST be replaced with `user.phone_number`.

**3.10** `AlertDispatcher.dispatch(events)` MUST NOT change its public signature. Internally, it still calls `state_machine.process_event(event)` for each event. The multi-user iteration happens inside the state machine, not the dispatcher.

**3.11** `_format_call_message`, `_format_sms_message`, `_format_update_sms` MAY accept an optional `language` parameter for future i18n. For now they MUST continue to use Polish templates only.

**3.12** `check_pending_calls()` MUST be updated to handle per-user alert records. When checking call status, it MUST resolve the user from the alert record's `user_id` to correctly route any follow-up actions.

**3.13** Tests MUST cover: multi-user dispatch (event affecting PL alerts both PL-monitoring users), per-user cooldown independence, preset tier routing, customizable tier routing, channel fallback when tier disallows a channel, confirmation code DB persistence, and single-user-acknowledge-does-not-block-other-users.

### Gate Criteria

- Events affecting multiple countries correctly alert all users monitoring any of those countries.
- A Premium user with customizable rules gets routed according to their `user_alert_rules`.
- A Standard user with preset rules gets routed according to their tier's `preset_rules`.
- Phone calls are not sent to Standard tier users (not in `available_channels`).
- Confirmation codes survive a simulated restart (stored in DB, not memory).
- User A acknowledging an event does not prevent User B from receiving alerts for the same event.
- All existing test scenarios still pass (adapted for multi-user context).
- `config.alerts.phone_number` no longer exists in config or code.

## Phase 4: Migration Script and Seed Data

### Deliverables

- `scripts/migrate_sqlite_to_pg.py` — one-shot migration script that reads from SQLite and writes to PostgreSQL
- `scripts/seed_tiers.py` — (from Phase 2, may need minor updates for migration context)
- `scripts/create_initial_user.py` — helper script to create the first user (migrating the existing single-user setup)

### Requirements

**4.1** `scripts/migrate_sqlite_to_pg.py` MUST accept `--sqlite-path` (default: `data/sentinel.db`) and `--pg-url` (default: `DATABASE_URL` env var) arguments.

**4.2** The migration script MUST copy all data from the 4 existing SQLite tables (`articles`, `classifications`, `events`, `alert_records`) to their PostgreSQL equivalents. ISO date strings MUST be converted to proper `TIMESTAMPTZ` values. Integer booleans MUST be converted to native booleans. JSON text fields MUST be converted to proper JSONB.

**4.3** The migration script MUST run `scripts/seed_tiers.py` logic (or import it) to ensure tiers exist before migrating data.

**4.4** The migration script MUST create the existing single user from environment variables: `ALERT_PHONE_NUMBER` for phone, `ALERT_USER_NAME` (default: "Primary User") for name. It MUST assign this user to the Premium tier. It MUST set up `user_countries` for all currently configured `target_countries` from `config.yaml`.

**4.5** Existing `alert_records` rows MUST have their `user_id` set to the migrated primary user's ID.

**4.6** The migration script MUST validate data integrity after migration: row counts MUST match between SQLite source and PostgreSQL destination for all 4 original tables. It MUST print a summary report showing counts.

**4.7** The migration script MUST be idempotent. Running it against a PostgreSQL database that already has data MUST NOT create duplicates (use `INSERT ... ON CONFLICT DO NOTHING` for all inserts).

**4.8** The migration script MUST handle the case where the SQLite file does not exist (print error, exit 1).

**4.9** `scripts/create_initial_user.py` MUST accept `--name`, `--phone`, `--tier` (name, not ID), `--countries` (comma-separated codes), and `--pg-url` arguments. It MUST validate that the tier exists and that the number of countries does not exceed `tier.max_countries`. For a Premium customizable tier, it MUST create default `user_alert_rules` matching the current urgency level config.

**4.10** Both scripts MUST be runnable locally (pointing at a local PostgreSQL instance) for testing purposes. Neither script MUST require SSH access to the production server.

### Gate Criteria

- Migration script successfully copies a test SQLite database (with sample data across all 4 tables) to PostgreSQL with zero data loss.
- Row counts match between source and destination.
- Date fields are proper `TIMESTAMPTZ` in PostgreSQL (not text strings).
- Boolean fields are proper `BOOLEAN` in PostgreSQL (not integers).
- Running migration twice does not create duplicates.
- The migrated user exists in `users` table with correct tier, countries, and alert rules.
- `create_initial_user.py` rejects country count exceeding tier max.
- Both scripts work with a local PostgreSQL instance (no server access needed).
