# Project Sentinel — Architecture Reference

Last verified: 2026-10-03 (deployed commit 6429124)

> Dense structured reference for LLM agents. Every claim is anchored to a file, class or function. Anchors use function names, not line numbers, because line numbers drift.
> Where values come from: `config/config.yaml` holds the live values (production `/etc/sentinel/config.yaml` is byte-identical to it). `sentinel/config.py` holds the code defaults. `config/config.example.yaml` is only a template. Full key list: [config-reference.md](../reference/config-reference.md). Narrative walkthrough: [pipeline.md](pipeline.md).

## Contents

- [1. Module Map](#1-module-map)
- [2. Data Models](#2-data-models)
- [3. Pipeline Stages](#3-pipeline-stages)
- [4. Dual-Lane Scheduler](#4-dual-lane-scheduler)
- [5. Alert Routing Logic](#5-alert-routing-logic)
- [6. Key Config Keys](#6-key-config-keys)
- [6.5 Incident Grouping and Corroboration](#65-incident-grouping-and-corroboration)
- [7. Database Schema](#7-database-schema)
- [8. Entry Points and CLI Flags](#8-entry-points-and-cli-flags)
- [9. Known Quirks](#9-known-quirks)
- [10. Dashboard Subsystem](#10-dashboard-subsystem)

---

## 1. Module Map

| File | Main Class / Function | Responsibility |
|---|---|---|
| `sentinel.py` | `main()` | CLI entry point, arg parsing; each mode runs under `asyncio.run(...)` |
| `run.sh` | — | Runs `sentinel.py` with `.venv/bin/python`, forwarding all args. If the venv is missing, it first creates it and runs `pip install -r requirements.txt`. It does not activate the venv. |
| `sentinel/config.py` | `SentinelConfig`, `load_config()` | Pydantic schema and code defaults; YAML load + `${ENV_VAR}` substitution. `ClassificationConfig` validation: with `provider: openai` the model must start with `gpt-` and `classification.policy` must be a complete version-2 policy. |
| `sentinel/models.py` | `Article`, `ClassificationResult`, `Event`, `AlertRecord`, `_normalize_title()` | All dataclasses; SQLite serialization via `to_dict()`/`from_row()` |
| `sentinel/scheduler.py` | `SentinelPipeline`, `SentinelScheduler` | Pipeline orchestrator (`run_cycle`) + APScheduler dual-lane wrapper; writes `health.json` |
| `sentinel/database.py` | `Database` | SQLite WAL access layer: table creation, additive migrations (`_migrate_schema`), classification queue, nestable `transaction()` (SAVEPOINT), CRUD, cleanup |
| `sentinel/diagnostic.py` | `DiagnosticData`, `DiagnosticArticle`, `generate_html()` | Data containers and renderer for the HTML diagnostic report |
| `sentinel/logging_setup.py` | `setup_logging()` | Rotating file + stderr handler config |
| `sentinel/utils/` | `datetime.py`, `html.py` | Package (formerly the single module `sentinel/utils.py`): `datetime.py` holds UTC-store / Warsaw-render helpers such as `format_warsaw`; `html.py` holds `strip_html` |
| `sentinel/fetchers/base.py` | `BaseFetcher` | Abstract base: `name: str`, `fetch() -> list[Article]` |
| `sentinel/fetchers/rss.py` | `RSSFetcher` | `feedparser` + `httpx`; conditional GET via in-memory `_etag_cache` / `_last_modified_cache` keyed by URL (sends `If-None-Match` / `If-Modified-Since`; 304 → `[]`). `fetch(max_priority=N)` |
| `sentinel/fetchers/gdelt.py` | `GDELTFetcher` | GDELT DOC 2.0 API; theme + `sourcecountry` filter, `TIMESPAN={lookback_minutes}min`, `maxrecords=250`. Instantiated only when `sources.gdelt.enabled` is true (see `config/config.yaml` for the live state). No CAMEO event-code or Goldstein filter exists. |
| `sentinel/fetchers/google_news.py` | `GoogleNewsFetcher` | Google News RSS per configured query; stores the `news.google.com` redirect link as `source_url` |
| `sentinel/fetchers/telegram.py` | `TelegramFetcher` | Telethon MTProto client; buffers messages; requires the `start()`/`stop()` lifecycle |
| `sentinel/processing/__init__.py` | `process_articles()` | Standalone normalize → dedup → keyword-filter helper. No module calls it; `run_cycle` runs the stages itself. |
| `sentinel/processing/normalizer.py` | `Normalizer` | Strips/coerces fields to the `Article` schema |
| `sentinel/processing/deduplicator.py` | `Deduplicator` | URL-hash exact match. Fuzzy rapidfuzz title match runs only when `classification.incident_memory.enabled` is false. |
| `sentinel/processing/keyword_filter.py` | `KeywordFilter` | Multilingual keyword match; `diagnose()` for diagnostic mode |
| `sentinel/processing/enricher.py` | `ArticleEnricher` | Two-gate content enrichment for articles with thin summaries: a free heuristic gate (summary ≈ title) and a cheap LLM vagueness gate, then the article body is fetched via `httpx`. The LLM gate uses `OpenAIProvider` (purpose `enrichment_quality`, counted in the budget ledger) when `provider: openai`, and the Anthropic client otherwise. `enrich_batch` is `async`. |
| `sentinel/classification/classifier.py` | `Classifier` | Calls the configured provider; there is no automatic fallback between providers. `provider: openai` (live): one `OpenAIProvider.request` with `policy.messages()` and `CLASSIFICATION_SCHEMA`, then `summary_language.ensure_polish`. `provider: anthropic` (code default; legacy / rollback only): `anthropic.AsyncAnthropic` with `SYSTEM_PROMPT` + `USER_PROMPT_TEMPLATE`. `classify` (one article; used live), `classify_batch` (sequential loop; legacy non-memory path only), `aclose`. |
| `sentinel/classification/openai_provider.py` | `OpenAIProvider`, `UsageLedger`, `StructuredReply`, `ClassificationError`, `BudgetExceeded`, `validate_json()` | OpenAI Responses API via `openai.AsyncOpenAI` (`max_retries=0`, `asyncio.timeout`, `store=False`, strict JSON-schema output). Before each request `UsageLedger.reserve` books a worst-case cost and refuses it if the month would exceed `classification.budget.monthly_usd`; `settle` then records the actual cost. Every failure (auth, quota, rate limit, timeout, refusal, invalid JSON, budget) raises `ClassificationError`. |
| `sentinel/classification/policy.py` | `system_prompt(policy)`, `messages()`, `prompt_hash()`, `FACT_SCHEMA` | Builds the versioned prompt (version 2, "clarified" policy) from `classification.policy`. The user message is JSON with `evaluation_time`, `article` and `remembered_incidents`. |
| `sentinel/classification/schema.py` | `RESPONSE_SCHEMA`, `CLASSIFICATION_SCHEMA` | Strict JSON schema of the model reply, including `incident_memory` and `facts` |
| `sentinel/classification/summary_language.py` | `ensure_polish()`, `is_polish()`, `GUARD_VERSION` | Polish-summary guard. A local `lingua` detector plus a Cyrillic check decide whether `summary_pl` is Polish. If not, one translation request (purpose `summary_translation`) runs; if that fails, `classification.summary_language.fallback_pl` is used. The guard never changes urgency or the incident decision. |
| `sentinel/classification/incident_memory.py` | `IncidentMemory` (`candidates`, `validate`), `MEMORY_INSTRUCTIONS` | Incident memory. `candidates()` returns up to `max_candidates` recent events (the newest event always, the rest ranked by `fuzz.WRatio`) as model context. `validate()` checks the model's incident decision. It makes no model calls. |
| `sentinel/classification/corroborator.py` | `Corroborator` | Groups classifications into `Event`s (memory match live, fuzzy match legacy), checks source independence, sets a provisional `alert_status`, and increments `notification_revision` on escalation |
| `sentinel/alerts/dispatcher.py` | `AlertDispatcher` | Drops repeated event ids, re-reads each event's persisted row, sorts by urgency, then awaits `process_event` per event or logs in dry run |
| `sentinel/alerts/state_machine.py` | `AlertStateMachine` | Urgency → action decision; per-channel, per-revision delivery dedup; async call/SMS/push execution; call polling |
| `sentinel/alerts/twilio_client.py` | `TwilioClient` | Twilio REST wrapper: `make_alert_call(phone, message_pl, event_id)` (TwiML `<Say>` only), `send_sms(phone, message, event_id)` (record status `sent`), `get_call_status(twilio_sid)`. Twilio errors are logged and the method returns `None`. |
| `sentinel/alerts/push_client.py` | `ExpoPushClient` | `send_push(title, body, event_id, data)` POSTs to `https://exp.host/--/api/v2/push/send` (optional `EXPO_ACCESS_TOKEN` bearer); returns an `AlertRecord` with `alert_type="push"`, status `sent`. Code default off (`PushConfig.enabled=False`); live `config/config.yaml` sets `enabled: true` with one token `${EXPO_PUSH_TOKEN}` (value in `/etc/sentinel/sentinel.env`). See [`mobile-app.md`](mobile-app.md). |
| `sentinel/eval/` | `harness.py`, `compare_models.py`, `openrouter_client.py`, `cached_runtime.py`, `direct_luna.py`, `separate_metrics.py`, `export_candidates.py`, `rescore_dimensions.py`, `reference_history.py`, `clarified_policy.py`, `incident_memory.py` | Offline, opt-in evaluation tooling. The monitoring runtime does not import it; `sentinel.py` imports `harness.py` only for `--eval`. |

---

## 2. Data Models

Source: `sentinel/models.py`.

### `Article`
Produced by: all fetchers. Consumed by: `Normalizer`, `Deduplicator`, `KeywordFilter`, `ArticleEnricher`, `IncidentMemory`, `Classifier`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | UUID4, auto-generated |
| `source_name` | `str` | Human label (e.g. `"PAP"`; Google News: `GoogleNews:<query>`) |
| `source_url` | `str` | URL as fetched (Google News keeps its redirect link) |
| `source_type` | `str` | `rss` \| `gdelt` \| `google_news` \| `telegram` |
| `title` | `str` | Raw headline |
| `summary` | `str` | Body excerpt; the enricher may replace it with the fetched body |
| `language` | `str` | ISO 639-1: `pl`, `en`, `uk`, `ru` |
| `published_at` | `datetime` | Source publication time |
| `fetched_at` | `datetime` | Time of fetch; the OpenAI prompt sends it as `evaluation_time` |
| `raw_metadata` | `dict` | Source-specific extras (JSON in DB); the enricher adds `enrichment` |
| `url_hash` | `str` | SHA-256 of `source_url`; computed in `__post_init__` |
| `title_normalized` | `str` | `_normalize_title`: NFKD, strip combining marks, delete every character outside `[a-zA-Z0-9\s]`, collapse whitespace, lowercase. Non-Latin letters are removed, so an all-Cyrillic (UA/RU) title becomes empty or digits only. Used by legacy fuzzy dedup and by the corroborator's syndication check (`_is_independent_source`). |

### `ClassificationResult`
Produced by: `Classifier.classify()` (live, one article at a time; `classify_batch` only on the legacy non-memory path). Validated by: `IncidentMemory.validate()`. Consumed by: `Corroborator.process_classifications()`.

| Field | Type | Notes |
|---|---|---|
| `article_id` | `str` | FK → `Article.id` |
| `is_military_event` | `bool` | Core yes/no from the model |
| `event_type` | `str` | Free string in the live schema (`schema.py`: `{"type": "string"}`). The legacy Anthropic prompt lists `invasion` \| `airstrike` \| `missile_strike` \| `border_crossing` \| `airspace_violation` \| `naval_blockade` \| `cyber_attack` \| `troop_movement` \| `artillery_shelling` \| `drone_attack` \| `other` \| `none`; legacy fuzzy grouping uses this vocabulary in `EVENT_COMPATIBILITY`. |
| `urgency_score` | `int` | 1–10 |
| `affected_countries` | `list[str]` | Country codes |
| `aggressor` | `str` | Free text from model |
| `is_new_event` | `bool` | True for new/uncertain incidents, false otherwise |
| `confidence` | `float` | 0.0–1.0 (classification confidence, separate from incident confidence) |
| `summary_pl` | `str` | Polish summary after the Polish-summary guard: original, translated, or `fallback_pl` |
| `classified_at` | `datetime` | Timestamp |
| `model_used` | `str` | `classification.model` (live `gpt-5.6-luna`) |
| `input_tokens` | `int` | API usage (classification + any translation request) |
| `output_tokens` | `int` | API usage |
| `incident_memory` | `dict` | Validated incident decision: `decision` (`new` \| `duplicate` \| `update` \| `escalation` \| `uncertain`), `matched_event_id`, `confidence`, `reason`, `candidate_ids`. A rejected decision becomes `uncertain` and keeps `model_decision` / `model_confidence`. A replayed article gets `article_replay: true`. `{}` on the legacy non-memory path. |
| `facts` | `dict` | OpenAI path only: `attack_countries`, `protection`, `status`, `evidence` (`policy.FACT_SCHEMA`). Stored for audit; grouping and routing do not read it. |
| `summary_processing` | `dict` | Output of `ensure_polish`: `version`, `original_summary`, `action` (`unchanged` \| `translated` \| `fallback`), repair request ids or error |
| `provider_used` | `str` | `openai` \| `anthropic`; default `legacy` for old rows |
| `prompt_version` | `str` | `clarified-v2:<prompt hash>:<GUARD_VERSION>` (OpenAI) or `legacy:<hash>`; default `legacy-unversioned` |
| `request_hash` | `str` | SHA-256 of the OpenAI request payload |
| `response_id` | `str` | OpenAI response id |
| `cached_input_tokens` | `int` | Cached input tokens (default 0) |
| `estimated_cost_usd` | `float` | Ledger cost of the classification + translation requests (default 0.0) |
| `id` | `str` | UUID4 primary key |

### `Event`
Produced by: `Corroborator.process_classifications()`. Consumed by: `AlertDispatcher.dispatch()`, `AlertStateMachine.process_event()`, `IncidentMemory.candidates()`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | UUID4 |
| `event_type` | `str` | From the first article; not changed on update |
| `urgency_score` | `int` | Live (memory mode): the first article's score, raised only on an `escalation` decision. Legacy: max across grouped articles. |
| `affected_countries` | `list[str]` | First article's list; on each update the union of concrete codes (uppercased, blank / `unknown` dropped, sorted) |
| `aggressor` | `str` | From the first article; not changed on update |
| `summary_pl` | `str` | First article's Polish summary; replaced only on an `escalation` decision (memory mode) |
| `first_seen_at` | `datetime` | `classified_at` of the first classification |
| `last_updated_at` | `datetime` | Processing time (`datetime.now(UTC)`) of the last create or update, not an article time |
| `source_count` | `int` | Count of independent sources |
| `article_ids` | `list[str]` | All contributing article IDs |
| `alert_status` | `str` | See the note below the table. |
| `acknowledged_at` | `datetime\|None` | Set when the operator replies to the confirmation SMS with the correct 6-digit code |
| `notification_revision` | `int` | Default 1. Incremented only when incident memory accepts an `escalation`. All delivery dedup keys on it (§5). |

`alert_status` values. `Corroborator._determine_alert_status` writes a provisional `phone_call` or `sms` (or `dry_run` in dry-run mode). `pending` is the column default; the corroborator never assigns it to a stored event, because events start at urgency ≥ 5. `AlertStateMachine` overwrites the value only on the call and SMS paths: `call_placed`, `retry_pending`, `acknowledged`, `sms_sent`. Push-only tiers and failed SMS sends never reach those writes, so the provisional `sms` stays stored. A call round whose calls all fail still ends with `retry_pending`. A query for `sms_sent` therefore misses push-only alerts. Historical rows may also contain `whatsapp_sent` from the removed WhatsApp channel. `expired` is read by `get_active_events` and `_update_event` but no code writes it.

### `AlertRecord`
Produced by: `AlertStateMachine._record_alert()`. Consumed by: `AlertStateMachine.process_event()` (`_channel_delivered`, `_has_new_delivered_revision`, pending-call guard) and `check_pending_calls()`.

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | FK → `Event.id` (`system` for system-health SMS, which are not stored) |
| `alert_type` | `str` | `phone_call` \| `sms` \| `push` (historical rows may contain `whatsapp`; `sms_update` is accepted as SMS for compatibility) |
| `twilio_sid` | `str` | Twilio call/message SID (push: Expo ticket id) |
| `status` | `str` | Calls: Twilio values `initiated`, `ringing`, `in-progress`, `completed`, `busy`, `no-answer`, `failed`, `canceled`. SMS and push: `sent`. `sent`, `delivered` and `acknowledged` count as successful delivery when read (`_SUCCESSFUL_DELIVERY_STATUSES`), but no runtime code writes `delivered` or `acknowledged` to an alert record; acknowledgment is stored on the event (`alert_status`, `acknowledged_at`). |
| `attempt_number` | `int` | Retry counter |
| `sent_at` | `datetime` | When the provider API was called |
| `message_body` | `str` | Full text of message/TTS script |
| `duration_seconds` | `int\|None` | Call duration (populated on poll) |
| `event_revision` | `int` | `Event.notification_revision` at send time, set by `_record_alert`; default 1 for old rows |

`Database.get_pending_call_records()` returns rows with `alert_type = 'phone_call'` and `status IN ('initiated', 'ringing')`.

---

## 3. Pipeline Stages

Source: `sentinel/scheduler.py:SentinelPipeline.run_cycle`. The whole cycle runs inside `self._cycle_lock`.

The stage numbers below are local to this document and follow the code blocks of `run_cycle`. [pipeline.md](pipeline.md) cuts the same cycle into nine differently numbered stages, so name the stage (for example "event grouping") rather than its number in cross-document references.

```
Stage 1 — await _fetch_all(fast_only) → list[Article]
          Calls fetcher.fetch() on each enabled BaseFetcher.
          fast_only=True: skips GDELT; RSSFetcher called with max_priority=1.
          A fetch exception is logged and counted per fetcher (§4).

Stage 2 — Normalizer.normalize_batch(list[Article]) → list[Article]
          Coerces fields, fills missing timestamps.

Stage 3 — one DB transaction (Database.transaction):
          a) Deduplicator.deduplicate_batch → unique articles, inserted into `articles`.
             URL-hash match (DB + within the batch). Fuzzy title match
             (same-source 85 / cross-source 95, processing.dedup.*) runs only
             when classification.incident_memory.enabled is false. Live
             (enabled) keeps same-headline articles from other URLs; incident
             memory handles them after classification.
          b) KeywordFilter.filter_batch → relevant articles. Multilingual keyword
             match (PL/EN/UA/RU). Skipped for keyword_bypass sources.
          c) Database.enqueue_classification(article) for each relevant article.

Stage 4 — Database.pending_classifications(classification.retry_batch_size)
          Reads queued articles whose next_attempt_at has passed, oldest
          fetched_at first. This includes articles left pending by earlier
          cycles, not only this cycle's articles.

Stage 5 — Classify and group.
          Live path (classification.incident_memory.enabled: true), one article
          at a time, so each stored result is memory for the next article:
            await enricher.enrich_batch([article])
            candidates = IncidentMemory.candidates(article)
            result = await Classifier.classify(article, incident_context=candidates)
              any exception in these three steps → Database.classification_failed(
              article_id, retry_delay_seconds, <exception class name>); the article
              stays in classification_queue and is retried after the delay.
            IncidentMemory.validate(result, candidates, article)
            one transaction: Corroborator.process_classifications([result]) +
              Database.classification_complete(article_id)
              exception → rollback, classification_failed(..., "grouping_failed").
          Legacy path (incident_memory.enabled: false):
            enrich_batch(all) → classify_batch(all) (sequential; per-article
            errors logged and skipped; a batch-level exception → []), then one
            transaction: process_classifications(all) + classification_complete
            per result. Articles without a result → classification_failed(...,
            "classification_failed").
          Then: events deduplicated by id (last snapshot wins); events whose
          alert_status is "pending" are dropped.

Stage 6 — await AlertDispatcher.dispatch(events)     [diagnostic=False only]
          Drops repeated ids, re-reads each persisted row, sorts by urgency
          desc, awaits AlertStateMachine.process_event() one event at a time
          (no asyncio.gather; per-event confirmation state lives on the shared
          state machine). With testing.dry_run it only logs each intended action.

Stage 7 — await AlertStateMachine.check_pending_calls()   [diagnostic=False only]
          Polls Twilio for phone_call records still initiated/ringing.
          Blocking Twilio HTTP calls run via asyncio.to_thread; DB access stays
          on the event-loop thread.

Stage 8 — Database.cleanup_old_records(article_days, event_days)
          Explicit DELETEs (§7). Articles still in classification_queue are kept.
```

---

## 4. Dual-Lane Scheduler

Source: `sentinel/scheduler.py:SentinelScheduler`.

| Lane | Interval | Jitter | Sources | APScheduler job ID |
|---|---|---|---|---|
| Fast | `scheduler.fast_interval_minutes` (code default 3 min) | `min(jitter_seconds, 10)` | Telegram + Google News + RSS priority ≤ 1 | `sentinel_fast_lane` |
| Slow (full) | `scheduler.interval_minutes` (code default 15 min) | `jitter_seconds` (code default 30 s) | All enabled fetchers (superset of the fast lane; GDELT only if `sources.gdelt.enabled`) | `sentinel_slow_lane` |

Both jobs: `max_instances=1`, `coalesce=True` (skips missed fires, never stacks).

- Health: `_update_health()` writes `health.json` next to the database (`<dirname(database.path)>/health.json`; production `/var/lib/sentinel/health.json`; `data/health.json` only with the code-default DB path). It includes `classification_status` from `Database.classification_health()` and reports unhealthy when any queued article has a failed attempt.
- Daily summary logged at UTC date rollover via `_maybe_log_daily_summary()`.
- Fetcher failure: one system-health SMS at exactly the 10th consecutive failure of a fetcher (`_check_fetcher_health`).
- Pipeline failure: one system-health SMS at exactly the 3rd consecutive cycle failure (`_check_pipeline_health`).
- System-health SMS go only through Twilio (`SentinelPipeline._send_system_sms`); there is no push fallback (see §9).

---

## 5. Alert Routing Logic

Source: `sentinel/alerts/state_machine.py:AlertStateMachine`.

Two decisions exist. Only the second one decides delivery.
1. `Corroborator._determine_alert_status` writes a provisional `Event.alert_status`: `phone_call` if urgency ≥ 9 and `source_count ≥ classification.corroboration_required`; `sms` if urgency ≥ 5; `dry_run` in dry-run mode. This label cannot block a call: an under-corroborated urgency-9 event still gets `sms` and is dispatched.
2. `AlertStateMachine._determine_action` makes the final channel choice from `alerts.urgency_levels` (sorted by `min_score` desc). The phone-call gate is `alerts.urgency_levels.critical.corroboration_required`.

Live, both corroboration keys are 1, so one source triggers a phone call today.

| urgency_score | source_count vs. `critical.corroboration_required` | action from `_determine_action` | provisional `Event.alert_status` |
|---|---|---|---|
| ≥ 9 (critical) | ≥ | `phone_call` (plus additive push) | `phone_call` |
| ≥ 9 (critical) | < | `sms` | `sms` |
| ≥ 7 (high) | any | `high.channel` → `sms` / `push` / `both` | `sms` |
| ≥ 5 (medium) | any | `medium.channel` → `sms` / `push` / `both` | `sms` |
| ≥ 1 (low) | any | `log_only` | no event (urgency < 5 creates none) |

For the SMS-action tiers (5–8), `_determine_action` returns the level's `channel` (code default `both`). Live `config/config.yaml` sets `channel: push` for `high` and `medium`: SMS is switched off on purpose, so tiers 5–8 are push-only. `channel` is ignored on `critical` and `low`.

`process_event(event)` steps:
1. Re-read the persisted event row and its `AlertRecord`s.
2. Acknowledged event (an `acknowledged` record or `acknowledged_at` set): return, unless `_has_new_delivered_revision()` is true, which means some earlier revision was delivered and `notification_revision` has since advanced (an incident-memory escalation). Then send the update SMS (`_send_update_sms`) and an update push for that revision, each only if its channel has not yet delivered it. No cooldown applies.
3. Pending-call guard: return if any `phone_call` record has status `initiated` or `ringing`.
4. `action = _determine_action(event)`; `send_push = action in (push, both, phone_call)`; `send_sms = action in (sms, both)`.
5. Per-channel dedup: `_channel_delivered(alerts, channel, revision)` is true only when a record of that channel has a successful status (`sent`, `delivered`, `acknowledged`) and `event_revision == event.notification_revision`. A failed attempt stays retryable; a new revision can notify again.
6. Push is sent first (`_maybe_send_push` → `ExpoPushClient.send_push` via `asyncio.to_thread`), so it reaches the phone before the Twilio work. It is a no-op when `alerts.push.enabled` is false or `tokens` is empty. A push-only tier with push disabled therefore delivers nothing.
7. `phone_call` → `_execute_phone_call`: confirmation SMS with a 6-digit code, then up to `alerts.acknowledgment.max_call_retries` calls in one round (live 1), polling for the SMS reply between calls. A correct reply → `acknowledged`. Round exhausted → `retry_pending`. A previous call younger than `acknowledgment.retry_interval_minutes` skips the round.
8. Otherwise `send_sms` → `_execute_sms` → `sms_sent` on success.

The 9–10 push is additive: it does not replace the call. A normal push does not bypass silent mode or Do Not Disturb until Apple Critical Alerts (a separate entitlement) is active, so the call stays the primary wake-up. Each push is stored as its own `AlertRecord` with `alert_type="push"`. See [`mobile-app.md`](mobile-app.md).

Known state (owner decision): the Twilio account is deliberately left unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 ("account not active"). `TwilioClient` logs the error and returns `None`. Today a 9–10 event therefore delivers the additive push, its call attempts fail, and the event ends the round as `retry_pending`. Phone calls stay configured and work again when the owner recharges the account. Runbook: [server-runbook.md → Troubleshooting](../how-to/server-runbook.md#troubleshooting).

---

## 6. Key Config Keys

Code default = `sentinel/config.py`. Live = `config/config.yaml` as of 2026-10-03; re-check that file before relying on a live value. Full list: [config-reference.md](../reference/config-reference.md).

| YAML path | Type | Code default | Live | Effect |
|---|---|---|---|---|
| `classification.provider` | `str` | `anthropic` | `openai` | Selects the classifier backend. `anthropic` is the legacy / rollback path. |
| `classification.model` | `str` | `claude-haiku-4-5-20251001` | `gpt-5.6-luna` | Model ID for the selected provider |
| `classification.policy` | `dict` | `{}` | version-2 policy | Source of the OpenAI system prompt (`policy.system_prompt`); required when provider is `openai` |
| `classification.incident_memory.enabled` | `bool` | `false` | `true` | Switches to per-article classification with incident memory, memory-based grouping, and URL-only dedup |
| `classification.incident_memory.min_confidence` / `critical_min_confidence` / `lookback_hours` | `float`/`int` | `0.85` / `0.9` / `168` | same | Memory-match gates (§6.5) |
| `classification.budget.monthly_usd` | `float` | `10` (max 50) | `30` | Monthly cap enforced by `UsageLedger.reserve`; reaching it pauses classification |
| `classification.budget.ledger_path` | `str` | `data/model-usage.db` | `/var/lib/sentinel/model-usage.db` | SQLite ledger file (table `model_usage`) |
| `classification.budget.*_per_million`, `cache_write_multiplier` | `float` | see `ModelBudgetConfig` | see config | Prices used for reservations and settled cost |
| `classification.retry_delay_seconds` | `int` | `300` | `300` | Delay before a failed article is retried from `classification_queue` |
| `classification.retry_batch_size` | `int` | `100` | `100` | Max queued articles classified per cycle |
| `classification.corroboration_required` | `int` | `2` | `1` | Only sets the provisional `Event.alert_status` label; does not gate the call |
| `classification.corroboration_window_minutes` | `int` | `360` | `360` | Legacy path only. Sliding window measured from the event's `last_updated_at`. |
| `classification.corroboration_max_age_minutes` | `int` | `2880` | `2880` | Legacy path only. Absolute cap from `first_seen_at`; `0` disables. |
| `classification.summary_similarity_metric` | `str` | `token_set_ratio` | `token_set_ratio` | Legacy path only. `rapidfuzz.fuzz` function; validated against `{ratio, partial_ratio, token_sort_ratio, token_set_ratio, WRatio, QRatio}`. |
| `classification.summary_similarity_threshold` | `int` | `50` | `50` | Legacy path only. Score (0–100) needed to merge into an event. |
| `classification.syndication_similarity_threshold` | `int` | `90` | `90` | Title similarity (`fuzz.ratio` over `title_normalized`) at/above which an article does not count as independent (both paths) |
| `scheduler.fast_interval_minutes` / `interval_minutes` / `jitter_seconds` | `int` | `3` / `15` / `30` | same | Lane cadence and jitter (fast lane capped at 10 s) |
| `processing.dedup.same_source_title_threshold` / `cross_source_title_threshold` / `lookback_minutes` | `int` | `85` / `95` / `60` | same | Legacy fuzzy title dedup only |
| `alerts.urgency_levels.critical.corroboration_required` | `int` | `1` | `1` | The actual phone-call gate: one source triggers a call today |
| `alerts.urgency_levels.{high,medium}.channel` | `str` | `both` | `push` | Delivery channel for tiers 5–8 (`sms`, `push`, `both`). Live: SMS off by owner decision, tiers 5–8 push-only. |
| `alerts.urgency_levels.*.retry_attempts`, `.fallback`, `.retry_interval_minutes` | — | `0` / `None` / `5` | critical: `3` / `sms` / `5` | Parsed but read by no code |
| `alerts.acknowledgment.max_call_retries` | `int` | `3` | `1` | Calls per round in `_execute_phone_call` |
| `alerts.acknowledgment.retry_interval_minutes` | `int` | `5` | `5` | Minimum gap before a new call round for the same event |
| `alerts.acknowledgment.cooldown_hours` | `int` | `6` | `6` | Parsed but read by no code; no cooldown is enforced |
| `alerts.acknowledgment.call_duration_threshold_seconds` | `int` | `15` | `15` | Parsed but read by no code; superseded by SMS-code confirmation |
| `alerts.push.enabled` | `bool` | `false` | `true` | Enables the Expo push channel (tiers 5–8 per `channel`, additive on 9–10) |
| `alerts.push.tokens` | `list[str]` | `[]` | `["${EXPO_PUSH_TOKEN}"]` | Expo push tokens; the value comes from `/etc/sentinel/sentinel.env` |
| `database.article_retention_days` / `event_retention_days` | `int` | `30` / `90` | same | Retention for `cleanup_old_records` |
| `sources.rss[*].priority` | `int` | `2` | per source | Priority 1 = fast lane; 2+ = slow lane only |
| `sources.rss[*].keyword_bypass`, `sources.telegram.channels[*].keyword_bypass` | `bool` | `false` | per source | Article skips the keyword filter |
| `sources.gdelt.enabled` | `bool` | `true` | `false` | GDELT fetcher instantiated only when true; omitting the key turns GDELT on |
| `sources.gdelt.lookback_minutes` | `int` | `60` | see config | GDELT `TIMESPAN` window (the API rejects < ~30 min) |
| `testing.dry_run` | `bool` | `false` | `false` | Dispatcher logs intended actions instead of sending event alerts |

---

## 6.5 Incident Grouping and Corroboration

Source: `sentinel/classification/corroborator.py:Corroborator.process_classifications`.

Order of checks per classification:
1. Replay (memory mode): if the article id is already in some event's `article_ids`, the result is stored as `duplicate` with `article_replay: true` and that event is returned unchanged. The revision does not advance.
2. Event gate: only `is_military_event` with `urgency_score ≥ 5` (`_MIN_EVENT_URGENCY`) can create or join an event. Other results are only stored.
3. Match: `_find_memory_match` when `incident_memory.enabled` (live), else `_find_matching_event` (legacy). No match → `_create_event`.
4. Join: `_is_independent_source` decides whether `source_count` grows, then `_update_event`.

### Live path: `_find_memory_match`

The classifier receives the candidates from `IncidentMemory.candidates()` and returns an incident decision. `IncidentMemory.validate()` accepts a `duplicate` / `update` / `escalation` decision only when `matched_event_id` is one of the supplied candidate ids and the confidence is at least `min_confidence` (`critical_min_confidence` when urgency ≥ the phone-call threshold). Explicit conflicting dates or weekdays in the source text turn the decision into `new`. Any invalid decision becomes `uncertain`.

`_find_memory_match` then merges into the matched event only when all of these hold:
- the decision is `duplicate`, `update` or `escalation` and `matched_event_id` is in `candidate_ids`;
- confidence passes the same threshold;
- countries are compatible (`_countries_compatible`, below);
- the event's `last_updated_at` is at most `incident_memory.lookback_hours` before `classified_at`.

A failed country or age guard turns the decision into `uncertain` and creates a new event. A critical article (urgency ≥ phone-call threshold) that matches a non-critical event is forced to `escalation`, so a low-severity memory cannot silence the first critical report. `new` and `uncertain` decisions always create a new event.

Effect of a merge in memory mode (`_update_event`): only `escalation` raises `urgency_score`, replaces `summary_pl` and increments `notification_revision`. `duplicate` and `update` add the article (and possibly a source) but change neither urgency nor summary. Lifecycle statuses `acknowledged`, `retry_pending`, `call_placed` and `expired` are kept; other statuses are recomputed.

### Legacy path: `_find_matching_event` (incident memory disabled)

A classification merges into an active event only when all of these hold:
1. Event-type compatibility (`EVENT_COMPATIBILITY`), e.g. `drone_attack` ↔ `airstrike`; `cyber_attack` matches only `cyber_attack`.
2. Country compatibility (`_countries_compatible`).
3. Critical-urgency guard: a phone-call-eligible article is never absorbed into an event that has `acknowledged_at` set.
4. Sliding window: `corroboration_window_minutes` from the event's `last_updated_at`, plus the `corroboration_max_age_minutes` cap from `first_seen_at`.
5. Summary similarity: `summary_similarity_metric(result.summary_pl, event.summary_pl) ≥ summary_similarity_threshold`.

On a legacy merge, `urgency_score` becomes the max and `alert_status` is always recomputed.

### Shared rules

Country compatibility (`_countries_compatible`), both paths:
- At or above the phone-call threshold (lowest `min_score` with `action: phone_call`, fallback 9), a concrete-country intersection is required. A critical article without a concrete country spawns its own event.
- Below the threshold, empty or `unknown` labels do not block a merge, but two concrete-but-different sets (e.g. PL vs RO) stay separate.
- Countries are normalized (uppercased; blank / `unknown` dropped) when events merge.

Source independence (`_is_independent_source`): a new article counts toward `source_count` only if its domain differs from every existing article's domain and its `title_normalized` is below `syndication_similarity_threshold` (`fuzz.ratio`) against each of them. Google News articles all have the domain `news.google.com` (redirect links), so two Google News articles never count as independent of each other.

---

## 7. Database Schema

Source: `sentinel/database.py:Database._create_tables` and `_migrate_schema`.

| Table | Key Fields | Indexes | Retention |
|---|---|---|---|
| `articles` | `id` PK, `url_hash`, `title_normalized`, `source_type`, `fetched_at` | `url_hash`, `fetched_at`, `title_normalized` | `database.article_retention_days`; articles still queued are kept |
| `classifications` | `id` PK, `article_id` FK, `is_military_event`, `urgency_score`, `classified_at`, `incident_memory` | `article_id`, `urgency_score` | Deleted together with their old articles |
| `classification_queue` | `article_id` PK/FK → `articles.id`, `attempts`, `next_attempt_at`, `last_error` | (PK) | Row deleted by `classification_complete`; failures bump `attempts` and push `next_attempt_at` |
| `events` | `id` PK, `alert_status`, `first_seen_at`, `last_updated_at`, `source_count`, `article_ids` (JSON), `notification_revision` | `alert_status`, `first_seen_at`, `last_updated_at` | `database.event_retention_days` (by `first_seen_at`) |
| `alert_records` | `id` PK, `event_id` FK, `alert_type`, `twilio_sid`, `status`, `attempt_number`, `event_revision` | `event_id` | Deleted together with their old events |

- Additive migration columns (`_migrate_schema`, for databases created before incident memory): `classifications.facts`, `summary_processing`, `provider_used`, `prompt_version`, `request_hash`, `response_id`, `cached_input_tokens`, `estimated_cost_usd`, `incident_memory`; `events.notification_revision`; `alert_records.event_revision`. `classification_queue` is also created there.
- Retention is done by explicit `DELETE` statements in `cleanup_old_records`, not by foreign-key cascades.
- SQLite WAL mode; `check_same_thread=False` (single process; DB access stays on the event-loop thread).
- Separate ledger database: `UsageLedger` keeps table `model_usage` (`id`, `month`, `model`, `purpose`, `request_hash`, `reserved_usd`, `charged_usd`, `status` `reserved`/`settled`, token counts, `response_id`, `created_at`) in the file named by `classification.budget.ledger_path` (production `/var/lib/sentinel/model-usage.db`). A reservation that never settles keeps its full reserved amount.

---

## 8. Entry Points and CLI Flags

Source: `sentinel.py`. Full reference: [cli.md](../reference/cli.md).

| Flag | Effect |
|---|---|
| _(no flags)_ | Start the continuous dual-lane scheduler |
| `--once` | Run one full-lane cycle, then exit |
| `--dry-run` | Sets `testing.dry_run=True`. No event alerts are sent (no call, SMS or push). Classification still calls the paid model, `check_pending_calls` still runs, and system-health SMS are not suppressed. |
| `--config PATH` | Load config from `PATH` (default: `config/config.yaml`) |
| `--log-level LEVEL` | Override config log level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `--health` | Print `<dirname(database.path)>/health.json` and exit |
| `--diagnostic` | One cycle with dry run forced, then `<dirname(database.path)>/diagnostic.html`. Skips dispatch, but still makes paid classifier calls and writes to the configured database. |
| `--test-headline "TEXT"` | Feed one headline through the classifier (paid call); print the result |
| `--test-file FILE` | Feed a YAML file of headlines through the classifier; print results |
| `--eval [PATH]` | Run the classification eval (default: `testing.eval_set_file`); hits the live API; saves a JSON report to `data/eval/`; exits 0 only if all cases pass |
| `--test-alert [phone_call\|sms\|push]` | Fire a real alert for a synthetic urgency-10 event. Inserts a synthetic article and event into `database.path`, then calls `_execute_phone_call`, `_execute_sms` or `_maybe_send_push` directly (default `phone_call`). `push` requires `alerts.push.enabled` and a token. |

The classifier and the alert path are async, so the synchronous CLI entry points bridge with `asyncio.run(...)`: `--test-headline` runs one `classify`; `--test-file` runs one `asyncio.run` around a loop over all headlines; `--eval` runs `asyncio.run(run_eval(...))`; `--test-alert` runs the chosen alert coroutine.

Config loading: `sentinel/config.py:load_config()`. Env vars substituted via `${VAR}` syntax. `.env` loaded via python-dotenv if available.

---

## 9. Known Quirks

- Two urgency decisions exist. `Corroborator._determine_alert_status` writes a provisional label from `classification.corroboration_required`; `AlertStateMachine._determine_action` decides delivery from `alerts.urgency_levels` and ignores the stored label. Only `critical.corroboration_required` gates the call (live 1).
- Provisional `alert_status` persists for push-only tiers. Push delivery never updates `alert_status`, so a 5–8 event delivered only by push keeps `sms`. Use `alert_records` (`alert_type='push'`) to see what was delivered.
- `retry_pending` events are re-called only when a new article joins them. `run_cycle` dispatches only events returned by the corroborator in that cycle; no code reloads `retry_pending` or `call_placed` events from the DB. Without a new article, an unacknowledged critical event gets exactly one call round (live `max_call_retries: 1`), despite the "Never stops until acknowledged" docstring of `_execute_phone_call`. See TODO.md (retry of unacknowledged critical events).
- Known state (owner decision): the Twilio account is unfunded, so all calls and SMS currently fail with HTTP 401 and return `None` (§5). Phone calls stay configured and return when the account is recharged. System-health SMS (§4) are Twilio-only with no push fallback, so they are not delivered today. See [server-runbook.md → Troubleshooting](../how-to/server-runbook.md#troubleshooting).
- No DTMF in call TwiML. `TwilioClient.make_alert_call` sends `<Say>` only; confirmation is an SMS reply with the 6-digit code.
- Dead config fields: `acknowledgment.call_duration_threshold_seconds`, `acknowledgment.cooldown_hours`, `alerts.language`, and per-level `retry_attempts` / `fallback` / `retry_interval_minutes` are parsed but read nowhere. See TODO.md (dead alert config keys).
- Confirmation code stored as an instance attribute, not reset between events. `_send_confirmation_sms` sets `self._confirmation_code` and `self._confirmation_sms_sid`; stale-code risk if events overlap.
- GDELT articles always have an empty `summary` (`GDELTFetcher` sets `summary=""`), so the keyword filter scans the GDELT title only.
- Google News redirect URLs are stored as-is, not resolved. Live (memory mode) has no fuzzy title dedup, so the same story under a different redirect URL reaches the classifier and incident memory must recognise it. All Google News articles share one domain, so they never corroborate each other (§6.5).
- `title_normalized` drops all non-Latin letters. All-Cyrillic titles normalize to an empty string, so two such titles score 100 in `fuzz.ratio` and count as syndicated (not independent). See TODO.md (Cyrillic title normalization).
- `TelegramFetcher` channel matching falls back to the first channel if the id does not match (`TelegramFetcher` message handler).
- `BaseFetcher.is_enabled()` raises `NotImplementedError` but is not `@abstractmethod`. All four current subclasses override it; the risk applies only to future fetchers.
- Cost tracking. Live (OpenAI): every request reserves a worst-case cost in `UsageLedger` (BEGIN IMMEDIATE) and settles the actual cost from configurable `classification.budget` prices; the per-row cost is stored in `classifications.estimated_cost_usd`. Reaching `budget.monthly_usd` raises `BudgetExceeded`: articles stay in `classification_queue`, are retried after `retry_delay_seconds`, and health turns unhealthy. The daily log line then reports token counts only. Legacy (Anthropic) only: `Classifier._log_daily_summary` logs an estimate with hardcoded per-million prices.
- Enrichment and translation also cost money. On the OpenAI path the enricher's vagueness check (`enrichment_quality`) and the Polish-summary repair (`summary_translation`) are separate ledger-tracked requests.
- The pipeline is async end to end. Live: `run_cycle` awaits `enricher.enrich_batch([article])` and `classifier.classify` once per article (incident memory), and groups each result in its own transaction. `OpenAIProvider` uses `openai.AsyncOpenAI` with `max_retries=0` and an `asyncio.timeout`; there is no automatic retry or provider fallback, and a failed article waits in the queue. Legacy: `classify_batch` awaits one `classify` per article over `anthropic.AsyncAnthropic` (one retry after 5 s in `_call_api`). `SentinelPipeline.shutdown` awaits `classifier.aclose()` (errors logged) and `enricher.aclose()` before `db.close()`.
- Alert path concurrency. `AlertDispatcher.dispatch` and the alert methods of `AlertStateMachine` (`process_event`, `_execute_phone_call`, `_execute_sms`, the SMS/confirmation helpers, `_maybe_send_push`, `check_pending_calls`, `_handle_call_result`) are `async def`. Blocking provider calls run through `await asyncio.to_thread(...)`: `make_alert_call`, `send_sms`, `get_call_status`, `ExpoPushClient.send_push`, and the two direct `messages.list` / `messages(sid).fetch` SDK calls. Exception: `SentinelPipeline._send_system_sms` calls `twilio_client.send_sms` synchronously on the event loop. DB access stays on the event-loop thread and never runs inside `asyncio.to_thread` (the shared `sqlite3` connection has no lock). Dispatch is sequential and holds the cycle lock, so per-event confirmation state on the shared instance is not clobbered. Synchronous helpers: `_determine_action`, `_channel_delivered`, `_has_new_delivered_revision`, `_is_acknowledged`, `_record_alert`, `_update_alert_record`. `_run_test_alert` drives `_execute_phone_call`, `_execute_sms` or `_maybe_send_push` under `asyncio.run(...)`.
- `TelegramFetcher` lifecycle is not in the `BaseFetcher` contract. `SentinelPipeline.startup()`/`shutdown()` use `hasattr(fetcher, "start")` duck-typing. A Telegram `start()` failure is logged and skipped; other fetchers are unaffected.
- `keyword_bypass` sources skip the keyword filter entirely. All their articles are classified by the live model and count against `classification.budget.monthly_usd`.
- Fast-lane jitter is capped at `min(jitter_seconds, 10)` regardless of config (`SentinelScheduler.start`). The slow lane uses the full `jitter_seconds`.
- The fetcher-health SMS fires exactly once, at `failures == 10` per fetcher (`_check_fetcher_health`). It does not repeat.
- The pipeline-failure SMS fires exactly once, at `consecutive_failures == 3` (`_check_pipeline_health`), not `>=`.

---

## 10. Dashboard Subsystem

Source: `dashboard/`. Only the rows for `classifier_input.py`, `types.ts` and `EventTimeline.tsx` were re-verified on 2026-10-03; the rest of this section was not re-checked in that pass.

Separate from the monitoring runtime described above. Read-only Flask backend + React/Vite/TypeScript frontend over the production SQLite DB; runs locally only, never deployed. Full reference: [`SPEC.md`](../../SPEC.md).

### 10.1 Backend (Flask)

| File | Responsibility |
|---|---|
| `dashboard/cli.py` | argparse entry point (`--port`, `--db`, `--tunnel`, `--sync`); invoked via `python -m dashboard` |
| `dashboard/app.py` | Flask `create_app(db_path, fts_db_path, annotations_db_path, tunnel, dev_cors)`; stashes `SENTINEL_DB_PATH`/`SENTINEL_FTS_DB_PATH`/`ANNOTATIONS_DB_PATH`/`USE_TUNNEL` on `app.config`; registers `/api/*` blueprints; serves `dashboard/frontend/dist/` when built |
| `dashboard/db.py` | `DashboardDB` read-only access layer (`?mode=ro` URI). Two modes: local file (persistent SCP'd copy) and tunnel (SCP-fresh-fetch at startup). ATTACHes `sentinel_fts.db` as `fts` (local mode only) and `annotations.db` as `annotations` (both modes) when each file exists. SPEC_ALERT_GROUPING.md Phase 2: module-level constant `EVENT_ID_RETENTION_DAYS = 30` (with per-instance `event_id_retention_days` override), correlated-subquery `_EVENT_ID_SQL` injecting `event_id` into every article list/detail row, and `get_event_with_articles(event_id)` returning the spec's `{event, articles[], alert_records[]}` shape |
| `dashboard/sync.py` | `sync_db()` — SCPs production DB to `dashboard/data/sentinel.db`, builds FTS5 index in attached `sentinel_fts.db` |
| `dashboard/annotations.py` | Phase 4 — `AnnotationDB` write-capable layer over `dashboard/data/annotations.db`. Auto-creates the file + `annotations` table on first access; layered validation (`validate_label` / `validate_expected_urgency` rejects bool subclass); upsert via `INSERT ... ON CONFLICT(article_id) DO UPDATE` preserving `created_at`; `list()` opens a second short-lived SQLite connection that ATTACHes the sentinel DB read-only to enrich each row with `article_title` + `article_urgency_score`. Module-level `ALLOWED_LABELS = ("correct", "incorrect", "uncertain")` reused by the API layer |
| `dashboard/classifier_input.py` | Reconstructs the legacy Anthropic/Haiku user-prompt block (`USER_PROMPT_TEMPLATE` / `_build_user_prompt`; drift-guard test). It does not match the live OpenAI payload (`policy.messages()`: policy system prompt + JSON user message with `evaluation_time` and `remembered_incidents`), so for `provider_used='openai'` rows the dashboard shows an input the live model never saw. See TODO.md (dashboard classifier input for OpenAI rows). |
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
| `src/types.ts` | TypeScript interfaces field-for-field mirror of Python API (`Article`, `Classification`, `EventRecord`, `AlertRecord`, `StatsResponse`, `SyncResult`, `SyncStatus`, `ArticleDetail`, `ArticleQueryParams`). `StatsResponse` carries both `articles_per_day` and `classified_per_day` (Phase 3) plus `annotation_stats` (Phase 4). Phase 4 adds `AnnotationLabel`, narrow `ArticleAnnotation` (per-article shape), full `Annotation` (incl. `id`/`created_at`/`updated_at`), `AnnotationListResponse`, `AnnotationPayload`, `AnnotationStats`. `ArticleQueryParams` gains `has_annotation` + `annotation_label`; `Article` gains `annotation: ArticleAnnotation \| null`. Some enum-like unions are widened with `\| string` to tolerate stale DB rows / backend drift; `event_type` is `string \| null`. `AlertRecord.alert_type` is not widened: it is `"sms" \| "phone_call" \| "whatsapp"` with no `push` variant, although push is the main live alert type. SPEC_ALERT_GROUPING.md Phase 2 adds optional `event_id?: string \| null` to `Article` (req 2.6a — optional `?` for fixture back-compat; API always emits the field) and an `EventDetail` interface extending `EventRecord` with `articles: Article[]` (req 2.6b) |
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
| `src/components/EventTimeline.tsx` | Phase 3 — vertical timeline of events linked to an article + their alert records (emoji icons for phone/SMS/WhatsApp; `push` has no icon or label, so push records render with the generic "•" fallback and the raw string `push`). Verbatim empty-state: "No events — article did not trigger event creation." |
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
