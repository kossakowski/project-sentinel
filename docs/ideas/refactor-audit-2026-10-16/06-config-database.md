# Audit 06 — Configuration and persistence

Scope: `sentinel/config.py`, `config/config.yaml` (live), `config/config.example.yaml`, `.env.example`,
`sentinel/database.py`, `sentinel/models.py` (row mapping), with notes on `dashboard/db.py`.
Repo state: master @ 835ed8e, 2026-10-16. Read-only audit; nothing edited.

## How this was verified

- I walked both YAML files against the Pydantic model tree with a script. It found unknown keys. Only one exists today: `sources.gdelt.update_interval_minutes` in live (TODO 6.1 #1).
- I diffed the live config against the example and against the code defaults, key by key. That includes the keyword lists.
- I loaded the live `config/config.yaml` through `load_config()` with dummy env vars. It loads. The first load takes 11 s because the lingua detector is built inside a validator; a second load takes 0.35 s.
- I reproduced the datetime text-comparison bug against `Database(":memory:")`. The script is in this scratchpad.
- I copied a local DB (`data/sentinel.db`, March 2026, 1491 articles, without `classification_queue`) to the scratchpad and inspected the copy. Every stored timestamp ends in `+00:00`. The production DB was not touched.
- `.venv/bin/pytest tests/test_config.py tests/test_models.py tests/test_incident_storage.py tests/test_database.py tests/test_classification_queue.py -q` gave 42 passed in 35 s.

## TODO 6.1 cross-reference

- #1 (GDELT stale key) is accurate. It is the only unknown key in the live config.
- #6 (dead alert keys) is accurate but incomplete. See F11 for the other unread keys.
- #7 (example ships `max_call_retries: 5`) is accurate but badly under-describes the example drift. The example is *ahead* of live on 19 alert keywords (F01) and lacks 3 live RSS sources.
- #8 (misleading comments) is accurate. Two more stale comments are in F23.
- #10 and #11 are accurate. `.env.example` lacks `EXPO_PUSH_TOKEN` and `EXPO_ACCESS_TOKEN`.
- TODO §0, "Stray server .env", is **mis-described**. It treats the file as a permissions problem only. In fact `load_config()` *loads* it on every start (F06).

---

## Findings

### F01 — Live keyword lists lack 19 keywords from the 2026-03-24 audit; they landed only in the example
- **File:** `config/config.yaml` `monitoring.keywords` (lines ~22-330) vs `config/config.example.yaml`. Commit `7651e3f` ("audit remediation … keyword updates A1-A21") touched only `config.example.yaml`.
- **Category:** config drift / latent life-safety bug. **Severity: high.**
- **What's wrong:** these keywords are in the example and missing from the live config:
  - PL critical: `atak na Polskę`, `zaatakować Polskę`, `alarm lotniczy` (the last is covered by `alarm`).
  - PL high: `rakiet`, `Szahed`, `bezzałogowc`, `poderwał`.
  - UK high: `дрон`, `безпілотник`, `крилат`, `пуски ракет`.
  - EN high: `scramble(s|d)`, `GPS jamming`, `cyberattack(s)`, `Baltic states`.
  - I tested headlines against the live lists with the same substring rule `keyword_filter.matches` uses (lowercased). None of these match: "Atak na Polskę: rakiety spadły pod Lublinem", "Rosyjskie rakiety nad Polską", "Szahedy nad Podkarpaciem", "Російський дрон влетів у Польщу", "Безпілотник збили над Польщею" and "Poland scrambles jets". The example matches all of them. Neither config matches "Rosja zaatakowała Polskę".
  - Only `keyword_bypass` sources (Telegram and some RSS) skip this gate. Google News PL/UA and non-bypass RSS articles with such titles are dropped before classification.
- **Proposed refactor:**
  - (1) The owner reviews and merges the example-only keywords into live. Add `zaatakował` / `zaatakowała` stems too.
  - (2) Make the drift impossible: keep one keyword list (for example `config/keywords.yaml`, included by both files) or add a test that asserts identical keyword sets.
- **Behavior-preserving:** no. More articles get classified, which costs more OpenAI money and needs owner sign-off on keywords.
- **Risk to the 9-10 path:** this *is* the 9-10 path. A Polish-language critical headline from a non-bypass source can be dropped before the classifier.
- **Effort:** S (merge) / M (single-source lists).
- **Test that proves it:** `test_live_and_example_keyword_sets_identical`, plus a parametrized `KeywordFilter(load_config(live)).matches()` test that runs a fixture of canonical attack headlines in PL/UK/EN/RU and expects a non-None result.

### F02 — Alert tiers are not validated; a typo silently disables phone calls
- **File:** `sentinel/config.py:94-123` (`UrgencyLevel.action: str`, `min_score: int`, `AcknowledgmentConfig.max_call_retries: int = 3`); consumer `sentinel/alerts/state_machine.py:494-511`.
- **Category:** weak typing / validation. **Severity: high.**
- **What's wrong:**
  - `action` is a free string. With `action: phone-call` or `Phone_call`, `_determine_action` returns that string, so `send_push` and `send_sms` are False and no call is placed. Only an INFO log line records it (`state_machine.py:422-460`). `_phone_call_threshold` and `IncidentMemory.phone_threshold` then silently fall back to 9.
  - Nothing checks that exactly one tier is `phone_call`, that `min_score` is in 1-10 and unique, or that the tiers cover 1..10.
  - `max_call_retries: 0` passes validation, and `range(1, 1)` then places zero calls per round (`state_machine.py:586`). `corroboration_required` and `call_poll_*` have no bounds either.
- **Proposed refactor:**
  - Set `action: Literal["phone_call", "sms", "log_only"]`, `min_score: int = Field(ge=1, le=10)` and `corroboration_required: int = Field(ge=1)`.
  - Set `max_call_retries: int = Field(ge=1, le=5)` and `call_poll_timeout_seconds` / `call_poll_interval_seconds` / `call_retry_pause_seconds` to `gt=0`.
  - Add an `AlertsConfig` model_validator: exactly one `phone_call` level, unique `min_score`, lowest `min_score == 1`, and the phone-call threshold ≤ 10.
  - Expose `AlertsConfig.phone_call_threshold` as a property (see F18).
- **Behavior-preserving:** yes for the current live and example configs (both satisfy the rules). Only invalid configs are rejected.
- **Risk to the 9-10 path:** removes a silent-no-call failure mode. A rejected config must fail at `/deploy` pre-flight, not at restart, so pair this with F04.
- **Effort:** S.
- **Test that proves it:** `test_urgency_action_typo_rejected`, `test_no_phone_call_tier_rejected`, `test_max_call_retries_zero_rejected`, `test_live_tiers_pass_validation`.

### F03 — Unknown or misspelled keys are silently ignored, and the fallbacks are the dangerous defaults
- **File:** `sentinel/config.py`, every `BaseModel` (no `model_config = ConfigDict(extra="forbid")`).
- **Category:** config validation. **Severity: high.**
- **What's wrong:** Pydantic's default `extra="ignore"` drops typos. Several code defaults are exactly the values the owner moved away from on purpose:
  - `max_call_retries` 3 (the call-storm class; live 1).
  - `incident_memory.enabled` False (silently back to the legacy grouping path).
  - `provider` "anthropic".
  - `classification.corroboration_required` 2.
  - `push.enabled` False (tiers 5-8 are push-only, so they would deliver nothing).
  - A misspelling such as `max_call_retires: 1` or `incident_memroy:` loads cleanly and changes live behavior. Today exactly one unknown key exists (TODO 6.1 #1).
- **Proposed refactor:**
  - Add `class _Strict(BaseModel): model_config = ConfigDict(extra="forbid")` and make every config model inherit from it.
  - Fix TODO 6.1 #1 first, then check every test fixture dict (`tests/conftest.py`, `test_cli.py`, `test_telegram.py`, `test_scheduler.py`, `test_integration.py`) for stale keys.
  - Optional: separately, move the life-safety defaults to "required" (no default) so that omission also fails.
- **Behavior-preserving:** no. Loading becomes stricter, but runtime behavior for the valid live config does not change.
- **Risk to the 9-10 path:** positive. A strict config also means a stray key can stop the service from starting, so deploy must validate first (F04, and `/deploy` step 6a).
- **Effort:** S.
- **Test that proves it:** `test_unknown_key_rejected` (for example `alerts.acknowledgment.max_call_retires`), plus the live-config load test from F04.

### F04 — No test loads the live production config through `load_config()`
- **File:** `tests/test_config.py:11` (loads only the example); `:349` (`test_shipped_configs_channel_routing` parses the live YAML with raw `yaml.safe_load`, so no Pydantic validation runs).
- **Category:** missing test on a critical path. **Severity: high.**
- **What's wrong:** an edit to `config/config.yaml` that breaks validation passes the whole suite, ships via `/deploy` 6c, and fails only when systemd restarts. The service is then down, so no calls go out. The life-safety values are also not pinned: critical `min_score` 9 / `phone_call`, `max_call_retries` 1, `incident_memory.enabled` true, `push.enabled` true, and `channel: push` for 5-8 (the last is asserted, but only on raw YAML).
- **Proposed refactor:** add `test_live_config_loads_and_pins_life_safety_values`. It monkeypatches dummy `ALERT_PHONE_NUMBER`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `EXPO_PUSH_TOKEN`, calls `load_config("config/config.yaml")`, and asserts those values. I verified the live config loads with dummy vars today.
- **Behavior-preserving:** yes (test only).
- **Risk to the 9-10 path:** none. It guards against outage-by-config.
- **Effort:** S.
- **Test that proves it:** the test itself.

### F05 — ISO timestamps are compared as text to SQLite `datetime('now', …)`, so time windows inflate to up to ~a day
- **File:** `sentinel/database.py:228` (`get_recent_titles`), `:293` (`get_active_events`), `:439/:446/:454/:461` (`cleanup_old_records`); same pattern in `dashboard/db.py:608`.
- **Category:** latent bug. **Severity: med** (high if the legacy path is re-enabled).
- **What's wrong:**
  - Rows store `2026-10-16T00:00:01+00:00` (`isoformat()`), but `datetime('now','-60 minutes')` returns `2026-10-16 17:50:29`. Comparing them as text, `'T'` (0x54) is greater than `' '` (0x20), so every row from the cutoff's calendar day counts as newer than the cutoff.
  - Reproduced: `get_recent_titles(60)` returned an article that was 18.8 hours old.
  - Legacy dedup (`deduplicator.py:39`, used only when `incident_memory.enabled` is false) therefore compares against all of today's titles. A same-source title with ≥85 similarity from hours earlier drops a new article as "republished". That is a missed-alert risk on the rollback path.
  - `get_active_events` over-fetches (harmless, because Python re-checks the window at `corroborator.py:186-189`).
  - Cleanup lags by up to 1 day (harmless).
  - `tests/test_database.py:66-90` hides the bug: it rewrites `fetched_at` to SQLite format ("Fix fetched_at to use SQLite-compatible format").
  - `get_memory_events` already does this correctly with `julianday()` (`:307-313`).
- **Proposed refactor:** compute the cutoff in Python (`(datetime.now(UTC) - timedelta(...)).isoformat()`) and compare like with like, or use `julianday(col) > julianday('now', ?)` everywhere. Put the helper in one place (`Database._cutoff_iso(minutes=…)`). Remove the format rewrite from the test.
- **Behavior-preserving:** no. Legacy dedup and active-event windows shrink to their configured size; the live memory path is unaffected.
- **Risk to the 9-10 path:** reduces false "duplicate" drops on the rollback path. There is no change on the live path.
- **Effort:** S.
- **Test that proves it:** `test_recent_titles_respects_window_with_iso_rows`. Insert an article with ISO `fetched_at` 3 hours ago (same UTC day) and assert `get_recent_titles(60)` excludes it. That test fails today.

### F06 — `load_config()` loads any `.env` found walking up from `sentinel/`, including the stray server file
- **File:** `sentinel/config.py:376-381` (`load_dotenv()` with no path; python-dotenv 1.1.0 `find_dotenv` walks up from the caller file's directory, so `sentinel/config.py` leads to `/home/deploy/sentinel/.env` on the server).
- **Category:** unclear boundary / secret handling. **Severity: med.**
- **What's wrong:**
  - TODO §0 says the stray `/home/deploy/sentinel/.env` (stale Twilio, Anthropic and Telegram keys) is a permission and rotation issue.
  - It is also *active*: systemd's `EnvironmentFile=/etc/sentinel/sentinel.env` runs first, and `load_dotenv` (no override) then fills in every variable missing from it out of the stale file. A key removed from `sentinel.env` would silently come back from the March file instead of failing.
  - In tests, `load_config` loads the developer's real `.env` (with `OPENAI_API_KEY` and Twilio creds) into the test process. That makes tests non-hermetic: `test_missing_env_var` passes only because the var it checks is not in `.env`.
  - The `except ImportError: pass` hides a missing dependency.
- **Proposed refactor:**
  - Make dotenv loading explicit and local-only: `load_config(path, env_file: str | None = None)`. The CLI passes `--env-file` (default `.env` only when not under systemd, for example when `INVOCATION_ID` is unset), and tests pass None.
  - Remove the `ImportError` swallow (the dependency is pinned in `requirements.txt`).
- **Behavior-preserving:** no. Production stops reading the stray file. That is intended, but verify `sentinel.env` + `openai.env` hold every needed var first (read-only check by the owner).
- **Risk to the 9-10 path:** if `sentinel.env` lacks a Twilio var that today comes from the stray `.env`, calls would break. The owner must check before shipping. Low otherwise.
- **Effort:** S.
- **Test that proves it:** `test_load_config_does_not_read_dotenv_by_default`. Write a tmp `.env` beside a fake module path, call `load_config`, and assert the variable is not in `os.environ`.

### F07 — Secret handling is inverted: a non-critical push token can block startup, while missing Twilio creds fail only at call time
- **File:** `sentinel/config.py:350-367` (every `${VAR}` is mandatory, with no default syntax); `config/config.yaml:656` (`${EXPO_PUSH_TOKEN}`); `sentinel/alerts/twilio_client.py:21-25` (`os.environ.get(..., "")`); `push_client.py:27`; `openai_provider.py:123` (raises at construction).
- **Category:** inconsistent error handling. **Severity: med.**
- **What's wrong:**
  - If `EXPO_PUSH_TOKEN` is missing from `sentinel.env` (for example during a token rotation), `load_config` raises, the service does not start, and the urgency 9-10 phone call is lost too. A failure in the 5-8 push channel takes down the life-safety channel.
  - Conversely, empty `TWILIO_*` builds `Client("", "")` silently, and the failure surfaces only when a 9-10 call is attempted.
  - Secrets come in through two mechanisms: some as YAML `${VAR}`, others read directly in client modules.
- **Proposed refactor:**
  - (a) Support `${VAR:-default}` / `${VAR:-}` in `_substitute_env_vars`, and let `push.tokens` drop empty entries, so a missing push token degrades push only.
  - (b) Add a startup credential check: an explicit `RuntimeSecrets` dataclass loaded once (Twilio SID, token and number; OpenAI key; Expo access token). Required ones fail fast at startup and in `--health`; optional ones log a warning.
  - (c) Clients receive secrets by injection instead of reading `os.environ`.
- **Behavior-preserving:** no (startup semantics change).
- **Risk to the 9-10 path:** positive. Missing Twilio creds are detected at boot, and a push-token mistake no longer stops calls. Note: Twilio is deliberately unfunded, so the check must look only for presence, never call the API.
- **Effort:** M.
- **Test that proves it:** `test_missing_push_token_degrades_push_not_startup` and `test_missing_twilio_creds_fail_startup_check`.

### F08 — `update_event()` always bumps `last_updated_at`, even for status-only writes
- **File:** `sentinel/database.py:262-279`. Callers that write status only: `state_machine.py:609` (`call_placed`), `:645` and `:809` (`retry_pending`), `:649` (`acknowledged`), `:780` (`sms_sent`).
- **Category:** latent semantic bug / unclear contract. **Severity: med.**
- **What's wrong:**
  - `last_updated_at` is read as "last article activity" by incident memory (`get_memory_events` lookback, `corroborator.py:131` age gate), by the legacy sliding window (`:188`), and by candidate ordering.
  - Every call attempt or acknowledgement refreshes it, so a delivery event extends the incident's grouping life and ranks it first in the memory candidates.
  - This compounds TODO §0 "Stale retry_pending calls after a Twilio recharge": each retry round resets the clock.
  - A caller cannot set `last_updated_at` explicitly either, because the method overwrites it.
  - The in-memory `Event` returned by the corroborator keeps the stale value while the DB gets `now`.
- **Proposed refactor:** add `touch_activity: bool = False`. Only the corroborator's article-merge path passes True, with the article's time. Status writes go through a separate `set_event_status(event_id, status, acknowledged_at=None)`. Alternatively, add a `status_changed_at` column.
- **Behavior-preserving:** no (grouping windows change). Needs an owner and life-safety review because it interacts with the critical-protection rules.
- **Risk to the 9-10 path:** medium. It changes which events new critical articles can join. Run the incident-memory tests and `--eval` (paid; owner runs it) before and after.
- **Effort:** S (code) / M (validation).
- **Test that proves it:** `test_status_update_does_not_extend_memory_lookback`. Create an event 167 h old, call `set_event_status(..., "retry_pending")`, and assert that `get_memory_events(168, …)` drops it an hour later.

### F09 — The classification queue has no attempt cap, and oldest-first ordering lets a backlog delay fresh critical articles
- **File:** `sentinel/database.py:167-180` (`pending_classifications` `ORDER BY julianday(a.fetched_at)` `LIMIT retry_batch_size`; `classification_failed` increments `attempts` forever); `sentinel/scheduler.py:241-270` (sequential classification in memory mode).
- **Category:** latent life-safety bug. **Severity: med-high.**
- **What's wrong:**
  - After an OpenAI outage or when the monthly budget cap runs out, "articles stay pending" (CLAUDE.md). When service resumes, the queue drains oldest-first at 100 per cycle, one sequential model call each.
  - With a backlog of N, a fresh urgency-9 article waits about N/100 cycles. Each cycle can itself outlast the 3-minute fast interval.
  - A permanently failing article (a poison input) is retried every `retry_delay_seconds` forever, and each retry can spend a paid call.
  - `last_error` stores only `type(e).__name__`.
  - Chronological order is a tested requirement (`tests/test_classification_queue.py:122`), so changing it is deliberate.
- **Proposed refactor:**
  - Order by `(priority bucket, fetched_at)`. Fresh articles (`fetched_at` within the last cycle) and keyword `critical` or bypass sources go first, and the backlog follows oldest-first.
  - Add `max_attempts` (config) after which a row is marked `dead` (kept, never retried, surfaced in `--health`).
  - Store `str(e)[:500]` in `last_error`.
- **Behavior-preserving:** no.
- **Risk to the 9-10 path:** positive (shorter time to call under backlog). Needs owner sign-off because it changes the tested ordering contract.
- **Effort:** M.
- **Test that proves it:** `test_fresh_article_classified_before_backlog`. Seed 150 overdue rows plus one fresh row and assert the fresh row is in the first `pending_classifications(100)`. Also `test_poison_article_stops_after_max_attempts`.

### F10 — Schema migrations are ad hoc: no version, and every open runs writes
- **File:** `sentinel/database.py:29-144`.
- **Category:** structure. **Severity: low-med.**
- **What's wrong:**
  - The base `CREATE TABLE` script holds some columns (for example `incident_memory`, `notification_revision`). Others exist only in the `additions` tuple, and `incident_memory`, `notification_revision` and `event_revision` appear in both.
  - `classification_queue` is created inside `_migrate_schema`, not in the base script.
  - No `PRAGMA user_version` exists, so every `Database()` open runs three full-table `UPDATE … WHERE x IS NULL` statements on NOT NULL columns. They can never match, but they take a write lock. That happens on service start and on every CLI invocation on the server (`sentinel.py:427` `--test-alert`, the health paths).
  - `PRAGMA foreign_keys` is off, so the `REFERENCES` clauses are decorative.
- **Proposed refactor:**
  - Use a numbered migration list keyed on `PRAGMA user_version`: v0 → base schema; v1 → incident-memory columns + queue; v2 → backfill. It runs once, inside one transaction.
  - Keep the `CREATE TABLE` script as "latest schema" for fresh DBs and set `user_version` to the latest.
  - Add a `Database(path, read_only=True)` mode for CLI and health readers that skips migration.
- **Behavior-preserving:** yes (same resulting schema). Verify on a copy of a production backup.
- **Risk to the 9-10 path:** low. A migration bug blocks startup, so test it on a copy of a real DB.
- **Effort:** M.
- **Test that proves it:** extend `test_legacy_populated_database_migrates_idempotently` to assert `user_version`, and add `test_second_open_executes_no_writes` (use `conn.set_trace_callback` to assert no UPDATE).

### F11 — Dead or misleading config keys beyond TODO 6.1 #6
- **File:** `sentinel/config.py:84` (`monitoring.aggressor_countries`; zero runtime readers), `:47` (`TelegramChannel.priority`; docs confirm it is unread), `:268` (`classification.temperature`; OpenAI ignores it), `:269` (`classification.corroboration_required`, which only sets a label but shares its name with the call gate `alerts.urgency_levels.critical.corroboration_required`).
- **Category:** dead code / naming. **Severity: low** (naming: med, because it has misled readers; TODO §0 needed a paragraph to explain it).
- **What's wrong:** these keys suggest control that does not exist. The two same-named `corroboration_required` keys have different meanings and different defaults (2 vs 1).
- **Proposed refactor:**
  - Remove `aggressor_countries` and Telegram `priority` (or wire `priority` into lane selection), in the same change as TODO #6.
  - Rename `classification.corroboration_required` to `classification.label_phone_call_min_sources`, with a Pydantic `validation_alias` for one release.
  - Mark `temperature` legacy-only in its field description.
- **Behavior-preserving:** yes (with the alias).
- **Risk to the 9-10 path:** none.
- **Effort:** S.
- **Test that proves it:** with F03's `extra="forbid"`, a test that loads the live config proves no removed key is still present.

### F12 — Status and type values are untyped strings shared across four modules and the dashboard
- **File:** `alert_status` values `pending|sms|phone_call|sms_sent|call_placed|retry_pending|acknowledged|expired` are written in `corroborator.py:425-443` and `state_machine.py:609/645/649/780/809`, and filtered in `database.py:292`. `alert_type` (`phone_call|sms|sms_update|push`) and Twilio statuses are string literals in `state_machine.py`.
- **Category:** weak typing. **Severity: med.**
- **What's wrong:**
  - A typo is a silent logic error. `database.py:292` filters `'expired'`, which no code ever writes (TODO §0).
  - The memory-mode "keep lifecycle state" set (`corroborator.py:398`) lists acknowledged, retry_pending, call_placed and expired, but not `sms_sent`. Whether `sms_sent` should be recomputed is undocumented.
  - The dashboard keeps its own union (`types.ts`, TODO 6.2).
- **Proposed refactor:** add `class AlertStatus(StrEnum)` and `class AlertType(StrEnum)` in `sentinel/models.py`, type the `Event.alert_status` / `AlertRecord.alert_type` fields with them, and replace the literals. StrEnum values are identical strings, so the DB stays unchanged.
- **Behavior-preserving:** yes.
- **Risk to the 9-10 path:** low (a mechanical rename). Run the state machine and incident tests afterwards.
- **Effort:** M.
- **Test that proves it:** existing suites stay green, plus `test_every_written_status_is_enum_member` (grep-style AST test or runtime assertion).

### F13 — The Database layer leaks: raw `db.conn` SQL and a JSON-array membership scan
- **File:** `sentinel/classification/corroborator.py:53-56` (`json_each(events.article_ids)` full scan per classified article), `:296` and `:304` (article lookup by id, N+1 per event article); `sentinel/eval/compare_models.py:153-160` (overrides `get_memory_events` with copied SQL); `dashboard/db.py` (five more `json_each` membership queries, own row parsers `_parse_json_list` / `_classification_from_row` / `_article_from_row` that duplicate `sentinel.models.*.from_row` and omit the newer columns, a hardcoded `EVENT_ID_RETENTION_DAYS = 30` vs config `event_retention_days: 90`). Dashboard noted only; another agent owns it.
- **Category:** boundaries / duplication. **Severity: med.**
- **What's wrong:**
  - `events.article_ids` is a denormalized JSON array. Every caller that needs "which event holds article X" re-implements a full scan.
  - Schema knowledge is duplicated in three places: `sentinel/database.py`, `eval/compare_models.py` and `dashboard/db.py`.
- **Proposed refactor:**
  - Step 1 (behavior-preserving, S): add `Database.find_event_for_article(article_id)` and `Database.get_articles_by_ids(ids)`, and route the corroborator through them.
  - Step 2 (M-L): add an `event_articles(event_id, article_id, PRIMARY KEY(event_id, article_id))` table with an index on `article_id`. Dual-write with `article_ids` during migration, then make the JSON column derived.
  - Step 3: let the dashboard import `sentinel.models` for row mapping.
- **Behavior-preserving:** step 1 yes; step 2 yes if dual-written (ordering of `article_ids` must be preserved, because `state_machine.py:136` uses the last element).
- **Risk to the 9-10 path:** step 1 none; step 2 medium (grouping replay guard depends on it).
- **Effort:** S / L.
- **Test that proves it:** `test_find_event_for_article_matches_json_each`, and a property test that the order of `event_articles` equals the old `article_ids` list.

### F14 — `update_event` / `update_alert_record` build SQL column names from free kwargs
- **File:** `sentinel/database.py:262-279`, `:408-425`.
- **Category:** weak typing / fail-late. **Severity: low-med.**
- **What's wrong:**
  - Column names are f-string-interpolated without an allowlist. A typo such as `alert_stauts=` raises `OperationalError` only at runtime, inside the alert path. There it is caught (or not) mid-call-round; `state_machine.py:609` runs right after a real call is placed.
  - Not exploitable (internal callers only), but it fails late.
- **Proposed refactor:** validate keys against `Event.__dataclass_fields__` / `AlertRecord.__dataclass_fields__` and raise `ValueError` immediately. Better, use typed methods (`set_event_status`, `record_call_result`).
- **Behavior-preserving:** yes.
- **Risk to the 9-10 path:** none (it fails earlier, in tests).
- **Effort:** S.
- **Test that proves it:** `test_update_event_rejects_unknown_column`.

### F15 — Timezone normalization is scattered; `_iso_to_dt` can return naive datetimes
- **File:** `sentinel/models.py:28-31`; ad hoc fixes at `corroborator.py:239-246` (`_as_utc`) and `state_machine.py:317`; `sentinel/utils/datetime.py:7-10`.
- **Category:** duplication / latent bug. **Severity: low.**
- **What's wrong:**
  - A row written by SQL (`datetime('now')`, as tests do) or by hand on the server parses as naive.
  - `state_machine.py:565-567` then computes `datetime.now(UTC) < last_call_time + retry_interval`, which raises `TypeError` inside `_execute_phone_call`, before any call is placed.
  - All current writers use aware UTC. The local DB is 100% `+00:00`; production is unverified.
- **Proposed refactor:** make `_iso_to_dt` always return aware UTC (`replace(tzinfo=UTC)` if naive, else `astimezone(UTC)`), then delete `_as_utc` and the `:317` special case. Use the shared helper in `sentinel/utils/datetime.py`.
- **Behavior-preserving:** yes for aware data; it only removes a crash for naive data.
- **Risk to the 9-10 path:** removes a crash path.
- **Effort:** S.
- **Test that proves it:** `test_alert_record_from_naive_row_is_utc_aware`, and `test_execute_phone_call_with_naive_sent_at_does_not_raise`.

### F16 — The config layer depends on the classification layer and lingua; one validator sits in the middle of the field list
- **File:** `sentinel/config.py:214-227` (imports `lingua` and `sentinel.classification.summary_language`), `:242-263` (imports `sentinel.classification.policy`; the validator is declared between fields, with fields continuing at `:265`); `policy: dict[str, Any]` (`:234`).
- **Category:** structure / weak typing. **Severity: low.**
- **What's wrong:**
  - Loading config builds the lingua detector (11 s on first load; it is cached).
  - The import direction is inverted (config → classification).
  - The policy schema (version, ranges, `near_border_strike`, `neutralised_drone`) is validated by catching `KeyError` / `TypeError` from prompt generation, not declared.
  - The field-then-validator-then-field order hides `incident_memory`, `model`, `max_tokens` and the rest below a 20-line validator.
- **Proposed refactor:**
  - Add a typed `ClassificationPolicy` model (`version: Literal[2]`, `monitored_countries: list[str]` (min 1), `near_border_strike: Literal[...]`, `ranges: dict[str, tuple[int, int]]` with a bounds validator).
  - Keep `classification.policy` serialized identically, because `prompt_hash(cfg.policy)` feeds `prompt_version` and the eval caches.
  - Move all fields above the validators.
  - Keep the Polish-fallback check, but import lazily or in a `validate_runtime()` step.
- **Behavior-preserving:** yes, if `model_dump()` of the policy equals the old dict. Assert this with a hash-equality test.
- **Risk to the 9-10 path:** low; a policy change alters prompts, so the hash test is mandatory.
- **Effort:** M.
- **Test that proves it:** `test_policy_hash_unchanged_after_typing`, which compares against the hash of the current live config.

### F17 — Life-safety threshold derived in three places, plus hardcoded cuts
- **File:** `corroborator.py:249-256` (`_phone_call_threshold`), `incident_memory.py:59-62` (`phone_threshold`), `state_machine.py:494-511` (sorted tier walk); hardcoded `9/7/5` in `corroborator.py:437-443` (a known exception per CLAUDE.md).
- **Category:** duplication. **Severity: low-med.**
- **What's wrong:** three copies of "min `min_score` where action is `phone_call`, default 9". If one copy changes (for example the default), the grouping protection and the dispatcher disagree on what is critical.
- **Proposed refactor:** add `AlertsConfig.phone_call_threshold` (computed property, validated to exist by F02) and `AlertsConfig.level_for(score)`. All three consumers call these. Optionally derive the label cuts in `_determine_alert_status` from the tiers.
- **Behavior-preserving:** yes for the property; no for replacing the hardcoded cuts (they equal today's tiers, so that is behavior-equal on the live config).
- **Risk to the 9-10 path:** low; it removes divergence.
- **Effort:** S.
- **Test that proves it:** `test_threshold_consumers_agree`, which sets critical `min_score` to 8 and asserts that the corroborator, incident memory and state machine all treat 8 as critical.

### F18 — Health path derivation duplicated three times
- **File:** `sentinel.py:92`, `sentinel.py:141`, `sentinel/scheduler.py:596` (`os.path.dirname(config.database.path) or "data"`).
- **Category:** duplication. **Severity: low.**
- **Proposed refactor:** add a `DatabaseConfig.health_path` property.
- **Behavior-preserving:** yes.
- **Risk to the 9-10 path:** none.
- **Effort:** S.
- **Test that proves it:** `test_health_path_next_to_db`.

### F19 — Config is mutated at runtime, and components snapshot it at construction
- **File:** `sentinel.py:203`, `:205`, `:256`, `:425` (`config.testing.dry_run = …`, `config.logging.level = …`); `dispatcher.py:14` caches `dry_run` in `__init__`; `corroborator.py:37` ORs its flag with the config value.
- **Category:** unclear boundaries. **Severity: low.**
- **What's wrong:** correctness depends on mutation order (mutate before constructing components). `validate_assignment` is off, so assignments bypass validation. This is related to TODO 6.1 #17 (`--dry-run` not guarding `check_pending_calls`).
- **Proposed refactor:** freeze the config models (`frozen=True`), and pass CLI overrides as a `RunOptions(dry_run, diagnostic, log_level)` object that the scheduler, dispatcher, corroborator and state machine read from one place.
- **Behavior-preserving:** yes.
- **Risk to the 9-10 path:** low; it makes the dry-run guard (TODO #17) easier to get right.
- **Effort:** M.
- **Test that proves it:** `test_config_is_frozen`, and `test_dry_run_option_reaches_state_machine`.

### F20 — `insert_article` relies on check-then-insert; its IntegrityError branch never sees URL duplicates
- **File:** `sentinel/database.py:192-212`; `idx_articles_url_hash` is non-unique (`:48`).
- **Category:** latent bug / dead code. **Severity: low.**
- **What's wrong:** URL uniqueness is enforced only by a preceding SELECT. The `IntegrityError` catch can fire only on an id collision. This is safe today because there is a single writer process with serialized cycles.
- **Proposed refactor:** add `CREATE UNIQUE INDEX` on `url_hash` (after a read-only duplicate check on a production backup copy; the local copy has 0 duplicates), then use `INSERT OR IGNORE` and `rowcount`.
- **Behavior-preserving:** yes if production has no duplicates.
- **Risk to the 9-10 path:** low; the migration fails if duplicates exist, so check first.
- **Effort:** S.
- **Test that proves it:** `test_duplicate_url_insert_returns_false_without_precheck`.

### F21 — Connection and transaction semantics rely on implicit sqlite3 behavior
- **File:** `sentinel/database.py:23-26`, `:146-158`.
- **Category:** fragility. **Severity: low.**
- **What's wrong:**
  - `transaction()` uses SAVEPOINTs under Python's legacy implicit-transaction mode (`isolation_level=""`). Any DML executed outside `transaction()` (tests do this through `db.conn.execute("UPDATE …")`) opens an implicit BEGIN. Later outermost `RELEASE` calls then stop committing until someone calls `commit()`. That is a silent lost-write hazard if production code ever does it.
  - There is a single shared connection with `check_same_thread=False`.
  - There is no explicit `busy_timeout` (the default is 5 s), while CLI processes on the server open the same file and write (F10).
- **Proposed refactor:** open with `isolation_level=None` (true autocommit, so savepoints alone define transactions), set `PRAGMA busy_timeout=10000` explicitly, and document "all writes go through Database methods".
- **Behavior-preserving:** yes for production paths. Tests that call `db.conn.commit()` keep working.
- **Risk to the 9-10 path:** low.
- **Effort:** S.
- **Test that proves it:** `test_write_outside_transaction_is_committed`, or assert `conn.in_transaction is False` after each Database method.

### F22 — Test-suite hygiene in this area
- **File:**
  - `tests/test_database.py:288` (`test_concurrent_access` is sequential; misnamed).
  - `tests/test_database.py:66-90` (masks F05).
  - `tests/test_config.py:235-283`: these tests pin the code defaults (360, 50, token_set_ratio, 90) but never the live values. The legacy-default tests (`provider` "anthropic", `max_call_retries` 3) pin dangerous defaults as if they were intended.
  - `tests/test_models.py` has no Cyrillic `_normalize_title` test (TODO §0 bug) and no naive-datetime test.
- **Category:** tests. **Severity: low.**
- **Proposed refactor:** rename or delete the misnamed test, remove the format rewrite, add live-value pins (F04), and add `test_normalize_title_cyrillic_not_empty` as an xfail that documents the TODO §0 bug.
- **Behavior-preserving:** yes.
- **Effort:** S.

### F23 — More stale comments in the live config (beyond TODO 6.1 #8)
- **File:**
  - `config/config.yaml:595-596` says "Push token is configured in prod (/etc/sentinel/config.yaml is the live source)". That is stale: the tracked file is the source, and `/deploy` 6c syncs it.
  - `:594-595` says "Only the critical 9-10 call keeps an SMS fallback". The `fallback` key is dead (TODO #6), and `_execute_phone_call`'s docstring (`state_machine.py:553-556`) claims "If the entire round fails, sends an SMS", but the code only sets `retry_pending` (`:638-645`). The only SMS on the 9-10 path is the confirmation-code SMS.
- **Category:** misleading docs-in-config. **Severity: low** (but it misleads anyone reasoning about the 9-10 fallback).
- **Proposed refactor:** fix both comments and the docstring in the TODO #8 change.
- **Behavior-preserving:** yes.
- **Effort:** S.

---

## Proposed phase grouping (configuration and persistence)

**Phase 1: Safety net (behavior-preserving, tests first; about 1 day).** F04 (live-config load and life-safety pins), F22, F18, F14, F15, F17, F23 + TODO 6.1 #8. Gate: the full suite is green and the new pins pass on the live config.

**Phase 2: Strict config (behavior change at load time only).** TODO 6.1 #1 → F03 (`extra="forbid"`) → F02 (tier and acknowledgment validation) → F11 + TODO 6.1 #6 (dead keys; rename with alias) → TODO 6.1 #7 + #11 (example and `.env.example` alignment). Gate: the live config and every fixture load; `/deploy` pre-flight runs the F04 test before syncing config.

**Phase 3: Owner decisions (behavior change, life-safety).** F01 (keyword sync; owner reviews the 19 keywords, then single-source the lists), F06 (stop loading the stray `.env`; owner first confirms `sentinel.env` is complete), F07 (degrade push on a missing token; startup credential check), F09 (queue priority and attempt cap). Gate: owner sign-off on each item; an incident-memory and eval run by the owner for F09.

**Phase 4: DB correctness (behavior change, mostly the legacy path).** F05 (time-window comparisons), F08 (`last_updated_at` semantics; needs a life-safety review alongside TODO §0 "Stale retry_pending"), F20, F21. Gate: the reproduction tests from F05 and F08 fail before and pass after; the incident-memory suite stays green.

**Phase 5: Structural (larger, behavior-preserving).** F10 (versioned migrations, read-only open), F12 (status enums), F13 step 1 → step 2 (repository methods, then the `event_articles` table), F16 (typed policy with hash-equality guard), F19 (frozen config plus RunOptions). Coordinate F13 and F12 with the dashboard owner (TODO 6.2), because `dashboard/db.py` duplicates row mapping and the `json_each` queries.
