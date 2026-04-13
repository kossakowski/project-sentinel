> **What this document is:** A plain-language walkthrough of how Project Sentinel moves from raw media sources to a phone call on your nightstand. Read this when you want to understand what the system is doing at any given stage, or when you need to reason about why an alert did or did not fire.

---

# Pipeline Reference

Project Sentinel processes incoming media in seven sequential stages. Each stage has a clear job: fetch raw content, clean it, deduplicate it, filter for relevance, classify it with AI, corroborate it across sources, and finally alert you. The sections below describe each stage in the order data flows through it.

The system runs continuously on two overlapping schedules. The **fast lane** runs every 3 minutes and covers Telegram channels, Google News, and priority-1 RSS sources — the outlets most likely to carry breaking military news. The **slow lane** runs every 15 minutes and covers everything, including GDELT. Every slow-lane cycle is a superset of a fast-lane cycle.

---

## Stage 1: Fetching

The system collects articles from four distinct source types. Each type is handled independently — a failure in one does not interrupt the others.

### RSS Feeds

RSS sources are standard news feeds fetched from configured URLs. Each source carries a priority tag from 1 (highest urgency) to 3 (background). The fast lane only fetches priority-1 sources (`max_priority=1`) to keep cycle time short. The slow lane fetches all RSS sources regardless of priority.

The fetcher handles the common failure modes cleanly: a 304 Not Modified response is treated as a no-op and skipped without error; 429 rate-limit responses are logged and the source is skipped for that cycle; responses that appear to be an HTML block rather than XML (body under 2,000 bytes) are recognized as WAF bot-detection pages and discarded; malformed XML is caught and logged without crashing the pipeline.

### Google News

The system runs keyword searches against the Google News RSS API. There are 16 configured queries: 7 in English, 7 in Polish, and 2 in Ukrainian. Every query is scoped to the past hour only, so results stay fresh and do not overlap with prior cycles. Example queries include "military attack Poland", "atak wojskowy Polska", and "військовий напад Польща".

PAP (the Polish Press Agency) blocks automated fetching via WAF, so it is not fetched as a direct RSS source. Instead, a dedicated `site:pap.pl` query in Google News captures PAP articles indirectly.

### GDELT

GDELT (Global Database of Events, Language, and Tone) is a global news index that covers sources in any language. The system queries the GDELT DOC 2.0 API for articles published in the past 15 minutes, filtered to military-relevant topic codes: ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, and TAX_FNCACT_MILITARY. Up to 250 articles are returned per call. GDELT does not provide article summaries, so only titles and URLs are available at this stage. Language detection is performed later in the pipeline. GDELT runs on the slow lane only.

### Telegram

The system connects to Telegram using the MTProto API via a full user account — not a bot — which allows it to read channels without being added as a member. It listens in real time to four channels: @kpszsu (Ukrainian Air Force), @GeneralStaffZSU (Ukrainian General Staff), @DeepStateUA, and @nexta_live (NEXTA Live). Messages accumulate in a memory buffer as they arrive. Each fast-lane cycle drains and clears that buffer, processing whatever has come in since the last cycle. All four Telegram channels are designated keyword bypass sources, meaning their content skips keyword filtering and goes directly to AI classification.

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

Before spending AI budget on classification, articles are screened for military relevance using a keyword filter. Two categories of source bypass this stage entirely and proceed directly to classification: the four specialist defence media (Defence24 PL and Defence24 EN) and all four Telegram channels. These sources are considered high signal-to-noise by design.

For all other sources, the filter works as follows:

1. The article's title and summary are concatenated and lowercased.
2. Matching is language-aware. For Slavic languages (Polish, Ukrainian, Russian), plain substring matching is used because word inflection causes endings to vary — for example, "inwazja", "inwazji", and "inwazją" all need to match. For English and other languages, word-boundary matching is used to prevent false matches inside longer words.
3. Critical keywords are checked first. These are terms that by themselves signal a serious event: examples include "invasion", "missile strike", "Article 5", "inwazja", and "atak militarny".
4. High-severity keywords are checked next: terms like "drone", "jets scrambled", "airspace violation", "Shahed", and "sabotage".
5. Exclude keywords are checked last — but only if no critical keyword was already matched. This prevents a term like "drill" from blocking an article that also contains "nuclear drill", since the critical match takes precedence.
6. An article passes if it contains any critical keyword, or if it contains a high-severity keyword with no exclude keyword match.

The configured keyword lists cover English (20 critical, 38+ high, 24 exclude), Polish (17 critical, 31 high, 15 exclude), Ukrainian (9 critical, 19 high), and Russian (9 critical, 19 high). Articles that fail this filter are silently dropped.

---

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

Additional rules the model applies: diplomatic tensions, opinion pieces, and "special military operation" framing by Russian state media are all handled explicitly — the last of these is treated as an attack, not a euphemism to be taken at face value. All classification results are stored in the database regardless of their outcome, so the full record is available for auditing.

---

## Stage 6: Corroboration

A single article, however alarming, is not enough to trigger a phone call. The corroborator groups classification results into Events — each Event representing one real-world military incident — and requires corroboration from independent sources before escalating to the highest alert level.

An Event is created when the first classification with urgency 5 or higher arrives. Subsequent classifications are evaluated to see whether they belong to an existing Event or represent a new one. Four conditions must all be satisfied for a match:

1. The event types must be compatible. For example, a drone_attack classification is compatible with an airstrike Event; a cyber_attack is only compatible with other cyber_attack classifications.
2. At least one affected country must overlap.
3. The classification must fall within the 60-minute corroboration window of the Event.
4. The Polish summaries must have at least 55% semantic similarity (measured by token sort ratio).

If no existing Event satisfies all four conditions, a new Event is created.

A classification counts as a new independent source only if it comes from a different domain than sources already in the Event, and its title is less than 90% similar to any existing source title. This second check prevents wire service syndication from being mistaken for independent confirmation.

The alert level assigned to an Event is determined by its current urgency and source count:

| Condition | Alert level |
|-----------|-------------|
| Urgency ≥ 9 and at least 1 independent source | Phone call |
| Urgency ≥ 7 | SMS |
| Urgency ≥ 5 | WhatsApp (routed to SMS in practice) |
| Below threshold | Pending — no alert yet |

Events are stored in the database and are not static. As new articles arrive in later cycles, the urgency, source count, and alert level can all escalate.

---

## Stage 7: Alerts

### Phone Call (Urgency 9–10 with Independent Corroboration)

A phone call is the highest alert level and requires both a very high urgency score and at least one independent confirming source.

1. An SMS is sent immediately before the call. It contains the event summary in Polish and a randomly generated 6-digit confirmation code, along with the message: "Telefon będzie dzwonił dopóki nie potwierdzisz." (The phone will ring until you confirm.)

2. The Twilio call is placed. A Polish text-to-speech voice (Amazon Polly, voice: Ewa) speaks the alert text twice: the event type, the Polish summary, the number of confirming sources, and the urgency score out of 10. The call ends by instructing the operator to reply to the SMS with the confirmation code.

3. The system polls for an SMS reply containing the 6-digit code every 5 seconds, for up to 90 seconds per call attempt.

4. If no confirmation is received, up to 5 call attempts are made in one round.

5. If still unconfirmed after 5 attempts, the system waits 5 minutes and begins another round.

6. This cycle repeats indefinitely until the operator sends the correct code.

7. Upon confirmation, the Event is marked acknowledged and a detailed follow-up SMS is sent with the full source list.

### SMS Alert (Urgency 7–8)

An SMS is sent containing the full event details in Polish: event type, urgency score out of 10, affected countries, aggressor, the Polish summary, a list of source titles with URLs, and a timestamp.

### Post-Acknowledgment Behavior

Once an operator confirms an alert, a 6-hour cooldown applies to that Event. No further calls or initial SMSes are sent for the same Event during this window. If new confirming sources arrive within those 6 hours, a brief SMS update is sent.

### System Health Alerts

The system monitors its own health and alerts the operator if something goes wrong at the infrastructure level:

- 5 consecutive fetcher failures generate a WARNING log entry.
- 10 consecutive fetcher failures generate an ERROR log entry and send a Polish SMS to the operator.
- 3 consecutive pipeline-level failures (not just fetcher failures, but full cycle crashes) send a Polish SMS to the operator.

---

## Storage

All pipeline data is persisted in a SQLite database with four tables:

- **articles** — every unique article the system has fetched, retained for 30 days.
- **classifications** — every AI classification result, retained alongside the article record.
- **events** — corroborated military events with source lists, urgency history, and alert level, retained for 90 days.
- **alert_records** — every Twilio dispatch attempt, including call status and SMS delivery status, retained alongside Event records.

After every pipeline cycle, the system writes a health snapshot to `data/health.json`. This file is readable with `./run.sh --health` and shows the last cycle's outcome, source counts, and any errors.
