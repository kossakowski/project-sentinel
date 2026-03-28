"""Tests for sentinel.alerts.state_machine — multi-user per-event routing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.state_machine import (
    AlertStateMachine,
    _format_call_message,
    _format_sms_message,
    _format_update_sms,
    _resolve_channel_from_preset,
    _fallback_channel,
)
from sentinel.models import (
    AlertRecord,
    Article,
    ConfirmationCode,
    Event,
    Tier,
    User,
    UserAlertRule,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_event(
    urgency_score: int = 10,
    source_count: int = 2,
    event_type: str = "missile_strike",
    alert_status: str = "pending",
    acknowledged_at: datetime | None = None,
    event_id: str | None = None,
    affected_countries: list[str] | None = None,
) -> Event:
    """Helper to create an Event with customizable fields."""
    return Event(
        id=event_id or str(uuid4()),
        event_type=event_type,
        urgency_score=urgency_score,
        affected_countries=affected_countries or ["PL"],
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
    user_id: str | None = None,
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
        user_id=user_id,
    )


def _create_standard_tier(db) -> Tier:
    """Create and insert the Standard tier."""
    tier = Tier(
        name=f"Standard-{uuid4().hex[:6]}",
        available_channels=["sms", "whatsapp"],
        max_countries=1,
        preference_mode="preset",
        preset_rules={
            "9-10": "phone_call",
            "7-8": "sms",
            "5-6": "whatsapp",
            "1-4": "log_only",
        },
    )
    db.insert_tier(tier)
    return tier


def _create_premium_tier(db) -> Tier:
    """Create and insert the Premium tier."""
    tier = Tier(
        name=f"Premium-{uuid4().hex[:6]}",
        available_channels=["phone_call", "sms", "whatsapp"],
        max_countries=None,
        preference_mode="customizable",
        preset_rules=None,
    )
    db.insert_tier(tier)
    return tier


def _create_user(
    db, tier: Tier, phone: str = "+48123456789", name: str = "Test User",
    countries: list[str] | None = None,
) -> User:
    """Create and insert a user with country associations."""
    user = User(
        name=name,
        phone_number=phone,
        tier_id=tier.id,
        language="pl",
    )
    db.insert_user(user)
    for country in (countries or ["PL"]):
        db.insert_user_country(user.id, country)
    return user


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


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


@pytest.fixture
def premium_user(db):
    """Create a Premium tier user monitoring PL."""
    tier = _create_premium_tier(db)
    user = _create_user(db, tier, phone="+48111111111", name="Premium User")
    # Add rules for premium user
    rule_critical = UserAlertRule(
        user_id=user.id,
        min_urgency=9,
        max_urgency=10,
        channel="phone_call",
        corroboration_required=2,
        priority=10,
    )
    rule_high = UserAlertRule(
        user_id=user.id,
        min_urgency=7,
        max_urgency=8,
        channel="sms",
        priority=5,
    )
    rule_medium = UserAlertRule(
        user_id=user.id,
        min_urgency=5,
        max_urgency=6,
        channel="whatsapp",
        priority=3,
    )
    db.insert_user_alert_rule(rule_critical)
    db.insert_user_alert_rule(rule_high)
    db.insert_user_alert_rule(rule_medium)
    return user


@pytest.fixture
def standard_user(db):
    """Create a Standard tier user monitoring PL."""
    tier = _create_standard_tier(db)
    user = _create_user(db, tier, phone="+48222222222", name="Standard User")
    return user


# --------------------------------------------------------------------------
# Unit tests for helper functions
# --------------------------------------------------------------------------


def test_resolve_channel_from_preset_critical():
    """Urgency 10 in preset rules resolves to phone_call."""
    rules = {"9-10": "phone_call", "7-8": "sms", "5-6": "whatsapp", "1-4": "log_only"}
    assert _resolve_channel_from_preset(rules, 10) == "phone_call"
    assert _resolve_channel_from_preset(rules, 9) == "phone_call"


def test_resolve_channel_from_preset_high():
    """Urgency 7-8 resolves to sms."""
    rules = {"9-10": "phone_call", "7-8": "sms", "5-6": "whatsapp", "1-4": "log_only"}
    assert _resolve_channel_from_preset(rules, 8) == "sms"
    assert _resolve_channel_from_preset(rules, 7) == "sms"


def test_resolve_channel_from_preset_no_match():
    """Urgency 0 resolves to log_only (no matching rule)."""
    rules = {"9-10": "phone_call", "7-8": "sms"}
    assert _resolve_channel_from_preset(rules, 0) == "log_only"


def test_fallback_channel_available():
    """Channel in available list returns as-is."""
    assert _fallback_channel("sms", ["phone_call", "sms", "whatsapp"]) == "sms"


def test_fallback_channel_not_available():
    """phone_call not in available falls to sms."""
    assert _fallback_channel("phone_call", ["sms", "whatsapp"]) == "sms"


def test_fallback_channel_all_blocked():
    """All channels blocked falls to log_only."""
    assert _fallback_channel("phone_call", []) == "log_only"


def test_fallback_channel_only_whatsapp():
    """Only whatsapp available, phone_call requested -> whatsapp."""
    assert _fallback_channel("phone_call", ["whatsapp"]) == "whatsapp"


# --------------------------------------------------------------------------
# 1. Multi-user dispatch: event affecting PL alerts all PL-monitoring users
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_multi_user_dispatch(_sleep, state_machine, db, mock_twilio):
    """Event affecting PL alerts both PL-monitoring users."""
    tier = _create_premium_tier(db)
    user_a = _create_user(db, tier, phone="+48111111111", name="User A", countries=["PL"])
    user_b = _create_user(db, tier, phone="+48222222222", name="User B", countries=["PL"])

    # Add sms rules for both users so they get SMS (simpler to test than calls)
    for u in [user_a, user_b]:
        db.insert_user_alert_rule(UserAlertRule(
            user_id=u.id, min_urgency=7, max_urgency=10, channel="sms", priority=10,
        ))

    event = _make_event(urgency_score=8, source_count=2)
    db.insert_event(event)

    state_machine.process_event(event)

    # Both users should get SMS
    assert mock_twilio.send_sms.call_count == 2
    called_phones = {call.args[0] for call in mock_twilio.send_sms.call_args_list}
    assert "+48111111111" in called_phones
    assert "+48222222222" in called_phones


# --------------------------------------------------------------------------
# 2. Premium user with customizable rules gets routed correctly
# --------------------------------------------------------------------------
def test_premium_customizable_routing_sms(state_machine, db, mock_twilio, premium_user):
    """Premium user: urgency 8 -> sms (from user_alert_rules)."""
    event = _make_event(urgency_score=8, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)

    mock_twilio.send_sms.assert_called_once()
    assert mock_twilio.send_sms.call_args[0][0] == "+48111111111"


def test_premium_customizable_routing_whatsapp(state_machine, db, mock_twilio, premium_user):
    """Premium user: urgency 5 -> whatsapp (from user_alert_rules)."""
    event = _make_event(urgency_score=5, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)

    mock_twilio.send_whatsapp.assert_called_once()
    assert mock_twilio.send_whatsapp.call_args[0][0] == "+48111111111"


@patch("sentinel.alerts.state_machine.time.sleep")
def test_premium_customizable_routing_phone_call(
    _sleep, state_machine, db, mock_twilio, premium_user
):
    """Premium user: urgency 10 -> phone_call (from user_alert_rules)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)

    assert mock_twilio.make_alert_call.call_count >= 1
    assert mock_twilio.make_alert_call.call_args[0][0] == "+48111111111"


# --------------------------------------------------------------------------
# 3. Standard user with preset rules gets routed correctly
# --------------------------------------------------------------------------
def test_standard_preset_routing_sms(state_machine, db, mock_twilio, standard_user):
    """Standard user: urgency 7 -> sms from preset, sms is in available_channels."""
    event = _make_event(urgency_score=7, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, standard_user)

    mock_twilio.send_sms.assert_called_once()
    assert mock_twilio.send_sms.call_args[0][0] == "+48222222222"


def test_standard_preset_routing_whatsapp(state_machine, db, mock_twilio, standard_user):
    """Standard user: urgency 5 -> whatsapp from preset."""
    event = _make_event(urgency_score=5, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, standard_user)

    mock_twilio.send_whatsapp.assert_called_once()


# --------------------------------------------------------------------------
# 4. Channel fallback: Standard tier disallows phone_call
# --------------------------------------------------------------------------
def test_standard_tier_phone_call_falls_back_to_sms(
    state_machine, db, mock_twilio, standard_user
):
    """Standard tier: preset says phone_call for urgency 10, but phone_call not
    in available_channels -> falls back to sms."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    state_machine._process_event_for_user(event, standard_user)

    # phone_call not in standard available_channels [sms, whatsapp]
    # Falls back to sms (next in severity order)
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 5. Per-user cooldown independence
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_per_user_cooldown_independence(_sleep, state_machine, db, mock_twilio):
    """User A acknowledged -> in cooldown. User B still gets alerted."""
    tier = _create_premium_tier(db)
    user_a = _create_user(db, tier, phone="+48111111111", name="User A", countries=["PL"])
    user_b = _create_user(db, tier, phone="+48222222222", name="User B", countries=["PL"])

    for u in [user_a, user_b]:
        db.insert_user_alert_rule(UserAlertRule(
            user_id=u.id, min_urgency=7, max_urgency=10, channel="sms", priority=10,
        ))

    event = _make_event(urgency_score=8, source_count=2)
    db.insert_event(event)

    # User A has an acknowledged alert (in cooldown)
    ack_record = _make_alert_record(
        event.id,
        alert_type="sms",
        status="acknowledged",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
        user_id=user_a.id,
    )
    db.insert_alert_record(ack_record)

    state_machine.process_event(event)

    # User A: in cooldown, no alert
    # User B: gets SMS
    assert mock_twilio.send_sms.call_count == 1
    assert mock_twilio.send_sms.call_args[0][0] == "+48222222222"


# --------------------------------------------------------------------------
# 6. Single user acknowledge does NOT block other users
# --------------------------------------------------------------------------
def test_single_user_ack_does_not_block_others(state_machine, db, mock_twilio):
    """User A acknowledges event -> User B still gets alerted (not blocked)."""
    tier = _create_premium_tier(db)
    user_a = _create_user(db, tier, phone="+48111111111", name="User A", countries=["PL"])
    user_b = _create_user(db, tier, phone="+48222222222", name="User B", countries=["PL"])

    for u in [user_a, user_b]:
        db.insert_user_alert_rule(UserAlertRule(
            user_id=u.id, min_urgency=7, max_urgency=10, channel="sms", priority=10,
        ))

    event = _make_event(urgency_score=8, source_count=2)
    db.insert_event(event)

    # User A has acknowledged
    ack_record_a = _make_alert_record(
        event.id, alert_type="sms", status="acknowledged",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
        user_id=user_a.id,
    )
    db.insert_alert_record(ack_record_a)

    # Now process: User A in cooldown, User B should still get alert
    state_machine.process_event(event)

    # User B got an SMS
    assert mock_twilio.send_sms.call_count == 1
    assert mock_twilio.send_sms.call_args[0][0] == "+48222222222"


# --------------------------------------------------------------------------
# 7. Confirmation code DB persistence
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_confirmation_code_db_persistence(_sleep, state_machine, db, mock_twilio, premium_user):
    """Confirmation code is stored in DB, not as instance variable."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    state_machine._send_confirmation_whatsapp(event, premium_user)

    # Code should be in DB
    code = db.get_active_confirmation_code(premium_user.id, event.id)
    assert code is not None
    assert len(code.code) == 6
    assert code.used_at is None

    # No instance variable _confirmation_code
    assert not hasattr(state_machine, "_confirmation_code")


# --------------------------------------------------------------------------
# 8. Cooldown prevents re-alerting
# --------------------------------------------------------------------------
def test_cooldown_prevents_recall(state_machine, db, mock_twilio, premium_user):
    """User with acknowledged alert within cooldown -> no alert."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Create acknowledged alert record
    ack_record = _make_alert_record(
        event.id, alert_type="phone_call", status="acknowledged",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
        user_id=premium_user.id,
    )
    db.insert_alert_record(ack_record)

    state_machine._process_event_for_user(event, premium_user)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
    mock_twilio.send_whatsapp.assert_not_called()


# --------------------------------------------------------------------------
# 9. Cooldown expired allows re-alerting (update SMS)
# --------------------------------------------------------------------------
def test_cooldown_expired_allows_update(state_machine, db, mock_twilio, config, premium_user):
    """User with acknowledged alert past cooldown, event updated -> gets update SMS.

    Once an event is acknowledged for a user, further updates go through the
    acknowledged path (update SMS), not a new phone call round.
    """
    cooldown_hours = config.alerts.acknowledgment.cooldown_hours
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Acknowledged record well past cooldown
    ack_record = _make_alert_record(
        event.id, alert_type="phone_call", status="acknowledged",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=cooldown_hours + 1),
        user_id=premium_user.id,
    )
    db.insert_alert_record(ack_record)

    # Event updated recently (after the old alert)
    event.last_updated_at = datetime.now(timezone.utc)

    state_machine._process_event_for_user(event, premium_user)

    # Cooldown expired + acknowledged + event updated -> update SMS
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 10. Acknowledged event gets SMS update (after cooldown expires)
# --------------------------------------------------------------------------
def test_acknowledged_event_gets_sms_update(
    state_machine, db, mock_twilio, config, premium_user
):
    """Event updated after acknowledgment and cooldown expired -> SMS update sent."""
    cooldown_hours = config.alerts.acknowledgment.cooldown_hours
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Create an acknowledged alert record past the cooldown window
    past_time = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours + 1)
    record = _make_alert_record(
        event.id, alert_type="phone_call", status="acknowledged",
        sent_at=past_time, user_id=premium_user.id,
    )
    db.insert_alert_record(record)

    # Event updated after the last alert (more recently)
    event.last_updated_at = datetime.now(timezone.utc)

    state_machine._process_event_for_user(event, premium_user)

    # Cooldown expired, event is acknowledged, event was updated -> update SMS
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 11. Retry interval enforced per-user
# --------------------------------------------------------------------------
def test_retry_interval_enforced(state_machine, db, mock_twilio, config, premium_user):
    """Retry is not attempted before the configured retry interval has elapsed."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Insert a recent call attempt for this user
    recent_call = _make_alert_record(
        event.id, alert_type="phone_call", status="no-answer",
        sent_at=datetime.now(timezone.utc),
        user_id=premium_user.id,
    )
    db.insert_alert_record(recent_call)

    state_machine._process_event_for_user(event, premium_user)
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 12. Retry interval elapsed allows call
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_retry_interval_elapsed_allows_call(
    _sleep, state_machine, db, mock_twilio, config, premium_user
):
    """Retry is allowed after the retry interval has elapsed."""
    retry_minutes = config.alerts.acknowledgment.retry_interval_minutes
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    old_call = _make_alert_record(
        event.id, alert_type="phone_call", status="no-answer",
        sent_at=datetime.now(timezone.utc) - timedelta(minutes=retry_minutes + 1),
        user_id=premium_user.id,
    )
    db.insert_alert_record(old_call)

    state_machine._process_event_for_user(event, premium_user)
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 13. Call complete sets retry_pending (WhatsApp confirmation needed)
# --------------------------------------------------------------------------
def test_call_completed_sets_retry_pending(state_machine, db, mock_twilio, premium_user):
    """Call completed -> retry_pending (confirmation is via WhatsApp)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(
        event.id, status="initiated", user_id=premium_user.id,
    )
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "completed",
        "duration": 30,
    }

    state_machine.check_pending_calls()

    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 14. No-answer sets retry_pending
# --------------------------------------------------------------------------
def test_no_answer_retry(state_machine, db, mock_twilio, premium_user):
    """Call no-answer -> retry pending."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(
        event.id, status="initiated", user_id=premium_user.id,
    )
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "no-answer",
        "duration": 0,
    }

    state_machine.check_pending_calls()

    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 15. Round exhausted sends retries
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_round_exhausted_retries(_sleep, state_machine, db, mock_twilio, premium_user):
    """5 failed calls in a round -> status retry_pending (will retry next cycle)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)

    # 5 call attempts made (from config max_call_retries=5)
    assert mock_twilio.make_alert_call.call_count == 5
    # 1 WhatsApp confirmation request
    assert mock_twilio.send_whatsapp.call_count == 1

    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 16. Duplicate alert prevented by retry interval
# --------------------------------------------------------------------------
@patch("sentinel.alerts.state_machine.time.sleep")
def test_duplicate_alert_prevented(_sleep, state_machine, db, mock_twilio, premium_user):
    """Same event processed twice -> second time respects retry interval."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)
    first_count = mock_twilio.make_alert_call.call_count
    assert first_count == 5

    # Second attempt — retry interval not elapsed
    state_machine._process_event_for_user(event, premium_user)
    assert mock_twilio.make_alert_call.call_count == first_count


# --------------------------------------------------------------------------
# 17. Low urgency -> log only
# --------------------------------------------------------------------------
def test_low_urgency_logs_only(state_machine, db, mock_twilio, standard_user):
    """Urgency 3 -> log_only from preset rules."""
    event = _make_event(urgency_score=3, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, standard_user)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
    mock_twilio.send_whatsapp.assert_not_called()


# --------------------------------------------------------------------------
# 18. No users for country -> no alerts
# --------------------------------------------------------------------------
def test_no_users_for_country(state_machine, db, mock_twilio):
    """Event affecting a country with no monitoring users -> no alerts."""
    event = _make_event(urgency_score=10, source_count=2, affected_countries=["XX"])
    db.insert_event(event)

    state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
    mock_twilio.send_whatsapp.assert_not_called()


# --------------------------------------------------------------------------
# 19. Multi-country event alerts users from different countries
# --------------------------------------------------------------------------
def test_multi_country_event(state_machine, db, mock_twilio):
    """Event affecting PL and LT alerts users monitoring either country."""
    tier = _create_premium_tier(db)
    user_pl = _create_user(db, tier, phone="+48111111111", name="PL User", countries=["PL"])
    user_lt = _create_user(db, tier, phone="+37011111111", name="LT User", countries=["LT"])

    for u in [user_pl, user_lt]:
        db.insert_user_alert_rule(UserAlertRule(
            user_id=u.id, min_urgency=7, max_urgency=10, channel="sms", priority=10,
        ))

    event = _make_event(
        urgency_score=8, source_count=2, affected_countries=["PL", "LT"]
    )
    db.insert_event(event)

    state_machine.process_event(event)

    assert mock_twilio.send_sms.call_count == 2


# --------------------------------------------------------------------------
# 20. User monitoring multiple countries not alerted twice
# --------------------------------------------------------------------------
def test_user_monitoring_multiple_countries_not_duplicated(
    state_machine, db, mock_twilio
):
    """User monitoring PL and LT only gets one alert for event affecting both."""
    tier = _create_premium_tier(db)
    user = _create_user(db, tier, phone="+48111111111", name="Multi-country User",
                        countries=["PL", "LT"])
    db.insert_user_alert_rule(UserAlertRule(
        user_id=user.id, min_urgency=7, max_urgency=10, channel="sms", priority=10,
    ))

    event = _make_event(
        urgency_score=8, source_count=2, affected_countries=["PL", "LT"]
    )
    db.insert_event(event)

    state_machine.process_event(event)

    # Only 1 SMS despite the user monitoring both countries
    assert mock_twilio.send_sms.call_count == 1


# --------------------------------------------------------------------------
# 21. AlertRecord user_id is set on all execution methods
# --------------------------------------------------------------------------
def test_alert_record_has_user_id(state_machine, db, mock_twilio, premium_user):
    """SMS alert record includes user_id."""
    # Add SMS rule
    db.delete_user_alert_rules(premium_user.id)
    db.insert_user_alert_rule(UserAlertRule(
        user_id=premium_user.id, min_urgency=7, max_urgency=10,
        channel="sms", priority=10,
    ))

    event = _make_event(urgency_score=8, source_count=1)
    db.insert_event(event)

    state_machine._process_event_for_user(event, premium_user)

    records = db.get_alert_records(event.id)
    assert len(records) >= 1
    for rec in records:
        assert rec.user_id == premium_user.id


# --------------------------------------------------------------------------
# 22. check_pending_calls resolves user for follow-up
# --------------------------------------------------------------------------
def test_check_pending_calls_resolves_user(state_machine, db, mock_twilio, premium_user):
    """check_pending_calls resolves user from alert_record.user_id."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(
        event.id, status="initiated", user_id=premium_user.id,
    )
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "no-answer",
        "duration": 0,
    }

    # Should not crash — resolves user from user_id
    state_machine.check_pending_calls()

    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 23. SMS format still includes source details
# --------------------------------------------------------------------------
def test_sms_format_includes_source_details(db, config):
    """SMS message includes per-source detail lines from the database."""
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

    assert "- PAP: Atak rakietowy na Polskę" in message
    assert "- TVN24: Rosja atakuje Polskę rakietami" in message
    assert "Źródła (2):" in message


# --------------------------------------------------------------------------
# 24. Update SMS includes source name
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


# --------------------------------------------------------------------------
# 25. Pending call for user prevents double dispatch
# --------------------------------------------------------------------------
def test_pending_call_prevents_double_dispatch(state_machine, db, mock_twilio, premium_user):
    """Pending call for a user prevents sending another alert for same event."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Insert a pending call for this user
    pending = _make_alert_record(
        event.id, alert_type="phone_call", status="initiated",
        user_id=premium_user.id,
    )
    db.insert_alert_record(pending)

    state_machine._process_event_for_user(event, premium_user)

    # Should skip because there's a pending call
    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()
