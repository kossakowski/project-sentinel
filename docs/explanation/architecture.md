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
| `sentinel/utils/` | `datetime.py`, `html.py` | Was the single module `sentinel/utils.py`; now a package — `datetime.py` (UTC-store / Warsaw-render helpers, e.g. `format_warsaw`), `html.py` (`strip_html`) |
| `sentinel/fetchers/base.py` | `BaseFetcher` | Abstract base: `name: str`, `fetch() -> list[Article]` |
| `sentinel/fetchers/rss.py` | `RSSFetcher` | `feedparser` + `httpx`; conditional GET via in-memory `_etag_cache` / `_last_modified_cache` keyed by URL (sends `If-None-Match` / `If-Modified-Since`; 304 → `[]`). `rss.py:99-111`. `fetch(max_priority=N)` |
| `sentinel/fetchers/gdelt.py` | `GDELTFetcher` | GDELT DOC 2.0 API; theme + `sourcecountry` filter, `TIMESPAN={lookback_minutes}min`, `maxrecords=250`. **DISABLED in production** (`sources.gdelt.enabled: false`); the fetcher is only instantiated when enabled. (No CAMEO event-code or Goldstein filter — those never existed.) |
| `sentinel/fetchers/google_news.py` | `GoogleNewsFetcher` | Google News RSS per configured query |
| `sentinel/fetchers/telegram.py` | `TelegramFetcher` | Telethon MTProto client; buffers messages; **requires `start()`/`stop()` lifecycle** |
| `sentinel/processing/normalizer.py` | `Normalizer` | Strips/coerces fields to `Article` schema |
| `sentinel/processing/deduplicator.py` | `Deduplicator` | URL-hash exact match + rapidfuzz fuzzy title match against DB |
| `sentinel/processing/keyword_filter.py` | `KeywordFilter` | Multilingual keyword match; `diagnose()` for diagnostic mode |
| `sentinel/processing/enricher.py` | `ArticleEnricher` | Two-gate content enrichment for articles with thin summaries: free heuristic gate (summary ≈ title) + cheap LLM vagueness gate, then fetches the article body via `httpx`; `enrich_batch` is `async` |
| `sentinel/classification/classifier.py` | `Classifier` | Sends articles to Claude Haiku 4.5 via `anthropic.AsyncAnthropic`; `classify` / `classify_batch` / `_call_api` / `_send_request` / `aclose` are `async`; returns `ClassificationResult` list. `classify_batch` is sequential (one awaited `classify` per article). |
| `sentinel/classification/corroborator.py` | `Corroborator` | Groups classifications into `Event` objects; checks source count |
| `sentinel/alerts/dispatcher.py` | `AlertDispatcher` | Sorts events by urgency; routes to `AlertStateMachine` or dry-run log |
| `sentinel/alerts/state_machine.py` | `AlertStateMachine` | Urgency → action decision; async call/SMS execution; cooldown; call polling |
| `sentinel/alerts/twilio_client.py` | `TwilioClient` | Twilio REST API wrapper: `make_alert_call(phone, message_pl, event_id)` (`twilio_client.py:43`), `send_sms(phone, message, event_id)`, `get_call_status(twilio_sid)` |
| `sentinel/alerts/push_client.py` | `ExpoPushClient` | Additive Expo push channel: `send_push(title, body, event_id, data)` POSTs to `https://exp.host/--/api/v2/push/send` (optional `EXPO_ACCESS_TOKEN` bearer). OFF by default (`alerts.push.enabled: false`); returns a generic `AlertRecord` with `alert_type="push"`. See [`mobile-app.md`](mobile-app.md) for the companion app that registers the device push token. |

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
| `alert_status` | `str` | Values written by code: `pending`, `call_placed`, `retry_pending`, `sms_sent`, `acknowledged`, `dry_run` (historical records may also contain `whatsapp_sent` from the removed WhatsApp channel). `Corroborator._determine_alert_status` sets a provisional value (`phone_call`/`sms`/`pending`) but `AlertStateMachine` overwrites it with the values above. |
| `acknowledged_at` | `datetime\|None` | Set when operator replies to SMS with correct 6-digit confirmation code |

### `AlertRecord`
Produced by: `AlertStateMachine`. Consumed by: `AlertStateMachine.check_pending_calls()`.

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | FK → `Event.id` |
| `alert_type` | `str` | `phone_call` \| `sms` \| `push` (historical records may also contain `whatsapp` — that channel was removed; the literal survives only in old DB rows) |
| `twilio_sid` | `str` | Twilio call/message SID |
| `status` | `str` | Twilio API values: `initiated`, `ringing`, `in-progress`, `completed`, `busy`, `no-answer`, `failed`, `canceled`; plus internal `acknowledged`. `Database.get_pending_call_records()` (`database.py:221`) filters `status IN ('initiated', 'ringing')`. |
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

Stage 4.5 — await ArticleEnricher.enrich_batch(list[Article]) → list[Article]
          [processing/enricher.py]
          async; awaited by run_cycle inside the cycle lock (scheduler.py:239),
          only when relevant articles remain after Stage 4.
          For articles whose summary adds nothing over the title, fetches the
          article body. Two gates: a free heuristic (summary ≈ title) and a cheap
          LLM vagueness check; flagged articles get their body fetched via httpx.
          Improves classifier input quality; does not drop articles.

Stage 5 — await Classifier.classify_batch(list[Article]) → list[ClassificationResult]
          [classification/classifier.py]
          async; awaited by run_cycle inside the cycle lock (scheduler.py:245).
          Calls Claude Haiku 4.5 (claude-haiku-4-5-20251001) via anthropic.AsyncAnthropic.
          Sequential: awaits one classify() per article (no asyncio.gather/Semaphore);
          the loop-unblocking comes from await, not parallelism. Per-article
          json.JSONDecodeError / anthropic.APIError are logged and the article skipped.
          Stores ClassificationResult to DB.
          On exception: logs error, returns []. Pipeline continues.

Stage 6 — Corroborator.process_classifications(list[ClassificationResult]) → list[Event]
          [classification/corroborator.py]
          Groups military classifications by event_type + affected_countries within
          the corroboration window (default 6h, config-driven). Summary and
          syndication similarity thresholds are also config-driven.
          Checks source independence (title similarity + domain).
          Sets Event.alert_status = 'pending' if source_count < corroboration_required.

Stage 7 — await AlertDispatcher.dispatch(list[Event])     [diagnostic=False only]
          [alerts/dispatcher.py]
          async; awaited by run_cycle inside the cycle lock (scheduler.py:262).
          Receives events returned by Corroborator (new or updated).
          Sorts by urgency_score desc. Awaits AlertStateMachine.process_event()
          sequentially, one event at a time (no asyncio.gather over events —
          per-event confirmation state lives on the shared state machine). The
          dry-run path stays synchronous.

Stage 8 — await AlertStateMachine.check_pending_calls()   [diagnostic=False only]
          [alerts/state_machine.py]
          async. Polls Twilio for call status of initiated/ringing records.
          The blocking Twilio HTTP calls are offloaded via asyncio.to_thread;
          DB reads/writes stay on the event-loop thread.
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
| Slow (full) | `config.scheduler.interval_minutes` (default: 15 min) | `jitter_seconds` (default: 30 s) | All enabled fetchers (superset of fast lane: all RSS + GDELT **only if `sources.gdelt.enabled` — currently off in production**) | `sentinel_slow_lane` |

Both jobs: `max_instances=1`, `coalesce=True` (skips missed fires, never stacks).

Health written to `data/health.json` after each cycle via `SentinelScheduler._update_health()`.
Daily summary logged at UTC date rollover via `_maybe_log_daily_summary()`.
Fetcher failure: SMS sent after 10 consecutive failures for a single fetcher.
Pipeline failure: SMS sent after 3 consecutive cycle failures.

---

## 5. Alert Routing Logic (`sentinel/alerts/state_machine.py:AlertStateMachine._determine_action`)

**Two independent alert-level decisions exist** (they can disagree — see §9):
1. `Corroborator._determine_alert_status` gates whether an event is "alertable" using hardcoded urgency cuts (`phone_call` if urgency ≥ 9 AND `source_count ≥ corroboration_required`; `sms` if ≥ 7; `sms` if ≥ 5; else `pending`; `dry_run` short-circuits to `"dry_run"`). It writes a provisional `Event.alert_status`.
2. `AlertStateMachine._determine_action` makes the **final channel choice** from `config.alerts.urgency_levels` + each level's `corroboration_required`, ignoring the stored value.

Decision matrix driven by `config.alerts.urgency_levels` (sorted by `min_score` desc):

| urgency_score | source_count vs. corroboration_required | action | Event.alert_status set by corroborator |
|---|---|---|---|
| ≥ 9 (CRITICAL) | ≥ corroboration_required | `phone_call` | `phone_call` |
| ≥ 9 (CRITICAL) | < corroboration_required | `sms` (fallback) | `sms` |
| ≥ 7 (HIGH) | any | `sms` | `sms` |
| ≥ 5 (MEDIUM) | any | `sms` | `sms` |
| ≥ 1 (LOW) | any | `log_only` | `pending` |

**Additive push dispatch.** For any non-`log_only` action, `process_event` fires an Expo push (`_maybe_send_push` → `ExpoPushClient.send_push`) **additively, before** the Twilio dispatch — after the cooldown / acknowledged / pending-call / dedup gates, so it reaches the phone immediately. It is a no-op when `alerts.push.enabled` is false or no tokens are configured (the default). The push is recorded as a separate `AlertRecord` with `alert_type="push"`; the initial push is deduped on the presence of a prior `push` record. Because `push` is NOT in `_USER_NOTIFIED_ALERT_TYPES` (`sms`, `whatsapp`, `phone_call`), a sent push does not suppress a later SMS. See [`mobile-app.md`](mobile-app.md) for the companion app.

Post-alert state transitions (managed by `AlertStateMachine`, not corroborator):
- `acknowledged`: operator replies to the pre-call SMS with the correct 6-digit confirmation code. `acknowledged_at` is set on the Event. Further source additions trigger `_send_update_sms()`.
- `retry_pending`: call failed all `max_call_retries` attempts in one cycle without SMS confirmation. Next cycle attempts again.
- Cooldown: `acknowledgment.cooldown_hours` (default: 6) after `acknowledged_at`. No further calls or initial SMSes during cooldown.
- Pending call guard: if any `AlertRecord` has `status in ("initiated", "ringing")`, the event is skipped this cycle.

---

## 6. Key Config Keys

| YAML path | Type | Default | Effect |
|---|---|---|---|
| `classification.corroboration_required` | `int` | `2` | Min independent sources before a phone call fires (the corroborator's `phone_call` gate). **Pydantic default `2`, but live `config/config.yaml` sets `1`.** |
| `classification.corroboration_window_minutes` | `int` | `360` | **Sliding** window (6 h) for grouping articles into the same Event, measured from the event's `last_updated_at` (last activity), **not** `first_seen_at` — a multi-hour incident that keeps getting fresh articles stays ONE event. Default & live `360`. |
| `classification.corroboration_max_age_minutes` | `int` | `2880` | Absolute lifetime cap (48 h) measured from `first_seen_at`; retires perpetually-updated events so they can't chain-merge distinct incidents. `0` disables. Default & live `2880`. |
| `classification.summary_similarity_metric` | `str` | `token_set_ratio` | Which `rapidfuzz.fuzz` function matches a summary to an existing event; validated against `{ratio, partial_ratio, token_sort_ratio, token_set_ratio, WRatio, QRatio}`. `token_set_ratio` is length-robust. Config-selectable (no code deploy needed). |
| `classification.summary_similarity_threshold` | `int` | `50` | Score (0-100) from `summary_similarity_metric` required to merge a summary into an existing event (lower = more aggressive merging). Default & live `50`. |
| `classification.syndication_similarity_threshold` | `int` | `90` | Title similarity (`fuzz.ratio` over normalized titles) at/above which a new article is treated as a syndicated copy of an existing source and does NOT count as independent (checked across all source types). |
| `classification.model` | `str` | `claude-haiku-4-5-20251001` | Anthropic model for classification |
| `scheduler.fast_interval_minutes` | `int` | `3` | Fast-lane cadence |
| `scheduler.interval_minutes` | `int` | `15` | Slow-lane cadence |
| `scheduler.jitter_seconds` | `int` | `30` | Random delay added to slow-lane trigger; fast-lane capped at 10 s |
| `processing.dedup.same_source_title_threshold` | `int` | `85` | rapidfuzz score for same-source dedup |
| `processing.dedup.cross_source_title_threshold` | `int` | `95` | rapidfuzz score for cross-source dedup |
| `processing.dedup.lookback_minutes` | `int` | `60` | How far back DB title comparison looks |
| `alerts.urgency_levels.<name>.corroboration_required` | `int` | `1` | Per-level override for corroboration gate on phone calls |
| `alerts.acknowledgment.call_duration_threshold_seconds` | `int` | `15` | **Dead** — field still defined but read nowhere; the `if False:` block that referenced it was removed. Superseded by SMS-code confirmation. |
| `alerts.acknowledgment.cooldown_hours` | `int` | `6` | No re-alerts within this window after acknowledgment |
| `database.article_retention_days` | `int` | `30` | Articles older than this deleted each cycle |
| `database.event_retention_days` | `int` | `90` | Events older than this deleted each cycle |
| `sources.rss[*].priority` | `int` | `2` | Priority 1 = included in fast lane; 2+ = slow lane only |
| `sources.rss[*].keyword_bypass` | `bool` | `false` | If true, article skips Stage 4 (keyword filter) |
| `sources.telegram.channels[*].keyword_bypass` | `bool` | `false` | Same bypass for Telegram channels |
| `sources.gdelt.enabled` | `bool` | `false` | GDELT fetcher instantiated only when true; **disabled in production** (IP-throttled) |
| `sources.gdelt.lookback_minutes` | `int` | `60` | GDELT `TIMESPAN` window (the API rejects < ~30 min). Live config carries a stale `update_interval_minutes: 15` that is a no-op typo for this field |
| `alerts.push.enabled` | `bool` | `false` | Enables the additive Expo push channel |
| `alerts.push.tokens` | `list[str]` | `[]` | Expo push tokens to deliver to (live `config.yaml` omits the whole block → push off) |
| `testing.dry_run` | `bool` | `false` | Dispatcher logs intended actions; no Twilio calls made |

---

## 6.5 Corroboration & Event Grouping (`sentinel/classification/corroborator.py`)

Stage 6 groups military classifications (urgency ≥ 5) into `Event`s and decides independence. A new classification merges into an existing event only when **all** of these hold (`_find_matching_event`):

1. **Event-type compatibility** (`EVENT_COMPATIBILITY`) — e.g. `drone_attack` ↔ `airstrike`; `cyber_attack` only matches `cyber_attack`.
2. **Country compatibility** (`_countries_compatible`):
   - At/above the phone-call urgency threshold (9), a concrete-country intersection is **required** — a Poland-critical article whose country the classifier failed to extract (empty / `"unknown"`) spawns its OWN event/call; the no-signal relaxation is NOT applied at critical urgency.
   - Below the threshold, empty / `"unknown"` labels carry no location signal and don't block a merge, but two concrete-but-different country sets (e.g. PL vs RO) stay separate.
   - Countries are normalized (uppercased; blank / `"unknown"` dropped) when events merge.
3. **Critical-urgency safety guard** — a phone-call-eligible article is **never** absorbed into an event that already has `acknowledged_at` set (already alerted / in cooldown). It forces a NEW event and a NEW call, so a fresh critical escalation can't be silenced by an earlier event's cooldown.
4. **Sliding time window** — `corroboration_window_minutes` (live 360) measured from the event's `last_updated_at`, plus an absolute `corroboration_max_age_minutes` (live 2880) cap from `first_seen_at`.
5. **Summary similarity** — `summary_similarity_metric(result.summary_pl, event.summary_pl) ≥ summary_similarity_threshold` (live `token_set_ratio` @ 50).

**Source independence** (`_is_independent_source`): a new article counts toward `source_count` only if it's a different domain AND its normalized title is `< syndication_similarity_threshold` (90, `fuzz.ratio`) similar to every existing source title — caught across all source types to reject wire/syndication reuse.

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
| `--eval [PATH]` | Run classification eval against a YAML eval set (default: `testing.eval_set_file`); hits the live API; saves a JSON report to `data/eval/`; exits 0 only if all cases pass |
| `--test-alert [phone_call\|sms\|push]` | Fire a real alert with a synthetic event; bypasses fetch/classify/corroborate (argparse `choices=["phone_call", "sms", "push"]`, default `phone_call`). `phone_call`/`sms` go via Twilio; `push` goes via Expo (requires `alerts.push.enabled` + a token) |

The classifier **and** the alert/Twilio path are async, so the synchronous CLI/eval entry points bridge to them via `asyncio.run(...)`: `--test-headline` (`_run_test_headline`) runs one `classify`; `--test-file` (`_run_test_file`) runs **one** `asyncio.run` wrapping an inner loop over all headlines (not one event loop per headline); `--eval` (`_run_eval`) runs `asyncio.run(run_eval(...))`. `--test-alert` (`_run_test_alert`) drives the now-async `_execute_phone_call` / `_execute_sms` under `asyncio.run(...)` as well (see §9).

Config loading: `sentinel/config.py:load_config()`. Env vars substituted via `${VAR}` syntax. `.env` loaded via python-dotenv if available.

---

## 9. Known Quirks

- **Two urgency decision paths can disagree.** `Corroborator._determine_alert_status` uses `config.classification.corroboration_required` and writes `event.alert_status`; `AlertStateMachine._determine_action` re-decides from `config.alerts.urgency_levels` and ignores the stored value.
- **No DTMF in call TwiML.** Confirmation is via SMS 6-digit code reply, not `<Gather>`. `twilio_client.py:41`.
- **Call-duration acknowledgment removed; config field orphaned.** The old duration-based `if False:` block in `_handle_call_result` was deleted; `alerts.acknowledgment.call_duration_threshold_seconds` is still defined in config but now read nowhere.
- **Confirmation code stored as instance attribute, not reset between events.** `state_machine.py:368`, `state_machine.py:391` — stale-code risk if events overlap.
- **GDELT articles have empty `summary` always** (`gdelt.py:178`); Stage 4 keyword filter effectively scans GDELT title only.
- **Google News redirect URLs stored as-is**, not resolved to canonical. Same article surfaced by two queries dedupes only via fuzzy title match.
- **`TelegramFetcher` channel matching falls back to first channel if id mismatches** (`telegram.py:100-108`).
- **`BaseFetcher.is_enabled()` raises `NotImplementedError` but is NOT `@abstractmethod`.** Silent failure mode if a subclass forgets to override. All four current subclasses do override it; the silent-failure risk only applies to future fetcher additions.
- **Classifier daily token cost logged with hardcoded prices** `$0.80/M input, $4.00/M output` at UTC date rollover (`classifier.py:246-248`); not configurable.
- **The pipeline is fully async (classifier + alert path).** `Classifier` uses `anthropic.AsyncAnthropic`; `classify` / `classify_batch` / `aclose` are coroutines. `run_cycle` awaits `classify_batch` inside the cycle lock, and `SentinelPipeline.shutdown` awaits `classifier.aclose()` (in a `try/except` that logs failures) before `db.close()`. `classify_batch` is **deliberately sequential** — one awaited `classify` per article, no `asyncio.gather`/`Semaphore`/`TaskGroup` — because the event-loop unblocking comes from `await` alone; this preserves the Anthropic rate-limit profile and per-article error isolation. The alert path is now async too: `AlertDispatcher.dispatch` and `AlertStateMachine`'s alert-execution methods (`process_event`, `_execute_phone_call`, `_execute_sms`, the SMS/confirmation helpers, `check_pending_calls`, `_handle_call_result`) are `async def`; `time.sleep` poll/pause loops became `await asyncio.sleep`. The synchronous `TwilioClient` SDK is **not** rewritten — instead every Twilio HTTP touch point is offloaded at the call site with `await asyncio.to_thread(...)` (`make_alert_call`, `send_sms`, `get_call_status`, plus the two direct `messages.list` / `messages(sid).fetch` SDK calls wrapped in lambdas). **DB access stays on the event-loop thread** and is never placed inside an `asyncio.to_thread` callable (the shared `sqlite3` connection has no application-level lock). Dispatch is **sequential** (each event's `process_event` awaited before the next) and an in-flight alert holds the Phase 1 cycle lock for its whole duration — deliberate, to keep per-event confirmation state (`self._confirmation_code` / `self._confirmation_sms_sid`) on the shared instance from being clobbered and to avoid reintroducing alert-path races. `_run_test_alert` drives `_execute_phone_call` / `_execute_sms` under `asyncio.run(...)`. Six pure helpers (`_determine_action`, `_is_in_cooldown`, `_user_already_notified`, `_is_acknowledged`, `_last_alert_time`, `_update_alert_record`) stay synchronous.
- **Production `corroboration_required=1`** (single source triggers call). Code default is `2`. Check live `config/config.yaml` before assuming corroboration behavior.
- **`TelegramFetcher` lifecycle not in `BaseFetcher` contract.** `SentinelPipeline.startup()`/`shutdown()` use `hasattr(fetcher, "start")` duck-typing. Telegram `start()` failure is logged and skipped; other fetchers unaffected.
- **`keyword_bypass` sources skip Stage 4 entirely.** All their articles consume Haiku API quota.
- **Fast-lane jitter capped at `min(jitter_seconds, 10)`** regardless of config (`scheduler.py:464`). Slow-lane uses full `jitter_seconds`.
- **Fetcher health SMS fires exactly once at `failures == 10`** per fetcher (`scheduler.py:420`). Does not repeat.
- **Pipeline failure SMS fires exactly once at `consecutive_failures == 3`** (`scheduler.py:515`), not `>=`.

---

## 10. Dashboard Subsystem (`dashboard/`)

Separate from the monitoring runtime described above. Read-only Flask backend + React/Vite/TypeScript frontend over the production SQLite DB; runs locally only, never deployed. Full reference: [`SPEC.md`](../../SPEC.md).

### 10.1 Backend (Flask)

| File | Responsibility |
|---|---|
| `dashboard/cli.py` | argparse entry point (`--port`, `--db`, `--tunnel`, `--sync`); invoked via `python -m dashboard` |
| `dashboard/app.py` | Flask `create_app(db_path, fts_db_path, annotations_db_path, tunnel, dev_cors)`; stashes `SENTINEL_DB_PATH`/`SENTINEL_FTS_DB_PATH`/`ANNOTATIONS_DB_PATH`/`USE_TUNNEL` on `app.config`; registers `/api/*` blueprints; serves `dashboard/frontend/dist/` when built |
| `dashboard/db.py` | `DashboardDB` read-only access layer (`?mode=ro` URI). Two modes: local file (persistent SCP'd copy) and tunnel (SCP-fresh-fetch at startup). ATTACHes `sentinel_fts.db` as `fts` (local mode only) and `annotations.db` as `annotations` (both modes) when each file exists. SPEC_ALERT_GROUPING.md Phase 2: module-level constant `EVENT_ID_RETENTION_DAYS = 30` (with per-instance `event_id_retention_days` override), correlated-subquery `_EVENT_ID_SQL` injecting `event_id` into every article list/detail row, and `get_event_with_articles(event_id)` returning the spec's `{event, articles[], alert_records[]}` shape |
| `dashboard/sync.py` | `sync_db()` — SCPs production DB to `dashboard/data/sentinel.db`, builds FTS5 index in attached `sentinel_fts.db` |
| `dashboard/annotations.py` | Phase 4 — `AnnotationDB` write-capable layer over `dashboard/data/annotations.db`. Auto-creates the file + `annotations` table on first access; layered validation (`validate_label` / `validate_expected_urgency` rejects bool subclass); upsert via `INSERT ... ON CONFLICT(article_id) DO UPDATE` preserving `created_at`; `list()` opens a second short-lived SQLite connection that ATTACHes the sentinel DB read-only to enrich each row with `article_title` + `article_urgency_score`. Module-level `ALLOWED_LABELS = ("correct", "incorrect", "uncertain")` reused by the API layer |
| `dashboard/classifier_input.py` | Reconstructs the exact prompt the production classifier sent to Claude Haiku (kept in lockstep via drift-guard test) |
| `dashboard/api/_common.py` | `get_db()` opens a per-request `DashboardDB` from `app.config`; propagates `SENTINEL_DB_PATH`, `USE_TUNNEL`, `SENTINEL_FTS_DB_PATH`, `ANNOTATIONS_DB_PATH`, and (SPEC_ALERT_GROUPING.md Phase 2) `EVENT_ID_RETENTION_DAYS` |
| `dashboard/api/articles.py` | `GET /api/articles` (list/filter/sort/search/paginate; Phase 4 adds `has_annotation` + `annotation_label` filters; SPEC_ALERT_GROUPING.md Phase 2 adds an `event_id` field on every row), `GET /api/articles/<id>` (detail + classifier input + events + alert_records) |
| `dashboard/api/stats.py` | `GET /api/stats` — totals, per-day series, urgency/source/language/event-type distributions, pipeline funnel, plus Phase 4 `annotation_stats` |
| `dashboard/api/sync.py` | `POST /api/sync` (refused 409 in tunnel mode), `GET /api/sync/status` |
| `dashboard/api/annotations.py` | Phase 4 — `annotations_bp` blueprint. `POST /api/annotations` (upsert), `GET /api/annotations` (paginated list with `?label` filter and `?sort` whitelist), `GET /api/annotations/<article_id>` (404 on miss), `DELETE /api/annotations/<article_id>` (idempotent 204). Layered validation: API layer rejects invalid `label` / out-of-range `expected_urgency` with HTTP 400 + `{"error": ...}` before touching the DB |
| `dashboard/api/events.py` | SPEC_ALERT_GROUPING.md Phase 2 — `events_bp` blueprint. `GET /api/events/<event_id>` (read-only event detail; 404 with `{"error": "event not found"}` on unknown id; 405 on non-GET via Flask's automatic handler). Response shape: full event row + `articles[]` (each rendered via the same `_article_from_row` shape the article list returns, ordered by `published_at` ASC) + `alert_records[]` (ordered by `sent_at` ASC) |
| `dashboard/run-dashboard.sh` | Bash launcher mirroring `run.sh`; activates `.venv` then runs `python -m dashboard "$@"` |

Tunnel mode does **not** use SSH port-forwarding (SQLite is a file, not a network service). It SCPs the live DB to a temp path at `create_app()`, opens it read-only, and removes it on exit. Tunnel mode forces LIKE-only search (no FTS) and refuses `POST /api/sync` (409).

Multi-source filter: `GET /api/articles` accepts `source_name` as a repeated query parameter (e.g. `?source_name=PAP&source_name=TVN24`). `dashboard/api/articles.py` calls `request.args.getlist("source_name")`, trims whitespace, drops empty values, and passes `None | str | list[str]` to `dashboard/db.py:_build_filters`, which emits `source_name IN (?, ?, ...)` for the multi-value case. Single-value form preserved for backward compatibility.

`raw_metadata` is always returned as a `dict` from `dashboard/db.py:get_article_detail` — non-object JSON values (string, array, null) are coerced to `{}` so the frontend can render without runtime checks.

Every article-list row carries an `event_id` field (SPEC_ALERT_GROUPING.md Phase 2 — req 2.2) populated by `dashboard/db.py:_EVENT_ID_SQL`, a correlated scalar `LEFT JOIN` against `events` via `EXISTS (SELECT 1 FROM json_each(e.article_ids) je WHERE je.value = a.id)`. The scan is bounded to events whose `first_seen_at >= datetime('now', '-N days')` where N is the `EVENT_ID_RETENTION_DAYS` code constant (default 30) — overridable per-instance via the `DashboardDB(event_id_retention_days=...)` constructor or per-app via `app.config["EVENT_ID_RETENTION_DAYS"]` (propagated by `dashboard/api/_common.py:get_db()`). When multiple events match the same article the lowest `first_seen_at` event wins (`ORDER BY e.first_seen_at ASC LIMIT 1`); when no retained event matches the field is null. The same lookup is injected into `get_article_detail` so the article-detail page sees an event_id consistent with the list view. `dashboard/db.py:get_event_with_articles(event_id)` powers `GET /api/events/<id>` and returns the spec's normative `{event, articles[], alert_records[]}` shape, reusing `_list_select_columns()` so each nested article carries the same field set the article list returns (including its own `event_id`).

`dashboard/db.py:get_stats()` returns both `articles_per_day` and `classified_per_day` (added in Phase 3). Both series share the same 30-day calendar and are keyed by the article's `published_at` (not the classifier-run timestamp), so the overview `TimeSeriesChart` can render a point-aligned filtering-ratio comparison. Backfilled classifications for articles published outside the 30-day window appear in neither series — the two share the same filter so the displayed ratio is honest.

Data files (`dashboard/data/sentinel.db`, `dashboard/data/sentinel_fts.db`, `dashboard/data/annotations.db`) are dashboard-owned and separate from production. The annotations file is created on first POST so a fresh install needs no manual `mkdir` or `CREATE TABLE`.

#### Annotation system architecture (Phase 4)

- **Separate-file design.** Annotations live in `dashboard/data/annotations.db`, NOT the sentinel DB. A fresh production sync overwrites `sentinel.db` byte-for-byte, so co-locating annotations would lose every user label on every sync. Stable article-id UUIDs let the cross-DB JOIN remain correct across syncs.
- **Cross-DB ATTACH as the project pattern.** `DashboardDB._maybe_attach_annotations` opens the file with `ATTACH DATABASE ? AS annotations` on every per-request connection. This mirrors the existing FTS attach pattern but with one key difference: **FTS is intentionally skipped in tunnel mode** (the SCP'd temp copy has no co-located FTS index and any stale local FTS file would silently return wrong rows), whereas **annotations are attached in BOTH modes** because `annotations.db` is local + persistent and joins safely on the stable UUID.
- **Upsert preserving `created_at`.** `AnnotationDB.upsert()` uses `INSERT ... ON CONFLICT(article_id) DO UPDATE SET label=..., expected_urgency=..., notes=..., updated_at=...` (NOT `INSERT OR REPLACE`). Re-labelling keeps the original row `id` and `created_at`; only `updated_at` ticks forward. Matches the user's mental model ("I'm editing this annotation", not "starting over").
- **Layered validation.** `validate_label` + `validate_expected_urgency` are module-level helpers reused by both `dashboard/api/annotations.py` (API boundary — produces HTTP 400 + `{"error": ...}` before touching the DB) and `AnnotationDB.upsert` (DB boundary defence-in-depth). Booleans are explicitly rejected for `expected_urgency` even though `bool` is an `int` subclass.
- **Idempotent DELETE.** `DELETE /api/annotations/<id>` returns 204 even when no annotation exists (RFC 7231 §4.3.5 idempotency). The user-facing intent ("make sure no annotation here") is satisfied either way; the spec's "DELETE removes annotation, returns 204" wording is honoured.
- **Narrow per-article shape vs full Annotation record.** Spec req 4.5 makes the article-list `annotation` field deliberately narrow — `{label, expected_urgency, notes}` only (`dashboard/db.py:_annotation_from_row`). Frontend types codify this split with `ArticleAnnotation` (narrow) and `Annotation` (full, includes `id`/`created_at`/`updated_at`); the dedicated `GET /api/annotations/<id>` endpoint returns the full shape.
- **Graceful absent-file behaviour.** `DashboardDB._build_filters` checks `self._annotations_available` before referencing `ann.*` columns. When the file is missing (fresh install), `has_annotation=true` emits a `1=0` placeholder (empty result, pagination preserved); `has_annotation=false` emits `1=1` (matches everything); `annotation_label=...` emits `1=0`. Article rows simply lack the `annotation_label` column and `_annotation_from_row` returns None.
- **Stats deviation.** `dashboard/db.py:_annotation_stats` computes `average_urgency_deviation = AVG(ABS(c.urgency_score - ann.expected_urgency))` server-side via the ATTACHed annotations DB, filtered to rows where both columns are present. None when no such pair exists. Returned under `stats.annotation_stats` alongside `total` + zero-filled `by_label` counts.

### 10.2 Frontend (React/Vite/TypeScript at `dashboard/frontend/`)

Stack: React 18.3 + react-router-dom 6 + Vite 5.4 + TypeScript 5.5 (strict) + recharts 2.15 (Phase 3) + vitest 2 + @testing-library/react + jsdom.

| Path | Responsibility |
|---|---|
| `vite.config.ts` | Dev server on `:5173`; `/api/*` proxied to `http://localhost:5001` (Flask). Production build → `dist/`, served by Flask at `/` |
| `src/main.tsx` | React entry; mounts `BrowserRouter` with v7 future flags from `utils/routerFutureFlags.ts` |
| `src/App.tsx` | Root routes — `/` → `pages/OverviewPage` (Phase 3); `/articles` → `pages/ArticlesPage`; `/articles/:id` → `pages/ArticleDetailPage` (Phase 3); `/events/:id` → `pages/EventDetailPage` (SPEC_ALERT_GROUPING.md Phase 2). Persistent nav with `NavLink` to Overview + Articles |
| `src/types.ts` | TypeScript interfaces field-for-field mirror of Python API (`Article`, `Classification`, `EventRecord`, `AlertRecord`, `StatsResponse`, `SyncResult`, `SyncStatus`, `ArticleDetail`, `ArticleQueryParams`). `StatsResponse` carries both `articles_per_day` and `classified_per_day` (Phase 3) plus `annotation_stats` (Phase 4). Phase 4 adds `AnnotationLabel`, narrow `ArticleAnnotation` (per-article shape), full `Annotation` (incl. `id`/`created_at`/`updated_at`), `AnnotationListResponse`, `AnnotationPayload`, `AnnotationStats`. `ArticleQueryParams` gains `has_annotation` + `annotation_label`; `Article` gains `annotation: ArticleAnnotation \| null`. Enum-like unions widened with `\| string` to tolerate stale DB rows / backend drift; `event_type` is `string \| null`. SPEC_ALERT_GROUPING.md Phase 2 adds optional `event_id?: string \| null` to `Article` (req 2.6a — optional `?` for fixture back-compat; API always emits the field) and an `EventDetail` interface extending `EventRecord` with `articles: Article[]` (req 2.6b) |
| `src/api/client.ts` | Typed fetch client (`fetchArticles`, `fetchArticleDetail`, `fetchStats`, `triggerSync`, `fetchSyncStatus`, plus Phase 4 `fetchAnnotation`/`fetchAnnotations`/`saveAnnotation`/`deleteAnnotation`, plus SPEC_ALERT_GROUPING.md Phase 2 `fetchEvent(eventId)` resolving to `EventDetail`); `ApiError` carries `status`/`body`/`url`; `buildSearchParams` emits repeated params for array values |
| `src/hooks/useArticles.ts` | Data-fetching hook; `AbortController` + `requestIdRef` race guard; `refreshKey`-driven refetch; errors → toast |
| `src/hooks/useStats.ts` | Phase 3 — data-fetching hook for `GET /api/stats`. Same pattern as `useArticles` (`AbortController` + `requestIdRef` + `notify()` toast); one round-trip drives the whole overview |
| `src/hooks/useArticleDetail.ts` | Phase 3 — data-fetching hook for `GET /api/articles/:id`. Same pattern as `useStats`. Resets `data:null` on error since each id is a distinct resource |
| `src/hooks/useAnnotations.ts` | Phase 4 — `useAnnotation(articleId, initialAnnotation?)` hook for the annotation panel. Mirrors `useArticleDetail` (`AbortController` + `requestIdRef` + `notify()` toast); treats 404 as "no annotation yet" (not an error). Exposes `save()` and `remove()` mutators that update local state on success |
| `src/hooks/useEventDetail.ts` | SPEC_ALERT_GROUPING.md Phase 2 — data-fetching hook for `GET /api/events/:id`. Mirrors `useArticleDetail` (`AbortController` + `requestIdRef` race guard) but suppresses the toast on 404 so `EventDetailPage` can render its dedicated not-found UI without a duplicate banner |
| `src/hooks/useLocalStorage.ts` | Persistent state hook with optional validator; corrupted or wrong-shape values fall back to `initialValue` AND clear the bad key (validator wrapped in try/catch) |
| `src/pages/OverviewPage.tsx` | Phase 3 — landing route `/`. Composes `StatsCards`, `ViewToggle`, `PipelineFunnel`, `TimeSeriesChart`, `UrgencyHistogram`, `SourceBreakdown`. Reads URL `?view=analytics\|pipeline` (default `pipeline`). Owns the single `useStats()` call for the page |
| `src/pages/ArticlesPage.tsx` | Orchestrator — owns URL ↔ state mapping via `useSearchParams`; drives `useArticles`, parallel tab-count fetches, `fetchStats`; wires `SyncButton.refreshTick`; conditional sort param; broad clear-all |
| `src/pages/ArticleDetailPage.tsx` | Phase 3 — article detail at `/articles/:id`. Header (title, source link, dates, language/pipeline badges) + `ClassifierView` + `EventTimeline` + (Phase 4) `<AnnotationPanel articleId={data.id} />` below the timeline. Back link preserves filter/sort/page state via `location.state.from` |
| `src/pages/EventDetailPage.tsx` | SPEC_ALERT_GROUPING.md Phase 2 — event detail at `/events/:id`. Metadata header (id, type, urgency, affected_countries, aggressor, summary_pl, timestamps, source_count, alert_status badge), article list (ordered `published_at` ASC; each article title linked to `/articles/:id`), and alert timeline (ordered `sent_at` ASC; `message_body` truncates at 200 chars with per-row expand toggle). Back button uses `navigate(-1)` per spec 2.5d. Distinguishes 404 (`data-testid="event-detail-not-found"`) from generic errors (`data-testid="event-detail-error"`) |
| `src/components/ArticleTable.tsx` | Main table; lazy-fetches `ArticleDetail` on row expand for `raw_metadata`; per-row `AbortController`; sort headers with `aria-pressed` indicator (shown only when explicit sort active); `safeHref` scheme validation for `source_url`. Title cell wraps article title in a `<Link>` that passes `location.state.from = pathname+search` so the detail page can reconstruct the correct "Back to articles" URL (Phase 3). `renderCell` (Phase 4) handles the new `annotation` column key by rendering an `<AnnotationBadge>`. SPEC_ALERT_GROUPING.md Phase 2: `computeEventGroups()` does a single-pass render-time tagging that classifies each row as `first` / `continuation` / `standalone`. The first row of a same-event run shows a chevron + member-count indicator that is a `<Link to="/events/<id>">`; continuation rows get `.article-row-in-group` styling applying two independent visual cues (faded background + coloured left border) per spec 2.3b accessibility rule; standalone rows (null event_id OR not consecutive) are untouched per spec 2.3c |
| `src/components/ColumnPicker.tsx` | Popover checkbox list for column visibility; localStorage-persisted; Escape-key dismiss |
| `src/components/FilterBar.tsx` | Filter controls including `SourceMultiSelect` popover; URL state via `useSearchParams`; whitespace-trimmed values |
| `src/components/FilterTabs.tsx` | All / Classified / Unclassified tabs with per-tab counts |
| `src/components/SearchBar.tsx` | Search input with 300 ms debounce and clear (×) button |
| `src/components/Pagination.tsx` | Page navigation + page-size selector (25/50/100, localStorage-persisted, resets to page 1 on size change) |
| `src/components/SyncButton.tsx` | `POST /api/sync`; disabled in tunnel mode (tooltip explains); refreshes view via `refreshTick` callback |
| `src/components/Toast.tsx` | Toast notification context + tray; `notify(message, variant)` API; React-stable via `useCallback` |
| `src/components/StatsCards.tsx` | Phase 3 — four KPI cards: Total Articles (with 30-day avg), Total Classified (with %), Total Events (with article-reach), Total Alerts (with article-reach) |
| `src/components/ViewToggle.tsx` | Phase 3 — two-mode toggle (Pipeline / Analytics). Persists selection in `?view=` URL param via `setSearchParams` |
| `src/components/PipelineFunnel.tsx` | Phase 3 — 4-stage horizontal funnel (Collected → Classified → Events → Alerts). Bar list with width proportional to `stage/collected`. Each stage is a `<Link>` to filtered `/articles`. Implemented as a styled bar list (not recharts `FunnelChart`) so each stage is a real focusable anchor with screen-reader access — justification in the file header comment |
| `src/components/TimeSeriesChart.tsx` | Phase 3 — recharts `LineChart` of `articles_per_day` and `classified_per_day` (both keyed by publication date) over the last 30 days |
| `src/components/UrgencyHistogram.tsx` | Phase 3 — recharts `BarChart` of `urgency_distribution` (1-10). Bar fill colours come from `badges.urgencyColor` (1-4 gray / 5-6 yellow / 7-8 orange / 9-10 red) |
| `src/components/SourceBreakdown.tsx` | Phase 3 — recharts horizontal `BarChart` of top-15 sources by article count (sorted desc) + small language distribution chip row from `stats.language_distribution` |
| `src/components/ClassifierView.tsx` | Phase 3 — side-by-side input/output panes for a classified article + Raw JSON toggle. Renders a gray-background notice (`data-testid="classifier-view-unclassified"`) when the article was filtered out before classification |
| `src/components/EventTimeline.tsx` | Phase 3 — vertical timeline of events linked to an article + their alert records (emoji icons for phone/SMS/WhatsApp). Verbatim empty-state: "No events — article did not trigger event creation." |
| `src/components/AnnotationPanel.tsx` | Phase 4 — article-detail-page form. Three label buttons (Correct / Incorrect / Uncertain), urgency `number` input 1-10 with client-side validation, notes textarea. Submit POSTs via `useAnnotation.save`, shows an inline success indicator without navigating, and re-hydrates the form from server state. `noValidate` on the form so React (not the browser) owns the validation UX. Delete button only renders when an annotation exists and confirms via injectable `confirmDelete` (defaults to `window.confirm`) |
| `src/components/AnnotationBadge.tsx` | Phase 4 — coloured dot for the article table's annotation column. Green = correct, red = incorrect, yellow = uncertain. Renders an em dash placeholder when `annotation === null` so cells never collapse to whitespace. Uses inline `backgroundColor` (from `annotationBadge(label).color`) so the dot stays correct even if the project CSS is customised |
| `src/components/columns.ts` | Column metadata (key, label, default visibility, localStorage key, `isColumnKeyList` validator). Phase 4 adds `"annotation"` to `ColumnKey`, `ALL_COLUMNS` (label `"Note"`), and `DEFAULT_VISIBLE_COLUMNS` (rightmost) |
| `src/components/badges.ts` | `urgencyClass` + `urgencyTier` + `urgencyColor` (Phase 3) + `pipelineStatusBadge` helpers, plus Phase 4 `annotationBadge(label)` returning `{color, label, className}` for `AnnotationBadge` and inline rendering. `urgencyColor` returns the literal hex fill that the urgency histogram passes to recharts |
| `src/utils/safeHref.ts` | Validates URL scheme (http/https only) before rendering as href — blocks `javascript:` / `data:` XSS |
| `src/utils/routerFutureFlags.ts` | Shared v7 future flags (`v7_startTransition`, `v7_relativeSplatPath`) for `BrowserRouter` and test `MemoryRouter` rigs |
| `src/styles/index.css` | Global styles — table, badges, urgency colours, popovers, toasts, plus Phase 3 selectors (`.stats-cards`, `.pipeline-funnel`, `.urgency-histogram`, `.source-breakdown`, `.classifier-view`, `.event-timeline`, `.view-toggle`), Phase 4 selectors (`.annotation-badge`, `.annotation-panel`, `.annotation-panel-save`, `.annotation-panel-delete`, plus the three label-button states), and SPEC_ALERT_GROUPING.md Phase 2 selectors (`.article-row-in-group` continuation styling, `.event-detail-page` layout with metadata grid + article list + alert timeline + not-found / error states) |

### 10.3 Frontend Conventions

- **URL is the canonical state surface** for filters, search (`q`), `sort`, `order`, `page`, `tab`, and the overview view mode (`view`) — managed via `react-router-dom` `useSearchParams`. Bookmarkable and shareable.
- **localStorage** is used **only** for column visibility and `page_size` (user preferences, not filters).
- **Conditional sort**: the `sort` param is sent to the backend only when the user has explicitly clicked a column header (URL has `sort=...`). With no explicit sort, the backend default ordering applies — FTS rank when a search `q` is present, recency otherwise. This preserves Phase 1's FTS rank behaviour. The UI shows the directional indicator (▲/▼) only when explicit sort is active; the first click of an unsorted column sorts descending, subsequent clicks alternate.
- **Multi-source filter**: frontend repeats `?source_name=A&source_name=B` URL params; backend collapses with whitespace strip + empty drop into `None | str | list[str]` and emits a parameterized `IN (?, ?, ...)` clause. Single-value form (one source) preserved for backward compatibility.
- **Lazy `raw_metadata` fetch**: row-detail data is **not** included in `/api/articles` (list response stays lean over ~37K articles). On row expand, `ArticleTable` calls `fetchArticleDetail(id)` with a per-row `AbortController`; results cached in a `Map<articleId, DetailEntry>`. Errors surface inline within the expanded row (intentionally not via global toast — too noisy for per-row fetches).
- **Broad clear-all-filters**: resets tab, search, sort, order, page, and every `FilterBar` field. Only `page_size` is preserved (preference, not filter).
- **Global error surfacing**: all non-row-level API errors go through the global Toast tray (`useToasts().notify`); `notify` is memoized stable so dependent effects don't refire spuriously.
- **Data hooks pattern (Phase 2 + 3 + 4 + SPEC_ALERT_GROUPING.md Phase 2)**: `useArticles` / `useStats` / `useArticleDetail` / `useAnnotation` / `useEventDetail` all use the same `AbortController` + `requestIdRef` race guard + `notify()` toast surfacing for errors (req 2.9a). Previously-loaded payloads stay visible on transient failure (`useStats`); `useArticleDetail` resets to `data:null` on error because each id is a distinct resource. `useAnnotation` treats 404 as "no annotation yet" (not an error) — the spec separates absent and error states. `useEventDetail` suppresses the toast on 404 so `EventDetailPage` renders its dedicated not-found UI without a duplicate banner.
- **AbortController** is used consistently in `useArticles`, `useStats`, `useArticleDetail`, `useAnnotation`, `useEventDetail`, `ArticleTable.loadDetail`, and `ArticlesPage`'s stats/tab-count effects. Stale-response guards via `requestIdRef`.
- **Charts use recharts (project-wide).** The single explicit exception is `PipelineFunnel`, which is a styled horizontal-bar list (not recharts `FunnelChart`) so each stage is an individually clickable, keyboard-focusable, screen-reader-accessible `<Link>` to a filtered `/articles` view.
- **One `useStats()` call per page** (not per chart). All Phase 3 charts on the overview receive their data via props from the page-level hook — a single network round-trip drives the whole overview.
- **Centralized urgency colour mapping** (`components/badges.ts`): `urgencyClass` returns the CSS class for the article table; `urgencyColor` returns the literal hex fill for recharts SVG bars. Both use the same 1-4 / 5-6 / 7-8 / 9-10 thresholds so the histogram and the table stay visually in lockstep.
- **Centralised annotation colour mapping** (Phase 4, `components/badges.ts`): `annotationBadge(label)` returns `{color, label, className}` so both `AnnotationBadge` (table dot) and `AnnotationPanel` (selected-label highlight) read from one source of truth.
- **Back-link state preservation (Phase 3)**: pages link to detail via `<Link state={{from: pathname+search}}>`. The detail page reads `location.state.from` with a safe fallback to `/articles`. No global router state, no localStorage — purely router-state-driven. **Exception (SPEC_ALERT_GROUPING.md Phase 2)**: `EventDetailPage` uses `navigate(-1)` instead of a `location.state.from` link per spec 2.5d — entering from any context (article-table indicator, direct URL, browser tab) returns to wherever the user came from.
- **Render-time event grouping (SPEC_ALERT_GROUPING.md Phase 2, `ArticleTable.computeEventGroups`)**: visual grouping is a single-pass render-time tagging over the already-rendered article array — not a re-query or sort. This preserves the existing sort/pagination behaviour automatically: a non-default sort that interleaves event members simply produces standalone rows (no group indicator), without breaking the table.
- **`TimeSeriesChart` "classified" series is keyed by article publication date** (not classifier-run timestamp) so the chart shows an apples-to-apples filtering ratio. Backend extension in `dashboard/db.py:get_stats()` computes both series with the same 30-day cutoff.
- **`ClassifierView` has two distinct DOM trees + testids** — `data-testid="classifier-view"` for the side-by-side panes (classified articles); `data-testid="classifier-view-unclassified"` for the gray-background notice (unclassified articles). Tests can assert presence/absence cleanly.
- **`AnnotationPanel.noValidate`** — the form opts out of native HTML5 validation so React owns user-facing error UX. The `<input type="number" min={1} max={10}>` constraints would otherwise silently block submission on bad values with no visible feedback; `parseUrgency` runs first and surfaces a `data-testid="annotation-panel-local-error"` message.
- **XSS / scheme safety**: `source_url` is rendered as `<a href={...}>` only when the URL parses as `http`/`https`; otherwise rendered as plain text via `safeHref`. Article `id` is `encodeURIComponent`'d in router `<Link>`s (and in the annotation endpoint URLs).
- **SQL injection guard (backend)**: every dashboard query is parameterized, including the dynamic `IN` clause for multi-source filter (placeholders generated to match the value count). Annotation sort columns are whitelisted in `dashboard/annotations.py:_ALLOWED_SORT_COLUMNS` before being interpolated into ORDER BY.
- **Tunnel-mode surfacing**: `SyncButton` polls `/api/sync/status` and disables itself with an explanatory tooltip when `tunnel_mode: true`.

### 10.4 Known Frontend Limitations (Phase 3 + 4)

- **Production bundle size**: ~596 kB / ~172 kB gzipped — recharts pulls in d3 transitively. Vite emits a chunk-size warning but does not fail the build. The dashboard is desktop-only / local-only (per SPEC.md Non-Goals), so this is acceptable.
- **`SourceBreakdown` truncates to top-15**: production has 37 sources; the long tail is currently not surfaced. A "Show all sources" affordance is a candidate future enhancement.
- **`PipelineFunnel` "Collected" stage navigates to bare `/articles`** (no filter). The backend's `pipeline_status` values do not include `"collected"` — every article in the DB is collected by definition.
- **`classified_per_day` filters by `published_at`**, not `classified_at`. Backfilled classifications for articles published outside the 30-day window do not appear in either series; the two series share the same filter so the displayed ratio is honest.
- **Existing-user localStorage column state does not auto-include the new `annotation` column** (Phase 4). Spec req 4.4a is satisfied literally — the default-visible list now contains `annotation` — but users with a prior persisted column-visibility blob need one ColumnPicker toggle to surface it.
- **Tunnel-mode annotation-JOIN end-to-end coverage**: the code path is structurally identical to local mode and unit-covered for `_maybe_attach_annotations`, but no test instantiates a tunnel-mode `DashboardDB` to exercise the full integration.
- **FTS + annotation-filter compose** is covered only via the LIKE branch in tests; no test combines a built FTS index with `has_annotation` / `annotation_label`.

Status: Phase 1 (backend), Phase 2 (React frontend foundation), Phase 3 (analytics overview + article detail pages), Phase 4 (annotation system), SPEC_ALERT_GROUPING.md Phase 2 (article-list `event_id` + visual grouping + `/events/:id` detail page), and SPEC_ALERT_GROUPING.md Phase 3 (the `/sentinel-audit` skill now partitions classified articles into per-event blocks via SQL `json_each` over `events.article_ids` filtered by `e.last_updated_at`, with a flat "Standalone classified articles" section for articles outside any event) complete. Later SPEC.md phases are spec'd but not yet implemented.
