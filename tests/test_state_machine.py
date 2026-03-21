"""Tests for sentinel.alerts.state_machine."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.state_machine import (
    AlertStateMachine,
    _format_call_message,
    _format_sms_message,
    _format_update_sms,
)
from sentinel.models import AlertRecord, Article, Event


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
    # Default: calls are not answered (no-answer on first poll)
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    return twilio


@pytest.fixture
def state_machine(db, mock_twilio, config):
    """Create an AlertStateMachine with mocked dependencies."""
    return AlertStateMachine(db, mock_twilio, config)


# --------------------------------------------------------------------------
# 1. test_new_critical_event_triggers_call
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_new_critical_event_triggers_call(_sleep, state_machine, mock_twilio):
    """Urgency 10 + 2 sources -> phone call (retries until fallback to SMS)."""
    event = _make_event(urgency_score=10, source_count=2)
    state_machine.process_event(event)

    # With the aggressive retry loop, all 5 attempts fail (no-answer),
    # so make_alert_call is called 5 times, then falls back to SMS
    assert mock_twilio.make_alert_call.call_count == 5
    # 2 SMS: confirmation SMS at start + fallback SMS after all calls fail
    assert mock_twilio.send_sms.call_count == 2


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
@patch("sentinel.alerts.state_machine.time.sleep")
def test_round_exhausted_sends_sms_and_retries(_sleep, state_machine, db, mock_twilio):
    """5 failed calls in a round -> SMS sent, status retry_pending (will retry next cycle)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Process the event — all 5 attempts fail (mock returns no-answer)
    state_machine.process_event(event)

    # 5 call attempts made, then SMS fallback
    assert mock_twilio.make_alert_call.call_count == 5
    # 2 SMS: confirmation SMS at start + fallback SMS after all calls fail
    assert mock_twilio.send_sms.call_count == 2

    # Status should be retry_pending, not sms_fallback (will retry next cycle)
    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


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
@patch("sentinel.alerts.state_machine.time.sleep")
def test_cooldown_expired_allows_call(_sleep, state_machine, mock_twilio, config):
    """Acknowledged event after cooldown -> can call again."""
    cooldown_hours = config.alerts.acknowledgment.cooldown_hours
    event = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(timezone.utc)
        - timedelta(hours=cooldown_hours + 1),
    )

    state_machine.process_event(event)

    # The cooldown has expired — calls are attempted
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 12. test_new_event_bypasses_cooldown
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_new_event_bypasses_cooldown(_sleep, state_machine, mock_twilio):
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
    assert mock_twilio.make_alert_call.call_count >= 1


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
@patch("sentinel.alerts.state_machine.time.sleep")
def test_duplicate_alert_prevented(_sleep, state_machine, db, mock_twilio):
    """Same event processed twice in same cycle -> second call respects retry interval."""
    event = _make_event(urgency_score=10, source_count=2)

    # First call — triggers the full retry loop (5 attempts + SMS)
    state_machine.process_event(event)
    first_call_count = mock_twilio.make_alert_call.call_count
    assert first_call_count == 5  # all retries exhausted

    # Second call — retry interval not elapsed, skips
    state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count == first_call_count


# --------------------------------------------------------------------------
# 15. test_corroboration_upgrade_triggers_call
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_corroboration_upgrade_triggers_call(_sleep, state_machine, db, mock_twilio):
    """Event starts with 1 source -> SMS, updated to 2 sources -> phone call."""
    event_id = str(uuid4())
    article_id_1 = str(uuid4())

    # Step 1: event with 1 source -> should send SMS
    event = Event(
        id=event_id,
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja wystrzeliła rakiety.",
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=1,
        article_ids=[article_id_1],
        alert_status="pending",
    )
    state_machine.process_event(event)
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()

    # Step 2: event now has 2 sources (corroborated)
    # The sms_sent record is in the DB, but it's not a pending phone_call
    # so the state machine should re-evaluate and trigger a phone call
    article_id_2 = str(uuid4())
    event.source_count = 2
    event.article_ids = [article_id_1, article_id_2]
    event.alert_status = "pending"

    state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 16. test_retry_interval_enforced
# --------------------------------------------------------------------------
def test_retry_interval_enforced(state_machine, db, mock_twilio, config):
    """Retry is not attempted before the configured retry interval has elapsed."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Insert a recent failed call attempt (sent just now)
    recent_call = _make_alert_record(
        event.id,
        alert_type="phone_call",
        status="no-answer",
        attempt_number=1,
        sent_at=datetime.now(timezone.utc),  # just now
    )
    db.insert_alert_record(recent_call)

    # Process the event — should NOT retry because the interval hasn't elapsed
    state_machine.process_event(event)
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 17. test_retry_interval_elapsed_allows_call
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_retry_interval_elapsed_allows_call(_sleep, state_machine, db, mock_twilio, config):
    """Retry is allowed after the retry interval has elapsed."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    retry_minutes = config.alerts.acknowledgment.retry_interval_minutes

    # Insert a failed call attempt that happened well past the retry interval
    old_call = _make_alert_record(
        event.id,
        alert_type="phone_call",
        status="no-answer",
        attempt_number=1,
        sent_at=datetime.now(timezone.utc) - timedelta(minutes=retry_minutes + 1),
    )
    db.insert_alert_record(old_call)

    # Process the event — should retry because interval has elapsed
    state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 18. test_sms_format_includes_source_details
# --------------------------------------------------------------------------
def test_sms_format_includes_source_details(db, config):
    """SMS message includes per-source detail lines from the database."""
    # Insert articles into DB so the formatter can look them up
    article1 = Article(
        source_name="PAP",
        source_url="https://pap.pl/art1",
        source_type="rss",
        title="Atak rakietowy na Polskę",
        summary="Rakiety wystrzelone...",
        language="pl",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    article2 = Article(
        source_name="TVN24",
        source_url="https://tvn24.pl/art2",
        source_type="rss",
        title="Rosja atakuje Polskę rakietami",
        summary="Potwierdzony atak...",
        language="pl",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    db.insert_article(article1)
    db.insert_article(article2)

    event = Event(
        id=str(uuid4()),
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja wystrzeliła rakiety.",
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=2,
        article_ids=[article1.id, article2.id],
    )

    message = _format_sms_message(event, db, config)

    # Verify per-source lines are present
    assert "- PAP: Atak rakietowy na Polskę" in message
    assert "- TVN24: Rosja atakuje Polskę rakietami" in message
    assert "Źródła (2):" in message


# --------------------------------------------------------------------------
# 19. test_update_sms_includes_source_name
# --------------------------------------------------------------------------
def test_update_sms_includes_source_name(db, config):
    """Update SMS includes the name of the most recent source."""
    article = Article(
        source_name="Defence24",
        source_url="https://defence24.pl/art99",
        source_type="rss",
        title="Nowe szczegóły ataku",
        summary="Dodatkowe informacje...",
        language="pl",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    db.insert_article(article)

    event = Event(
        id=str(uuid4()),
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Nowe informacje o ataku.",
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=3,
        article_ids=["old-id-1", "old-id-2", article.id],
    )

    message = _format_update_sms(event, db, config)

    assert "Defence24" in message
    assert "Nowe informacje (Defence24):" in message
