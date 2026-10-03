# Testing Strategy

Last verified: 2026-10-03 (deployed commit 6429124)

Contents: [Quick reference](#quick-reference) · [Test suite](#test-suite) · [Fixture files](#fixture-files) · [Dry-run behavior](#dry-run-behavior) · [Diagnostic mode](#diagnostic-mode) · [Dashboard frontend testing](#dashboard-frontend-testing)

---

## Quick Reference

All commands use `./run.sh`. It activates `.venv` and forwards the arguments to `sentinel.py`.

**Which config file is used.** Without `--config`, `sentinel.py` loads `config/config.yaml`. That file is the production config. It uses server paths under `/var/lib/sentinel` and `/var/log/sentinel` and the `${EXPO_PUSH_TOKEN}` placeholder. On a local machine it fails to load (`Environment variable 'EXPO_PUSH_TOKEN' is not set`), and even with that variable set it cannot write to the server paths. For local runs, pass the template or a private copy of it, for example `./run.sh --config config/config.example.yaml --dry-run --once`. The template uses local paths (`data/sentinel.db`, `logs/sentinel.log`, `data/model-usage.db`) and needs only the variable names listed in `.env.example`.

Classification uses the provider set in `classification.provider` (live: OpenAI `gpt-5.6-luna`, see [config reference](../reference/config-reference.md)). Every classifier call needs `OPENAI_API_KEY`, is charged, and is recorded in the usage ledger (`classification.budget.ledger_path`). The ledger counts toward the monthly cap `classification.budget.monthly_usd`.

Every `./run.sh` command on this page omits `--config` for brevity. On a local machine, add `--config data/config.local.yaml` (or `--config config/config.example.yaml`) to each of them.

Dry-run limit: a dry run suppresses alerts for the events of the current cycle. The cycle still checks phone calls left pending in the configured database and can retry such a call or send its fallback SMS. A fresh local database has no pending calls, so this matters only for a database that an earlier real run used. `--diagnostic` skips that check.

| Mode | Command | What it does | Side effects |
|---|---|---|---|
| Dry run (once) | `./run.sh --dry-run --once` | One full pipeline cycle; the dispatcher only logs the alert it would send | Events written to the DB; paid model calls (enrichment check and classification); no calls, SMS or pushes |
| Dry run (continuous) | `./run.sh --dry-run` | Continuous dual-lane scheduler with the same suppression | Same as above, runs until killed |
| Run once | `./run.sh --once` | One full pipeline cycle with real alerts | Real alerts if an event qualifies; the channels depend on the loaded config (template: SMS for tiers 5-8 because push is disabled; production: push only for tiers 5-8); paid model calls |
| Test headline | `./run.sh --test-headline "TEXT"` | Classifies a single headline through the configured provider; no fetch, no DB write | Paid model call (sometimes a second Polish-summary repair call), recorded in the usage ledger |
| Test file | `./run.sh --test-file path/to/headlines.yaml` | Classifies every entry of a `headlines:` list (see [Fixture files](#fixture-files) for the format); prints mismatches against `expected:` when present | Paid model call per headline; no DB writes |
| Eval harness | `./run.sh --eval` or `./run.sh --eval path/to/eval_set.yaml` | Runs the classifier eval set (default `testing.eval_set_file` = `tests/fixtures/eval_set.yaml`); saves a JSON report under `data/eval/` | Paid model calls; exits 0 only at 100% pass |
| Test alert (call) | `./run.sh --test-alert` or `./run.sh --test-alert phone_call` | Places a real Twilio phone call for a synthetic event; bypasses fetch, classification and corroboration | Forces `dry_run=False`; writes a synthetic `[TEST]` article and event to the configured DB |
| Test alert (SMS) | `./run.sh --test-alert sms` | Sends a real Twilio SMS for a synthetic event | Same DB writes as above |
| Test alert (push) | `./run.sh --test-alert push` | Sends a real Expo push for a synthetic event (requires `alerts.push.enabled: true` and at least one token in `alerts.push.tokens`) | Real push to configured devices; same DB writes as above |
| Diagnostic | `./run.sh --diagnostic` | One full pipeline cycle; writes `diagnostic.html` | No alerts sent (forces dry-run); paid model calls |
| Health check | `./run.sh --health` | Prints `health.json` to stdout | Read-only |

`health.json` and `diagnostic.html` live in the directory of `database.path`: `data/` with the template config, `/var/lib/sentinel/` with the production config.

Known state of Twilio: the owner keeps the Twilio account unfunded on purpose since 2026-09-21. Every Twilio call and SMS, including `--test-alert phone_call` and `--test-alert sms`, currently fails with HTTP 401 (`account … with status 4 is not active`) and costs nothing. Calls return when the owner recharges the account. See the [server runbook](server-runbook.md#1-an-urgency-910-alert-cannot-be-delivered-check-first).

---

## Test Suite

```bash
# All tests (offline: every external API is mocked)
.venv/bin/pytest tests/ -v

# How many tests exist right now (prints "N tests collected")
.venv/bin/pytest tests/ -q --co | tail -1

# With coverage
.venv/bin/pytest tests/ -v --cov=sentinel --cov-report=term-missing

# By phase
.venv/bin/pytest tests/test_config.py tests/test_database.py tests/test_models.py tests/test_cli.py -v           # Phase 1
.venv/bin/pytest tests/test_rss.py tests/test_gdelt.py tests/test_google_news.py tests/test_telegram.py -v      # Phase 2
.venv/bin/pytest tests/test_normalizer.py tests/test_deduplicator.py tests/test_keyword_filter.py -v            # Phase 3
.venv/bin/pytest tests/test_classifier.py tests/test_corroborator.py tests/test_cli_bridges.py -v               # Phase 4
.venv/bin/pytest tests/test_twilio_client.py tests/test_state_machine.py tests/test_dispatcher.py -v           # Phase 5
.venv/bin/pytest tests/test_scheduler.py tests/test_integration.py tests/test_cli.py -v                         # Phase 6

# Live classifier path (OpenAI provider, Polish-summary guard, classification queue)
.venv/bin/pytest tests/test_direct_openai.py tests/test_summary_language.py tests/test_classification_queue.py -v

# Incident memory
.venv/bin/pytest tests/test_incident_memory.py tests/test_incident_storage.py tests/test_incident_alerts.py -v

# Article enrichment (vagueness check + body fetch)
.venv/bin/pytest tests/test_enricher.py tests/test_vagueness_check.py -v

# Push client and datetime utilities
.venv/bin/pytest tests/test_push_client.py tests/test_utils_datetime.py -v

# Model-comparison eval tooling (see docs/how-to/model-comparison.md)
.venv/bin/pytest tests/test_model_comparison.py tests/test_openrouter_eval_client.py tests/test_cached_runtime.py tests/test_clarified_policy.py tests/test_separate_metrics.py -v

# Dashboard subsystem (separate from monitoring runtime; see SPEC.md)
.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py tests/test_dashboard_annotations.py -v

# /sentinel-audit skill structural tests (docs/archive/SPEC_ALERT_GROUPING.md Phase 3 — asserts event-grouped
# report layout, ordering, JSON-array parsing strategy, and preserved Step 2 / Step 4 sections in
# .claude/skills/sentinel-audit/SKILL.md)
.venv/bin/pytest tests/test_sentinel_audit_skill.py -v
```

pytest config in `pyproject.toml` (`[tool.pytest.ini_options]`): `testpaths = ["tests"]` and a registered marker `integration`. No test uses that marker today, so `-m integration` selects nothing and the whole suite runs offline with mocks. `asyncio_mode` is not set, so pytest-asyncio runs in its default strict mode: every async test (and async fixture) must carry an explicit `@pytest.mark.asyncio` marker. With the installed pytest 9 and pytest-asyncio 1.x, an unmarked `async def test_...` fails with "async def functions are not natively supported". All async test files follow this convention.

Test dependencies: `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-mock>=3.12`, `pytest-cov>=5.0`.

### Mocking and shared fixtures

`tests/conftest.py` provides two config fixtures:

- `config` uses the code defaults, which select the legacy Anthropic provider and `claude-haiku-4-5-20251001`. Most older tests use it.
- `direct_config` switches to the live settings: provider `openai`, model `gpt-5.6-luna`, the version-2 policy from `tests/fixtures/benchmark_policy_v2.yaml`, incident memory on, and a usage ledger under `tmp_path`.

Tests of the live OpenAI path (`tests/test_direct_openai.py`) set a placeholder `OPENAI_API_KEY` and replace the `openai.AsyncOpenAI` client with one whose HTTP calls go to an `httpx.MockTransport` handler. No real request leaves the machine. These tests cover no-retry behaviour, the total timeout, the budget ledger, a missing key, the strict output schema and reasoning being off.

### Async classifier, alert-path & CLI-bridge tests

The classifier, the alert path (`AlertDispatcher.dispatch`, the `AlertStateMachine` alert-execution methods, `check_pending_calls`) and the CLI bridges are async. Tests reflect this:

- `tests/test_classifier.py` — covers the legacy Anthropic path only. It patches `sentinel.classification.classifier.anthropic.AsyncAnthropic` and stubs `messages.create` with an `AsyncMock`. The retry test patches `sentinel.classification.classifier.asyncio.sleep` (asserting it is awaited once with `5`) rather than sleeping for real. Dedicated cases assert `classify_batch` is strictly sequential (concurrency never exceeds 1, input order preserved), skips per-article failures, and that `aclose()` awaits the underlying client close exactly once.
- `tests/test_state_machine.py` — the alert-path tests are async (`@pytest.mark.asyncio`); `asyncio.sleep` is patched as an `AsyncMock` so poll/pause loops don't sleep for real. Dedicated cases assert the API-call retry pause is awaited (`test_api_call_retry_pause_is_awaited`), that the named Twilio calls are routed through `asyncio.to_thread` (`test_twilio_calls_routed_through_to_thread`), that DB calls are **not** offloaded to a thread (`test_db_calls_not_offloaded_to_thread`, a negative guard checking the offloaded callable's `__self__` is not a `Database`), and that the poll/pause durations are read from config (`test_poll_durations_from_config`).
- `tests/test_dispatcher.py` — dispatch tests are async; `test_dispatch_is_async_and_sequential` asserts events are processed one at a time in urgency-descending order (no concurrent `process_event`).
- `tests/test_cli_bridges.py` — smoke tests that the sync CLI/eval entry points bridge to the async paths correctly: `_run_test_file` drives all headlines under a **single** `asyncio.run` (not one event loop per headline), `run_eval` is a coroutine, `run_cycle` awaits the classifier, and `test_run_test_alert_bridges_async` (parametrized `phone_call`/`sms`) checks `_run_test_alert` drives the async `_execute_phone_call` / `_execute_sms` under `asyncio.run`. The module is loaded via `importlib` to work around package-name shadowing of `sentinel.py`.
- `tests/test_integration.py` and `tests/test_scheduler.py` — pipeline mocks set `classify_batch` and `aclose` as `AsyncMock`s so the awaited call sites (in `run_cycle` and `shutdown`) succeed without raising or logging a spurious error. `test_scheduler.py` stubs `dispatch` / `check_pending_calls` as `AsyncMock`s, adds `test_run_cycle_awaits_dispatch_and_check_pending` (it turns `RuntimeWarning` into an error to catch un-awaited coroutines), and also asserts `shutdown` awaits `classifier.aclose()` once.

---

## Fixture Files

`--eval` and `--test-file` read two different formats.

- **Eval sets (`--eval` only).** A flat top-level list of cases, or a dict with a `cases:` list (`sentinel/eval/harness.py`). Each case has `id`, `headline`, `summary`, `source`, `language`, `failure_mode` and an `expected:` map. In `expected:`, the keys `is_military_event`, `urgency_min`, `urgency_max` and `expected_action` are required. Optional keys are `affected_countries`, `affected_countries_must_not_contain`, `aggressor`, `aggressor_any_of`, and `event_type` or `event_type_any_of`. A case passes only when every applicable check passes, including the derived action. The harness derives the action itself: urgency 9 or more with a monitored country gives `phone_call`, 5 or more gives `sms` (the harness's name for the 5-8 tier), anything else gives `log_only`. Errors count as failures.
- **Headline files (`--test-file` only).** A dict with a `headlines:` list. Each entry is a plain string or a map with `text` (or `headline`) and an optional `expected:` map. Each `expected:` key is compared by exact equality with the attribute of the same name on the classification result, so range keys such as `urgency_min` always show as mismatches. The eval sets below have no `headlines:` key, so `--test-file` cannot read them.

| Path | Contents | Used by |
|---|---|---|
| `tests/fixtures/eval_set.yaml` | Default eval set (config key `testing.eval_set_file`). Cases extracted from the 2026-03-24 to 2026-05-01 audit reports, tagged by `failure_mode`. It has no `phone_call` (9-10) case; the highest expected urgency is 8. | `--eval` |
| `tests/fixtures/eval_set_human.yaml` | Production articles blind-labelled by the owner on 2026-05-22, including `phone_call` cases; the urgency range is the human score plus or minus 1. | `--eval` |
| `tests/fixtures/benchmark_policy_v2.yaml` | Resolved version-2 classification policy. | `direct_config` test fixture, runtime/policy tests, model comparison |
| `tests/fixtures/model_comparison_first50.yaml` | First-round model-comparison dataset. | `sentinel.eval.compare_models` (default dataset) |
| `tests/fixtures/model_comparison_v2_development.yaml` | Version-2 development cases. | `sentinel.eval.compare_models --dataset …` |
| `tests/fixtures/model_comparison_v2_holdout.yaml` | Version-2 held-out cases. | `sentinel.eval.compare_models`, `sentinel.eval.direct_luna`, `tests/test_direct_openai.py` |
| `tests/fixtures/luna_direct_fresh.yaml` | Fresh cases for the capped direct-API Luna checks. | `sentinel.eval.direct_luna` (default `--fresh`), `tests/test_direct_openai.py` |
| `tests/fixtures/incident_memory_eval.yaml` | Incident-memory smoke set. | `sentinel.eval.incident_memory` |
| `tests/fixtures/polish_summary_guard_fresh.yaml` | Fixed translation-only cases for the Polish-summary guard ([design note](../ideas/polish-summary-guard.md)). No module or test loads it by default. | manual checks |

Count the cases in a fixture with `.venv/bin/python -c "import yaml; print(len(yaml.safe_load(open('tests/fixtures/eval_set.yaml'))))"`. The model-comparison and policy files are explained in [model-comparison.md](model-comparison.md).

### `--eval` (classifier eval harness)

```bash
./run.sh --eval                               # uses testing.eval_set_file (tests/fixtures/eval_set.yaml)
./run.sh --eval tests/fixtures/eval_set_human.yaml   # explicit path
```

The eval harness calls the configured classifier provider (paid, recorded in the usage ledger), scores every case against its `expected:` map, and writes a JSON report under `data/eval/`. It exits 0 only when the pass rate is 1.0 (100%) — any miss is a non-zero exit, which makes it usable as a CI/regression gate. (LLM classification is probabilistic, so expect to tune thresholds or labels rather than chasing a flaky single run.)

---

## Dry-Run Behavior

What is suppressed in dry-run mode:
- All Twilio phone calls and SMS.
- Expo push notifications.

What runs normally in dry-run mode:
- Fetching from every source enabled in the config. Which sources are on is set by `sources.*.enabled` in `config/config.yaml`; see [sources](../reference/sources.md).
- Deduplication and keyword filtering.
- Article enrichment: a paid OpenAI vagueness check (`enrichment_quality`) and, when needed, an article-body fetch.
- AI classification through the configured provider (live: `gpt-5.6-luna`). Model costs apply and are recorded in the usage ledger.
- Event creation and DB writes.
- Log output includes `[DRY RUN] would_trigger=phone_call` for events that would have triggered alerts.

Note: `--test-alert` forces `dry_run=False` regardless of config, because its purpose is to fire real alerts.

---

## Diagnostic Mode

`./run.sh --diagnostic` runs one full pipeline cycle and writes `diagnostic.html` in the directory of `database.path` (`data/` with the template config).

**Contents of `diagnostic.html`:**
- Every fetched article from all sources in this cycle.
- Per-article: keyword match result (matched/filtered/bypassed), classification result (urgency score, event type, confidence), corroboration status.
- Summary stats: articles fetched per source, filtered count, classified count, events created.

Use when: tuning keyword lists (`monitoring.keywords` in config), validating classifier accuracy against live data, or investigating why a real event was or was not flagged.

---

## Dashboard Frontend Testing

The dashboard's React frontend at `dashboard/frontend/` ships its own test suite (vitest + @testing-library/react + jsdom). All commands are run from the frontend directory.

```bash
# Install once (creates node_modules/)
cd dashboard/frontend && npm install

# Run all frontend unit tests
cd dashboard/frontend && npx vitest run

# Watch mode (for iterative development)
cd dashboard/frontend && npm run test:watch

# Type-check only — no compiled output
cd dashboard/frontend && npx tsc --noEmit

# Full production build (also type-checks via `tsc -b`)
cd dashboard/frontend && npm run build
```

Test stack: `vitest@^2`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`. Setup file at `src/test-setup.ts` wires jest-dom matchers. Shared fixtures live in `src/__tests__/fixtures.ts` (extended in Phase 3 with stats, article-detail, and classification fixtures; extended again in Phase 4 with `makeAnnotation` / `makeArticleAnnotation` helpers and `annotation_stats` defaults).

What's covered (the folder `dashboard/frontend/src/__tests__/` is the source of truth; [dashboard/CLAUDE.md](../../dashboard/CLAUDE.md) owns the dashboard rules):

| Test file | Focus | Phase |
|---|---|---|
| `src/__tests__/ArticleTable.test.tsx` | Rendering, sorting, expandable row + lazy `raw_metadata` fetch + error path, urgency colors, badges, sort-indicator visibility, `safeHref` plain-text fallback. Phase 4: `test_default_columns` now asserts the `annotation` / `Note` column is in the default visible set | 2 + 4 |
| `src/__tests__/ArticlesPage.test.tsx` | Stats error toast, tab-count error toast, conditional sort param omission, broad clear-all (URL fully cleared), sync → stats refresh + one Phase 3 cross-cutting assertion. Phase 4: stats stub carries `annotation_stats` so the page renders without crashing | 2 + 3 + 4 |
| `src/__tests__/ColumnPicker.test.tsx` | Toggles + `localStorage` persistence | 2 |
| `src/__tests__/FilterBar.test.tsx` | Filter → URL updates, clear-all, source multi-select round-trip | 2 |
| `src/__tests__/FilterTabs.test.tsx` | Tab selection filters by `pipeline_status` | 2 |
| `src/__tests__/SearchBar.test.tsx` | 300 ms debounce via `vi.useFakeTimers` | 2 |
| `src/__tests__/Pagination.test.tsx` | Page-size change resets to page 1; `localStorage` persistence | 2 |
| `src/__tests__/SyncButton.test.tsx` | Sync flow + tunnel-mode disabled state | 2 |
| `src/__tests__/client.test.ts` | `ApiError` carries `status`/`body`/`url`/`message` correctly | 2 |
| `src/__tests__/safeHref.test.ts` | http/https accept; javascript/data/ftp/malformed reject | 2 |
| `src/__tests__/useLocalStorage.test.ts` | Hydration, malformed JSON fallback + clear, validator rejection | 2 |
| `src/__tests__/OverviewPage.test.tsx` | Overview renders, view toggle switches Pipeline ↔ Analytics, stats cards display, pipeline funnel counts, funnel stage navigation | 3 |
| `src/__tests__/TimeSeriesChart.test.tsx` | Dual-series legend assertion (`articles_per_day` + `classified_per_day`) | 3 |
| `src/__tests__/UrgencyHistogram.test.tsx` | Histogram bar colors per urgency tier (gray / yellow / orange / red) | 3 |
| `src/__tests__/SourceBreakdown.test.tsx` | Sources sorted by count descending | 3 |
| `src/__tests__/ArticleDetailPage.test.tsx` | Detail header + back-link state preservation | 3 |
| `src/__tests__/EventDetailPage.test.tsx` | Known event renders, 404 shows not-found, back link uses browser history | — |
| `src/__tests__/datetime.test.ts` | UTC to Europe/Warsaw formatting (summer and winter time), em dash for empty input, raw string for unparseable input | — |
| `src/__tests__/ClassifierView.test.tsx` | Side-by-side rendering, Raw JSON toggle, unclassified notice | 3 |
| `src/__tests__/EventTimeline.test.tsx` | Events with alerts + empty-events message | 3 |
| `src/__tests__/AnnotationPanel.test.tsx` | 6 tests — `test_annotation_panel_prefill` (req 4.3a), empty-form initial state + no delete button, save flow with inline success indicator and form-stays-mounted (req 4.3b), client-side urgency rejection without API call, delete confirmation reject + accept paths (req 4.3c), server-error surfacing | 4 |
| `src/__tests__/AnnotationBadge.test.tsx` | 3 tests — `test_annotation_badge_colors` (req 4.4) verifies green/red/yellow per label via `annotationBadge` helper; em-dash placeholder when annotation is null; label text in `compact={false}` mode | 4 |

Phase 3 gate commands (from SPEC.md): `npm install`, `npm run build`, `npx tsc --noEmit`, `npx vitest run` — all must pass.

Phase 4 gate commands (from SPEC.md): `.venv/bin/pytest tests/test_dashboard_annotations.py -v` (22 tests covering all 12 named spec acceptance tests plus 10 edge cases), full backend regression via `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py tests/test_dashboard_annotations.py -v`, plus `npm run build` / `npx tsc --noEmit` / `npx vitest run` on the frontend.

**Recharts under jsdom (Phase 3 quirk).** Recharts uses `ResponsiveContainer` which measures its parent's `clientWidth/clientHeight`. jsdom returns `0` for layout dimensions, so the chart's SVG paints nothing and the test sees an empty chart. Phase 3 chart tests (`OverviewPage.test.tsx`, `TimeSeriesChart.test.tsx`, `UrgencyHistogram.test.tsx`, `SourceBreakdown.test.tsx`) work around this by `vi.mock("recharts", ...)`-ing `ResponsiveContainer` with a stub that renders its children at deterministic dimensions (e.g. 600×280). The rest of recharts (`LineChart`, `BarChart`, `XAxis`, etc.) is left untouched.

**Backend coordination note.** The Phase 1 backend test `test_app_factory_frontend_placeholder` (in `tests/test_dashboard_api.py`) checks that `/` returns the bundled placeholder HTML when no built frontend is present. Phase 2 added a real `dashboard/frontend/dist/` so this test now monkeypatches `dashboard.app.config.FRONTEND_DIST_DIR` to a temporary empty directory — making it pass regardless of whether the developer has run `npm run build` locally.

**Backend Phase 3 extension.** `tests/test_dashboard_db.py` asserts that `get_stats()` returns `classified_per_day` with 30 entries sharing dates with `articles_per_day`. `tests/test_dashboard_api.py` asserts the same key surfaces in the `/api/stats` response.

**Backend Phase 4 extension.** `tests/test_dashboard_annotations.py` (22 tests) covers the `AnnotationDB` layer, every `/api/annotations*` endpoint, the `has_annotation` / `annotation_label` filters on `/api/articles`, the `annotation_stats` block on `/api/stats`, and edge cases (upsert with null fields, bool rejection on `expected_urgency`, missing `article_id` rejection, behaviour when the annotations DB file is absent, persistence across `DashboardDB` reopen, and search + annotation-filter composition via the LIKE branch). Each test isolates BOTH the sentinel DB and the annotations DB under `tmp_path` so parallel test runs stay safe.

**`/sentinel-audit` skill structural tests ([SPEC_ALERT_GROUPING.md](../archive/SPEC_ALERT_GROUPING.md) Phase 3).** `tests/test_sentinel_audit_skill.py` (4 module-level pytest functions, module-scoped fixture reading `SKILL.md` once via pathlib) is the structural acceptance suite for the `/sentinel-audit` skill prompt. The audit skill is a markdown-driven LLM prompt rather than executable Python, so its tests are string-presence checks against `.claude/skills/sentinel-audit/SKILL.md`: `test_skill_md_documents_event_grouping` (event_id + events.article_ids + "Standalone classified articles" + per-event-block layout terms), `test_skill_md_documents_ordering` (urgency_score desc → first_seen_at desc, validated via 400-char sliding window), `test_skill_md_preserves_unchanged_sections` (Step 2 keyword filter + Step 4 source health + `.last-audit-timestamp` + `data/audit-reports/audit-` output path all survive Phase 3 changes), and `test_skill_md_documents_json_array_format` (either `json_each` or `json.loads` is documented for parsing `events.article_ids`). Runtime audit-report behaviour is verified manually per the Manual Verification checklist in [docs/archive/SPEC_ALERT_GROUPING.md](../archive/SPEC_ALERT_GROUPING.md) Phase 3, not by pytest.
