# Project Sentinel — Architecture Reference

> Dense structured reference for LLM agents. No prose. Every claim anchored to a file/class/function.

---

## 1. Module Map

| File | Main Class / Function | Responsibility |
|---|---|---|
| `sentinel.py` | `main()` | CLI entry point, arg parsing, asyncio event loop |
| `run.sh` | — | Activates `.venv`, forwards all args to `sentinel.py` |
| `sentinel/config.py` | `SentinelConfig`, `load_config()` | Pydantic config schema; YAML load + `${ENV_VAR}` substitution |
| `sentinel/models.py` | `Article`, `ClassificationResult`, `Event`, `AlertRecord` | All dataclasses; SQLite serialization via `to_dict()`/`from_row()` |
| `sentinel/scheduler.py` | `SentinelPipeline`, `SentinelScheduler` | Pipeline orchestrator + APScheduler dual-lane wrapper |
| `sentinel/database.py` | `Database` | SQLite WAL-mode access layer; table creation, CRUD, cleanup |
| `sentinel/diagnostic.py` | `DiagnosticData`, `DiagnosticArticle` | Data containers for HTML diagnostic report |
| `sentinel/logging_setup.py` | `setup_logging()` | Rotating file + stderr handler config |
| `sentinel/fetchers/base.py` | `BaseFetcher` | Abstract base: `name: str`, `fetch() -> list[Article]` |
| `sentinel/fetchers/rss.py` | `RSSFetcher` | feedparser over configured RSS sources; `fetch(max_priority=N)` |
| `sentinel/fetchers/gdelt.py` | `GDELTFetcher` | GDELT DOC 2.0 API; theme + CAMEO code + Goldstein filter |
| `sentinel/fetchers/google_news.py` | `GoogleNewsFetcher` | Google News RSS per configured query |
| `sentinel/fetchers/telegram.py` | `TelegramFetcher` | Telethon MTProto client; buffers messages; **requires `start()`/`stop()` lifecycle** |
| `sentinel/processing/normalizer.py` | `Normalizer` | Strips/coerces fields to `Article` schema |
| `sentinel/processing/deduplicator.py` | `Deduplicator` | URL-hash exact match + rapidfuzz fuzzy title match against DB |
| `sentinel/processing/keyword_filter.py` | `KeywordFilter` | Multilingual keyword match; `diagnose()` for diagnostic mode |
| `sentinel/classification/classifier.py` | `Classifier` | Sends articles to Claude Haiku 4.5; returns `ClassificationResult` list |
| `sentinel/classification/corroborator.py` | `Corroborator` | Groups classifications into `Event` objects; checks source count |
| `sentinel/alerts/dispatcher.py` | `AlertDispatcher` | Sorts events by urgency; routes to `AlertStateMachine` or dry-run log |
| `sentinel/alerts/state_machine.py` | `AlertStateMachine` | Urgency → action decision; call/SMS/WhatsApp execution; cooldown; call polling |
| `sentinel/alerts/twilio_client.py` | `TwilioClient` | Twilio REST API wrapper: `make_call()`, `send_sms()`, `get_call_status()` |
| `app.py` | — | **Legacy prototype — not used in production. Ignore.** |

---

## 2. Data Models (`sentinel/models.py`)

### `Article`
Produced by: all fetchers. Consumed by: `Normalizer`, `Deduplicator`, `KeywordFilter`, `Classifier`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | UUID4, auto-generated |
| `source_name` | `str` | Human label (e.g. `"PAP"`) |
| `source_url` | `str` | Canonical URL of the article |
| `source_type` | `str` | `rss` \| `gdelt` \| `google_news` \| `telegram` |
| `title` | `str` | Raw headline |
| `summary` | `str` | Body excerpt or empty |
| `language` | `str` | ISO 639-1: `pl`, `en`, `uk`, `ru` |
| `published_at` | `datetime` | Source publication time |
| `fetched_at` | `datetime` | Time of fetch |
| `raw_metadata` | `dict` | Source-specific extras (JSON in DB) |
| `url_hash` | `str` | SHA-256 of `source_url`; computed in `__post_init__` |
| `title_normalized` | `str` | NFKD + strip diacritics + lowercase + collapse whitespace; used for fuzzy dedup |

### `ClassificationResult`
Produced by: `Classifier.classify_batch()`. Consumed by: `Corroborator.process_classifications()`.

| Field | Type | Notes |
|---|---|---|
| `article_id` | `str` | FK → `Article.id` |
| `is_military_event` | `bool` | Core yes/no from Haiku |
| `event_type` | `str` | `invasion` \| `airstrike` \| `missile_strike` \| `border_crossing` \| `airspace_violation` \| `naval_blockade` \| `cyber_attack` \| `troop_movement` \| `artillery_shelling` \| `drone_attack` \| `other` |
| `urgency_score` | `int` | 1–10 |
| `affected_countries` | `list[str]` | ISO codes |
| `aggressor` | `str` | Free text from model |
| `is_new_event` | `bool` | Model's judgement: new vs. ongoing coverage |
| `confidence` | `float` | 0.0–1.0 |
| `summary_pl` | `str` | Polish-language summary from model |
| `classified_at` | `datetime` | Timestamp |
| `model_used` | `str` | Haiku model ID |
| `input_tokens` | `int` | API usage |
| `output_tokens` | `int` | API usage |

### `Event`
Produced by: `Corroborator.process_classifications()`. Consumed by: `AlertDispatcher.dispatch()`, `AlertStateMachine.process_event()`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | UUID4 |
| `event_type` | `str` | Same enum as `ClassificationResult.event_type` |
| `urgency_score` | `int` | Max urgency across corroborating articles |
| `affected_countries` | `list[str]` | Union across corroborating articles |
| `aggressor` | `str` | From highest-urgency article |
| `summary_pl` | `str` | Polish summary |
| `first_seen_at` | `datetime` | Earliest article in group |
| `last_updated_at` | `datetime` | Latest article in group |
| `source_count` | `int` | Count of independent sources |
| `article_ids` | `list[str]` | All contributing article IDs |
| `alert_status` | `str` | `pending` \| `phone_call` \| `sms` \| `whatsapp` \| `dry_run` \| `retry_pending` |
| `acknowledged_at` | `datetime\|None` | Set when operator replies to SMS with correct 6-digit confirmation code |

### `AlertRecord`
Produced by: `AlertStateMachine`. Consumed by: `AlertStateMachine.check_pending_calls()`.

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | FK → `Event.id` |
| `alert_type` | `str` | `phone_call` \| `sms` \| `whatsapp` |
| `twilio_sid` | `str` | Twilio call/message SID |
| `status` | `str` | `initiated` \| `ringing` \| `completed` \| `acknowledged` \| `failed` |
| `attempt_number` | `int` | Retry counter |
| `sent_at` | `datetime` | When Twilio API was called |
| `message_body` | `str` | Full text of message/TTS script |
| `duration_seconds` | `int\|None` | Call duration (populated on poll) |

---

## 3. Pipeline Stages (`sentinel/scheduler.py:SentinelPipeline.run_cycle`)

```
Stage 1 — _fetch_all(fast_only: bool) → list[Article]
          [scheduler.py:SentinelPipeline._fetch_all]
          Calls fetcher.fetch() on each enabled BaseFetcher.
          fast_only=True: skips GDELT; RSSFetcher called with max_priority=1.

Stage 2 — Normalizer.normalize_batch(list[Article]) → list[Article]
          [processing/normalizer.py]
          Coerces fields, fills missing timestamps.

Stage 3 — Deduplicator.deduplicate_batch(list[Article]) → list[Article]
          [processing/deduplicator.py]
          1. Exact match: url_hash in articles table.
          2. Fuzzy match: rapidfuzz against title_normalized in recent DB articles
             (same-source threshold: 85; cross-source threshold: 95;
             lookback: config.processing.dedup.lookback_minutes).
          Stores new articles to DB. diagnostic=True records reasons.

Stage 4 — KeywordFilter.filter_batch(list[Article]) → list[Article]
          [processing/keyword_filter.py]
          Multilingual keyword match (PL/EN/UA/RU).
          SKIPPED for articles from keyword_bypass sources (Telegram channels
          or RSS sources with keyword_bypass: true in config).

Stage 5 — Classifier.classify_batch(list[Article]) → list[ClassificationResult]
          [classification/classifier.py]
          Calls Claude Haiku 4.5 (claude-haiku-4-5-20251001) via Anthropic API.
          Stores ClassificationResult to DB.
          On exception: logs error, returns []. Pipeline continues.

Stage 6 — Corroborator.process_classifications(list[ClassificationResult]) → list[Event]
          [classification/corroborator.py]
          Groups military classifications by event_type + affected_countries.
          Checks source independence (title similarity + domain).
          Sets Event.alert_status = 'pending' if source_count < corroboration_required.

Stage 7 — AlertDispatcher.dispatch(list[Event])     [diagnostic=False only]
          [alerts/dispatcher.py]
          Receives events returned by Corroborator (new or updated).
          Sorts by urgency_score desc. Calls AlertStateMachine.process_event().

Stage 8 — AlertStateMachine.check_pending_calls()   [diagnostic=False only]
          [alerts/state_machine.py]
          Polls Twilio for call status of initiated/ringing records.
          On completion: checks duration vs. acknowledgment threshold.

Stage 9 — Database.cleanup_old_records(article_days, event_days)
          [database.py]
          Deletes articles older than retention window.
```

---

## 4. Dual-Lane Scheduler (`sentinel/scheduler.py:SentinelScheduler`)

| Lane | Interval | Jitter | Sources | APScheduler job ID |
|---|---|---|---|---|
| Fast | `config.scheduler.fast_interval_minutes` (default: 3 min) | `min(jitter_seconds, 10)` | Telegram + Google News + RSS priority ≤ 1 | `sentinel_fast_lane` |
| Slow (full) | `config.scheduler.interval_minutes` (default: 15 min) | `jitter_seconds` (default: 30 s) | All sources (superset of fast lane, including GDELT + all RSS) | `sentinel_slow_lane` |

Both jobs: `max_instances=1`, `coalesce=True` (skips missed fires, never stacks).

Health written to `data/health.json` after each cycle via `SentinelScheduler._update_health()`.
Daily summary logged at UTC date rollover via `_maybe_log_daily_summary()`.
Fetcher failure: SMS sent after 10 consecutive failures for a single fetcher.
Pipeline failure: SMS sent after 3 consecutive cycle failures.

---

## 5. Alert Routing Logic (`sentinel/alerts/state_machine.py:AlertStateMachine._determine_action`)

Decision matrix driven by `config.alerts.urgency_levels` (sorted by `min_score` desc):

| urgency_score | source_count vs. corroboration_required | action | Event.alert_status set by corroborator |
|---|---|---|---|
| ≥ 9 (CRITICAL) | ≥ corroboration_required | `phone_call` | `phone_call` |
| ≥ 9 (CRITICAL) | < corroboration_required | `sms` (fallback) | `sms` |
| ≥ 7 (HIGH) | any | `sms` | `sms` |
| ≥ 5 (MEDIUM) | any | `whatsapp` → routed to `sms` (WhatsApp disabled) | `whatsapp` |
| ≥ 1 (LOW) | any | `log_only` | `pending` |

Post-alert state transitions (managed by `AlertStateMachine`, not corroborator):
- `acknowledged`: operator replies to the pre-call SMS with the correct 6-digit confirmation code. `acknowledged_at` is set on the Event. Further source additions trigger `_send_update_sms()`.
- `retry_pending`: call failed all `max_call_retries` attempts in one cycle without SMS confirmation. Next cycle attempts again.
- Cooldown: `acknowledgment.cooldown_hours` (default: 6) after `acknowledged_at`. No further calls or initial SMSes during cooldown.
- Pending call guard: if any `AlertRecord` has `status in ("initiated", "ringing")`, the event is skipped this cycle.

---

## 6. Key Config Keys

| YAML path | Type | Default | Effect |
|---|---|---|---|
| `classification.corroboration_required` | `int` | `2` | Min independent sources before `Event.alert_status` leaves `pending`. **Live config uses `1`.** |
| `classification.corroboration_window_minutes` | `int` | `60` | Lookback window for grouping articles into the same Event |
| `classification.model` | `str` | `claude-haiku-4-5-20251001` | Anthropic model for classification |
| `scheduler.fast_interval_minutes` | `int` | `3` | Fast-lane cadence |
| `scheduler.interval_minutes` | `int` | `15` | Slow-lane cadence |
| `scheduler.jitter_seconds` | `int` | `30` | Random delay added to slow-lane trigger; fast-lane capped at 10 s |
| `processing.dedup.same_source_title_threshold` | `int` | `85` | rapidfuzz score for same-source dedup |
| `processing.dedup.cross_source_title_threshold` | `int` | `95` | rapidfuzz score for cross-source dedup |
| `processing.dedup.lookback_minutes` | `int` | `60` | How far back DB title comparison looks |
| `alerts.urgency_levels.<name>.corroboration_required` | `int` | `1` | Per-level override for corroboration gate on phone calls |
| `alerts.acknowledgment.call_duration_threshold_seconds` | `int` | `15` | Min call duration to count as acknowledged |
| `alerts.acknowledgment.cooldown_hours` | `int` | `6` | No re-alerts within this window after acknowledgment |
| `database.article_retention_days` | `int` | `30` | Articles older than this deleted each cycle |
| `database.event_retention_days` | `int` | `90` | Events older than this deleted each cycle |
| `sources.rss[*].priority` | `int` | `2` | Priority 1 = included in fast lane; 2+ = slow lane only |
| `sources.rss[*].keyword_bypass` | `bool` | `false` | If true, article skips Stage 4 (keyword filter) |
| `sources.telegram.channels[*].keyword_bypass` | `bool` | `false` | Same bypass for Telegram channels |
| `testing.dry_run` | `bool` | `false` | Dispatcher logs intended actions; no Twilio calls made |

---

## 7. Database Schema (`sentinel/database.py:Database._create_tables`)

| Table | Key Fields | Indexes | Retention |
|---|---|---|---|
| `articles` | `id` PK, `url_hash`, `title_normalized`, `source_type`, `fetched_at` | `url_hash`, `fetched_at`, `title_normalized` | `database.article_retention_days` (default: 30 d) |
| `classifications` | `id` PK, `article_id` FK, `is_military_event`, `urgency_score`, `classified_at` | `article_id`, `urgency_score` | Cascades with article cleanup |
| `events` | `id` PK, `alert_status`, `first_seen_at`, `source_count`, `article_ids` (JSON) | `alert_status`, `first_seen_at` | `database.event_retention_days` (default: 90 d) |
| `alert_records` | `id` PK, `event_id` FK, `alert_type`, `twilio_sid`, `status`, `attempt_number` | `event_id` | Cascades with event cleanup |

SQLite WAL mode enabled. `check_same_thread=False` (single-process, async-safe via GIL).

---

## 8. Entry Points and CLI Flags (`sentinel.py`)

| Flag | Effect |
|---|---|
| _(no flags)_ | Start continuous dual-lane scheduler |
| `--once` | Run one full-lane cycle, then exit |
| `--dry-run` | Set `testing.dry_run=True`; no Twilio calls/SMS |
| `--config PATH` | Load config from `PATH` (default: `config/config.yaml`) |
| `--log-level LEVEL` | Override config log level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `--health` | Print `data/health.json` and exit |
| `--diagnostic` | One cycle + generate `data/diagnostic.html`; skips alert dispatch |
| `--test-headline "TEXT"` | Feed single headline through classifier only; print result |
| `--test-file FILE` | Feed YAML file of headlines through classifier; print results |
| `--test-alert [phone_call\|sms\|whatsapp]` | Fire real Twilio alert with synthetic event; bypasses fetch/classify/corroborate |

Config loading: `sentinel/config.py:load_config()`. Env vars substituted via `${VAR}` syntax. `.env` loaded via python-dotenv if available.

---

## 9. Known Quirks

- **`app.py` is a legacy prototype.** Not imported, not used, not tested. Ignore it.
- **Production `corroboration_required=1`** (single source triggers call). Code default is `2`. Check live `config/config.yaml` before assuming corroboration behavior.
- **`TelegramFetcher` lifecycle not in `BaseFetcher` contract.** `SentinelPipeline.startup()`/`shutdown()` use `hasattr(fetcher, "start")` duck-typing. If Telegram fails `start()`, it is logged and skipped — other fetchers are unaffected.
- **`keyword_bypass` sources skip Stage 4 entirely.** High-trust sources (e.g. UA Air Force Telegram) are passed directly to the classifier without keyword pre-filtering. This means all their articles consume Haiku API quota.
- **WhatsApp alert channel is disabled in code.** `AlertStateMachine.process_event()` routes `action == "whatsapp"` to `_execute_sms()`. Config urgency level `medium` still lists `whatsapp` as action; the code silently converts it.
- **Fast-lane jitter is capped at 10 s** regardless of `jitter_seconds` config value. Slow-lane uses the full configured value.
- **Fetcher health SMS fires exactly once at the 10th consecutive failure** per fetcher (`failures == 10` guard). It does not repeat.
- **Pipeline failure SMS fires at exactly 3 consecutive cycle failures** (`consecutive_failures == 3` guard). `SentinelScheduler._check_pipeline_health()`.
