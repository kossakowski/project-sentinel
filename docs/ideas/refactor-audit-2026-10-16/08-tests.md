# 08 — Python test suite and build gates (read-only audit, 2026-10-16)

Auditor scope: `tests/` (49 files, 17,094 lines), pytest/ruff/pre-commit config, coverage, safety net for a big refactor.
Repo state: master @ 835ed8e, working tree clean before and after the audit (verified with `git status`).

## 1. Test run (fresh, this session)

Command: `.venv/bin/pytest tests/ -q -p no:cacheprovider --durations=25`

Exact summary line: **`644 passed in 387.28s (0:06:27)`** — exit 0, 0 failures, 0 errors, 0 warnings printed.

Slowest tests:

| Time | Test | Cause |
|---|---|---|
| 39.60s | `tests/test_cli.py::test_custom_config_path` | subprocess `sentinel.py --once`, **real network fetches** (see T-01) |
| 28.81s | `tests/test_cli.py::test_dry_run_flag` | subprocess; ~11s standalone (heavy imports: lingua, trafilatura, telethon) |
| 13.51s | `tests/test_direct_openai.py::test_direct_request_and_persistence` | first test to build the lingua detector (lru_cache per process) |
| 13.07s | `tests/test_direct_openai.py::test_no_send_runner_uses_real_direct_classifier` | same |
| 6.72s | `tests/test_eval_suite_report.py::test_items_never_attempted_fail_coverage` | eval report build |
| 4.50s | `tests/test_eval_suite_report.py::test_decision_rule_coverage_false_call_margin_and_pool` | |
| 3.90s | `tests/test_fulltext.py::test_extract_text_caps_length_and_rejects_empty_pages` | trafilatura |
| 3.59s | `tests/test_cli.py::test_help_exits_cleanly` | subprocess import cost |
| 2.95s | `tests/test_cli.py::test_invalid_config_exits` | subprocess import cost |
| 2.11s | `tests/test_dashboard_api.py::test_run_dashboard_sh_help_smoke` | shell subprocess |

The other 15 of the top 25 are 1.4–3.6s each (mostly eval-suite report and direct_openai tests).

## 2. Coverage (pytest-cov 7.0 is installed; nothing was installed)

Command: `COVERAGE_FILE=<scratchpad>/.coverage .venv/bin/pytest tests/ -q -p no:cacheprovider --cov=sentinel --cov-branch --cov-report=term-missing:skip-covered --deselect tests/test_cli.py::test_custom_config_path`
Result: `643 passed, 1 deselected in 737.65s (0:12:17)`. **TOTAL 76% (statements+branches; 5670 stmts, 1179 missed).** 14 files at 100% (including `alerts/dispatcher.py` and `alerts/push_client.py`).

Life-safety path modules:

| Module | Cover | Notable uncovered lines |
|---|---|---|
| `sentinel/alerts/state_machine.py` | 87% | **706-715** (SMS code matched → ack), **725-741** (confirmation-SMS delivery status), **589-590, 616-617, 635-636** (ack inside the call loop), **604-605** (Twilio call failed to initiate → `continue`), **623-627** (resend confirmation SMS on failed delivery), 749-763 (call-poll branches) |
| `sentinel/alerts/twilio_client.py` | 94% | 123-129 |
| `sentinel/classification/corroborator.py` | 91% | 58-70, 445-458 |
| `sentinel/classification/incident_memory.py` | 96% | 133-134 |
| `sentinel/classification/classifier.py` | 85% | 391-403, 284-285 |
| `sentinel/classification/openai_provider.py` | 96% | |
| `sentinel/scheduler.py` | 78% | 172-187 (`_init_fetchers`), 366-405 (diagnostic), **453-460 / 473-477** (10-failure system SMS and its error path), 602-611 |
| `sentinel/database.py` | 96% | |
| `sentinel/config.py` | 91% | 380-392 (load_config error paths) |

Weak elsewhere: `diagnostic.py` 17%, `logging_setup.py` 21%, `fetchers/telegram.py` 53%, `processing/enricher.py` 64%, `processing/keyword_filter.py` 72% (132-163), `processing/__init__.py` 53%; eval tooling: `eval/incident_memory.py` 0%, `eval/export_candidates.py` 0%, `eval/suite/fulltext_snapshot.py` 0%, `eval/suite/runner.py` 51%, `eval/suite/sample.py` 52%, `eval/rescore_dimensions.py` 50%.

## 3. Build-gate tooling found

- `pyproject.toml` has `[tool.pytest.ini_options]` (testpaths, one `integration` marker that no test uses) and `[tool.ruff]` (E, W, F, I, UP, B, SIM). No `asyncio_mode`, no `filterwarnings`, no `--strict-markers`, no coverage config.
- `.pre-commit-config.yaml`: ruff `--fix` + ruff-format (rev v0.15.14), installed as `.git/hooks/pre-commit`. It runs only on staged files.
- **Today `ruff check sentinel tests` reports 55 errors** (37 UP017, 9 F401, 6 I001, 1 F541, 1 SIM108, 1 SIM300; 54 autofixable). `ruff format --check` would reformat 9 files.
- No mypy/pyright (not installed, no config). No CI (known). No `setup.cfg`, `tox.ini`, `Makefile`.
- The `/deploy` skill gate is `.venv/bin/pytest tests/ -v` (`.claude/skills/deploy/SKILL.md:78`). It runs the network test from T-01 and no lint.
- Dev dependencies (pytest, pytest-cov, pytest-asyncio, pytest-mock) are in the runtime `requirements.txt`, unpinned with `>=`, so they install on the production server.

## 4. Findings

### T-01 — A "unit" test does real network fetches with the real `.env` loaded
- File: `tests/test_cli.py:83-125` (`test_custom_config_path`); root cause `sentinel/config.py:375-379` (`load_config` always calls `load_dotenv()`).
- Category: hits network / real APIs, flaky. Severity: **high**.
- What's wrong: the config leaves RSS (`https://example.com/rss`), GDELT and Google News enabled (pydantic defaults `enabled: True`, `sentinel/config.py:22,28,39`). The run is not `--dry-run`. The subprocess runs with cwd = repo root, so `load_dotenv()` loads the real `.env` (it holds the OpenAI, Twilio and Expo credentials), and `classification: {}` falls back to the Anthropic provider. If Google News returned an article that matched "military attack", the test could spend money on a paid classifier call. An urgency-9+ result would then place a call with the real Twilio credentials to the literal `+48123456789` in the test config, which may be a real stranger's number (it fails today only because the Twilio account is suspended). It is also the slowest test (39.6s) and depends on outside sites being up. `docs/how-to/testing.md:85` claims "the whole suite runs offline with mocks", which is false.
- Refactor: disable every source in that config, or add `--dry-run`. Pass `env` without `.env` (`env={"PATH": ..., "ALERT_PHONE_NUMBER": ...}`, cwd=tmp_path with an explicit `sentinel.py` path). Make `load_dotenv()` opt-in (call it in `sentinel.py` `main()`, not inside `load_config`). Add an autouse conftest guard that blocks outbound sockets (monkeypatch `socket.socket.connect` to refuse non-loopback; no new package needed). Mark subprocess smoke tests `@pytest.mark.slow`.
- Effort: S.

### T-02 — No end-to-end test asserts that a 9–10 article actually produces call + SMS + push
- Files: `tests/test_integration.py:379-433` (`test_corroboration_across_cycles`, urgency 9, two cycles), `:287-326` (`test_pipeline_survives_twilio_failure`, urgency 9), `:96-140` (`test_full_pipeline_with_fixtures`, urgency 8).
- Category: missing e2e / safety net. Severity: **high**.
- What's wrong: the "end-to-end" tests feed urgency-9 articles through `SentinelPipeline.run_cycle()` but assert only `articles_fetched == 1`. A pipeline that silently dropped every critical event would pass. `make_alert_call` call-count assertions exist only in `test_state_machine.py` (9) and `test_incident_alerts.py` (2), which start from a hand-built `Event`. None go from article to call. `ExpoPushClient` is never patched or asserted in the pipeline tests.
- Refactor: add the golden characterization test from section 5. As a minimum quick fix, in these tests assert `mock_twilio.make_alert_call.call_count == <max_call_retries>`, assert one confirmation `send_sms`, assert the event `alert_status`, and assert a push was sent.
- Effort: M.

### T-03 — The suite tests a config that is not production (fixture drift)
- File: `tests/conftest.py:12-129` (`sample_config_dict`) versus `config/config.yaml`.
- Category: fixture realism / refactor blocker. Severity: **high**.
- What's wrong: the shared fixture differs from production on exactly the parameters that decide whether a call is placed:

  | Key | Fixture | Production |
  |---|---|---|
  | critical `corroboration_required` | 2 | 1 |
  | `classification.corroboration_required` | 2 | 1 |
  | `corroboration_window_minutes` | 60 | 360 |
  | summary metric / threshold | token_sort_ratio / 40 | token_set_ratio / 50 |
  | `max_call_retries` | 5 | 1 |
  | provider / model | anthropic haiku | openai gpt-5.6-luna |
  | `incident_memory.enabled` | false (code default) | true |
  | medium / low tiers, `channel: push` | missing | present |
  | push block | missing | enabled |

  As a result, `test_integration.py` and most `test_state_machine.py` tests exercise the legacy fuzzy rollback path, a 2-source rule and 5-call rounds (`test_state_machine.py:125, 279, 391` hard-code `== 5`). The live single-source, incident-memory, push-tier path is covered only piecemeal (`test_incident_memory.py`, `test_incident_alerts.py`, `direct_config`). The only checks against the real YAML are string assertions on its shape (`test_config.py:349-384`, `test_direct_openai.py:191-205`).
- Refactor: add a `prod_config` fixture that loads the real `config/config.yaml` through `load_config`. Set the placeholder env vars with `monkeypatch.setenv` and redirect `database.path`, `logging.file` and `budget.ledger_path` to `tmp_path`. Run the alert-routing tests parametrized over `[sample_config, prod_config]`. Replace literal `== 5` with `config.alerts.acknowledgment.max_call_retries`.
- Effort: M.

### T-04 — The positive SMS-acknowledgement path and "call failed to initiate" are never executed
- File: `sentinel/alerts/state_machine.py:589-590, 604-605, 616-617, 623-627, 635-636, 706-715, 725-741` (coverage-confirmed misses). Mocks are at `tests/test_state_machine.py:103, 1644` and `tests/test_incident_alerts.py:49`, which always return `messages.list.return_value = []`.
- Category: missing tests on life-safety logic. Severity: **high**.
- What's wrong: no test has the owner reply with the right code. So nothing checks that a correct reply stops further calls and acknowledges the event, or that a wrong code does not. `record is None` (Twilio failed to initiate) is the exact production state today (Twilio 401 since 2026-08-23), and it has no test. The resend-on-undelivered confirmation SMS and the delivery-status branches are not tested either. The random 6-digit code (`state_machine.py:667`, `random.randint`) cannot be controlled from tests without patching `random`.
- Refactor: inject a code generator (`AlertStateMachine(..., code_factory=...)`), or read `sm._confirmation_code` through a public accessor. Add tests for: correct reply before the first call (0 calls), after call 1 (1 call, acknowledged), a wrong code (round exhausted, `retry_pending`), `make_alert_call` returning None for every attempt (no crash, `retry_pending`, push still sent), and confirmation delivery `failed` (SMS resent once).
- Effort: S–M.

### T-05 — Tests and production code reach through `TwilioClient` into the raw Twilio SDK
- File: `sentinel/alerts/state_machine.py:698-703, 727` (`self.twilio.client.messages.list(...)`, `self.twilio.client.messages(sid).fetch()`). Tests mock that SDK shape at `tests/test_state_machine.py:103, 715-773, 1644` and `tests/test_incident_alerts.py:49`.
- Category: coupling to internals / leaky abstraction. Severity: med.
- What's wrong: the acknowledgement logic depends on the SDK object graph, and the tests encode it (`twilio.client.messages.return_value.fetch`). Any refactor of `TwilioClient` (or a provider swap) breaks tests and makes it easy to miss the ack path. All Twilio mocks are bare `MagicMock()` without `spec=`; only `test_dispatcher.py` uses `spec=AlertStateMachine`. A renamed method would therefore still pass.
- Refactor: add `TwilioClient.list_inbound_sms(from_, since, limit)` and `TwilioClient.get_message_status(sid)`. Have the state machine call only those. Replace the two hand-rolled mocks with one `FakeTwilio` class in conftest, built with `create_autospec(TwilioClient, instance=True)` plus recording side effects. Do the same for `FakePush` with `ExpoPushClient`.
- Effort: M.

### T-06 — `SentinelPipeline.__new__` hand-assembly in tests (blocks scheduler refactor)
- Files: `tests/test_classification_queue.py:21-41` (`build_pipeline`), `tests/test_incident_memory.py:316-334`.
- Category: coupling to private internals. Severity: med.
- What's wrong: the tests bypass `__init__` and set about 18 attributes by hand, including private ones (`_cycle_lock`, `_fetch_all`, `diagnostic_data`). They replace `dispatcher` and `state_machine` with `SimpleNamespace(AsyncMock)`, so the live memory-mode path is never connected to real dispatch. Every scheduler refactor (renaming a stage, adding a dependency) breaks these tests or silently skips new stages. Elsewhere, the triple patch `_init_fetchers` + `sentinel.scheduler.Classifier` + `sentinel.scheduler.TwilioClient` is copy-pasted 13 times (`test_integration.py` ×9, `test_scheduler.py` ×3, `test_cli_bridges.py` ×1).
- Refactor: give `SentinelPipeline.__init__` optional injected collaborators (`fetchers=`, `classifier=`, `twilio_client=`, `push_client=`, `clock=`), with production defaults unchanged. Add one conftest fixture `make_pipeline(config, **overrides)` and delete both `__new__` builders and the 13 patch stacks.
- Effort: M.

### T-07 — Duplicated factories and fixtures across files; test-to-test imports
- Files: `_make_article` in 7 files (`test_normalizer.py:9`, `test_classifier.py:16`, `test_keyword_filter.py:9`, `test_integration.py:19`, `test_corroborator.py:9`, `test_enricher.py:13`, `test_deduplicator.py:9`) plus `_article` variants in `test_incident_storage.py:10` and `test_incident_memory.py:36`. `_make_event` in `test_state_machine.py:40`, `test_dispatcher.py:27`, `test_incident_storage.py:42`, `test_incident_alerts.py:15`. `_make_classification` in `test_integration.py:40`, `test_corroborator.py:25`, `test_incident_storage.py:24`, and `result_for` in `test_classification_queue.py:44`. Twilio mock twice in one file (`test_state_machine.py:87-105` `mock_twilio` and `:1628-1646` `_fresh_twilio`, documented as "identical"). Dashboard fixtures `sentinel_db_path`, `fts_db_path`, `app` and `client` are repeated in `test_dashboard_api.py:30-56`, `test_dashboard_annotations.py:26-85` and `test_dashboard_db.py:336-365`. `test_dashboard_api.py:23` and `test_dashboard_annotations.py` import `_build_sentinel_db` from another test module (`tests/__init__.py` makes this possible).
- Category: duplication. Severity: med.
- What's wrong: when the `Article`, `Event` or `ClassificationResult` model changes (a likely part of any refactor), about 15 factories need the same edit. Their defaults differ too (urgency 7 vs 8 vs 10; source_count 1 vs 2), so the tests are hard to compare.
- Refactor: create `tests/factories.py` with `make_article(**kw)`, `make_classification(article, **kw)`, `make_event(**kw)`, `make_alert_record(**kw)`, `FakeTwilio` and `FakePush`, and expose them as conftest fixtures. Move the dashboard fixtures and `_build_sentinel_db` into `tests/dashboard/conftest.py` (move the three dashboard test files into `tests/dashboard/`).
- Effort: M (mechanical; sonnet-suitable).

### T-08 — The dashboard test DB uses a hand-written schema copy
- File: `tests/test_dashboard_db.py:25` (`_SCHEMA = """…"""`) and `:141` (`_build_sentinel_db`, raw `executescript`).
- Category: drift. Severity: med.
- What's wrong: the dashboard tests run against a frozen copy of the schema, not the schema `sentinel/database.py` creates. That is why the TODO 6.2 lag (`classification_queue` ignored, `push` alert type missing) is invisible to tests.
- Refactor: build the fixture DB with `sentinel.database.Database(path)` (real migrations), then insert rows. Add one test that diffs `PRAGMA table_info` between the two schemas if the dashboard keeps its own expectations.
- Effort: S.

### T-09 — Production code and tests use the private `_determine_action`
- Files: `sentinel/alerts/dispatcher.py:54` (production calls `self.state_machine._determine_action`), `tests/test_dispatcher.py:54-60, 94, 142`, and 10 call sites in `tests/test_state_machine.py:912-999`. In total `test_state_machine.py` touches the private formatters 73 times (`_build_push_data`, `_format_push`, `_format_sms_message`, `_format_update_sms`, imported at `:27-30`) plus `sm._maybe_send_push` ×4.
- Category: coupling to internals. Severity: med.
- What's wrong: the routing decision (call vs push vs log) is the core life-safety rule. It is private and also part of the dispatcher's dry-run contract, so any rename or split of the state machine breaks about 85 references at once.
- Refactor: promote it to a public `decide_action(event) -> Action` (or a pure `routing.py` module: `decide_action(event, alerts_config)`), and move message formatting to a public `alerts/messages.py`. Tests then target the public pure functions; a refactor of `AlertStateMachine` leaves them intact.
- Effort: S–M.

### T-10 — No time control; 136 `datetime.now(UTC)` calls in tests, and window logic is relative to the wall clock
- Files: across `tests/` (136 occurrences). Production reads the wall clock at `state_machine.py:567, 577`, in the corroborator windows and in the incident-memory `lookback_hours`.
- Category: flaky pattern. Severity: low–med.
- What's wrong: there is no freezegun-like seam and no injected clock. Retry-interval, corroboration-window and memory-age tests build "now minus X" timestamps and race the real clock (safe today because the margins are wide). A UTC-midnight run could flip the daily-budget logic (`classifier._daily_date` is reset by hand in `test_incident_memory.py:411-413`). Each test patches `asyncio.sleep` by hand (13 decorators in `test_state_machine.py`, 1 in `test_incident_alerts.py`), so a new test that forgets the patch sleeps for real (`call_poll_timeout_seconds`).
- Refactor: add a `Clock` protocol (`now()`, `async sleep()`) injected into `AlertStateMachine`, `Corroborator`, `IncidentMemory` and the scheduler, with a `FakeClock` fixture. Add an autouse fixture that patches `sentinel.alerts.state_machine.asyncio.sleep` (opt-out marker for the one test that checks it is awaited).
- Effort: M.

### T-11 — Non-test scripts live in test namespaces
- Files: `tests/test_vagueness_check.py` (741 lines, no `test_` functions). At import it builds `anthropic.Anthropic()` (`:10`), and `main()` makes paid Haiku calls with `time.sleep` retries (`:648`). Root `test_e2e_live.py` (254 lines) places a **real phone call** when run.
- Category: hygiene / risk. Severity: low–med.
- What's wrong: pytest collects and imports the vagueness script on every run. `docs/how-to/testing.md:68` lists it as a test command. `pytest test_e2e_live.py` or `pytest .` would import the live script; it is guarded by `__main__`, but the name invites mistakes.
- Refactor: move both to `scripts/` (`scripts/vagueness_check.py`, `scripts/e2e_live_call.py`) with names that do not match `test_*`, and update the docs. Add `--ignore`-style protection with `python_files = ["test_*.py"]` scoped to `tests/` only (already via testpaths).
- Effort: S.

### T-12 — No enforced build gate; lint is red today
- Files: `pyproject.toml:1-5` (no `--strict-markers`, `filterwarnings`, coverage floor, `asyncio_mode`), `.claude/skills/deploy/SKILL.md:78`, `requirements.txt:5-8`.
- Category: build gates. Severity: med.
- What's wrong: `ruff check` has 55 errors and `ruff format` would rewrite 9 files, so the pre-commit hook only guards staged files and the gap grows. No type checker exists. A pydantic/model refactor is exactly where mypy pays off. The deploy gate runs the network test (T-01) and no lint. The `integration` marker is registered but unused.
- Refactor: (1) run `ruff check --fix` and `ruff format` once in a separate no-behavior commit; (2) add `addopts = "--strict-markers -p no:cacheprovider"` and `markers = ["slow", "network"]`; (3) add `[tool.coverage.report] fail_under = 76` (ratchet up); (4) add mypy in non-strict mode for `sentinel/alerts` and `sentinel/classification` first; (5) split `requirements-dev.txt`; (6) point `/deploy` at the gate below.
- Effort: S (plus M for mypy cleanup).

### T-13 — Brittle value-pinning and CWD-dependent paths
- Files: `tests/test_direct_openai.py:192-194` (asserts the production budget `== 30`), `tests/conftest.py:223` and 7 other places that open `"tests/fixtures/…"` or `"config/config.yaml"` relative to the CWD.
- Category: brittleness. Severity: low.
- What's wrong: an owner budget change fails a test that is meant to check validation. Running pytest from any other directory fails at fixture setup.
- Refactor: assert `ModelBudgetConfig(monthly_usd=configured_value)` validates (not the literal 30). Add a `REPO_ROOT = Path(__file__).resolve().parents[1]` constant in conftest and use it everywhere.
- Effort: S.

### T-14 — Slow suite for a pre-deploy gate (6.5 min, 12 min with coverage)
- Files: `tests/test_cli.py` (4 subprocess tests, about 75s), lingua detector built in-process (13s first hit).
- Category: build speed. Severity: low.
- Refactor: mark subprocess tests `slow` and run them only in the full gate. Add a session-scoped fixture that warms `summary_language` once. Consider `pytest-xdist` later (not installed; owner decision). Most test files use `tmp_path` and SQLite, so parallelism is safe after T-01.
- Effort: S.

## 5. Behavior-preservation safety net for a big refactor (what is missing)

The existing unit tests are good locally: state machine 87%, dispatcher and push 100%, incident memory 96%. But they are bound to private names (T-06, T-09) and to a non-production config (T-03), so a refactor would rewrite the tests together with the code and prove nothing. The safety net must be **black-box at the system edges, use production config, and be golden-file based**:

**A. Golden end-to-end characterization test** — new `tests/e2e/test_critical_path_golden.py` (missing today).
- Config: the real `config/config.yaml` through `load_config` (env placeholders via `monkeypatch.setenv`; db, log and ledger paths in `tmp_path`); `load_dotenv` disabled; sockets blocked.
- Real objects: `SentinelPipeline` built through its normal constructor, real `Classifier` + `OpenAIProvider` + policy + schema validation, real `IncidentMemory`, `Corroborator`, `AlertDispatcher`, `AlertStateMachine` and `Database`.
- Fakes only at the edges:
  - a fake fetcher returning fixture articles;
  - OpenAI over `httpx.MockTransport` returning canned structured replies (reuse the `classifier_with_http` seam at `tests/test_direct_openai.py:68-80`);
  - `FakeTwilio` and `FakePush` autospecced from the real classes, recording every call and its body;
  - a `FakeClock` with patched sleep.
- Scenarios (each a golden JSON snapshot of: events table, alert_records, the ordered list of outbound calls/SMS/pushes with their bodies, and the final `alert_status`):
  1. A single-source urgency-10 PL invasion produces exactly `max_call_retries` calls, one confirmation SMS, one additive push and status `retry_pending`.
  2. A Baltic urgency-9 strike produces a call.
  3. An urgency-7 article (other NATO strike) produces a push only, with no SMS and no call.
  4. A second outlet's duplicate in the next cycle produces no new call, `source_count` 2 and no revision bump.
  5. A noncritical event escalated by a critical article produces a call and revision 2.
  6. An acknowledged event plus an escalation produces an update SMS and a push but no call.
  7. A correct SMS-code reply stops the calls and sets acknowledged (T-04).
  8. With `make_alert_call` returning None (today's Twilio 401), push is still delivered, nothing crashes and the event stays retryable.
  9. With the classifier returning 5xx or budget exhausted, the article stays queued, and the next cycle classifies it and calls.
  10. A dry run sends nothing and does not poll pending calls (also pins TODO 6.1 item 17).
- Snapshot update flag (`--update-golden`) so intended changes are reviewed as diffs.

**B. Routing table test** (missing): run a pure `decide_action` against the real config over a grid of urgency 1–10 × sources 1–3 × acknowledged yes/no, compared with a checked-in expected table (CSV). It fails if a refactor changes any cell.

**C. Config contract test** (partly present at `test_config.py:349`): load the real YAML and assert the life-safety invariants rather than string shapes: critical `min_score` ≤ 9, critical action `phone_call`, `max_call_retries` ≥ 1, and incident-memory `critical_min_confidence` unchanged unless the golden is updated.

**D. Message-format goldens**: SMS, call TTS and push payload text for 3 representative events, through public formatters (T-09). These pin the Polish text and the byte budgets.

**E. Mutation spot-check** (one-off, manual): flip `>=` to `>` on the critical threshold and drop the `continue` at `state_machine.py:605`. The safety net must go red; today it would not catch the second mutation (T-04).

Order: T-01 → T-12(1) → T-05/T-06 seams (minimal, behavior-free) → A+B+D → only then refactor `state_machine` or `scheduler`.

## 6. Exact build-gate command (proposed)

Target gate (after T-01 and the one-off ruff cleanup):

```
.venv/bin/ruff check sentinel tests dashboard && .venv/bin/ruff format --check sentinel tests dashboard && .venv/bin/pytest tests/ -q -p no:cacheprovider --strict-markers -m "not network" --cov=sentinel --cov-branch --cov-fail-under=76
```

Until the ruff cleanup lands, the gate that passes today is `.venv/bin/pytest tests/ -q -p no:cacheprovider --deselect tests/test_cli.py::test_custom_config_path` (643 passed).
