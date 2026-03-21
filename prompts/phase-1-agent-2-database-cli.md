# Agent 2: Database, Logging, and CLI

Use standard thinking.

## Your Task

Implement the SQLite database access layer, logging setup, and CLI entry point for the Project Sentinel project. The data models (`sentinel/models.py`) and config system (`sentinel/config.py`) are already implemented by a previous agent.

**Working directory**: `/home/kossa/code/project-sentinel`

## Before You Start

Read these files:
1. `docs/phase-1-infrastructure.md` -- sections 1.2 (Database), 1.4 (Logging), 1.5 (CLI)
2. `sentinel/models.py` -- the data models you'll be storing (already implemented)
3. `sentinel/config.py` -- the config system (already implemented) -- understand the `SentinelConfig` structure
4. `config/config.example.yaml` -- the config file structure

## Deliverables

### File 1: `sentinel/database.py`

Implement a `Database` class that manages all SQLite operations.

**Constructor:**
```python
class Database:
    def __init__(self, db_path: str):
        """Create the database file (and parent dirs) and tables if they don't exist."""
```
- Create parent directories for `db_path` if they don't exist (`os.makedirs`)
- Use `sqlite3.connect(db_path)` with `check_same_thread=False`
- Set `row_factory = sqlite3.Row` for dict-like access
- Enable WAL mode for better concurrent read performance: `PRAGMA journal_mode=WAL`
- Call `_create_tables()` to create schema

**Schema** (4 tables as specified in `docs/phase-1-infrastructure.md` section 1.2):
- `articles` -- with columns: id, source_name, source_url, source_type, title, summary, language, published_at, fetched_at, url_hash, title_normalized, raw_metadata
- `classifications` -- with columns: id, article_id, is_military_event, event_type, urgency_score, affected_countries, aggressor, is_new_event, confidence, summary_pl, classified_at, model_used, input_tokens, output_tokens
- `events` -- with columns: id, event_type, urgency_score, affected_countries, aggressor, summary_pl, first_seen_at, last_updated_at, source_count, article_ids, alert_status, acknowledged_at
- `alert_records` -- with columns: id, event_id, alert_type, twilio_sid, status, duration_seconds, attempt_number, sent_at, message_body

Create all indexes as specified in the spec. Use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` for idempotency.

**Methods to implement:**

```python
def insert_article(self, article: Article) -> bool:
    """Insert an article. Returns False if URL hash already exists (duplicate)."""
    # Check url_hash first, insert if unique
    # Use article.to_dict() for column values

def article_exists(self, url_hash: str) -> bool:
    """Check if an article with this URL hash exists."""

def get_recent_titles(self, since_minutes: int) -> list[tuple[str, str]]:
    """Return (source_name, title_normalized) tuples for articles fetched within last N minutes.
    Used by the deduplicator for fuzzy title matching."""
    # Query: SELECT source_name, title_normalized FROM articles
    #        WHERE fetched_at > datetime('now', '-N minutes')

def insert_classification(self, result: ClassificationResult) -> None:
    """Insert a classification result."""

def insert_event(self, event: Event) -> None:
    """Insert a new event."""

def update_event(self, event_id: str, **kwargs) -> None:
    """Update specific fields of an event.
    Only update the fields passed as kwargs.
    Always update last_updated_at to current time."""

def get_active_events(self, within_hours: int) -> list[Event]:
    """Get events with alert_status != 'expired' from the last N hours."""
    # Use Event.from_row() to convert sqlite3.Row to Event

def insert_alert_record(self, record: AlertRecord) -> None:
    """Insert an alert record."""

def get_alert_records(self, event_id: str) -> list[AlertRecord]:
    """Get all alert records for an event, ordered by sent_at."""

def get_pending_call_records(self) -> list[AlertRecord]:
    """Get alert records of type 'phone_call' with status 'initiated' or 'ringing'.
    Used to check call completion status."""

def cleanup_old_records(self, article_days: int, event_days: int) -> int:
    """Delete articles older than article_days and events older than event_days.
    Returns total number of records deleted.
    Also deletes classifications and alert_records for deleted articles/events."""

def close(self) -> None:
    """Close the database connection."""
```

**Implementation notes:**
- Use parameterized queries (never f-strings with SQL) to prevent injection
- Wrap write operations in transactions (use `with self.conn:` context manager)
- Handle `sqlite3.IntegrityError` in `insert_article` for duplicate url_hash
- All datetime comparisons in SQL use ISO 8601 string comparison (works correctly with SQLite)
- The `cleanup_old_records` must cascade: when deleting articles, also delete their classifications; when deleting events, also delete their alert_records
- Use a logger: `self.logger = logging.getLogger("sentinel.database")`

### File 2: `sentinel/logging_setup.py`

Implement logging configuration:

```python
def setup_logging(config: SentinelConfig) -> None:
    """Configure logging based on config settings."""
```

Requirements:
- Create a root logger for "sentinel" namespace
- Add two handlers:
  1. `RotatingFileHandler` writing to `config.logging.file` with `maxBytes` and `backupCount`
  2. `StreamHandler` writing to stdout
- Both use format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Set level from `config.logging.level`
- Create parent directories for the log file if they don't exist
- This function should be idempotent (calling twice doesn't add duplicate handlers)

### File 3: `sentinel.py` (CLI Entry Point)

Create the main entry point at the project root (not inside the `sentinel/` package).

**Important:** This file already does NOT exist at the project root. There IS an `app.py` (the existing Flask app) -- do NOT modify it. Create a NEW file `sentinel.py`.

```python
#!/usr/bin/env python3
"""Sentinel - Military Alert Monitoring System"""
```

Implement using `argparse`:

**Arguments:**
- `--dry-run` (store_true) -- sets config.testing.dry_run = True
- `--test-headline TEXT` -- (Phase 1: just parse the arg, print "Test headline mode not yet implemented" and exit)
- `--test-file FILE` -- (Phase 1: same as above)
- `--config PATH` (default: `config/config.yaml`) -- path to config file
- `--once` (store_true) -- (Phase 1: just parse the flag)
- `--log-level LEVEL` (choices: DEBUG, INFO, WARNING, ERROR) -- overrides config
- `--health` (store_true) -- (Phase 1: print "Health check not yet implemented" and exit)

**Phase 1 behavior:**
1. Parse arguments
2. Load and validate config via `load_config(args.config)`
3. If `--log-level` provided, override `config.logging.level`
4. If `--dry-run`, set `config.testing.dry_run = True`
5. Call `setup_logging(config)`
6. Initialize database: `Database(config.database.path)`
7. Log: `"Sentinel v{version} initialized successfully"`
8. Log: `"Config loaded: {N} RSS sources, {M} Google News queries, GDELT {'enabled' if ... else 'disabled'}, Telegram {'enabled' if ... else 'disabled'}"`
9. Log: `"Database: {config.database.path}"`
10. Log: `"Dry run: {config.testing.dry_run}"`
11. If `--test-headline` or `--test-file` or `--health`: print "not yet implemented" and exit
12. Print "Sentinel initialized successfully. Pipeline execution will be implemented in Phase 6."
13. Exit 0

**Error handling:**
- If config file doesn't exist: print error and exit 1
- If config validation fails: print the Pydantic error and exit 1
- If env var missing: print which var is missing and exit 1

### File 4: Update `requirements.txt`

Verify that `pyyaml` and `pydantic` are present (Agent 1 should have added them). If not, add them. Also add:
```
pytest>=8.0
pytest-mock>=3.12
pytest-cov>=5.0
```

These are needed for the test agent (Agent 3) but best to install now.

## Validation Criteria

Before you finish, run these checks:

1. **Database smoke test:**
```bash
python -c "
from sentinel.database import Database
from sentinel.models import Article
from datetime import datetime, timezone

db = Database(':memory:')

# Create a test article
a = Article(
    source_name='TestSource',
    source_url='https://example.com/test',
    source_type='rss',
    title='Test Article',
    summary='Test summary',
    language='en',
    published_at=datetime.now(timezone.utc),
    fetched_at=datetime.now(timezone.utc),
    raw_metadata={}
)

# Insert
result = db.insert_article(a)
assert result == True, 'First insert should succeed'

# Duplicate
result2 = db.insert_article(a)
assert result2 == False, 'Duplicate should fail'

print('Database OK')
db.close()
"
```

2. **CLI smoke test:**
```bash
python sentinel.py --help
```
Must print usage and exit 0.

3. **Full init test:**
```bash
ALERT_PHONE_NUMBER="+48123456789" TELEGRAM_API_ID="12345" TELEGRAM_API_HASH="abc123" python sentinel.py --config config/config.example.yaml --dry-run --once
```
Must print initialization messages and exit 0.

4. **Logging test:**
```bash
ALERT_PHONE_NUMBER="+48123456789" TELEGRAM_API_ID="12345" TELEGRAM_API_HASH="abc123" python sentinel.py --config config/config.example.yaml --log-level DEBUG --once 2>&1 | head -20
```
Must show log output with correct format.

## Code Quality Rules
- Type hints on all function signatures
- Use `logging.getLogger("sentinel.xxx")` for per-module loggers
- Parameterized SQL queries only (never f-strings)
- Handle all edge cases (empty database, missing directories, etc.)
- Clean error messages for user-facing failures
