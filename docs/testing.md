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
