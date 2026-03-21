import logging
from datetime import datetime, timedelta, timezone

from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import AlertRecord, Event

# Event type translations for Polish alert messages
EVENT_TYPE_PL = {
    "invasion": "Inwazja",
    "airstrike": "Nalot powietrzny",
    "missile_strike": "Uderzenie rakietowe",
    "border_crossing": "Przekroczenie granicy",
    "airspace_violation": "Naruszenie przestrzeni powietrznej",
    "naval_blockade": "Blokada morska",
    "cyber_attack": "Atak cybernetyczny",
    "troop_movement": "Ruchy wojsk",
    "artillery_shelling": "Ostrzał artyleryjski",
    "drone_attack": "Atak dronów",
}


def _format_call_message(event: Event) -> str:
    """Format the phone call TTS message in Polish."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    return (
        f"{event_type_pl} wykryte. {event.summary_pl}. "
        f"Źródła potwierdzające: {event.source_count}. "
        f"Pilność: {event.urgency_score} na 10."
    )


def _format_sms_message(event: Event) -> str:
    """Format the SMS alert message in Polish."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    countries_str = ", ".join(event.affected_countries)
    first_seen_local = event.first_seen_at.strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"\U0001f6a8 PROJECT SENTINEL: {event_type_pl}\n"
        f"Pilność: {event.urgency_score}/10\n"
        f"Kraje: {countries_str}\n"
        f"Agresor: {event.aggressor}\n"
        f"\n"
        f"{event.summary_pl}\n"
        f"\n"
        f"Źródła ({event.source_count})\n"
        f"\n"
        f"Wykryto: {first_seen_local}"
    )


def _format_update_sms(event: Event) -> str:
    """Format SMS update for an already-acknowledged event."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    return (
        f"\u2139\ufe0f PROJECT SENTINEL UPDATE: {event_type_pl}\n"
        f"Nowe informacje:\n"
        f"{event.summary_pl}\n"
        f"\n"
        f"Łącznie źródeł: {event.source_count}\n"
        f"Pilność: {event.urgency_score}/10"
    )


class AlertStateMachine:
    """Manages the lifecycle of event alerts."""

    def __init__(
        self, db: Database, twilio_client: TwilioClient, config: SentinelConfig
    ) -> None:
        self.db = db
        self.twilio = twilio_client
        self.config = config
        self.logger = logging.getLogger("sentinel.alerts.state_machine")

    def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event."""
        if self._is_in_cooldown(event):
            self.logger.debug(
                "Event %s in cooldown, skipping", event.id
            )
            return

        existing_alerts = self.db.get_alert_records(event.id)

        if self._is_acknowledged(existing_alerts):
            if event.last_updated_at > self._last_alert_time(existing_alerts):
                self._send_update_sms(event)
            return

        # If there are pending call records (initiated but not yet resolved),
        # don't send another alert — the call check cycle will handle it
        if any(
            a.alert_type == "phone_call" and a.status in ("initiated", "ringing")
            for a in existing_alerts
        ):
            self.logger.debug(
                "Event %s has a pending call, skipping", event.id
            )
            return

        action = self._determine_action(event)
        self.logger.info(
            "Event %s: urgency=%d, sources=%d, action=%s",
            event.id,
            event.urgency_score,
            event.source_count,
            action,
        )

        if action == "phone_call":
            self._execute_phone_call(event, existing_alerts)
        elif action == "sms":
            self._execute_sms(event)
        elif action == "whatsapp":
            self._execute_whatsapp(event)
        # action == "log_only" -> do nothing beyond the log above

    def check_pending_calls(self) -> None:
        """Check status of calls that were placed but not yet confirmed.

        Called on each scheduler cycle.
        """
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            status = self.twilio.get_call_status(record.twilio_sid)
            if status is not None:
                self._handle_call_result(record, status)

    def _determine_action(self, event: Event) -> str:
        """Determine the alert action based on urgency score and source count.

        Decision matrix (from config urgency_levels):
          9-10 + 2+ sources -> phone_call
          9-10 + 1 source   -> sms
          7-8               -> sms
          5-6               -> whatsapp
          1-4               -> log_only
        """
        score = event.urgency_score
        source_count = event.source_count

        for level_name, level in self.config.alerts.urgency_levels.items():
            if score >= level.min_score:
                if level.action == "phone_call":
                    if source_count >= level.corroboration_required:
                        return "phone_call"
                    else:
                        return "sms"
                return level.action

        return "log_only"

    def _is_in_cooldown(self, event: Event) -> bool:
        """Check if the event is within the cooldown period after acknowledgment."""
        if event.acknowledged_at is None:
            return False

        cooldown_hours = self.config.alerts.acknowledgment.cooldown_hours
        cooldown_end = event.acknowledged_at + timedelta(hours=cooldown_hours)
        return datetime.now(timezone.utc) < cooldown_end

    def _is_acknowledged(self, alerts: list[AlertRecord]) -> bool:
        """Check if any alert for this event was acknowledged."""
        return any(a.status == "acknowledged" for a in alerts)

    def _last_alert_time(self, alerts: list[AlertRecord]) -> datetime:
        """Return the sent_at time of the most recent alert."""
        if not alerts:
            return datetime.min.replace(tzinfo=timezone.utc)
        return max(a.sent_at for a in alerts)

    def _execute_phone_call(
        self, event: Event, existing_alerts: list[AlertRecord] | None = None
    ) -> None:
        """Place a phone call alert."""
        if existing_alerts is None:
            existing_alerts = self.db.get_alert_records(event.id)

        # Count previous call attempts
        call_attempts = sum(
            1 for a in existing_alerts if a.alert_type == "phone_call"
        )
        max_retries = self.config.alerts.acknowledgment.max_call_retries

        if call_attempts >= max_retries:
            self.logger.warning(
                "Event %s: max call retries (%d) reached, falling back to SMS",
                event.id,
                max_retries,
            )
            self._execute_sms(event)
            self.db.update_event(event.id, alert_status="sms_fallback")
            return

        phone_number = self.config.alerts.phone_number
        message = _format_call_message(event)

        record = self.twilio.make_alert_call(phone_number, message, event.id)
        if record is not None:
            record.attempt_number = call_attempts + 1
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="call_placed")

    def _execute_sms(self, event: Event) -> None:
        """Send an SMS alert."""
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event)

        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="sms_sent")

    def _execute_whatsapp(self, event: Event) -> None:
        """Send a WhatsApp alert."""
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event)

        record = self.twilio.send_whatsapp(phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="whatsapp_sent")

    def _handle_call_result(
        self, record: AlertRecord, status: dict
    ) -> None:
        """Handle the result of a previously placed phone call.

        If the call was answered (duration > threshold), mark as acknowledged.
        Otherwise, retry or fall back to SMS.
        """
        call_status = status["status"]
        duration = status["duration"]
        threshold = (
            self.config.alerts.acknowledgment.call_duration_threshold_seconds
        )

        if call_status == "completed" and duration > threshold:
            # Call was answered — acknowledged
            self.db.update_event(
                record.event_id,
                alert_status="acknowledged",
                acknowledged_at=datetime.now(timezone.utc).isoformat(),
            )
            # Update the alert record
            self._update_alert_record(
                record, status="acknowledged", duration_seconds=duration
            )
            self.logger.info(
                "Event %s acknowledged via call (duration=%ds)",
                record.event_id,
                duration,
            )
            # Send follow-up SMS with details
            self._send_followup_sms(record.event_id)
        elif call_status in ("completed", "busy", "no-answer", "canceled", "failed"):
            # Call was not properly answered
            self._update_alert_record(
                record, status=call_status, duration_seconds=duration
            )
            self.logger.info(
                "Event %s call result: %s (duration=%ds), will retry",
                record.event_id,
                call_status,
                duration,
            )
            # Retry logic is handled by process_event on next cycle
            # The alert_status remains "call_placed" so it will be retried
            self.db.update_event(
                record.event_id, alert_status="retry_pending"
            )
        # If still in-progress/queued/ringing, leave as-is

    def _send_followup_sms(self, event_id: str) -> None:
        """Send a follow-up SMS after a call is acknowledged."""
        # Retrieve the event from the database to get current details
        active_events = self.db.get_active_events(within_hours=24)
        event = next((e for e in active_events if e.id == event_id), None)
        if event is None:
            return

        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event)
        record = self.twilio.send_sms(phone_number, message, event_id)
        if record is not None:
            self.db.insert_alert_record(record)

    def _send_update_sms(self, event: Event) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        phone_number = self.config.alerts.phone_number
        message = _format_update_sms(event)
        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.logger.info(
                "Update SMS sent for acknowledged event %s", event.id
            )

    def _update_alert_record(
        self,
        record: AlertRecord,
        status: str,
        duration_seconds: int | None = None,
    ) -> None:
        """Update an existing alert record's status and duration in the DB."""
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE alert_records SET status = ?, duration_seconds = ? "
                "WHERE id = ?",
                (status, duration_seconds, record.id),
            )
