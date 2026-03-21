# Agent 3: Tests & Validation

Use standard thinking.

## Your Task

Write the complete test suite for Phase 1 of the Sentinel project and ensure all tests pass. All source code (models, config, database, CLI, logging) is already implemented by previous agents.

**Working directory**: `/home/kossa/code/twilio-plaground`

## Before You Start

Read these files to understand what you're testing:
1. `docs/phase-1-infrastructure.md` -- the specification, especially the "Acceptance Tests" section at the bottom
2. `sentinel/models.py` -- data models to test
3. `sentinel/config.py` -- config system to test
4. `sentinel/database.py` -- database to test
5. `sentinel.py` -- CLI to test
6. `sentinel/logging_setup.py` -- logging setup
7. `config/config.example.yaml` -- the config file used in tests

**Important:** Read ALL source files before writing tests. Understand the actual interfaces, method signatures, and return types. Do NOT assume -- verify by reading the code.

## Deliverables

### File 1: `tests/conftest.py`

Shared pytest fixtures used across all test files:

```python
import pytest
import os
import tempfile
import yaml
from sentinel.config import load_config, SentinelConfig
from sentinel.database import Database
from sentinel.models import Article, ClassificationResult, Event, AlertRecord
from datetime import datetime, timezone

@pytest.fixture
def sample_config_dict():
    """Minimal valid config dictionary for testing."""
    # Return a minimal dict that passes SentinelConfig validation
    # Must include all required fields with valid values
    # Use this to test config loading without needing the full config.example.yaml

@pytest.fixture
def sample_config_yaml(sample_config_dict, tmp_path):
    """Write a minimal config to a temp YAML file and return its path."""
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)
    return str(config_path)

@pytest.fixture
def config(sample_config_yaml):
    """Load and return a SentinelConfig from the sample YAML."""
    # Set required env vars for the test
    os.environ.setdefault("ALERT_PHONE_NUMBER", "+48123456789")
    os.environ.setdefault("TELEGRAM_API_ID", "12345")
    os.environ.setdefault("TELEGRAM_API_HASH", "abc123def456")
    return load_config(sample_config_yaml)

@pytest.fixture
def db(tmp_path):
    """Create a temporary in-memory database (or temp file DB)."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    yield database
    database.close()

@pytest.fixture
def sample_article():
    """Create a sample Article for testing."""
    return Article(
        source_name="TestSource",
        source_url="https://example.com/article/123",
        source_type="rss",
        title="Russia launches military operation near Polish border",
        summary="Russian forces have begun a large-scale military operation...",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        raw_metadata={"key": "value"},
    )

@pytest.fixture
def sample_classification(sample_article):
    """Create a sample ClassificationResult for testing."""
    return ClassificationResult(
        article_id=sample_article.id,
        is_military_event=True,
        event_type="troop_movement",
        urgency_score=7,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.85,
        summary_pl="Rosja rozpoczęła operację wojskową w pobliżu polskiej granicy.",
        classified_at=datetime.now(timezone.utc),
        model_used="claude-haiku-4-5-20251001",
        input_tokens=287,
        output_tokens=94,
    )

@pytest.fixture
def sample_event(sample_article):
    """Create a sample Event for testing."""
    return Event(
        event_type="troop_movement",
        urgency_score=7,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja rozpoczęła operację wojskową w pobliżu polskiej granicy.",
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=1,
        article_ids=[sample_article.id],
        alert_status="pending",
        acknowledged_at=None,
    )

@pytest.fixture
def sample_alert_record(sample_event):
    """Create a sample AlertRecord for testing."""
    return AlertRecord(
        event_id=sample_event.id,
        alert_type="phone_call",
        twilio_sid="CA1234567890abcdef",
        status="initiated",
        duration_seconds=None,
        attempt_number=1,
        sent_at=datetime.now(timezone.utc),
        message_body="Alert test message",
    )
```

**Important for `sample_config_dict`:** This fixture must create a valid minimal config that passes Pydantic validation. Look at `config/config.example.yaml` for the structure, but use a minimal version with:
- 1 RSS source
- GDELT enabled with at least 1 theme and 1 CAMEO code
- 1 Google News query
- Telegram disabled (so api_id/api_hash not required)
- At least 1 keyword per language for EN
- At least 1 target country and 1 aggressor country
- All other required sections with defaults

### File 2: `tests/test_models.py`

Test the data model dataclasses. **4 tests minimum:**

```python
def test_article_to_dict_roundtrip(sample_article):
    """Article -> to_dict() -> from_dict() preserves all fields."""
    d = sample_article.to_dict()
    restored = Article.from_dict(d)
    assert restored.id == sample_article.id
    assert restored.source_name == sample_article.source_name
    assert restored.source_url == sample_article.source_url
    assert restored.title == sample_article.title
    assert restored.url_hash == sample_article.url_hash
    assert restored.title_normalized == sample_article.title_normalized
    assert restored.raw_metadata == sample_article.raw_metadata
    # Datetimes: compare ISO strings since exact precision may vary
    assert restored.published_at.date() == sample_article.published_at.date()

def test_classification_to_dict_roundtrip(sample_classification):
    """ClassificationResult roundtrip preserves all fields, including list fields."""
    d = sample_classification.to_dict()
    restored = ClassificationResult.from_dict(d)
    assert restored.article_id == sample_classification.article_id
    assert restored.urgency_score == sample_classification.urgency_score
    assert restored.affected_countries == sample_classification.affected_countries
    assert restored.confidence == sample_classification.confidence

def test_event_to_dict_roundtrip(sample_event):
    """Event roundtrip preserves all fields, including list fields and None."""
    d = sample_event.to_dict()
    restored = Event.from_dict(d)
    assert restored.event_type == sample_event.event_type
    assert restored.affected_countries == sample_event.affected_countries
    assert restored.article_ids == sample_event.article_ids
    assert restored.acknowledged_at is None

def test_alert_record_to_dict_roundtrip(sample_alert_record):
    """AlertRecord roundtrip preserves all fields including None duration."""
    d = sample_alert_record.to_dict()
    restored = AlertRecord.from_dict(d)
    assert restored.event_id == sample_alert_record.event_id
    assert restored.alert_type == sample_alert_record.alert_type
    assert restored.duration_seconds is None
```

**Additional tests to add:**
- `test_article_url_hash_deterministic` -- same URL always gives same hash
- `test_article_title_normalized` -- verify accents stripped, lowercase, punctuation removed
- `test_article_default_id_generated` -- Article created without explicit id gets a UUID

### File 3: `tests/test_config.py`

Test the configuration system. **7 tests minimum:**

1. `test_load_valid_config` -- load `config/config.example.yaml` with env vars set, verify key fields accessible
2. `test_missing_required_field` -- config YAML missing `monitoring` section → Pydantic `ValidationError`
3. `test_env_var_substitution` -- config with `${TEST_VAR}` gets substituted when env var is set
4. `test_missing_env_var` -- config with `${NONEXISTENT_VAR}` → `ConfigError`
5. `test_invalid_url` -- RSS source with URL "not_a_url" → Pydantic `ValidationError`
6. `test_defaults_applied` -- config without optional fields gets defaults (e.g., `scheduler.interval_minutes` = 15)
7. `test_disabled_source_loadable` -- source with `enabled: false` still loads correctly

**Implementation hints:**
- For tests that need a modified config, create a temp YAML file with only the relevant changes
- For `test_load_valid_config`, use `config/config.example.yaml` directly but set env vars first
- For `test_missing_required_field`, write a YAML missing a required section and assert `ValidationError`
- For `test_env_var_substitution`, write a YAML with `${TEST_SENTINEL_VAR}`, set the env var, verify substitution
- For `test_missing_env_var`, write a YAML with `${SENTINEL_NONEXISTENT}`, don't set it, assert `ConfigError`
- Clean up env vars in test teardown (use `monkeypatch` fixture)

### File 4: `tests/test_database.py`

Test the database access layer. **10 tests minimum:**

1. `test_create_tables` -- Database init creates tables; calling init again doesn't error (idempotent)
2. `test_insert_article` -- insert article, verify it's retrievable
3. `test_duplicate_article_rejected` -- insert same article twice → second returns False
4. `test_get_recent_titles` -- insert articles with different timestamps, verify only recent ones returned
5. `test_insert_classification` -- insert classification linked to article, verify stored correctly
6. `test_insert_event` -- insert event with article_ids list, verify stored
7. `test_update_event` -- update event urgency_score and source_count, verify changed
8. `test_get_active_events` -- insert events with different statuses and times, verify filtering
9. `test_cleanup_old_records` -- insert old articles/events, run cleanup, verify deleted
10. `test_concurrent_access` -- rapid sequential inserts don't corrupt data

**Implementation hints:**
- Use the `db` fixture (temp database)
- For `test_get_recent_titles`, insert articles then call `get_recent_titles(since_minutes=5)` -- should return them. Also test that articles from 1 hour ago are NOT returned (you may need to manipulate `fetched_at` manually in SQL for this).
- For `test_cleanup_old_records`, insert articles with `fetched_at` set to 60 days ago, then cleanup with `article_days=30` -- they should be deleted. Also verify their classifications are deleted.
- For `test_concurrent_access`, insert 100 articles in a loop and verify all 100 are stored.

### File 5: `tests/test_cli.py`

Test the CLI entry point. **4 tests minimum:**

1. `test_help_exits_cleanly` -- run `python sentinel.py --help` via `subprocess.run`, verify exit code 0
2. `test_invalid_config_exits` -- run with `--config /nonexistent/path`, verify exit code 1
3. `test_dry_run_flag` -- test that `--dry-run` is recognized (parse args programmatically or check output)
4. `test_custom_config_path` -- test that `--config` accepts a custom path

**Implementation hints:**
- Use `subprocess.run(["python", "sentinel.py", ...], capture_output=True, text=True)` for CLI tests
- Set env vars via the `env` parameter of `subprocess.run`
- For `test_dry_run_flag`, run with `--dry-run --once --config config/config.example.yaml` and check output contains "dry" or "Dry" (case insensitive)
- The CLI should exit 0 for valid configs, exit 1 for invalid

### File 6: `pyproject.toml`

Create `pyproject.toml` with pytest configuration:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests that require network/API access",
]
testpaths = ["tests"]

[tool.ruff]
line-length = 120
```

## After Writing Tests

1. Install test dependencies: `pip install pytest pytest-mock pytest-cov`
2. Run ALL tests: `pytest tests/ -v`
3. **ALL tests must pass.** If any test fails:
   - Read the error carefully
   - Determine if the issue is in the test or in the source code
   - If the test is wrong (doesn't match actual implementation), fix the test
   - If the source code has a bug, fix the source code
   - Re-run until all pass
4. Run with coverage: `pytest tests/ -v --cov=sentinel --cov-report=term-missing`
5. Print the final test results

## Critical Rules

- **Read the source code before writing tests.** Don't assume APIs -- verify them.
- **Match the actual method signatures.** If `database.py` uses different parameter names than the spec, match the code, not the spec.
- **Handle imports correctly.** Use the actual module paths.
- **Tests must be independent.** Each test should work in isolation. Use fixtures for setup/teardown.
- **Use `tmp_path` fixture** for any temp files (pytest provides it automatically).
- **Clean up env vars** using `monkeypatch` to avoid test pollution.
- **Fix both test AND source code if needed.** You have permission to fix bugs in source code discovered during testing. If you fix source code, note what you fixed.
