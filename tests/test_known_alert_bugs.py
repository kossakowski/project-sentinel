"""Known ways a 9-10 phone call is lost on master (audit 01: A1, A2, A3).

Each test asserts the behaviour the alert path must have, and is marked
``xfail(strict=True)`` with the exception that breaks it today. If a bug is
fixed, its test passes, strict xfail turns that into a failure, and the mark
must be removed; a failure with any other exception is reported as a real
failure. The real ``AlertStateMachine`` and ``TwilioClient`` run on the live
config; only the Twilio SDK and the Expo HTTP edge are faked.
"""

import sqlite3

import httpx
import pytest
import requests

from sentinel.alerts import push_client as push_client_module
from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.alerts.twilio_client import TwilioClient


def _state_machine(config, db) -> AlertStateMachine:
    return AlertStateMachine(
        db,
        TwilioClient(config),
        config,
        push_client=ExpoPushClient(config),
        code_factory=lambda: "777777",
    )


@pytest.mark.xfail(
    strict=True,
    raises=AttributeError,
    reason="[01:A1] the additive push runs before the call without a guard; a non-dict Expo body "
    "raises AttributeError in push_client and the call is never placed",
)
@pytest.mark.asyncio
async def test_push_error_does_not_block_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, instant_alert_sleep, monkeypatch
):
    event = store_critical_event()
    posted: list[dict] = []

    def expo_answers_with_a_list(url, **kwargs):
        posted.append(kwargs["json"])
        return httpx.Response(200, json=[{"status": "ok", "id": "ticket-1"}], request=httpx.Request("POST", url))

    monkeypatch.setattr(push_client_module.httpx, "post", expo_answers_with_a_list)

    await _state_machine(prod_config, prod_db).process_event(event)

    assert len(posted) == 1
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries


@pytest.mark.xfail(
    strict=True,
    raises=requests.exceptions.ConnectionError,
    reason="[01:A2] TwilioClient.send_sms catches only TwilioRestException; a network error on the "
    "confirmation SMS escapes before the first call",
)
@pytest.mark.asyncio
async def test_sms_network_error_does_not_block_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()
    twilio_sdk.messages.create.side_effect = requests.ConnectionError("Connection reset by peer")

    await _state_machine(prod_config, prod_db).process_event(event)

    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries


@pytest.mark.xfail(
    strict=True,
    raises=sqlite3.OperationalError,
    reason="[01:A3] AlertDispatcher.dispatch has no per-event isolation; one failing event aborts "
    "every later event of the batch",
)
@pytest.mark.asyncio
async def test_one_failing_event_does_not_skip_rest(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, monkeypatch
):
    failing = store_critical_event(urgency=10, title="Atak zbrojny na Polskę pod Białymstokiem")
    second = store_critical_event(urgency=9, title="Uderzenie rakietowe na Rzeszów")
    state_machine = _state_machine(prod_config, prod_db)
    real_process_event = state_machine.process_event

    async def database_locked_for_first_event(event):
        if event.id == failing.id:
            raise sqlite3.OperationalError("database is locked")
        await real_process_event(event)

    monkeypatch.setattr(state_machine, "process_event", database_locked_for_first_event)

    # Highest urgency first: the failing event is dispatched before the second one.
    await AlertDispatcher(state_machine, prod_config).dispatch([failing, second])

    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert prod_db.get_event_by_id(second.id).alert_status == "retry_pending"
