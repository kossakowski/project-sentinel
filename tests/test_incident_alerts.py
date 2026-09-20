"""Revision-aware alert delivery regressions for incident memory."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.config import UrgencyLevel
from sentinel.models import AlertRecord, Event


def _event(*, urgency: int = 7, sources: int = 1, revision: int = 1) -> Event:
    return Event(
        id=str(uuid4()),
        event_type="airspace_violation",
        urgency_score=urgency,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Potwierdzony incydent.",
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=sources,
        article_ids=[str(uuid4())],
        notification_revision=revision,
    )


def _record(event_id: str, alert_type: str, status: str = "sent", revision: int = 1) -> AlertRecord:
    return AlertRecord(
        event_id=event_id,
        alert_type=alert_type,
        twilio_sid=str(uuid4()),
        status=status,
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="test",
        event_revision=revision,
    )


def _twilio() -> MagicMock:
    client = MagicMock()
    client.send_sms.side_effect = lambda _phone, _body, event_id: _record(event_id, "sms")
    client.make_alert_call.side_effect = lambda _phone, _body, event_id: _record(event_id, "phone_call", "initiated")
    client.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    client.client.messages.list.return_value = []
    client.twilio_phone = "+15550000000"
    return client


def _push(statuses: list[str]) -> MagicMock:
    client = MagicMock()

    def send(_title, _body, event_id, _data):
        return _record(event_id, "push", statuses.pop(0))

    client.send_push.side_effect = send
    return client


def _enable_push(config) -> None:
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[test]"]


@pytest.mark.asyncio
async def test_dispatcher_deduplicates_batch_ids_and_refreshes_persisted_event(db, config):
    """One incident is dispatched once using its latest persisted revision."""
    stale = _event(urgency=5, revision=1)
    db.insert_event(stale)
    db.update_event(stale.id, urgency_score=9, notification_revision=2, summary_pl="Eskalacja.")
    state_machine = MagicMock()
    state_machine.db = db
    state_machine.process_event = AsyncMock()

    await AlertDispatcher(state_machine, config).dispatch([stale, stale])

    state_machine.process_event.assert_awaited_once()
    dispatched = state_machine.process_event.await_args.args[0]
    assert (dispatched.urgency_score, dispatched.notification_revision, dispatched.summary_pl) == (9, 2, "Eskalacja.")


@pytest.mark.asyncio
async def test_successful_initial_revision_is_not_replayed_after_restart(db, config):
    """Persisted revision-one deliveries suppress both channels after restart."""
    _enable_push(config)
    event = _event()
    db.insert_event(event)
    twilio = _twilio()
    push = _push(["sent"])

    await AlertStateMachine(db, twilio, config, push_client=push).process_event(event)
    await AlertStateMachine(db, twilio, config, push_client=push).process_event(event)

    assert twilio.send_sms.call_count == 1
    assert push.send_push.call_count == 1
    assert {record.event_revision for record in db.get_alert_records(event.id)} == {1}


@pytest.mark.asyncio
async def test_acknowledged_escalation_ignores_cooldown_once_per_channel(db, config):
    """A revision increment sends one update, without another call or replay."""
    _enable_push(config)
    event = _event(revision=1)
    event.acknowledged_at = datetime.now(UTC) - timedelta(minutes=1)
    db.insert_event(event)
    db.insert_alert_record(_record(event.id, "phone_call", "acknowledged", revision=1))
    twilio = _twilio()
    push = _push(["sent"])
    machine = AlertStateMachine(db, twilio, config, push_client=push)

    # The lead-owned grouping decision is the sole source of this increment.
    db.update_event(event.id, notification_revision=2)
    await machine.process_event(event)  # deliberately stale snapshot
    await machine.process_event(event)
    db.update_event(event.id, source_count=3)  # timestamp/source changes alone are not updates
    await machine.process_event(event)

    twilio.make_alert_call.assert_not_called()
    assert twilio.send_sms.call_count == 1
    assert push.send_push.call_count == 1
    records = db.get_alert_records(event.id)
    assert {record.event_revision for record in records if record.alert_type in ("sms", "push")} == {2}


@pytest.mark.asyncio
async def test_partial_push_failure_retries_only_that_channel(db, config):
    """A failed push record does not suppress it, while successful SMS does."""
    _enable_push(config)
    event = _event()
    db.insert_event(event)
    twilio = _twilio()
    push = _push(["failed", "sent"])
    machine = AlertStateMachine(db, twilio, config, push_client=push)

    await machine.process_event(event)
    await machine.process_event(event)

    assert twilio.send_sms.call_count == 1
    assert push.send_push.call_count == 2
    pushes = [record for record in db.get_alert_records(event.id) if record.alert_type == "push"]
    assert [record.status for record in pushes] == ["failed", "sent"]
    assert [record.event_revision for record in pushes] == [1, 1]


@pytest.mark.asyncio
@patch("sentinel.alerts.state_machine.asyncio.sleep", new_callable=AsyncMock)
async def test_first_critical_escalation_calls_once_and_revisions_push(_sleep, db, config):
    """A noncritical incident can receive its first corroborated critical call."""
    _enable_push(config)
    config.alerts.urgency_levels["medium"] = UrgencyLevel(min_score=5, action="sms", channel="sms")
    event = _event(urgency=5, sources=1)
    db.insert_event(event)
    twilio = _twilio()
    push = _push(["sent"])
    machine = AlertStateMachine(db, twilio, config, push_client=push)

    await machine.process_event(event)
    db.update_event(event.id, urgency_score=9, source_count=2, notification_revision=2)
    await machine.process_event(event)
    calls_after_escalation = twilio.make_alert_call.call_count
    await machine.process_event(event)

    assert calls_after_escalation > 0
    assert twilio.make_alert_call.call_count == calls_after_escalation
    assert push.send_push.call_count == 1


@pytest.mark.asyncio
async def test_legacy_successful_revision_one_records_prevent_replay(db, config):
    """Migration-default revision-one records retain their historical dedup value."""
    _enable_push(config)
    event = _event(revision=1)
    db.insert_event(event)
    db.insert_alert_record(_record(event.id, "sms"))
    db.insert_alert_record(_record(event.id, "push"))
    twilio = _twilio()
    push = _push([])

    await AlertStateMachine(db, twilio, config, push_client=push).process_event(event)

    twilio.send_sms.assert_not_called()
    push.send_push.assert_not_called()
