"""Tests for sentinel.alerts.state_machine — 14 tests per spec."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.state_machine import AlertStateMachine, _format_sms_message
from sentinel.models import AlertRecord, Event


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_event(
    urgency_score: int = 10,
    source_count: int = 2,
    event_type: str = "missile_strike",
    alert_status: str = "pending",
    acknowledged_at: datetime | None = None,
    event_id: str | None = None,
) -> Event:
    """Helper to create an Event with customizable fields."""
    return Event(
        id=event_id or str(uuid4()),
        event_type=event_type,
        urgency_score=urgency_score,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja wystrzeliła rakiety w kierunku Polski.",
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=source_count,
        article_ids=[str(uuid4())],
        alert_status=alert_status,
        acknowledged_at=acknowledged_at,
    )


def _make_alert_record(
    event_id: str,
    alert_type: str = "phone_call",
    status: str = "initiated",
    attempt_number: int = 1,
    duration_seconds: int | None = None,
    sent_at: datetime | None = None,
) -> AlertRecord:
    """Helper to create an AlertRecord."""
    return AlertRecord(
        id=str(uuid4()),
        event_id=event_id,
        alert_type=alert_type,
        twilio_sid=f"CA_{uuid4().hex[:12]}",
        status=status,
        duration_seconds=duration_seconds,
        attempt_number=attempt_number,
        sent_at=sent_at or datetime.now(timezone.utc),
        message_body="Test alert message",
    )


@pytest.fixture
def mock_twilio():
    """Mock TwilioClient."""
    twilio = MagicMock()

    def _make_call_record(phone, message, event_id):
        return _make_alert_record(event_id, alert_type="phone_call", status="initiated")

    def _make_sms_record(phone, message, event_id):
        return _make_alert_record(event_id, alert_type="sms", status="sent")

    def _make_wa_record(phone, message, event_id):
        return _make_alert_record(event_id, alert_type="whatsapp", status="sent")

    twilio.make_alert_call.side_effect = _make_call_record
    twilio.send_sms.side_effect = _make_sms_record
    twilio.send_whatsapp.side_effect = _make_wa_record
    return twilio


@pytest.fixture
def state_machine(db, mock_twilio, config):
    """Create an AlertStateMachine with mocked dependencies."""
    return AlertStateMachine(db, mock_twilio, config)


# --------------------------------------------------------------------------
# 1. test_new_critical_event_triggers_call
# --------------------------------------------------------------------------
def test_new_critical_event_triggers_call(state_machine, mock_twilio):
    """Urgency 10 + 2 sources -> phone call."""
    event = _make_event(urgency_score=10, source_count=2)
    state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_called_once()
    mock_twilio.send_sms.assert_not_called()


# --------------------------------------------------------------------------
# 2. test_single_source_critical_triggers_sms
# --------------------------------------------------------------------------
def test_single_source_critical_triggers_sms(state_machine, mock_twilio):
    """Urgency 10 + 1 source -> SMS only (wait for corroboration)."""
    event = _make_event(urgency_score=10, source_count=1)
    state_machine.process_event(event)

    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 3. test_high_urgency_triggers_sms
# --------------------------------------------------------------------------
def test_high_urgency_triggers_sms(state_machine, mock_twilio):
    """Urgency 8 -> SMS."""
    event = _make_event(urgency_score=8, source_count=1)
    state_machine.process_event(event)

    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 4. test_medium_urgency_triggers_whatsapp
# --------------------------------------------------------------------------
def test_medium_urgency_triggers_whatsapp(state_machine, mock_twilio, config):
    """Urgency 6 -> WhatsApp."""
    # Ensure the config has the 'medium' urgency level
    # The sample_config_dict in conftest only has critical (9+) and high (7+)
    # We need to add medium for this test
    from sentinel.config import UrgencyLevel

    config.alerts.urgency_levels["medium"] = UrgencyLevel(
        min_score=5, action="whatsapp", corroboration_required=1
    )

    event = _make_event(urgency_score=6, source_count=1)
    state_machine.process_event(event)

    mock_twilio.send_whatsapp.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()


# --------------------------------------------------------------------------
# 5. test_low_urgency_logs_only
# --------------------------------------------------------------------------
def test_low_urgency_logs_only(state_machine, mock_twilio, config):
    """Urgency 3 -> no alert sent (log only)."""
    from sentinel.config import UrgencyLevel

    config.alerts.urgency_levels["low"] = UrgencyLevel(
        min_score=1, action="log_only"
    )

    event = _make_event(urgency_score=3, source_count=1)
    state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
    mock_twilio.send_whatsapp.assert_not_called()


# --------------------------------------------------------------------------
# 6. test_answered_call_acknowledged
# --------------------------------------------------------------------------
def test_answered_call_acknowledged(state_machine, db, mock_twilio):
    """Call completed, duration 30s -> acknowledged."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "completed",
        "duration": 30,
    }

    state_machine.check_pending_calls()

    # Verify event was marked as acknowledged
    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "acknowledged"
    assert updated.acknowledged_at is not None


# --------------------------------------------------------------------------
# 7. test_short_call_not_acknowledged
# --------------------------------------------------------------------------
def test_short_call_not_acknowledged(state_machine, db, mock_twilio):
    """Call completed, duration 5s -> not acknowledged, retry pending."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "completed",
        "duration": 5,
    }

    state_machine.check_pending_calls()

    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "retry_pending"
    assert updated.acknowledged_at is None


# --------------------------------------------------------------------------
# 8. test_no_answer_retry
# --------------------------------------------------------------------------
def test_no_answer_retry(state_machine, db, mock_twilio):
    """Call no-answer -> retry pending."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "no-answer",
        "duration": 0,
    }

    state_machine.check_pending_calls()

    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 9. test_max_retries_sms_fallback
# --------------------------------------------------------------------------
def test_max_retries_sms_fallback(state_machine, db, mock_twilio):
    """3 failed calls -> SMS fallback."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Insert 3 previous failed call attempts
    for i in range(3):
        rec = _make_alert_record(
            event.id,
            alert_type="phone_call",
            status="no-answer",
            attempt_number=i + 1,
        )
        db.insert_alert_record(rec)

    # Process the event again — should fall back to SMS
    state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_called_once()


# --------------------------------------------------------------------------
# 10. test_cooldown_prevents_recall
# --------------------------------------------------------------------------
def test_cooldown_prevents_recall(state_machine, mock_twilio):
    """Acknowledged event within cooldown -> no call."""
    event = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
    mock_twilio.send_whatsapp.assert_not_called()


# --------------------------------------------------------------------------
# 11. test_cooldown_expired_allows_call
# --------------------------------------------------------------------------
def test_cooldown_expired_allows_call(state_machine, mock_twilio, config):
    """Acknowledged event after cooldown -> can call again."""
    cooldown_hours = config.alerts.acknowledgment.cooldown_hours
    event = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(timezone.utc)
        - timedelta(hours=cooldown_hours + 1),
    )

    state_machine.process_event(event)

    # The cooldown has expired, but the event may still have acknowledged alerts
    # in the DB. Since there are no alerts in the DB for this event yet
    # (we didn't insert any), it should proceed to call.
    mock_twilio.make_alert_call.assert_called_once()


# --------------------------------------------------------------------------
# 12. test_new_event_bypasses_cooldown
# --------------------------------------------------------------------------
def test_new_event_bypasses_cooldown(state_machine, mock_twilio):
    """Different event during cooldown -> calls normally."""
    # Event 1: acknowledged, in cooldown
    event1 = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    state_machine.process_event(event1)
    mock_twilio.make_alert_call.assert_not_called()

    # Event 2: completely new event, different ID
    event2 = _make_event(
        urgency_score=10,
        source_count=2,
        event_type="invasion",
    )
    state_machine.process_event(event2)
    mock_twilio.make_alert_call.assert_called_once()


# --------------------------------------------------------------------------
# 13. test_acknowledged_event_gets_sms_update
# --------------------------------------------------------------------------
def test_acknowledged_event_gets_sms_update(state_machine, db, mock_twilio):
    """Event updated after acknowledgment -> SMS update sent."""
    event = _make_event(urgency_score=10, source_count=2)

    # Create an acknowledged alert record with a sent_at in the past
    past_time = datetime.now(timezone.utc) - timedelta(hours=1)
    record = _make_alert_record(
        event.id,
        alert_type="phone_call",
        status="acknowledged",
        sent_at=past_time,
    )
    db.insert_alert_record(record)

    # The event was updated after the last alert
    event.last_updated_at = datetime.now(timezone.utc)

    state_machine.process_event(event)

    # Should have sent an update SMS
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 14. test_duplicate_alert_prevented
# --------------------------------------------------------------------------
def test_duplicate_alert_prevented(state_machine, db, mock_twilio):
    """Same event processed twice in same cycle -> alerted only once."""
    event = _make_event(urgency_score=10, source_count=2)

    # First call — should trigger
    state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count == 1

    # Second call — the alert record from the first call is now in the DB
    # with status "initiated", so the state machine should skip
    state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count == 1
