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
from sentinel.classification.corroborator import Corroborator
from sentinel.config import RetryConfig
from sentinel.database import Database
from sentinel.models import AlertRecord, Article, ClassificationResult, Event

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


def _corr_article(source_url: str, title: str) -> Article:
    """Build a critical (invasion-of-Poland) Article for the corroborator path."""
    return Article(
        source_name="TestSource",
        source_url=source_url,
        source_type="rss",
        title=title,
        summary="Russian forces have begun operations.",
        language="en",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )


def _corr_classification(article: Article, summary_pl: str) -> ClassificationResult:
    """Build a call-tier ClassificationResult that will merge into the seeded event."""
    return ClassificationResult(
        article_id=article.id,
        is_military_event=True,
        event_type="invasion",
        urgency_score=9,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=False,
        confidence=0.9,
        summary_pl=summary_pl,
        classified_at=datetime.now(UTC),
        model_used="claude-haiku-4-5-20251001",
        input_tokens=287,
        output_tokens=94,
    )


def _seed_call_tier_event(db, article: Article, alert_status: str) -> Event:
    """Insert a call-tier (invasion-of-Poland) event in the given alert_status."""
    summary_pl = "Rosja dokonala inwazji na Polske."
    event = Event(
        event_type="invasion",
        urgency_score=9,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl=summary_pl,
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=2,
        article_ids=[article.id],
        alert_status=alert_status,
        acknowledged_at=None,
    )
    db.insert_event(event)
    return event


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


# --------------------------------------------------------------------------
# 13. test_merge_preserves_retry_pending_status  [1.2, 1.3]
# --------------------------------------------------------------------------
def test_merge_preserves_retry_pending_status(db, config):
    """A merge into a retry_pending event must not overwrite its alert_status.

    A failed phone round leaves a call-tier event in ``retry_pending`` — the sole
    signal the cycle-driven retry sweep (``get_events_by_alert_status`` →
    ``retry_pending_calls``) uses to keep retrying it up to the cap. The
    corroborator re-runs ``_update_event`` on EVERY matched article (even a
    non-independent syndicated copy), and its ``_determine_alert_status`` knows
    nothing of the retry lifecycle. If the merge re-derived the status the event
    would drop out of the sweep and a failed urgency-9/10 call would never be
    retried (prime-directive miss). The retry-lifecycle status must survive.
    """
    corroborator = Corroborator(db, config)
    assert not corroborator.dry_run, "guard test needs a real (non-dry-run) status derivation"

    seed_article = _corr_article("https://source-a.com/a1", "Russia invades Poland")
    db.insert_article(seed_article)
    event = _seed_call_tier_event(db, seed_article, alert_status="retry_pending")

    # A fresh corroborating article merges into the retry_pending event.
    new_article = _corr_article("https://source-b.com/a2", "Russian invasion of Poland confirmed")
    db.insert_article(new_article)
    classification = _corr_classification(new_article, event.summary_pl)

    corroborator.process_classifications([classification])

    merged = db.get_event_by_id(event.id)
    # The article actually merged (source grew) ...
    assert new_article.id in merged.article_ids
    # ... but the retry-lifecycle status was preserved, not clobbered.
    assert merged.alert_status == "retry_pending"
    # ... so the cycle-driven sweep still returns it and keeps driving the retry.
    assert any(e.id == event.id for e in db.get_events_by_alert_status("retry_pending"))


# --------------------------------------------------------------------------
# 14. test_merge_preserves_failed_terminal_status  [1.2, 1.3]
# --------------------------------------------------------------------------
def test_merge_preserves_failed_terminal_status(db, config):
    """A merge into a failed_terminal event must not erase its terminal marker.

    ``failed_terminal`` is the terminal state that keeps ``process_event``'s
    post-cap SMS+push fallback routing genuinely new content. A later merged
    article must not knock the event back to a live phone-call status, which
    would re-open the exhausted retry loop and lose the fallback marker.
    """
    corroborator = Corroborator(db, config)
    assert not corroborator.dry_run, "guard test needs a real (non-dry-run) status derivation"

    seed_article = _corr_article("https://source-a.com/b1", "Russia invades Poland")
    db.insert_article(seed_article)
    event = _seed_call_tier_event(db, seed_article, alert_status="failed_terminal")

    new_article = _corr_article("https://source-b.com/b2", "Russian invasion of Poland confirmed")
    db.insert_article(new_article)
    classification = _corr_classification(new_article, event.summary_pl)

    corroborator.process_classifications([classification])

    merged = db.get_event_by_id(event.id)
    assert new_article.id in merged.article_ids
    assert merged.alert_status == "failed_terminal"


# --------------------------------------------------------------------------
# 15. test_call_result_does_not_clobber_resolved  [1.2, one-call-per-event]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_status", ["acknowledged", "failed_terminal"])
async def test_call_result_does_not_clobber_resolved(state_machine, db, resolved_status):
    """A late call-status poll must not re-arm retry on an already-resolved event.

    A call placed in a prior round can be polled a cycle later. If the event was
    resolved in the meantime — acknowledged out-of-band by an SMS reply, or moved
    to ``failed_terminal`` by the round cap — ``_handle_call_result`` must NOT
    overwrite its ``alert_status`` back to ``retry_pending``. Doing so would feed an
    acknowledged event back into the retry sweep and place a SECOND call on it
    (breaking one-call-per-event), or re-open the exhausted cap.
    """
    event = _make_event(urgency_score=10)
    event.alert_status = resolved_status
    event.acknowledged_at = datetime.now(UTC) if resolved_status == "acknowledged" else None
    db.insert_event(event)

    record = AlertRecord(
        event_id=event.id,
        alert_type="phone_call",
        twilio_sid="CA-late",
        status="initiated",
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="x",
    )
    db.insert_alert_record(record)

    await state_machine._handle_call_result(record, {"status": "no-answer", "duration": 0})

    assert db.get_event_by_id(event.id).alert_status == resolved_status


# --------------------------------------------------------------------------
# 16. test_acknowledge_resolves_pending_call_records  [1.2, one-call-per-event]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_acknowledge_resolves_pending_call_records(state_machine, db, mock_twilio):
    """Acknowledgment clears any still-in-flight call record for the event.

    An SMS ack can land while a call is ``initiated``/``ringing``. If that record
    is left in-flight, the next cycle's poll (``get_pending_call_records``)
    re-touches it. Acknowledgment marks it resolved so no stale in-flight row
    survives to trigger a re-poll → clobber → second call.
    """
    event = _make_event(urgency_score=10)
    db.insert_event(event)
    db.insert_alert_record(
        AlertRecord(
            event_id=event.id,
            alert_type="phone_call",
            twilio_sid="CA-inflight",
            status="initiated",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body="x",
        )
    )

    await state_machine._acknowledge_event(event, total_attempts=1)

    assert all(r.event_id != event.id for r in db.get_pending_call_records())
    assert db.get_event_by_id(event.id).alert_status == "acknowledged"


# --------------------------------------------------------------------------
# 17. test_acknowledged_event_not_recalled_by_pending_poll  [1.2, one-call-per-event]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_acknowledged_event_not_recalled_by_pending_poll(_sleep, state_machine, db, mock_twilio, config):
    """End-to-end: a full check_pending_calls cycle never re-calls an acked event.

    Reproduces the silent-second-call chain: an acknowledged event with a stale
    in-flight call record. ``check_pending_calls`` polls the stale record, gets a
    terminal call status, and (pre-guard) would clobber the event back to
    ``retry_pending``, whereupon the retry sweep would place a second call. With
    the guards in place the event stays acknowledged and NO second call is placed.
    """
    config.alerts.acknowledgment.retry_interval_minutes = 0
    event = _make_event(urgency_score=10)
    event.alert_status = "acknowledged"
    event.acknowledged_at = datetime.now(UTC)
    db.insert_event(event)

    db.insert_alert_record(
        AlertRecord(
            event_id=event.id,
            alert_type="phone_call",
            twilio_sid="CA-stale",
            status="initiated",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body="x",
        )
    )
    mock_twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    calls_before = mock_twilio.make_alert_call.call_count

    await state_machine.check_pending_calls()

    assert db.get_event_by_id(event.id).alert_status == "acknowledged"
    assert mock_twilio.make_alert_call.call_count == calls_before


# --------------------------------------------------------------------------
# 18. test_dry_run_cycle_places_no_retry_call  [dry-run safety]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_dry_run_cycle_places_no_retry_call(_sleep, state_machine, db, mock_twilio, config):
    """A ``--dry-run`` cycle must place no real call/SMS for a retry_pending event.

    The retry sweep runs inside ``check_pending_calls`` on every non-diagnostic
    cycle. Without a dry-run gate it would fire real Twilio calls for any DB
    ``retry_pending`` row (e.g. an unacknowledged ``--test-alert`` leftover),
    breaking the run-locally-by-default contract. In dry-run the sweep is a no-op.
    """
    config.testing.dry_run = True
    config.alerts.acknowledgment.retry_interval_minutes = 0

    event = _make_event(urgency_score=10)
    event.alert_status = "retry_pending"
    db.insert_event(event)

    await state_machine.check_pending_calls()

    assert mock_twilio.make_alert_call.call_count == 0
    assert mock_twilio.send_sms.call_count == 0


# --------------------------------------------------------------------------
# 19. test_transport_failed_rounds_are_interval_spaced  [1.2]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_transport_failed_rounds_are_interval_spaced(_sleep, state_machine, db, mock_twilio, config):
    """During a transport outage the retry rounds are SPACED by the interval.

    Every round is transport-failed (Twilio accepts no call), so there is no
    in-flight record to poll and the retry sweep is the only thing re-entering the
    event. If transport-failed rounds did not count toward the retry interval, a
    dispatch round plus the same-cycle sweep — then one round per cycle — would burn
    the ``max_rounds`` cap back-to-back within minutes, killing the call channel for
    the whole outage. Spacing must count the failed rounds so the cap spans the
    configured window; and it must be the config interval, not a permanent stall.
    """
    config.alerts.retry.max_rounds = 5
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 5
    _fail_calls(mock_twilio)

    event = _make_event(urgency_score=10)
    db.insert_event(event)

    # Round 1 via dispatch.
    await state_machine.process_event(db.get_event_by_id(event.id))
    assert db.get_event_by_id(event.id).alert_round_count == 1
    calls_after_round1 = mock_twilio.make_alert_call.call_count

    # Repeated sweeps inside the interval must NOT advance further rounds, even
    # though every round is transport-failed.
    for _ in range(4):
        await state_machine.check_pending_calls()
    assert db.get_event_by_id(event.id).alert_round_count == 1
    assert mock_twilio.make_alert_call.call_count == calls_after_round1

    # Removing the interval lets the next sweep advance a round — the spacing was
    # the config interval, not a stall.
    config.alerts.acknowledgment.retry_interval_minutes = 0
    await state_machine.check_pending_calls()
    assert db.get_event_by_id(event.id).alert_round_count == 2
    assert mock_twilio.make_alert_call.call_count > calls_after_round1


# --------------------------------------------------------------------------
# 20. test_sweep_ignores_stale_retry_pending  [deploy-time storm guard]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_sweep_ignores_stale_retry_pending(_sleep, state_machine, db, mock_twilio, config):
    """A SAME-UTC-DAY stale ``retry_pending`` row beyond the window is NOT swept.

    ``get_events_by_alert_status`` had no recency bound, so on the first post-deploy
    cycle every historical ``retry_pending`` event still within DB retention would
    restart phone rounds at once (a call storm), as would an unacknowledged
    ``--test-alert`` leftover. The sweep is bounded by
    ``alerts.retry.sweep_max_age_minutes``.

    This exercises the format-consistency of that bound. The stored column holds
    ISO timestamps with a 'T' separator; comparing them against SQLite's
    ``datetime('now', ...)`` (a SPACE separator) is a mixed-format TEXT compare in
    which ANY row sharing the current UTC calendar date sorts GREATER than the
    threshold ('T' 0x54 > ' ' 0x20) and passes regardless of age — so a same-day
    stale row would resume real phone rounds after a deploy. The stale row here is
    the SAME UTC calendar date as "now" but far older than the window, so it would
    be (wrongly) swept under a mixed-format compare and is correctly aged out only
    when the cutoff matches the stored format.

    ``datetime.now`` in the DB layer is pinned so the same-day stale row is
    deterministically older than the window regardless of wall-clock time (near
    UTC midnight a real ``now - hours`` would slip to the previous calendar date
    and stop exercising the same-day path this guards).
    """
    config.alerts.retry.sweep_max_age_minutes = 60
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    _fail_calls(mock_twilio)

    fixed_now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    # Same UTC calendar date as fixed_now, but ~12h old — far beyond the 60-min window.
    stale_ts = fixed_now.replace(hour=0, minute=0, second=1, microsecond=0)
    assert stale_ts.date() == fixed_now.date(), "stale row must share the current UTC date"

    stale = _make_event(urgency_score=10, event_id="stale")
    stale.alert_status = "retry_pending"
    stale.last_updated_at = stale_ts
    db.insert_event(stale)

    with patch("sentinel.database.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now

        calls_before = mock_twilio.make_alert_call.call_count
        await state_machine.retry_pending_calls()
        assert mock_twilio.make_alert_call.call_count == calls_before, (
            "a same-UTC-day row older than the window must NOT be swept"
        )

        # A fresh retry_pending event within the window IS swept.
        fresh = _make_event(urgency_score=10, event_id="fresh")
        fresh.alert_status = "retry_pending"
        fresh.last_updated_at = fixed_now
        db.insert_event(fresh)
        await state_machine.retry_pending_calls()
        assert mock_twilio.make_alert_call.call_count > calls_before


# --------------------------------------------------------------------------
# 21. test_capped_fallback_throttles_syndicated_remerges  [don't-spam]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_capped_fallback_throttles_syndicated_remerges(_sleep, state_machine, db, mock_twilio, config):
    """A failed_terminal event does not re-spam SMS+push on every syndicated merge.

    The corroborator re-dispatches a ``failed_terminal`` event on EVERY merged
    article, including non-independent syndicated copies that add nothing. The
    post-cap fallback must fire once, then suppress redundant re-sends within the
    interval — yet still deliver genuinely-new independent corroboration
    (``source_count`` grew) even inside that window (prime directive).
    """
    config.alerts.retry.max_rounds = 1
    config.alerts.acknowledgment.retry_interval_minutes = 30
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[test]"]

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

    event = _make_event(urgency_score=10, source_count=2)
    event.alert_status = "failed_terminal"
    event.alert_round_count = 1
    db.insert_event(event)

    # First post-cap dispatch fires exactly one fallback SMS + push.
    await state_machine.process_event(db.get_event_by_id(event.id))
    push_after_first = state_machine.push.send_push.call_count
    sms_after_first = mock_twilio.send_sms.call_count
    assert push_after_first == 1
    assert sms_after_first == 1

    # Syndicated copies of the same story re-merge (source_count unchanged) inside
    # the window: none may fire another fallback.
    for _ in range(3):
        await state_machine.process_event(db.get_event_by_id(event.id))
    assert state_machine.push.send_push.call_count == push_after_first
    assert mock_twilio.send_sms.call_count == sms_after_first

    # Genuinely-new independent corroboration (source_count grows) still gets
    # through even inside the window.
    db.update_event(event.id, source_count=3)
    await state_machine.process_event(db.get_event_by_id(event.id))
    assert state_machine.push.send_push.call_count > push_after_first
    assert mock_twilio.send_sms.call_count > sms_after_first


# --------------------------------------------------------------------------
# 22. test_failed_confirmation_sms_keeps_prior_code_matchable  [1.2, 1.5]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_confirmation_sms_keeps_prior_code_matchable(state_machine, db, mock_twilio):
    """A failed confirmation-SMS send must not rotate away the last delivered code.

    Each phone-retry round regenerates the 6-digit confirmation code before
    sending it. If a later round's send FAILS (a voice-up / SMS-down carrier
    split), the active code must stay the last successfully-DELIVERED one — the
    only code the operator actually holds — so a correct reply still acknowledges
    the event. Rotating the active code to the undelivered value instead would
    leave the operator's real code unmatched and, under the bounded retry cap
    (1.2), burn a call-tier event to ``failed_terminal`` despite a correct answer.
    Keeping the delivered code and its SID paired also keeps the within-round
    resend guard consistent.
    """
    event = _make_event(event_id="evt-conf")
    db.insert_event(event)

    # Round 1: the confirmation SMS is delivered with code A (111111).
    with patch("sentinel.alerts.state_machine.random.randint", return_value=111111):
        await state_machine._send_confirmation_sms(event)
    assert state_machine._confirmation_codes[event.id] == "111111"
    delivered_sid = state_machine._confirmation_sms_sids[event.id]

    # Round 2: the confirmation SMS send FAILS and would have carried code B.
    def _fail_sms(phone, message, event_id):
        return AlertRecord(
            event_id=event_id,
            alert_type="sms",
            twilio_sid="",
            status="failed",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=message,
            error_code="30008",
            error_detail="unknown delivery error",
        )

    mock_twilio.send_sms.side_effect = _fail_sms
    with patch("sentinel.alerts.state_machine.random.randint", return_value=222222):
        await state_machine._send_confirmation_sms(event)

    # The failed send never rotated the active code or its tracked SID away from
    # round 1's delivered values.
    assert state_machine._confirmation_codes[event.id] == "111111"
    assert state_machine._confirmation_sms_sids[event.id] == delivered_sid

    # The failure is still durably recorded (fail-loud, never a silent drop).
    failed_sms = [r for r in db.get_alert_records(event.id) if r.alert_type == "sms" and r.status == "failed"]
    assert failed_sms, "a failed confirmation SMS must still persist a failed row"

    since = datetime.now(UTC) - timedelta(minutes=1)

    # The undelivered code B does NOT acknowledge (it was never made active) ...
    reply_b = MagicMock()
    reply_b.body = "222222"
    mock_twilio.client.messages.list.return_value = [reply_b]
    assert await state_machine._check_sms_confirmation(since, event.id) is False

    # ... while a reply carrying the last DELIVERED code A still acknowledges.
    reply_a = MagicMock()
    reply_a.body = "111111"
    mock_twilio.client.messages.list.return_value = [reply_a]
    assert await state_machine._check_sms_confirmation(since, event.id) is True


# --------------------------------------------------------------------------
# 23. test_confirmation_matches_prior_round_code_and_widens_window  [1.5]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_confirmation_matches_prior_round_code_and_widens_window(state_machine, mock_twilio):
    """A correct reply carrying an EARLIER round's code, sent before the current
    round's ``call_placed_at``, still acknowledges.

    Two exclusion axes are closed at once. (a) Code axis: each round's confirmation
    SMS rotates the active code, so the match must consider EVERY code sent for the
    event, not just the latest. (b) Timestamp axis: a reply that lands in the gap
    between rounds is sent BEFORE the current round's ``since``, so the scan must
    widen to the event's first-round window start (``_confirmation_window_start``)
    or the reply is filtered out by ``date_sent_after``. Under the previous
    single-code / current-``since`` logic this reply was lost on both axes — and,
    under the bounded cap (1.2), that burns a call-tier event to failed_terminal
    despite a correct operator answer.
    """
    event_id = "evt-multi-round"

    t0 = datetime(2026, 7, 11, 10, 0, 0, tzinfo=UTC)  # round 1 placement (window start)
    t_reply = datetime(2026, 7, 11, 10, 3, 0, tzinfo=UTC)  # reply lands between rounds
    t2 = datetime(2026, 7, 11, 10, 5, 0, tzinfo=UTC)  # round 2 placement (current `since`)

    # Two delivered rounds: codes 111111 then 222222; scan window pinned to t0.
    state_machine._confirmation_code_history[event_id] = {"111111", "222222"}
    state_machine._confirmation_codes[event_id] = "222222"
    state_machine._confirmation_window_start[event_id] = t0

    captured: dict = {}

    def _list_filtered(to=None, from_=None, date_sent_after=None, limit=10):
        captured["date_sent_after"] = date_sent_after
        reply = MagicMock()
        reply.body = "111111"  # operator replied with round 1's (now-rotated) code
        reply.date_sent = t_reply
        # Emulate Twilio's date_sent_after filter.
        if date_sent_after is not None and reply.date_sent <= date_sent_after:
            return []
        return [reply][:limit]

    mock_twilio.client.messages.list.side_effect = _list_filtered

    # Called with the CURRENT round's `since` (t2, AFTER the reply): still matches.
    assert await state_machine._check_sms_confirmation(t2, event_id) is True
    # The query was widened to the first-round window start, not the passed t2.
    assert captured["date_sent_after"] == t0


# --------------------------------------------------------------------------
# 24. test_pending_reply_acknowledges_at_retry_cap  [1.2, 1.5]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_pending_reply_acknowledges_at_retry_cap(_sleep, state_machine, db, mock_twilio, config):
    """A correct reply on the cap-exhausting round acknowledges, never failed_terminal.

    When the durable round counter reaches ``max_rounds`` the sweep re-enters
    ``_execute_phone_call`` to finalize the event. If the operator's correct reply
    (carrying a delivered code) arrived just before that re-entry, it MUST be
    honored — otherwise a timely acknowledgment is silently lost and the call-tier
    event is wrongly burned to failed_terminal (and up to that point the operator
    is spam-called after already complying).
    """
    config.alerts.retry.max_rounds = 2
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0
    _fail_calls(mock_twilio)  # calls fail; the confirmation SMS still delivers (default mock)

    event = _make_event(urgency_score=10)
    db.insert_event(event)

    # Fix the confirmation code so we can reply with exactly what was delivered.
    with patch("sentinel.alerts.state_machine.random.randint", return_value=424242):
        # Round 1 via dispatch, round 2 via the sweep: counter reaches the cap (2),
        # event left retry_pending (the cap-exhausting re-entry has not run yet).
        await state_machine.process_event(db.get_event_by_id(event.id))
        assert db.get_event_by_id(event.id).alert_round_count == 1
        await state_machine.check_pending_calls()
        capped = db.get_event_by_id(event.id)
        assert capped.alert_round_count == 2
        assert capped.alert_status == "retry_pending"
        assert "424242" in state_machine._confirmation_code_history[event.id]

        calls_before = mock_twilio.make_alert_call.call_count

        # The operator replies with the delivered code, landing before the
        # cap-exhausting sweep re-entry.
        reply = MagicMock()
        reply.body = "Potwierdzam 424242"
        mock_twilio.client.messages.list.return_value = [reply]

        # The next sweep hits the cap in _execute_phone_call; it must acknowledge.
        await state_machine.check_pending_calls()

    final = db.get_event_by_id(event.id)
    assert final.alert_status == "acknowledged", "a correct reply at the cap must acknowledge, not failed_terminal"
    assert final.alert_status != "failed_terminal"
    # No additional call placed once the pending reply is honored.
    assert mock_twilio.make_alert_call.call_count == calls_before


# --------------------------------------------------------------------------
# 25. test_sweep_recovers_stranded_mid_round_event  [1.3, prime directive]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("stranded_status", ["call_placed", "phone_call"])
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_sweep_recovers_stranded_mid_round_event(_sleep, stranded_status, state_machine, db, mock_twilio, config):
    """A crash mid-round strands a call-tier event; the cycle-driven sweep recovers it.

    Neither ``call_placed`` (a call was placed, the process died before the
    round-end transition to retry_pending) nor ``phone_call`` (the corroborator's
    initial call-tier status, crashed before any call landed) leaves an
    ``initiated``/``ringing`` record for ``check_pending_calls``'s poll to pick up,
    and a single-source event attracts no further merging article to re-dispatch it
    via ``process_event``. The sweep must re-enter such an event and place its call
    instead of leaving it silently stranded (a fail-silent 9-10 miss).
    """
    config.alerts.retry.max_rounds = 3
    config.alerts.acknowledgment.max_call_retries = 1
    config.alerts.acknowledgment.retry_interval_minutes = 0

    event = _make_event(urgency_score=10, source_count=2)
    event.alert_status = stranded_status
    db.insert_event(event)

    # call_placed mirrors a crash AFTER the round's call record was resolved to a
    # terminal status (no longer in-flight, so the poll finds nothing).
    if stranded_status == "call_placed":
        db.insert_alert_record(
            AlertRecord(
                event_id=event.id,
                alert_type="phone_call",
                twilio_sid="CA-resolved",
                status="no-answer",
                attempt_number=1,
                sent_at=datetime.now(UTC) - timedelta(minutes=10),
                message_body="x",
            )
        )

    calls_before = mock_twilio.make_alert_call.call_count
    await state_machine.retry_pending_calls()

    # The stranded event was re-entered and a fresh call placed (recovery) ...
    assert mock_twilio.make_alert_call.call_count > calls_before, (
        "a crash-stranded call-tier event must be recovered by the sweep"
    )
    # ... and it advanced into the normal retry lifecycle.
    assert db.get_event_by_id(event.id).alert_status in ("retry_pending", "call_placed", "acknowledged")


# --------------------------------------------------------------------------
# 26. test_sweep_skips_event_with_inflight_call  [one-call-per-event]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_sweep_skips_event_with_inflight_call(_sleep, state_machine, db, mock_twilio, config):
    """The broadened sweep must not double-call an event whose call is still in-flight.

    A ``call_placed`` event can have a still-``initiated``/``ringing`` call record
    (the crash happened while the call was live). That record is owned by
    ``check_pending_calls``'s poll; the sweep re-entering it would place a SECOND
    concurrent call. The in-flight guard skips it, preserving one-call-per-event.
    """
    config.alerts.acknowledgment.retry_interval_minutes = 0

    event = _make_event(urgency_score=10)
    event.alert_status = "call_placed"
    db.insert_event(event)
    db.insert_alert_record(
        AlertRecord(
            event_id=event.id,
            alert_type="phone_call",
            twilio_sid="CA-inflight",
            status="ringing",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body="x",
        )
    )

    calls_before = mock_twilio.make_alert_call.call_count
    await state_machine.retry_pending_calls()

    assert mock_twilio.make_alert_call.call_count == calls_before, (
        "an event with an in-flight call must not be re-called by the sweep"
    )
