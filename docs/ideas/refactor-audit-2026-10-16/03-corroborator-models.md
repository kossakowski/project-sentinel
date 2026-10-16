# Audit 03 — Event grouping and domain model

Scope: `sentinel/classification/corroborator.py` (458 lines), `sentinel/models.py` (310 lines), the
corroborator → dispatcher → state-machine contract, plus the glue in `sentinel/scheduler.py`,
`sentinel/classification/incident_memory.py` and `sentinel/database.py` where it touches events.
Audited at master `835ed8e`. Read-only.

Verified this session:
- `.venv/bin/pytest tests/test_corroborator.py tests/test_incident_storage.py tests/test_models.py tests/test_incident_memory.py tests/test_incident_alerts.py -q` → 79 passed (65–100 s; about 1 s of fixture setup per test).
- `fuzz.ratio("", "") == 100`, `_normalize_title("Ракетний удар по Львову") == ""`, and
  `Corroborator._extract_domain` returns `news.google.com` for every Google News link and `t.me`
  for every Telegram channel (one-off `python -c` check).

Known items referenced by TODO.md title (not rediscovered): "Owner sign-off: acknowledged-event
guard is gone in incident-memory mode", "Urgency-9 event fragmentation", "Stale retry_pending calls
after a Twilio recharge", "Unacknowledged calls are retried only when a new article joins the
event", "Cyrillic titles normalize to empty", "Telegram fetcher mislabels every channel",
"Ukraine-only shelter orders scored urgency 9 attempt a phone call", "Owner decision: corroboration
for phone calls (1 vs 2 sources)".

Legend: BP = behavior-preserving. "9–10 risk" = risk to the urgency 9–10 call path while doing the
refactor (or, for behavior changes, of the change itself).

---

## F01 — Life-safety gates are scattered across two interleaved grouping modes
- **Where:** `corroborator.py:49`, `:82`, `:375-381`, `:398` (four separate `incident_memory.enabled` branches); safety gates at `:115-117` (critical confidence bar, duplicated in `incident_memory.py:151-156`), `:132-139` and `:171-174` (country gate), `:141-143` (first-critical escalation override), `:182-183` (acknowledged guard, legacy only).
- **Category:** structure / unclear boundaries. **Severity:** high.
- **What's wrong:** One class runs two grouping algorithms by flag checks spread through `process_classifications`, `_update_event` and the status re-evaluation. The five life-safety rules from `.claude/rules/corroboration.md` live in four methods and two modules. You cannot see in one place which rules hold in which mode. The TODO item "acknowledged-event guard is gone in incident-memory mode" exists precisely because the legacy guard sits inside the legacy loop and was never ported.
- **Proposed refactor:**
  1. Extract `sentinel/classification/safety.py` with pure functions: `critical_confidence_ok(result, decision, cfg)`, `countries_compatible(result, event, threshold)`, `force_escalation(result, event, threshold) -> bool`, `blocks_absorption_into_acknowledged(result, event, threshold) -> bool`. No DB, no config object beyond the values.
  2. Split `Corroborator` into `MemoryGrouper.match(result) -> Event | None` and `LegacyGrouper.match(result) -> Event | None`, both calling `safety.*`. Keep one shared `EventWriter` (`create`, `attach`) for persistence. `Corroborator.process_classifications` stays as the public façade (the eval harness and scheduler call it).
  3. In `MemoryGrouper`, call `blocks_absorption_into_acknowledged` behind a config flag that defaults to today's behavior (off). The owner's sign-off then becomes a config change, not a code edit.
- **BP:** yes (flag defaults to current behavior).
- **9–10 risk:** medium during the move (both paths touched); covered by 79 existing tests plus F06's new ones.
- **Effort:** M.
- **Proving test:** existing `test_corroborator.py` + `test_incident_memory.py` + `test_incident_alerts.py` pass unchanged; new `tests/test_safety_gates.py` with one table-driven test per gate (urgency × ack state × country sets × decision) asserting the same verdicts as today; one test that flips the new flag and asserts a critical `duplicate` on an acknowledged event creates a new event.

## F02 — `last_updated_at` means "any write", not "last article"
- **Where:** `database.py:268` (`update_event` always sets `last_updated_at = now`); state-machine status writes through it at `state_machine.py:609` (`call_placed`), `:645` and `:809` (`retry_pending`), `:651` (`acknowledged`), `:780` (`sms_sent`); consumers `corroborator.py:131-135` (memory age gate), `:188` (legacy sliding window), `database.py:299-314` (`get_memory_events` lookback). `corroborator.py:382` also sets an in-memory `now` that differs from the DB's own `now`.
- **Category:** latent bug / unclear data contract. **Severity:** high.
- **What's wrong:** The grouping windows are documented as "measured from the event's last activity (most recent corroborating article)". In fact every call attempt, acknowledgement and SMS status write also extends them. This compounds TODO "Stale retry_pending calls after a Twilio recharge": every retry round keeps a days-old incident inside the 168 h memory window, so a later article can match it and re-run `_execute_phone_call`.
- **Proposed refactor:** add a `last_article_at` column (migrated from `last_updated_at`), set only by `EventWriter.create/attach`; grouping and `get_memory_events` read it. Make `update_event` stop touching timestamps unless a `touch=True` argument is passed, or keep `last_updated_at` as the "row modified" stamp for the dashboard.
- **BP:** no. Grouping windows shrink to article time, so some matches that happen today stop happening (more new events, more calls in edge cases). Owner decision.
- **9–10 risk:** medium (changes which event a critical article joins); direction is towards more separate events, i.e. louder, not quieter.
- **Effort:** M (schema migration + 3 readers).
- **Proving test:** create event, call `state_machine._acknowledge_event`, assert `last_article_at` unchanged; memory match with an article older than `lookback_hours` from the last article but younger than the last status write → rejected as `uncertain`.

## F03 — Corroborator → dispatcher contract carries snapshots nobody trusts and drops the decision
- **Where:** `corroborator.py:40-96` returns `list[Event]`; `scheduler.py:299-301` dedups by id and filters `alert_status != "pending"`; `dispatcher.py` (`dispatch`) re-reads every event from the DB; `state_machine.py:391-399` re-reads it again.
- **Category:** data contract / dead code. **Severity:** high.
- **What's wrong:**
  - The `!= "pending"` filter never filters: events exist only at urgency ≥ `_MIN_EVENT_URGENCY` (5), and `_determine_alert_status` returns `sms`/`phone_call`/`dry_run` for every urgency ≥ 5 (`corroborator.py:434-445`). The real gate is the state machine's `log_only`.
  - The returned objects are discarded twice in favor of DB rows, so the only real payload is the event id.
  - The grouping decision (created vs attached, `duplicate`/`update`/`escalation`, revision advanced, matched an acknowledged event, article replay) is lost at the boundary. The state machine re-derives it from alert records.
- **Proposed refactor:** return `list[GroupingOutcome]` (frozen dataclass: `event_id`, `created: bool`, `decision: Literal[...]`, `revision_advanced: bool`, `replay: bool`). Scheduler passes outcomes; dispatcher loads each event once; drop the pending filter (or make it an explicit `urgency >= lowest alerting tier` check with a test). Keep a thin `events` accessor for the eval harness during transition.
- **BP:** yes (same events dispatched in the same order).
- **9–10 risk:** medium (dispatch input); mitigated by a parity test.
- **Effort:** M.
- **Enables:** TODO "Stale retry_pending…" (dispatcher can refuse a call when `replay` or when the event's call age exceeds a max) and "Unacknowledged calls are retried only when a new article joins" (a retry sweep can feed synthetic outcomes through the same entry point).
- **Proving test:** scheduler-level test that runs the existing incident-memory scenarios and asserts the set and order of `process_event` calls is identical before and after.

## F04 — `incident_memory` is an untyped dict mutated in three places; stored audit trail can lie
- **Where:** `models.py:139` (`incident_memory: dict`); writers `incident_memory.py:122-184` (`validate` replaces it), `corroborator.py:60-67` (replay branch replaces it), `corroborator.py:136-143` (mutates in place: `memory.update(...)`, `memory["decision"] = "escalation"`). Implicit keys: `decision`, `matched_event_id`, `confidence`, `reason`, `candidate_ids`, `article_replay`, `model_decision`, `model_confidence`.
- **Category:** weak typing / latent bug. **Severity:** high.
- **What's wrong:**
  - The rejection returns at `corroborator.py:118-130` (bad confidence or ids, or the matched event deleted by `cleanup_old_records` between `candidates()` and grouping) return `None` without rewriting the dict. The stored classification row then says `decision=duplicate, matched_event_id=X` although a new event was created and called.
  - The country/age rejection at `:136-138` sets `uncertain` but discards the model's original decision and confidence, unlike `validate`'s fallback, which keeps `model_decision`/`model_confidence`. Post-incident review of "why did this ring / not ring" is harder than it needs to be.
  - The correct behavior depends on the dict being mutated before `insert_classification` at `:85` (ordering coupling).
- **Proposed refactor:** `IncidentDecision` frozen dataclass (`decision: Literal["new","duplicate","update","escalation","uncertain"]`, `matched_event_id: str | None`, `confidence: float`, `reason: str`, `candidate_ids: tuple[str, ...]`, `model_decision: str | None`, `rejected_by: str | None`, `article_replay: bool = False`) with `to_dict()`/`from_dict()`. `validate` returns one; the matcher returns `(event | None, final_decision)`; `process_classifications` assigns it once before persisting. Every rejection sets `rejected_by` ("confidence", "candidate_allowlist", "event_missing", "country_gate", "memory_age").
- **BP:** alerting yes; the stored JSON gains keys and the two silent-rejection rows change from the model decision to `uncertain` (dashboard/eval readers see corrected data).
- **9–10 risk:** low.
- **Effort:** M.
- **Proving test:** delete the matched event before `process_classifications`; assert a new event exists AND the stored classification row has `decision == "uncertain"`, `rejected_by == "event_missing"`; snapshot test that the stored JSON for every existing `test_incident_memory.py` case is unchanged except the new keys.

## F05 — One malformed event row blocks all classification for up to `lookback_hours`
- **Where:** `models.py:28-31` (`_iso_to_dt`), `:40-45` (`_json_to_list`), `:244-259` (`Event.from_dict`, `d["summary_pl"]` required); called via `database.py:299-314` (`get_memory_events`) from `incident_memory.py:64-66` (`candidates`); `scheduler.py:250-260` catches the exception and marks the article `classification_failed`.
- **Category:** inconsistent error handling / fail-closed on the life-safety path. **Severity:** med (low probability, maximum blast radius).
- **What's wrong:** `get_memory_events` decodes every recent event. A single row with bad JSON in `article_ids`/`affected_countries` or a bad timestamp raises inside `candidates()`. The scheduler then fails EVERY article each cycle until the row ages out of the live 168 h window. No urgency 9–10 article is classified or alerted during that time. Rows are normally written by `list_to_json`, so this needs a manual edit, a migration bug or disk corruption, but the outcome is total silence.
- **Proposed refactor:** decode rows defensively in `get_memory_events` (skip and log a row that fails `Event.from_row`, with an error counter in `health.json`), and in the scheduler classify without memory when `candidates()` raises (an article without memory becomes a new event, which is the fail-open direction the rules already use for `uncertain`).
- **BP:** only in the failure case (today: no classification; after: classification with a new event). Owner should confirm the fail-open choice.
- **9–10 risk:** reduces risk.
- **Effort:** S.
- **Proving test:** insert an event with `article_ids = 'not json'` inside the lookback window; run one scheduler cycle with a fake classifier returning urgency 10 for PL; assert an event is created and `process_event` is called.

## F06 — Live grouping path lacks tests on its call-relevant branches
- **Where:** `corroborator.py:49-70` (article-replay branch), `:131-139` (memory-age gate), `:128-130` (matched event missing), `:398` (lifecycle-status preservation in memory mode). `tests/test_corroborator.py` (1269 lines, 36 tests) covers only the legacy path; memory-path tests live in `tests/test_incident_memory.py` and none of them hits these branches (grep for `article_replay`, `lookback`, `retry_pending`, `call_placed` in those tests finds nothing).
- **Category:** missing tests on critical paths. **Severity:** med.
- **What's wrong:** The replay branch returns the existing event as alertable, so a replayed article on a `retry_pending` critical event re-enters `_execute_phone_call` (relevant to TODO "Stale retry_pending…"). The age gate decides whether a critical article joins an old incident silently or gets its own call. Neither is pinned by a test, so F01–F04 refactors could change them unnoticed.
- **Proposed refactor:** add tests before any other change: (1) replay of an already-attached article returns the same event, writes `article_replay: True`, does not add a source or advance the revision; (2) memory match with event age `lookback_hours + 1` → new event, stored `uncertain`; (3) memory `update` on events in each of `acknowledged`, `retry_pending`, `call_placed`, `sms_sent`, `dry_run` → assert which statuses are kept (documents today's `sms_sent` flip, see F07); (4) matched event deleted → new event.
- **BP:** yes (tests only). **9–10 risk:** none. **Effort:** S.
- **Proving test:** the tests themselves; they must pass on current master.

## F07 — `alert_status` mixes a provisional tier label and the call lifecycle
- **Where:** `corroborator.py:425-445` (`_determine_alert_status`: hardcoded 9/7/5; the `>= 7` and `>= 5` branches both return `"sms"`; uses `classification.corroboration_required`, code default 2, live 1); `corroborator.py:398` (lifecycle preserve set `{"acknowledged","retry_pending","call_placed","expired"}`); writers in `state_machine.py:609,645,651,780,809`; `database.py:292` filters `!= 'expired'`; readers only `diagnostic.py:161`, the dashboard and the no-op scheduler filter (F03).
- **Category:** dead code / stringly typed state / hardcoded values (known exception in corroboration.md). **Severity:** med.
- **What's wrong:**
  - No runtime decision reads `alert_status`; the state machine only writes it. It is a display label with two owners.
  - `expired` is never written anywhere, yet it is preserved and filtered on.
  - `sms_sent` is missing from the preserve set, so an `update` on an SMS-tier event flips it back to `sms`.
  - On the legacy path every update overwrites `acknowledged`/`retry_pending` with `phone_call` (the DB label lies; `acknowledged_at` still holds).
  - Nine status strings are spread over four modules without a type.
- **Proposed refactor:** (a) BP: `EventStatus(StrEnum)` in `models.py`, one `LIFECYCLE_STATUSES` constant shared by corroborator and state machine, collapse the duplicate branch, delete `expired` from the preserve set and from `get_active_events` once F02/TODO decides whether expiry will exist. (b) Not BP: split into a derived `tier` (computed from `alerts.urgency_levels`, not stored) and a stored `lifecycle`; or drop `_determine_alert_status` and the second corroboration knob entirely, leaving `alerts.urgency_levels.critical.corroboration_required` as the single gate.
- **BP:** (a) yes, (b) no for stored data and dashboard labels; no effect on who gets called.
- **9–10 risk:** low. **Effort:** S (a), M (b).
- **Proving test:** F06 test (3) extended to every status; a test asserting `_determine_alert_status` agrees with `state_machine._determine_action` tiers for urgency 1–10.

## F08 — Time source is not injectable; eval harness patches module-level `datetime` in three modules
- **Where:** `corroborator.py:338`, `:382` (`datetime.now(UTC)`), `database.py:268`, `state_machine.py`; patched by `sentinel/eval/suite/runner.py:221`, `sentinel/eval/compare_models.py:370`, `sentinel/eval/direct_luna.py:117` (`patch("sentinel.classification.corroborator.datetime", ReplayClock)` etc.).
- **Category:** testability / refactor hazard. **Severity:** med.
- **What's wrong:** Any refactor in this area that moves a `datetime.now` call into a new module (for example F01's `safety.py` or `EventWriter`) silently makes eval replays use wall-clock time in the age and lookback gates. The eval would then measure a different grouping than production without failing.
- **Proposed refactor:** inject `clock: Callable[[], datetime] = lambda: datetime.now(UTC)` into `Corroborator`, `Database` and `AlertStateMachine`; the harnesses pass `ReplayClock.now`. Remove the `patch(...)` calls. Do this first in the phase plan.
- **BP:** yes. **9–10 risk:** low. **Effort:** S–M.
- **Proving test:** an eval replay unit test asserting `event.first_seen_at`, `event.last_updated_at` and the stored classification time equal `ReplayClock.current`, run without any `patch`.

## F09 — Source independence keys on the URL domain: Google News and Telegram can never corroborate
- **Where:** `corroborator.py:284-334` (`_is_independent_source`), `:447-458` (`_extract_domain`); `sentinel/fetchers/google_news.py:141,162` (link used as-is, `news.google.com`); `sentinel/fetchers/telegram.py:120` (`https://t.me/<channel>/<id>`).
- **Category:** latent bug / duplication (N+1 raw `SELECT *` instead of `Database.get_article_by_id`). **Severity:** med.
- **What's wrong:** Every Google News article has domain `news.google.com` and every Telegram channel has domain `t.me` (verified). Two different publishers found through Google News, or two different Telegram channels, never count as independent. This stays true after the TODO "Telegram fetcher mislabels every channel" fix. Combined with "Cyrillic titles normalize to empty", UA/RU and aggregator sources barely move `source_count`. Today it affects only labels and the "źródła: N" text, but it becomes a call gate if the owner chooses two sources ("Owner decision: corroboration for phone calls").
- **Proposed refactor:** one `publisher_key(article) -> str` (Telegram: `t.me/<channel>`; Google News: the publisher from the entry's `source` element stored in `raw_metadata`, else `source_name`; others: domain). Load all event articles in one query. Unit-test the key per source type.
- **BP:** no (source_count grows in more cases). Owner decision, bundled with the 1-vs-2-source decision.
- **9–10 risk:** none today (critical tier needs 1 source); high relevance if 2 sources become required.
- **Effort:** M (needs the Google News fetcher to keep the publisher).
- **Proving test:** two Telegram articles from `t.me/kpszsu/1` and `t.me/nexta_live/2` with different titles → `is_independent` true; two Google News links from different publishers → true; same publisher → false.

## F10 — The per-article grouping pipeline is copied four times (prod + three eval harnesses)
- **Where:** `scheduler.py:248-277`; `sentinel/eval/suite/runner.py:~197-225`; `sentinel/eval/compare_models.py:~328-375`; `sentinel/eval/direct_luna.py:~110-125` (each does `candidates → classify → validate → Corroborator(...).process_classifications([result])`, with its own variations: `direct_luna` builds a fresh `Corroborator` per article).
- **Category:** duplication / eval–prod drift. **Severity:** med.
- **What's wrong:** A change to the production order (for example F05's fail-open, or a new safety guard between `validate` and grouping) must be repeated in three harnesses, or the eval stops measuring production.
- **Proposed refactor:** `IncidentPipeline.ingest(article, classify) -> GroupingOutcome` in `sentinel/classification/`, owning `candidates`, `validate`, grouping and the transaction; the scheduler and all harnesses call it with their own `classify` callable and clock (F08).
- **BP:** yes. **9–10 risk:** low (scheduler path changes shape, not logic). **Effort:** M.
- **Proving test:** existing `tests/test_scheduler.py`, `tests/test_incident_memory.py::test_same_batch_second_classification_receives_first_event_memory` and the eval-suite runner tests pass; one test asserting the harness and the scheduler produce identical events for the same scripted classifier outputs.

## F11 — Escalation replaces the summary but keeps the first article's `event_type` and `aggressor`
- **Where:** `corroborator.py:376-381` (escalation updates `urgency_score`, `summary_pl`, `notification_revision` only); `state_machine.py:145,160,197,221` build the call text, SMS and push headline from `event.event_type` via `EVENT_TYPE_PL`.
- **Category:** latent bug (alert text). **Severity:** med.
- **What's wrong:** When an `airspace_violation` incident escalates to a confirmed `missile_strike`, the phone call and the update push still name the old type ("naruszenie przestrzeni powietrznej") while the summary describes a strike. The urgency is correct; the spoken headline understates it.
- **Proposed refactor:** on `escalation`, also adopt `result.event_type` (and `result.aggressor` when non-empty). Put this in `EventWriter.attach` from F01.
- **BP:** no (message text changes; who gets called does not). Light owner confirmation.
- **9–10 risk:** none to delivery; improves message accuracy.
- **Effort:** S.
- **Proving test:** extend `test_first_critical_escalation_revises_summary_once` to assert `event.event_type == "missile_strike"` after the escalation and that `_format_call_message` contains the new Polish type.

## F12 — Thresholds computed in three places; `_MIN_EVENT_URGENCY` hardcoded
- **Where:** `corroborator.py:248-257` (`_phone_call_threshold`, fallback 9), `incident_memory.py:59-62` (same logic, fallback 9), `state_machine.py:494-504` (sorted tiers); `corroborator.py:28` (`_MIN_EVENT_URGENCY = 5`, equals the live `medium.min_score`).
- **Category:** duplication / hardcoded values (the latter is a listed known exception). **Severity:** med.
- **What's wrong:** The critical confidence bar (`incident_memory.critical_min_confidence`) and the country gate both depend on "the phone-call threshold". It is computed independently in two modules with duplicated fallbacks. If someone lowers the critical tier to 8, all three must agree; today nothing asserts that.
- **Proposed refactor:** `AlertsConfig.phone_call_threshold` and `AlertsConfig.lowest_alerting_score` properties in `sentinel/config.py`, used by the corroborator, incident memory and state machine. Keep `_MIN_EVENT_URGENCY` as an alias to `lowest_alerting_score` only after the owner agrees (changing it changes which articles create events).
- **BP:** yes for the threshold property; no for deriving `_MIN_EVENT_URGENCY` if tiers ever diverge from 5 (today they match).
- **9–10 risk:** low. **Effort:** S.
- **Proving test:** config fixture with `critical.min_score = 8`: an urgency-8 article with confidence 0.86 (between `min_confidence` 0.85 and `critical_min_confidence` 0.9) is rejected by both `IncidentMemory.validate` and the corroborator, and requires a concrete country match.

## F13 — Raw SQL and hand serialization in the domain layer; `update_event` has no column allowlist
- **Where:** `corroborator.py:53-56` (`json_each` replay lookup), `:296`, `:304` (`SELECT * FROM articles`), `:404-413` (hand-serializes with `list_to_json` for `update_event(**kwargs)`); `database.py:262-279` (f-string `SET` built from kwargs keys).
- **Category:** unclear boundaries / error handling. **Severity:** low.
- **What's wrong:** The corroborator must know which columns are JSON. A typo in a kwarg raises `sqlite3.OperationalError` inside the grouping transaction; the memory path then marks the article `grouping_failed` and re-queues it every cycle, so a single code typo silently stops all event creation (tests would catch most typos, but nothing enforces column names).
- **Proposed refactor:** `Database.find_event_for_article(article_id)`, `Database.get_articles(ids)`, and `Database.save_event(event)` that serializes via `Event.to_dict()` with an allowlist derived from the dataclass fields.
- **BP:** yes. **9–10 risk:** low. **Effort:** S.
- **Proving test:** `update_event(event_id, bogus=1)` raises `ValueError` with the column name; existing tests pass.

## F14 — Legacy batch grouping has no per-article error isolation
- **Where:** `scheduler.py:288-293` (whole batch in one transaction, no `try`), versus the memory path's per-article `try` at `:264-277`.
- **Category:** inconsistent error handling. **Severity:** low (rollback path only).
- **What's wrong:** If the owner rolls back to the legacy path (`incident_memory.enabled: false`), one bad classification raises out of `run_cycle`, so the whole cycle dispatches nothing, including any 9–10 event in the same batch.
- **Proposed refactor:** group per result inside its own savepoint, as the memory path does (falls out of F10 for free).
- **BP:** only on error. **9–10 risk:** reduces risk on the rollback path. **Effort:** S.
- **Proving test:** legacy mode, a batch of [bad result, urgency-10 PL result] → the urgency-10 event is created and dispatched.

## F15 — Domain model typing and normalization ownership
- **Where:** `models.py:64-121` (`Article.from_dict` recomputes `url_hash` and `title_normalized` and ignores the stored columns), `:11-15` (`_normalize_title`), `:34-61` (`list_to_json`/`dict_to_json` public, `_json_to_list`/`_json_to_dict` private, both imported elsewhere), `:210-263` (`event_type`, `alert_status` bare `str`), `:266-310` (`AlertRecord.alert_type`/`status` bare `str`); `processing/deduplicator.py:38-41` reads the stored `title_normalized` column.
- **Category:** weak typing / hidden coupling. **Severity:** low.
- **What's wrong:** When TODO "Cyrillic titles normalize to empty" is fixed, rows decoded through `Article.from_dict` get the new normalization while `get_recent_titles` returns the old stored value, so the corroborator and the deduplicator compare different strings during the transition. The bare-string status and type fields make typos invisible.
- **Proposed refactor:** move `normalize_title` to `sentinel/utils/text.py` with one owner; add a one-off backfill of `articles.title_normalized` in `_migrate_schema` when the function changes (versioned); `Literal`/`StrEnum` for `alert_status`, `alert_type`, `AlertRecord.status`, `source_type`; rename the JSON helpers consistently.
- **BP:** yes for typing and the move; the normalization fix itself is a behavior change (known TODO).
- **9–10 risk:** none. **Effort:** S.
- **Proving test:** `mypy`/pyright on `sentinel/models.py` (no checker is configured today) and a test that a stored row's `title_normalized` equals `normalize_title(title)` after migration.

## F16 — Legacy-only dead entries and dry-run leakage
- **Where:** `corroborator.py:15-25` (`EVENT_COMPATIBILITY` lists `ground_assault` and `aerial_bombardment`, which the classifier never emits per `classifier.py:126-127`; no entry for `troop_movement` or `other`); `corroborator.py:34-37`, `:434-435` (`dry_run` writes `alert_status = "dry_run"` permanently into the DB; the scheduler never passes `dry_run`; the dispatcher owns dry-run separately).
- **Category:** dead code / boundary leak. **Severity:** low.
- **What's wrong:** Dead vocabulary hides which types really group on the rollback path. Dry-run is a delivery concern stored as grouping state.
- **Proposed refactor:** derive the vocabulary from one list shared with the classifier schema and add a test that every emitted `event_type` has an entry; remove `dry_run` from the corroborator.
- **BP:** yes for the dead entries; the dry-run removal changes the stored label in dry-run runs only.
- **9–10 risk:** none. **Effort:** S.
- **Proving test:** parametrized test over the classifier's `event_type` enum asserting `_are_compatible_types(t, t)` and an explicit entry.

---

## Proposed phase grouping (this area)

| Phase | Findings | Type | Gate |
|---|---|---|---|
| 0. Pin current behavior | F06 (new tests), F08 (inject clock; remove eval `patch`) | BP | New tests green on unchanged master; eval replay test green without `patch`. |
| 1. Contracts and types | F04 (`IncidentDecision`), F07a (`EventStatus` enum, shared lifecycle set), F12 (threshold property), F13 (DB API, allowlist), F15 typing | BP (F04 changes stored audit JSON only) | Full test suite green; stored-JSON snapshot test diff shows only new keys. |
| 2. Structure | F01 (`safety.py`, split groupers, `EventWriter`, ack-guard flag default off), F03 (`GroupingOutcome`), F10 (`IncidentPipeline.ingest`), F14 falls out of F10, F16 dead entries | BP | Dispatch-parity test (same `process_event` calls and order); eval harness parity test; owner sees no change in calls. |
| 3. Owner decisions (one at a time, each eval-gated) | F01 flag on (TODO "acknowledged-event guard"), F02 (`last_article_at`), F05 fail-open, F11 escalation type, F09 publisher key (bundled with the 1-vs-2-source decision), F07b status split | Behavior changes | Owner sign-off per item; F02/F09 rerun the eval replay before deploy. |

Phase 0 must come first: F08 removes the module-level `datetime` patches that any later file move would silently break, and F06 pins the replay, age-gate and lifecycle branches that the later refactors touch. After Phase 2, the TODO fixes "Stale retry_pending calls after a Twilio recharge" and "Unacknowledged calls are retried only when a new article joins the event" become a dispatcher-side change on `GroupingOutcome` plus an age check, without touching grouping.
