# Testing Strategy

---

## Quick Reference

All commands use `./run.sh` (auto-activates `.venv`, forwards args to `sentinel.py`).

| Mode | Command | What it does | Side effects |
|---|---|---|---|
| Dry run (once) | `./run.sh --dry-run --once` | One full pipeline cycle; suppresses all Twilio calls | Events written to DB; no Twilio charges |
| Dry run (continuous) | `./run.sh --dry-run` | Continuous dual-lane scheduler; suppresses Twilio | Same as above, runs until killed |
| Run once | `./run.sh --once` | One full pipeline cycle with real alerts | Real Twilio calls/SMS if event triggers |
| Test headline | `./run.sh --test-headline "TEXT"` | Classifies a single headline via Claude Haiku; no fetch, no DB write | API cost: ~$0.001 per call |
| Test file | `./run.sh --test-file tests/fixtures/test_headlines.yaml` | Classifies all headlines in fixture; compares against expected scores | API cost per headline; no DB writes |
| Test alert (call) | `./run.sh --test-alert` or `./run.sh --test-alert phone_call` | Fires real Twilio phone call with synthetic event; bypasses fetch/classify/corroborate | Real Twilio charge; forces `dry_run=False` |
| Test alert (SMS) | `./run.sh --test-alert sms` | Fires real Twilio SMS with synthetic event | Real Twilio charge |
| Test alert (WhatsApp) | `./run.sh --test-alert whatsapp` | Fires real Twilio WhatsApp message with synthetic event | Real Twilio charge |
| Diagnostic | `./run.sh --diagnostic` | One full pipeline cycle; generates `data/diagnostic.html` | No alerts sent (forces dry-run); real API fetch costs |
| Health check | `./run.sh --health` | Prints `data/health.json` to stdout | Read-only |

---

## Test Suite

```bash
# All unit tests
.venv/bin/pytest tests/ -v

# Skip integration tests (no network/API calls)
.venv/bin/pytest tests/ -v -m "not integration"

# Integration tests only
.venv/bin/pytest tests/ -v -m integration

# With coverage
.venv/bin/pytest tests/ -v --cov=sentinel --cov-report=term-missing

# By phase
.venv/bin/pytest tests/test_config.py tests/test_database.py tests/test_models.py tests/test_cli.py -v           # Phase 1
.venv/bin/pytest tests/test_rss.py tests/test_gdelt.py tests/test_google_news.py tests/test_telegram.py -v      # Phase 2
.venv/bin/pytest tests/test_normalizer.py tests/test_deduplicator.py tests/test_keyword_filter.py -v            # Phase 3
.venv/bin/pytest tests/test_classifier.py tests/test_corroborator.py -v                                         # Phase 4
.venv/bin/pytest tests/test_twilio_client.py tests/test_state_machine.py tests/test_dispatcher.py -v           # Phase 5
.venv/bin/pytest tests/test_scheduler.py tests/test_integration.py tests/test_cli.py -v                         # Phase 6

# Dashboard subsystem (separate from monitoring runtime; see SPEC.md)
.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py -v
```

pytest config in `pyproject.toml` (`[tool.pytest.ini_options]`): `testpaths = ["tests"]`, `asyncio_mode = "auto"`, marker `integration` for tests requiring network/API access.

Test dependencies: `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-mock>=3.12`, `pytest-cov>=5.0`.

---

## Fixture Files

| Path | Contents |
|---|---|
| `tests/fixtures/test_headlines.yaml` | 25 headlines with expected `is_military_event`, `urgency_min/max`, `event_type`, `affected_countries`, `aggressor`. Covers critical (9-10), high (7-8), medium (5-6), low/not-military (1-4), and edge cases. |

Config key for fixture path: `testing.test_headlines_file`.

Pass threshold: **90%+ of headlines within expected urgency range** (LLM classification is probabilistic; off-by-one deviations are acceptable).

---

## Dry-Run Behavior

What is **suppressed** in dry-run mode:
- All Twilio phone calls, SMS, and WhatsApp messages.
- No Twilio charges incurred.

What runs **normally** in dry-run mode:
- All source fetching (RSS, Telegram, Google News, GDELT).
- Deduplication and keyword filtering.
- AI classification via Claude Haiku (API costs apply).
- Event creation and DB writes.
- Log output includes `[DRY RUN] would_trigger=phone_call` for events that would have triggered alerts.

Note: `--test-alert` **forces** `dry_run=False` regardless of config — its purpose is to fire real alerts.

---

## Diagnostic Mode

`./run.sh --diagnostic` runs one full pipeline cycle and writes `data/diagnostic.html`.

**Contents of `data/diagnostic.html`:**
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

Test stack: `vitest@^2`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`. Setup file at `src/test-setup.ts` wires jest-dom matchers. Shared fixtures live in `src/__tests__/fixtures.ts` (extended in Phase 3 with stats, article-detail, and classification fixtures).

What's covered:

| Test file | Focus | Phase |
|---|---|---|
| `src/__tests__/ArticleTable.test.tsx` | Rendering, sorting, expandable row + lazy `raw_metadata` fetch + error path, urgency colors, badges, sort-indicator visibility, `safeHref` plain-text fallback | 2 |
| `src/__tests__/ArticlesPage.test.tsx` | Stats error toast, tab-count error toast, conditional sort param omission, broad clear-all (URL fully cleared), sync → stats refresh + one Phase 3 cross-cutting assertion | 2 + 3 |
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
| `src/__tests__/ClassifierView.test.tsx` | Side-by-side rendering, Raw JSON toggle, unclassified notice | 3 |
| `src/__tests__/EventTimeline.test.tsx` | Events with alerts + empty-events message | 3 |

Phase 3 gate commands (from SPEC.md): `npm install`, `npm run build`, `npx tsc --noEmit`, `npx vitest run` — all must pass.

**Recharts under jsdom (Phase 3 quirk).** Recharts uses `ResponsiveContainer` which measures its parent's `clientWidth/clientHeight`. jsdom returns `0` for layout dimensions, so the chart's SVG paints nothing and the test sees an empty chart. Phase 3 chart tests (`OverviewPage.test.tsx`, `TimeSeriesChart.test.tsx`, `UrgencyHistogram.test.tsx`, `SourceBreakdown.test.tsx`) work around this by `vi.mock("recharts", ...)`-ing `ResponsiveContainer` with a stub that renders its children at deterministic dimensions (e.g. 600×280). The rest of recharts (`LineChart`, `BarChart`, `XAxis`, etc.) is left untouched.

**Backend coordination note.** The Phase 1 backend test `test_app_factory_frontend_placeholder` (in `tests/test_dashboard_api.py`) checks that `/` returns the bundled placeholder HTML when no built frontend is present. Phase 2 added a real `dashboard/frontend/dist/` so this test now monkeypatches `dashboard.app.config.FRONTEND_DIST_DIR` to a temporary empty directory — making it pass regardless of whether the developer has run `npm run build` locally.

**Backend Phase 3 extension.** `tests/test_dashboard_db.py` asserts that `get_stats()` returns `classified_per_day` with 30 entries sharing dates with `articles_per_day`. `tests/test_dashboard_api.py` asserts the same key surfaces in the `/api/stats` response.
