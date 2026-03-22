# Configuration Reference

All configuration lives in `config/config.yaml`. Secrets are referenced via `${ENV_VAR}` syntax and loaded from `.env`.

## Environment Variables (`.env`)

These must be set in `.env` (never in `config.yaml`):

| Variable | Description | Example |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID | `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `TWILIO_PHONE_NUMBER` | Twilio phone number (outbound caller ID) | `+12025551234` |
| `TWILIO_WHATSAPP_NUMBER` | Twilio WhatsApp sender | `whatsapp:+14155238886` |
| `ALERT_PHONE_NUMBER` | Your phone number (receives alerts) | `+48XXXXXXXXX` |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | `sk-ant-xxxxx` |
| `TELEGRAM_API_ID` | Telegram API ID (from my.telegram.org) | `12345678` |
| `TELEGRAM_API_HASH` | Telegram API hash | `abcdef1234567890abcdef1234567890` |

## Config Sections

### `monitoring`

Controls **what** you're monitoring for.

#### `monitoring.target_countries`

Countries you're monitoring for attacks on.

```yaml
monitoring:
  target_countries:
    - code: PL        # ISO 3166-1 alpha-2
      name: Poland    # English name (for logs/display)
      name_native: Polska  # Native name (for Polish alerts)
    - code: LT
      name: Lithuania
      name_native: Litwa
    - code: LV
      name: Latvia
      name_native: Łotwa
    - code: EE
      name: Estonia
      name_native: Estonia
```

#### `monitoring.aggressor_countries`

Potential aggressors. Used in classification prompt context.

```yaml
  aggressor_countries:
    - code: RU
      name: Russia
      name_native: Rosja
    - code: BY
      name: Belarus
      name_native: Białoruś
```

#### `monitoring.keywords`

Keyword lists by language. Each language has `critical` and `high` severity levels.

```yaml
  keywords:
    en:
      critical:
        - "military attack"
        - "invasion"
        # ... (see config.example.yaml for full list)
      high:
        - "military buildup"
        - "troops massing"
        # ...
    pl:
      critical:
        - "atak wojskowy"
        - "inwazja"
        # ...
      high:
        - "koncentracja wojsk"
        # ...
    uk:
      critical:
        - "військовий напад"
        # ...
      high:
        - "порушення повітряного простору"
        # ...
    ru:
      critical:
        - "военная операция"
        # ...
      high:
        - "провокация"
        # ...
```

**Rules:**
- Keywords are matched case-insensitively
- `critical` keywords override `exclude_keywords` (an article with both "inwazja" and "ćwiczenia" still passes)
- `high` keywords do NOT override `exclude_keywords`
- For PL/UK/RU: substring matching (stems, due to grammatical inflection)
- For EN: word-boundary matching preferred

#### `monitoring.exclude_keywords`

Articles matching these keywords (and no `critical` keyword) are filtered out.

```yaml
  exclude_keywords:
    en:
      - "exercise"
      - "drill"
      - "simulation"
      # ...
    pl:
      - "ćwiczenia"
      - "manewry"
      # ...
```

---

### `sources`

Controls **where** you scan.

#### `sources.rss`

List of RSS feeds to poll.

```yaml
sources:
  rss:
    - name: PAP              # Display name (used in logs and alerts)
      url: https://www.pap.pl/rss.xml
      language: pl            # Expected language of articles
      enabled: true           # Set false to disable without removing
      priority: 1             # 1=highest, 3=lowest (affects corroboration weight)
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | -- | Human-readable source name |
| `url` | URL | yes | -- | RSS/Atom feed URL |
| `language` | string | yes | -- | ISO 639-1 language code |
| `enabled` | bool | no | `true` | Whether to poll this feed |
| `priority` | int | no | `2` | Source priority (1-3) |

#### `sources.gdelt`

GDELT DOC 2.0 API configuration.

```yaml
  gdelt:
    enabled: true
    update_interval_minutes: 15
    themes:
      - ARMEDCONFLICT
      - WB_2462_POLITICAL_VIOLENCE_AND_WAR
      - CRISISLEX_C03_WELLBEING_HEALTH
      - TAX_FNCACT_MILITARY
    cameo_codes:
      - "18"    # ASSAULT
      - "19"    # FIGHT
      - "190"   # Use conventional military force
      - "191"   # Impose blockade
      - "192"   # Occupy territory
      - "193"   # Fight with small arms
      - "194"   # Fight with artillery/tanks
      - "195"   # Employ aerial weapons
      - "20"    # UNCONVENTIONAL MASS VIOLENCE
    goldstein_threshold: -7.0
```

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable GDELT fetcher |
| `update_interval_minutes` | int | `15` | TIMESPAN for GDELT query |
| `themes` | list[str] | -- | GKG theme codes to filter by |
| `cameo_codes` | list[str] | -- | CAMEO event codes to filter by |
| `goldstein_threshold` | float | `-7.0` | Only events with Goldstein score below this |

#### `sources.google_news`

Google News RSS keyword search feeds.

```yaml
  google_news:
    enabled: true
    queries:
      - query: "military attack Poland"
        language: en
      - query: "atak wojskowy Polska"
        language: pl
```

| Field | Type | Description |
|---|---|---|
| `query` | string | Search keywords |
| `language` | string | Language/country for Google News localization |

#### `sources.telegram`

Telegram channel monitoring.

```yaml
  telegram:
    enabled: true
    channels:
      - name: Ukrainian Air Force
        channel_id: "@kpszsu"
        language: uk
        priority: 1
      - name: NEXTA
        channel_id: "@nexta_live"
        language: en
        priority: 1
```

**Note:** `api_id` and `api_hash` come from environment variables, not from config.yaml.

---

### `processing`

Controls deduplication behavior.

```yaml
processing:
  dedup:
    same_source_title_threshold: 85
    cross_source_title_threshold: 95
    lookback_minutes: 60
```

| Field | Type | Default | Description |
|---|---|---|---|
| `same_source_title_threshold` | int | `85` | Fuzzy match % for same-source duplicate detection |
| `cross_source_title_threshold` | int | `95` | Fuzzy match % for cross-source duplicate detection |
| `lookback_minutes` | int | `60` | How far back to check for fuzzy duplicates |

---

### `classification`

Controls the LLM classification engine.

```yaml
classification:
  model: claude-haiku-4-5-20251001
  max_tokens: 512
  temperature: 0.0
  corroboration_required: 2
  corroboration_window_minutes: 60
```

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | `claude-haiku-4-5-20251001` | Anthropic model ID |
| `max_tokens` | int | `512` | Max output tokens per classification |
| `temperature` | float | `0.0` | LLM temperature (0=deterministic) |
| `corroboration_required` | int | `2` | Min independent sources for phone call |
| `corroboration_window_minutes` | int | `60` | Time window for grouping articles into events |

---

### `alerts`

Controls alert dispatch, thresholds, acknowledgment, and message templates.

```yaml
alerts:
  phone_number: "${ALERT_PHONE_NUMBER}"
  language: pl
  urgency_levels:
    critical:
      min_score: 9
      action: phone_call
      corroboration_required: 2
      retry_attempts: 3
      retry_interval_minutes: 5
      fallback: sms
    high:
      min_score: 7
      action: sms
      corroboration_required: 1
    medium:
      min_score: 5
      action: whatsapp
      corroboration_required: 1
    low:
      min_score: 1
      action: log_only
  templates:
    call: "{event_type_pl} wykryte. {summary_pl}. Źródła potwierdzające: {source_count}. Pilność: {urgency_score} na 10."
    sms: "... (see config.example.yaml for full default)"
    sms_update: "... (see config.example.yaml for full default)"
  acknowledgment:
    call_duration_threshold_seconds: 15
    max_call_retries: 3
    retry_interval_minutes: 5
    cooldown_hours: 6
```

#### Urgency Level Fields

| Field | Type | Description |
|---|---|---|
| `min_score` | int | Minimum urgency score for this level |
| `action` | string | `phone_call`, `sms`, `whatsapp`, or `log_only` |
| `corroboration_required` | int | Min sources needed to trigger this action |
| `retry_attempts` | int | How many times to retry if call fails |
| `retry_interval_minutes` | int | Wait between retries |
| `fallback` | string | Action if all retries fail |

#### Template Fields

Alert message templates are Python format strings with named placeholders. Defaults are built into the `AlertTemplates` Pydantic model; override them in config to customize.

| Field | Type | Default | Description |
|---|---|---|---|
| `call` | string | `"{event_type_pl} wykryte. {summary_pl}. ..."` | Phone call TTS message. Placeholders: `{event_type_pl}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` |
| `sms` | string | (see `config.example.yaml`) | SMS alert body. Placeholders: `{event_type_pl}`, `{urgency_score}`, `{affected_countries_str}`, `{aggressor}`, `{summary_pl}`, `{source_count}`, `{sources_list}`, `{first_seen_at_local}` |
| `sms_update` | string | (see `config.example.yaml`) | SMS update for acknowledged events. Placeholders: `{event_type_pl}`, `{new_source_name}`, `{summary_pl}`, `{source_count}`, `{urgency_score}` |

#### Acknowledgment Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `call_duration_threshold_seconds` | int | `15` | Call duration to consider "answered" |
| `max_call_retries` | int | `3` | Max call attempts before SMS fallback |
| `retry_interval_minutes` | int | `5` | Wait between call retries |
| `cooldown_hours` | int | `6` | No re-call for same event within this period |

---

### `scheduler`

```yaml
scheduler:
  interval_minutes: 15
  jitter_seconds: 30
```

| Field | Type | Default | Description |
|---|---|---|---|
| `interval_minutes` | int | `15` | Pipeline execution interval |
| `jitter_seconds` | int | `30` | Random offset added/subtracted to interval |

---

### `database`

```yaml
database:
  path: data/sentinel.db
  article_retention_days: 30
  event_retention_days: 90
```

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | string | `data/sentinel.db` | SQLite database file path |
| `article_retention_days` | int | `30` | Delete articles older than this |
| `event_retention_days` | int | `90` | Delete events older than this |

---

### `logging`

```yaml
logging:
  level: INFO
  file: logs/sentinel.log
  max_size_mb: 50
  backup_count: 5
```

| Field | Type | Default | Description |
|---|---|---|---|
| `level` | string | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `file` | string | `logs/sentinel.log` | Log file path |
| `max_size_mb` | int | `50` | Max log file size before rotation |
| `backup_count` | int | `5` | Number of rotated log files to keep |

---

### `testing`

```yaml
testing:
  dry_run: false
  test_mode: false
  test_headlines_file: tests/fixtures/test_headlines.yaml
```

| Field | Type | Default | Description |
|---|---|---|---|
| `dry_run` | bool | `false` | Log alerts but don't call Twilio (also set via `--dry-run` CLI flag) |
| `test_mode` | bool | `false` | Use test fixtures instead of live sources |
| `test_headlines_file` | string | `tests/fixtures/test_headlines.yaml` | Path to test headlines YAML |
