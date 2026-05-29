"""Tests for sentinel.alerts.state_machine.

The alert-execution path is async (SPEC_ASYNC_REFACTOR.md Phase 3): the
state-machine methods are coroutines, internal sleeps are ``await
asyncio.sleep`` (patched here so tests don't really sleep), and every Twilio
SDK call is offloaded via ``asyncio.to_thread``. Because ``asyncio.to_thread``
actually runs the wrapped callable in a worker thread, the synchronous
``mock_twilio`` MagicMock still records calls and returns its configured values
unchanged — so the Twilio wrapper mocks stay plain MagicMocks (NOT AsyncMocks).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.state_machine import (
    SMS_MAX_CHARS,
    AlertStateMachine,
    _format_sms_message,
    _format_update_sms,
)
from sentinel.database import Database
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
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
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
        sent_at=sent_at or datetime.now(UTC),
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

    twilio.make_alert_call.side_effect = _make_call_record
    twilio.send_sms.side_effect = _make_sms_record
    # Default: calls are not answered (no-answer on first poll)
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    # SMS confirmation check reads inbound messages — default to empty
    twilio.client.messages.list.return_value = []
    twilio.twilio_phone = "+15551234567"
    return twilio


@pytest.fixture
def state_machine(db, mock_twilio, config):
    """Create an AlertStateMachine with mocked dependencies."""
    return AlertStateMachine(db, mock_twilio, config)


# --------------------------------------------------------------------------
# 1. test_new_critical_event_triggers_call
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_new_critical_event_triggers_call(_sleep, state_machine, mock_twilio):
    """Urgency 10 + 2 sources -> phone call (retries, SMS confirmation)."""
    event = _make_event(urgency_score=10, source_count=2)
    await state_machine.process_event(event)

    # 5 call attempts (no SMS reply in mock)
    assert mock_twilio.make_alert_call.call_count == 5
    # 1 SMS confirmation code + 5 call attempts = at least 6 SMS-related calls
    # The confirmation SMS is sent via send_sms, so call_count >= 1
    assert mock_twilio.send_sms.call_count >= 1


# --------------------------------------------------------------------------
# 2. test_single_source_critical_triggers_sms
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_source_critical_triggers_sms(state_machine, mock_twilio):
    """Urgency 10 + 1 source -> SMS only (wait for corroboration)."""
    event = _make_event(urgency_score=10, source_count=1)
    await state_machine.process_event(event)

    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 3. test_high_urgency_triggers_sms
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_high_urgency_triggers_sms(state_machine, mock_twilio):
    """Urgency 8 -> SMS."""
    event = _make_event(urgency_score=8, source_count=1)
    await state_machine.process_event(event)

    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 4. test_medium_urgency_triggers_sms
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_medium_urgency_triggers_sms(state_machine, mock_twilio, config):
    """Urgency 6 -> SMS."""
    from sentinel.config import UrgencyLevel

    config.alerts.urgency_levels["medium"] = UrgencyLevel(min_score=5, action="sms", corroboration_required=1)

    event = _make_event(urgency_score=6, source_count=1)
    await state_machine.process_event(event)

    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 5. test_low_urgency_logs_only
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_low_urgency_logs_only(state_machine, mock_twilio, config):
    """Urgency 3 -> no alert sent (log only)."""
    from sentinel.config import UrgencyLevel

    config.alerts.urgency_levels["low"] = UrgencyLevel(min_score=1, action="log_only")

    event = _make_event(urgency_score=3, source_count=1)
    await state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()


# --------------------------------------------------------------------------
# 6. test_answered_call_acknowledged
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_call_completed_sets_retry_pending(state_machine, db, mock_twilio):
    """Call completed -> retry_pending (confirmation is via SMS reply, not call)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "completed",
        "duration": 30,
    }

    await state_machine.check_pending_calls()

    # Call completion alone doesn't acknowledge — SMS reply needed
    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 7. test_short_call_not_acknowledged
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_instant_rejection_not_acknowledged(state_machine, db, mock_twilio):
    """Call completed, duration 1s (instant rejection) -> not acknowledged."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "completed",
        "duration": 1,
    }

    await state_machine.check_pending_calls()

    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "retry_pending"
    assert updated.acknowledged_at is None


# --------------------------------------------------------------------------
# 8. test_no_answer_retry
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_answer_retry(state_machine, db, mock_twilio):
    """Call no-answer -> retry pending."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    record = _make_alert_record(event.id, status="initiated")
    db.insert_alert_record(record)

    mock_twilio.get_call_status.return_value = {
        "status": "no-answer",
        "duration": 0,
    }

    await state_machine.check_pending_calls()

    updated_events = db.get_active_events(within_hours=24)
    updated = next(e for e in updated_events if e.id == event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 9. test_max_retries_sms_fallback
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_round_exhausted_sends_sms_and_retries(_sleep, state_machine, db, mock_twilio):
    """5 failed calls in a round -> SMS sent, status retry_pending (will retry next cycle)."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Process the event — all 5 attempts fail (mock returns no-answer)
    await state_machine.process_event(event)

    # 5 call attempts made, no SMS reply
    assert mock_twilio.make_alert_call.call_count == 5
    # 1 SMS confirmation code sent at start
    assert mock_twilio.send_sms.call_count >= 1

    # Status should be retry_pending, not sms_fallback (will retry next cycle)
    updated = db.get_event_by_id(event.id)
    assert updated.alert_status == "retry_pending"


# --------------------------------------------------------------------------
# 10. test_cooldown_prevents_recall
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cooldown_prevents_recall(state_machine, mock_twilio):
    """Acknowledged event within cooldown -> no call."""
    event = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(UTC) - timedelta(hours=1),
    )

    await state_machine.process_event(event)

    mock_twilio.make_alert_call.assert_not_called()
    mock_twilio.send_sms.assert_not_called()


# --------------------------------------------------------------------------
# 11. test_cooldown_expired_allows_call
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_cooldown_expired_allows_call(_sleep, state_machine, mock_twilio, config):
    """Acknowledged event after cooldown -> can call again."""
    cooldown_hours = config.alerts.acknowledgment.cooldown_hours
    event = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(UTC) - timedelta(hours=cooldown_hours + 1),
    )

    await state_machine.process_event(event)

    # The cooldown has expired — calls are attempted
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 12. test_new_event_bypasses_cooldown
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_new_event_bypasses_cooldown(_sleep, state_machine, mock_twilio):
    """Different event during cooldown -> calls normally."""
    # Event 1: acknowledged, in cooldown
    event1 = _make_event(
        urgency_score=10,
        source_count=2,
        acknowledged_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await state_machine.process_event(event1)
    mock_twilio.make_alert_call.assert_not_called()

    # Event 2: completely new event, different ID
    event2 = _make_event(
        urgency_score=10,
        source_count=2,
        event_type="invasion",
    )
    await state_machine.process_event(event2)
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 13. test_acknowledged_event_gets_sms_update
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_acknowledged_event_gets_sms_update(state_machine, db, mock_twilio):
    """Event updated after acknowledgment -> SMS update sent."""
    event = _make_event(urgency_score=10, source_count=2)

    # Create an acknowledged alert record with a sent_at in the past
    past_time = datetime.now(UTC) - timedelta(hours=1)
    record = _make_alert_record(
        event.id,
        alert_type="phone_call",
        status="acknowledged",
        sent_at=past_time,
    )
    db.insert_alert_record(record)

    # The event was updated after the last alert
    event.last_updated_at = datetime.now(UTC)

    await state_machine.process_event(event)

    # Should have sent an update SMS
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 14. test_duplicate_alert_prevented
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_duplicate_alert_prevented(_sleep, state_machine, db, mock_twilio):
    """Same event processed twice in same cycle -> second call respects retry interval."""
    event = _make_event(urgency_score=10, source_count=2)

    # First call — triggers the full retry loop (5 attempts + SMS)
    await state_machine.process_event(event)
    first_call_count = mock_twilio.make_alert_call.call_count
    assert first_call_count == 5  # all retries exhausted

    # Second call — retry interval not elapsed, skips
    await state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count == first_call_count


# --------------------------------------------------------------------------
# 14a. test_sms_not_resent_when_new_article_added
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sms_not_resent_when_new_article_added(state_machine, db, mock_twilio):
    """Reproduces the 2026-05-23 Latvia drone-lake bug: a non-acknowledged
    SMS-status event was re-dispatched on every new article, firing one extra
    SMS per article. Cooldown only engaged on acknowledged_at, so SMS events
    spammed forever. Now the same-event re-dispatch must NOT re-fire SMS.
    """
    event = _make_event(urgency_score=7, source_count=1, event_type="airspace_violation")

    await state_machine.process_event(event)
    assert mock_twilio.send_sms.call_count == 1

    # Simulate corroborator adding a new article: same event id, source_count
    # may bump, last_updated_at advances. The pending status is what the
    # corroborator leaves on the row after each update.
    event.article_ids.append(str(uuid4()))
    event.last_updated_at = datetime.now(UTC) + timedelta(minutes=5)
    event.alert_status = "pending"

    await state_machine.process_event(event)
    assert mock_twilio.send_sms.call_count == 1, "SMS must not be re-sent for the same event when a new article arrives"

    # Third article — still no extra SMS.
    event.article_ids.append(str(uuid4()))
    event.last_updated_at = datetime.now(UTC) + timedelta(minutes=10)
    await state_machine.process_event(event)
    assert mock_twilio.send_sms.call_count == 1


# --------------------------------------------------------------------------
# 15. test_corroboration_upgrade_triggers_call
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_corroboration_upgrade_triggers_call(_sleep, state_machine, db, mock_twilio):
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
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=1,
        article_ids=[article_id_1],
        alert_status="pending",
    )
    await state_machine.process_event(event)
    mock_twilio.send_sms.assert_called_once()
    mock_twilio.make_alert_call.assert_not_called()

    # Step 2: event now has 2 sources (corroborated)
    # The sms_sent record is in the DB, but it's not a pending phone_call
    # so the state machine should re-evaluate and trigger a phone call
    article_id_2 = str(uuid4())
    event.source_count = 2
    event.article_ids = [article_id_1, article_id_2]
    event.alert_status = "pending"

    await state_machine.process_event(event)
    assert mock_twilio.make_alert_call.call_count >= 1


# --------------------------------------------------------------------------
# 16. test_retry_interval_enforced
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_interval_enforced(state_machine, db, mock_twilio, config):
    """Retry is not attempted before the configured retry interval has elapsed."""
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # Insert a recent failed call attempt (sent just now)
    recent_call = _make_alert_record(
        event.id,
        alert_type="phone_call",
        status="no-answer",
        attempt_number=1,
        sent_at=datetime.now(UTC),  # just now
    )
    db.insert_alert_record(recent_call)

    # Process the event — should NOT retry because the interval hasn't elapsed
    await state_machine.process_event(event)
    mock_twilio.make_alert_call.assert_not_called()


# --------------------------------------------------------------------------
# 17. test_retry_interval_elapsed_allows_call
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_interval_elapsed_allows_call(_sleep, state_machine, db, mock_twilio, config):
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
        sent_at=datetime.now(UTC) - timedelta(minutes=retry_minutes + 1),
    )
    db.insert_alert_record(old_call)

    # Process the event — should retry because interval has elapsed
    await state_machine.process_event(event)
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
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    article2 = Article(
        source_name="TVN24",
        source_url="https://tvn24.pl/art2",
        source_type="rss",
        title="Rosja atakuje Polskę rakietami",
        summary="Potwierdzony atak...",
        language="pl",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
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
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=2,
        article_ids=[article1.id, article2.id],
    )

    message = _format_sms_message(event, db, config)

    # Verify per-source lines are present
    assert "- PAP: Atak rakietowy na Polskę" in message
    assert "- TVN24: Rosja atakuje Polskę rakietami" in message
    assert "Źródła (2):" in message


def test_sms_body_capped_for_many_long_url_sources(db, config):
    """A heavily-corroborated event with many long (Google News-style) URLs must
    produce an SMS under Twilio's limit, trimming the source list with a
    "…i N innych źródeł" trailer rather than overflowing and failing to send.
    """
    article_ids = []
    for i in range(12):
        # Google News redirect URLs run hundreds of chars; emulate that bloat.
        article = Article(
            source_name=f"GoogleNews:Russia attack NATO {i}",
            source_url="https://news.google.com/rss/articles/" + ("A1b2C3d4" * 60) + f"?oc=5&i={i}",
            source_type="google_news",
            title=f"Rosyjski dron uderzył w blok mieszkalny w Rumunii — relacja numer {i}",
            summary="Szczegóły zdarzenia...",
            language="pl",
            published_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
        )
        db.insert_article(article)
        article_ids.append(article.id)

    event = Event(
        id=str(uuid4()),
        event_type="drone_attack",
        urgency_score=8,
        affected_countries=["RO"],
        aggressor="RU",
        summary_pl="Rosyjski dron uderzył w blok mieszkalny w Rumunii, dwoje rannych.",
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=6,
        article_ids=article_ids,
    )

    message = _format_sms_message(event, db, config)

    # Stays under Twilio's concatenated-message limit (the bug was HTTP 400 >1600).
    assert len(message) <= SMS_MAX_CHARS
    # Trims rather than dropping the alert: at least the first source survives...
    assert "GoogleNews:Russia attack NATO 0" in message
    # ...and the omitted ones are summarized.
    assert "więcej" in message


def test_sms_body_capped_when_summary_is_huge(db, config):
    """A pathologically long summary_pl (classifier output is unbounded) must not
    push the body past the limit. The summary is truncated rather than the
    rendered body, so trailing template fields (e.g. "Wykryto:") survive — a
    blind tail-clamp would have deleted them.
    """
    event = Event(
        id=str(uuid4()),
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="A" * 2000,
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=1,
        article_ids=[],
    )

    message = _format_sms_message(event, db, config)

    assert len(message) <= SMS_MAX_CHARS
    # The trailing detection-time field must NOT be truncated away.
    assert "Wykryto:" in message


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
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    db.insert_article(article)

    event = Event(
        id=str(uuid4()),
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Nowe informacje o ataku.",
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=3,
        article_ids=["old-id-1", "old-id-2", article.id],
    )

    message = _format_update_sms(event, db, config)

    assert "Defence24" in message
    assert "Nowe informacje (Defence24):" in message


# --------------------------------------------------------------------------
# 20. test_api_call_retry_pause_is_awaited  [3.1c]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_api_call_retry_pause_is_awaited(mock_sleep, state_machine, db, mock_twilio):
    """In a multi-retry round the inter-retry pause is `await asyncio.sleep`, not time.sleep.

    All 5 call attempts fail (mock returns no-answer), so the loop pauses
    between attempts. The patched asyncio.sleep must have been awaited.
    """
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    await state_machine.process_event(event)

    # 5 attempts -> 4 inter-retry pauses at minimum (poll waits also use sleep,
    # but the key assertion is that the async sleep was used at all).
    assert mock_sleep.await_count >= 1
    # The inter-retry pause uses the configured retry-pause value (default 10).
    retry_pause = state_machine.config.alerts.acknowledgment.call_retry_pause_seconds
    assert any(call.args == (retry_pause,) for call in mock_sleep.await_args_list)


# --------------------------------------------------------------------------
# 21. test_twilio_calls_routed_through_to_thread  [3.2a]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_twilio_calls_routed_through_to_thread(mock_sleep, state_machine, db, mock_twilio):
    """Every Twilio SDK call on the alert path goes through asyncio.to_thread.

    There are five Twilio touch points the state machine offloads:
      1. ``self.twilio.make_alert_call`` (bound wrapper)
      2. ``self.twilio.send_sms`` (bound wrapper)
      3. ``self.twilio.get_call_status`` (bound wrapper)
      4. a lambda wrapping ``self.twilio.client.messages.list(...)``
         (``_check_sms_confirmation``)
      5. a lambda wrapping ``self.twilio.client.messages(sid).fetch()``
         (``_check_confirmation_sms_delivered``)

    The three bound wrappers can be asserted by identity, but #4 and #5 are
    anonymous lambdas, so identity can't catch them. Instead we prove the
    *direct-SDK* calls are reached ONLY through ``to_thread`` by a count
    argument: re-running the recorded callables in isolation must reproduce
    EXACTLY the number of ``messages.list`` / ``messages(sid).fetch``
    invocations that the live run produced. If a regression un-offloaded
    either direct-SDK call (calling ``messages.list`` / ``.fetch`` directly
    instead of via ``to_thread``), that invocation would still happen during
    the live run but would NOT be among the recorded callables — so the
    reproduced count would fall short of the live count and this test fails.

    The no-answer phone-call path reaches all five touch points: each retry
    polls inbound SMS (#4) and call status (#3), the round opens with a
    confirmation SMS (#2) and the calls themselves (#1), and after the first
    attempt the confirmation-SMS delivery is checked (#5) because the
    confirmation SID was set.
    """
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    # The fetch mock for touch point #5: messages(sid).fetch() always returns
    # twilio.client.messages.return_value (regardless of sid), and .fetch is a
    # child mock on it. Capture it so we can count fetch() invocations.
    fetch_mock = mock_twilio.client.messages.return_value.fetch
    list_mock = mock_twilio.client.messages.list

    recorded = []

    # AsyncMock whose side effect both RECORDS func and CALLS THROUGH, so the
    # real lambdas execute their wrapped SDK calls against the MagicMock.
    async def fake_to_thread(func, *args, **kwargs):
        recorded.append(func)
        return func(*args, **kwargs)

    with patch(
        "sentinel.alerts.state_machine.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=fake_to_thread,
    ) as mock_tt:
        await state_machine.process_event(event)

    assert mock_tt.await_count >= 1

    # (a) The three bound wrappers used on the phone-call path were offloaded
    #     (assertable by identity).
    assert mock_twilio.make_alert_call in recorded
    assert mock_twilio.get_call_status in recorded
    assert mock_twilio.send_sms in recorded  # confirmation SMS

    # (b) The two direct-SDK lambdas were actually exercised during the live
    #     run — the path really did reach messages.list (#4) and the
    #     confirmation-SMS delivery fetch (#5).
    live_list_calls = list_mock.call_count
    live_fetch_calls = fetch_mock.call_count
    assert live_list_calls >= 1, "expected _check_sms_confirmation to call messages.list"
    assert live_fetch_calls >= 1, "expected _check_confirmation_sms_delivered to call messages(sid).fetch()"

    # (c) Linchpin: the direct-SDK calls were reached ONLY through to_thread.
    #     Reset the two SDK mocks, re-execute the recorded callables in
    #     isolation, and require the reproduced counts to equal the live
    #     counts exactly. A direct (un-offloaded) call would not be recorded,
    #     so its touch could not be reproduced -> counts diverge -> failure.
    bound_wrappers = {
        mock_twilio.make_alert_call,
        mock_twilio.send_sms,
        mock_twilio.get_call_status,
    }
    list_mock.reset_mock()
    fetch_mock.reset_mock()
    for func in recorded:
        if func in bound_wrappers:
            # Bound wrappers expect positional args (phone, message, event_id /
            # sid); skip executing them here — they're already proven by
            # identity in (a) and don't touch the direct-SDK mocks.
            continue
        func()  # a recorded lambda -> re-touches messages.list or fetch
    assert list_mock.call_count == live_list_calls, (
        "messages.list reached outside to_thread: "
        f"live={live_list_calls} but only {list_mock.call_count} reproduced from recorded offloads"
    )
    assert fetch_mock.call_count == live_fetch_calls, (
        "messages(sid).fetch reached outside to_thread: "
        f"live={live_fetch_calls} but only {fetch_mock.call_count} reproduced from recorded offloads"
    )


# --------------------------------------------------------------------------
# 22. test_db_calls_not_offloaded_to_thread  [3.2c]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_db_calls_not_offloaded_to_thread(mock_sleep, state_machine, db, mock_twilio):
    """No Database method is ever placed inside asyncio.to_thread.

    All SQLite access must stay on the event-loop thread (shared connection,
    no application-level lock).

    This is a POSITIVE allowlist rather than a single negative check, because a
    ``lambda: self.db.something()`` has ``__self__ is None`` and would silently
    slip past an ``isinstance(func.__self__, Database)`` test. Every offloaded
    callable must be either one of the known bound Twilio wrappers (by
    identity), OR a lambda that, when executed, touches ONLY
    ``self.twilio.client...`` and never ``self.db`` / ``Database``. A future
    ``to_thread(lambda: self.db.update_event(...))`` regression would therefore
    fail here: the lambda is not a known wrapper and, when re-executed against a
    tripwire DB, would raise.
    """
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)

    recorded = []

    async def fake_to_thread(func, *args, **kwargs):
        recorded.append(func)
        return func(*args, **kwargs)

    with patch("sentinel.alerts.state_machine.asyncio.to_thread", side_effect=fake_to_thread):
        await state_machine.process_event(event)
        # Also exercise the pending-call path, which polls Twilio per record.
        record = _make_alert_record(event.id, status="initiated")
        db.insert_alert_record(record)
        await state_machine.check_pending_calls()

    assert recorded, "expected at least one offloaded Twilio call"

    # Defense in depth: the original negative check. A bound Database method
    # would carry __self__ that is a Database instance.
    for func in recorded:
        owner = getattr(func, "__self__", None)
        assert not isinstance(owner, Database), f"Database call {func!r} must not be offloaded to a thread"

    # Positive allowlist. The three bound Twilio wrappers are accepted by
    # identity; everything else must be a lambda that touches only
    # self.twilio.client and never the DB. We prove the latter by re-executing
    # each non-wrapper callable with self.db swapped for a tripwire that raises
    # on ANY attribute access. The real lambdas close over `self`, so they see
    # the swapped db; a hypothetical `lambda: self.db.update_event(...)` would
    # trip it.
    bound_wrappers = {
        mock_twilio.make_alert_call,
        mock_twilio.send_sms,
        mock_twilio.get_call_status,
    }

    class _DBTripwire:
        """Stand-in for the Database that explodes if anything touches it."""

        def __getattribute__(self, name):  # noqa: D401 - tripwire
            raise AssertionError(
                f"offloaded callable touched the Database (attr {name!r}); DB access must not be offloaded to a thread"
            )

    saved_db = state_machine.db
    state_machine.db = _DBTripwire()
    try:
        for func in recorded:
            if func in bound_wrappers:
                continue  # known-good Twilio wrapper, asserted by identity
            # A non-wrapper offload must be a Twilio-client lambda. Re-running
            # it must not touch the DB tripwire. (It re-touches messages.list /
            # messages(sid).fetch, which is fine — those are Twilio, not DB.)
            func()
    finally:
        state_machine.db = saved_db


# --------------------------------------------------------------------------
# 23. test_poll_durations_from_config  [3.6a]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_poll_durations_from_config(mock_sleep, state_machine, db, mock_twilio, config):
    """_wait_for_call_and_check_sms reads poll timeout/interval from config (defaults 90/5)."""
    # Defaults preserve the original hardcoded behavior.
    assert config.alerts.acknowledgment.call_poll_timeout_seconds == 90
    assert config.alerts.acknowledgment.call_poll_interval_seconds == 5

    # Drive the wait loop directly with a tiny custom config so it polls a few
    # times and then the call "finishes". With timeout=20, interval=5 and the
    # call finishing after the first poll, exactly one sleep(5) is awaited.
    config.alerts.acknowledgment.call_poll_timeout_seconds = 20
    config.alerts.acknowledgment.call_poll_interval_seconds = 5
    mock_twilio.get_call_status.return_value = {"status": "completed", "duration": 30}

    record = _make_alert_record(str(uuid4()), status="initiated")
    sms_since = datetime.now(UTC)

    await state_machine._wait_for_call_and_check_sms(record, sms_since)

    # First poll: sleep(5) awaited once, then the call is "completed" so we return.
    mock_sleep.assert_awaited_once_with(5)


# --------------------------------------------------------------------------
# Push notification wiring (additive channel)
# --------------------------------------------------------------------------
def _make_push_client():
    """Mock ExpoPushClient that returns a push AlertRecord on send."""
    push = MagicMock()

    def _send(title, body, event_id, data=None):
        return _make_alert_record(event_id, alert_type="push", status="sent")

    push.send_push.side_effect = _send
    return push


def _enable_push(config):
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[x]"]


@pytest.mark.asyncio
async def test_push_disabled_sends_no_push(db, mock_twilio, config):
    """With push disabled (default), no push is sent even when an SMS fires."""
    push = _make_push_client()
    sm = AlertStateMachine(db, mock_twilio, config, push_client=push)
    event = _make_event(urgency_score=8, source_count=1)
    db.insert_event(event)

    await sm.process_event(event)

    push.send_push.assert_not_called()
    assert not [a for a in db.get_alert_records(event.id) if a.alert_type == "push"]


@pytest.mark.asyncio
async def test_push_enabled_sends_once_per_event(db, mock_twilio, config):
    """An alertable event pushes once; a second cycle does not re-push."""
    _enable_push(config)
    push = _make_push_client()
    sm = AlertStateMachine(db, mock_twilio, config, push_client=push)
    event = _make_event(urgency_score=8, source_count=1)
    db.insert_event(event)

    await sm.process_event(event)
    await sm.process_event(event)  # SMS tier suppressed on re-alert -> no second push

    assert push.send_push.call_count == 1
    push_records = [a for a in db.get_alert_records(event.id) if a.alert_type == "push"]
    assert len(push_records) == 1


@pytest.mark.asyncio
async def test_push_dedup_on_existing_push_record(db, mock_twilio, config):
    """A prior push record suppresses re-pushing the same event's initial alert."""
    _enable_push(config)
    push = _make_push_client()
    sm = AlertStateMachine(db, mock_twilio, config, push_client=push)
    event = _make_event(urgency_score=10, source_count=2)
    existing = [_make_alert_record(event.id, alert_type="push", status="sent")]

    await sm._maybe_send_push(event, existing)

    push.send_push.assert_not_called()


@pytest.mark.asyncio
async def test_push_update_bypasses_dedup(db, mock_twilio, config):
    """An update push fires despite an existing push record (caller-gated)."""
    _enable_push(config)
    push = _make_push_client()
    sm = AlertStateMachine(db, mock_twilio, config, push_client=push)
    event = _make_event(urgency_score=10, source_count=2)
    db.insert_event(event)
    existing = [_make_alert_record(event.id, alert_type="push", status="sent")]

    await sm._maybe_send_push(event, existing, is_update=True)

    push.send_push.assert_called_once()
    assert [a for a in db.get_alert_records(event.id) if a.alert_type == "push"]


@pytest.mark.asyncio
async def test_low_urgency_sends_no_push(db, mock_twilio, config):
    """log_only events never push."""
    from sentinel.config import UrgencyLevel

    _enable_push(config)
    config.alerts.urgency_levels["low"] = UrgencyLevel(min_score=1, action="log_only")
    push = _make_push_client()
    sm = AlertStateMachine(db, mock_twilio, config, push_client=push)
    event = _make_event(urgency_score=3, source_count=1)
    db.insert_event(event)

    await sm.process_event(event)

    push.send_push.assert_not_called()
