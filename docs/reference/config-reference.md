# Config Reference — Project Sentinel

## Config Loading

| Item | Value |
|---|---|
| File | `config/config.yaml` (override via `--config PATH`) |
| Env var syntax | `${VAR_NAME}` — expanded at load time; missing var raises `ConfigError` |
| Loader | `sentinel/config.py:load_config()` → returns `SentinelConfig` |
| `.env` | Auto-loaded via `python-dotenv` before substitution |
| Top-level model | `SentinelConfig` (wraps all sections below) |

---

## Required Environment Variables

| Variable | Used by | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Classification engine (`sentinel/classification/classifier.py`) | yes |
| `TWILIO_ACCOUNT_SID` | Alert dispatcher (`sentinel/alerts/dispatcher.py`) | yes |
| `TWILIO_AUTH_TOKEN` | Alert dispatcher | yes |
| `TWILIO_PHONE_NUMBER` | Outbound caller ID | yes |
| `ALERT_PHONE_NUMBER` | Destination for all alerts (`alerts.phone_number`) | yes |
| `TELEGRAM_API_ID` | Telegram fetcher (`sentinel/fetchers/telegram.py`) | yes if telegram enabled |
| `TELEGRAM_API_HASH` | Telegram fetcher | yes if telegram enabled |

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
| `priority` | int | `2` | 1=fast lane + highest corroboration weight; 2–3=slow lane only |
| `keyword_bypass` | bool | `false` | Skip keyword filter; send all articles to AI classification |

Live **enabled** priority-1 feeds: RMF24, Defence24 PL, Ukrainska Pravda UA, Ukrainska Pravda EN, Kyiv Independent.
`keyword_bypass: true` on: Defence24 PL, Defence24 EN (only).
PAP and TVN24 are priority-1 but **`enabled: false`** — PAP is blocked by an Incapsula/Imperva WAF (routed via the `google_news` `site:pap.pl` query instead); TVN24 was disabled 2026-05-27 (Cloudflare blocks the Hetzner datacenter IP).

### `sources.gdelt` — `GDELTConfig`

Consumed by: `sentinel/fetchers/gdelt.py`

**GDELT is DISABLED in production** (`enabled: false`) due to IP-level 429 throttling (~20% success rate from the Hetzner datacenter IP). The fetcher is only instantiated when enabled, so the slow lane "would" include GDELT but currently does not.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | **`false`** | `true` | Enable GDELT DOC 2.0 fetcher. Off in production. |
| `lookback_minutes` | int | (omitted → `60`) | `60` | `TIMESPAN` window (minutes) for the GDELT DOC 2.0 query. Sent as `TIMESPAN={lookback_minutes}min`. Must be ≥ ~30 — the API rejects shorter spans with `200 OK` + plain-text body `"Timespan is too short."` (logged as an ERROR). |
| `themes` | list[str] | `[ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, TAX_FNCACT_MILITARY]` | required | GKG theme codes; OR-combined with the target-country `sourcecountry:` filter to build the query. |

> ⚠ **Stale key in live config:** `config/config.yaml` contains `sources.gdelt.update_interval_minutes: 15`. There is **no such Pydantic field** — Pydantic ignores unknown keys, so it is a **silent no-op**. The real field is `lookback_minutes` (omitted in the live config, so GDELT would fall back to the `60` default if re-enabled). Do not mistake `update_interval_minutes` for a working setting.

### `sources.google_news` — `GoogleNewsConfig`

Consumed by: `sentinel/fetchers/google_news.py`

| YAML key | Type | Pydantic default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable Google News RSS fetcher |
| `queries` | list[GoogleNewsQuery] | required | List of `{query: str, language: str}` pairs |

Live: 16 queries across `en`, `pl`, `uk`. Includes `site:pap.pl` as PAP fallback.

### `sources.telegram` — `TelegramConfig`

Consumed by: `sentinel/fetchers/telegram.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | `true` | Enable Telegram MTProto fetcher |
| `api_id` | int | `${TELEGRAM_API_ID}` | `None` | From env; required when enabled |
| `api_hash` | str | `${TELEGRAM_API_HASH}` | `None` | From env; required when enabled |
| `session_name` | str | `/var/lib/sentinel/sentinel_session` | `"sentinel"` | Telethon session file path |
| `channels` | list[TelegramChannel] | see below | `[]` | Channels to monitor |

`TelegramChannel` fields: `name` (str), `channel_id` (str, e.g. `@kpszsu`), `language` (str), `priority` (int, default `1`), `keyword_bypass` (bool, default `false`).

Live channels (all `keyword_bypass: true`):

| Name | channel_id | lang | priority |
|---|---|---|---|
| Ukrainian Air Force | `@kpszsu` | uk | 1 |
| General Staff of Ukraine | `@GeneralStaffZSU` | uk | 1 |
| NEXTA Live | `@nexta_live` | ru | 1 |
| DeepState UA | `@DeepStateUA` | uk | 2 |

---

## `monitoring` — `MonitoringConfig`

Consumed by: `sentinel/scheduler.py`, `sentinel/classification/classifier.py`

| YAML key | Type | Description |
|---|---|---|
| `target_countries` | list[dict] | Countries monitored for attack. Each: `{code, name, name_native}` |
| `aggressor_countries` | list[dict] | Potential aggressors injected into classification prompt context |
| `keywords` | dict[str, KeywordSet] | Per-language keyword lists; structure: `{lang: {critical: [], high: []}}` |
| `exclude_keywords` | dict[str, list[str]] | Per-language exclusion terms |

Live `target_countries`: PL, LT, LV, EE. Live `aggressor_countries`: RU, BY.

**Keyword matching rules:**
- `critical` keywords: case-insensitive; override `exclude_keywords` (article passes even if both match)
- `high` keywords: case-insensitive; do NOT override `exclude_keywords`
- PL/UK/RU: substring matching (handles inflection); EN: word-boundary preferred
- `exclude_keywords` only filtered when no `critical` keyword matches

Live keyword languages: `en`, `pl`, `uk`, `ru`. Live `exclude_keywords` languages: `en`, `pl`.

---

## `classification` — `ClassificationConfig`

Consumed by: `sentinel/classification/classifier.py`

Consumed by: `sentinel/classification/classifier.py` (LLM call) and `sentinel/classification/corroborator.py` (event grouping / corroboration).

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `model` | str | `claude-haiku-4-5-20251001` | `claude-haiku-4-5-20251001` | Anthropic model ID. Also used by the enricher's vagueness/quality gate. |
| `max_tokens` | int | `512` | `512` | Max output tokens per classification call |
| `temperature` | float | `0.0` | `0.0` | LLM temperature (0 = deterministic) |
| `corroboration_required` | int | `1` | `2` | Min independent sources for a phone-call-eligible event. **Live config sets `1`**; the Pydantic default is `2`. (The per-level `alerts.urgency_levels.*.corroboration_required` is the value the state machine actually gates on; this top-level key feeds the corroborator's alertable check.) |
| `corroboration_window_minutes` | int | `360` | `360` | **Sliding** window (minutes) for grouping a new article into an existing event, measured from that event's `last_updated_at` (its **last activity**), not `first_seen_at`. So a multi-hour incident that keeps drawing fresh articles stays ONE event. Live & default `360` (6h). |
| `corroboration_max_age_minutes` | int | `2880` | `2880` | Absolute lifetime cap (minutes) measured from `first_seen_at`. Once an event is older than this it stops absorbing articles — a fresh article spawns a NEW event — so a perpetually-updated event can't chain-merge genuinely distinct incidents. `0` disables the cap. Live & default `2880` (48h). |
| `summary_similarity_metric` | str | `token_set_ratio` | `token_set_ratio` | Which `rapidfuzz.fuzz` function compares a new summary to an existing event's summary. **Validated against an allow-list**: `ratio`, `partial_ratio`, `token_sort_ratio`, `token_set_ratio`, `WRatio`, `QRatio` (any other value raises `ConfigError` at load). `token_set_ratio` is length-robust — a short wire headline and a long elaboration of the same incident still score high — unlike the length-sensitive `token_sort_ratio`. |
| `summary_similarity_threshold` | int | `50` | `50` | Score (0-100) from the metric above, at/above which a new summary is treated as the same event. Lower = more aggressive merging. Live & default `50`. Tune in config without a code deploy. |
| `syndication_similarity_threshold` | int | `90` | `90` | Source-independence guard. A source counts as *independent* only if it is a different domain AND its (normalized) title similarity to an already-counted source is `< 90` (`fuzz.ratio`), checked across all source types to catch wire/syndication reuse. Range 0-100. |

**Event-grouping notes (corroborator):**
- **Sliding window + max-age cap together:** the 6h window is re-anchored on every update, so the 48h cap is what ultimately retires a long-running event.
- **Country gate:** at/above the phone-call urgency threshold (9), a match requires a concrete-country intersection — a Poland-critical article whose country wasn't extracted spawns its OWN event/call (empty/"unknown" does NOT relax the gate at critical urgency). Below the threshold, empty/"unknown" labels don't block a merge, but two concrete-but-different country sets (e.g. PL vs RO) stay separate. Countries are normalized (uppercased; blank/"unknown" dropped) on merge.
- **Critical-urgency safety guard:** a phone-call-eligible article is NEVER absorbed into an event that already has `acknowledged_at` set (already alerted / in cooldown). It forces a NEW event and a NEW call so a fresh escalation can't be silenced by an earlier event's cooldown.

---

## `alerts` — `AlertsConfig`

Consumed by: `sentinel/alerts/`

### Top-level alert fields

| YAML key | Type | Live value | Description |
|---|---|---|---|
| `phone_number` | str | `${ALERT_PHONE_NUMBER}` | Destination for all alert channels |
| `language` | str | `pl` | Alert language code |

### `alerts.urgency_levels` — `UrgencyLevel` (dict keyed by name)

| Level | `min_score` | `action` | `corroboration_required` | `retry_attempts` | `retry_interval_minutes` | `fallback` |
|---|---|---|---|---|---|---|
| `critical` | 9 | `phone_call` | 1 | 3 | 5 | `sms` |
| `high` | 7 | `sms` | 1 | 0 | 5 | — |
| `medium` | 5 | `sms` | 1 | 0 | 5 | — |
| `low` | 1 | `log_only` | 1 | 0 | 5 | — |

`action` values: `phone_call`, `sms`, `log_only`.

### `alerts.acknowledgment` — `AcknowledgmentConfig`

Acknowledgment via SMS 6-digit code reply. An SMS with the code is sent before the first call attempt; inbound SMS is polled for the reply after each call attempt.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `call_duration_threshold_seconds` | int | `15` | `15` | **Dead** — still defined but no longer read (the `if False:` block that used it was removed); superseded by SMS-code confirmation |
| `max_call_retries` | int | `5` | `3` | Max call attempts before marking `retry_pending` |
| `retry_interval_minutes` | int | `5` | `5` | Wait between retry cycles |
| `cooldown_hours` | int | `6` | `6` | No re-call for same event within this window |
| `call_poll_timeout_seconds` | int | `90` | `90` | Max seconds to wait for a placed call to finish (and for an SMS reply) before moving to the next attempt; read by `_wait_for_call_and_check_sms` |
| `call_poll_interval_seconds` | int | `5` | `5` | Seconds between Twilio call-status / inbound-SMS polls during the wait loop |
| `call_retry_pause_seconds` | int | `10` | `10` | Seconds to pause between call attempts within a single retry round |

The three poll/pause durations above were previously hardcoded; they are now config-driven (added with the alert-path async conversion). Configs that omit these keys still load and fall back to the defaults shown.

### `alerts.templates` — `AlertTemplates`

Python format strings. Override in config to customize; Pydantic provides defaults.

| Key | Placeholders | Description |
|---|---|---|
| `call` | `{event_type_pl}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | TTS text read aloud during phone call |
| `sms` | `{event_type_pl}`, `{urgency_score}`, `{affected_countries_str}`, `{aggressor}`, `{summary_pl}`, `{source_count}`, `{sources_list}`, `{first_seen_at_local}` | Initial SMS alert body |
| `sms_update` | `{event_type_pl}`, `{new_source_name}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | SMS for new sources corroborating an acknowledged event |

### `alerts.push` — `PushConfig`

Consumed by: `sentinel/alerts/push_client.py` (`ExpoPushClient`) via `sentinel/alerts/state_machine.py`.

Push (Expo) is an **additive, opt-in** channel for the companion mobile app. It fires *alongside* the phone call / SMS (before the Twilio dispatch, after the cooldown/dedup/suppression gates) for any non-`log_only` event — it never replaces the Twilio channels. A push does NOT suppress a later SMS (`push` is not in the user-notified-alert-types set). **The live `config/config.yaml` omits this block entirely, so push is OFF by default**; `config/config.example.yaml` ships it as a commented template.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | (omitted → `false`) | `false` | Enable Expo push dispatch |
| `tokens` | list[str] | (omitted → `[]`) | `[]` | Expo push tokens (e.g. `ExponentPushToken[...]`, or `${EXPO_PUSH_TOKEN}` from the env). Surfaced by the `mobile/` companion app. |

Optional env var: **`EXPO_ACCESS_TOKEN`** — when set, `ExpoPushClient` sends it as a bearer token to `https://exp.host/--/api/v2/push/send`. Not required for basic sends.

---

## `scheduler` — `SchedulerConfig`

Consumed by: `sentinel/scheduler.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `interval_minutes` | int | `15` | `15` | Slow-lane interval: all enabled sources (GDELT belongs here but is disabled in production) |
| `fast_interval_minutes` | int | `3` | `3` | Fast-lane interval: Telegram + priority-1 RSS + Google News |
| `jitter_seconds` | int | `30` | `30` | Random ±offset applied to each scheduled run |

Fast lane sources: all Telegram channels, all `priority: 1` RSS feeds, all Google News queries.
Slow lane: all **enabled** sources (superset of the fast lane). GDELT would run in the slow lane but
is currently disabled (`sources.gdelt.enabled: false`), and its fetcher is only instantiated when
enabled — so today the slow lane equals the fast-lane superset without GDELT.

---

## `processing` — `ProcessingConfig` / `ProcessingDedup`

Consumed by: `sentinel/processing/deduplicator.py`

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

Consumed by: `sentinel/scheduler.py`, `sentinel/alerts/`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `dry_run` | bool | `false` | `false` | Run full pipeline but suppress all Twilio calls/SMS; also set by `--dry-run` CLI flag |
| `eval_set_file` | str | (omitted → `tests/fixtures/eval_set.yaml`) | `tests/fixtures/eval_set.yaml` | Default YAML eval set used by `--eval` (no path arg) for classification-accuracy checks. **The live `config/config.yaml` omits this key**, so it falls back to the Pydantic default. |

`dry_run` runs the complete classification pipeline — only the Twilio dispatch step is skipped. Safe for development and continuous testing.

---

## See also

- [CLI Reference](cli.md) — every `sentinel.py` and dashboard flag.
- [Media Sources Reference](sources.md) — the source lists this config drives.
- [Testing how-to](../how-to/testing.md) — dry run, fixtures, the eval harness.
