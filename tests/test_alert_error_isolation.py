"""Error isolation on the 9-10 alert path (refactor Phase 2: 2.1, 2.2, 2.3, 2.7, 2.8).

A failure in one channel or one event must never cost a 9-10 event its call.
The state-machine tests run the real ``AlertStateMachine`` and ``TwilioClient``
on the live config; only the Twilio SDK ``Client`` and the Expo push are faked
at the edges, as in ``test_known_alert_bugs.py``.
"""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

import httpx
import pytest
import requests
from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.http.http_client import TwilioHttpClient

import sentinel.alerts.twilio_client as twilio_client_module
from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.state_machine import (
    SMS_SUMMARY_MAX_CHARS,
    AlertStateMachine,
    _format_update_sms,
)
from sentinel.alerts.twilio_client import TWIML_MAX_CHARS, TwilioClient
from sentinel.models import AlertRecord, Event
from sentinel.scheduler import CycleResult, PipelineStats, SentinelPipeline, SentinelScheduler

CODE = "135246"


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


# ---------------------------------------------------------------------------
# 2.1: the additive push never blocks the call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_goes_before_confirmation_sms_and_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    order: list[str] = []
    expo_send_push.side_effect = lambda *args, **kwargs: order.append("push")
    twilio_sdk.messages.create.side_effect = lambda **kwargs: order.append("sms") or SimpleNamespace(sid="SM1")
    twilio_sdk.calls.create.side_effect = lambda **kwargs: order.append("call") or SimpleNamespace(sid="CA1")

    await _state_machine(prod_config, prod_db).process_event(store_critical_event())

    assert order == ["push", "sms"] + ["call"] * prod_config.alerts.acknowledgment.max_call_retries


@pytest.mark.asyncio
async def test_push_build_error_is_logged_and_call_still_placed(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, monkeypatch, caplog
):
    """An error while the push data is built (before send_push) is logged with its traceback."""
    event = store_critical_event()

    def broken_builder(*args, **kwargs):
        raise KeyError("typo_field")

    monkeypatch.setattr("sentinel.alerts.state_machine._build_push_data", broken_builder)

    with caplog.at_level(logging.ERROR, logger="sentinel.alerts.state_machine"):
        await _state_machine(prod_config, prod_db).process_event(event)

    assert expo_send_push.call_count == 0
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    push_errors = [record for record in caplog.records if "push failed" in record.getMessage()]
    assert len(push_errors) == 1
    assert push_errors[0].exc_info is not None
    assert isinstance(push_errors[0].exc_info[1], KeyError)


@pytest.fixture
def push_config(config):
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[aaa]"]
    return config


def _expo_reply(body) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = body
    return response


@pytest.mark.parametrize(
    "body",
    [
        [{"status": "ok", "id": "ticket-1"}],
        "ok",
        None,
        {"data": "ok"},
        {"data": ["ok", 7]},
    ],
    ids=["list-body", "string-body", "null-body", "string-data", "non-dict-tickets"],
)
def test_push_client_tolerates_unexpected_response_body(push_config, body):
    with patch("sentinel.alerts.push_client.httpx.post", return_value=_expo_reply(body)):
        record = ExpoPushClient(push_config).send_push("Tytuł", "Treść", "evt-1", data={})

    assert record is None


def test_push_client_keeps_ok_ticket_next_to_malformed_one(push_config):
    reply = _expo_reply({"data": ["garbage", {"status": "ok", "id": "ticket-2"}]})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=reply):
        record = ExpoPushClient(push_config).send_push("Tytuł", "Treść", "evt-1", data={})

    assert record is not None
    assert record.twilio_sid == "ticket-2"


def test_push_client_http_error_still_returns_none(push_config):
    with patch("sentinel.alerts.push_client.httpx.post", side_effect=httpx.ReadTimeout("slow")):
        assert ExpoPushClient(push_config).send_push("Tytuł", "Treść", "evt-1") is None


# ---------------------------------------------------------------------------
# 2.2: Twilio HTTP timeout and errors reported as failures
# ---------------------------------------------------------------------------


def test_twilio_client_has_http_timeout(prod_config, twilio_sdk):
    assert prod_config.alerts.twilio.http_timeout_seconds == 30

    TwilioClient(prod_config)

    sdk_class = twilio_client_module.Client
    http_client = sdk_class.call_args.kwargs["http_client"]
    assert isinstance(http_client, TwilioHttpClient)
    assert http_client.timeout == 30


def test_twilio_client_timeout_follows_config(prod_config):
    """The real SDK client (no mock) carries the configured timeout on every request."""
    prod_config.alerts.twilio.http_timeout_seconds = 7.5

    client = TwilioClient(prod_config)

    assert client.client.http_client.timeout == 7.5


_TWILIO_FAILURES = [
    requests.ConnectionError("Connection reset by peer"),
    requests.Timeout("Read timed out"),
    TwilioException("Unable to reach Twilio"),
    TwilioRestException(status=401, uri="/Calls.json", msg="Account not active", code=20003),
    RuntimeError("unexpected SDK failure"),
]
_FAILURE_IDS = ["connection-error", "timeout", "twilio-exception", "rest-401", "unexpected"]


@pytest.mark.parametrize("error", _TWILIO_FAILURES, ids=_FAILURE_IDS)
def test_twilio_call_error_returns_none(prod_config, twilio_sdk, error):
    twilio_sdk.calls.create.side_effect = error

    assert TwilioClient(prod_config).make_alert_call("+48500100200", "Alarm", "evt-1") is None


@pytest.mark.parametrize("error", _TWILIO_FAILURES, ids=_FAILURE_IDS)
def test_twilio_sms_error_returns_none(prod_config, twilio_sdk, error):
    twilio_sdk.messages.create.side_effect = error

    assert TwilioClient(prod_config).send_sms("+48500100200", "Alarm", "evt-1") is None


@pytest.mark.parametrize("error", _TWILIO_FAILURES, ids=_FAILURE_IDS)
def test_twilio_call_status_error_returns_none(prod_config, twilio_sdk, error):
    twilio_sdk.calls.return_value.fetch.side_effect = error

    assert TwilioClient(prod_config).get_call_status("CA00000000000000000000000000000001") is None


@pytest.mark.asyncio
async def test_sms_timeout_does_not_block_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()
    twilio_sdk.messages.create.side_effect = requests.Timeout("Read timed out")

    await _state_machine(prod_config, prod_db).process_event(event)

    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert prod_db.get_event_by_id(event.id).alert_status == "retry_pending"


@pytest.mark.asyncio
async def test_confirmation_sms_error_inside_state_machine_does_not_block_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, monkeypatch, caplog
):
    """Even an error outside the Twilio client (here: recording the SMS) cannot stop the call."""
    event = store_critical_event()
    real_record_alert = AlertStateMachine._record_alert

    def failing_sms_record(self, record, recorded_event):
        if record.alert_type == "sms":
            raise RuntimeError("disk I/O error")
        real_record_alert(self, record, recorded_event)

    monkeypatch.setattr(AlertStateMachine, "_record_alert", failing_sms_record)

    with caplog.at_level(logging.ERROR, logger="sentinel.alerts.state_machine"):
        await _state_machine(prod_config, prod_db).process_event(event)

    assert twilio_sdk.messages.create.call_count == 1
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert "confirmation SMS failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("earlier_event", [False, True], ids=["first-event", "after-delivered-sms"])
async def test_unsent_confirmation_sms_is_resent_after_first_call(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, earlier_event
):
    """A confirmation SMS Twilio did not accept is resent, even after an earlier event's SMS was delivered."""
    state_machine = _state_machine(prod_config, prod_db)
    if earlier_event:
        await state_machine.process_event(store_critical_event(title="Atak zbrojny na Polskę pod Białymstokiem"))
    sms_before = twilio_sdk.messages.create.call_count
    event = store_critical_event(title="Uderzenie rakietowe na Rzeszów")
    twilio_sdk.messages.create.side_effect = [
        requests.ConnectionError("Connection reset by peer"),
        SimpleNamespace(sid="SM-resent"),
    ]

    await state_machine.process_event(event)

    assert twilio_sdk.messages.create.call_count == sms_before + 2
    assert CODE in _sms_bodies(twilio_sdk)[-1]
    sms_records = [record for record in prod_db.get_alert_records(event.id) if record.alert_type == "sms"]
    assert [record.twilio_sid for record in sms_records] == ["SM-resent"]
    calls_per_event = prod_config.alerts.acknowledgment.max_call_retries
    assert twilio_sdk.calls.create.call_count == (2 if earlier_event else 1) * calls_per_event


# ---------------------------------------------------------------------------
# 2.3: one failing event never skips the rest of the batch
# ---------------------------------------------------------------------------


def _event(urgency: int) -> Event:
    now = datetime.now(UTC)
    return Event(
        id=str(uuid4()),
        event_type="invasion",
        urgency_score=urgency,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosyjskie wojska przekroczyły granicę Polski.",
        first_seen_at=now,
        last_updated_at=now,
        source_count=1,
        article_ids=[str(uuid4())],
        alert_status="phone_call",
    )


@pytest.mark.asyncio
async def test_dispatch_logs_failed_event_and_processes_the_rest(config, caplog):
    first, second, third = _event(10), _event(9), _event(9)
    state_machine = MagicMock(spec=AlertStateMachine)
    state_machine.db = None
    processed: list[str] = []

    async def process_event(event):
        processed.append(event.id)
        if event.id == first.id:
            raise RuntimeError("database is locked")

    state_machine.process_event = AsyncMock(side_effect=process_event)

    with caplog.at_level(logging.CRITICAL, logger="sentinel.alerts.dispatcher"):
        failed = await AlertDispatcher(state_machine, config).dispatch([first, second, third])

    assert processed == [first.id, second.id, third.id]
    assert failed == [first.id]
    failures = [record for record in caplog.records if record.levelno == logging.CRITICAL]
    assert len(failures) == 1
    assert first.id in failures[0].getMessage()
    assert failures[0].exc_info is not None


@pytest.mark.asyncio
async def test_dispatch_uses_snapshot_when_event_cannot_be_reread(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep, monkeypatch, caplog
):
    """An event row that cannot be read is alerted from the snapshot: the call is still placed."""
    event = store_critical_event()

    def unreadable_row(event_id):
        raise ValueError("Invalid isoformat string: 'garbage'")

    monkeypatch.setattr(prod_db, "get_event_by_id", unreadable_row)

    with caplog.at_level(logging.ERROR):
        await AlertDispatcher(_state_machine(prod_config, prod_db), prod_config).dispatch([event])

    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert twilio_sdk.messages.create.call_count == 1
    assert "Alerting failed" not in caplog.text
    assert "in-memory snapshot" in caplog.text
    assert "phone_call" in [record.alert_type for record in prod_db.get_alert_records(event.id)]


@pytest.mark.asyncio
async def test_pending_call_check_and_cleanup_run_after_an_event_fails(config, tmp_path):
    """run_cycle still checks pending calls and cleans up when one event's alert raised."""
    config.database.path = str(tmp_path / "sentinel.db")
    failing, second = _event(10), _event(9)
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)
    pipeline.classifier.aclose = AsyncMock()
    try:
        processed: list[str] = []

        async def process_event(event):
            processed.append(event.id)
            if event.id == failing.id:
                raise RuntimeError("database is locked")

        pipeline.corroborator.process_classifications = MagicMock(return_value=[failing, second])
        pipeline.state_machine.process_event = AsyncMock(side_effect=process_event)
        pipeline.state_machine.check_pending_calls = AsyncMock(return_value=[])
        pipeline.db.cleanup_old_records = MagicMock(return_value=0)

        result = await pipeline.run_cycle()

        assert processed == [failing.id, second.id]
        pipeline.state_machine.check_pending_calls.assert_awaited_once()
        pipeline.db.cleanup_old_records.assert_called_once()
        # Only the event that went through counts as alerted; the other is counted as a failure.
        assert result.alerts_sent == 1
        assert result.alert_failures == 1
        assert pipeline.stats.consecutive_failures == 1
    finally:
        await pipeline.shutdown()


@pytest.mark.asyncio
async def test_run_cycle_counts_failed_pending_call_checks(config, tmp_path):
    config.database.path = str(tmp_path / "sentinel.db")
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)
    pipeline.classifier.aclose = AsyncMock()
    try:
        pipeline.corroborator.process_classifications = MagicMock(return_value=[])
        pipeline.state_machine.check_pending_calls = AsyncMock(return_value=["record-1", "record-2"])
        pipeline.db.cleanup_old_records = MagicMock(return_value=0)

        result = await pipeline.run_cycle()

        assert result.alert_failures == 2
        pipeline.db.cleanup_old_records.assert_called_once()
    finally:
        await pipeline.shutdown()


def _cycle_result(*, alert_failures: int) -> CycleResult:
    return CycleResult(
        cycle_start=datetime.now(UTC),
        duration_seconds=1.0,
        articles_fetched=1,
        articles_unique=1,
        articles_relevant=1,
        articles_classified=1,
        events_created=2,
        alerts_sent=1,
        alert_failures=alert_failures,
    )


def test_alert_failures_extend_the_failure_streak():
    stats = PipelineStats()

    stats.record_cycle(_cycle_result(alert_failures=1))
    stats.record_cycle(_cycle_result(alert_failures=2))
    assert stats.consecutive_failures == 2
    assert stats.total_cycles == 2

    stats.record_cycle(_cycle_result(alert_failures=0))
    assert stats.consecutive_failures == 0


@pytest.mark.asyncio
async def test_cycle_with_alert_failures_reads_unhealthy(config, tmp_path):
    """A cycle that finished but failed to alert an event is not reported as healthy."""
    config.database.path = str(tmp_path / "sentinel.db")
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)
    pipeline.classifier.aclose = AsyncMock()
    try:
        outcome = {"alert_failures": 1}

        async def run_cycle(fast_only=False):
            result = _cycle_result(alert_failures=outcome["alert_failures"])
            pipeline.stats.record_cycle(result)
            return result

        pipeline.run_cycle = run_cycle
        pipeline._send_system_sms = MagicMock()
        scheduler = SentinelScheduler(pipeline, config)
        health_path = tmp_path / "health.json"

        for _ in range(3):
            await scheduler._run_with_error_handling()

        health = json.loads(health_path.read_text())
        assert health["is_healthy"] is False
        assert "Alerting failed for 1" in health["last_error"]
        assert health["consecutive_failures"] == 3
        assert health["last_cycle_alerts_sent"] == 1
        # The third failed cycle in a row sends the system SMS, as a crashed cycle does.
        pipeline._send_system_sms.assert_called_once()

        outcome["alert_failures"] = 0
        await scheduler._run_with_error_handling()

        health = json.loads(health_path.read_text())
        assert health["is_healthy"] is True
        assert health["last_error"] is None
        assert health["consecutive_failures"] == 0
    finally:
        await pipeline.shutdown()


# ---------------------------------------------------------------------------
# 2.7: the confirmation SMS always carries the code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_sms_keeps_code_with_long_summary(prod_config, prod_db, twilio_sdk):
    event = _event(10)
    event.summary_pl = "Rosyjskie wojska atakują. " * 80  # about 2000 characters
    assert len(event.summary_pl) > 1600

    await _state_machine(prod_config, prod_db)._send_confirmation_sms(event)

    (body,) = _sms_bodies(twilio_sdk)
    assert f"Odpowiedz kodem aby potwierdzic odbior alertu: {CODE}" in body
    assert body.endswith("Telefon bedzie dzwonil dopoki nie potwierdzisz.")
    assert len(body) <= 1600
    summary_line = body.split("\n\n")[1]
    assert len(summary_line) == SMS_SUMMARY_MAX_CHARS
    assert summary_line.endswith("…")


@pytest.mark.asyncio
async def test_confirmation_sms_short_summary_unchanged(prod_config, prod_db, twilio_sdk):
    event = _event(10)

    await _state_machine(prod_config, prod_db)._send_confirmation_sms(event)

    (body,) = _sms_bodies(twilio_sdk)
    assert body.split("\n\n")[1] == event.summary_pl


# ---------------------------------------------------------------------------
# A long summary cannot push the call over Twilio's TwiML limit
# ---------------------------------------------------------------------------

_LONG_SUMMARY = "Rosyjskie wojska atakują. " * 80  # about 2000 characters
_MEDIUM_SUMMARY = "Rosyjskie wojska atakują. " * 35  # about 900 characters, above the SMS cap


def _twiml_sent(twilio_sdk) -> list[str]:
    return [call.kwargs["twiml"] for call in twilio_sdk.calls.create.call_args_list]


@pytest.mark.asyncio
async def test_call_with_long_summary_fits_twiml_limit(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()
    prod_db.update_event(event.id, summary_pl=_LONG_SUMMARY)

    await _state_machine(prod_config, prod_db).process_event(event)

    twiml = _twiml_sent(twilio_sdk)
    assert len(twiml) == prod_config.alerts.acknowledgment.max_call_retries
    for document in twiml:
        assert len(document.encode("utf-8")) <= TWIML_MAX_CHARS
        # The script is shortened at its tail: its head and the start of the summary are still spoken twice.
        assert document.count("Inwazja wykryte. Rosyjskie wojska atakują. Rosyjskie wojska atakują.") == 2


@pytest.mark.asyncio
async def test_call_speaks_summary_beyond_sms_cap_in_full(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    assert len(_MEDIUM_SUMMARY) > SMS_SUMMARY_MAX_CHARS
    event = store_critical_event()
    prod_db.update_event(event.id, summary_pl=_MEDIUM_SUMMARY)

    await _state_machine(prod_config, prod_db).process_event(event)

    for document in _twiml_sent(twilio_sdk):
        assert document.count(f"{_MEDIUM_SUMMARY}. Źródła potwierdzające: 1. Pilność: 10 na 10.") == 2


def _twiml_bytes(message: str) -> int:
    return len(twilio_client_module._alert_twiml(xml_escape(message)).encode("utf-8"))


def _longest_fitting_head(message: str) -> str:
    """The longest head of ``message`` whose call TwiML, cut mark included, fits the limit.

    Found by bisection over the head length, independently of the client's own
    character-by-character scan.
    """
    low, high = 0, len(message)
    while low < high:
        middle = (low + high + 1) // 2
        if _twiml_bytes(message[:middle] + "…") <= TWIML_MAX_CHARS:
            low = middle
        else:
            high = middle - 1
    return message[:low]


@pytest.mark.parametrize(
    "message",
    [
        "&" * 3000,
        "Atak 🚨 na Polskę <PL> & Litwę. " * 200,
        "Российские войска атакуют Польшу. " * 150,
        "Żółte śmigłowce ćwiczą nad Łodzią. " * 150,
    ],
    ids=["escape-heavy", "emoji-and-markup", "cyrillic", "polish-diacritics"],
)
def test_twilio_call_message_is_shortened_to_twiml_limit(prod_config, twilio_sdk, message, caplog):
    with caplog.at_level(logging.WARNING, logger="sentinel.alerts.twilio_client"):
        record = TwilioClient(prod_config).make_alert_call("+48500100200", message, "evt-1")

    assert record is not None
    (twiml,) = _twiml_sent(twilio_sdk)
    assert len(twiml.encode("utf-8")) <= TWIML_MAX_CHARS
    assert twiml.endswith("Potwierdź odbiór alertu. Odpisz na SMS kodem, który otrzymałeś.</Say></Response>")
    # The message keeps the longest head that fits, not a shorter one.
    head = _longest_fitting_head(message)
    assert len(head) > 300
    assert record.message_body == head.rstrip() + "…"
    assert "shortened" in caplog.text


def test_twilio_call_message_within_limit_is_unchanged(prod_config, twilio_sdk):
    message = "Inwazja wykryte. Rosyjskie wojska & czołgi <PL>. Pilność: 10 na 10."

    record = TwilioClient(prod_config).make_alert_call("+48500100200", message, "evt-1")

    (twiml,) = _twiml_sent(twilio_sdk)
    assert twiml.count("Rosyjskie wojska &amp; czołgi &lt;PL&gt;. Pilność: 10 na 10.") == 2
    assert record.message_body == message


def test_update_sms_carries_summary_beyond_sms_cap_in_full(prod_config, prod_db):
    event = _event(10)
    event.summary_pl = _MEDIUM_SUMMARY
    event.source_count = 3

    body = _format_update_sms(event, prod_db, prod_config)

    assert f"\n{_MEDIUM_SUMMARY}\n" in body
    assert "Łącznie źródeł: 3" in body
    assert body.endswith("Pilność: 10/10")


# ---------------------------------------------------------------------------
# 2.8: check_pending_calls keeps the acknowledged label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_label_survives_pending_check(
    prod_config, prod_db, store_critical_event, twilio_sdk, expo_send_push, instant_alert_sleep
):
    event = store_critical_event()

    # The owner replies with the code while the call is still ringing, so the
    # round ends before the call record is resolved.
    def inbound_replies(**kwargs):
        if twilio_sdk.calls.create.call_count == 0:
            return []
        return [SimpleNamespace(body=CODE)]

    twilio_sdk.messages.list.side_effect = inbound_replies
    state_machine = _state_machine(prod_config, prod_db)

    await state_machine.process_event(event)

    acknowledged = prod_db.get_event_by_id(event.id)
    assert acknowledged.alert_status == "acknowledged"
    (call_record,) = [r for r in prod_db.get_alert_records(event.id) if r.alert_type == "phone_call"]
    assert call_record.status == "initiated"

    # The next pending-call check resolves the record but keeps the label.
    await state_machine.check_pending_calls()

    stored = prod_db.get_event_by_id(event.id)
    assert stored.alert_status == "acknowledged"
    assert stored.acknowledged_at == acknowledged.acknowledged_at
    (call_record,) = [r for r in prod_db.get_alert_records(event.id) if r.alert_type == "phone_call"]
    assert call_record.status == "completed"


@pytest.mark.asyncio
async def test_unacknowledged_call_result_still_sets_retry_pending(prod_config, prod_db, store_critical_event):
    event = store_critical_event()
    prod_db.insert_alert_record(
        AlertRecord(
            event_id=event.id,
            alert_type="phone_call",
            twilio_sid="CA00000000000000000000000000000001",
            status="initiated",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body="Alarm",
        )
    )
    twilio = create_autospec(TwilioClient, instance=True)
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    state_machine = AlertStateMachine(prod_db, twilio, prod_config, push_client=ExpoPushClient(prod_config))

    await state_machine.check_pending_calls()

    assert prod_db.get_event_by_id(event.id).alert_status == "retry_pending"
    assert [record.status for record in prod_db.get_alert_records(event.id)] == ["no-answer"]


def _pending_call(db, event_id: str) -> AlertRecord:
    record = AlertRecord(
        event_id=event_id,
        alert_type="phone_call",
        twilio_sid=f"CA{uuid4().hex}",
        status="initiated",
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="Alarm",
    )
    db.insert_alert_record(record)
    return record


@pytest.mark.asyncio
async def test_unreadable_event_row_does_not_stop_pending_call_check(
    prod_config, prod_db, store_critical_event, caplog
):
    """A call whose event row cannot be read is logged; the other pending calls are still checked."""
    broken, healthy = store_critical_event(), store_critical_event()
    broken_call = _pending_call(prod_db, broken.id)
    _pending_call(prod_db, healthy.id)
    prod_db.conn.execute("UPDATE events SET first_seen_at = 'garbage' WHERE id = ?", (broken.id,))
    prod_db.conn.commit()
    twilio = create_autospec(TwilioClient, instance=True)
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    state_machine = AlertStateMachine(prod_db, twilio, prod_config, push_client=ExpoPushClient(prod_config))

    with caplog.at_level(logging.CRITICAL, logger="sentinel.alerts.state_machine"):
        failed = await state_machine.check_pending_calls()

    assert failed == [broken_call.id]
    assert twilio.get_call_status.call_count == 2
    # The other call is resolved and its event marked for retry.
    assert [record.status for record in prod_db.get_alert_records(healthy.id)] == ["no-answer"]
    assert prod_db.get_event_by_id(healthy.id).alert_status == "retry_pending"
    # The unreadable event keeps its label; its call record is resolved and not checked again.
    (label,) = prod_db.conn.execute("SELECT alert_status FROM events WHERE id = ?", (broken.id,)).fetchone()
    assert label == "phone_call"
    assert [record.id for record in prod_db.get_pending_call_records()] == []
    failures = [record for record in caplog.records if record.levelno == logging.CRITICAL]
    assert len(failures) == 1
    assert broken.id in failures[0].getMessage()
    assert failures[0].exc_info is not None


def _corrupt_sent_at(db, record_id: str) -> None:
    """Make one stored alert record unparseable (its sent_at is no longer an ISO timestamp)."""
    db.conn.execute("UPDATE alert_records SET sent_at = 'garbage' WHERE id = ?", (record_id,))
    db.conn.commit()


@pytest.mark.asyncio
async def test_unreadable_call_record_does_not_stop_pending_call_check(
    prod_config, prod_db, store_critical_event, caplog
):
    """A pending call record that cannot be parsed is named and skipped; the other calls are still checked."""
    broken, healthy = store_critical_event(), store_critical_event()
    broken_call = _pending_call(prod_db, broken.id)
    healthy_call = _pending_call(prod_db, healthy.id)
    _corrupt_sent_at(prod_db, broken_call.id)
    twilio = create_autospec(TwilioClient, instance=True)
    twilio.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    state_machine = AlertStateMachine(prod_db, twilio, prod_config, push_client=ExpoPushClient(prod_config))

    with caplog.at_level(logging.CRITICAL, logger="sentinel.alerts.state_machine"):
        failed = await state_machine.check_pending_calls()

    assert failed == [broken_call.id]
    twilio.get_call_status.assert_called_once_with(healthy_call.twilio_sid)
    assert [record.status for record in prod_db.get_alert_records(healthy.id)] == ["no-answer"]
    assert prod_db.get_event_by_id(healthy.id).alert_status == "retry_pending"
    failures = [record for record in caplog.records if record.levelno == logging.CRITICAL]
    assert len(failures) == 1
    assert broken_call.id in failures[0].getMessage()
    assert failures[0].exc_info is not None

    # The next cycle reports the unreadable record again instead of raising.
    assert await state_machine.check_pending_calls() == [broken_call.id]
    assert twilio.get_call_status.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alert_type", "status"),
    [("phone_call", "initiated"), ("push", "sent")],
    ids=["pending-call", "delivered-push"],
)
async def test_unreadable_alert_record_does_not_cost_the_call(
    prod_config,
    prod_db,
    store_critical_event,
    twilio_sdk,
    expo_send_push,
    instant_alert_sleep,
    caplog,
    alert_type,
    status,
):
    """An alert record of the event that cannot be parsed is left out; the 9-10 event still gets push, SMS and call."""
    event = store_critical_event()
    record = AlertRecord(
        event_id=event.id,
        alert_type=alert_type,
        twilio_sid=f"X{uuid4().hex}",
        status=status,
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="Alarm",
    )
    prod_db.insert_alert_record(record)
    _corrupt_sent_at(prod_db, record.id)

    with caplog.at_level(logging.CRITICAL, logger="sentinel.alerts.state_machine"):
        await _state_machine(prod_config, prod_db).process_event(event)

    assert expo_send_push.call_count == 1
    assert twilio_sdk.messages.create.call_count == 1
    assert CODE in _sms_bodies(twilio_sdk)[0]
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    failures = [entry for entry in caplog.records if entry.levelno == logging.CRITICAL]
    assert len(failures) == 1
    assert event.id in failures[0].getMessage()
    assert record.id in failures[0].getMessage()
    assert failures[0].exc_info is not None
