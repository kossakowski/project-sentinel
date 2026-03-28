# Phase 2 Review: Multi-Tenant Schema and Tier System

**Reviewer:** Blind code review agent (Opus 4.6)
**Date:** 2026-03-28
**Branch:** `code-surgeon/multi-tenant-evolution`
**Scope:** Phase 2 requirements 2.1-2.19 from CHANGE-SPEC.md

---

## Spec Compliance Summary

| Req | Status | Notes |
|-----|--------|-------|
| 2.1 | PASS | `tiers` table has all specified columns: `id TEXT PRIMARY KEY`, `name TEXT NOT NULL UNIQUE`, `available_channels JSONB NOT NULL`, `max_countries INTEGER` (nullable), `preference_mode TEXT NOT NULL CHECK(...)`, `preset_rules JSONB`, `is_active BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`. CHECK constraint on preference_mode matches spec exactly. |
| 2.2 | PASS | `users` table has all specified columns with correct types, FK to tiers(id), defaults for language ('pl'), is_active (TRUE), created_at (NOW()), updated_at (NOW()). |
| 2.3 | PASS | `user_countries` table has `id TEXT PRIMARY KEY`, `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `country_code TEXT NOT NULL`, and `UNIQUE(user_id, country_code)`. |
| 2.4 | PASS | `user_alert_rules` table has all specified columns, ON DELETE CASCADE on user_id FK, `CHECK(min_urgency <= max_urgency)`. Default values for corroboration_required (1) and priority (0) match spec. |
| 2.5 | PASS | `confirmation_codes` table has all specified columns and FKs. Index `idx_confirmation_codes_lookup` on `(user_id, event_id, code)` exists. |
| 2.6 | PASS | `alert_records` table has `user_id TEXT REFERENCES users(id)` (nullable for legacy rows). |
| 2.7 | PASS | `AlertRecord` dataclass has `user_id: str | None = None`. `to_dict()` includes `user_id`. `from_dict()` uses `d.get("user_id")` defaulting to None. Backward compat preserved. |
| 2.8 | PASS | All 7 methods implemented: `insert_tier`, `get_tier_by_id`, `get_all_tiers`, `insert_user`, `get_user_by_id`, `get_active_users`, `get_users_by_country`. |
| 2.9 | PASS | All 3 methods implemented: `insert_user_alert_rule`, `get_user_alert_rules` (ordered by priority DESC), `delete_user_alert_rules`. |
| 2.10 | PASS | All 3 methods implemented: `insert_user_country`, `get_user_countries` (ordered by country_code), `delete_user_countries`. |
| 2.11 | PASS | All 3 methods implemented: `insert_confirmation_code`, `get_active_confirmation_code` (most recent unused via `ORDER BY created_at DESC LIMIT 1` with `used_at IS NULL`), `mark_confirmation_code_used` (sets `used_at = NOW()`). |
| 2.12 | PASS | `Tier` dataclass has all required fields with correct types. `to_dict()` and `from_dict()` both present. `from_dict()` handles JSON string -> list/dict deserialization for available_channels and preset_rules. |
| 2.13 | PASS | `User` dataclass has all required fields with correct types. `to_dict()` and `from_dict()` both present. |
| 2.14 | PASS | `UserAlertRule` dataclass has all required fields with correct types. `to_dict()` and `from_dict()` both present. |
| 2.15 | PASS | `ConfirmationCode` dataclass has all required fields with correct types. `to_dict()` and `from_dict()` both present. `used_at: datetime | None = None`. |
| 2.16 | PASS | Tier system is fully data-driven. `preference_mode` and `preset_rules` stored in DB as schema columns. No code-level branching on tier names in the DB layer. Adding a new tier requires only a DB insert. |
| 2.17 | PASS | `seed_tiers.py` defines Standard (preset, max_countries=1, preset_rules with 4 urgency ranges) and Premium (customizable, max_countries=None, preset_rules=None). Channel lists match spec exactly. |
| 2.18 | PASS | Script accepts `--database-url` with `DATABASE_URL` env var fallback. Uses `INSERT ... ON CONFLICT (name) DO NOTHING` for idempotency. Error exits with code 1 if no URL provided. |
| 2.19 | PASS | `test_multi_tenant.py` covers: tier insert/retrieve (TestTiers, 6 tests), user insert/retrieve (TestUsers, 4 tests), user country association (TestUserCountries, 5 tests), user alert rules CRUD (TestUserAlertRules, 5 tests), confirmation code lifecycle (TestConfirmationCodes, 6 tests), AlertRecord user_id field (TestAlertRecordUserIdField, 7 tests), schema structure (TestMultiTenantSchema, 4 tests). |

---

## Findings

### Finding 1: Missing `UserCountry` dataclass listed in deliverables
- **File**: sentinel/models.py (entire file)
- **Severity**: Low
- **Category**: spec-compliance
- **Description**: The CHANGE-SPEC Phase 2 deliverables section states: "new dataclasses: `User`, `Tier`, `UserCountry`, `UserAlertRule`, `ConfirmationCode`". No `UserCountry` dataclass exists in models.py. The `user_countries` table is managed through direct method signatures: `insert_user_country(user_id, country_code)`, `get_user_countries(user_id) -> list[str]`, `delete_user_countries(user_id)`. This is a pragmatic choice -- a dataclass for a 3-column junction table would be over-engineering -- but the CHANGE-SPEC deliverables list does not match the implementation.
- **Recommendation**: Update the CHANGE-SPEC deliverables list to remove `UserCountry` and note that user_countries is managed via direct method parameters. Alternatively, add a trivial `UserCountry` dataclass if consistency with the spec matters more than pragmatism.

### Finding 2: `insert_tier()` has no duplicate-name handling
- **File**: sentinel/database.py:449-461
- **Severity**: Medium
- **Category**: quality
- **Description**: `insert_tier()` uses plain `INSERT INTO tiers` without `ON CONFLICT` handling. The `tiers` table has `name TEXT NOT NULL UNIQUE`. If called with a duplicate tier name, this will raise `psycopg.errors.UniqueViolation` without any application-level handling. Compare with `seed_tiers.py` which correctly uses `INSERT ... ON CONFLICT (name) DO NOTHING`. This asymmetry means the Database CRUD method is less robust than the standalone script.
- **Recommendation**: Add `ON CONFLICT (name) DO NOTHING` to `insert_tier()`, consistent with the defensive pattern used in `insert_article()` and `seed_tiers.py`. Alternatively, return a boolean to indicate whether the insert succeeded.

### Finding 3: `insert_user_country()` has no duplicate handling for UNIQUE constraint
- **File**: sentinel/database.py:540-550
- **Severity**: Medium
- **Category**: quality
- **Description**: `insert_user_country()` uses plain INSERT. The table has `UNIQUE(user_id, country_code)`. Calling it twice with the same (user_id, country_code) pair will raise `UniqueViolation`. This makes the method non-idempotent, unlike `insert_article()` which handles duplicates gracefully.
- **Recommendation**: Add `ON CONFLICT (user_id, country_code) DO NOTHING` to make this operation idempotent.

### Finding 4: Flaky test -- `test_most_recent_active_code_returned` relies on timestamp ordering that may not be deterministic
- **File**: tests/test_multi_tenant.py:335-356
- **Severity**: Medium
- **Category**: testing
- **Description**: Both `code1` and `code2` are `ConfirmationCode` instances created with `created_at=datetime.now(timezone.utc)` (the dataclass default factory). The `insert_confirmation_code()` method calls `code.to_dict()` which serializes the Python-side `created_at` to ISO format and passes it to the INSERT, overriding the DB `DEFAULT NOW()`. If both objects are instantiated within the same microsecond (which is common on fast CPUs), they will have identical `created_at` values. The query `ORDER BY created_at DESC LIMIT 1` would then have no deterministic tiebreaker, and the test assertion `active.code == "CODE2"` could intermittently fail.
- **Recommendation**: Explicitly set `created_at` on `code1` to be earlier than `code2`. For example: `code1 = ConfirmationCode(..., created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))` and let `code2` use the default (now). This guarantees deterministic ordering.

### Finding 5: Unused `import json` in seed_tiers.py
- **File**: scripts/seed_tiers.py:15
- **Severity**: Low
- **Category**: quality
- **Description**: `import json` is present at line 15 but never referenced in the file. The script uses `psycopg.types.json.Jsonb()` for JSON handling.
- **Recommendation**: Remove the unused import.

### Finding 6: No automated test for `seed_tiers.py`
- **File**: tests/ (missing)
- **Severity**: Medium
- **Category**: testing
- **Description**: There is no test exercising the `seed_tiers()` function or the script's CLI entry point. The gate criteria state "Tier seed script runs idempotently and creates Standard + Premium tiers." The implementation uses `ON CONFLICT (name) DO NOTHING` which looks correct, but idempotency is not verified by any automated test. Additionally, the correctness of the tier data (channel lists, preset_rules, preference_mode) is not validated against the spec.
- **Recommendation**: Add a test that: (a) calls `seed_tiers(pg_url)`, (b) verifies 2 tiers exist with correct names and data, (c) calls `seed_tiers(pg_url)` again, (d) verifies still exactly 2 tiers (idempotency).

### Finding 7: No test for duplicate user_country insert behavior
- **File**: tests/test_multi_tenant.py (missing)
- **Severity**: Low
- **Category**: testing
- **Description**: No test verifies behavior when inserting the same (user_id, country_code) pair twice. The UNIQUE constraint on `user_countries` will cause a `UniqueViolation` exception, but this is not tested. Whether the exception or silent ignore is the intended behavior is undocumented.
- **Recommendation**: Add a test that inserts the same country for the same user twice and asserts the expected outcome (crash or idempotent skip, depending on whether Finding 3's recommendation is adopted).

### Finding 8: No test for duplicate tier name insert behavior
- **File**: tests/test_multi_tenant.py (missing)
- **Severity**: Low
- **Category**: testing
- **Description**: No test exercises inserting two tiers with the same `name`. The schema has `name TEXT NOT NULL UNIQUE` but the behavior on conflict is untested.
- **Recommendation**: Add a test that attempts a duplicate tier insert and verifies the expected behavior.

### Finding 9: No test for CHECK constraint on `user_alert_rules`
- **File**: tests/test_multi_tenant.py (missing)
- **Severity**: Low
- **Category**: testing
- **Description**: The `user_alert_rules` table has `CHECK(min_urgency <= max_urgency)`. No test verifies that the database rejects a rule where `min_urgency > max_urgency`.
- **Recommendation**: Add a test that attempts to insert a rule with `min_urgency=8, max_urgency=5` and asserts that a `CheckViolation` / `IntegrityError` is raised.

### Finding 10: No test for cascading deletes from user deletion
- **File**: tests/test_multi_tenant.py (missing)
- **Severity**: Medium
- **Category**: testing
- **Description**: `user_countries` and `user_alert_rules` both have `ON DELETE CASCADE` on `user_id`. No test verifies that deleting a user row cascades to remove associated countries and rules. This is especially important because there is an asymmetry: `confirmation_codes.user_id` and `alert_records.user_id` do NOT have `ON DELETE CASCADE`. This means deleting a user with confirmation codes or alert records will fail with an FK violation. This asymmetry is untested and undocumented.
- **Recommendation**: Add tests that: (a) verify CASCADE works (delete user -> countries and rules are gone), (b) verify FK restriction works (delete user with confirmation codes -> FK violation raised). This documents the intentional design.

### Finding 11: Inconsistent ON DELETE behavior across user-referencing tables
- **File**: sentinel/database.py:159, 169, 190, 201
- **Severity**: Medium
- **Category**: schema design
- **Description**: The four tables that reference `users(id)` have inconsistent delete behavior:
  - `user_countries.user_id`: `ON DELETE CASCADE` (line 159)
  - `user_alert_rules.user_id`: `ON DELETE CASCADE` (line 169)
  - `alert_records.user_id`: No ON DELETE clause (line 190) -- defaults to `RESTRICT`
  - `confirmation_codes.user_id`: No ON DELETE clause (line 201) -- defaults to `RESTRICT`

  This means deleting a user cleans up their countries and rules but blocks on any existing alert records or confirmation codes. This may be intentional (preserve audit trail) but is undocumented and could surprise future developers.
- **Recommendation**: Add a code comment explaining the intentional design choice. Consider using `ON DELETE SET NULL` for `alert_records.user_id` (which is already nullable) to preserve records while allowing user deletion. For `confirmation_codes`, RESTRICT may indeed be correct since deleting a user with pending codes could cause issues.

### Finding 12: Seed script generates non-deterministic UUIDs at module import time
- **File**: scripts/seed_tiers.py:24-48
- **Severity**: Medium
- **Category**: quality
- **Description**: The `TIERS` list is defined at module level with `"id": str(uuid4())`. Every time the module is imported or the script is run, new UUIDs are generated. Because the INSERT uses `ON CONFLICT (name) DO NOTHING`, the first run's IDs persist and subsequent runs' IDs are silently discarded. This has a practical consequence: the CHANGE-SPEC Phase 4 (req 4.3) says the migration script "MUST run `scripts/seed_tiers.py` logic (or import it) to ensure tiers exist before migrating data." If the migration script imports `seed_tiers` and tries to reference `TIERS[0]["id"]` to get the Standard tier's ID, it will get a freshly-generated UUID that does not match the one actually stored in the database.
- **Recommendation**: Either (a) use deterministic UUIDs via `uuid5(NAMESPACE_DNS, "standard")` so IDs are stable across runs, or (b) have `seed_tiers()` query the database after insert and return the actual tier IDs, or (c) move UUID generation inside the function rather than at module level.

### Finding 13: `conftest.py` fixtures have implicit ordering dependency risk
- **File**: tests/conftest.py:294-329
- **Severity**: Low
- **Category**: testing
- **Description**: The `sample_user` fixture inserts `sample_tier` into the DB. The `sample_user_alert_rule` fixture inserts `sample_user`. The `sample_confirmation_code` fixture inserts both `sample_user` and `sample_event`. If any test uses `sample_user` alongside `sample_tier` (both passed directly as test params), the tier would be inserted twice (once by the `sample_user` fixture, once by whatever uses `sample_tier`), causing a `UniqueViolation`. Currently this does not happen in any test, but the design is fragile.
- **Recommendation**: Consider restructuring fixtures to use a dedicated "seeded tier" fixture that both `sample_user` and any direct tier consumers depend on, preventing double insertion.

### Finding 14: `get_users_by_country` may return duplicates if a user monitors the same country via multiple rows
- **File**: sentinel/database.py:523-534
- **Severity**: Low
- **Category**: quality
- **Description**: The query JOINs `users` with `user_countries`. If the `UNIQUE(user_id, country_code)` constraint were ever removed or bypassed, a user with duplicate country rows would appear multiple times in the result. With the current constraint in place, this cannot happen. Defensive coding would add `DISTINCT` to the SELECT.
- **Recommendation**: The UNIQUE constraint makes this a non-issue. Optionally add `SELECT DISTINCT u.*` for defense-in-depth, but not required.

### Finding 15: `get_all_tiers()` returns all tiers including inactive ones
- **File**: sentinel/database.py:476-481
- **Severity**: Low
- **Category**: quality
- **Description**: `get_all_tiers()` returns all tiers regardless of `is_active` status. This contrasts with `get_active_users()` which filters by `is_active = TRUE`. The spec (2.8) says `get_all_tiers() -> list[Tier]` without specifying active-only, so this is technically compliant, but the naming asymmetry with `get_active_users()` may cause confusion.
- **Recommendation**: No change needed if intentional. Consider documenting that this returns all tiers (including inactive) in the docstring, or add a `get_active_tiers()` variant.

### Finding 16: Column names in dynamic INSERT SQL are derived from `to_dict()` keys -- safe but pattern requires awareness
- **File**: sentinel/database.py:449-460, 487-498, 577-588, 616-627
- **Severity**: Low
- **Category**: security
- **Description**: All new insert methods (`insert_tier`, `insert_user`, `insert_user_alert_rule`, `insert_confirmation_code`) use `data = obj.to_dict(); columns = ", ".join(data.keys())` to construct SQL dynamically. Column names come from hardcoded `to_dict()` return dictionaries, not from user input. Values are properly parameterized via `%s`. This is the same pattern used by all Phase 1 insert methods and is safe as long as `to_dict()` keys remain hardcoded.
- **Recommendation**: No action needed. This is a pre-existing, consistent pattern. Noted for awareness.

---

## Statistics
- Files reviewed: 5
- Findings: 16 (Critical: 0, High: 0, Medium: 6, Low: 10)

---

## Resolver Decisions

**Resolver:** Opus 4.6 (1M context)
**Date:** 2026-03-28
**Method:** Verified each finding against actual code at cited locations, cross-referenced CHANGE-SPEC.md requirements (Phases 2-4), and applied canonical blocking definition.

### Finding 1: Missing `UserCountry` dataclass listed in deliverables
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: `sentinel/models.py` contains `Tier`, `User`, `UserAlertRule`, `ConfirmationCode` dataclasses but no `UserCountry`. CHANGE-SPEC Phase 2 deliverables (line 122) lists "new dataclasses: `User`, `Tier`, `UserCountry`, `UserAlertRule`, `ConfirmationCode`". The `user_countries` table is handled via `insert_user_country(user_id, country_code)` returning/accepting primitives.
- **Rationale**: Confirmed: the spec lists `UserCountry` but none exists. The reviewer correctly notes this is pragmatic for a 3-column junction table. A trivial spec update suffices. Low severity is correct -- this is a documentation/spec mismatch, not a code defect.

### Finding 2: `insert_tier()` has no duplicate-name handling
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: `sentinel/database.py:449-461` -- `insert_tier()` uses plain `INSERT INTO tiers ({columns}) VALUES ({placeholders})` with no `ON CONFLICT` clause. The `tiers` table has `name TEXT NOT NULL UNIQUE` (line 127 of DDL). Meanwhile, `seed_tiers.py:60` uses `ON CONFLICT (name) DO NOTHING` and `insert_article()` (line 221-223) uses `ON CONFLICT (url_hash) DO NOTHING RETURNING id`. The CRUD method is less defensive than both the seed script and the established pattern.
- **Rationale**: This is a real inconsistency. `insert_tier()` will raise an unhandled `UniqueViolation` on duplicate names. The fix is trivial -- add `ON CONFLICT (name) DO NOTHING`. Medium is correct.

### Finding 3: `insert_user_country()` has no duplicate handling for UNIQUE constraint
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: `sentinel/database.py:540-550` -- plain `INSERT INTO user_countries (id, user_id, country_code) VALUES (%s, %s, %s)` with no `ON CONFLICT` clause. The table has `UNIQUE(user_id, country_code)` (DDL line 161). Calling this twice with the same pair raises `UniqueViolation`.
- **Rationale**: This method is called during user setup and could easily be called idempotently (e.g., re-running a setup script). The `insert_article` pattern establishes `ON CONFLICT DO NOTHING` as the project standard. Medium is correct.

### Finding 4: Flaky test -- `test_most_recent_active_code_returned` relies on timestamp ordering
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: `tests/test_multi_tenant.py:340-356` -- `code1` and `code2` are both created with default `created_at=datetime.now(timezone.utc)` (from `ConfirmationCode` dataclass default factory, `models.py:393`). The `to_dict()` method serializes `created_at` as ISO string which is passed to INSERT, so the DB `DEFAULT NOW()` is not used. If both instantiated in the same microsecond (very plausible), `ORDER BY created_at DESC LIMIT 1` has no deterministic tiebreaker. The test asserts `active.code == "CODE2"` on line 356.
- **Rationale**: This is a real flakiness risk. On fast machines or under load, microsecond-identical timestamps are common. The fix is simple: set `code1.created_at` to a known earlier time. Medium is correct for a test that could intermittently fail in CI.

### Finding 5: Unused `import json` in seed_tiers.py
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: fix
- **Evidence**: `scripts/seed_tiers.py:14` -- `import json` is present. Searched the file: `json` is never referenced. The script uses `psycopg.types.json.Jsonb()` for JSON serialization.
- **Rationale**: Dead import. Trivial fix, Low severity correct.

### Finding 6: No automated test for `seed_tiers.py`
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: No test file exercises `seed_tiers()`. Gate criteria state: "Tier seed script runs idempotently and creates Standard + Premium tiers." The seed script's `ON CONFLICT (name) DO NOTHING` idempotency and the correctness of tier data (channel lists matching spec 2.17) are not validated by any test.
- **Rationale**: Gate criteria explicitly requires verifying idempotent seed behavior. This is untested. Medium is correct. A test should call `seed_tiers()` twice and verify 2 tiers with correct data.

### Finding 7: No test for duplicate user_country insert behavior
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: No test in `test_multi_tenant.py` inserts the same `(user_id, country_code)` pair twice. The behavior depends on whether Finding 3's fix is applied: with `ON CONFLICT DO NOTHING` it would be idempotent; without it, it raises `UniqueViolation`.
- **Rationale**: Once Finding 3 is fixed (adding `ON CONFLICT DO NOTHING`), a test verifying idempotency would be nice but is not blocking. Low severity is correct -- the primary fix is in Finding 3, and adding a test is optional.

### Finding 8: No test for duplicate tier name insert behavior
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: No test exercises inserting two tiers with the same name. Same pattern as Finding 7 -- depends on Finding 2's fix.
- **Rationale**: Once Finding 2 is fixed, the behavior is defined. A test would be nice but is not blocking at Low severity.

### Finding 9: No test for CHECK constraint on `user_alert_rules`
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: `user_alert_rules` DDL (line 175) has `CHECK(min_urgency <= max_urgency)`. No test in `test_multi_tenant.py` attempts to violate this constraint.
- **Rationale**: The CHECK constraint is a DB-level safety net. Testing it validates the DDL but is not a functional gap -- the constraint exists and PostgreSQL enforces it. Low severity is correct.

### Finding 10: No test for cascading deletes from user deletion
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: DDL confirmed: `user_countries.user_id` has `ON DELETE CASCADE` (line 159), `user_alert_rules.user_id` has `ON DELETE CASCADE` (line 169), `alert_records.user_id` has no ON DELETE clause (line 190, defaults to NO ACTION/RESTRICT), `confirmation_codes.user_id` has no ON DELETE clause (line 201, defaults to NO ACTION/RESTRICT). No test verifies this behavior. The asymmetry means deleting a user with alert_records or confirmation_codes will fail with FK violation, which is untested and undocumented.
- **Rationale**: This is a design behavior that future code (Phase 3 alert routing, Phase 4 migration) will depend on. The CASCADE vs RESTRICT asymmetry is intentional (preserve audit trail) but must be documented by tests. Medium is correct.

### Finding 11: Inconsistent ON DELETE behavior across user-referencing tables
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: note
- **Evidence**: Same DDL evidence as Finding 10. `user_countries` and `user_alert_rules` cascade; `alert_records` and `confirmation_codes` restrict (default NO ACTION).
- **Rationale**: The spec does not mandate specific ON DELETE behavior for `confirmation_codes` or `alert_records`. The asymmetry is defensible: countries and rules are user config (delete with user), while alert_records and confirmation_codes are audit/operational data (preserve). However, the intent should be documented in a code comment. Reclassifying action to "note" rather than "fix" because the schema design is sound -- only a comment is needed, and Finding 10 covers the test gap. The comment can be added alongside the Finding 10 test fix. Medium is correct but action is note (a code comment, not a schema change).

### Finding 12: Seed script generates non-deterministic UUIDs at module import time
- **Decision**: accept
- **Final Severity**: Medium
- **Executor Action**: fix
- **Evidence**: `scripts/seed_tiers.py:24-48` -- `TIERS` list at module level with `"id": str(uuid4())`. New UUIDs generated on every import/run. `ON CONFLICT (name) DO NOTHING` means first run's IDs persist, subsequent IDs discarded. CHANGE-SPEC Phase 4 req 4.3: "The migration script MUST run `scripts/seed_tiers.py` logic (or import it) to ensure tiers exist before migrating data." Phase 4 req 4.4: "It MUST assign this user to the Premium tier." If the migration script imports `seed_tiers` and tries to use `TIERS[1]["id"]` to reference the Premium tier, it gets a UUID that does not match the DB.
- **Rationale**: The reviewer's Phase 4 concern is valid. Req 4.4 requires assigning a user to the Premium tier, which means the migration script needs the actual tier ID from the DB. If someone naively does `from seed_tiers import TIERS; premium_id = TIERS[1]["id"]`, they get a wrong ID. The fix options are all reasonable: (a) deterministic UUIDs via `uuid5`, (b) have `seed_tiers()` return actual DB tier IDs, or (c) generate UUIDs inside the function. Option (b) is most robust since it works regardless of import order. Medium is correct.

### Finding 13: `conftest.py` fixtures have implicit ordering dependency risk
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: `tests/conftest.py:294-329` -- `sample_user` fixture inserts `sample_tier` into DB (line 297). If a test requested both `sample_user` and `sample_tier` as parameters, `sample_tier` would be created once by pytest (it's function-scoped), then `sample_user` would insert it, and if any other code path also tried to insert it, that would fail. However, pytest's fixture deduplication means `sample_tier` is resolved once per test function and passed to `sample_user`, so double-insertion would only happen if a test explicitly called `db.insert_tier(sample_tier)` after `sample_user` already did.
- **Rationale**: This is a design fragility rather than an active bug. Currently no test triggers it. The reviewer correctly notes it could bite someone later. Low severity is correct -- no fix needed now.

### Finding 14: `get_users_by_country` may return duplicates
- **Decision**: reject
- **Final Severity**: Low (n/a)
- **Executor Action**: n/a
- **Evidence**: `sentinel/database.py:523-534` -- the query JOINs `users` with `user_countries`. The `UNIQUE(user_id, country_code)` constraint (DDL line 161) makes duplicates impossible. The reviewer acknowledges this: "With the current constraint in place, this cannot happen."
- **Rationale**: The reviewer themselves admits this is a non-issue given the constraint. Adding DISTINCT for a hypothetical future constraint removal is speculative defense-in-depth that adds query overhead for no current benefit. Reject.

### Finding 15: `get_all_tiers()` returns all tiers including inactive ones
- **Decision**: reject
- **Final Severity**: Low (n/a)
- **Executor Action**: n/a
- **Evidence**: `sentinel/database.py:476-481` -- `SELECT * FROM tiers ORDER BY name`. CHANGE-SPEC req 2.8 says `get_all_tiers() -> list[Tier]` -- no active-only filter specified. The method name says "all" and returns all. The asymmetry with `get_active_users()` is because users have a different access pattern (active filtering is the common case for users in alert routing).
- **Rationale**: The method does exactly what its name and the spec say. The naming asymmetry is intentional -- `get_all_tiers()` is an admin/listing method, while `get_active_users()` is an operational method. No change needed.

### Finding 16: Column names in dynamic INSERT SQL derived from `to_dict()` keys
- **Decision**: accept
- **Final Severity**: Low
- **Executor Action**: note
- **Evidence**: All insert methods (`insert_tier`, `insert_user`, `insert_user_alert_rule`, `insert_confirmation_code`) use `data = obj.to_dict(); columns = ", ".join(data.keys())`. Keys come from hardcoded `to_dict()` return dicts in models.py, not from user input. Values are parameterized via `%s`.
- **Rationale**: The reviewer explicitly says "safe" and "no action needed." This is an awareness note about a pre-existing pattern. Accepted as-is.

---

## Resolution Summary

### Blocking findings: 6

Findings that block (decision=accept, action=fix, severity=Medium+):

1. **Finding 2** (Medium/fix): `insert_tier()` needs `ON CONFLICT (name) DO NOTHING`
2. **Finding 3** (Medium/fix): `insert_user_country()` needs `ON CONFLICT (user_id, country_code) DO NOTHING`
3. **Finding 4** (Medium/fix): Flaky test needs deterministic `created_at` timestamps
4. **Finding 6** (Medium/fix): Add automated test for `seed_tiers.py` idempotency
5. **Finding 10** (Medium/fix): Add tests for CASCADE and RESTRICT delete behaviors
6. **Finding 12** (Medium/fix): Seed script UUIDs must be deterministic or returned from DB

### Non-blocking accepted findings: 8

- Finding 1 (Low/note): Update spec to remove `UserCountry` from deliverables list
- Finding 5 (Low/fix): Remove unused `import json` from seed_tiers.py
- Finding 7 (Low/note): Test for duplicate user_country insert (optional after Finding 3 fix)
- Finding 8 (Low/note): Test for duplicate tier name insert (optional after Finding 2 fix)
- Finding 9 (Low/note): Test for CHECK constraint violation (optional)
- Finding 11 (Medium/note): Add code comment documenting CASCADE vs RESTRICT intent
- Finding 13 (Low/note): Fixture ordering fragility (no active bug)
- Finding 16 (Low/note): Dynamic SQL from `to_dict()` keys (awareness only)

### Rejected findings: 2

- Finding 14: `get_users_by_country` duplicates -- impossible given UNIQUE constraint
- Finding 15: `get_all_tiers()` returns inactive tiers -- matches spec and method name
