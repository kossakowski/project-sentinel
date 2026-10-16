import asyncio
import errno
import ipaddress
import itertools
import os
import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import yaml
from twilio.rest import Client as TwilioSdkClient

from sentinel.alerts.push_client import ExpoPushClient
from sentinel.config import load_config
from sentinel.database import Database
from sentinel.models import AlertRecord, Article, ClassificationResult, Event

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite the files under tests/golden/ from the current behaviour instead of comparing against them.",
    )


@pytest.fixture
def update_golden(request) -> bool:
    """True only when pytest runs with ``--update-golden``."""
    return bool(request.config.getoption("--update-golden"))


# ---------------------------------------------------------------------------
# Network guard: no test may reach a non-loopback address
# ---------------------------------------------------------------------------


class NetworkAccessBlocked(OSError):
    """Raised by the test-suite guard for any non-loopback connection or DNS lookup.

    It is an ``OSError`` (``ENETUNREACH``) so code under test sees exactly what
    it would see on a machine without a network.
    """

    def __init__(self, target: object) -> None:
        super().__init__(errno.ENETUNREACH, f"Network access is blocked during tests: {target!r}")


_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_REAL_SOCKET_SENDTO = socket.socket.sendto
_REAL_GETADDRINFO = socket.getaddrinfo
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


def _is_local_host(host: object) -> bool:
    """True for loopback IPs and localhost names. Any other hostname would need DNS."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() in _LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _is_local_target(sock: socket.socket, address: object) -> bool:
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) and address else address
    return _is_local_host(host)


def _guarded_connect(self, address):
    if not _is_local_target(self, address):
        raise NetworkAccessBlocked(address)
    return _REAL_SOCKET_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    if not _is_local_target(self, address):
        raise NetworkAccessBlocked(address)
    return _REAL_SOCKET_CONNECT_EX(self, address)


def _guarded_sendto(self, data, *flags_and_address):
    # sendto(data, address) or sendto(data, flags, address): the address is last.
    if not _is_local_target(self, flags_and_address[-1]):
        raise NetworkAccessBlocked(flags_and_address[-1])
    return _REAL_SOCKET_SENDTO(self, data, *flags_and_address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    # None (passive bind) and numeric addresses resolve locally without DNS;
    # a numeric non-loopback address is still refused at connect().
    if host is not None and not _is_local_host(host):
        try:
            ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host)
        except ValueError:
            raise NetworkAccessBlocked(host) from None
    return _REAL_GETADDRINFO(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Refuse every non-loopback socket connection or datagram and every DNS lookup of a real hostname."""
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", _guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


# ---------------------------------------------------------------------------
# Live production config
# ---------------------------------------------------------------------------

# Shape-valid stand-ins for the ${VAR} placeholders of config/config.yaml.
PROD_ENV_DUMMIES = {
    "ALERT_PHONE_NUMBER": "+48500100200",
    "TELEGRAM_API_ID": "1234567",
    "TELEGRAM_API_HASH": "0123456789abcdef0123456789abcdef",
    "EXPO_PUSH_TOKEN": "ExponentPushToken[sentinel-test-device-0001]",
}


@pytest.fixture
def prod_config(tmp_path, monkeypatch):
    """The tracked config/config.yaml, loaded through load_config().

    Only the four on-disk paths move under ``tmp_path``; every other value is
    the live production value. The ``${VAR}`` placeholders resolve to the
    shape-valid dummies in ``PROD_ENV_DUMMIES``.
    """
    for name, value in PROD_ENV_DUMMIES.items():
        monkeypatch.setenv(name, value)
    config = load_config(str(LIVE_CONFIG_PATH))
    runtime_dir = tmp_path / "prod-runtime"
    config.database.path = str(runtime_dir / "sentinel.db")
    config.logging.file = str(runtime_dir / "sentinel.log")
    config.classification.budget.ledger_path = str(runtime_dir / "model-usage.db")
    config.sources.telegram.session_name = str(runtime_dir / "sentinel_session")
    return config


# ---------------------------------------------------------------------------
# Clock and sleep control for the alert path
# ---------------------------------------------------------------------------

FROZEN_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

# Modules whose ``datetime.now()`` the freeze_time fixture pins.
FROZEN_CLOCK_MODULES = (
    "sentinel.classification.classifier",
    "sentinel.classification.corroborator",
    "sentinel.alerts.state_machine",
    "sentinel.alerts.twilio_client",
    "sentinel.database",
)


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` always returns ``FROZEN_NOW``."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.astimezone().replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# SQLite date functions whose first argument is a time value ('now' or a timestamp).
_SQL_TIME_FUNCTIONS = ("datetime", "date", "julianday", "unixepoch")


def _install_frozen_sql_clock(conn: sqlite3.Connection) -> None:
    """Make SQLite's own 'now' equal ``FROZEN_NOW`` on this connection.

    ``Database`` compares some windows against SQLite's ``datetime('now', …)``
    (the end-of-cycle retention cleanup among them). Without this, rows stamped
    at the frozen instant would age against the real wall clock. The overrides
    replace a 'now' (or missing) time value with the frozen instant and let
    SQLite's built-in function, on a private connection, do the rest.
    """
    builtin = sqlite3.connect(":memory:", check_same_thread=False)
    frozen_sql_now = FROZEN_NOW.strftime("%Y-%m-%d %H:%M:%S")

    def make(function_name: str):
        def frozen(*args):
            values = list(args) or [frozen_sql_now]
            if isinstance(values[0], str) and values[0].strip().lower() == "now":
                values[0] = frozen_sql_now
            placeholders = ", ".join("?" for _ in values)
            return builtin.execute(f"SELECT {function_name}({placeholders})", values).fetchone()[0]

        return frozen

    for function_name in _SQL_TIME_FUNCTIONS:
        conn.create_function(function_name, -1, make(function_name))


class _FrozenClockSqlite3:
    """Stand-in for the ``sqlite3`` module inside ``sentinel.database``."""

    def __getattr__(self, name):
        return getattr(sqlite3, name)

    @staticmethod
    def connect(*args, **kwargs):
        conn = sqlite3.connect(*args, **kwargs)
        _install_frozen_sql_clock(conn)
        return conn


@pytest.fixture
def freeze_time(monkeypatch):
    """Pin the alert-path clock to ``FROZEN_NOW`` (2026-10-16T12:00:00+00:00).

    Patches ``datetime`` in every module of ``FROZEN_CLOCK_MODULES``, and the
    SQLite 'now' of connections that ``sentinel.database`` opens while the
    fixture is active. Returns the frozen instant.
    """
    for module_name in FROZEN_CLOCK_MODULES:
        monkeypatch.setattr(f"{module_name}.datetime", _FrozenDatetime)
    monkeypatch.setattr("sentinel.database.sqlite3", _FrozenClockSqlite3())
    return FROZEN_NOW


_REAL_ASYNCIO_SLEEP = asyncio.sleep


class _InstantSleepAsyncio:
    """Stand-in for ``asyncio`` inside the state machine: ``sleep`` returns at once."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(delay, result=None):
        await _REAL_ASYNCIO_SLEEP(0)
        return result


@pytest.fixture
def instant_alert_sleep(monkeypatch):
    """Skip the state machine's call-poll and retry-pause waits (other modules are untouched)."""
    monkeypatch.setattr("sentinel.alerts.state_machine.asyncio", _InstantSleepAsyncio())


# ---------------------------------------------------------------------------
# Fakes at the delivery edges (Twilio SDK, Expo push)
# ---------------------------------------------------------------------------


@pytest.fixture
def twilio_sdk(monkeypatch):
    """Autospec of the Twilio SDK ``Client``, so the real ``TwilioClient`` runs on top of it.

    Returns the SDK instance mock. Default behaviour: every call and SMS is
    accepted with a fresh SID, a placed call reports ``completed`` after 20 s,
    a sent SMS reports ``delivered`` and no inbound SMS reply exists. Tests
    override ``calls.create``, ``messages.create`` or ``messages.list`` to
    model failures and replies; outbound TwiML and SMS bodies are read from the
    ``twiml=`` and ``body=`` keyword arguments.
    """
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC00000000000000000000000000000000")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-auth-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+48100200300")
    client_class = create_autospec(TwilioSdkClient)
    sdk = client_class.return_value
    call_sids = (f"CA{n:032d}" for n in itertools.count(1))
    sms_sids = (f"SM{n:032d}" for n in itertools.count(1))
    sdk.calls.create.side_effect = lambda **kwargs: SimpleNamespace(sid=next(call_sids))
    sdk.calls.return_value.fetch.return_value = SimpleNamespace(status="completed", duration="20", answered_by=None)
    sdk.messages.create.side_effect = lambda **kwargs: SimpleNamespace(sid=next(sms_sids))
    sdk.messages.list.return_value = []
    sdk.messages.return_value.fetch.return_value = SimpleNamespace(status="delivered", error_code=None)
    monkeypatch.setattr("sentinel.alerts.twilio_client.Client", client_class)
    return sdk


def _accept_push(self, title, body, event_id, data=None):
    return AlertRecord(
        event_id=event_id,
        alert_type="push",
        twilio_sid="expo-ticket-0001",
        status="sent",
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body=body,
    )


@pytest.fixture
def expo_send_push(monkeypatch):
    """Autospec of ``ExpoPushClient.send_push`` that accepts every push.

    Returns the mock; each call's arguments include the push ``data`` dict.
    """
    fake = create_autospec(ExpoPushClient.send_push, side_effect=_accept_push)
    monkeypatch.setattr(ExpoPushClient, "send_push", fake)
    return fake


@pytest.fixture
def sample_config_dict():
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
                "lookback_minutes": 60,
                "themes": ["ARMEDCONFLICT"],
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
            # Pin the legacy metric + threshold so existing grouping tests keep their
            # exact semantics; tests for the new behaviour set these explicitly.
            "summary_similarity_threshold": 40,
            "summary_similarity_metric": "token_sort_ratio",
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
            "path": "data/sentinel.db",
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
def db(tmp_path):
    """Create a temporary database."""
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
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
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
        classified_at=datetime.now(UTC),
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
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
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
        sent_at=datetime.now(UTC),
        message_body="Alert test message",
    )


@pytest.fixture
def direct_config(config, tmp_path):
    cfg = config.classification
    cfg.provider = "openai"
    cfg.model = "gpt-5.6-luna"
    cfg.max_tokens = 1024
    cfg.policy = yaml.safe_load(Path("tests/fixtures/benchmark_policy_v2.yaml").read_text())
    cfg.incident_memory.enabled = True
    cfg.budget.ledger_path = str(tmp_path / "usage.db")
    return config


# ---------------------------------------------------------------------------
# Alert-path state on the live config
# ---------------------------------------------------------------------------


@pytest.fixture
def prod_db(prod_config):
    """A fresh database at ``prod_config.database.path`` (under tmp_path)."""
    database = Database(prod_config.database.path)
    yield database
    database.close()


@pytest.fixture
def store_critical_event(prod_db):
    """Store a single-source Polish invasion event and its article; return the event.

    Mirrors what the corroborator persists for a new urgency 9-10 article, so
    ``AlertStateMachine.process_event`` routes it to a phone call.
    """

    def store(*, urgency: int = 10, title: str = "Atak zbrojny na Polskę") -> Event:
        now = datetime.now(UTC)
        article = Article(
            source_name="PAP",
            source_url=f"https://www.pap.pl/aktualnosci/{uuid4()}",
            source_type="rss",
            title=title,
            summary="Rosyjskie wojska przekroczyły granicę Polski od strony Białorusi.",
            language="pl",
            published_at=now,
            fetched_at=now,
        )
        prod_db.insert_article(article)
        event = Event(
            event_type="invasion",
            urgency_score=urgency,
            affected_countries=["PL"],
            aggressor="RU",
            summary_pl="Rosyjskie wojska przekroczyły granicę Polski i atakują pozycje na Podlasiu.",
            first_seen_at=now,
            last_updated_at=now,
            source_count=1,
            article_ids=[article.id],
            alert_status="phone_call",
        )
        prod_db.insert_event(event)
        return event

    return store
