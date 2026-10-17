"""The alert lifecycle of an event: routing, delivery and the pending-call check.

``AlertStateMachine.process_event`` takes the channel from the urgency tiers
(``routing.resolve_action``), checks the event's alert records for what was
already delivered (``ledger``), sends the push and SMS and hands a 9-10 call
to a per-event ``CallRound``. The texts come from ``formatting``.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sentinel.alerts.call_round import CallRound, generate_confirmation_code, record_call_result
from sentinel.alerts.formatting import SMS_SUMMARY_MAX_CHARS as SMS_SUMMARY_MAX_CHARS  # re-exported
from sentinel.alerts.formatting import build_push_data, format_push, format_sms_message, format_update_sms
from sentinel.alerts.ledger import channel_delivered, has_new_delivered_revision, has_pending_call, is_acknowledged
from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.routing import Action, resolve_action
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import PENDING_CALL_STATUSES, AlertRecord, AlertStatus, AlertType, Event

# Row-by-row reads of alert_records. Database.get_alert_records and
# get_pending_call_records parse every row in one go, so a single row whose
# stored values cannot be parsed (for example a malformed sent_at) makes the
# whole read raise. When that happens the alert path runs the same query again
# and parses each row on its own, so only the unreadable rows are left out.
_EVENT_ALERT_RECORDS_SQL = "SELECT * FROM alert_records WHERE event_id = ? ORDER BY sent_at"
_PENDING_CALL_RECORDS_SQL = (
    f"SELECT * FROM alert_records WHERE alert_type = ? AND status IN ({', '.join('?' * len(PENDING_CALL_STATUSES))})"
)
_PENDING_CALL_PARAMS = (AlertType.PHONE_CALL, *PENDING_CALL_STATUSES)


class AlertStateMachine:
    """Manages the lifecycle of event alerts."""

    def __init__(
        self,
        db: Database,
        twilio_client: TwilioClient,
        config: SentinelConfig,
        push_client: ExpoPushClient | None = None,
        code_factory: Callable[[], str] = generate_confirmation_code,
    ) -> None:
        """Create the state machine.

        ``code_factory`` makes the confirmation code that each call round sends
        by SMS and then waits for in the owner's reply. Tests pass a constant.
        """
        self.db = db
        self.twilio = twilio_client
        self.config = config
        self.push = push_client or ExpoPushClient(config)
        self._code_factory = code_factory
        self.logger = logging.getLogger("sentinel.alerts.state_machine")

    async def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event.

        The caller can hold an event snapshot from before an incident-memory
        merge or escalation.  Prefer the row just persisted by that workflow so
        delivery decisions always use its current notification revision.  When
        that row cannot be read, the snapshot is alerted instead, so a broken
        row never costs the event its call.  The same holds for the event's
        alert records: an unreadable record is left out of the delivery
        decisions instead of stopping them (see ``_read_alert_records``).
        """
        try:
            persisted_event = self.db.get_event_by_id(event.id)
        except Exception:
            self.logger.error(
                "Could not re-read event %s; alerting from the in-memory snapshot",
                event.id,
                exc_info=True,
            )
            persisted_event = None
        if persisted_event is not None:
            event = persisted_event
        existing_alerts = self._read_alert_records(event.id)

        if is_acknowledged(existing_alerts) or event.acknowledged_at is not None:
            # An acknowledgement stops further calls, but it must not hide a
            # genuine escalation.  Only the incident grouper increments this
            # revision; source-count and timestamp changes therefore cannot
            # manufacture an update.  Cooldown intentionally does not apply to
            # a new revision.
            if has_new_delivered_revision(event, existing_alerts):
                if not channel_delivered(existing_alerts, "sms", event.notification_revision):
                    await self._send_update_sms(event)
                if not channel_delivered(existing_alerts, "push", event.notification_revision):
                    await self._maybe_send_push(event, existing_alerts, is_update=True)
            return

        # If there are pending call records (initiated but not yet resolved),
        # don't send another alert — the call check cycle will handle it
        if has_pending_call(existing_alerts):
            self.logger.debug("Event %s has a pending call, skipping", event.id)
            return

        action = resolve_action(self.config.alerts.urgency_levels, event.urgency_score, event.source_count)
        self.logger.info(
            "Event %s: urgency=%d, sources=%d, action=%s",
            event.id,
            event.urgency_score,
            event.source_count,
            action,
        )

        # Route the resolved action to the per-tier channels. SMS-tier levels
        # (5-8) resolve to "sms" / "push" / "both" via each level's `channel`;
        # 9-10 resolves to "phone_call" (call + confirmation SMS plus an additive
        # Expo push, AD-2) and 1-4 to "log_only".
        send_push = action in (Action.PUSH, Action.BOTH, Action.PHONE_CALL)
        send_sms = action in (Action.SMS, Action.BOTH)

        # SMS and push are each suppressed only after *that channel* has
        # successfully delivered this notification revision.  A failed attempt
        # stays retryable, and a real revision increment can notify again.
        if send_sms and channel_delivered(existing_alerts, "sms", event.notification_revision):
            self.logger.debug(
                "Event %s already has SMS delivery for revision %d; suppressing re-SMS",
                event.id,
                event.notification_revision,
            )
            send_sms = False

        # Push reaches the phone immediately and self-dedups on a successful
        # push for this revision (so call-retry/re-corroboration cycles do not
        # re-push, while failed pushes remain retryable). It goes first, but an
        # error while it is built or sent must never stop the 9-10 call or the
        # SMS that follow it.
        if send_push:
            try:
                await self._maybe_send_push(event, existing_alerts)
            except Exception:
                self.logger.exception(
                    "Event %s: push failed; continuing with the remaining channels (action=%s)",
                    event.id,
                    action,
                )

        if action == Action.PHONE_CALL:
            await self._execute_phone_call(event, existing_alerts)
        elif send_sms:
            await self._execute_sms(event)
        # push-only / suppressed-SMS / log_only -> no Twilio SMS

    async def check_pending_calls(self) -> list[str]:
        """Check status of calls that were placed but not yet confirmed.

        Called on each scheduler cycle. Records are isolated from each other:
        an exception while one record is checked (for example, its event row
        cannot be read) is logged with its traceback and the remaining records
        are still checked, so the caller's cleanup still runs.  A pending
        record that cannot even be parsed is skipped the same way and logged
        on every cycle until the row is repaired.

        Returns the ids of the alert records whose check raised or that could
        not be parsed, so the caller can count them and report the cycle as
        unhealthy.
        """
        failed_record_ids: list[str] = []
        try:
            pending_calls = self.db.get_pending_call_records()
        except Exception:
            pending_calls, unreadable = self._reread_alert_records(
                _PENDING_CALL_RECORDS_SQL, _PENDING_CALL_PARAMS, "Pending call check", "checking the readable ones"
            )
            failed_record_ids.extend(unreadable)
        for record in pending_calls:
            try:
                status = await asyncio.to_thread(self.twilio.get_call_status, record.twilio_sid)
                if status is not None:
                    await record_call_result(self, record, status)
            except Exception:
                self.logger.critical(
                    "Pending-call check failed for alert record %s (event %s); continuing with the remaining records",
                    record.id,
                    record.event_id,
                    exc_info=True,
                )
                failed_record_ids.append(record.id)
        return failed_record_ids

    def _determine_action(self, event: Event) -> Action:
        """Kept for tests: ``resolve_action`` for ``event`` on this machine's tiers.

        Production code calls ``resolve_action`` itself.
        """
        return resolve_action(self.config.alerts.urgency_levels, event.urgency_score, event.source_count)

    def _now(self) -> datetime:
        """The current UTC time on the alert path.

        Call rounds read the clock here too, so pinning this module's
        ``datetime`` (as the frozen-clock tests and the eval replays do) pins
        the whole round.
        """
        return datetime.now(UTC)

    async def _sleep(self, seconds: float) -> None:
        """Wait without blocking the event loop; call rounds wait here too, for the same reason as ``_now``."""
        await asyncio.sleep(seconds)

    def _read_alert_records(self, event_id: str) -> list[AlertRecord]:
        """Return the alert records of ``event_id``, leaving out rows that cannot be parsed.

        A single unreadable row must not cost a 9-10 event its call.  When the
        normal read raises, the rows are parsed one by one and the unreadable
        ones are named in one critical log line.  They then take no part in the
        delivery decisions, which has these effects until the rows are
        repaired:

        - An unreadable pending call no longer holds the event back.
        - An unreadable delivered SMS or push no longer suppresses a resend.
        - An unreadable call no longer counts for the retry interval or the
          attempt number, so the next round can start sooner than
          ``retry_interval_minutes`` allows.
        - On an acknowledged event, an escalation update is sent only when a
          readable record shows an earlier delivered revision.  When every
          delivered record is unreadable, no update SMS or push goes out.
        """
        try:
            return self.db.get_alert_records(event_id)
        except Exception:
            records, _ = self._reread_alert_records(
                _EVENT_ALERT_RECORDS_SQL, (event_id,), f"Event {event_id}", "deciding delivery without them"
            )
            return records

    def _reread_alert_records(
        self, sql: str, params: tuple, context: str, consequence: str
    ) -> tuple[list[AlertRecord], list[str]]:
        """Re-read alert records row by row after the normal read raised.

        Call it inside the ``except`` block of that read, so its traceback is
        logged.  A warning is written before the re-read, so the failure is on
        record even when the re-read raises too.  Unreadable rows are named in
        one critical line.  When every row is readable the first read failed
        for another reason (for example a locked database), which is logged as
        an error.  Returns the readable records and the unreadable row ids.
        """
        self.logger.warning("%s: alert records could not be read together; re-reading them row by row", context)
        records, unreadable = self._parse_alert_record_rows(sql, params)
        if unreadable:
            self.logger.critical(
                "%s: %d alert record(s) cannot be read, %s: %s",
                context,
                len(unreadable),
                consequence,
                ", ".join(unreadable),
                exc_info=True,
            )
        else:
            self.logger.error(
                "%s: the alert records could not be read together, but every row was readable on its own",
                context,
                exc_info=True,
            )
        return records, unreadable

    def _parse_alert_record_rows(self, sql: str, params: tuple) -> tuple[list[AlertRecord], list[str]]:
        """Run ``sql`` on alert_records and parse each row on its own.

        Returns the readable records in query order and the ids of the rows
        that could not be parsed.
        """
        records: list[AlertRecord] = []
        unreadable: list[str] = []
        for row in self.db.conn.execute(sql, params).fetchall():
            try:
                records.append(AlertRecord.from_row(row))
            except Exception:
                unreadable.append(str(row["id"]))
        return records, unreadable

    async def _execute_phone_call(self, event: Event, existing_alerts: list[AlertRecord] | None = None) -> None:
        """Run one call round for ``event`` (see ``CallRound.run``).

        Called without ``existing_alerts`` (the ``--test-alert`` path), it reads
        the event's records itself, so the retry interval still applies.
        """
        if existing_alerts is None:
            existing_alerts = self._read_alert_records(event.id)
        await CallRound(self, event).run(existing_alerts)

    async def _acknowledge_event(self, event: Event, total_attempts: int) -> None:
        """Mark event as acknowledged and send follow-ups."""
        self.db.update_event(
            event.id,
            alert_status=AlertStatus.ACKNOWLEDGED,
            acknowledged_at=self._now().isoformat(),
        )
        self.logger.info(
            "Event %s: confirmed via SMS after %d call attempts",
            event.id[:8],
            total_attempts,
        )
        await self._send_followup_sms(event)

    async def _execute_sms(self, event: Event) -> None:
        """Send an SMS alert."""
        record = await self._send_sms(event, format_sms_message(event, self.db, self.config))
        if record is not None:
            self.db.update_event(event.id, alert_status=AlertStatus.SMS_SENT)

    async def _send_followup_sms(self, event: Event) -> None:
        """Send a follow-up SMS after a call is acknowledged.

        The SMS is built from the stored event row.  When that row cannot be
        read, it is built from the snapshot the call round alerted from.
        """
        try:
            stored = self.db.get_event_by_id(event.id)
        except Exception:
            self.logger.error(
                "Could not re-read event %s; sending the follow-up SMS from the in-memory snapshot",
                event.id,
                exc_info=True,
            )
            stored = event
        if stored is None:
            return
        await self._send_sms(stored, format_sms_message(stored, self.db, self.config))

    async def _send_update_sms(self, event: Event) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        record = await self._send_sms(event, format_update_sms(event, self.db, self.config))
        if record is not None:
            self.logger.info("Update SMS sent for acknowledged event %s", event.id)

    async def _send_sms(
        self, event: Event, body: str, accepted: Callable[[AlertRecord], None] | None = None
    ) -> AlertRecord | None:
        """Send ``body`` to the owner's phone and record it under ``event``.

        Returns the record, or None when Twilio did not accept the SMS.
        ``accepted`` sees the record as soon as Twilio accepted it, before it is
        saved, so an error while saving cannot hide an SMS that did go out.
        """
        record = await asyncio.to_thread(self.twilio.send_sms, self.config.alerts.phone_number, body, event.id)
        if record is not None:
            if accepted is not None:
                accepted(record)
            self._record_alert(record, event)
        return record

    async def _maybe_send_push(self, event: Event, existing_alerts: list[AlertRecord], is_update: bool = False) -> None:
        """Send an Expo push for the resolved channel, recording it as a 'push' alert.

        Invoked by process_event when the resolved tier channel is "push" or
        "both" (per-tier routing), additively on the 9-10 "phone_call" action
        (AD-2), and on acknowledged-event escalation updates (AD-3). No-op when
        push is disabled or no tokens are configured. Delivery is deduped only by
        a successful push record for the current notification revision, so a
        failed attempt retries and an escalation revision can notify once. The
        blocking HTTP POST is offloaded to a thread like the Twilio calls.
        """
        push_cfg = self.config.alerts.push
        if not push_cfg.enabled or not push_cfg.tokens:
            return
        if channel_delivered(existing_alerts, "push", event.notification_revision):
            return

        title, body = format_push(event, is_update=is_update)
        data = build_push_data(event, self.db, self.config, is_update)
        record = await asyncio.to_thread(self.push.send_push, title, body, event.id, data)
        if record is not None:
            try:
                self._record_alert(record, event)
            except Exception:
                # The phone already has this push; only its record is missing.
                self.logger.error(
                    "Event %s: push was sent but its record could not be saved; the next dispatch may send it again",
                    event.id,
                )
                raise
            self.logger.info("Push alert recorded for event %s", event.id[:8])

    def _record_alert(self, record: AlertRecord, event: Event) -> None:
        """Persist an attempt with the incident revision it belongs to.

        Transports return a record only when they accepted an attempt, but test
        doubles and later providers can return a failed record.  Persisting that
        diagnostic is useful; the revision dedup logic deliberately treats only
        successful statuses as delivered.
        """
        record.event_revision = event.notification_revision
        self.db.insert_alert_record(record)

    def _update_alert_record(self, record: AlertRecord, status: str, duration_seconds: int | None = None) -> None:
        """Update an existing alert record's status and duration in the DB."""
        self.db.update_alert_record(record.id, status=status, duration_seconds=duration_seconds)
