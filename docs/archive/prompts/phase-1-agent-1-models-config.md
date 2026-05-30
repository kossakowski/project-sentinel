# Agent 1: Models & Configuration System

Use standard thinking.

## Your Task

Implement the data models and configuration system for the Project Sentinel project. You are writing foundational code that all other components depend on. Correctness and clean interfaces are critical.

**Working directory**: `/home/kossa/code/project-sentinel`

## Before You Start

Read these files to understand the full specification:
1. `docs/phase-1-infrastructure.md` -- sections 1.1 (Config) and 1.3 (Models)
2. `docs/architecture.md` -- section 4 (Data Models)
3. `config/config.example.yaml` -- the config file your loader must parse correctly

## Deliverables

### File 1: `sentinel/models.py`

Create Python dataclasses for the four core data models. These are runtime data objects, NOT config models (config models go in config.py).

**Article** -- represents a fetched news article:
- Fields: `id` (str, UUID), `source_name` (str), `source_url` (str), `source_type` (str), `title` (str), `summary` (str), `language` (str), `published_at` (datetime), `fetched_at` (datetime), `raw_metadata` (dict)
- Derived fields computed on creation: `url_hash` (SHA-256 hex of `source_url`), `title_normalized` (lowercase, stripped of accents and punctuation, collapsed whitespace)
- Methods: `to_dict() -> dict`, `from_dict(d: dict) -> Article` (classmethod), `from_row(row: sqlite3.Row) -> Article` (classmethod)
- Import `uuid4` for default id generation
- For `title_normalized`: use `unicodedata.normalize('NFKD', ...)` to strip accents, then remove non-alphanumeric (keep spaces), lowercase, collapse whitespace

**ClassificationResult** -- LLM classification output:
- Fields: `article_id` (str), `is_military_event` (bool), `event_type` (str), `urgency_score` (int), `affected_countries` (list[str]), `aggressor` (str), `is_new_event` (bool), `confidence` (float), `summary_pl` (str), `classified_at` (datetime), `model_used` (str), `input_tokens` (int), `output_tokens` (int)
- Auto-generate `id` (UUID)
- Methods: `to_dict()`, `from_dict()`, `from_row()`
- Lists (like `affected_countries`) stored as JSON strings in dict/DB

**Event** -- a corroborated real-world incident:
- Fields: `id` (str, UUID), `event_type` (str), `urgency_score` (int), `affected_countries` (list[str]), `aggressor` (str), `summary_pl` (str), `first_seen_at` (datetime), `last_updated_at` (datetime), `source_count` (int), `article_ids` (list[str]), `alert_status` (str, default "pending"), `acknowledged_at` (datetime | None)
- Methods: `to_dict()`, `from_dict()`, `from_row()`
- Lists stored as JSON strings

**AlertRecord** -- a sent alert log entry:
- Fields: `id` (str, UUID), `event_id` (str), `alert_type` (str), `twilio_sid` (str), `status` (str), `duration_seconds` (int | None), `attempt_number` (int), `sent_at` (datetime), `message_body` (str)
- Methods: `to_dict()`, `from_dict()`, `from_row()`

**Important implementation details:**
- Use `@dataclass` from `dataclasses` module, NOT Pydantic (Pydantic is for config validation only)
- `to_dict()` must convert datetimes to ISO 8601 strings and lists to JSON strings (for SQLite storage)
- `from_dict()` must reverse those conversions (parse ISO strings back to datetime, parse JSON strings back to lists)
- `from_row()` takes a `sqlite3.Row` (dict-like) and delegates to `from_dict()`
- Use `field(default_factory=...)` for mutable defaults
- For UUID generation: `field(default_factory=lambda: str(uuid4()))`
- Handle `None` values gracefully in `from_dict()` (some fields like `acknowledged_at`, `duration_seconds` can be None)

### File 2: `sentinel/config.py`

Create the configuration loading system with Pydantic validation.

**Part A: Pydantic Config Models**

Define all the config models listed in `docs/phase-1-infrastructure.md` section 1.1. Key models:
- `RSSSource`, `GDELTConfig`, `GoogleNewsQuery`, `GoogleNewsConfig`, `TelegramChannel`, `TelegramConfig`, `SourcesConfig`
- `KeywordSet`, `MonitoringConfig`
- `UrgencyLevel`, `AcknowledgmentConfig`, `AlertsConfig`
- `ClassificationConfig`, `SchedulerConfig`, `DatabaseConfig`, `LoggingConfig`, `TestingConfig`
- `ProcessingDedup`, `ProcessingConfig` (for dedup thresholds -- see `config.example.yaml` processing section)
- `SentinelConfig` (top-level, contains all sections)

Use `pydantic.BaseModel` for all config models. Use `pydantic.HttpUrl` for URL validation. Set sensible defaults where the spec defines them.

**Important:** The `TelegramConfig` model needs `api_id` and `api_hash` fields, but these come from env vars. When Telegram is disabled, these fields should be optional (use `int | None = None` and `str | None = None` with a validator that only requires them when `enabled=True`).

**Part B: Environment Variable Substitution**

Write a function `_substitute_env_vars(data: Any) -> Any` that:
1. Recursively walks the parsed YAML dict/list structure
2. For any string value matching `${VAR_NAME}`, replaces it with `os.environ["VAR_NAME"]`
3. Raises `ConfigError` (a custom exception you define) if the env var is not set
4. Handles partial substitution: `"prefix_${VAR}_suffix"` should also work
5. Uses `re.sub(r'\$\{([^}]+)\}', replacer, value)` for the replacement

**Part C: Config Loader**

```python
def load_config(config_path: str) -> SentinelConfig:
    """Load, validate, and return the Sentinel configuration."""
```

Steps:
1. Load `.env` file if present (using `python-dotenv`)
2. Read the YAML file
3. Apply env var substitution recursively
4. Parse through `SentinelConfig(**data)` for Pydantic validation
5. Return the validated config object
6. Raise `ConfigError` with clear messages on any failure

Define `class ConfigError(Exception): pass` in this module.

### File 3: Update `requirements.txt`

Add to existing requirements:
```
pyyaml>=6.0
pydantic>=2.0
```

Keep the existing entries (`flask`, `twilio`, `python-dotenv`).

### File 4: Update `sentinel/__init__.py`

Add a version string:
```python
__version__ = "0.1.0"
```

## Validation Criteria

Before you finish, verify:
1. `python -c "from sentinel.models import Article, ClassificationResult, Event, AlertRecord; print('OK')"` succeeds
2. `python -c "from sentinel.config import load_config, ConfigError, SentinelConfig; print('OK')"` succeeds
3. The config loader can parse `config/config.example.yaml` when required env vars are set (set dummy values for testing):
   ```bash
   ALERT_PHONE_NUMBER="+48123456789" TELEGRAM_API_ID="12345" TELEGRAM_API_HASH="abc123" python -c "
   from sentinel.config import load_config
   config = load_config('config/config.example.yaml')
   print(f'Sources: {len(config.sources.rss)} RSS feeds')
   print(f'Keywords: {len(config.monitoring.keywords)} languages')
   print(f'Config loaded OK')
   "
   ```
4. Article `to_dict()` → `from_dict()` roundtrip preserves all fields
5. No import errors, no syntax errors

## Code Quality Rules
- Type hints on all function signatures
- No hardcoded values -- everything comes from config
- Clean imports (stdlib, then third-party, then local)
- No unnecessary comments -- code should be self-explanatory
- Handle edge cases (None values, empty lists, missing optional fields)
