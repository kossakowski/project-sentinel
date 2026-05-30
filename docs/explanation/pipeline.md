> **What this document is:** A plain-language walkthrough of how Project Sentinel moves from raw media sources to a phone call on your nightstand. Read this when you want to understand what the system is doing at any given stage, or when you need to reason about why an alert did or did not fire.

---

# Pipeline Reference

Project Sentinel processes incoming media in seven sequential stages. Each stage has a clear job: fetch raw content, clean it, deduplicate it, filter for relevance, classify it with AI, corroborate it across sources, and finally alert you. The sections below describe each stage in the order data flows through it.

The system runs continuously on two overlapping schedules. The **fast lane** runs every 3 minutes and covers Telegram channels, Google News, and priority-1 RSS sources. The **slow lane** runs every 15 minutes and covers all enabled sources (GDELT would belong here, but it is disabled in production — see the GDELT section below). Every slow-lane cycle is a superset of a fast-lane cycle.

### Scheduler jitter

| Lane | Jitter applied | Reference |
|------|---------------|-----------|
| Fast | `min(config.jitter_seconds, 10)` — capped at 10s regardless of config value | `sentinel/scheduler.py:464` |
| Slow | Full `config.jitter_seconds` — no cap | `sentinel/scheduler.py` |

---

## Stage 1: Fetching

The system collects articles from four distinct source types. Each type is handled independently — a failure in one does not interrupt the others.

### RSS Feeds

RSS sources are standard news feeds fetched from configured URLs. Each source carries a priority tag from 1 (highest urgency) to 3 (background). The fast lane only fetches priority-1 sources (`max_priority=1`) to keep cycle time short. The slow lane fetches all RSS sources regardless of priority.

The fetcher handles the common failure modes cleanly: a 304 Not Modified response is treated as a no-op and skipped without error; 429 rate-limit responses are logged and the source is skipped for that cycle; responses that appear to be an HTML block rather than XML (body under 2,000 bytes) are recognized as WAF bot-detection pages and discarded; malformed XML is caught and logged without crashing the pipeline.

### Google News

The system runs keyword searches against the Google News RSS API. Live `config/config.yaml` defines 16 queries at `sources.google_news.queries` (7 EN, 7 PL, 2 UK). Note: `config/config.example.yaml` ships with 15 queries — the live count (16) is authoritative. Every query is scoped to the past hour. Example queries: "military attack Poland", "atak wojskowy Polska", "військовий напад Польща".

PAP (the Polish Press Agency) blocks automated fetching via WAF, so it is not fetched as a direct RSS source. Instead, a dedicated `site:pap.pl` query in Google News captures PAP articles indirectly.

### GDELT

GDELT (Global Database of Events, Language, and Tone) is a global news index that covers sources in any language. The system queries the GDELT DOC 2.0 API over a lookback window of `sources.gdelt.lookback_minutes` (default 60 minutes — the API rejects windows shorter than ~30 minutes), filtered to military-relevant topic codes: ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, and TAX_FNCACT_MILITARY, plus a `sourcecountry` filter. Up to 250 articles are returned per call. GDELT articles ship with `summary = ""` (`sentinel/fetchers/gdelt.py:178`); the keyword filter therefore scans title-only for GDELT. Language detection is performed later in the pipeline.

**GDELT is currently disabled in production** (`sources.gdelt.enabled: false`) because the API IP-throttles us with HTTP 429 down to roughly a 20% success rate. The fetcher is only instantiated when enabled, so although the slow lane *would* include GDELT, in production it does not run at all. (The live config also carries a stale `update_interval_minutes: 15`, which is a no-op — the real field is `lookback_minutes`.)

### Telegram

The Telegram fetcher is push-based and uses the `telethon` library (MTProto, user-account auth — not a bot, not `pyrogram`). `start()` registers a `telethon.events.NewMessage` handler on the configured channels; messages accumulate in an in-memory buffer as they arrive. `fetch()` drains and clears that buffer each fast-lane cycle (`sentinel/fetchers/telegram.py:71-78`). Channels monitored: @kpszsu, @GeneralStaffZSU, @DeepStateUA, @nexta_live. All four are keyword-bypass sources — they skip Stage 4 and go straight to AI classification.

---

## Stage 2: Normalization

Before any analysis, each article is cleaned into a consistent format.

HTML tags and entities are stripped from both the title and summary. Titles are capped at 500 characters; summaries at 1,000. If a summary is empty, the title is used in its place. Tracking parameters are removed from URLs (utm_* parameters, fbclid, gclid, and similar), and URL fragments are dropped so that the same article reached via different tracking links resolves to a single canonical URL. Timestamps that lack a timezone are assumed to be UTC. Timestamps that appear to be in the future are capped to the current time. Language codes are standardized — for example, "english" becomes "en" and "polish" becomes "pl".

---

## Stage 3: Deduplication

Three deduplication checks are applied in sequence. An article must pass all three to continue.

1. **Same-batch URL check.** Within a single fetch cycle, if two articles share an identical normalized URL, the second one is dropped immediately in memory, before any database access.

2. **Database URL check.** The normalized URL is hashed and compared against all URLs stored in the database from previous cycles. If there is a match, the article has already been processed and is dropped.

3. **Fuzzy title matching.** All article titles from the past 60 minutes are retrieved from the database. Each incoming article title is compared against this set using Levenshtein string similarity. The thresholds differ based on whether the comparison is cross-source or within the same source: a similarity of 95% or higher across different sources is treated as wire-service syndication and dropped; a similarity of 85% or higher within the same source is treated as an updated re-publish and dropped.

Articles that clear all three checks are inserted into the database.

---

## Stage 4: Keyword Filtering

Before spending AI budget on classification, articles are screened for military relevance using a keyword filter. Two categories of source bypass this stage entirely and proceed directly to classification: the two specialist defence-media RSS feeds carrying `keyword_bypass: true` (Defence24 PL and Defence24 EN) and all four Telegram channels. These sources are considered high signal-to-noise by design.

For all other sources, the filter works as follows:

1. The article's title and summary are concatenated and lowercased.
2. Matching is language-aware. For Slavic languages (Polish, Ukrainian, Russian), plain substring matching is used because word inflection causes endings to vary — for example, "inwazja", "inwazji", and "inwazją" all need to match. For English and other languages, word-boundary matching is used to prevent false matches inside longer words.
3. Critical keywords are checked first. These are terms that by themselves signal a serious event: examples include "invasion", "missile strike", "Article 5", "inwazja", and "atak militarny".
4. High-severity keywords are checked next: terms like "drone", "jets scrambled", "airspace violation", "Shahed", and "sabotage".
5. Exclude keywords are checked last — but only if no critical keyword was already matched. This prevents a term like "drill" from blocking an article that also contains "nuclear drill", since the critical match takes precedence.
6. An article passes if it contains any critical keyword, or if it contains a high-severity keyword with no exclude keyword match.

The configured keyword lists cover English (20 critical, 38+ high, 24 exclude), Polish (17 critical, 31 high, 15 exclude), Ukrainian (9 critical, 19 high), and Russian (9 critical, 19 high). Articles that fail this filter are silently dropped.

---

## Stage 4.5: Summary Enrichment

Before classification, articles whose summary adds little beyond the title are enriched by `ArticleEnricher.enrich_batch` (`sentinel/processing/enricher.py`, awaited at `scheduler.py:239`). A free heuristic gate flags articles where the summary is essentially the title (common for Google News and GDELT), and a cheap LLM gate flags vague or clickbait titles whose summary is technically different but uninformative. Flagged articles have their full body fetched over HTTP and merged in, giving the classifier better input. No articles are dropped here; the stage runs only when relevant articles remain after keyword filtering.

## Stage 5: AI Classification

Every article that reaches this stage is sent individually to Claude Haiku 4.5 for classification. The model evaluates the article as a military intelligence analyst and returns a structured assessment covering six dimensions.

**Is this a real military event?** The model determines whether the article describes an actual ongoing or recent military incident, as opposed to an exercise, a historical reference, or an opinion piece.

**Event type.** If a real event is detected, it is assigned one of these categories: invasion, airstrike, missile_strike, border_crossing, airspace_violation, naval_blockade, cyber_attack, troop_movement, artillery_shelling, drone_attack, other, or none.

**Urgency score (1–10).** This is the most operationally important output:

| Score | Meaning |
|-------|---------|
| 1–2 | Routine military news |
| 3–4 | Minor incident |
| 5–6 | Notable — airspace violation, border provocation, significant troop movement |
| 7–8 | Serious escalation — shots fired, large airspace violation, cyberattack on critical infrastructure |
| 9–10 | Active attack or invasion directly on Poland, Lithuania, Latvia, or Estonia |

Urgency 9–10 is reserved exclusively for direct attacks on monitored territory. Events in Ukraine max out at urgency 4 unless they directly affect Poland or the Baltic states.

**Affected countries.** Only the four monitored countries are recorded here (Poland, Lithuania, Latvia, Estonia), and only when the article explicitly names them. If no monitored country is named, urgency is capped at 2–3 and confidence falls below 0.5.

**Aggressor.** Identified as Russia (RU), Belarus (BY), unknown, or none.

**Confidence (0–1).** The model's confidence in its assessment.

**Polish summary.** One to two sentences summarizing the event in Polish. This text is used verbatim in the phone call and SMS alert.

Additional rules the model applies: diplomatic tensions, opinion pieces, and "special military operation" framing by Russian state media are all handled explicitly — the last of these is treated as an attack. Classifier confidence is NOT threshold-gated: all results are returned and stored regardless of the confidence score (`sentinel/classifier.py`). Downstream gating is done on urgency + source_count only.

---

## Stage 6: Corroboration

A single article, however alarming, is not enough to trigger a phone call. The corroborator groups classification results into Events — each Event representing one real-world military incident — and requires corroboration from independent sources before escalating to the highest alert level.

An Event is created when the first classification with urgency 5 or higher arrives. Subsequent classifications are evaluated to see whether they belong to an existing Event or represent a new one. All of these conditions must be satisfied for a match:

1. The event types must be compatible. For example, a drone_attack classification is compatible with an airstrike Event; a cyber_attack is only compatible with other cyber_attack classifications.
2. The affected countries must be compatible. At and above the phone-call urgency threshold (9), a **concrete-country intersection is required** — a Poland-critical article whose country the classifier failed to extract (empty or "unknown") spawns its own Event and its own call rather than being absorbed. Below that threshold, empty/"unknown" labels carry no location signal and don't block a merge, but two concrete-but-different country sets (e.g. PL vs RO) still stay separate. Country labels are normalized (uppercased, blank/"unknown" dropped) when Events merge.
3. The classification must fall within the corroboration window — `classification.corroboration_window_minutes` (default and live `360` = 6h). This is a **sliding** window measured from the Event's *last activity* (`last_updated_at`), not its birth, so a multi-hour incident that keeps drawing fresh articles stays one Event. A separate absolute lifetime cap, `classification.corroboration_max_age_minutes` (default and live `2880` = 48h, `0` disables), is measured from `first_seen_at` and retires a perpetually-updated Event so it can't chain-merge genuinely separate incidents.
4. The Polish summaries must have at least `classification.summary_similarity_threshold` similarity (default and live `50`), measured by the configurable `classification.summary_similarity_metric` (default `token_set_ratio`, a length-robust `rapidfuzz.fuzz` function; the metric is a config key, tunable without a code deploy).

There is also a **critical-urgency safety guard**: a phone-call-eligible article is never absorbed into an Event that has already been acknowledged (and is therefore in or past its post-alert cooldown). It is forced into a new Event — and a new call — so a fresh critical escalation can never be silenced by an earlier Event's cooldown.

If no existing Event satisfies all the conditions, a new Event is created.

A classification counts as a new independent source only if it comes from a different domain than sources already in the Event, and its title is less than `classification.syndication_similarity_threshold` similar (Pydantic default 90, measured by `rapidfuzz.fuzz.ratio`) to any existing source title. This second check prevents wire service syndication from being mistaken for independent confirmation.

The alert level assigned to an Event is determined by `alerts/state_machine.py:_determine_action`:

| Condition (evaluated in order) | Alert level | Reference |
|--------------------------------|-------------|-----------|
| `urgency >= 9 AND source_count >= 1` | Phone call | live `classification.corroboration_required = 1` |
| `urgency >= 7` (no source_count check) | SMS | `state_machine.py:_determine_action` |
| `urgency >= 5` | SMS | `state_machine.py:_determine_action` |
| Below threshold | Pending — no alert | |

Note: two parallel urgency decision paths exist (corroborator and state_machine) and can disagree. The **Pydantic default for `corroboration_required` is `2`**, but live `config/config.yaml` sets it to `1` — so in production a single source can trigger a phone call. Always check the live config before assuming corroboration behaviour.

Events are stored in the database and are not static. As new articles arrive in later cycles, the urgency, source count, and alert level can all escalate.

---

## Stage 7: Alerts

### Push Notification (additive, fires first)

For any Event whose action is not `log_only`, an **Expo push notification** is sent to the companion mobile app *before* the (potentially blocking) Twilio dispatch, so it reaches the phone immediately. Push is **additive** — it never replaces the phone call or SMS — and is **off by default**: it only fires when `alerts.push.enabled` is true and at least one Expo token is configured (the live production config omits the block, so push is currently disabled). The initial push is deduplicated against any prior push for the same Event, and because push is not one of the "user already notified" channels, a sent push never suppresses a later SMS. See the [mobile app explainer](mobile-app.md) for how a device registers its push token.

### Phone Call (Urgency 9–10 with Independent Corroboration)

A phone call is the highest alert level and requires both a very high urgency score and at least one independent confirming source.

1. An SMS is sent immediately before the call. It contains the event summary in Polish and a randomly generated 6-digit confirmation code, along with the message: "Telefon będzie dzwonił dopóki nie potwierdzisz." (The phone will ring until you confirm.)

2. The Twilio call is placed. A Polish text-to-speech voice (Amazon Polly, voice: Ewa) speaks the alert text twice: the event type, the Polish summary, the number of confirming sources, and the urgency score out of 10. The call ends by instructing the operator to reply to the SMS with the confirmation code.

3. Per call attempt: poll for SMS reply containing the 6-digit code every `alerts.acknowledgment.call_poll_interval_seconds` (default 5s), for up to `alerts.acknowledgment.call_poll_timeout_seconds` (default 90s) — `_wait_for_call_and_check_sms` in `alerts/state_machine.py`. The poll is a non-blocking `await asyncio.sleep`, and the Twilio status / inbound-SMS lookups it makes are offloaded with `asyncio.to_thread`, so the wait never blocks the event loop.

4. Between attempts within a round: `alerts.acknowledgment.call_retry_pause_seconds` (default 10s) via `await asyncio.sleep` (`alerts/state_machine.py`, `_execute_phone_call`).

5. Attempts per round: `alerts.max_call_retries` from config — live value `5`, code default `3`.

6. After a full round fails: wait 5 minutes, begin next round. Repeats indefinitely until the operator replies with the correct code.

7. Upon confirmation, the Event is marked acknowledged and a detailed follow-up SMS is sent with the full source list.

### SMS Alert (Urgency 7–8)

An SMS is sent containing the full event details in Polish: event type, urgency score out of 10, affected countries, aggressor, the Polish summary, a list of source titles with URLs, and a timestamp.

The body is **budget-capped to stay under Twilio's 1600-character limit** (`alerts/state_machine.py`): the whole message is held to `SMS_MAX_CHARS = 1500`, the classifier's `summary_pl` is truncated to `SMS_SUMMARY_MAX_CHARS = 600`, and the source list is packed greedily into whatever budget remains with an "…i N więcej" trailer counting the omitted sources. This was a fix — heavily-corroborated events (many long Google News redirect URLs) previously blew past 1600 characters and Twilio silently rejected the send with HTTP 400.

### Post-Acknowledgment Behavior

Once an operator confirms an alert, a 6-hour cooldown applies to that Event. No further calls or initial SMSes are sent for the same Event during this window. If new confirming sources arrive within those 6 hours, a brief SMS update is sent.

### System Health Alerts

| Trigger | Action | Reference |
|---------|--------|-----------|
| Fetcher `failures == 5` | WARNING log | `sentinel/scheduler.py` |
| Fetcher `failures == 10` (exact equality — one-shot) | ERROR log + Polish SMS to operator | `scheduler.py:420` |
| `consecutive_failures == 3` (exact equality — one-shot) | Polish SMS to operator | `scheduler.py:515` |

Both SMS triggers fire exactly once at the threshold; they do not re-fire on subsequent failures within the same streak.

---

## Storage

All pipeline data is persisted in a SQLite database with four tables:

- **articles** — every unique article the system has fetched, retained for 30 days.
- **classifications** — every AI classification result, retained alongside the article record.
- **events** — corroborated military events with source lists, urgency history, and alert level, retained for 90 days.
- **alert_records** — every Twilio dispatch attempt, including call status and SMS delivery status, retained alongside Event records.

After every pipeline cycle, the system writes a health snapshot to `data/health.json`. This file is readable with `./run.sh --health` and shows the last cycle's outcome, source counts, and any errors.
