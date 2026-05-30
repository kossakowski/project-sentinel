> ⚠️ **HISTORIC — archived 2026-05-30.** Describes a completed implementation effort; do not consult as current truth. See [docs/archive/README.md](README.md) and the living docs it points to.

# Project Sentinel — Async Refactor of Blocking Calls (Code Debt #4) — Implementation Specification

## Overview

When complete, Project Sentinel's async pipeline will no longer freeze its asyncio event loop. The classifier will use `anthropic.AsyncAnthropic` with `await`ed API calls and `asyncio.sleep` retries; the alert state machine's phone-call retry/poll loop will `await asyncio.sleep` and offload every blocking Twilio HTTP call via `asyncio.to_thread`; and a single `asyncio.Lock` around `run_cycle` will guarantee the fast and slow scheduler lanes never execute concurrently, preserving the one-cycle-at-a-time invariant that the synchronous blocking previously provided by accident. Behavior — alert timing, retry counts, thresholds, classification order — is unchanged; this is a pure concurrency-correctness refactor that must keep all 310 existing tests green.

## Goals

- Stop the synchronous Anthropic SDK call (`classifier.py`) from freezing the event loop for ~2-3s per article.
- Stop the alert state machine's `time.sleep` loop (`state_machine.py`) from freezing the event loop for up to ~8 minutes during a phone-call alert.
- Prevent the fast/slow scheduler lanes from racing on shared `state_machine`/`db`/`corroborator` state once the blocking calls become non-blocking (no duplicate alerts, no clobbered confirmation state).
- Keep every documented CLI command (`--test-headline`, `--test-file`, `--test-alert`, eval) working after `classify()` and the alert methods become coroutines.
- Keep `TwilioClient` synchronous and its tests untouched.
- Keep all SQLite access on the event-loop thread (single shared connection, no application-level lock).

## Non-Goals

- **Bounded-concurrency classification** — `classify_batch` stays sequential. No `asyncio.gather`/semaphore over articles. (Decision: the loop-unblocking comes from `await`, not parallelism; sequential preserves rate-limit behavior and per-article error isolation.)
- **Background-task alert dispatch / "keep monitoring during a call"** — dispatch is not moved to `asyncio.create_task`. An in-flight alert holds the cycle lock for its duration. (Decision: avoids reintroducing the alert-path races; a deliberate redesign for a future spec if the alert-window monitoring gap proves to matter.)
- **TwilioClient async rewrite** — `twilio_client.py` is not modified; the synchronous SDK is wrapped at the call sites.
- **Async-ifying the remaining sync DB/CPU steps in `run_cycle`** (`deduplicate_batch`, `process_classifications`, `cleanup_old_records`, normalizer, keyword filter) — they stay synchronous on the loop thread. They contain no sleeps and are out of scope.
- **Any behavioral change to alert logic** — retry counts, cooldowns, urgency thresholds, corroboration, poll/wait durations, message content, and the dual-lane intervals are all preserved. De-hardcoding the poll constants (Phase 3, SHOULD) keeps the same default values.
- **Removing the inline 90s call-poll in favor of the cross-cycle `check_pending_calls` mechanism** — that is a behavioral redesign, out of scope.
- **Changing the APScheduler job structure** beyond adding the lock inside `run_cycle`.

## Technical Context

- **Language/runtime:** Python 3.11 (ruff `target-version = "py311"`).
- **Async stack:** APScheduler `AsyncIOScheduler`; the process is bootstrapped via `asyncio.run(...)` in `sentinel.py:main()` for the `run_continuous`/`run_once`/`run_diagnostic` modes. `run_cycle` (`scheduler.py:204`) is already `async def` and already `await`s `_fetch_all` (221) and `enrich_batch` (239).
- **Dual lane:** `start()` (`scheduler.py:461`) registers two separate APScheduler jobs — `sentinel_fast_lane` and `sentinel_slow_lane` — each `max_instances=1, coalesce=True`. `max_instances=1` is **per job**, so the two lanes can interleave; today they don't only because the synchronous classify/dispatch calls freeze the single event-loop thread. Both lanes call the same `run_cycle` on one shared `SentinelPipeline` instance, hitting all three target call sites (`scheduler.py:245`, `262`, `265`).
- **Linting:** ruff with `select = [E, W, F, I, UP, B, SIM]`, `ignore = [E501]`, `line-length = 120`, isort `known-first-party = ["sentinel"]`. **`F` (pyflakes) flags unused imports**, so an `import time` left behind after removing `time.sleep` is a lint failure.
- **Type checking:** none configured (no mypy). No type-check gate criteria.
- **Tests:** pytest with `pytest-asyncio==1.3.0` installed. `asyncio_mode` is **not** configured (default strict), so existing async tests (`tests/test_scheduler.py`) carry explicit `@pytest.mark.asyncio` markers; new async tests MUST do the same. 310 tests currently pass.
- **Integration points / call sites that break when methods go async** (verified):
  - `classify()` callers: `sentinel/eval/harness.py:259` (sync `run_eval`), `sentinel.py:310` (`_run_test_headline`), `sentinel.py:355` (`_run_test_file`), and `classifier.py:207` (internal, `classify_batch`).
  - `classify_batch()` caller: `scheduler.py:245`.
  - alert-method callers: `dispatcher.py:34` (`process_event`), `scheduler.py:262`/`265` (`dispatch`/`check_pending_calls`), `sentinel.py:457`/`459` (`_run_test_alert` → `_execute_phone_call`/`_execute_sms`).
  - `run_eval()` caller: `sentinel.py:385` (`_run_eval`).
- **Database:** `sentinel/database.py` holds one `sqlite3` connection (`check_same_thread=False`, WAL, **no application-level lock**). Safe only while all access stays on the single event-loop thread.

## Architecture Decisions

- **Decision:** `classify_batch` processes articles sequentially with `await`, not concurrently.
  **Rationale:** The event-loop freeze (the stated bug) is solved by `await` alone — during each awaited API call the loop runs other coroutines. Concurrency would only shorten batch wall-clock, which matters solely in a high-volume spike; it adds a semaphore, changes the Anthropic load profile, and complicates per-article error isolation. Not worth it for this change.

- **Decision:** A single `asyncio.Lock` on the pipeline serializes the entire `run_cycle` body across both lanes.
  **Rationale:** Once the classify/dispatch/check-pending calls `await`, the two lanes can interleave at those yield points and race on shared alert/DB state (TOCTOU duplicate phone calls; clobbered `self._confirmation_*`). A whole-cycle lock restores today's effective "one cycle at a time" behavior with minimal code. `coalesce=True` already collapses fast-lane ticks missed while waiting. Whole-cycle (not tail-only) was chosen so cross-lane fetches don't double-fetch and stress dedup.

- **Decision:** Wrap the synchronous Twilio SDK calls in `asyncio.to_thread` at the `state_machine.py` call sites; do not modify `TwilioClient`.
  **Rationale:** Honors constraint 4 ("don't restructure TwilioClient"), keeps `test_twilio_client.py` green, and completes the non-blocking-loop goal cheaply. Only the Twilio HTTP call is offloaded; DB access stays on the loop thread (constraint 8).

- **Decision:** Bridge the sync CLI/eval entry points to the now-async methods with `asyncio.run(...)`, mirroring how `sentinel.py` already launches `run_continuous`/`run_once`/`run_diagnostic`. `run_eval` itself becomes `async def`.
  **Rationale:** Idiomatic and uniform with existing code; avoids a permanent parallel sync code path (no `classify_sync` shim) and avoids per-article event-loop churn.

## Assumptions

(Review and override before running code-refiner.)

- Output spec file is `SPEC_ASYNC_REFACTOR.md` (the names `SPEC.md` and `SPEC_ALERT_GROUPING.md` are already taken by the dashboard and alert-grouping specs).
- `anthropic>=0.40` (installed) exposes `anthropic.AsyncAnthropic` with a `messages.create(...)` coroutine that accepts the identical arguments and returns the same `anthropic.types.Message` type as the sync client.
- `asyncio.Lock()` constructed in `SentinelPipeline.__init__` (before the event loop is running) is valid on Python 3.10+ — it binds to the running loop lazily on first `await`. The executor MUST NOT "fix" this by lazily creating the lock.
- `tests/conftest.py` provides `config` and `db` fixtures (real temp SQLite, real `SentinelConfig`); state-machine/classifier tests build on these and on the file-local `mock_twilio` fixture. No async or event-loop fixtures exist; converted async tests rely on `@pytest.mark.asyncio`.
- `sentinel/config.py` is the config schema; new `alerts.acknowledgment` fields (Phase 3, SHOULD) follow the existing pattern there and default to the current hardcoded values, so existing `config.yaml` files keep working without edits.
- The eval set and `_make_article`/`_check_case`/metrics/cost helpers in `harness.py` are unaffected by making `run_eval` async (only the classify call and the function signature change).
- "All 310 tests pass" is the verified current baseline and the regression bar.

---

## Phase 1 — Cross-Lane Cycle Serialization Lock

Implemented **first** so that the `await`s introduced in Phases 2 and 3 never open an unguarded interleave window between the lanes. The lock is a near-no-op while the cycle tail is still synchronous (it only begins serializing cross-lane fetches), and becomes load-bearing as soon as async lands in the tail.

### Deliverables

- `sentinel/scheduler.py` — add an `asyncio.Lock` to `SentinelPipeline` and wrap the `run_cycle` body with it (modify existing).
- `tests/test_scheduler.py` — add serialization + lock-release tests (modify existing).

### Requirements

**1.1** — Cycle mutual exclusion.
**1.1a** — `SentinelPipeline.__init__` MUST create exactly one `asyncio.Lock`, stored as a private instance attribute (e.g. `self._cycle_lock`). It MUST be constructed in `__init__` (not lazily). _(Rationale: see Assumptions — `asyncio.Lock()` binds to the loop lazily; constructing it once keeps a single shared lock for both lanes.)_
**1.1b** — `run_cycle` MUST acquire that lock for the entire duration of its body via `async with self._cycle_lock:` wrapping all pipeline steps (fetch through cleanup), so at most one `run_cycle` invocation runs at a time across both lanes and the immediate startup cycle.
**1.1c** — The lock MUST be released whether `run_cycle` returns normally or raises (guaranteed by `async with`), so a failed cycle never deadlocks later cycles.
**1.1d** — Adding the lock MUST NOT change `run_cycle`'s returned `CycleResult` contents, the order of pipeline steps, or any externally observable behavior other than cross-lane serialization.
**1.1e** — `_run_fast_lane`, `_run_slow_lane`, and `_run_with_error_handling` MUST NOT acquire the lock themselves (it lives inside `run_cycle`), preserving the existing error-handling and health-update flow. The direct `await pipeline.run_cycle()` calls in `sentinel.py` (`run_continuous`/`run_once`/`run_diagnostic`) MUST therefore also be serialized by the same lock without changes to those call sites.

### Acceptance Tests

1. `test_run_cycle_serializes_concurrent_invocations` — (integration) [1.1, 1.1a, 1.1b] Construct a `SentinelPipeline` with mocked components; patch one async step (e.g. `_fetch_all`) to record a concurrency counter (increment on entry, `await asyncio.sleep(0)`, decrement on exit). Launch two `run_cycle` coroutines via `asyncio.gather` and assert the observed concurrency never exceeds 1.
2. `test_run_cycle_releases_lock_on_error` — (integration) [1.1c] Make a mocked step raise inside `run_cycle`; assert the exception propagates and a subsequent `run_cycle` still acquires the lock and runs (no deadlock).
3. `test_run_cycle_returns_result` — (integration) [1.1d] With mocked components, a single `run_cycle` returns a `CycleResult` (existing behavior preserved).
4. `test_cycle_lock_is_asyncio_lock` — (unit) [1.1a] After construction, the pipeline's lock attribute is an `asyncio.Lock` instance.

### Gate Criteria

- `.venv/bin/pytest tests/test_scheduler.py -v` — scheduler tests pass.
- `.venv/bin/pytest tests/ -q` — full suite green (310+ tests).
- `.venv/bin/ruff check sentinel/scheduler.py tests/test_scheduler.py` — no lint errors.
- `python -c "import asyncio, inspect; from sentinel.scheduler import SentinelPipeline; assert inspect.iscoroutinefunction(SentinelPipeline.run_cycle)"` — import succeeds and `run_cycle` is a coroutine function.

---

## Phase 2 — Classifier Async Conversion

### Dependencies on Previous Phases

- Requires Phase 1's cycle lock to be in place, so the new `await self.classifier.classify_batch(...)` at `scheduler.py:245` does not create an unguarded cross-lane interleave window.

### Deliverables

- `sentinel/classification/classifier.py` — `AsyncAnthropic` client; `classify`, `classify_batch`, `_call_api`, `_send_request` become `async`; `time.sleep`→`await asyncio.sleep`; swap `import time` for `import asyncio`; optional `aclose()` (modify existing).
- `sentinel/eval/harness.py` — `run_eval` becomes `async def`, `await classifier.classify(article)` (modify existing).
- `sentinel.py` — bridge `_run_test_headline` (310), `_run_test_file` (355), and `_run_eval` (385) to the async methods via `asyncio.run(...)` (modify existing).
- `sentinel/scheduler.py` — `await self.classifier.classify_batch(relevant)` at line 245 (modify existing).
- `tests/test_classifier.py` — convert the 12 tests to async; switch the mock to `AsyncMock`/`AsyncAnthropic`; fix the retry test to patch `asyncio.sleep` (modify existing).
- `tests/test_cli_bridges.py` — smoke tests that the async CLI bridges complete with mocked dependencies (create; Phase 3 adds the alert-bridge case to the same file).

### Requirements

**2.1** — Async Anthropic client and call path.
**2.1a** — `Classifier.__init__` MUST construct `anthropic.AsyncAnthropic()` (replacing `anthropic.Anthropic()` at `classifier.py:158`), stored as `self.client`. `__init__` MUST remain a normal (non-async) `def`.
**2.1b** — `_send_request` MUST be `async def` and MUST `await self.client.messages.create(...)`, preserving the same keyword arguments (`model`, `max_tokens`, `temperature`, `system`, `messages`) and the `anthropic.types.Message` return type.
**2.1c** — `_call_api` MUST be `async def`, MUST `await self._send_request(article)`, and on `anthropic.APIError` MUST `await asyncio.sleep(5)` (replacing `time.sleep(5)` at `classifier.py:266`) before retrying exactly once. The retry count (one) and the caught exception type (`anthropic.APIError`) MUST be unchanged.
**2.1d** — `classify` MUST be `async def` and MUST `await self._call_api(article)`. Its JSON parsing, value clamping, `ClassificationResult` construction, and `_track_tokens(...)` call MUST be unchanged.
**2.1e** — `classify_batch` MUST be `async def` and MUST process articles **sequentially**, `await`ing `self.classify(article)` one at a time in input order. Per-article `json.JSONDecodeError` and `anthropic.APIError` handling (log at ERROR, skip the article) MUST be preserved. The return value MUST remain a `list[ClassificationResult]` in input order, excluding skipped articles.
**2.1f** — `classify_batch` MUST NOT use any concurrency primitive (`asyncio.gather`, `asyncio.Semaphore`, `asyncio.TaskGroup`, etc.). _(Rationale: sequential is a deliberate decision; see Architecture Decisions.)_
**2.1g** — `classifier.py` MUST remove `import time` (now unused — pyflakes `F401` would fail the lint gate) and MUST add `import asyncio`.

**2.2** — Scheduler awaits the classifier.
**2.2a** — `scheduler.py:245` MUST become `await self.classifier.classify_batch(relevant)`. The surrounding `try/except Exception` that logs and falls back to `classifications = []` MUST be preserved.

**2.3** — Eval harness async.
**2.3a** — `run_eval` (`harness.py:247`) MUST become `async def` and MUST `await classifier.classify(article)` at line 259. Its per-case `try/except`, `compute_metrics`, `compute_cost`, and `EvalReport` construction MUST be unchanged.
**2.3b** — `sentinel.py:_run_eval` MUST invoke the harness via `asyncio.run(run_eval(eval_set_path, config))` and otherwise preserve its reporting/exit-code behavior.

**2.4** — CLI classify bridges.
**2.4a** — `sentinel.py:_run_test_headline` MUST run the now-async `classify` for its single article via `asyncio.run(...)`, preserving its result printing.
**2.4b** — `sentinel.py:_run_test_file` MUST run the now-async `classify` calls under a **single** `asyncio.run(...)` (e.g. wrapping an inner async helper that loops over headlines), NOT one `asyncio.run(...)` per article. _(Rationale: per-article loop creation/teardown is wasteful and alters error semantics.)_

**2.5** — Async client cleanup.
**2.5a** — `Classifier` SHOULD expose an `async def aclose(self)` that awaits `self.client.close()`.
**2.5b** — `SentinelPipeline.shutdown` SHOULD `await self.classifier.aclose()` to avoid "unclosed client" warnings. _(SHOULD, not MUST: the process runs 24/7 and shutdown is rare; the warning is cosmetic.)_

### Acceptance Tests

1. `test_classify_invasion_headline` (+ the 11 other existing classifier tests) — (unit) [2.1a, 2.1b, 2.1d] Converted to `async def` with `@pytest.mark.asyncio`; the mock client is an `AsyncMock` whose `messages.create` is awaitable and returns the existing `SimpleNamespace` response shape; assert the classification fields as before.
2. `test_api_error_handled` — (unit) [2.1c] Patch `sentinel.classification.classifier.asyncio.sleep` (as an `AsyncMock`); raise `anthropic.APIError` once then succeed; assert exactly one retry and that the patched async sleep was awaited once with `5`.
3. `test_classify_batch_is_sequential` — (unit) [2.1e, 2.1f] `classify` replaced with an `AsyncMock` whose side effect increments a shared counter, `await asyncio.sleep(0)`, then decrements; assert the counter never exceeds 1 and results preserve input order.
4. `test_classify_batch_skips_failures` — (unit) [2.1e] One article raises `anthropic.APIError`, another raises `json.JSONDecodeError`, a third succeeds; assert only the successful result is returned and order is preserved.
5. `test_run_eval_is_async` — (integration) [2.3a] `inspect.iscoroutinefunction(run_eval)` is true; awaiting it with a mocked classifier returns an `EvalReport` with the expected case count.
6. `test_run_cycle_awaits_classifier` — (integration) [2.2a] Drive the real `run_cycle` with mocked components and `classifier.classify_batch` as an `AsyncMock`; assert it is awaited once and the cycle completes without an un-awaited-coroutine warning.
7. `test_cli_classify_bridges_complete` — (unit) [2.4a, 2.4b] Patch `Classifier` so `classify` is an `AsyncMock` returning a result; call `_run_test_headline` and `_run_test_file` (multi-headline fixture); assert both return without raising and that `_run_test_file` drives all classifications under a single `asyncio.run` (e.g. patch `asyncio.run` and assert called once).
8. `test_classifier_aclose` — (unit) [2.5a] With `self.client.close` patched as an `AsyncMock`, `await classifier.aclose()` awaits it exactly once. (Only required if 2.5 is implemented.)

### Gate Criteria

- `.venv/bin/pytest tests/test_classifier.py tests/test_cli_bridges.py -v` — classifier and CLI-bridge tests pass.
- `.venv/bin/pytest tests/ -q` — full suite green (310+ tests).
- `.venv/bin/ruff check sentinel/classification/classifier.py sentinel/eval/harness.py sentinel.py sentinel/scheduler.py tests/test_classifier.py tests/test_cli_bridges.py` — no lint errors (in particular, no unused `import time`).
- `python -c "import inspect; from sentinel.classification.classifier import Classifier; assert inspect.iscoroutinefunction(Classifier.classify) and inspect.iscoroutinefunction(Classifier.classify_batch) and inspect.iscoroutinefunction(Classifier._call_api) and inspect.iscoroutinefunction(Classifier._send_request)"` — classifier methods are coroutines.
- `python -c "import inspect; from sentinel.eval.harness import run_eval; assert inspect.iscoroutinefunction(run_eval)"` — `run_eval` is a coroutine.

---

## Phase 3 — Alert State Machine Async + Twilio Offload

### Dependencies on Previous Phases

- Requires Phase 1's cycle lock: the alert path gains many `await` points, so without the lock the lanes would interleave inside the alert decision/execution sequence (TOCTOU duplicate calls; clobbered `self._confirmation_*`).
- Independent of Phase 2 in terms of files, but Phase 1 MUST precede it.

### Deliverables

- `sentinel/alerts/state_machine.py` — convert the alert-execution methods to `async`; `time.sleep`→`await asyncio.sleep`; wrap Twilio SDK calls in `await asyncio.to_thread(...)`; swap `import time` for `import asyncio`; (SHOULD) read poll/pause durations from config (modify existing).
- `sentinel/alerts/dispatcher.py` — `dispatch` becomes `async def`, `await self.state_machine.process_event(event)` (modify existing).
- `sentinel/scheduler.py` — `await self.dispatcher.dispatch(...)` (262) and `await self.state_machine.check_pending_calls()` (265) (modify existing).
- `sentinel.py` — `_run_test_alert` runs the now-async `_execute_phone_call`/`_execute_sms` via `asyncio.run(...)` (modify existing).
- `sentinel/config.py` + `config/config.example.yaml` — (SHOULD) add `alerts.acknowledgment` poll/pause keys (modify existing).
- `tests/test_state_machine.py` — convert the ~20 tests to async; patch `asyncio.sleep`; adjust Twilio mocks for awaited paths (modify existing).
- `tests/test_dispatcher.py` — convert `dispatch` tests to async (modify existing).
- `tests/test_cli_bridges.py` — add the `_run_test_alert` async-bridge smoke test (modify; created in Phase 2).

### Requirements

**3.1** — Async alert-execution path.
**3.1a** — The following `AlertStateMachine` methods MUST become `async def` (they perform, or transitively call, a sleep or a Twilio network call): `process_event`, `_execute_phone_call`, `_wait_for_call_and_check_sms`, `_execute_sms`, `_send_confirmation_sms`, `_send_followup_sms`, `_send_update_sms`, `_check_sms_confirmation`, `_check_confirmation_sms_delivered`, `_acknowledge_event`, `_handle_call_result`, and `check_pending_calls`. All internal calls between them MUST be `await`ed.
**3.1b** — The pure decision/DB-read/DB-write helpers that perform no sleep and no network I/O MUST remain synchronous `def`: `_determine_action`, `_is_in_cooldown`, `_user_already_notified`, `_is_acknowledged`, `_last_alert_time`, and `_update_alert_record`. _(Rationale: minimal diff; these never block the loop.)_
**3.1c** — `time.sleep(10)` (`state_machine.py:317`) and `time.sleep(poll_interval)` (`state_machine.py:432`) MUST be replaced with `await asyncio.sleep(...)`.
**3.1d** — `state_machine.py` MUST remove `import time` (now unused — `F401` lint failure otherwise) and MUST add `import asyncio`.

**3.2** — Twilio I/O offloaded to threads.
**3.2a** — Every synchronous Twilio SDK call on the alert path MUST be invoked via `await asyncio.to_thread(...)`: the wrapper methods `make_alert_call`, `send_sms`, and `get_call_status`, AND the two direct SDK calls `self.twilio.client.messages.list(...)` (`state_machine.py:381`) and `self.twilio.client.messages(sid).fetch()` (`state_machine.py:409`).
**3.2b** — `sentinel/alerts/twilio_client.py` MUST NOT be modified; `TwilioClient` methods remain synchronous and `tests/test_twilio_client.py` MUST pass unchanged. _(Rationale: constraint 4.)_
**3.2c** — No `self.db.*` (or any `Database`) call MUST be placed inside an `asyncio.to_thread(...)` callable; all SQLite access MUST remain on the event-loop thread. _(Rationale: the shared `sqlite3` connection has no application-level lock; off-thread access would race. Constraint 8.)_

**3.3** — Dispatcher async.
**3.3a** — `AlertDispatcher.dispatch` MUST become `async def` and MUST `await self.state_machine.process_event(event)` for each non-dry-run event, preserving the urgency-descending sort order.
**3.3b** — The dry-run path (`_log_dry_run`, which calls only the synchronous `_determine_action`) MAY remain synchronous.
**3.3c** — `dispatch` MUST process events **sequentially** (await each `process_event` before the next); it MUST NOT use `asyncio.gather`/`TaskGroup` over events. _(Rationale: per-event confirmation state lives on the shared `state_machine` instance (`self._confirmation_code`, `self._confirmation_sms_sid`); concurrent events would clobber it. Serial dispatch + the Phase 1 lock keep alert state correct without moving it off `self`.)_

**3.4** — Scheduler awaits the alert path.
**3.4a** — `scheduler.py:262` MUST become `await self.dispatcher.dispatch(alertable_events)` and `scheduler.py:265` MUST become `await self.state_machine.check_pending_calls()`. These remain gated behind `if not diagnostic:` exactly as today.

**3.5** — CLI alert bridge.
**3.5a** — `sentinel.py:_run_test_alert` MUST run the now-async `_execute_phone_call(event)` / `_execute_sms(event)` via `asyncio.run(...)`, preserving its synthetic article/event setup and printed output.

**3.6** — De-hardcode poll/pause durations.
**3.6a** — The hardcoded `max_wait = 90` and `poll_interval = 5` (`state_machine.py:427-428`) and the `10`-second inter-retry pause (`state_machine.py:317`) SHOULD be read from config under `alerts.acknowledgment` as `call_poll_timeout_seconds` (default 90), `call_poll_interval_seconds` (default 5), and `call_retry_pause_seconds` (default 10). _(Rationale: project rule "nothing is hardcoded"; these exact lines are being edited anyway. Defaults preserve current behavior exactly.)_
**3.6b** — If 3.6a is implemented, `config/config.example.yaml` SHOULD document the three keys and the config schema in `sentinel/config.py` SHOULD define them with the stated defaults, so existing `config.yaml` files (lacking the keys) keep working.

**3.7** — Behavior preservation.
**3.7a** — The phone-call retry count (`max_call_retries`), cooldown logic, SMS-confirmation logic, acknowledgment flow, and message formatting MUST be unchanged; only the `def`→`async def`, `time.sleep`→`await asyncio.sleep`, and Twilio→`to_thread` transformations (plus the optional config reads in 3.6) are in scope.

### Acceptance Tests

1. `test_new_critical_event_triggers_call` (+ the other existing state-machine tests, ~20 total) — (unit) [3.1, 3.2, 3.7] Converted to `async def` with `@pytest.mark.asyncio`; the `asyncio.sleep` is patched (via `@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)`) so tests don't really sleep; `mock_twilio` methods that are now reached through `to_thread` still record calls and return their configured values; assert the same alert outcomes as before.
2. `test_api_call_retry_pause_is_awaited` — (unit) [3.1c] In a multi-retry scenario, assert the patched `asyncio.sleep` is awaited (not `time.sleep`).
3. `test_twilio_calls_routed_through_to_thread` — (unit) [3.2a] Patch `sentinel.alerts.state_machine.asyncio.to_thread` with an `AsyncMock` side-effect that calls through to its first arg; drive a phone-call path; assert `to_thread` was awaited with `get_call_status` (and `make_alert_call`).
4. `test_db_calls_not_offloaded_to_thread` — (unit) [3.2c] With `asyncio.to_thread` patched to record its first positional arg across a full alert path, assert none of the recorded callables is a bound method of `Database`.
5. `test_dispatch_is_async_and_sequential` — (unit) [3.3a, 3.3c] `inspect.iscoroutinefunction(AlertDispatcher.dispatch)` is true; with `process_event` replaced by an `AsyncMock` that records concurrent entry, dispatching multiple events keeps observed concurrency at 1 and preserves urgency-desc order.
6. `test_dispatch_dry_run_logs_without_alerting` — (integration) [3.3b] In dry-run, `dispatch` logs intended actions and does not call `process_event` (existing behavior preserved).
7. `test_poll_durations_from_config` — (unit) [3.6a] (If 3.6 implemented) `_wait_for_call_and_check_sms` uses the configured `call_poll_timeout_seconds`/`call_poll_interval_seconds`; defaults are 90/5.
8. `test_run_cycle_awaits_dispatch_and_check_pending` — (integration) [3.4a] Drive the real non-diagnostic `run_cycle` with `dispatcher.dispatch` and `state_machine.check_pending_calls` as `AsyncMock`s; assert both are awaited and the cycle completes without an un-awaited-coroutine warning.
9. `test_run_test_alert_bridges_async` — (unit) [3.5a] Patch `Database`, `TwilioClient`, and `AlertStateMachine` (with `_execute_phone_call`/`_execute_sms` as `AsyncMock`s); call `_run_test_alert("phone_call")` and `_run_test_alert("sms")`; assert each completes without raising and the async method was awaited.

### Gate Criteria

- `.venv/bin/pytest tests/test_state_machine.py tests/test_dispatcher.py tests/test_twilio_client.py tests/test_cli_bridges.py -v` — alert, dispatcher, unchanged Twilio-client, and CLI-bridge tests pass.
- `.venv/bin/pytest tests/ -q` — full suite green (310+ tests).
- `.venv/bin/ruff check sentinel/alerts/ sentinel/scheduler.py sentinel.py tests/test_state_machine.py tests/test_dispatcher.py tests/test_cli_bridges.py` — no lint errors (no unused `import time`).
- `python -c "import inspect; from sentinel.alerts.state_machine import AlertStateMachine as S; from sentinel.alerts.dispatcher import AlertDispatcher as D; assert all(inspect.iscoroutinefunction(getattr(S, m)) for m in ['process_event','_execute_phone_call','_wait_for_call_and_check_sms','_execute_sms','check_pending_calls','_check_sms_confirmation','_check_confirmation_sms_delivered']); assert inspect.iscoroutinefunction(D.dispatch)"` — alert/dispatch methods are coroutines.
- `python -c "import inspect; from sentinel.alerts.state_machine import AlertStateMachine as S; assert not inspect.iscoroutinefunction(S._determine_action) and not inspect.iscoroutinefunction(S._is_in_cooldown)"` — pure helpers remain synchronous.
