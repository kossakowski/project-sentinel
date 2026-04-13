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
| `TWILIO_WHATSAPP_NUMBER` | WhatsApp channel (format: `whatsapp:+…`); defaults to `whatsapp:{TWILIO_PHONE_NUMBER}` if not set | no |
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

Live priority-1 feeds: TVN24, RMF24, Defence24 PL, Ukrainska Pravda EN, Kyiv Independent, Ukrainska Pravda UA.
`keyword_bypass: true` on: Defence24 PL, Defence24 EN.
PAP disabled (Incapsula WAF); routed via `google_news` `site:pap.pl` query.

### `sources.gdelt` — `GDELTConfig`

Consumed by: `sentinel/fetchers/gdelt.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | `true` | Enable GDELT DOC 2.0 fetcher |
| `update_interval_minutes` | int | `15` | `15` | TIMESPAN window for GDELT query |
| `themes` | list[str] | `[ARMEDCONFLICT, WB_2462_POLITICAL_VIOLENCE_AND_WAR, CRISISLEX_C03_WELLBEING_HEALTH, TAX_FNCACT_MILITARY]` | required | GKG theme codes |
| `cameo_codes` | list[str] | `[18,19,190–195,20]` | required | CAMEO event codes (assault/fight/force/blockade/occupy/arms/artillery/aerial/mass violence) |
| `goldstein_threshold` | float | `-7.0` | `-7.0` | Include only events with Goldstein score ≤ this |

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

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `model` | str | `claude-haiku-4-5-20251001` | `claude-haiku-4-5-20251001` | Anthropic model ID |
| `max_tokens` | int | `512` | `512` | Max output tokens per classification call |
| `temperature` | float | `0.0` | `0.0` | LLM temperature (0 = deterministic) |
| `corroboration_required` | int | `1` | `2` | Min independent sources to form an event; live config overrides Pydantic default |
| `corroboration_window_minutes` | int | `60` | `60` | Time window for grouping articles into a single event |

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
| `medium` | 5 | `whatsapp` (routed to `sms` in code) | 1 | 0 | 5 | — |
| `low` | 1 | `log_only` | 1 | 0 | 5 | — |

`action` values: `phone_call`, `sms`, `whatsapp`, `log_only`.

### `alerts.acknowledgment` — `AcknowledgmentConfig`

Acknowledgment via SMS 6-digit code reply. An SMS with the code is sent before the first call attempt; inbound SMS is polled for the reply after each call attempt.

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `call_duration_threshold_seconds` | int | `15` | `15` | Call shorter than this = voicemail → retry |
| `max_call_retries` | int | `5` | `3` | Max call attempts before marking `retry_pending` |
| `retry_interval_minutes` | int | `5` | `5` | Wait between retry cycles |
| `cooldown_hours` | int | `6` | `6` | No re-call for same event within this window |

### `alerts.templates` — `AlertTemplates`

Python format strings. Override in config to customize; Pydantic provides defaults.

| Key | Placeholders | Description |
|---|---|---|
| `call` | `{event_type_pl}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | TTS text read aloud during phone call |
| `sms` | `{event_type_pl}`, `{urgency_score}`, `{affected_countries_str}`, `{aggressor}`, `{summary_pl}`, `{source_count}`, `{sources_list}`, `{first_seen_at_local}` | Initial SMS alert body |
| `sms_update` | `{event_type_pl}`, `{new_source_name}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` | SMS for new sources corroborating an acknowledged event |

---

## `scheduler` — `SchedulerConfig`

Consumed by: `sentinel/scheduler.py`

| YAML key | Type | Live value | Pydantic default | Description |
|---|---|---|---|---|
| `interval_minutes` | int | `15` | `15` | Slow-lane interval: all sources including GDELT |
| `fast_interval_minutes` | int | `3` | `3` | Fast-lane interval: Telegram + priority-1 RSS + Google News |
| `jitter_seconds` | int | `30` | `30` | Random ±offset applied to each scheduled run |

Fast lane sources: all Telegram channels, all `priority: 1` RSS feeds, all Google News queries.
Slow lane: all sources (superset of fast lane, including GDELT).

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
| `test_mode` | bool | `false` | `false` | Use fixture headlines instead of live sources |
| `test_headlines_file` | str | `tests/fixtures/test_headlines.yaml` | same | Path to test headlines YAML for `--test-file` |

`dry_run` runs the complete classification pipeline — only the Twilio dispatch step is skipped. Safe for development and continuous testing.
