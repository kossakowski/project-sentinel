"""One call round of a 9-10 event: the confirmation SMS, the calls and the acknowledgement.

A ``CallRound`` belongs to one event. It draws a confirmation code, sends it
by SMS and then places up to ``alerts.acknowledgment.max_call_retries`` calls.
The calls are only an alarm: the event is acknowledged when the owner replies
to the SMS with the code. The code and the SID of its SMS are attributes of
the round, so a reply to one event's code can never acknowledge another event.

A call that is still ringing when its round ends is resolved later by the
state machine's pending-call check through ``record_call_result``.

A round works through the state machine that started it: its Twilio client,
database, alert-record helpers, clock and logger.
"""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sentinel.alerts.formatting import cap_sms_summary, event_type_pl, format_call_message
from sentinel.models import (
    ACTIVE_CALL_STATUSES,
    FINISHED_CALL_STATUSES,
    AlertRecord,
    AlertStatus,
    AlertType,
    CallStatus,
    Event,
)

if TYPE_CHECKING:
    from sentinel.alerts.state_machine import AlertStateMachine


def generate_confirmation_code() -> str:
    """Return a random 6-digit SMS confirmation code (100000-999999).

    Uses ``secrets`` so the code is not predictable from other random output.
    """
    return str(100000 + secrets.randbelow(900000))


def _as_utc(value: datetime) -> datetime:
    """Read a timestamp without a time zone as UTC, the zone every writer stores."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class CallRound:
    """The confirmation code, its SMS and the calls of one round for one event."""

    def __init__(self, machine: "AlertStateMachine", event: Event) -> None:
        self.machine = machine
        self.event = event
        # The code the owner must reply with; drawn when the round sends its SMS.
        self.code: str | None = None
        # The SID of the confirmation SMS Twilio accepted, for the delivery check.
        self.sms_sid: str | None = None

    async def run(self, existing_alerts: list[AlertRecord]) -> None:
        """Place the round's calls until the owner replies with the code.

        The round starts only when ``retry_interval_minutes`` have passed
        since the event's last call. It sends the confirmation SMS, then calls
        up to ``max_call_retries`` times, polling Twilio for the call status
        and for the SMS reply in between. The confirmation SMS is checked once
        after the first call and resent with the same code if it did not
        arrive. A reply acknowledges the event and stops the round. When no
        reply came, the event is set to ``retry_pending``, and a later
        dispatch of the event starts a new round.
        """
        machine, event = self.machine, self.event
        acknowledgment = machine.config.alerts.acknowledgment

        # Enforce retry interval: if there was a previous call from a prior
        # cycle, check that enough time has elapsed
        call_records = [a for a in existing_alerts if a.alert_type == AlertType.PHONE_CALL]
        if call_records:
            last_call_time = max(_as_utc(a.sent_at) for a in call_records)
            retry_interval = timedelta(minutes=acknowledgment.retry_interval_minutes)
            if machine._now() < last_call_time + retry_interval:
                machine.logger.debug("Event %s: retry interval not elapsed, skipping call", event.id)
                return

        phone_number = machine.config.alerts.phone_number
        message = format_call_message(event, machine.config)
        max_per_round = acknowledgment.max_call_retries
        total_attempts = len(call_records)
        call_placed_at = machine._now()

        # Send SMS confirmation code — this is the ONLY confirmation mechanism.
        # A failure here must not stop the call: the call is the alarm.
        await self._send_confirmation_sms_guarded()

        retry_pause = acknowledgment.call_retry_pause_seconds

        # Call loop — calls are alarms only, not confirmation
        for attempt in range(1, max_per_round + 1):
            # Check SMS reply before each call
            if await self.reply_received(call_placed_at):
                await machine._acknowledge_event(event, total_attempts)
                return

            total_attempts += 1
            machine.logger.info(
                "Event %s: calling %s (round attempt %d/%d, total %d)",
                event.id[:8],
                phone_number,
                attempt,
                max_per_round,
                total_attempts,
            )

            record = await asyncio.to_thread(machine.twilio.make_alert_call, phone_number, message, event.id)
            if record is None:
                machine.logger.error("Event %s: Twilio call failed to initiate", event.id[:8])
                continue

            record.attempt_number = total_attempts
            machine._record_alert(record, event)
            machine.db.update_event(event.id, alert_status=AlertStatus.CALL_PLACED)

            # Wait for call to finish, polling SMS in the meantime
            await self.wait_for_call(record, call_placed_at)

            # Check SMS reply after call ends
            if await self.reply_received(call_placed_at):
                await machine._acknowledge_event(event, total_attempts)
                return

            # After first call, verify confirmation SMS was delivered; resend if failed
            if attempt == 1:
                delivery = await self.confirmation_sms_delivered()
                if delivery is False:
                    machine.logger.warning("Event %s: confirmation SMS failed to deliver, resending", event.id[:8])
                    await self._send_confirmation_sms_guarded(new_code=False)

            # Brief pause between retries
            if attempt < max_per_round:
                await machine._sleep(retry_pause)

        # Round exhausted — check SMS one more time
        if await self.reply_received(call_placed_at):
            await machine._acknowledge_event(event, total_attempts)
            return

        # Still not confirmed — mark for retry on next cycle
        machine.logger.warning(
            "Event %s: %d calls this round, no SMS confirmation, retry in %d min",
            event.id[:8],
            max_per_round,
            acknowledgment.retry_interval_minutes,
        )
        machine.db.update_event(event.id, alert_status=AlertStatus.RETRY_PENDING)

    async def _send_confirmation_sms_guarded(self, *, new_code: bool = True) -> None:
        """Send the confirmation SMS; log any error instead of raising it.

        The call round goes on without the SMS: the call is the alarm, and an
        error in its confirmation message must never prevent it.
        """
        try:
            await self.send_confirmation_sms(new_code=new_code)
        except Exception:
            self.machine.logger.exception(
                "Event %s: confirmation SMS failed; placing the call anyway", self.event.id[:8]
            )

    async def send_confirmation_sms(self, *, new_code: bool = True) -> None:
        """Send an SMS with the round's confirmation code.

        The first send draws the code from the state machine's
        ``code_factory``. A resend within the round (``new_code=False``)
        repeats that code: a send that timed out can still have reached the
        owner, who may already reply with it. The summary is capped like the
        alert SMS, so a long summary can never push the code out of the
        transport's length limit. The code is never logged.
        """
        event = self.event

        # Forget the previous confirmation SMS, so a send that fails leaves no
        # SID behind and the delivery check reports it as failed.
        self.sms_sid = None

        if new_code or not self.code:
            self.code = self.machine._code_factory()

        message = (
            f"PROJECT SENTINEL: {event_type_pl(event)}\n\n"
            f"{cap_sms_summary(event.summary_pl)}\n\n"
            f"Odpowiedz kodem aby potwierdzic odbior alertu: {self.code}\n\n"
            f"Telefon bedzie dzwonil dopoki nie potwierdzisz."
        )
        record = await self.machine._send_sms(event, message, accepted=self._remember_sms_sid)
        if record is not None:
            self.machine.logger.info(
                "SMS confirmation request sent for event %s (SID=%s)", event.id[:8], record.twilio_sid
            )

    def _remember_sms_sid(self, record: AlertRecord) -> None:
        self.sms_sid = record.twilio_sid

    async def reply_received(self, since: datetime) -> bool:
        """Check if the owner replied by SMS with this round's code since ``since``."""
        if not self.code:
            return False
        # The synchronous Twilio call runs in a thread so it does not block the event loop.
        bodies = await asyncio.to_thread(self.machine.twilio.list_inbound_sms, since)
        for body in bodies or ():
            if self.code in body:
                self.machine.logger.info("SMS confirmation received from %s", self.machine.config.alerts.phone_number)
                return True
        return False

    async def confirmation_sms_delivered(self) -> bool | None:
        """Check if the confirmation SMS was delivered.

        Returns True if delivered, None if still pending or unknown, and False
        if it failed, was undelivered, or was never accepted by Twilio (no SID).
        """
        sid = self.sms_sid
        if not sid:
            self.machine.logger.warning("Confirmation SMS was not sent; no message to check")
            return False
        status = await asyncio.to_thread(self.machine.twilio.get_sms_status, sid)
        if status is None:
            return None
        if status.status == "delivered":
            return True
        if status.status in ("failed", "undelivered"):
            self.machine.logger.warning(
                "Confirmation SMS %s status: %s (error=%s)",
                sid,
                status.status,
                status.error_code,
            )
            return False
        return None  # still queued/sending/sent

    async def wait_for_call(self, record: AlertRecord, sms_since: datetime) -> None:
        """Wait for a call to finish, checking for the SMS reply in the meantime."""
        acknowledgment = self.machine.config.alerts.acknowledgment
        max_wait = acknowledgment.call_poll_timeout_seconds
        poll_interval = acknowledgment.call_poll_interval_seconds
        waited = 0

        while waited < max_wait:
            await self.machine._sleep(poll_interval)
            waited += poll_interval

            # Check SMS while call is in progress
            if await self.reply_received(sms_since):
                return

            # Check if call is done
            status = await asyncio.to_thread(self.machine.twilio.get_call_status, record.twilio_sid)
            if status is None:
                continue

            call_status = status["status"]
            if call_status not in ACTIVE_CALL_STATUSES:
                # Call finished
                self.machine._update_alert_record(
                    record,
                    status=call_status,
                    duration_seconds=status.get("duration", 0),
                )
                return


async def record_call_result(machine: "AlertStateMachine", record: AlertRecord, status: dict) -> None:
    """Record the result of a call that a previous round left pending.

    A call that ended (completed, busy, no-answer, canceled or failed) is
    recorded with its status and duration. A call never acknowledges the
    event; only the SMS-code reply does. So an ended call sets the event to
    ``retry_pending`` unless it was acknowledged meanwhile, and the next
    dispatch of the event starts a new round. A call that is still going on
    is left as it is.
    """
    call_status = status["status"]
    duration = status["duration"]
    if call_status not in FINISHED_CALL_STATUSES:
        return
    machine._update_alert_record(record, status=call_status, duration_seconds=duration)
    if call_status in (CallStatus.FAILED, CallStatus.CANCELED):
        machine.logger.warning(
            "Event %s call %s (duration=%ds), terminal status — moving to retry/fallback",
            record.event_id,
            call_status,
            duration,
        )
    else:
        machine.logger.info(
            "Event %s call result: %s (duration=%ds), will retry",
            record.event_id,
            call_status,
            duration,
        )
    # An SMS-code reply can arrive while the call is still running; the
    # event is then already acknowledged and keeps that label. A row that
    # cannot be read raises before the label is written, so the label is
    # kept; check_pending_calls logs it and checks the remaining records.
    event = machine.db.get_event_by_id(record.event_id)
    if event is not None and event.acknowledged_at is not None:
        machine.logger.debug(
            "Event %s is acknowledged; keeping its alert_status after call result %s",
            record.event_id,
            call_status,
        )
        return
    # The next dispatch of the event starts the next round.
    machine.db.update_event(record.event_id, alert_status=AlertStatus.RETRY_PENDING)
