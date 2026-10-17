"""The SMS-code acknowledgement path and the failed-call path of a 9-10 alert.

The real ``AlertStateMachine`` runs on the live config with a real database
and the real ``TwilioClient``; only the Twilio SDK ``Client`` and
``ExpoPushClient.send_push`` are autospecced. The confirmation code is fixed
through ``code_factory``. Inbound replies are what the SDK's
``messages.list`` returns.
"""

import logging
import os
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest
from twilio.base.exceptions import TwilioRestException

from sentinel.alerts.call_round import CallRound
from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.state_machine import AlertStateMachine, generate_confirmation_code
from sentinel.alerts.twilio_client import TwilioClient

CODE = "424242"


def _state_machine(config, db) -> AlertStateMachine:
    return AlertStateMachine(
        db,
        TwilioClient(config),
        config,
        push_client=ExpoPushClient(config),
        code_factory=lambda: CODE,
    )


def _sms_bodies(twilio_sdk) -> list[str]:
    return [call.kwargs["body"] for call in twilio_sdk.messages.create.call_args_list]


def _record_types(db, event_id) -> list[str]:
    return sorted(record.alert_type for record in db.get_alert_records(event_id))


@pytest.mark.asyncio
async def test_correct_code_reply_acknowledges(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()

    # The owner replies with the code once the first call has been placed.
    def inbound_replies(**kwargs):
        if twilio_sdk.calls.create.call_count == 0:
            return []
        return [SimpleNamespace(body=f" Potwierdzam {CODE} ")]

    twilio_sdk.messages.list.side_effect = inbound_replies

    await _state_machine(prod_config, prod_db).process_event(event)

    stored = prod_db.get_event_by_id(event.id)
    assert stored.alert_status == "acknowledged"
    assert stored.acknowledged_at is not None
    # The reply stops the round after the first call.
    assert twilio_sdk.calls.create.call_count == 1
    # Replies are read from the owner's number to the Twilio number.
    inbound_query = twilio_sdk.messages.list.call_args.kwargs
    assert inbound_query["from_"] == prod_config.alerts.phone_number
    assert inbound_query["to"] == os.environ["TWILIO_PHONE_NUMBER"]

    confirmation, followup = _sms_bodies(twilio_sdk)
    assert CODE in confirmation
    # The follow-up is the full alert SMS.
    assert followup.startswith("\U0001f6a8 PROJECT SENTINEL: Inwazja")
    assert stored.summary_pl in followup
    assert CODE not in followup
    assert expo_send_push.call_count == 1
    assert _record_types(prod_db, event.id) == ["phone_call", "push", "sms", "sms"]


@pytest.mark.asyncio
async def test_wrong_code_reply_does_not_acknowledge(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()
    twilio_sdk.messages.list.return_value = [SimpleNamespace(body="135799")]

    await _state_machine(prod_config, prod_db).process_event(event)

    stored = prod_db.get_event_by_id(event.id)
    assert twilio_sdk.messages.list.call_count >= 1
    assert stored.alert_status == "retry_pending"
    assert stored.acknowledged_at is None
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    # Only the confirmation SMS went out; no follow-up.
    assert len(_sms_bodies(twilio_sdk)) == 1
    assert CODE in _sms_bodies(twilio_sdk)[0]


@pytest.mark.asyncio
async def test_call_failed_to_initiate_is_recorded(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, caplog
):
    """Today's production state: the suspended Twilio account answers every call and SMS with HTTP 401."""
    event = store_critical_event()
    account_suspended = TwilioRestException(
        status=401,
        uri="/2010-04-01/Accounts/AC00000000000000000000000000000000/Calls.json",
        msg="Unable to create record: Account not active",
        code=20003,
    )
    twilio_sdk.calls.create.side_effect = account_suspended
    twilio_sdk.messages.create.side_effect = account_suspended

    with caplog.at_level(logging.ERROR, logger="sentinel.alerts.state_machine"):
        await _state_machine(prod_config, prod_db).process_event(event)

    stored = prod_db.get_event_by_id(event.id)
    # Every attempt of the round was tried, none started, and the event stays retryable.
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert stored.alert_status == "retry_pending"
    assert stored.acknowledged_at is None
    assert "Twilio call failed to initiate" in caplog.text
    # The additive push is independent of Twilio and still reaches the phone.
    assert expo_send_push.call_count == 1
    assert _record_types(prod_db, event.id) == ["push"]


def test_default_confirmation_code_is_six_secret_digits(prod_config, prod_db, monkeypatch):
    state_machine = AlertStateMachine(prod_db, TwilioClient(prod_config), prod_config)
    assert state_machine._code_factory is generate_confirmation_code

    monkeypatch.setattr(secrets, "randbelow", lambda bound: 0)
    assert generate_confirmation_code() == "100000"
    monkeypatch.setattr(secrets, "randbelow", lambda bound: bound - 1)
    assert generate_confirmation_code() == "999999"


@pytest.mark.asyncio
async def test_confirmation_code_not_logged(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, caplog
):
    """A full call round, with a resent confirmation SMS and the owner's reply, never logs the code."""
    event = store_critical_event()
    # The first confirmation SMS is reported undelivered, so the round resends it;
    # the owner replies with the code once the resent SMS is out.
    twilio_sdk.messages.return_value.fetch.return_value = SimpleNamespace(status="undelivered", error_code=30003)

    def inbound_replies(**kwargs):
        if twilio_sdk.messages.create.call_count < 2:
            return []
        return [SimpleNamespace(body=CODE)]

    twilio_sdk.messages.list.side_effect = inbound_replies

    with caplog.at_level(logging.DEBUG):
        await _state_machine(prod_config, prod_db).process_event(event)

    assert prod_db.get_event_by_id(event.id).alert_status == "acknowledged"
    confirmation, resent, followup = _sms_bodies(twilio_sdk)
    assert CODE in confirmation and CODE in resent and CODE not in followup
    messages = [record.getMessage() for record in caplog.records]
    assert any("SMS confirmation request sent" in message for message in messages)
    assert any("confirmation SMS failed to deliver, resending" in message for message in messages)
    assert any("SMS confirmation received" in message for message in messages)
    assert [message for message in messages if CODE in message] == []
    # The formatted log, tracebacks included, does not carry it either.
    assert CODE not in caplog.text


@pytest.mark.asyncio
async def test_confirmation_code_not_logged_when_the_sms_send_raises(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, caplog
):
    """A confirmation SMS whose send raises is logged with its traceback, but not with the code."""
    event = store_critical_event()
    accept_sms = twilio_sdk.messages.create.side_effect

    def first_send_raises(**kwargs):
        if twilio_sdk.messages.create.call_count == 1:
            raise RuntimeError("SMS gateway error")
        return accept_sms(**kwargs)

    twilio_sdk.messages.create.side_effect = first_send_raises

    def inbound_replies(**kwargs):
        if twilio_sdk.messages.create.call_count < 2:
            return []
        return [SimpleNamespace(body=CODE)]

    twilio_sdk.messages.list.side_effect = inbound_replies

    with caplog.at_level(logging.DEBUG):
        await _state_machine(prod_config, prod_db).process_event(event)

    assert prod_db.get_event_by_id(event.id).alert_status == "acknowledged"
    failed, resent = _sms_bodies(twilio_sdk)[:2]
    assert CODE in failed and CODE in resent
    assert any(record.exc_info and "Twilio SMS failed" in record.getMessage() for record in caplog.records)
    assert "SMS gateway error" in caplog.text
    assert CODE not in caplog.text


@pytest.mark.asyncio
async def test_each_round_checks_only_its_own_code(prod_config, prod_db, store_critical_event, twilio_sdk):
    """Two rounds on one state machine keep their own codes; a reply with one code acknowledges only its round."""
    codes = iter(["111111", "222222"])
    state_machine = AlertStateMachine(
        prod_db,
        TwilioClient(prod_config),
        prod_config,
        push_client=ExpoPushClient(prod_config),
        code_factory=lambda: next(codes),
    )
    first = CallRound(state_machine, store_critical_event())
    second = CallRound(state_machine, store_critical_event(title="Uderzenie rakietowe na Rzeszów"))
    since = datetime.now(UTC)

    await first.send_confirmation_sms()
    await second.send_confirmation_sms()
    twilio_sdk.messages.list.return_value = [SimpleNamespace(body="111111")]

    assert (first.code, second.code) == ("111111", "222222")
    assert first.sms_sid != second.sms_sid
    assert await first.reply_received(since) is True
    assert await second.reply_received(since) is False


@pytest.mark.asyncio
async def test_call_round_reads_that_raise_do_not_stop_the_round(prod_config, prod_db, store_critical_event, caplog):
    """A Twilio read that raises counts as no reply and an unknown delivery status, as one that returns None does."""
    twilio = create_autospec(TwilioClient, instance=True)
    twilio.list_inbound_sms.side_effect = RuntimeError("inbound read error")
    twilio.get_sms_status.side_effect = RuntimeError("status read error")
    state_machine = AlertStateMachine(
        prod_db, twilio, prod_config, push_client=ExpoPushClient(prod_config), code_factory=lambda: CODE
    )
    call_round = CallRound(state_machine, store_critical_event())
    call_round.code, call_round.sms_sid = CODE, "SM00000000000000000000000000000001"

    with caplog.at_level(logging.WARNING, logger="sentinel.alerts.state_machine"):
        assert await call_round.reply_received(datetime.now(UTC)) is False
        assert await call_round.confirmation_sms_delivered() is None

    assert "Failed to check SMS confirmations: inbound read error" in caplog.text
    assert "Failed to check SMS delivery status: status read error" in caplog.text
