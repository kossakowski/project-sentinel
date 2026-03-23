# Phase 1: Infrastructure

## Objective
Set up the project skeleton: config loading with validation, SQLite database with schema, data models, logging, and the CLI entry point.

## Deliverables

### 1.1 Configuration System (`sentinel/config.py`)

The config loader must:
- Load `config/config.yaml` using PyYAML
- Validate all fields using Pydantic models
- Substitute `${ENV_VAR}` references with values from `.env` / environment
- Fail fast with clear error messages if required config is missing or invalid
- Provide typed access to all config values (no `config["sources"]["rss"][0]["url"]` string access)

#### Pydantic Models

```python
class RSSSource(BaseModel):
    name: str
    url: HttpUrl
    language: str  # "pl", "en", "uk", "ru"
    enabled: bool = True
    priority: int = 2  # 1=highest, 3=lowest

class GDELTConfig(BaseModel):
    enabled: bool = True
    update_interval_minutes: int = 15
    themes: list[str]
    cameo_codes: list[str]
    goldstein_threshold: float = -7.0

class GoogleNewsQuery(BaseModel):
    query: str
    language: str

class GoogleNewsConfig(BaseModel):
    enabled: bool = True
    queries: list[GoogleNewsQuery]

class TelegramChannel(BaseModel):
    name: str
    channel_id: str
    language: str
    priority: int = 1

class TelegramConfig(BaseModel):
    enabled: bool = True
    api_id: int  # From ${TELEGRAM_API_ID}
    api_hash: str  # From ${TELEGRAM_API_HASH}
    session_name: str = "sentinel"
    channels: list[TelegramChannel]

class SourcesConfig(BaseModel):
    rss: list[RSSSource]
    gdelt: GDELTConfig
    google_news: GoogleNewsConfig
    telegram: TelegramConfig

class KeywordSet(BaseModel):
    critical: list[str] = []
    high: list[str] = []

class MonitoringConfig(BaseModel):
    target_countries: list[dict]  # [{code, name, name_native}]
    aggressor_countries: list[dict]
    keywords: dict[str, KeywordSet]  # keyed by language code
    exclude_keywords: dict[str, list[str]]

class UrgencyLevel(BaseModel):
    min_score: int
    action: str  # "phone_call", "sms", "whatsapp", "log_only"
    corroboration_required: int = 1
    retry_attempts: int = 0
    retry_interval_minutes: int = 5
    fallback: str | None = None

class AcknowledgmentConfig(BaseModel):
    call_duration_threshold_seconds: int = 15
    max_call_retries: int = 3
    retry_interval_minutes: int = 5
    cooldown_hours: int = 6

class AlertsConfig(BaseModel):
    phone_number: str  # From ${ALERT_PHONE_NUMBER}
    language: str = "pl"
    urgency_levels: dict[str, UrgencyLevel]
    acknowledgment: AcknowledgmentConfig

class ClassificationConfig(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    temperature: float = 0.0
    corroboration_required: int = 2
    corroboration_window_minutes: int = 60

class SchedulerConfig(BaseModel):
    interval_minutes: int = 15
    jitter_seconds: int = 30

class DatabaseConfig(BaseModel):
    path: str = "data/sentinel.db"
    article_retention_days: int = 30
    event_retention_days: int = 90

class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/sentinel.log"
    max_size_mb: int = 50
    backup_count: int = 5

class TestingConfig(BaseModel):
    dry_run: bool = False
    test_mode: bool = False
    test_headlines_file: str = "tests/fixtures/test_headlines.yaml"

class SentinelConfig(BaseModel):
    monitoring: MonitoringConfig
    sources: SourcesConfig
    classification: ClassificationConfig
    alerts: AlertsConfig
    scheduler: SchedulerConfig
    database: DatabaseConfig
    logging: LoggingConfig
    testing: TestingConfig
```

#### Environment Variable Substitution

Config values containing `${VAR_NAME}` must be replaced with the corresponding environment variable. This allows secrets to stay in `.env` while the config structure lives in YAML.

Example in YAML:
```yaml
alerts:
  phone_number: "${ALERT_PHONE_NUMBER}"
```

Implementation: walk the parsed YAML dict recursively, find all `${...}` patterns, replace with `os.environ[VAR_NAME]`, raise `ConfigError` if the env var is not set.

### 1.2 Database (`sentinel/database.py`)

SQLite database with the following tables:

```sql
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    language TEXT NOT NULL,
    published_at TEXT NOT NULL,  -- ISO 8601 UTC
    fetched_at TEXT NOT NULL,    -- ISO 8601 UTC
    url_hash TEXT NOT NULL,      -- SHA-256 of source_url for fast dedup
    title_normalized TEXT NOT NULL,  -- lowercase, stripped, for fuzzy dedup
    raw_metadata TEXT            -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_title_normalized ON articles(title_normalized);

CREATE TABLE IF NOT EXISTS classifications (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    is_military_event INTEGER NOT NULL,  -- 0 or 1
    event_type TEXT,
    urgency_score INTEGER NOT NULL,
    affected_countries TEXT,  -- JSON array
    aggressor TEXT,
    is_new_event INTEGER NOT NULL,
    confidence REAL NOT NULL,
    summary_pl TEXT,
    classified_at TEXT NOT NULL,
    model_used TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER
);

CREATE INDEX IF NOT EXISTS idx_classifications_article_id ON classifications(article_id);
CREATE INDEX IF NOT EXISTS idx_classifications_urgency ON classifications(urgency_score);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    urgency_score INTEGER NOT NULL,
    affected_countries TEXT NOT NULL,  -- JSON array
    aggressor TEXT,
    summary_pl TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 1,
    article_ids TEXT NOT NULL,  -- JSON array
    alert_status TEXT NOT NULL DEFAULT 'pending',
    acknowledged_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_alert_status ON events(alert_status);
CREATE INDEX IF NOT EXISTS idx_events_first_seen ON events(first_seen_at);

CREATE TABLE IF NOT EXISTS alert_records (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    alert_type TEXT NOT NULL,  -- "phone_call", "sms", "whatsapp"
    twilio_sid TEXT,
    status TEXT NOT NULL,
    duration_seconds INTEGER,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    sent_at TEXT NOT NULL,
    message_body TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_event_id ON alert_records(event_id);
```

#### Database Access Layer

Provide a `Database` class with methods:
- `__init__(self, db_path: str)` -- create DB file and tables if not exist
- `insert_article(self, article: Article) -> bool` -- returns False if duplicate URL hash
- `article_exists(self, url_hash: str) -> bool`
- `get_recent_titles(self, since_minutes: int) -> list[tuple[str, str]]` -- for fuzzy dedup
- `insert_classification(self, result: ClassificationResult)`
- `insert_event(self, event: Event)`
- `update_event(self, event_id: str, **kwargs)`
- `get_active_events(self, within_hours: int) -> list[Event]` -- events not yet expired
- `insert_alert_record(self, record: AlertRecord)`
- `get_alert_records(self, event_id: str) -> list[AlertRecord]`
- `cleanup_old_records(self, article_days: int, event_days: int)` -- retention policy

All datetime values stored as ISO 8601 UTC strings. Use `datetime.utcnow().isoformat()`.

### 1.3 Data Models (`sentinel/models.py`)

Python dataclasses (or Pydantic models) for:
- `Article`
- `ClassificationResult`
- `Event`
- `AlertRecord`

As defined in [architecture.md](architecture.md) section 4. Each model must have:
- `to_dict()` method for DB insertion
- `from_dict()` classmethod for DB retrieval
- `from_row()` classmethod for SQLite row conversion

### 1.4 Logging Setup

Use Python's `logging` module with `RotatingFileHandler`:
- Log to file (`logs/sentinel.log`) and stdout
- Configurable level from config
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Each component gets its own named logger (`sentinel.fetcher.rss`, `sentinel.classifier`, etc.)
- Rotate at configurable max size, keep configurable backup count

### 1.5 CLI Entry Point (`sentinel.py`)

```
usage: sentinel.py [-h] [--dry-run] [--test-headline TEXT]
                   [--test-file FILE] [--config PATH] [--once]
                   [--log-level LEVEL] [--health] [--diagnostic]
                   [--test-alert [TYPE]]

Project Sentinel - Military Alert Monitoring System

options:
  --dry-run            Run pipeline but don't send any Twilio alerts (log only)
  --test-headline TEXT Feed a single headline through the classifier and print result
  --test-file FILE     Feed all headlines from a YAML file through the classifier
  --config PATH        Path to config file (default: config/config.yaml)
  --once               Run the pipeline once and exit (don't schedule)
  --log-level LEVEL    Override config log level (DEBUG, INFO, WARNING, ERROR)
  --health             Print health status and exit
  --diagnostic         Run one cycle and generate an HTML diagnostic report
  --test-alert [TYPE]  Fire a real test alert through Twilio (default: phone_call).
                       Choices: phone_call, sms, whatsapp. Bypasses fetching,
                       classification, and corroboration.
  -h, --help           Show this help message
```

In Phase 1, the CLI only needs to:
- Parse arguments
- Load and validate config
- Initialize database
- Set up logging
- Print "Project Sentinel initialized successfully" and exit

The actual pipeline execution is wired in Phase 6.

## Acceptance Tests

### test_config.py
1. `test_load_valid_config` -- loads `config.example.yaml` successfully, all fields accessible
2. `test_missing_required_field` -- raises `ValidationError` with clear message
3. `test_env_var_substitution` -- `${VAR}` replaced with env var value
4. `test_missing_env_var` -- raises `ConfigError` when referenced env var is not set
5. `test_invalid_url` -- RSS source with malformed URL raises validation error
6. `test_defaults_applied` -- optional fields get default values
7. `test_disabled_source_skipped` -- sources with `enabled: false` are loadable but marked

### test_database.py
1. `test_create_tables` -- tables created on init, idempotent (can run twice)
2. `test_insert_article` -- article inserted and retrievable
3. `test_duplicate_article_rejected` -- same URL hash returns False
4. `test_get_recent_titles` -- returns titles from last N minutes only
5. `test_insert_classification` -- classification linked to article
6. `test_insert_event` -- event inserted with article IDs
7. `test_update_event` -- event fields updated correctly
8. `test_get_active_events` -- returns only events within time window
9. `test_cleanup_old_records` -- records older than retention period deleted
10. `test_concurrent_access` -- no corruption with rapid sequential writes

### test_models.py
1. `test_article_to_dict_roundtrip` -- Article -> dict -> Article preserves all fields
2. `test_classification_to_dict_roundtrip` -- same for ClassificationResult
3. `test_event_to_dict_roundtrip` -- same for Event
4. `test_alert_record_to_dict_roundtrip` -- same for AlertRecord

### test_cli.py
1. `test_dry_run_flag` -- `--dry-run` sets `testing.dry_run = True`
2. `test_custom_config_path` -- `--config` overrides default path
3. `test_help_exits_cleanly` -- `--help` prints usage and exits 0
4. `test_invalid_config_exits` -- bad config path exits with error message

## Dependencies Added

```
pyyaml>=6.0
pydantic>=2.0
```
(Added to `requirements.txt` alongside existing deps)
