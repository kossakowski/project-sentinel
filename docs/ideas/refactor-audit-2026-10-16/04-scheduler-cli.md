# Audit 04 — Orchestration and entry points (scheduler, CLI, diagnostic, logging, run.sh, utils)

Auditor scope: `sentinel/scheduler.py`, `sentinel.py`, `sentinel/diagnostic.py`, `sentinel/logging_setup.py`,
`run.sh`, `sentinel/utils/`, plus the tests `tests/test_scheduler.py`, `tests/test_integration.py`,
`tests/test_utils_datetime.py`, `tests/test_cli.py` and `docs/reference/cli.md`.
Repo state: master @ 835ed8e, read-only. Date: 2026-10-16.

What I ran (no paid commands):
- `.venv/bin/pytest tests/test_scheduler.py tests/test_integration.py tests/test_utils_datetime.py tests/test_cli.py -q` → 30 passed (127 s; 44 s of that is two `test_cli.py` subprocess tests that do real network fetches).
- A scratch probe (outside the repo) that re-runs `test_pipeline_survives_twilio_failure` with instrumentation and a variant with a keyword-matching headline (results in F1 and F8).
- A direct probe of `sentinel.utils.strip_html` (results in F10).

Known items referenced, not rediscovered (TODO.md):
- §0 "Unacknowledged calls are retried only when a new article joins the event", "Stale retry_pending calls after a Twilio recharge", "No working out-of-band watchdog (check-health.sh)", "Owner sign-off: acknowledged-event guard is gone in incident-memory mode".
- §6.1 #4 (`--test-alert push` help text), #9 (`--test-file` list YAML crash), #10 (local default config), #12 (daily summary), #17 (`--dry-run` pending-call check).
- Accuracy check of known items: #12 and #17 are described correctly against current code (`scheduler.py:101-113`, `:605-618`; `:304-309`). One precision note on #12: the logged summary is not "the previous day with one cycle"; it is the first cycle of the *new* day, so the previous day's totals are lost entirely. The §0 item "Unacknowledged calls…" cites `scheduler.py:287-306`; the dispatch block is now at `:300-309` (drift of a few lines, content still correct). The §0 watchdog item covers only `check-health.sh`; it does not mention that the in-process health SMS (F5) is also a dead channel.

Severity scale: high = can delay or drop a 9–10 alert, or hides that monitoring is down; med = real defect or debt that weakens safety margins or tests; low = hygiene.

---

## F1 — Alerts of events grouped in a cycle can be lost for good (no per-event isolation, no outbox)

- **File:line:** `sentinel/scheduler.py:262` (`incident_memory.validate` outside the `try`), `:300-309` (single dispatch at cycle end); `sentinel/alerts/dispatcher.py:45-50` (no `try` around `process_event`); `sentinel/alerts/twilio_client.py:60`, `:93`, `:123` (catch only `TwilioRestException`).
- **Category:** error isolation / latent bug.
- **Severity:** high.
- **What's wrong:**
  - In the live incident-memory path every article's event is committed to the DB inside the loop (`:264-268`), but dispatch happens once, after the whole loop.
  - Anything that raises after a commit and before or during dispatch aborts `run_cycle`. Examples: `validate()` for a later article (it is outside the `try`), a `classification_failed()` DB error inside an `except`, or a non-Twilio exception from one event's `process_event`.
  - `TwilioClient` catches only `TwilioRestException`. A `requests` `ConnectionError`/timeout or any other exception propagates through `process_event` → `dispatch` → `run_cycle`. The dispatcher has no per-event `try`, so every later event in the sorted list is skipped too, and `check_pending_calls()` and cleanup are skipped.
  - Nothing re-dispatches these events later. `run_cycle` only dispatches events returned by this cycle's corroborator. The event sits in the DB with `alert_status='phone_call'` and no alert record.
  - Probe result: with a keyword-matching headline, urgency 9 and `send_sms` raising `RuntimeError`, `run_cycle` raised `RuntimeError` and left event `alert_status='sms'` with no delivery and no retry.
  - This is broader than the known §0 item "Unacknowledged calls are retried only when a new article joins the event". That item covers *retries* after a call; this one covers losing the *first* attempt.
- **Proposed refactor:**
  1. In `AlertDispatcher.dispatch`, wrap each `process_event` in `try/except Exception`, log at CRITICAL with the event id, and continue. Return a `DispatchReport` that lists the failed ids.
  2. In `TwilioClient.make_alert_call/send_sms/get_call_status`, also catch `requests.RequestException` (and `Exception` as the last guard) and return `None`, as the docstrings already promise.
  3. Move `validate()` inside the per-article `try`.
  4. Add an outbox sweep at cycle start: events whose `alert_status` is alertable, whose current `notification_revision` has no successful delivery record, and whose age is within a new config key (for example `alerts.dispatch_sweep_max_age_minutes`). Re-dispatch them. The age cap is required so it does not ring for days-old incidents (see §0 "Stale retry_pending calls").
- **Behavior-preserving:** no. Steps 1–3 only add resilience. Step 4 adds re-sends and needs owner sign-off together with the §0 retry-sweep decision.
- **Risk to the 9–10 path:** this is the path. Steps 1–3 are low risk. Step 4 can cause duplicate calls if its "already delivered" check is wrong.
- **Effort:** S for steps 1–3, M for step 4.
- **Tests that prove it:**
  - `test_dispatch_continues_after_one_event_raises`: two events, the first `process_event` raises, and the second is still processed.
  - `test_twilio_network_error_returns_none`: `calls.create` raises `requests.ConnectionError`, and the method returns `None`.
  - `test_validate_exception_marks_article_failed_and_cycle_continues`.
  - `test_event_committed_in_failed_cycle_is_dispatched_by_next_cycle` (step 4).

## F2 — 9–10 latency: dispatch waits for the whole FIFO batch, classified one by one

- **File:line:** `sentinel/scheduler.py:242` (`pending_classifications(retry_batch_size)`), `:251-273` (sequential classify), `:304-306` (dispatch after the loop); `sentinel/database.py:167-173` (`ORDER BY fetched_at ASC`); `config/config.yaml:475-477` (`timeout_seconds: 30`, `retry_batch_size: 100`).
- **Category:** orchestration / latency on the critical path.
- **Severity:** high.
- **What's wrong:**
  - A critical article's event is created mid-loop, but its call waits until up to 100 articles are classified sequentially. The worst case is 100 × 30 s.
  - The queue is oldest-first. After a provider outage or a budget pause (`project_spend_limit_exceeded`), a backlog of hundreds of articles builds up. A fresh 9–10 article then waits several full cycles behind stale ones.
  - All of this runs under `_cycle_lock`, so the fast lane (every 3 min) is blocked as well. APScheduler skips its runs ("maximum number of running instances").
- **Proposed refactor:**
  1. Dispatch inline. After each successful grouping, call `await self.dispatcher.dispatch(alertable(grouped))` at least for events at or above the phone threshold (or for all alertable events). Keep the end-of-cycle dispatch as a de-duplicated safety net; the dispatcher already re-reads the persisted row.
  2. Prioritise the queue. Store the keyword tier (`critical`/`high`) in `classification_queue` and order by `tier, attempts = 0 DESC, fetched_at DESC` so fresh critical work goes first. Alternatively, split each cycle's slots between new articles and backlog.
  3. Add a per-cycle classification time budget as a config key.
- **Behavior-preserving:** no (timing and ordering change; the grouping logic stays the same).
- **Risk to the 9–10 path:** it lowers risk. Inline dispatch interleaves call waits (`call_poll_timeout_seconds`) with classification. That is acceptable because the user is being called, but say so in the spec.
- **Effort:** M.
- **Tests that prove it:**
  - `test_critical_event_dispatched_before_rest_of_batch_classified` (spy records the order of dispatch versus classify calls).
  - `test_fresh_critical_article_dequeued_before_backlog`.

## F3 — No timeout around a cycle or around Twilio I/O; one hung await stops both lanes

- **File:line:** `sentinel/scheduler.py:224` (`async with self._cycle_lock` around everything); `sentinel/alerts/twilio_client.py:25` (`Client(account_sid, auth_token)` with no `http_client` timeout, and `requests` has no default timeout); `sentinel/alerts/state_machine.py:468`, `:602`, `:758` (`asyncio.to_thread` on those calls).
- **Category:** resilience.
- **Severity:** med-high.
- **What's wrong:**
  - Fetchers (30 s), the enricher (5 s) and OpenAI (`asyncio.timeout`) are bounded. Twilio is not. A half-open TCP connection to Twilio blocks the worker thread, the awaiting cycle, and therefore `_cycle_lock`, without limit.
  - Every later fast-lane and slow-lane run is skipped, `health.json` stops updating, and the watchdog that should notice is dead (§0 known).
  - Nothing in the process logs "cycle has held the lock for N minutes".
- **Proposed refactor:**
  1. Build the Twilio client with `TwilioHttpClient(timeout=config.alerts.twilio_timeout_seconds)`.
  2. Wrap the fetch and classify stages (not an in-progress call round) in `asyncio.timeout(config.scheduler.stage_timeout_seconds)`.
  3. In `_run_with_error_handling`, log a warning when the lock wait exceeds the lane interval.
- **Behavior-preserving:** no.
- **Risk to the 9–10 path:** low if the timeout never wraps `_execute_phone_call`. Cancelling inside a call round could leave an `initiated` record; `check_pending_calls` handles that state.
- **Effort:** S–M.
- **Tests that prove it:**
  - `test_hung_fetcher_stage_times_out_and_cycle_completes`.
  - `test_twilio_client_has_timeout`.

## F4 — Health reporting has blind spots: dead sources and a dead alert channel both look "healthy"

- **File:line:**
  - `sentinel/fetchers/rss.py:51-56` and `google_news.py:63-…` (`_fetch_*_safe` swallow per-source errors);
  - `sentinel/scheduler.py:191-196` (Telegram `start()` failure only logged), `:572-576` (`fetcher_status` = no exception from `fetch()`), `:578-594` (`is_healthy` ignores fetcher and alert-channel state), `:599-601` (non-atomic write, written even on failed cycles);
  - `sentinel/fetchers/telegram.py:71-78` (`fetch` returns an empty buffer when never started; `_running` is never read);
  - `sentinel.py:167-171` (the first cycle bypasses `_run_with_error_handling`).
- **Category:** observability.
- **Severity:** med (high in combination with the known §0 watchdog gap).
- **What's wrong:**
  - If every RSS feed returns 403, `fetcher_status.rss` stays `true`, because the RSS fetcher never raises.
  - If Telegram fails to log in at startup (an expired session, for example), it returns `[]` forever and is reported healthy. Telegram is the main fast-lane source.
  - `is_healthy` stays `true` while every Twilio call fails with 401. That 401 is the known, deliberate unfunded state, but health should still show "phone channel down".
  - `health.json` is rewritten even when the cycle fails, so the mtime-only watchdog (`deploy/scripts/check-health.sh:13`) sees a fresh file.
  - The write is not atomic: `open('w')` then `json.dump`, so a reader can see a truncated file.
  - The immediate first cycle after a restart never records success or failure. `docs/reference/cli.md` documents this as behaviour, but it is a defect.
- **Proposed refactor:**
  1. Let fetchers return a `FetchOutcome(articles, sources_ok, sources_failed)`. Health then shows per-source counts.
  2. Give `TelegramFetcher` an `is_connected` property and report it. Retry `start()` on later cycles.
  3. Add `alert_channels: {phone: last_success_at, last_error}` from `alert_records`.
  4. Write via a temp file plus `os.replace`.
  5. Run the first cycle through `scheduler._run_with_error_handling(fast_only=False)`.
- **Behavior-preserving:** alerting yes; the health output changes.
- **Risk to the 9–10 path:** none (reporting only). It shortens the time an outage goes unnoticed.
- **Effort:** M.
- **Tests that prove it:**
  - `test_rss_all_sources_failing_marks_fetcher_unhealthy`.
  - `test_telegram_start_failure_reported_in_health`.
  - `test_health_written_atomically`.
  - `test_initial_cycle_updates_health`.

## F5 — In-process health alerts go only through Twilio SMS (off and unfunded), with hardcoded thresholds and a blocking call

- **File:line:** `sentinel/scheduler.py:448-477` (thresholds 5/10, Polish text, synchronous `twilio_client.send_sms` on the event loop), `:550-554` (3 consecutive pipeline failures).
- **Category:** hardcoded values / dead channel / async hygiene.
- **Severity:** med.
- **What's wrong:**
  - The only in-process "Sentinel is broken" alert uses SMS. SMS is off by owner choice and the account is unfunded, so the alert reaches no one. This is the same failure as the known §0 watchdog item, but on a second code path that item does not mention.
  - The thresholds and message text are hardcoded, against the project rule.
  - The send is synchronous on the event loop and has no timeout (see F3).
  - It is not gated by `dry_run`; `cli.md` documents that.
- **Proposed refactor:**
  1. Add a `HealthNotifier` class that sends via `ExpoPushClient` (and SMS only if configured), wrapped in `asyncio.to_thread`.
  2. Move the thresholds to config keys: `scheduler.health.fetcher_warn_after`, `fetcher_alert_after`, `pipeline_alert_after`.
  3. Move the message templates to config or the alerts formatter.
- **Behavior-preserving:** no (channel change). Moving the thresholds alone is behavior-preserving if the defaults are 5/10/3.
- **Risk to the 9–10 path:** none.
- **Effort:** S–M.
- **Tests that prove it:**
  - `test_tenth_fetcher_failure_sends_health_push_once`.
  - `test_health_thresholds_read_from_config`.

## F6 — `run_cycle` is a 140-line function with two grouping paths interleaved

- **File:line:** `sentinel/scheduler.py:214-354`. The memory path is `:248-273`. The legacy path is split across `:274-285` and `:288-298`. Diagnostic branches are at `:304`, `:312`, `:325`.
- **Category:** structure / oversized function.
- **Severity:** med.
- **What's wrong:**
  - One method does lane selection, fetch, the dedup/enqueue transaction, two mutually exclusive classify-and-group strategies, dispatch, the pending-call poll, diagnostic capture, cleanup and stats.
  - The legacy path is split across two `if` blocks, with `relevant` re-bound in between (`:276`).
  - The fix points for F1 and F2 sit in the middle of this function, so changing it safely is hard.
- **Proposed refactor:**
  1. Split it into `_select_work(normalized) -> (unique, relevant)`, `_classify_group_memory(relevant) -> (results, events)`, `_classify_group_legacy(relevant) -> (results, events)` (chosen once via a strategy attribute), `_alert(events)`, and `_housekeeping()`.
  2. Collect intermediate data in a `CycleTrace` dataclass returned alongside `CycleResult`.
- **Behavior-preserving:** yes.
- **Risk to the 9–10 path:** low if the existing queue and memory tests stay green. Do this before F1 and F2.
- **Effort:** M.
- **Tests that prove it:** the existing `tests/test_classification_queue.py`, `test_incident_memory.py::test_same_batch_second_classification_receives_first_event_memory`, `test_integration.py` and `test_scheduler.py` stay green. Add a golden test comparing `CycleResult` before and after on a fixed fixture.

## F7 — The pipeline cannot be built with injected parts; tests hand-assemble it with `__new__`

- **File:line:** `sentinel/scheduler.py:150-168`; `tests/test_classification_queue.py:21-40`; `tests/test_incident_memory.py:317-334`.
- **Category:** testability / duplication.
- **Severity:** med.
- **What's wrong:**
  - `__init__` builds 15 collaborators directly, including network clients.
  - Two test modules bypass it with `SentinelPipeline.__new__` and set the attributes by hand. The two copies already differ: one sets `stats` and `fetchers`, the other a stub `stats`.
  - Any new attribute used by `run_cycle` breaks these tests at run time, or worse, gets stubbed differently in each copy.
- **Proposed refactor:**
  1. Add `SentinelPipeline(config, *, components: PipelineComponents | None = None)`, or a classmethod `from_config` plus a constructor that takes the components.
  2. Add one shared `tests/conftest.py` fixture `pipeline_factory(**overrides)`.
- **Behavior-preserving:** yes.
- **Risk to the 9–10 path:** none.
- **Effort:** S–M.
- **Tests that prove it:** both modules switch to the factory and still pass. Add `test_pipeline_factory_defaults_match_init`.

## F8 — Critical-path test gaps: integration tests exercise only the rollback path, and the Twilio-failure test is vacuous

- **File:line:** `tests/test_integration.py:59-84` (the fixture never enables incident memory; the default is `IncidentMemoryConfig.enabled = False`, `sentinel/config.py:173`), `:286-321` (`test_pipeline_survives_twilio_failure`); `tests/test_cli.py:82-130` (real network).
- **Category:** missing tests on the critical path.
- **Severity:** med-high.
- **What's wrong:**
  - Production runs incident memory. All nine integration tests run the legacy batch path, which is the rollback path.
  - Every test of the memory path in `run_cycle` replaces `dispatcher` and `state_machine` with `AsyncMock`. So no test drives memory classify → group → real dispatcher → real state machine → fake Twilio for an urgency-10 article.
  - `test_pipeline_survives_twilio_failure` never touches Twilio. Its headline "Russia launches invasion of Poland" fails the test keyword filter, so the probe showed `articles_relevant=0` and `make_alert_call` called 0 times. With a matching headline the test would fail, because the exception propagates (F1). Its comment "Twilio errors are caught in the state_machine/twilio_client layer" is false for non-`TwilioRestException` errors.
  - `test_custom_config_path` makes real HTTP requests to example.com, GDELT and Google News (28 s, and it can flake offline).
- **Proposed refactor:**
  1. Parametrise the integration fixture over `incident_memory.enabled ∈ {True, False}`, with a fake classifier that implements `classify(article, incident_context=…)`.
  2. Fix the Twilio test to use a keyword-matching headline and assert `make_alert_call.call_count >= 1`. It is expected to fail until F1 lands.
  3. Add `test_live_path_urgency10_places_call_end_to_end`.
  4. Disable sources in `test_custom_config_path`, or mark it `integration`.
- **Behavior-preserving:** yes (tests only).
- **Risk to the 9–10 path:** none. It adds a guard.
- **Effort:** M.
- **Tests that prove it:** the tests themselves. Write them first, so F1 and F2 have red-to-green proof.

## F9 — Test and dev modes write into the live DB and can interfere with the 9–10 path

- **File:line:** `sentinel.py:427-462` (`--test-alert` inserts an urgency-10 PL `missile_strike` event); `sentinel/classification/incident_memory.py:64-66` ("always retain the newest incident"); `sentinel/database.py:299-314` (`get_memory_events`, no filter); `sentinel.py:254-263` plus `scheduler.py:236-242`, `:288-292` (`--once --dry-run` and `--diagnostic` consume the queue and create `dry_run` events); `scheduler.py:168` (the lock is per-process only).
- **Category:** test/diagnostic leakage into production.
- **Severity:** med.
- **What's wrong:**
  - Run on the server (the documented use of `--test-alert`), the synthetic event becomes an incident-memory candidate for `lookback_hours` (168 h) and is always included while it is the newest event.
  - If the owner acknowledged it by SMS code, a real critical article that the model judges a `duplicate`/`update` of it merges silently, with no call. This rides on the §0 sign-off item "acknowledged-event guard is gone".
  - A `--once --dry-run` or `--diagnostic` run against the live DB runs concurrently with the daemon, with no inter-process lock. It dequeues articles, marks them complete and groups them into `alert_status='dry_run'` events, so the daemon never alerts those articles.
- **Proposed refactor:**
  1. Mark synthetic records (`source_type='test'` is already set on the article; add `Event.is_synthetic` or reuse `aggressor='TEST'`) and exclude them in `get_memory_events`.
  2. Take an advisory `fcntl.flock` on `<db>.lock` in the daemon. Make `--once`, `--dry-run` and `--diagnostic` refuse to run while it is held, unless `--allow-shared-db` is given. Or default them to a temporary copy of the DB.
- **Behavior-preserving:** no.
- **Risk to the 9–10 path:** it removes a latent silent-merge route. Make sure the filter cannot exclude real events (filter on an explicit flag, not on text).
- **Effort:** S (filter), M (lock).
- **Tests that prove it:**
  - `test_test_alert_event_not_in_memory_candidates`.
  - `test_dry_run_refuses_when_daemon_lock_held`.

## F10 — `strip_html` drops text at an unterminated `&` and can wipe a whole summary (latent bug)

- **File:line:** `sentinel/utils/html.py:20-26` (no `stripper.close()`); call sites `sentinel/fetchers/rss.py:148`, `sentinel/fetchers/google_news.py:158`, `sentinel/processing/enricher.py:227`.
- **Category:** latent bug.
- **Severity:** med.
- **What's wrong:** `HTMLParser` with `convert_charrefs=True` holds back text after a possible entity start until `close()`. Probe output:
  - `'Rosyjskie drony nad Polską. Więcej &raquo'` → `''`
  - `'Russian missile hit Rzeszow &hellip'` → `''`
  - `'x <b>y</b> tail &'` → `'x y'`

  RSS descriptions are often cut off mid-entity. A critical keyword that exists only in the summary is then lost before the keyword filter, so the article is never classified. Feedparser often decodes entities first, so the production frequency is unmeasured. Worth a DB check by the owner or another auditor.
- **Proposed refactor:** `stripper.feed(text); stripper.close(); return stripper.get_text()`. Drop the redundant `self.reset()` in `__init__`.
- **Behavior-preserving:** no (more text kept).
- **Risk to the 9–10 path:** it lowers risk. More text can only add keyword matches.
- **Effort:** S.
- **Test that proves it:** `test_strip_html_keeps_text_ending_in_unterminated_entity` (the three cases above).

## F11 — Lane membership, fast-lane jitter and the health path are hardcoded or duplicated; one constant is dead

- **File:line:** `sentinel/scheduler.py:417` (`_FAST_LANE_FETCHERS`, never read), `:419`, `:430-436` (`"gdelt"` set, `fetcher.name == "rss"`, `max_priority=1`), `:504` (`min(jitter, 10)`), `:596`; `sentinel.py:92`, `:140-143` (the health and diagnostic path logic, three copies).
- **Category:** hardcoded values / duplication / dead code.
- **Severity:** low.
- **What's wrong:**
  - Which sources run in the fast lane is code, not config, and is matched on name strings.
  - The fast-lane jitter cap of 10 s is invisible in `config.yaml`.
  - The path fallback `"data"` is repeated three times.
- **Proposed refactor:**
  1. Add config keys `scheduler.fast_lane: {fetchers: [telegram, google_news, rss], rss_max_priority: 1, jitter_seconds: 10}` and `scheduler.slow_only_fetchers: [gdelt]`, with defaults equal to today's values.
  2. Add a helper `sentinel/paths.py: runtime_file(config, name)`.
  3. Delete `_FAST_LANE_FETCHERS`.
- **Behavior-preserving:** yes (same defaults).
- **Risk to the 9–10 path:** low. A config typo could drop Telegram from the fast lane, so validate the names against the registered fetchers.
- **Effort:** S.
- **Test that proves it:** `test_fast_lane_fetchers_from_config` (assert which fetchers `_fetch_all(fast_only=True)` calls).

## F12 — The fetcher interface has drifted from `BaseFetcher`

- **File:line:** `sentinel/fetchers/base.py:20-26` (`fetch()` takes no arguments; `is_enabled` raises `NotImplementedError`); `rss.py:30` (`fetch(*, max_priority=None)`); `scheduler.py:191-205` (`hasattr(fetcher, "start"/"stop")`).
- **Category:** weak typing / unclear boundary.
- **Severity:** low.
- **What's wrong:** the scheduler relies on duck typing and name checks. A new fetcher that needs `start()` but misspells it is silently never started.
- **Proposed refactor:** give `BaseFetcher` async no-op `start()`/`stop()` and `fetch(self, *, fast_lane: bool = False)`, and let each fetcher decide its lane behaviour. Then remove the `hasattr` checks and the name switch.
- **Behavior-preserving:** yes.
- **Risk to the 9–10 path:** low.
- **Effort:** S.
- **Test that proves it:** the existing fetcher tests, plus `test_all_fetchers_implement_lane_signature`.

## F13 — Cycle metrics are mislabelled ("events_created", "alerts_sent")

- **File:line:** `sentinel/scheduler.py:335-336`; consumers `:587-588` (`health.json`), `:110-113` (daily summary), `sentinel.py:110-111`.
- **Category:** misleading observability.
- **Severity:** low.
- **What's wrong:**
  - `events_created` counts events *touched* (created or updated).
  - `alerts_sent` counts events whose status is not `pending`. That includes `dry_run`, acknowledged, suppressed and failed deliveries.
  - `health.json` `last_cycle_alerts_sent` therefore says alerts were sent when Twilio returned 401 on every attempt.
- **Proposed refactor:** let the dispatcher return a `DispatchReport` (attempted and delivered per channel). Rename the fields `events_touched` and `alerts_attempted`, and add `alerts_delivered`. Fold in the known §6.1 #12 fix.
- **Behavior-preserving:** no (the reporting changes; alerting does not).
- **Risk to the 9–10 path:** none.
- **Effort:** S.
- **Test that proves it:** `test_alerts_delivered_zero_when_twilio_fails`.

## F14 — CLI sprawl: nine mode flags in an if-chain with silent precedence; dev tooling calls private APIs

- **File:line:** `sentinel.py:21-87`, `:229-263` (mode chain), `:302-486` (about 190 lines of test and eval tooling in the production entry point), `:444-448` (identity `alert_status_map`, dead), `:473-484` (calls the private `_execute_phone_call`, `_execute_sms`, `_maybe_send_push`), `:411-416` (docstring says "through Twilio" and "source_count=2 (bypassing corroboration)"; push is not Twilio).
- **Category:** structure / CLI.
- **Severity:** low.
- **What's wrong:**
  - Mutually exclusive modes are not declared. `--once --health` prints health only, and `--diagnostic --once` runs only the diagnostic, with no error.
  - Modes mutate `config` in place (`config.testing.dry_run`).
  - Private state-machine methods are called from outside.
  - The known §6.1 #4 and #9 bugs live here.
- **Proposed refactor:**
  1. Put the mode flags in an argparse mutually-exclusive group. Rejecting conflicting combinations is a small, visible behavior change.
  2. Move `_run_test_*` and `_run_eval` to `sentinel/cli/devtools.py`.
  3. Add a public `AlertStateMachine.send_test(channel, event)`.
  4. Pass the dry-run override into the pipeline and dispatcher constructors instead of mutating config.
  5. Fix §6.1 #4 and #9 in the same change.
- **Behavior-preserving:** yes except for item 1.
- **Risk to the 9–10 path:** none (the test-alert path only).
- **Effort:** M.
- **Tests that prove it:**
  - `test_conflicting_modes_rejected`.
  - `test_test_alert_uses_public_api` (the existing `tests/test_cli.py` style).

## F15 — No SIGTERM handling: systemd stop skips the graceful shutdown

- **File:line:** `sentinel.py:175-184` (`while True: await asyncio.sleep(1)`; only `CancelledError` and `KeyboardInterrupt` are handled); `sentinel/scheduler.py:210-212` (`enricher.aclose()` not guarded, so `db.close()` is skipped if it raises).
- **Category:** lifecycle.
- **Severity:** low-med.
- **What's wrong:**
  - Python's default SIGTERM action ends the process without running `finally`. On every deploy or restart, `scheduler.stop()`, `pipeline.shutdown()`, the Telegram disconnect, the classifier `aclose()` and `db.close()` are skipped.
  - If the process is killed inside a call round, the `initiated` record is recovered by `check_pending_calls`, so this is not an alert loss. But the shutdown path is effectively untested in production.
- **Proposed refactor:** in `run_continuous`, create `stop = asyncio.Event()`, call `loop.add_signal_handler(SIGTERM, stop.set)` (and the same for SIGINT), `await stop.wait()`, then run the existing `finally`. Guard each shutdown step separately.
- **Behavior-preserving:** no (it adds graceful stop).
- **Risk to the 9–10 path:** low. A stop that lands mid-call should wait for the call round; add a bounded wait.
- **Effort:** S.
- **Test that proves it:** `test_sigterm_runs_shutdown` (subprocess, send SIGTERM, assert "Project Sentinel stopped" and exit 0).

## F16 — Logging misses APScheduler and duplicates every line

- **File:line:** `sentinel/logging_setup.py:16-47`.
- **Category:** observability.
- **Severity:** low.
- **What's wrong:**
  - Only the `sentinel` logger gets handlers. APScheduler's "Execution of job … skipped: maximum number of running instances reached" warnings go to Python's last-resort stderr handler. They appear in the journal only and never in `/var/log/sentinel`. Those warnings are the evidence for fast-lane starvation (F2).
  - Under systemd, the file handler plus the stdout handler duplicate every line.
  - The idempotency guard means a second call cannot change the level.
- **Proposed refactor:** also attach the handlers to the `apscheduler` logger (at WARNING). Add `logging.stdout: bool` (default true locally, false in the unit) as a config key.
- **Behavior-preserving:** yes (more lines logged).
- **Risk to the 9–10 path:** none.
- **Effort:** S.
- **Test that proves it:** `test_apscheduler_warnings_reach_file_handler`.

## F17 — Poison articles: no max-attempts cap, and the legacy grouping error is not isolated

- **File:line:** `sentinel/database.py:175-180` (`classification_failed` has no cap), `:186-190` (`degraded` = any `failed > 0`); `sentinel/scheduler.py:288-292` (legacy `process_classifications` not in a `try`).
- **Category:** error handling.
- **Severity:** med.
- **What's wrong:**
  - An article that always fails (malformed text, a provider rejection) is retried every `retry_delay_seconds` forever. Each retry is a paid call.
  - Such an article keeps `classification_status.degraded = true` permanently, so `is_healthy` is false for good. That trains the owner to ignore health and hides real outages.
  - In the legacy path, a grouping exception aborts the cycle without marking the articles failed. They are re-classified (paid) and fail again every cycle.
- **Proposed refactor:**
  1. Add `classification.max_attempts` (config) and a terminal `dead_letter` state that is logged at ERROR and counted separately in health.
  2. Wrap the legacy grouping in `try/except` and mark the articles failed with `grouping_failed`, as the memory path already does.
- **Behavior-preserving:** no.
- **Risk to the 9–10 path:** a dead-lettered article is never alerted. Set the cap high (for example 24 attempts ≈ 2 h) and send a health push when an article reaches it.
- **Effort:** S–M.
- **Tests that prove it:**
  - `test_article_dead_lettered_after_max_attempts`.
  - `test_legacy_grouping_failure_marks_articles_failed`.

## F18 — The diagnostic report is wired into the production cycle and mislabels queue states

- **File:line:** `sentinel/scheduler.py:26` (imports the diagnostic dataclasses), `:238` (the `diagnostic` flag threaded into the deduplicator), `:356-414`; `sentinel/diagnostic.py:107-110` ("API error" label); `sentinel/processing/deduplicator.py:68-88`.
- **Category:** unclear boundary / test-mode leakage.
- **Severity:** low.
- **What's wrong:**
  - The production pipeline imports the report module, and a report flag runs through dedup.
  - In memory mode, `relevant` comes from the durable queue. The report rows are built only from this cycle's `normalized` articles, so backlog articles that were classified this cycle are missing from the table while the totals count them.
  - An article that passed the keywords but was not dequeued this cycle (the 100 limit, or backoff) is shown as "API error".
- **Proposed refactor:** always build the cheap `CycleTrace` (F6). `diagnostic.py` renders it. The deduplicator always records its reasons in a dict that is reset per call. Label the queue states as "queued" or "backoff" instead of "API error".
- **Behavior-preserving:** yes except the report labels.
- **Risk to the 9–10 path:** none.
- **Effort:** S (after F6).
- **Test that proves it:** `test_diagnostic_includes_backlog_articles_and_queue_labels`.

## Notes (no separate finding)
- `run.sh` is fine. It uses `set -euo pipefail` and passes all arguments through. It silently creates a venv on a missing `.venv`; on the server the unit uses `.venv/bin/python` directly, so this is local-only.
- `sentinel/utils/datetime.py` and its tests are small and correct, including the DST cases.
- `cleanup_old_records` runs every cycle (every 3 min). It is harmless but could move to an hourly job; fold it into F6's `_housekeeping`.
- `docs/reference/cli.md` matches the code. Update it after F4 (first cycle writes health), F14 (exclusive modes) and F15.

---

## Proposed phase grouping (this area)

| Phase | Content | Behavior change? | Gate |
|---|---|---|---|
| P0 — tests first | F8 (memory-path integration fixture, fix the vacuous Twilio test so it goes red, end-to-end urgency-10 test, offline CLI test) | no | New tests fail for the right reason (F1) and the rest pass |
| P1 — safety fixes, small | F1 steps 1–3 (per-event dispatch isolation, Twilio network-error catch, `validate` inside `try`), F10 (`strip_html` close), F17 step 2 (legacy grouping isolation) | yes, but strictly safer | P0 red tests green; full `pytest tests/` green |
| P2 — structure (behavior-preserving) | F6 (split `run_cycle` + `CycleTrace`), F7 (injectable pipeline + shared factory), F12 (fetcher interface), F11 (lane/jitter/path config with today's defaults), F18 (diagnostic renders the trace) | no | Golden `CycleResult` parity test; all existing tests green |
| P3 — latency and timeouts (owner sign-off) | F2 (inline critical dispatch + queue priority), F3 (Twilio timeout, stage timeouts), F1 step 4 (outbox sweep with max age, together with the §0 retry-sweep and stale-retry decisions), F17 step 1 (max attempts) | yes | Ordering and timeout tests; owner approves the sweep age and max attempts |
| P4 — observability | F4 (per-source health, Telegram connected, alert-channel status, atomic write, first-cycle health), F5 (health push notifier, config thresholds), F13 (`DispatchReport` + §6.1 #12), F15 (SIGTERM), F16 (logging) | reporting only, plus graceful stop | Health JSON schema test; SIGTERM subprocess test |
| P5 — CLI and dev-mode isolation | F9 (exclude synthetic events from memory, DB lock for dry-run/diagnostic), F14 (exclusive modes, `devtools` module, public `send_test`, §6.1 #4 and #9) | yes (small) | CLI tests; `docs/reference/cli.md` updated |

Order rationale: P0 gives P1 a red-to-green proof. P2 must come before P3 because the F2 and F1-step-4 changes land inside `run_cycle`. P3 touches the call path and depends on open §0 owner decisions, so it is gated on sign-off.
