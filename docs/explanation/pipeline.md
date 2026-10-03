> **What this document is:** A plain-language walkthrough of how Project Sentinel moves from raw media sources to an alert on your phone. Read this when you want to understand what the system is doing at any given stage, or when you need to reason about why an alert did or did not fire.

---

# Pipeline Reference

Last verified: 2026-10-03 (deployed commit 6429124)

The stage numbers in this document are local to it. [architecture.md](architecture.md) Section 3 cuts the same `run_cycle` into eight differently numbered stages, so name the stage (for example "event grouping") rather than its number in cross-document references.

## Contents

- [Schedule](#schedule)
- [Stage 1: Fetching](#stage-1-fetching)
- [Stage 2: Normalization](#stage-2-normalization)
- [Stage 3: Deduplication](#stage-3-deduplication)
- [Stage 4: Keyword Filtering](#stage-4-keyword-filtering)
- [Stage 5: Classification Queue and Model Budget](#stage-5-classification-queue-and-model-budget)
- [Stage 6: Summary Enrichment](#stage-6-summary-enrichment)
- [Stage 7: AI Classification](#stage-7-ai-classification)
- [Stage 8: Grouping into Events (Incident Memory)](#stage-8-grouping-into-events-incident-memory)
- [Stage 9: Alerts](#stage-9-alerts)
- [Storage](#storage)

Project Sentinel processes incoming media in nine stages. Each stage has one job: fetch raw content, clean it, drop exact duplicates, filter for relevance, queue the survivors for classification, enrich vague summaries, classify each article with an AI model, group the results into real-world incidents ("Events"), and finally alert you. The sections below follow the order in which data flows, as orchestrated by `SentinelPipeline.run_cycle` in `sentinel/scheduler.py`.

Numbers, thresholds, model names and on/off switches live in `config/config.yaml` (the live file; the server copy is identical). This page names the config key; [config-reference.md](../reference/config-reference.md) gives the values and code defaults.

## Schedule

The system runs continuously on two overlapping schedules. The fast lane runs every `scheduler.fast_interval_minutes` and covers Telegram channels, Google News, and priority-1 RSS sources. The slow lane runs every `scheduler.interval_minutes` and covers all enabled sources (GDELT would belong only here, but it is disabled in production; see the GDELT section below). Every slow-lane cycle is a superset of a fast-lane cycle. A lock makes sure two cycles never run at the same time.

| Lane | Jitter applied | Reference |
|------|---------------|-----------|
| Fast | `min(scheduler.jitter_seconds, 10)`, capped at 10 seconds whatever the config says | `SentinelScheduler.start` in `sentinel/scheduler.py` |
| Slow | Full `scheduler.jitter_seconds`, no cap | `SentinelScheduler.start` |

---

## Stage 1: Fetching

The system collects articles from four distinct source types. Each type is handled independently, so a failure in one does not interrupt the others.

### RSS Feeds

RSS sources are standard news feeds fetched from configured URLs. Each source carries a priority tag from 1 (highest urgency) to 3 (background). The fast lane only fetches priority-1 sources (`max_priority=1`) to keep cycle time short. The slow lane fetches all RSS sources regardless of priority.

The fetcher handles the common failure modes cleanly: a 304 Not Modified response is treated as a no-op and skipped without error; 429 rate-limit responses are logged and the source is skipped for that cycle; responses that appear to be an HTML block rather than XML (body under 2,000 bytes) are recognized as WAF bot-detection pages and discarded; malformed XML is caught and logged without crashing the pipeline.

### Google News

The system runs keyword searches against the Google News RSS API. The queries are listed at `sources.google_news.queries` in `config/config.yaml` and cover English, Polish and Ukrainian. Every query is scoped to the past hour. Example queries: "military attack Poland", "atak wojskowy Polska", "військовий напад Польща".

PAP (the Polish Press Agency) blocks automated fetching via WAF, so it is not fetched as a direct RSS source. Instead, a dedicated `site:pap.pl` query in Google News captures PAP articles indirectly.

### GDELT

GDELT (Global Database of Events, Language, and Tone) is a global news index that covers sources in any language. The system queries the GDELT DOC 2.0 API over a lookback window of `sources.gdelt.lookback_minutes` (the API rejects windows shorter than about 30 minutes), filtered to military-relevant topic codes: ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, and TAX_FNCACT_MILITARY, plus a `sourcecountry` filter. Up to 250 articles are returned per call. GDELT articles ship with an empty summary (`GDELTFetcher` in `sentinel/fetchers/gdelt.py`), so the keyword filter scans only the title. The article language comes from GDELT's own `language` field, mapped to a two-letter code by `GDELT_LANGUAGE_MAP` (English when unknown). The pipeline has no language detection of its own.

GDELT is currently disabled in production (`sources.gdelt.enabled: false`) because the API IP-throttles us with HTTP 429 down to roughly a 20% success rate. The fetcher is only instantiated when enabled, so although the slow lane would include GDELT, in production it does not run at all. (The live config also carries a stale `update_interval_minutes` key, which is a no-op; the real field is `lookback_minutes`.)

### Telegram

The Telegram fetcher is push-based and uses the `telethon` library (MTProto, user-account auth; not a bot, not `pyrogram`). `start()` registers a `telethon.events.NewMessage` handler on the configured channels, and messages accumulate in an in-memory buffer as they arrive. `fetch()` drains and clears that buffer each cycle (`TelegramFetcher.fetch` in `sentinel/fetchers/telegram.py`). The channels are listed at `sources.telegram.channels` in `config/config.yaml`; all of them are keyword-bypass sources, so they skip Stage 4 and go straight to the classification queue.

Known defect: the fetcher currently labels every Telegram message with the first configured channel's name, language and URL, so all channels look like one source. See "Telegram fetcher mislabels every channel" in [TODO.md](../../TODO.md).

---

## Stage 2: Normalization

Before any analysis, each article is cleaned into a consistent format.

HTML tags and entities are stripped from both the title and summary. Titles are capped at 500 characters; summaries at 1,000. If a summary is empty, the title is used in its place. Tracking parameters are removed from URLs (utm_* parameters, fbclid, gclid, and similar), and URL fragments are dropped so that the same article reached via different tracking links resolves to a single canonical URL. Timestamps that lack a timezone are assumed to be UTC. Timestamps that appear to be in the future are capped to the current time. Language codes are standardized; for example, "english" becomes "en" and "polish" becomes "pl".

---

## Stage 3: Deduplication

Which checks run depends on `classification.incident_memory.enabled`. Production has incident memory switched on, so only the two URL checks run there.

1. Same-batch URL check. Within a single fetch cycle, if two articles share an identical normalized URL, the second one is dropped in memory, before any database access.

2. Database URL check. The normalized URL is hashed and compared against all URLs stored in the database from previous cycles. If there is a match, the article has already been processed and is dropped.

3. Fuzzy title matching (only when incident memory is off). Titles from the past `processing.dedup.lookback_minutes` are compared with the incoming title using Levenshtein similarity. A match at or above `processing.dedup.cross_source_title_threshold` across different sources is treated as wire-service syndication and dropped; a match at or above `processing.dedup.same_source_title_threshold` within the same source is treated as a re-publish and dropped.

With incident memory on, step 3 is skipped on purpose (`Deduplicator._check_duplicate` in `sentinel/processing/deduplicator.py`). A near-identical headline at a different URL can be an independent confirmation or a new attack, so it goes on to classification, and incident memory decides in Stage 8 whether it is the same incident.

Articles that clear the checks are inserted into the `articles` table.

---

## Stage 4: Keyword Filtering

Before spending AI budget on classification, articles are screened for military relevance using a keyword filter. Two categories of source bypass this stage entirely and go straight to the classification queue: RSS feeds carrying `keyword_bypass: true` (the specialist defence-media feeds Defence24 and Defence24 EN) and all Telegram channels. These sources are considered high signal-to-noise by design.

For all other sources, the filter works as follows:

1. The article's title and summary are concatenated and lowercased.
2. The keyword set is chosen by the article's language. An article in a language that has no keyword set falls back to the English set.
3. Matching is language-aware. For Slavic languages (Polish, Ukrainian, Russian), plain substring matching is used because word inflection causes endings to vary; for example, "inwazja", "inwazji", and "inwazją" all need to match. For English and other languages, word-boundary matching is used to prevent false matches inside longer words.
4. Critical keywords are checked first. These are terms that by themselves signal a serious event: examples include "invasion", "missile strike", "Article 5", "inwazja", and "atak militarny".
5. High-severity keywords are checked next: terms like "drone", "jets scrambled", "airspace violation", "Shahed", and "sabotage".
6. Exclude keywords are checked last, and only if no critical keyword was already matched. This prevents a term like "drill" from blocking an article that also contains "nuclear drill", since the critical match takes precedence. A non-English article is checked against its own exclude list plus the English one.
7. An article passes if it contains any critical keyword, or if it contains a high-severity keyword with no exclude keyword match.

The keyword lists live at `monitoring.keywords` and `monitoring.exclude_keywords` in `config/config.yaml` (English, Polish, Ukrainian and Russian sets; only English and Polish have exclude lists). Articles that fail this filter are silently dropped (`KeywordFilter` in `sentinel/processing/keyword_filter.py`).

---

## Stage 5: Classification Queue and Model Budget

Articles that pass the keyword filter are not classified straight away. They are written to the `classification_queue` table in the same database transaction as the deduplication step, so an article is never lost between "seen" and "classified".

Each cycle then takes up to `classification.retry_batch_size` queued articles whose retry time has come, oldest first. This batch includes articles that failed in earlier cycles.

- If classification or event grouping fails for an article, it stays in the queue and is retried after `classification.retry_delay_seconds`. Its attempt counter goes up.
- An article leaves the queue only after its classification has been stored and grouped successfully.
- While any queued article has a failed attempt, the health snapshot reports `classification_status.degraded: true` and `is_healthy: false` (see [Storage](#storage)).

Every OpenAI request first reserves a worst-case cost against a persistent monthly spending ledger (`UsageLedger` in `sentinel/classification/openai_provider.py`). The ledger file is set by `classification.budget.ledger_path`, and the monthly cap by `classification.budget.monthly_usd`. If a request would push the month over the cap, the request is not sent (`BudgetExceeded`), and the article stays pending until the next month or until the cap is raised. Three kinds of request count against this budget: classification, the enrichment vagueness check (Stage 6), and the summary translation repair (Stage 7).

---

## Stage 6: Summary Enrichment

Before classification, articles whose summary adds little beyond the title are enriched by `ArticleEnricher.enrich_batch` (`sentinel/processing/enricher.py`). With incident memory on, as in production, this runs once per article inside the classification loop.

1. A free heuristic gate flags articles where the summary is essentially the title. This is common for Google News and GDELT.
2. Every other article goes through a small LLM check that flags vague or clickbait titles. On the live OpenAI path this is a budgeted OpenAI request (`purpose="enrichment_quality"`). The Anthropic version of this check is part of the legacy path.
3. For each flagged article the page is fetched over HTTP. Its `og:description`, or else page text capped at 500 characters, replaces the article summary.

No articles are dropped here. If enrichment raises an error, for example because the budget is exhausted, the article stays in the queue for a later retry.

---

## Stage 7: AI Classification

Each article is classified on its own. The provider and model are set by `classification.provider` and `classification.model` in `config/config.yaml`. Production uses `provider: openai`, which sends the request through `sentinel/classification/openai_provider.py` (OpenAI Responses API, strict JSON schema, reasoning effort from `classification.reasoning_effort`). The Anthropic Haiku path is kept only as a rollback option; see [Old behavior](#old-behavior-anthropic-haiku-classifier) below.

### What the model receives

The system prompt comes from `system_prompt` in `sentinel/classification/policy.py` (policy version 2). It is built from `classification.policy` in the config: the monitored countries and the score band for each kind of situation (`classification.policy.ranges`). The user message holds the article (title, summary, source, language, publication time) and up to `classification.incident_memory.max_candidates` remembered incidents for Stage 8.

### Score bands (policy v2)

The prompt tells the model to establish facts first and then pick a score inside the matching band. The main rules, with band names from `classification.policy.ranges`:

- An official resident air-raid, shelter or evacuation order in a monitored country scores in `official_warning` (9–10), even before any impact is confirmed.
- A confirmed hostile impact, invasion or offensive weapon over monitored territory scores in `active_attack` (9–10).
- Precautionary measures such as fighter scrambles or airport closures score in `precaution` (5–6). Under the `near_border_strike: awareness` setting, a confirmed strike inside Ukraine very close to Poland also scores in that band.
- Fighting that affects only Ukraine or Russia scores in `routine` (1–3). An explicit new capability or deployment that threatens the monitored countries scores in `capability_escalation` (5–6).
- Nuclear activity near monitored borders and direct new threats from Russian or Belarusian leaders score 7–8. Political reactions, resolved incidents and unclear locations score low.

Known defect: shelter orders that concern Ukraine only have been scored 9 with an empty country list, and each one attempts a phone call. See "Ukraine-only shelter orders scored urgency 9 attempt a phone call" in [TODO.md](../../TODO.md).

### What the model returns

The response must match `CLASSIFICATION_SCHEMA` in `sentinel/classification/schema.py`:

- `is_military_event`: whether the article reports a military incident, threat or protective response.
- `event_type` and `aggressor`: free-text labels (no fixed list).
- `urgency_score` (1–10): the most important output; it drives alerting.
- `affected_countries`: monitored countries with a concrete local incident or protective response.
- `confidence` (0–1): the model's confidence in its assessment.
- `summary_pl`: one or two sentences in Polish. This text appears in the push, the phone call and any SMS.
- `facts`: attack countries, protection level, status (active, resolved, historical, unclear) and short verbatim evidence.
- `incident_memory` and `is_new_event`: the model's decision on whether this is a known incident (used in Stage 8).

Classification confidence is not threshold-gated. Every result is stored whatever its confidence. Only the separate incident-memory confidence is checked against a threshold (Stage 8).

### Polish summary guard

The model's `summary_pl` passes through `ensure_polish` in `sentinel/classification/summary_language.py` before it is used.

1. The summary is accepted if it contains no Cyrillic letters and the language detector identifies it as Polish. The detector only chooses among `classification.summary_language.detector_languages`.
2. Otherwise one translation request repairs it. This request is budgeted and limited by `repair_max_tokens` and `repair_timeout_seconds` under `classification.summary_language`.
3. If the repair also fails, the summary is replaced by the fixed text in `classification.summary_language.fallback_pl` ("Polskie podsumowanie jest chwilowo niedostępne…"). That text can then appear in a push or a call. The urgency score and the incident decision are kept unchanged.

An empty summary is treated as a failed classification, so the article stays in the queue. What the guard did is stored with the classification in `summary_processing`.

### Old behavior: Anthropic Haiku classifier

When `classification.provider` is `anthropic` (the code default in `sentinel/config.py`), `Classifier` in `sentinel/classification/classifier.py` calls Claude Haiku with the older `SYSTEM_PROMPT` in that file. That prompt asks for a fixed list of event types and aggressors limited to RU, BY, unknown or none, scores Ukraine-only attacks 1–3 (5 for a capability escalation), and treats Russian "special military operation" wording as an attack. None of this applies in production. The path exists for rollback only.

---

## Stage 8: Grouping into Events (Incident Memory)

The corroborator (`Corroborator.process_classifications` in `sentinel/classification/corroborator.py`) groups classification results into Events. Each Event stands for one real-world incident. Production runs with `classification.incident_memory.enabled: true`, so grouping follows the model's own decision about incident identity. The older fuzzy matcher is described under [Old behavior](#old-behavior-fuzzy-event-matching).

### How an article is matched

1. Replay guard. If the article is already attached to an Event, it is recorded as a duplicate of that Event and nothing else changes.
2. Only results with `is_military_event` true and urgency 5 or higher can create or join an Event. Lower results are stored and go no further.
3. Candidate retrieval. Before classification, `IncidentMemory.candidates` in `sentinel/classification/incident_memory.py` loads recent Events (last updated within `incident_memory.lookback_hours`, at most `incident_memory.candidate_pool_size`). It always keeps the most recently updated Event and adds the best text matches, up to `incident_memory.max_candidates` in total. These candidates go to the model with the article.
4. The model's decision. The model answers `new`, `duplicate`, `update`, `escalation` or `uncertain`, with the ID of the matched candidate and a confidence value.
5. Validation (`IncidentMemory.validate`). A match is accepted only if the ID is one of the supplied candidates and the confidence reaches `incident_memory.min_confidence`, or `incident_memory.critical_min_confidence` when the article is at phone-call urgency. If the article and the candidate name explicit dates or weekdays that do not overlap, the decision is forced to `new`. An invalid answer becomes `uncertain`.
6. Safety guards in the corroborator (`_find_memory_match`). The countries must be compatible (see below), and the Event must have been updated within `incident_memory.lookback_hours`. Otherwise the decision becomes `uncertain`.
7. A `new` or `uncertain` result always creates a new Event.

Country compatibility (`_countries_compatible`): at or above the phone-call threshold, the article and the Event must share a concrete country. Below it, an empty or "unknown" country list does not block a match, but two different concrete countries (for example PL and RO) never match. Because of the critical rule, one incident with differing or missing country labels can split into several Events, and each gets its own call. See "Urgency-9 event fragmentation" in [TODO.md](../../TODO.md).

### What a match changes

- The article is attached to the Event. The source count rises only if the source is independent (see below).
- Only an `escalation` raises the Event's urgency, replaces its Polish summary and increases its `notification_revision`. A `duplicate` or `update` changes none of these, so it sends no new notification.
- If the first critical report (phone-call urgency) matches a non-critical Event, the decision is forced to `escalation`, so it cannot be silenced as a duplicate.
- An Event already in a call or acknowledgement state (`acknowledged`, `retry_pending`, `call_placed`, `expired`) keeps that state.

Acknowledged Events: in incident-memory mode there is no guard that keeps critical articles out of an acknowledged Event. A critical article that the model calls a `duplicate` or `update` of an acknowledged Event, with enough confidence, joins that Event without a new call. A model `new` decision still creates a new Event and a new call. An `escalation` sends an update push (and update SMS), not a call. The former invariant ("a critical article never joins an acknowledged Event") holds only on the legacy path. The owner sign-off on this change is open; see "Owner sign-off: acknowledged-event guard is gone in incident-memory mode" in [TODO.md](../../TODO.md).

### Independent sources

A classification counts as a new independent source only if it comes from a different domain than every article already in the Event, and its title is less than `classification.syndication_similarity_threshold` similar (`rapidfuzz.fuzz.ratio`) to each of their titles. The second check stops wire-service syndication from counting as independent confirmation.

### Alert level

The alert action is decided by `AlertStateMachine._determine_action` in `sentinel/alerts/state_machine.py`, from the tiers in `alerts.urgency_levels`:

| Condition (evaluated in order) | Action | Config key |
|--------------------------------|--------|-----------|
| urgency ≥ `critical.min_score` and source count ≥ `critical.corroboration_required` | Phone call + confirmation SMS + additive push | `alerts.urgency_levels.critical.corroboration_required` |
| urgency ≥ `critical.min_score`, fewer sources | SMS only (fallback, no push) | same key |
| urgency ≥ `high.min_score` | the tier's `channel` (`sms`, `push` or `both`) | `alerts.urgency_levels.high.channel` |
| urgency ≥ `medium.min_score` | the tier's `channel` | `alerts.urgency_levels.medium.channel` |
| lower | log only, no alert | |

One source triggers a phone call today. The live critical tier has `corroboration_required: 1`, and every Event has at least one source, so the SMS fallback row cannot be reached under the live config. Whether to require two sources is an open owner decision; see "Owner decision: corroboration for phone calls" in [TODO.md](../../TODO.md).

The corroborator also writes a provisional `alert_status` label (`_determine_alert_status`). It reads a different key, `classification.corroboration_required`, and does not decide whether a call is placed.

### Old behavior: fuzzy event matching

When `classification.incident_memory.enabled` is false, `_find_matching_event` matches a classification to an active Event only if all of these hold: compatible event types (`EVENT_COMPATIBILITY`), compatible countries (same rule as above), recent activity within `classification.corroboration_window_minutes` of the Event's last update, an Event younger than `classification.corroboration_max_age_minutes`, and Polish summaries at least `classification.summary_similarity_threshold` similar by `classification.summary_similarity_metric`. On this path a critical article is never absorbed into an acknowledged Event; it creates a new Event and a new call. On each match the Event's urgency becomes the higher of the two scores. None of this runs in production.

---

## Stage 9: Alerts

Known state: the owner has left the Twilio account unfunded on purpose. Since 2026-09-21 every Twilio call and SMS fails with HTTP 401, and Expo push is the only channel that reaches the phone. Phone calls stay configured and return when the owner recharges the account. This is not an outage; see the Troubleshooting section of the [server runbook](../how-to/server-runbook.md#troubleshooting).

The dispatcher (`AlertDispatcher.dispatch` in `sentinel/alerts/dispatcher.py`) handles the Events from this cycle's grouping step, highest urgency first, one at a time. For each Event, `AlertStateMachine.process_event` reloads the stored Event and decides what to send.

### Routing by tier

- Urgency 5–8. `_determine_action` returns the tier's `channel`. A `push` tier sends a push only, a `both` tier sends an SMS and a push, and an `sms` tier sends an SMS only. In production both `alerts.urgency_levels.high.channel` and `alerts.urgency_levels.medium.channel` are `push`, so urgency 5–8 is push-only by owner decision. The code default for `channel` is `both`.
- Urgency 9–10. The phone call and its confirmation SMS run, and an Expo push fires in addition. The tier `channel` is ignored here. A normal push does not break through silent mode or Do Not Disturb until Apple Critical Alerts (a separate entitlement, pending) is active, so the call remains the wake-up signal.

### Push notification

Push is enabled in production: `alerts.push.enabled: true`, with the device token taken from the `EXPO_PUSH_TOKEN` environment variable. The push is sent before the Twilio call, so it reaches the phone first. Its payload also carries the SMS-format text in `data.sms_body`. With push disabled or no token configured, a `both` tier sends an SMS only, and a `push` tier sends nothing at all. See the [mobile app explainer](mobile-app.md) for how a device registers its push token.

### Delivery is tracked per revision

Each Event has a `notification_revision`, and each alert record stores the revision it belongs to. SMS and push are deduplicated separately. A channel counts as delivered only when a record for the same revision has a successful status (`sent`, `delivered` or `acknowledged`). A failed attempt therefore stays retryable, and a new revision (created only by an incident-memory escalation) can notify once more.

### Phone call (urgency 9–10)

1. Before each round of calls, an SMS goes out with the Polish summary and a new random 6-digit code: "Odpowiedz kodem aby potwierdzic odbior alertu: NNNNNN" followed by "Telefon bedzie dzwonil dopoki nie potwierdzisz." (sent without Polish diacritics).

2. The Twilio call is placed. A Polish text-to-speech voice (Amazon Polly, voice Ewa) speaks the alert text twice: the event type, the Polish summary, the number of confirming sources, and the urgency score out of 10. The call ends by asking the operator to reply to the SMS with the code. Confirmation works only by that SMS reply.

3. During each call, the system checks for the SMS reply every `alerts.acknowledgment.call_poll_interval_seconds`, for up to `alerts.acknowledgment.call_poll_timeout_seconds` (`_wait_for_call_and_check_sms`). The wait does not freeze the process (Telegram keeps buffering messages), but it runs inside the cycle lock, so no other pipeline cycle starts until the call round ends.

4. Between calls in one round, the system pauses for `alerts.acknowledgment.call_retry_pause_seconds`.

5. A round has `alerts.acknowledgment.max_call_retries` calls (code default 3). The live config keeps this low on purpose after the 2026-07-30 call storm; the reason is in the comment at that key in `config/config.yaml`.

6. If a round ends without the code, the Event moves to `retry_pending`. A new round starts only when the Event is dispatched again, which happens when a later article joins it, and no sooner than `alerts.acknowledgment.retry_interval_minutes` after the last recorded call. There is no scheduled re-call. See "Unacknowledged calls are retried only when a new article joins the event" and "Stale retry_pending calls after a Twilio recharge" in [TODO.md](../../TODO.md).

7. When the code arrives, the Event is marked acknowledged and a follow-up SMS with the full source list is sent.

### SMS body format

`_format_sms_message` builds the full SMS text in Polish from `alerts.templates.sms`: event type, urgency score out of 10, affected countries, aggressor, the Polish summary, a list of source titles with URLs, and the time first seen. Tiers 5–8 are push-only in production, so this text is not sent as an SMS for them. It is still used in four places: the follow-up SMS after acknowledgement, the `data.sms_body` field of every non-update push (update pushes carry the `_format_update_sms` text), any tier set to `sms` or `both`, and the 9–10 SMS fallback.

The body is kept under Twilio's 1600-character limit. The whole message is held to `SMS_MAX_CHARS = 1500`, the summary is cut to `SMS_SUMMARY_MAX_CHARS = 600`, and the source list is packed into the remaining space with an "…i N więcej" line counting the sources left out (`sentinel/alerts/state_machine.py`). Before this cap, events with many long Google News links went over 1600 characters and Twilio rejected the send with HTTP 400. As a last safety net, `TwilioClient.send_sms` cuts any body over 1600 characters.

### After acknowledgement

Acknowledgement stops calls for that Event for good. There is no time-based cooldown: the `alerts.acknowledgment.cooldown_hours` key is read by no code. After acknowledgement, an update SMS (`alerts.templates.sms_update`) and an update push are sent once for each new `notification_revision`, and only an incident-memory escalation creates one. New sources, duplicates and plain updates send nothing.

### System health alerts

| Trigger | Action | Reference |
|---------|--------|-----------|
| Fetcher failures ≥ 5 in a row (up to 9) | WARNING log on each failure | `SentinelPipeline._check_fetcher_health` |
| Fetcher failures ≥ 10 in a row | ERROR log on each failure; Polish SMS to the operator only at exactly 10 | `SentinelPipeline._check_fetcher_health` |
| Whole pipeline failures = 3 in a row | Polish SMS to the operator | `SentinelScheduler._check_pipeline_health` |

Both SMS triggers fire once per failure streak. These SMS go through Twilio, so they do not arrive while the account is unfunded.

---

## Storage

Pipeline data lives in one SQLite database at `database.path` (on the server, `/var/lib/sentinel/sentinel.db`) with five tables:

- articles: every unique article the system has fetched, kept for `database.article_retention_days`. Articles still waiting in the classification queue are never cleaned up.
- classifications: every AI classification result, including the incident-memory decision and the Polish summary guard metadata, deleted together with its article.
- events: grouped incidents with source lists, urgency, alert status and `notification_revision`, kept for `database.event_retention_days`.
- alert_records: every push, SMS and call that a transport accepted, with its status and the `event_revision` it belongs to, deleted together with its Event. Failed Twilio attempts leave no record; they appear only in the log.
- classification_queue: articles waiting for classification or a retry, with attempt count, next attempt time and last error.

Model spending is kept in a separate SQLite ledger, the `model_usage` table in the file at `classification.budget.ledger_path`.

After every cycle, the system writes a health snapshot named `health.json` in the same folder as the database (`/var/lib/sentinel/health.json` on the server; `data/health.json` with a local relative path). It holds the last cycle's time, duration, article and alert counts, consecutive failures, the last error, uptime, database size, a true/false status per fetcher, and `classification_status` (pending, failed, degraded). `./run.sh --health` reads it.
