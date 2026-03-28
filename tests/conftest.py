import os

import pytest
import yaml

from sentinel.config import SentinelConfig, load_config
from sentinel.database import Database
from sentinel.models import AlertRecord, Article, ClassificationResult, Event
from datetime import datetime, timezone

from testcontainers.postgres import PostgresContainer


# ---------------------------------------------------------------------------
# Session-scoped PostgreSQL container
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """Spin up a PostgreSQL container for the test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_url(pg_container):
    """Return the connection URL for the session-scoped PostgreSQL container.

    testcontainers returns a SQLAlchemy-style URL like
    ``postgresql+psycopg2://user:pass@host:port/db``.  psycopg3 expects a
    plain ``postgresql://`` scheme, so we strip the driver suffix.
    """
    raw_url = pg_container.get_connection_url()
    # Strip any "+driver" suffix from the scheme (e.g. "postgresql+psycopg2" -> "postgresql")
    if "+psycopg2" in raw_url:
        raw_url = raw_url.replace("postgresql+psycopg2", "postgresql")
    elif "+psycopg" in raw_url:
        raw_url = raw_url.replace("postgresql+psycopg", "postgresql")
    return raw_url


@pytest.fixture(scope="session")
def _db_tables(pg_url):
    """Create tables once per session."""
    database = Database(pg_url)
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(_db_tables):
    """Reuse session-scoped Database, truncating all tables between tests."""
    # Truncate all tables before each test
    with _db_tables.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE alert_records, classifications, events, articles CASCADE"
            )
    yield _db_tables


@pytest.fixture
def sample_config_dict(pg_url):
    """Minimal valid config dictionary for testing."""
    return {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {
                "en": {
                    "critical": ["military attack"],
                    "high": ["military buildup"],
                },
            },
            "exclude_keywords": {
                "en": ["exercise", "drill"],
            },
        },
        "sources": {
            "rss": [
                {
                    "name": "TestFeed",
                    "url": "https://example.com/rss.xml",
                    "language": "en",
                    "enabled": True,
                    "priority": 2,
                },
            ],
            "gdelt": {
                "enabled": True,
                "update_interval_minutes": 15,
                "themes": ["ARMEDCONFLICT"],
                "cameo_codes": ["19"],
                "goldstein_threshold": -7.0,
            },
            "google_news": {
                "enabled": True,
                "queries": [
                    {"query": "military attack Poland", "language": "en"},
                ],
            },
            "telegram": {
                "enabled": False,
                "channels": [],
            },
        },
        "processing": {
            "dedup": {
                "same_source_title_threshold": 85,
                "cross_source_title_threshold": 95,
                "lookback_minutes": 60,
            },
        },
        "classification": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "temperature": 0.0,
            "corroboration_required": 2,
            "corroboration_window_minutes": 60,
        },
        "alerts": {
            "phone_number": "+48123456789",
            "language": "pl",
            "urgency_levels": {
                "critical": {
                    "min_score": 9,
                    "action": "phone_call",
                    "corroboration_required": 2,
                    "retry_attempts": 3,
                    "retry_interval_minutes": 5,
                    "fallback": "sms",
                },
                "high": {
                    "min_score": 7,
                    "action": "sms",
                    "corroboration_required": 1,
                },
            },
            "acknowledgment": {
                "call_duration_threshold_seconds": 15,
                "max_call_retries": 5,
                "retry_interval_minutes": 5,
                "cooldown_hours": 6,
            },
        },
        "scheduler": {
            "interval_minutes": 15,
            "jitter_seconds": 30,
        },
        "database": {
            "url": pg_url,
            "article_retention_days": 30,
            "event_retention_days": 90,
        },
        "logging": {
            "level": "INFO",
            "file": "logs/sentinel.log",
            "max_size_mb": 50,
            "backup_count": 5,
        },
        "testing": {
            "dry_run": False,
            "test_mode": False,
            "test_headlines_file": "tests/fixtures/test_headlines.yaml",
        },
    }


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
    os.environ.setdefault("ALERT_PHONE_NUMBER", "+48123456789")
    os.environ.setdefault("TELEGRAM_API_ID", "12345")
    os.environ.setdefault("TELEGRAM_API_HASH", "abc123def456")
    return load_config(sample_config_yaml)


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
        summary_pl="Rosja rozpoczela operacje wojskowa w poblizu polskiej granicy.",
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
        summary_pl="Rosja rozpoczela operacje wojskowa w poblizu polskiej granicy.",
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
