# Config Reference — Project Sentinel

Last verified: 2026-10-03 (deployed commit 6429124)

This page mirrors `sentinel/config.py` key by key. It names three different sources of values:

- Pydantic default — the code default in `sentinel/config.py`. It applies when a key is omitted.
- Template — `config/config.example.yaml`, the starting file for a fresh install. It is noted only where it differs.
- Live value — `config/config.yaml`. `/deploy` copies this file to `/etc/sentinel/config.yaml` on the server, so it holds the production values.

## Contents

- [Config Loading](#config-loading)
- [Required Environment Variables](#required-environment-variables)
- [`sources`](#sources--sourcesconfig-sentinelconfigpy) — RSS, GDELT, Google News, Telegram
- [`monitoring`](#monitoring--monitoringconfig)
- [`classification`](#classification--classificationconfig) — provider, budget, policy, summary language, incident memory
- [`alerts`](#alerts--alertsconfig) — urgency levels, acknowledgment, templates, push
- [`scheduler`](#scheduler--schedulerconfig)
- [`processing`](#processing--processingconfig--processingdedup)
- [`database`](#database--databaseconfig)
- [`logging`](#logging--loggingconfig)
- [`testing`](#testing--testingconfig)

## Config Loading

| Item | Value |
|---|---|
| File | `config/config.yaml` (override via `--config PATH`); production reads `/etc/sentinel/config.yaml` |
| Env var syntax | `${VAR_NAME}` — expanded at load time; missing var raises `ConfigError` |
| Loader | `sentinel/config.py:load_config()` → returns `SentinelConfig` |
| `.env` | Loaded via `python-dotenv` before substitution, only if the package is installed; it does not override variables already set |
| Top-level model | `SentinelConfig` (wraps all sections below) |

Env-var substitution rules (`sentinel/config.py:_substitute_env_vars`):

- Substitution walks every string in the whole YAML file before validation. A `${VAR}` inside a disabled section must still resolve, or loading fails.
- There is no default syntax. `${A:-b}` looks up a variable literally named `A:-b`.
- The live config references `ALERT_PHONE_NUMBER`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `EXPO_PUSH_TOKEN`, so all four must be set for it to load.
- In production the variables come from `/etc/sentinel/sentinel.env`, the systemd `EnvironmentFile`.

---

## Required Environment Variables

| Variable | Used by | Required |
|---|---|---|
| `OPENAI_API_KEY` | Direct classifier and enrichment quality gate (`sentinel/classification/openai_provider.py`) | when provider is `openai` (live) |
| `ANTHROPIC_API_KEY` | Legacy classifier and quality gate | when provider is `anthropic` |
| `TWILIO_ACCOUNT_SID` | Twilio client (`sentinel/alerts/twilio_client.py`) | for calls and SMS; not checked at load |
| `TWILIO_AUTH_TOKEN` | Twilio client | for calls and SMS; not checked at load |
| `TWILIO_PHONE_NUMBER` | Twilio client (outbound caller ID and SMS sender) | for calls and SMS; not checked at load |
| `ALERT_PHONE_NUMBER` | Destination for all alerts (`alerts.phone_number`) | yes (referenced in the live YAML) |
| `TELEGRAM_API_ID` | Telegram fetcher (`sentinel/fetchers/telegram.py`) | whenever referenced as `${...}` in the YAML (substitution runs before the `enabled` check) |
| `TELEGRAM_API_HASH` | Telegram fetcher | whenever referenced as `${...}` in the YAML |
| `EXPO_PUSH_TOKEN` | `alerts.push.tokens` | whenever referenced in the YAML; the live config references it |
| `EXPO_ACCESS_TOKEN` | Expo push client (`sentinel/alerts/push_client.py`), sent as a bearer token | optional in code; required in production (see [`alerts.push`](#alertspush--pushconfig)) |

---

## `sources` — `SourcesConfig` (`sentinel/config.py`)

Consumed by: `sentinel/fetchers/`

### `sources.rss` — `RSSSource` (list)

| YAML key | Type | Pydantic default | Description |
|---|---|---|---|
| `name` | str | required | Display name (logs, alerts) |
| `url` | HttpUrl | required | RSS/Atom feed URL |
| `language` | str | required | ISO 639-1 code (`pl`, `en`, `uk`, `ru`) |
| `enabled` | bool | `true` | Poll this feed |
| `priority` | int | `2` | `1` = polled in both the fast (3 min) and slow lanes; `≥2` = slow lane only. No effect on corroboration. |
| `keyword_bypass` | bool | `false` | Skip keyword filter; send all articles to AI classification |

Live enabled priority-1 feeds: RMF24, Defence24, Ukrainska Pravda UA, Ukrainska Pravda EN, Kyiv Independent.
`keyword_bypass: true` on: Defence24, Defence24 EN (only).
PAP and TVN24 are priority-1 but **`enabled: false`** — PAP is blocked by an Incapsula/Imperva WAF (routed via the `google_news` `site:pap.pl` query instead); TVN24 was disabled 2026-05-27 (Cloudflare blocks the Hetzner datacenter IP).

### `sources.gdelt` — `GDELTConfig`

Consumed by: `sentinel/fetchers/gdelt.py`

GDELT is disabled in production (`enabled: false`) due to IP-level 429 throttling (~20% success rate from the Hetzner datacenter IP). The fetcher is only instantiated when enabled, so the slow lane currently runs without GDELT. The template ships it enabled.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | `false` | `true` | Enable GDELT DOC 2.0 fetcher. |
| `lookback_minutes` | int | (omitted → `60`) | `60` | `TIMESPAN` window (minutes) for the GDELT DOC 2.0 query. Sent as `TIMESPAN={lookback_minutes}min`. Must be ≥ ~30 — the API rejects shorter spans with `200 OK` + plain-text body `"Timespan is too short."` (logged as an ERROR). |
| `themes` | list[str] | `[ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, TAX_FNCACT_MILITARY]` | required | GKG theme codes. Query shape: `(theme:A OR theme:B …) (sourcecountry:X OR sourcecountry:Y …)`, where the two groups are ANDed. The `sourcecountry` codes are the FIPS codes of `monitoring.target_countries`; `sourcecountry` filters by the publishing outlet's country, not by the attacked country. |

> Stale key in live config: `config/config.yaml` contains `sources.gdelt.update_interval_minutes: 15`. There is no such Pydantic field. Pydantic ignores unknown keys, so it is a silent no-op. The real field is `lookback_minutes`, which the live config omits, so GDELT would use the `60` default if re-enabled. TODO.md tracks this stale key.

### `sources.google_news` — `GoogleNewsConfig`

Consumed by: `sentinel/fetchers/google_news.py`

| YAML key | Type | Pydantic default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable Google News RSS fetcher |
| `queries` | list[GoogleNewsQuery] | required | List of `{query: str, language: str}` pairs |

Live: queries in `en`, `pl` and `uk`, including `site:pap.pl` as the PAP fallback. The full list is in `config/config.yaml` and [sources.md](sources.md).

### `sources.telegram` — `TelegramConfig`

Consumed by: `sentinel/fetchers/telegram.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | `true` | Enable Telegram MTProto fetcher |
| `api_id` | int | `${TELEGRAM_API_ID}` | `None` | From env; a validator requires it when `enabled` |
| `api_hash` | str | `${TELEGRAM_API_HASH}` | `None` | From env; a validator requires it when `enabled` |
| `session_name` | str | `/var/lib/sentinel/sentinel_session` | `"sentinel"` | Telethon session file path |
| `channels` | list[TelegramChannel] | see below | `[]` | Channels to monitor |

`TelegramChannel` fields: `name` (str), `channel_id` (str, e.g. `@kpszsu`), `language` (str), `priority` (int, default `1`), `keyword_bypass` (bool, default `false`). `priority` is accepted but no code reads it: all Telegram channels are drained in the fast lane. `keyword_bypass` applies only while `sources.telegram.enabled` is `true`.

Live channels (all `keyword_bypass: true`):

| Name | channel_id | lang | priority (unused) |
|---|---|---|---|
| Ukrainian Air Force | `@kpszsu` | uk | 1 |
| General Staff of Ukraine | `@GeneralStaffZSU` | uk | 1 |
| NEXTA Live | `@nexta_live` | ru | 1 |
| DeepState UA | `@DeepStateUA` | uk | 2 |

---

## `monitoring` — `MonitoringConfig`

Consumed by: `sentinel/processing/keyword_filter.py` (`keywords`, `exclude_keywords`) and `sentinel/fetchers/gdelt.py` (`target_countries`, as the GDELT `sourcecountry` filter).

| YAML key | Type | Description |
|---|---|---|
| `target_countries` | list[dict] | Each: `{code, name, name_native}`. Read only by the GDELT fetcher (disabled in production). |
| `aggressor_countries` | list[dict] | Each: `{code, name, name_native}`. Currently unused by code. |
| `keywords` | dict[str, KeywordSet] | Per-language keyword lists; structure: `{lang: {critical: [], high: []}}` |
| `exclude_keywords` | dict[str, list[str]] | Per-language exclusion terms (Pydantic default `{}`) |

Live `target_countries`: PL, LT, LV, EE. Live `aggressor_countries`: RU, BY.
The countries the classifier monitors are set by `classification.policy.monitored_countries` (OpenAI path), not by `monitoring.target_countries`. The legacy Anthropic prompt hard-codes them.

**Keyword matching rules:**
- `critical` keywords: case-insensitive; override `exclude_keywords` (article passes even if both match).
- `high` keywords: case-insensitive; do NOT override `exclude_keywords`.
- PL/UK/RU: substring matching (handles inflection). EN and every other language: word-boundary matching.
- An article in a language with no keyword set uses the `en` keyword set and word-boundary matching.
- `exclude_keywords` are checked only when no `critical` keyword matches. A non-English article is checked against its own language's list plus the `en` list; for pl/uk/ru the `en` excludes also match as substrings.
- Articles from `keyword_bypass` sources skip the filter entirely.

Live keyword languages: `en`, `pl`, `uk`, `ru`. Live `exclude_keywords` languages: `en`, `pl` (so uk/ru articles are checked against the `en` list only).

---

## `classification` — `ClassificationConfig`

Consumed by: `sentinel/classification/classifier.py` and `sentinel/classification/openai_provider.py` (model call), and `sentinel/classification/corroborator.py` (event grouping / corroboration).

Production runs the incident-memory path (`incident_memory.enabled: true`). In that mode `corroboration_window_minutes`, `corroboration_max_age_minutes`, `summary_similarity_metric` and `summary_similarity_threshold` are not read. Of the grouping keys below, only `syndication_similarity_threshold` and `corroboration_required` still act in production.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `provider` | str | `openai` | `anthropic` | Explicit provider (`anthropic` or `openai`); no automatic fallback. Omission preserves old installations. |
| `model` | str | `gpt-5.6-luna` | `claude-haiku-4-5-20251001` | Provider model ID, also used by the quality gate. With provider `openai` the ID must start with `gpt-`. |
| `max_tokens` | int | `1024` | `512` | Range 128–4096. OpenAI total output cap; legacy Anthropic adds `incident_memory.extra_output_tokens`. |
| `temperature` | float | `0.0` | `0.0` | Legacy Anthropic sampling only; no deterministic-output guarantee. OpenAI omits this setting, preserving the tested provider default. |
| `corroboration_required` | int | `1` | `2` | Only sets the stored `alert_status` label (`phone_call` vs `sms`) for urgency ≥ 9; both labels are dispatched, so it does not affect delivery. The call gate is `alerts.urgency_levels.critical.corroboration_required` (live `1`, so one source triggers a phone call today). |
| `corroboration_window_minutes` | int | `360` | `360` | Legacy path only (inert in production). Sliding window (minutes) for grouping a new article into an existing event, measured from that event's `last_updated_at` (its last activity), not `first_seen_at`. |
| `corroboration_max_age_minutes` | int | `2880` | `2880` | Legacy path only (inert in production). Absolute lifetime cap (minutes) measured from `first_seen_at`. Once an event is older than this, a fresh article spawns a new event. `0` disables the cap. |
| `summary_similarity_metric` | str | `token_set_ratio` | `token_set_ratio` | Legacy path only (inert in production). Which `rapidfuzz.fuzz` function compares a new summary to an existing event's summary. Allow-list: `ratio`, `partial_ratio`, `token_sort_ratio`, `token_set_ratio`, `WRatio`, `QRatio` (any other value raises `ConfigError` at load). `token_set_ratio` is length-robust, unlike `token_sort_ratio`. |
| `summary_similarity_threshold` | int | `50` | `50` | Legacy path only (inert in production). Score (0-100) from the metric above, at/above which a new summary is treated as the same event. Lower = more aggressive merging. |
| `syndication_similarity_threshold` | int | `90` | `90` | Source-independence guard (active on both paths). A source counts as *independent* only if it is a different domain AND its normalized title similarity to an already-counted source is `< 90` (`fuzz.ratio`), checked across all source types to catch wire/syndication reuse. Range 0-100. |

Legacy event-grouping notes (only when incident memory is disabled):
- **Sliding window + max-age cap together:** the 6h window is re-anchored on every update, so the 48h cap is what ultimately retires a long-running event.
- Country gate: at/above the phone-call urgency threshold (9), a match requires a concrete-country intersection — a Poland-critical article whose country wasn't extracted spawns its own event (empty/"unknown" does NOT relax the gate at critical urgency). Below the threshold, empty/"unknown" labels don't block a merge, but two concrete-but-different country sets (e.g. PL vs RO) stay separate. Countries are normalized (uppercased; blank/"unknown" dropped) on merge. The memory path applies the same country check.
- Critical-urgency acknowledged guard: a phone-call-eligible article is never absorbed into an event that already has `acknowledged_at` set. It forces a new event and a new call.

### Direct provider, budget and recovery

| Key | Live value | Pydantic default | Constraint | Meaning |
|---|---|---|---|---|
| `api_base_url` | `https://api.openai.com/v1` | `https://api.openai.com/v1` | only this value | Direct endpoint; alternative hosts are rejected. |
| `reasoning_effort` | `none` | `none` | only `none` | Explicitly disabled; other values are rejected. |
| `timeout_seconds` | `30` | `30` | > 0, ≤ 120 | Total request deadline; SDK retries are disabled. |
| `policy` | v2 policy (see below) | `{}` | required in OpenAI mode | Classification policy; see [`classification.policy`](#classificationpolicy). |
| `retry_delay_seconds` | `300` | `300` | ≥ 1 | Delay before a failed article is retried. |
| `retry_batch_size` | `100` | `100` | 1–1000 | Maximum pending articles processed per cycle, oldest `fetched_at` first. |
| `budget.ledger_path` | `/var/lib/sentinel/model-usage.db` | `data/model-usage.db` | — | Shared persistent OpenAI reservation/usage ledger. |
| `budget.monthly_usd` | `30` | `10` | > 0, ≤ 50 | UTC monthly application allowance, hard-enforced by the usage ledger (see below). Template: `10`. |
| `budget.input_per_million` | `0.20` | `0.20` | > 0 | Configured standard input estimate in USD. |
| `budget.cached_input_per_million` | `0.02` | `0.02` | ≥ 0 | Cached input estimate in USD. |
| `budget.output_per_million` | `1.20` | `1.20` | > 0 | Output estimate in USD. |
| `budget.cache_write_multiplier` | `1.25` | `1.25` | ≥ 1 | Conservative premium on uncached input when separate cache-write usage is unavailable. |

Budget enforcement. `UsageLedger.reserve` (`sentinel/classification/openai_provider.py`) raises `BudgetExceeded` when the month's reservations plus the new request would exceed `budget.monthly_usd`. Classification then pauses and the articles stay pending in `classification_queue`.

Retry behavior. A failed article (provider error, budget exhaustion, grouping failure) stays in `classification_queue` and is retried every `retry_delay_seconds`. There is no attempt cap. Every cycle in either lane picks up to `retry_batch_size` due items. While any queued row has a failed attempt, health reports `degraded`.

These rates were checked for Luna on 2026-09-20; they are not universal model
prices. The ledger includes the enrichment quality gate and uncertain reservations.
It excludes spending outside this application. See [API setup](../how-to/api-setup.md)
for billing and the budget/detection-gap trade-off.
Additive database migrations preserve historical events and classifications.
Only newly selected articles enter `classification_queue`; historic URL dedup
is retained, not silently relabelled as new-model output. Every direct result
persists provider/model/prompt/request provenance and factual extraction.

### `classification.policy`

Required when `provider` is `openai`. `ClassificationConfig._validate_direct_policy` rejects the config at load unless all of the following hold, and `sentinel/classification/policy.py:system_prompt()` builds the prompt from these values.

| Key | Live value | Rule |
|---|---|---|
| `version` | `2` | Must equal `2`. |
| `monitored_countries` | `[PL, LT, LV, EE]` | Non-empty list; the countries named in the classifier prompt. |
| `near_border_strike` | `awareness` | One of `awareness`, `log_only`, `critical`. Sets how a confirmed strike inside Ukraine very close to Poland is scored. |
| `neutralised_drone` | `original_severity` | One of `current_danger`, `original_severity`. Sets whether a neutralised Russian drone in Poland keeps its original severity. |
| `ranges` | 13 named bands (below) | Each value is an int pair `[lo, hi]` with 1 ≤ lo ≤ hi ≤ 10. All 13 names must be present. |

Live `ranges` (urgency bands the classifier assigns):

| Band | Live | Band | Live |
|---|---|---|---|
| `active_attack` | 9–10 | `reaction` | 2–4 |
| `official_warning` | 9–10 | `resolved` | 1–4 |
| `precaution` | 5–6 | `unclear_location` | 2–3 |
| `nuclear_activity` | 7–8 | `russian_drone_unresolved_poland` | 7–8 |
| `direct_hostile_threat` | 7–8 | `russian_drone_unresolved_other` | 5–6 |
| `routine` | 1–3 | `civilian_or_unknown_ground_drone` | 1–4 |
| `capability_escalation` | 5–6 | | |

### `classification.summary_language`

Direct OpenAI summaries pass a local Polish-language check. A failure permits one
summary-only translation through the same provider and budget. The classifier's
original danger, facts and incident decision remain unchanged. A failed translation
uses the configured Polish notice and still proceeds through normal alert rules.
Live values equal the defaults below.

| Key | Default | Constraint | Meaning |
|---|---|---|---|
| `detector_languages` | `[pl, en, uk, ru, de, cs, sk, lt, lv, et]` | must include pl/en/uk/ru; no duplicates; Lingua ISO 639-1 codes only | Local Lingua comparison languages. Cyrillic leakage also triggers repair. |
| `repair_max_tokens` | `512` | 128–1024 | Maximum output for the one allowed repair request. |
| `repair_timeout_seconds` | `10` | > 0, ≤ 30 | Total repair deadline, capped by the provider's overall timeout setting. |
| `fallback_pl` | Polish unavailability notice | 20–500 chars; must be detected as Polish | Used if translation cannot be completed and validated. |

`summary_processing` stores the original summary and repair provenance; old rows
receive `{}`. Accepted repair replies contribute to result token/cost totals.
The persistent usage ledger also retains refused/incomplete/unknown-charge attempts.
Local language detection is a statistical guard, not proof of factual fidelity.
See [design and verification](../ideas/polish-summary-guard.md).

### `classification.incident_memory`

This path includes stored incident context in the existing classification
request. It does not change the configured model or add another model call.
Production runs with incident memory enabled since the 2026-09-20 Luna deployment.
The Pydantic default stays `false` for old configurations. The fuzzy grouping
keys above apply only to the legacy path. Memory matching has no max-age cap: a
validated match can attach to any event whose `last_updated_at` is within
`lookback_hours`. While memory is enabled, the deduplicator also skips fuzzy
title dedup (`processing.dedup.*`); exact URL dedup still applies.

| Field | Live value | Pydantic default | Constraint | Purpose |
|---|---|---|---|---|
| `enabled` | `true` | `false` | — | Activate sequential classification with incident context and validated semantic grouping. |
| `lookback_hours` | `168` | `168` | 1–2160 | Retrieve recently updated incidents regardless of acknowledgement or expiry status; also the maximum age (since last activity) of a matched event. |
| `candidate_pool_size` | `100` | `100` | 1–1000 | Bound the database search before relevance ranking. |
| `max_candidates` | `5` | `5` | 1–20; ≤ `candidate_pool_size` | Bound the incident list sent to the model; retain the newest incident and rank the others by text overlap. |
| `evidence_per_event` | `2` | `2` | 1–5 | Include bounded recent article evidence so memory does not rely only on the original summary. |
| `max_text_chars` | `300` | `300` | 100–2000 | Limit each summary/title field in candidate context. |
| `min_confidence` | `0.85` | `0.85` | 0.5–1.0 | Minimum incident-identity confidence to accept a noncritical match to a supplied candidate ID. |
| `critical_min_confidence` | `0.9` | `0.9` | 0.5–1.0; ≥ `min_confidence` | Stricter minimum for incoming phone-call-eligible reports. |
| `extra_output_tokens` | `256` | `256` | 128–1024 | Legacy Anthropic memory allowance; OpenAI uses the single `max_tokens` total. |
| `weekday_aliases` | multilingual map | `{}` | — | Map weekday names across PL/EN/UA/RU to catch conflicting incident days. Explicit ISO and DD.MM.YYYY dates are also checked. |

The output distinguishes a new incident, duplicate coverage, a nonurgent update,
an escalation, and uncertain identity. Only a validated match can bypass the old
event-type mismatch. Concrete country conflicts and the critical-country guard
still prevent merging. An uncertain or invalid memory decision creates a separate
incident rather than suppressing it. A first critical report cannot be silently
absorbed into a previously noncritical event.

Duplicate coverage and routine details do not create a notification revision.
Significant escalation updates the alert summary and advances its durable revision.
SMS and push independently remember successful revisions; a failed attempt does
not mark the channel delivered. An acknowledged incident can receive a new-revision
SMS/push update, but the acknowledged gate prevents another call. New
attack waves remain separate events. Unacknowledged-call retries are unchanged.
Here, successful means provider acceptance (`sent`), not confirmed handset delivery.
The existing system does not process final SMS/push receipts. Immediate failed attempts
remain retryable on re-dispatch; later provider-side delivery failures are not yet
tracked. It also has no idle-cycle sweep of `retry_pending` incidents; this repair
does not resurrect old retry records.

Incident-memory context is billed in the same request and counts against
`classification.budget.monthly_usd`. Candidate context adds input tokens without
adding a second call per article. The memory path also bypasses fuzzy-title
rejection for different URLs, preserving corroboration and new developments; that
can increase classified article volume.
Design history: [the implementation plan](../ideas/incident-memory-plan.md) (a working note, not current truth).

---

## `alerts` — `AlertsConfig`

Consumed by: `sentinel/alerts/`

Known state: the Twilio account is deliberately unfunded by the owner. Since 2026-09-21 every Twilio call and SMS fails with HTTP 401 (account not active). Phone calls stay configured and return when the owner recharges the account. Expo push is unaffected. See the [server runbook](../how-to/server-runbook.md).

### Top-level alert fields

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `phone_number` | str | `${ALERT_PHONE_NUMBER}` | required | Destination for calls and SMS |
| `language` | str | `pl` | `pl` | Defined but not read (no effect). Call TTS language is hard-coded to `pl-PL` in `sentinel/alerts/twilio_client.py`. |

### `alerts.urgency_levels` — `UrgencyLevel` (dict keyed by name)

Live values:

| Level | `min_score` | `action` | `channel` | `corroboration_required` | `retry_attempts` | `retry_interval_minutes` | `fallback` |
|---|---|---|---|---|---|---|---|
| `critical` | 9 | `phone_call` | (ignored) | 1 | 3 (not read) | 5 (not read) | `sms` (not read) |
| `high` | 7 | `sms` | `push` | 1 | (omitted → 0, not read) | (omitted → 5, not read) | — |
| `medium` | 5 | `sms` | `push` | 1 | (omitted → 0, not read) | (omitted → 5, not read) | — |
| `low` | 1 | `log_only` | (ignored) | (omitted → 1) | (omitted → 0, not read) | (omitted → 5, not read) | — |

`action` values: `phone_call`, `sms`, `log_only`. Pydantic defaults: `corroboration_required` `1`, `retry_attempts` `0`, `retry_interval_minutes` `5`, `fallback` `None`, `channel` `both`.

The per-level `retry_attempts`, `retry_interval_minutes` and `fallback` are defined but not read (no effect). Call spacing comes only from `alerts.acknowledgment.retry_interval_minutes`. When a 9–10 event has fewer sources than `critical.corroboration_required`, `AlertStateMachine._determine_action` returns a hard-coded `sms` action instead of `fallback`; that path sends SMS only, with no push and no channel lookup. With the live value `1`, one source triggers a phone call today. TODO.md tracks the unread keys.

#### `channel` — per-tier delivery channel for the SMS tiers

| YAML key | Type | Allowed values | Pydantic default | Description |
|---|---|---|---|---|
| `channel` | str | `sms`, `push`, `both` | `both` | Which delivery channel an **SMS-action tier** uses. A `field_validator` rejects any other value with a `ValueError` at load. |

Live: tiers 5–8 (`high` and `medium`) are push-only on purpose, with no Twilio SMS. `both` is the Pydantic default and the template value.

The `channel` field selects, per urgency tier, how a 5–8 alert is delivered:

- `sms` — Twilio SMS only.
- `push` — Expo push only; no Twilio SMS for that tier.
- `both` — Twilio SMS and an Expo push.

Scope of `channel`:

- It is consulted only for the `high` (urgency 7–8) and `medium` (urgency 5–6) tiers — the levels whose `action` is `sms`. `AlertStateMachine._determine_action` returns the matched SMS-tier level's `channel` (`sms` / `push` / `both`).
- It is ignored for the `critical` (`phone_call`) and `low` (`log_only`) levels. The urgency 9–10 path sends a confirmation-code SMS, places the call(s), sends a follow-up SMS after acknowledgment, and additionally fires an Expo push (the call stays the primary wake-up). Urgency 1–4 logs only. Configs may omit `channel` on `critical`/`low`.
- Configs that omit `channel` entirely still load; the `both` default applies to `high`/`medium`.

Push disabled or no tokens. The push client no-ops while push is disabled or no tokens are configured. A `both` tier then sends SMS only. A `push` tier then sends nothing: the alert is dropped silently. The template ships `channel: both` with push disabled, so a fresh install sends SMS only.

### `alerts.acknowledgment` — `AcknowledgmentConfig`

Acknowledgment is by an SMS reply with a 6-digit code. The code SMS is sent before the first call attempt of a round. The reply is polled before each call, during each call's wait loop, after each call, and once more after the round.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `call_duration_threshold_seconds` | int | `15` | `15` | Defined but not read (no effect); superseded by SMS-code confirmation |
| `max_call_retries` | int | `1` | `3` | Calls placed per round (per dispatch), not a lifetime total. Capped at `1` since 2026-07-30 because event fragmentation multiplied calls. Template: `5`. |
| `retry_interval_minutes` | int | `5` | `5` | Minimum wait after the last call before a new round starts |
| `cooldown_hours` | int | `6` | `6` | Defined but not read (no effect) |
| `call_poll_timeout_seconds` | int | (omitted → `90`) | `90` | Max seconds to wait for a placed call to finish (and for an SMS reply) before moving to the next attempt; read by `_wait_for_call_and_check_sms`. Template: `90`. |
| `call_poll_interval_seconds` | int | (omitted → `5`) | `5` | Seconds between Twilio call-status / inbound-SMS polls during the wait loop. Template: `5`. |
| `call_retry_pause_seconds` | int | (omitted → `10`) | `10` | Seconds to pause between call attempts within a single round. Template: `10`. |

A round that ends without acknowledgment sets the event to `retry_pending`. A new round starts only when the event is dispatched again (a new article joins it in a later cycle) and `retry_interval_minutes` has passed. No idle-cycle sweep re-dispatches `retry_pending` events.

### `alerts.templates` — `AlertTemplates`

Python format strings. Override in config to customize; Pydantic provides defaults. The live config sets the same text as the defaults.

| Key | Placeholders | Description |
|---|---|---|
| `call` | `{event_type_pl}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | TTS text read aloud during phone call |
| `sms` | `{event_type_pl}`, `{urgency_score}`, `{affected_countries_str}`, `{aggressor}`, `{summary_pl}`, `{source_count}`, `{sources_list}`, `{first_seen_at_local}` | Initial SMS alert body |
| `sms_update` | `{event_type_pl}`, `{new_source_name}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | SMS for an already-acknowledged event, sent when incident memory classifies a new article as an escalation (its `notification_revision` increments). New corroborating sources alone do not trigger it. |

### `alerts.push` — `PushConfig`

Consumed by: `sentinel/alerts/push_client.py` (`ExpoPushClient`) via `sentinel/alerts/state_machine.py`.

Push (Expo) delivers to the companion mobile app. Push is enabled in production (live `enabled: true`, `tokens: ["${EXPO_PUSH_TOKEN}"]`; the token value comes from `/etc/sentinel/sentinel.env`). The Pydantic default is `enabled: false`, `tokens: []`, and the template ships the block disabled.

`AlertStateMachine.process_event` sends a push in three cases:

- the resolved 5–8 tier `channel` is `push` or `both`;
- additively on the urgency 9–10 `phone_call` path (the call is never replaced);
- for an already-acknowledged event whose `notification_revision` increased (incident-memory escalation), together with the update SMS.

The push is sent before any Twilio dispatch. It runs after the acknowledged gate and the pending-call gate. Each channel (SMS, push) is suppressed only by its own successful delivery (`sent`, `delivered` or `acknowledged`) of the current `notification_revision`, so a failed push stays retryable. A push does not suppress an SMS.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | `false` | Enable Expo push dispatch. Template: `false`. |
| `tokens` | list[str] | `["${EXPO_PUSH_TOKEN}"]` | `[]` | Expo push tokens, referenced from the env. Surfaced by the `mobile/` companion app. Template: `[]`. |

`EXPO_ACCESS_TOKEN` — when set, `ExpoPushClient` sends it as a bearer token to `https://exp.host/--/api/v2/push/send`. It is optional in code but required in production: the Expo project has Enhanced Security for Push Notifications enabled, so sends without it are rejected. If the robot token leaks, it is rotated in the Expo dashboard and updated in `/etc/sentinel/sentinel.env`.

---

## `scheduler` — `SchedulerConfig`

Consumed by: `sentinel/scheduler.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `interval_minutes` | int | `15` | `15` | Slow-lane interval: all enabled sources |
| `fast_interval_minutes` | int | `3` | `3` | Fast-lane interval: Telegram + priority-1 RSS + Google News |
| `jitter_seconds` | int | `30` | `30` | Random delay of 0..N seconds added to each run (never early). The fast lane caps it at 10 s; the slow lane uses the full value. |

Fast lane sources: all Telegram channels, all `priority: 1` RSS feeds, all Google News queries.
Slow lane: all **enabled** sources (superset of the fast lane). GDELT would run in the slow lane but
is disabled (`sources.gdelt.enabled: false`), and its fetcher is only instantiated when enabled.

---

## `processing` — `ProcessingConfig` / `ProcessingDedup`

Consumed by: `sentinel/processing/deduplicator.py`

These fuzzy title thresholds are skipped while `classification.incident_memory.enabled` is `true` (live), so they are inert in production. Exact URL dedup runs on both paths.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `processing.dedup.same_source_title_threshold` | int | `85` | `85` | Fuzzy match % to deduplicate same-source articles |
| `processing.dedup.cross_source_title_threshold` | int | `95` | `95` | Fuzzy match % to deduplicate cross-source articles |
| `processing.dedup.lookback_minutes` | int | `60` | `60` | How far back to scan for fuzzy duplicates |

---

## `database` — `DatabaseConfig`

Consumed by: `sentinel/database.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `path` | str | `/var/lib/sentinel/sentinel.db` | `data/sentinel.db` | SQLite file path |
| `article_retention_days` | int | `30` | `30` | Purge articles older than N days |
| `event_retention_days` | int | `90` | `90` | Purge events older than N days |

---

## `logging` — `LoggingConfig`

Consumed by: `sentinel/logging_setup.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `level` | str | `INFO` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `file` | str | `/var/log/sentinel/sentinel.log` | `logs/sentinel.log` | Log file path |
| `max_size_mb` | int | `50` | `50` | Rotate when file exceeds this size |
| `backup_count` | int | `5` | `5` | Rotated log files to retain |

---

## `testing` — `TestingConfig`

Consumed by: `sentinel/alerts/dispatcher.py` and `sentinel/classification/corroborator.py` (`dry_run`), and `sentinel.py` (`dry_run`, `eval_set_file`).

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `dry_run` | bool | `false` | `false` | Suppresses all event alert delivery (call, SMS, push); system-health SMS are not suppressed. Also set by the `--dry-run` CLI flag |
| `eval_set_file` | str | (omitted → `tests/fixtures/eval_set.yaml`) | `tests/fixtures/eval_set.yaml` | Default YAML eval set used by `--eval` (no path arg) for classification-accuracy checks |

`dry_run` suppresses all event alert delivery (Twilio call/SMS and Expo push) and marks events `alert_status: dry_run`. Fetching and classification still run and still spend model API money. The pending-call check still polls Twilio for the status of calls placed earlier. System-health SMS (repeated fetcher or pipeline failures, sent by `_send_system_sms` in `sentinel/scheduler.py`) are not suppressed.

---

## See also

- [CLI Reference](cli.md) — every `sentinel.py` and dashboard flag.
- [Media Sources Reference](sources.md) — the source lists this config drives.
- [Testing how-to](../how-to/testing.md) — dry run, fixtures, the eval harness.
