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
from types import SimpleNamespace

import pytest
from twilio.base.exceptions import TwilioRestException

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
