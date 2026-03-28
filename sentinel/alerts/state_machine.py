import logging
import random
import time
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


def _build_sources_list(event: Event, db: Database) -> str:
    """Build a formatted source list from event article_ids.

    Looks up each article in the database to get source_name, title,
    and source_url.  Each source is rendered as a title line followed
    by a clickable URL line so the recipient can immediately verify
    the article.
    """
    lines = []
    for article_id in event.article_ids:
        article = db.get_article_by_id(article_id)
        if article is not None:
            lines.append(f"- {article.source_name}: {article.title}")
            if article.source_url:
                lines.append(f"  {article.source_url}")
        else:
            lines.append(f"- (źródło {article_id[:8]})")
    return "\n".join(lines) if lines else f"- {event.source_count} źródeł"


def _get_latest_source_name(event: Event, db: Database) -> str:
    """Get the source_name of the most recently added article in the event.

    Uses the last article_id in the list (most recent).
    Falls back to 'nowe źródło' if not found.
    """
    if event.article_ids:
        article = db.get_article_by_id(event.article_ids[-1])
        if article is not None:
            return article.source_name
    return "nowe źródło"


def _format_call_message(event: Event, config: SentinelConfig) -> str:
    """Format the phone call TTS message in Polish using config template."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    template = config.alerts.templates.call
    return template.format(
        event_type_pl=event_type_pl,
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        urgency_score=event.urgency_score,
    )


def _format_sms_message(event: Event, db: Database, config: SentinelConfig) -> str:
    """Format the SMS alert message in Polish using config template.

    Includes per-source detail lines by looking up articles from the DB.
    """
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    countries_str = ", ".join(event.affected_countries)
    first_seen_local = event.first_seen_at.strftime("%Y-%m-%d %H:%M UTC")
    sources_list = _build_sources_list(event, db)

    template = config.alerts.templates.sms
    return template.format(
        event_type_pl=event_type_pl,
        urgency_score=event.urgency_score,
        affected_countries_str=countries_str,
        aggressor=event.aggressor,
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        sources_list=sources_list,
        first_seen_at_local=first_seen_local,
    )


def _format_update_sms(
    event: Event, db: Database, config: SentinelConfig
) -> str:
    """Format SMS update for an already-acknowledged event.

    Includes the name of the most recent source.
    """
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    new_source_name = _get_latest_source_name(event, db)

    template = config.alerts.templates.sms_update
    return template.format(
        event_type_pl=event_type_pl,
        new_source_name=new_source_name,
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        urgency_score=event.urgency_score,
    )


def _format_article_links_message(event: Event, db: Database) -> str:
    """Format a WhatsApp message with clickable links to source articles."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    lines = [
        f"🔗 PROJECT SENTINEL — Źródła: {event_type_pl}",
        "",
        f"{event.summary_pl}",
        "",
        f"Artykuły źródłowe ({event.source_count}):",
    ]

    for article_id in event.article_ids:
        article = db.get_article_by_id(article_id)
        if article is not None:
            lines.append(f"• {article.source_name}: {article.title}")
            if article.source_url:
                lines.append(f"  {article.source_url}")
            lines.append("")
        else:
            lines.append(f"• (źródło {article_id[:8]})")
            lines.append("")

    return "\n".join(lines).strip()


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
            # WhatsApp disabled — route to SMS instead
            self._execute_sms(event)
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

        Urgency levels are sorted by min_score descending to avoid
        dependency on dict insertion order.
        """
        score = event.urgency_score
        source_count = event.source_count

        sorted_levels = sorted(
            self.config.alerts.urgency_levels.items(),
            key=lambda kv: kv[1].min_score,
            reverse=True,
        )

        for level_name, level in sorted_levels:
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
        """Place a phone call alert with aggressive immediate retries.

        Calls up to max_call_retries times in a tight loop, polling Twilio
        for call status between attempts. If the entire round fails, sends
        an SMS and sets status to retry_pending so the next pipeline cycle
        triggers another round. Never stops until acknowledged.
        """
        if existing_alerts is None:
            existing_alerts = self.db.get_alert_records(event.id)

        # Enforce retry interval: if there was a previous call from a prior
        # cycle, check that enough time has elapsed
        call_records = [
            a for a in existing_alerts if a.alert_type == "phone_call"
        ]
        if call_records:
            last_call_time = max(a.sent_at for a in call_records)
            retry_interval = timedelta(
                minutes=self.config.alerts.acknowledgment.retry_interval_minutes
            )
            if datetime.now(timezone.utc) < last_call_time + retry_interval:
                self.logger.debug(
                    "Event %s: retry interval not elapsed, skipping call",
                    event.id,
                )
                return

        phone_number = self.config.alerts.phone_number
        message = _format_call_message(event, self.config)
        max_per_round = self.config.alerts.acknowledgment.max_call_retries
        total_attempts = len(call_records)
        call_placed_at = datetime.now(timezone.utc)

        # Send SMS confirmation code — this is the ONLY confirmation mechanism
        self._send_confirmation_sms(event)

        # Call loop — calls are alarms only, not confirmation
        for attempt in range(1, max_per_round + 1):
            # Check WhatsApp reply before each call
            if self._check_sms_confirmation(call_placed_at):
                self._acknowledge_event(event, total_attempts)
                return

            total_attempts += 1
            self.logger.info(
                "Event %s: calling %s (round attempt %d/%d, total %d)",
                event.id[:8],
                phone_number,
                attempt,
                max_per_round,
                total_attempts,
            )

            record = self.twilio.make_alert_call(phone_number, message, event.id)
            if record is None:
                self.logger.error("Event %s: Twilio call failed to initiate", event.id[:8])
                continue

            record.attempt_number = total_attempts
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="call_placed")

            # Wait for call to finish, polling SMS in the meantime
            self._wait_for_call_and_check_sms(record, call_placed_at)

            # Check WhatsApp after call ends
            if self._check_sms_confirmation(call_placed_at):
                self._acknowledge_event(event, total_attempts)
                return

            # Brief pause between retries (10 seconds)
            if attempt < max_per_round:
                time.sleep(10)

        # Round exhausted — check SMS one more time
        if self._check_sms_confirmation(call_placed_at):
            self._acknowledge_event(event, total_attempts)
            return

        # Still not confirmed — mark for retry on next cycle
        self.logger.warning(
            "Event %s: %d calls this round, no SMS confirmation, retry in %d min",
            event.id[:8],
            max_per_round,
            self.config.alerts.acknowledgment.retry_interval_minutes,
        )
        self.db.update_event(event.id, alert_status="retry_pending")

    def _acknowledge_event(self, event: Event, total_attempts: int) -> None:
        """Mark event as acknowledged and send follow-ups."""
        self.db.update_event(
            event.id,
            alert_status="acknowledged",
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )
        self.logger.info(
            "Event %s: confirmed via SMS after %d call attempts",
            event.id[:8],
            total_attempts,
        )
        self._send_followup_sms(event.id)

    def _send_confirmation_sms(self, event: Event) -> None:
        """Send an SMS with a random 6-digit confirmation code."""
        phone_number = self.config.alerts.phone_number
        event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)

        # Generate random 6-digit code, store it for verification
        self._confirmation_code = f"{random.randint(100000, 999999)}"

        message = (
            f"PROJECT SENTINEL: {event_type_pl}\n\n"
            f"{event.summary_pl}\n\n"
            f"Odpowiedz kodem aby potwierdzic odbior alertu: {self._confirmation_code}\n\n"
            f"Telefon bedzie dzwonil dopoki nie potwierdzisz."
        )
        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            self._confirmation_sms_sid = record.twilio_sid
            self.db.insert_alert_record(record)
            self.logger.info(
                "SMS confirmation request sent for event %s (code=%s, SID=%s)",
                event.id[:8],
                self._confirmation_code,
                record.twilio_sid,
            )

    def _check_sms_confirmation(self, since: datetime) -> bool:
        """Check if the user replied with the correct 6-digit code via SMS."""
        phone_number = self.config.alerts.phone_number
        code = getattr(self, "_confirmation_code", None)
        if not code:
            return False

        try:
            # Check inbound SMS from the user's phone to our Twilio number
            messages = self.twilio.client.messages.list(
                to=self.twilio.twilio_phone,
                from_=phone_number,
                date_sent_after=since,
                limit=10,
            )
            for msg in messages:
                body = msg.body.strip() if msg.body else ""
                if code in body:
                    self.logger.info(
                        "SMS confirmation received (code=%s) from %s",
                        code,
                        phone_number,
                    )
                    return True
        except Exception as exc:
            self.logger.warning("Failed to check SMS confirmations: %s", exc)
        return False

    def _check_confirmation_sms_delivered(self) -> bool | None:
        """Check if the confirmation SMS was delivered.

        Returns True if delivered, False if failed/undelivered, None if still pending.
        """
        sid = getattr(self, "_confirmation_sms_sid", None)
        if not sid:
            return None
        try:
            msg = self.twilio.client.messages(sid).fetch()
            if msg.status == "delivered":
                return True
            if msg.status in ("failed", "undelivered"):
                self.logger.warning(
                    "Confirmation SMS %s status: %s (error=%s)",
                    sid, msg.status, msg.error_code,
                )
                return False
            return None  # still queued/sending/sent
        except Exception as exc:
            self.logger.warning("Failed to check SMS delivery status: %s", exc)
            return None

    def _wait_for_call_and_check_sms(
        self, record: AlertRecord, sms_since: datetime
    ) -> None:
        """Wait for a call to finish, checking SMS confirmation in the meantime."""
        max_wait = 90
        poll_interval = 5
        waited = 0

        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval

            # Check SMS while call is in progress
            if self._check_sms_confirmation(sms_since):
                return

            # Check if call is done
            status = self.twilio.get_call_status(record.twilio_sid)
            if status is None:
                continue

            call_status = status["status"]
            if call_status not in ("queued", "ringing", "in-progress"):
                # Call finished
                self._update_alert_record(
                    record, status=call_status,
                    duration_seconds=status.get("duration", 0),
                )
                return

    def _execute_sms(self, event: Event) -> None:
        """Send an SMS alert."""
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)

        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="sms_sent")

    def _execute_whatsapp(self, event: Event) -> None:
        """Send a WhatsApp alert."""
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)

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
        if False:  # Confirmation is now via WhatsApp only, not call duration
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
            if call_status in ("failed", "canceled"):
                self.logger.warning(
                    "Event %s call %s (duration=%ds), "
                    "terminal status — moving to retry/fallback",
                    record.event_id,
                    call_status,
                    duration,
                )
            else:
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
        event = self.db.get_event_by_id(event_id)
        if event is None:
            return

        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)
        record = self.twilio.send_sms(phone_number, message, event_id)
        if record is not None:
            self.db.insert_alert_record(record)

    def _send_update_sms(self, event: Event) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        phone_number = self.config.alerts.phone_number
        message = _format_update_sms(event, self.db, self.config)
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
        self.db.update_alert_record(
            record.id, status=status, duration_seconds=duration_seconds
        )
