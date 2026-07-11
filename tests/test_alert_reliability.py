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
import requests
from pydantic import ValidationError
from twilio.base.exceptions import TwilioRestException

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import RetryConfig
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


# --------------------------------------------------------------------------
# 7. test_network_transport_failure_is_recorded  [1.1, 1.4]
# --------------------------------------------------------------------------
def test_network_transport_failure_is_recorded(config, db):
    """A network-level transport error is caught and surfaced, never raised.

    The Twilio SDK mints ``TwilioRestException`` only for non-2xx API responses;
    a DNS/connection/timeout fault surfaces as a
    ``requests.exceptions.RequestException`` from the underlying transport. It
    MUST NOT propagate and abort dispatch for the rest of the cycle — the client
    returns a structured ``status="failed"`` record with a non-null
    ``error_code`` so the caller persists a durable failure row (req 1.1/1.4).
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
        client.client.calls.create.side_effect = requests.exceptions.ConnectionError("connection reset")
        client.client.messages.create.side_effect = requests.exceptions.ConnectTimeout("timed out")
        client.client.calls.return_value.fetch.side_effect = requests.exceptions.ConnectionError("reset")

        call_result = client.make_alert_call("+48123456789", "Alert", "evt-net")
        sms_result = client.send_sms("+48123456789", "Alert", "evt-net")
        status_result = client.get_call_status("CA_missing")

    # make_alert_call: structured failure, not an exception, non-null error_code.
    assert call_result is not None, "a network fault must return a record, not raise (req 1.4)"
    assert call_result.status == "failed"
    assert call_result.error_code == "ConnectionError"
    assert call_result.error_detail

    # send_sms: same contract.
    assert sms_result.status == "failed"
    assert sms_result.error_code == "ConnectTimeout"
    assert sms_result.error_detail

    # get_call_status swallows the transport fault to its documented None.
    assert status_result is None

    # The transport error code lands on the durable alert_records row.
    db.insert_alert_record(call_result)
    rows = db.get_alert_records("evt-net")
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_code == "ConnectionError"


# --------------------------------------------------------------------------
# 8. test_failed_terminal_still_alerts_new_content  [1.2, prime directive]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_failed_terminal_still_alerts_new_content(_sleep, state_machine, db, mock_twilio, config):
    """A ``failed_terminal`` event is not blanket-skipped: new content still alerts.

    The bounded retry cap terminates only the failed phone-retry re-entry (the
    per-channel cap lives in ``_execute_phone_call``). A genuinely new escalation
    merged into the still-live incident — here delivered via the additive push
    channel — MUST still fire instead of being silenced for the whole retry
    window (prime directive: fail toward firing, never toward suppression).
    """
    config.alerts.retry.max_rounds = 1
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    config.alerts.push.enabled = False
    _fail_calls(mock_twilio)

    event = _make_event(urgency_score=10)
    db.insert_event(event)

    # Drive the event to failed_terminal via persistent call failures (push off,
    # so no push record exists yet).
    for _ in range(5):
        current = db.get_event_by_id(event.id)
        if current.alert_status == "failed_terminal":
            break
        await state_machine.process_event(current)
    assert db.get_event_by_id(event.id).alert_status == "failed_terminal"

    calls_before = mock_twilio.make_alert_call.call_count

    # A new escalation arrives and the push channel is now available.
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[test]"]
    push_record = AlertRecord(
        event_id=event.id,
        alert_type="push",
        twilio_sid="ticket-1",
        status="sent",
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="body",
    )
    state_machine.push.send_push = MagicMock(return_value=push_record)

    await state_machine.process_event(db.get_event_by_id(event.id))

    # The push fired (blanket skip would have dropped it) ...
    state_machine.push.send_push.assert_called_once()
    push_rows = [r for r in db.get_alert_records(event.id) if r.alert_type == "push" and r.status == "sent"]
    assert push_rows, "a failed_terminal event must still deliver a new-content push"
    # ... while the phone path stays capped (no new call placed).
    assert mock_twilio.make_alert_call.call_count == calls_before


# --------------------------------------------------------------------------
# 9. test_every_round_advances_cap  [1.2]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_every_round_advances_cap(_sleep, state_machine, db, mock_twilio, config):
    """Each unacknowledged round advances the counter once (spec 1.2 'once per round').

    ``alert_round_count`` increments exactly once for every completed-but-
    unacknowledged round regardless of transport outcome: a delivered-but-never-
    answered round (Twilio accepts the call, the phone rings, the user does not
    reply) ticks the counter just like a transport-outage round. At ``max_rounds``
    the event goes ``failed_terminal`` and places no further call — so a
    never-answered phone cannot loop forever any more than an unreachable one can.
    """
    config.alerts.retry.max_rounds = 3
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    # Default mock_twilio: make_alert_call succeeds (the phone rings) but the user
    # never replies, so no round is ever acknowledged.

    event = _make_event(urgency_score=10)
    db.insert_event(event)

    for _ in range(10):
        current = db.get_event_by_id(event.id)
        if current.alert_status == "failed_terminal":
            break
        await state_machine.process_event(current)

    final = db.get_event_by_id(event.id)
    # Three delivered-but-unacknowledged rounds each ticked the counter once.
    assert final.alert_round_count == 3, "each unacknowledged round must advance the cap counter once"
    assert final.alert_status == "failed_terminal"

    # No further call is placed once terminal (the cap holds even though calls
    # were being accepted by Twilio).
    before = mock_twilio.make_alert_call.call_count
    await state_machine.process_event(db.get_event_by_id(event.id))
    assert mock_twilio.make_alert_call.call_count == before


# --------------------------------------------------------------------------
# 10. test_max_rounds_lower_bound_enforced  [1.6]
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, -10])
def test_max_rounds_lower_bound_enforced(bad):
    """``alerts.retry.max_rounds`` below 1 fails fast at config load.

    A mistyped ``0``/negative would satisfy ``alert_round_count >= max_rounds``
    on first touch and silently mark every call-tier event ``failed_terminal``,
    disabling the life-safety phone channel system-wide. The Pydantic ``ge=1``
    bound rejects it at load instead.
    """
    with pytest.raises(ValidationError):
        RetryConfig(max_rounds=bad)

    # A valid value still constructs.
    assert RetryConfig(max_rounds=1).max_rounds == 1


# --------------------------------------------------------------------------
# 11. test_retry_pending_swept_across_cycles  [1.2, 1.3]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_pending_swept_across_cycles(_sleep, state_machine, db, mock_twilio, config):
    """A failed round is retried each cycle even when no new article merges.

    ``check_pending_calls`` sweeps events left in ``retry_pending`` (a fully-failed
    round leaves no in-flight call record for its poll to pick up) back through the
    bounded retry loop, so a single-source urgency-9 event whose call round fails
    at transport is retried up to the cap (1.3 — fail-loud, never fail-silent)
    instead of only when a new article happens to merge into it.
    """
    config.alerts.retry.max_rounds = 3
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    _fail_calls(mock_twilio)

    # A call-tier event that will not attract further corroborating articles: the
    # only thing that can retry its failed round is the cycle-driven sweep.
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # One dispatch places the first (failed) round and leaves the event pending.
    await state_machine.process_event(event)
    assert db.get_event_by_id(event.id).alert_status == "retry_pending"
    assert db.get_event_by_id(event.id).alert_round_count == 1
    calls_after_first = mock_twilio.make_alert_call.call_count

    # No new article merges — only the cycle-driven sweep runs. It must keep
    # retrying and drive the event to the terminal cap.
    for _ in range(10):
        if db.get_event_by_id(event.id).alert_status == "failed_terminal":
            break
        await state_machine.check_pending_calls()

    final = db.get_event_by_id(event.id)
    assert final.alert_status == "failed_terminal"
    assert final.alert_round_count == 3
    # The sweep placed the additional rounds — more calls than the lone dispatch.
    assert mock_twilio.make_alert_call.call_count > calls_after_first


# --------------------------------------------------------------------------
# 12. test_failed_terminal_escalation_alerts_despite_prior_push  [1.3, prime directive]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_failed_terminal_escalation_alerts_despite_prior_push(_sleep, state_machine, db, mock_twilio, config):
    """A post-cap escalation still alerts even when an earlier push already succeeded.

    The silencing chain being closed: at the phone-call cap the call is suppressed,
    the ``phone_call`` action carries no SMS, and ``_maybe_send_push`` dedups on any
    prior successful push — so with one earlier push a post-cap escalation would be
    fully silenced. The fallback MUST still deliver it: an additive push (dedup
    bypassed) AND an SMS, while the call cap holds (prime directive).
    """
    config.alerts.retry.max_rounds = 1
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[test]"]
    _fail_calls(mock_twilio)

    def _push_ok(title, body, event_id, data):
        return AlertRecord(
            event_id=event_id,
            alert_type="push",
            twilio_sid=f"ticket-{uuid4().hex[:6]}",
            status="sent",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=body,
        )

    state_machine.push.send_push = MagicMock(side_effect=_push_ok)

    event = _make_event(urgency_score=10)
    db.insert_event(event)

    # First cycles: a prior successful push is recorded, the call fails, and with
    # max_rounds=1 the event reaches failed_terminal.
    for _ in range(4):
        current = db.get_event_by_id(event.id)
        if current.alert_status == "failed_terminal":
            break
        await state_machine.process_event(current)
    assert db.get_event_by_id(event.id).alert_status == "failed_terminal"
    prior_push = [r for r in db.get_alert_records(event.id) if r.alert_type == "push" and r.status == "sent"]
    assert prior_push, "a prior successful push must exist for this scenario"

    push_before = state_machine.push.send_push.call_count
    sms_before = mock_twilio.send_sms.call_count
    calls_before = mock_twilio.make_alert_call.call_count

    # A fresh escalation merges into the failed_terminal event.
    escalated = db.get_event_by_id(event.id)
    escalated.summary_pl = "Nowa eskalacja: druga fala uderzeń rakietowych."
    escalated.last_updated_at = datetime.now(UTC)
    await state_machine.process_event(escalated)

    # Something perceivable fired despite the prior push and the call cap.
    assert state_machine.push.send_push.call_count > push_before, (
        "a post-cap escalation must still push even when an earlier push succeeded"
    )
    assert mock_twilio.send_sms.call_count > sms_before, "a post-cap escalation must fall back to SMS"
    assert mock_twilio.make_alert_call.call_count == calls_before, "the phone-call cap must still hold"
