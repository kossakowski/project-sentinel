"""Tests for Phase 1 alerting reliability: durable failure records + bounded retry.

Covers the six acceptance tests for requirements 1.1-1.7:

- A failed send leaves a durable ``alert_records`` row with ``status="failed"``
  and a non-null ``error_code`` (never a silent zero-row drop).
- Cross-cycle phone-retry rounds are bounded by a config cap enforced against the
  durable ``events.alert_round_count`` counter (survives restarts, read from DB).
- The Twilio/push clients surface transport errors as a structured failure result
  instead of a bare ``None``.
- Confirmation codes are scoped per-event so one event's ACK can't resolve another.
- The retry cap is config-driven.
- The additive schema migration preserves existing rows.

The alert path is async: state-machine methods are coroutines and every Twilio
SDK call is offloaded via ``asyncio.to_thread`` (which runs the wrapped callable
in a worker thread), so the synchronous ``mock_twilio`` MagicMock records calls
and returns its configured values unchanged.
"""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from twilio.base.exceptions import TwilioRestException

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.database import Database
from sentinel.models import AlertRecord, Event

# --------------------------------------------------------------------------
# Helpers / fixtures
# --------------------------------------------------------------------------


def _make_event(
    urgency_score: int = 10,
    source_count: int = 2,
    event_type: str = "missile_strike",
    alert_status: str = "pending",
    event_id: str | None = None,
) -> Event:
    """Build a critical (call-tier) Event for the alert path."""
    return Event(
        id=event_id or str(uuid4()),
        event_type=event_type,
        urgency_score=urgency_score,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja wystrzeliła rakiety w kierunku Polski.",
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=source_count,
        article_ids=[str(uuid4())],
        alert_status=alert_status,
        acknowledged_at=None,
    )


@pytest.fixture
def mock_twilio():
    """Mock TwilioClient whose calls succeed by default (status='initiated'/'sent')."""
    twilio = MagicMock()

    def _make_call_record(phone, message, event_id):
        return AlertRecord(
            event_id=event_id,
            alert_type="phone_call",
            twilio_sid=f"CA_{uuid4().hex[:12]}",
            status="initiated",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=message,
        )

    def _make_sms_record(phone, message, event_id):
        return AlertRecord(
            event_id=event_id,
            alert_type="sms",
            twilio_sid=f"SM_{uuid4().hex[:12]}",
            status="sent",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=message,
        )

    twilio.make_alert_call.side_effect = _make_call_record
    twilio.send_sms.side_effect = _make_sms_record
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    twilio.client.messages.list.return_value = []
    twilio.twilio_phone = "+15551234567"
    return twilio


@pytest.fixture
def state_machine(db, mock_twilio, config):
    """AlertStateMachine wired to the temp DB and mocked Twilio."""
    return AlertStateMachine(db, mock_twilio, config)


def _fail_calls(mock_twilio) -> None:
    """Force make_alert_call to return a bare None (simulated transport failure)."""
    mock_twilio.make_alert_call.side_effect = None
    mock_twilio.make_alert_call.return_value = None


# --------------------------------------------------------------------------
# 1. test_failed_call_is_recorded  [1.1, 1.3]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_failed_call_is_recorded(_sleep, state_machine, db, mock_twilio):
    """A failed call (make_alert_call -> None) leaves a durable failed row.

    Not just a log line: dispatching a critical event whose calls all fail must
    persist at least one ``alert_records`` row with ``status="failed"`` and a
    non-null ``error_code`` (fail-loud, never fail-silent).
    """
    _fail_calls(mock_twilio)
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    await state_machine.process_event(event)

    records = db.get_alert_records(event.id)
    failed = [r for r in records if r.alert_type == "phone_call" and r.status == "failed"]
    assert failed, "a failed call must persist a status='failed' alert_records row"
    assert all(r.error_code is not None for r in failed), "failed rows must carry a non-null error_code"


# --------------------------------------------------------------------------
# 2. test_retry_rounds_bounded  [1.2]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_rounds_bounded(_sleep, state_machine, db, mock_twilio, config):
    """With max_rounds=3 and persistent failure the event goes terminal at 3.

    The durable counter increments to 3, the event then reaches
    ``alert_status="failed_terminal"``, and a subsequent cycle places no further
    call. The bound is read from the DB counter, never in-memory state.
    """
    config.alerts.retry.max_rounds = 3
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    _fail_calls(mock_twilio)

    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Simulate scheduler cycles, always re-reading the event from the DB so the
    # round counter comes from durable state, not a stale object.
    for _ in range(8):
        current = db.get_event_by_id(event.id)
        if current.alert_status == "failed_terminal":
            break
        await state_machine.process_event(current)

    final = db.get_event_by_id(event.id)
    assert final.alert_round_count == 3
    assert final.alert_status == "failed_terminal"
    # 3 rounds x 1 attempt/round = exactly 3 call attempts; none after terminal.
    assert mock_twilio.make_alert_call.call_count == 3

    # One more cycle after terminal must not place another call.
    before = mock_twilio.make_alert_call.call_count
    await state_machine.process_event(db.get_event_by_id(event.id))
    assert mock_twilio.make_alert_call.call_count == before


# --------------------------------------------------------------------------
# 3. test_failure_record_has_error_code  [1.4]
# --------------------------------------------------------------------------
def test_failure_record_has_error_code(config, db):
    """A transport failure carrying an error code is surfaced by the client and
    captured into the persisted failure row.

    The Twilio client returns a structured ``status="failed"`` AlertRecord (not
    None) whose ``error_code`` equals the Twilio error code; persisting it keeps
    that code on the durable ``alert_records`` row.
    """
    with (
        patch.dict(
            os.environ,
            {
                "TWILIO_ACCOUNT_SID": "ACtest",
                "TWILIO_AUTH_TOKEN": "tok",
                "TWILIO_PHONE_NUMBER": "+15551234567",
            },
        ),
        patch("sentinel.alerts.twilio_client.Client"),
    ):
        client = TwilioClient(config)
        client.client = MagicMock()
        client.client.calls.create.side_effect = TwilioRestException(
            status=401, uri="/Calls", msg="Authenticate", code=20003
        )
        result = client.make_alert_call("+48123456789", "Alert", "evt-fail")

    assert result is not None, "client must return a structured result, not None (req 1.4)"
    assert result.status == "failed"
    assert result.error_code == "20003"
    assert result.error_detail

    # The code is captured into the persisted alert_records failure row.
    db.insert_alert_record(result)
    rows = db.get_alert_records("evt-fail")
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_code == "20003"


# --------------------------------------------------------------------------
# 4. test_confirmation_code_per_event  [1.5]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_confirmation_code_per_event(state_machine, mock_twilio):
    """An ACK carrying event A's code resolves A but never B.

    Confirmation codes are stored per-event, so a reply matching one event's code
    cannot acknowledge a different event.
    """
    event_a = _make_event(event_id="evt-A")
    event_b = _make_event(event_id="evt-B")

    with patch("sentinel.alerts.state_machine.random.randint", side_effect=[111111, 222222]):
        await state_machine._send_confirmation_sms(event_a)
        await state_machine._send_confirmation_sms(event_b)

    assert state_machine._confirmation_codes[event_a.id] == "111111"
    assert state_machine._confirmation_codes[event_b.id] == "222222"

    # The user replies with event A's code.
    inbound = MagicMock()
    inbound.body = "111111"
    mock_twilio.client.messages.list.return_value = [inbound]
    since = datetime.now(UTC) - timedelta(minutes=1)

    assert await state_machine._check_sms_confirmation(since, event_a.id) is True
    assert await state_machine._check_sms_confirmation(since, event_b.id) is False


# --------------------------------------------------------------------------
# 5. test_retry_cap_is_config_driven  [1.6]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_cap_is_config_driven(_sleep, state_machine, db, mock_twilio, config):
    """The terminal round count follows ``alerts.retry.max_rounds`` (1 then 5)."""
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    _fail_calls(mock_twilio)

    async def _run_until_terminal(event_id: str) -> Event:
        for _ in range(30):
            current = db.get_event_by_id(event_id)
            if current.alert_status == "failed_terminal":
                break
            await state_machine.process_event(current)
        return db.get_event_by_id(event_id)

    config.alerts.retry.max_rounds = 1
    ev1 = _make_event(event_id="cap-1")
    db.insert_event(ev1)
    final1 = await _run_until_terminal("cap-1")
    assert final1.alert_status == "failed_terminal"
    assert final1.alert_round_count == 1

    config.alerts.retry.max_rounds = 5
    ev2 = _make_event(event_id="cap-5")
    db.insert_event(ev2)
    final2 = await _run_until_terminal("cap-5")
    assert final2.alert_status == "failed_terminal"
    assert final2.alert_round_count == 5


# --------------------------------------------------------------------------
# 6. test_migration_adds_columns_preserves_rows  [1.7]
# --------------------------------------------------------------------------
def test_migration_adds_columns_preserves_rows(tmp_path):
    """An old-schema DB gains the new columns without losing existing rows.

    Seeds a pre-Phase-1 ``alert_records`` (no error columns) and ``events`` (no
    round counter) table with one row each, then opens it through ``Database``
    (which runs the additive migration) and asserts the columns now exist with
    sane defaults and the prior rows are intact.
    """
    db_path = str(tmp_path / "old_schema.db")

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE alert_records (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            twilio_sid TEXT,
            status TEXT NOT NULL,
            duration_seconds INTEGER,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            sent_at TEXT NOT NULL,
            message_body TEXT
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            urgency_score INTEGER NOT NULL,
            affected_countries TEXT NOT NULL,
            aggressor TEXT,
            summary_pl TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 1,
            article_ids TEXT NOT NULL,
            alert_status TEXT NOT NULL DEFAULT 'pending',
            acknowledged_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO alert_records (id, event_id, alert_type, twilio_sid, status, attempt_number, sent_at, message_body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("old-alert-1", "evt-old", "phone_call", "CA_legacy", "sent", 1, "2026-01-01T00:00:00+00:00", "legacy body"),
    )
    conn.execute(
        "INSERT INTO events (id, event_type, urgency_score, affected_countries, aggressor, summary_pl, "
        "first_seen_at, last_updated_at, source_count, article_ids, alert_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "evt-old",
            "missile_strike",
            9,
            '["PL"]',
            "RU",
            "Legacy event",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            1,
            '["art-1"]',
            "acknowledged",
        ),
    )
    conn.commit()
    conn.close()

    # Opening through Database runs _create_tables (IF NOT EXISTS, so the old
    # tables survive) and the additive migration.
    database = Database(db_path)
    try:
        alert_cols = {row["name"] for row in database.conn.execute("PRAGMA table_info(alert_records)")}
        assert "error_code" in alert_cols
        assert "error_detail" in alert_cols

        event_cols = {row["name"] for row in database.conn.execute("PRAGMA table_info(events)")}
        assert "alert_round_count" in event_cols

        # Prior rows intact, new columns default to null / 0.
        rows = database.get_alert_records("evt-old")
        assert len(rows) == 1
        assert rows[0].id == "old-alert-1"
        assert rows[0].status == "sent"
        assert rows[0].error_code is None
        assert rows[0].error_detail is None

        event = database.get_event_by_id("evt-old")
        assert event is not None
        assert event.summary_pl == "Legacy event"
        assert event.alert_status == "acknowledged"
        assert event.alert_round_count == 0
    finally:
        database.close()
