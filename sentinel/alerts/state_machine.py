import logging
import random
import time
from datetime import datetime, timedelta, timezone

from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import AlertRecord, ConfirmationCode, Event, User

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

# Channel severity order (highest to lowest)
CHANNEL_SEVERITY = ["phone_call", "sms", "whatsapp", "log_only"]


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


def _format_call_message(
    event: Event, config: SentinelConfig, *, language: str = "pl"
) -> str:
    """Format the phone call TTS message in Polish using config template."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    template = config.alerts.templates.call
    return template.format(
        event_type_pl=event_type_pl,
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        urgency_score=event.urgency_score,
    )


def _format_sms_message(
    event: Event, db: Database, config: SentinelConfig, *, language: str = "pl"
) -> str:
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
    event: Event, db: Database, config: SentinelConfig, *, language: str = "pl"
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


def _resolve_channel_from_preset(preset_rules: dict, urgency_score: int) -> str:
    """Resolve channel from tier preset rules based on urgency score.

    preset_rules maps urgency ranges like "9-10" to channel names.
    Returns the matching channel or "log_only" if no rule matches.
    """
    for range_str, channel in preset_rules.items():
        parts = range_str.split("-")
        if len(parts) == 2:
            low, high = int(parts[0]), int(parts[1])
        else:
            low = high = int(parts[0])
        if low <= urgency_score <= high:
            return channel
    return "log_only"


def _fallback_channel(channel: str, available_channels: list[str]) -> str:
    """Find the best available channel at or below the given channel severity.

    Falls back through CHANNEL_SEVERITY order. If nothing is available,
    returns "log_only".
    """
    try:
        start_idx = CHANNEL_SEVERITY.index(channel)
    except ValueError:
        return "log_only"

    for candidate in CHANNEL_SEVERITY[start_idx:]:
        if candidate == "log_only":
            return "log_only"
        if candidate in available_channels:
            return candidate
    return "log_only"


class AlertStateMachine:
    """Manages the lifecycle of event alerts with per-user routing."""

    def __init__(
        self, db: Database, twilio_client: TwilioClient, config: SentinelConfig
    ) -> None:
        self.db = db
        self.twilio = twilio_client
        self.config = config
        self.logger = logging.getLogger("sentinel.alerts.state_machine")

    def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event.

        Queries all active users whose monitored countries overlap with the
        event's affected_countries and processes the event for each user.
        """
        # Collect all matching users across all affected countries
        seen_user_ids: set[str] = set()
        matching_users: list[User] = []

        for country in event.affected_countries:
            users = self.db.get_users_by_country(country)
            for user in users:
                if user.id not in seen_user_ids:
                    seen_user_ids.add(user.id)
                    matching_users.append(user)

        if not matching_users:
            self.logger.debug(
                "Event %s: no users monitoring countries %s",
                event.id[:8],
                event.affected_countries,
            )
            return

        for user in matching_users:
            try:
                self._process_event_for_user(event, user)
            except Exception as exc:
                self.logger.error(
                    "Event %s: error processing for user %s: %s",
                    event.id[:8],
                    user.id[:8],
                    exc,
                    exc_info=True,
                )

    def _process_event_for_user(self, event: Event, user: User) -> None:
        """Process an event for a single user, applying per-user tier rules."""
        if self._is_in_cooldown(event, user):
            self.logger.debug(
                "Event %s: user %s in cooldown, skipping",
                event.id[:8],
                user.id[:8],
            )
            return

        existing_alerts = self._get_user_alert_records(event.id, user.id)

        if self._is_acknowledged(existing_alerts):
            if event.last_updated_at > self._last_alert_time(existing_alerts):
                self._send_update_sms(event, user)
            return

        # If there are pending call records for this user, don't send another
        if any(
            a.alert_type == "phone_call" and a.status in ("initiated", "ringing")
            for a in existing_alerts
        ):
            self.logger.debug(
                "Event %s: user %s has a pending call, skipping",
                event.id[:8],
                user.id[:8],
            )
            return

        action = self._determine_action(event, user)
        self.logger.info(
            "Event %s: user=%s, urgency=%d, sources=%d, action=%s",
            event.id[:8],
            user.id[:8],
            event.urgency_score,
            event.source_count,
            action,
        )

        if action == "phone_call":
            self._execute_phone_call(event, user, existing_alerts)
        elif action == "sms":
            self._execute_sms(event, user)
        elif action == "whatsapp":
            self._execute_whatsapp(event, user)
        # action == "log_only" -> do nothing beyond the log above

    def check_pending_calls(self) -> None:
        """Check status of calls that were placed but not yet confirmed.

        Called on each scheduler cycle. Resolves the user from the alert
        record's user_id for follow-up routing.
        """
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            status = self.twilio.get_call_status(record.twilio_sid)
            if status is not None:
                # Resolve user for follow-up actions
                user = None
                if record.user_id:
                    user = self.db.get_user_by_id(record.user_id)
                self._handle_call_result(record, status, user)

    def _determine_action(self, event: Event, user: User | None = None) -> str:
        """Determine the alert action based on user's tier rules.

        If a user is provided, resolves the channel from the user's tier:
        - preset mode: uses tier.preset_rules
        - customizable mode: uses user_alert_rules

        Falls back to the old config-based urgency_levels if no user is
        provided (for backward compatibility with dry-run logging).

        The resolved channel is validated against tier.available_channels
        with fallback to the next lower severity channel.
        """
        if user is None:
            return self._determine_action_from_config(event)

        tier = self.db.get_tier_by_id(user.tier_id)
        if tier is None:
            self.logger.warning(
                "User %s has invalid tier_id %s, falling back to log_only",
                user.id[:8],
                user.tier_id,
            )
            return "log_only"

        # Resolve channel from tier rules
        if tier.preference_mode == "preset":
            if tier.preset_rules is None:
                self.logger.warning(
                    "Tier %s is preset but has no preset_rules", tier.name
                )
                return "log_only"
            channel = _resolve_channel_from_preset(
                tier.preset_rules, event.urgency_score
            )
        elif tier.preference_mode == "customizable":
            channel = self._resolve_channel_from_user_rules(
                user, event
            )
        else:
            self.logger.warning(
                "Unknown preference_mode %s for tier %s",
                tier.preference_mode,
                tier.name,
            )
            return "log_only"

        # Validate against tier's available channels with fallback
        if channel == "log_only":
            return "log_only"

        if channel not in tier.available_channels:
            original = channel
            channel = _fallback_channel(channel, tier.available_channels)
            self.logger.info(
                "Channel %s not in tier %s available_channels, fell back to %s",
                original,
                tier.name,
                channel,
            )

        return channel

    def _determine_action_from_config(self, event: Event) -> str:
        """Legacy action determination from config urgency_levels.

        Used for dry-run logging when no user context is available.
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

    def _resolve_channel_from_user_rules(
        self, user: User, event: Event
    ) -> str:
        """Resolve channel from user's custom alert rules.

        Rules are sorted by priority DESC (from DB). First matching rule
        based on urgency range wins.
        """
        rules = self.db.get_user_alert_rules(user.id)
        score = event.urgency_score

        for rule in rules:
            if rule.min_urgency <= score <= rule.max_urgency:
                return rule.channel

        return "log_only"

    def _get_user_alert_records(
        self, event_id: str, user_id: str
    ) -> list[AlertRecord]:
        """Get alert records for a specific event and user."""
        all_records = self.db.get_alert_records(event_id)
        return [r for r in all_records if r.user_id == user_id]

    def _is_in_cooldown(self, event: Event, user: User) -> bool:
        """Check if the user is within the cooldown period for this event.

        Per-user cooldown: checks the user's most recent acknowledged alert
        record for this event, NOT the event-level acknowledged_at.
        """
        user_alerts = self._get_user_alert_records(event.id, user.id)
        acknowledged_alerts = [
            a for a in user_alerts if a.status == "acknowledged"
        ]
        if not acknowledged_alerts:
            return False

        latest_ack = max(a.sent_at for a in acknowledged_alerts)
        cooldown_hours = self.config.alerts.acknowledgment.cooldown_hours
        cooldown_end = latest_ack + timedelta(hours=cooldown_hours)
        return datetime.now(timezone.utc) < cooldown_end

    def _is_acknowledged(self, alerts: list[AlertRecord]) -> bool:
        """Check if any alert for this user+event was acknowledged."""
        return any(a.status == "acknowledged" for a in alerts)

    def _last_alert_time(self, alerts: list[AlertRecord]) -> datetime:
        """Return the sent_at time of the most recent alert."""
        if not alerts:
            return datetime.min.replace(tzinfo=timezone.utc)
        return max(a.sent_at for a in alerts)

    def _execute_phone_call(
        self,
        event: Event,
        user: User,
        existing_alerts: list[AlertRecord] | None = None,
    ) -> None:
        """Place a phone call alert with aggressive immediate retries.

        Calls up to max_call_retries times in a tight loop, polling Twilio
        for call status between attempts. If the entire round fails, sets
        status to retry_pending so the next pipeline cycle triggers another
        round. Never stops until acknowledged.
        """
        if existing_alerts is None:
            existing_alerts = self._get_user_alert_records(event.id, user.id)

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
                    "Event %s: user %s retry interval not elapsed, skipping call",
                    event.id[:8],
                    user.id[:8],
                )
                return

        phone_number = user.phone_number
        message = _format_call_message(event, self.config)
        max_per_round = self.config.alerts.acknowledgment.max_call_retries
        total_attempts = len(call_records)
        call_placed_at = datetime.now(timezone.utc)

        # Send WhatsApp confirmation request — this is the ONLY confirmation mechanism
        self._send_confirmation_whatsapp(event, user)

        # Call loop — calls are alarms only, not confirmation
        for attempt in range(1, max_per_round + 1):
            # Check WhatsApp reply before each call
            if self._check_whatsapp_confirmation(call_placed_at, user, event):
                self._acknowledge_event(event, user, total_attempts)
                return

            total_attempts += 1
            self.logger.info(
                "Event %s: calling %s (user %s, round attempt %d/%d, total %d)",
                event.id[:8],
                phone_number,
                user.id[:8],
                attempt,
                max_per_round,
                total_attempts,
            )

            record = self.twilio.make_alert_call(phone_number, message, event.id)
            if record is None:
                self.logger.error("Event %s: Twilio call failed to initiate", event.id[:8])
                continue

            record.attempt_number = total_attempts
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="call_placed")

            # Wait for call to finish, polling WhatsApp in the meantime
            self._wait_for_call_and_check_whatsapp(
                record, call_placed_at, user, event
            )

            # Check WhatsApp after call ends
            if self._check_whatsapp_confirmation(call_placed_at, user, event):
                self._acknowledge_event(event, user, total_attempts)
                return

            # Brief pause between retries (10 seconds)
            if attempt < max_per_round:
                time.sleep(10)

        # Round exhausted — check WhatsApp one more time
        if self._check_whatsapp_confirmation(call_placed_at, user, event):
            self._acknowledge_event(event, user, total_attempts)
            return

        # Still not confirmed — mark for retry on next cycle
        self.logger.warning(
            "Event %s: user %s, %d calls this round, no WhatsApp confirmation, retry in %d min",
            event.id[:8],
            user.id[:8],
            max_per_round,
            self.config.alerts.acknowledgment.retry_interval_minutes,
        )
        self.db.update_event(event.id, alert_status="retry_pending")

    def _acknowledge_event(
        self, event: Event, user: User, total_attempts: int
    ) -> None:
        """Mark event as acknowledged for this user and send follow-ups."""
        # Update the event-level status (backward compat)
        self.db.update_event(
            event.id,
            alert_status="acknowledged",
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        )

        # Mark user's alert records as acknowledged
        user_alerts = self._get_user_alert_records(event.id, user.id)
        for alert in user_alerts:
            if alert.status not in ("acknowledged",):
                self.db.update_alert_record(alert.id, status="acknowledged")

        self.logger.info(
            "Event %s: user %s confirmed via WhatsApp after %d call attempts",
            event.id[:8],
            user.id[:8],
            total_attempts,
        )
        self._send_followup_sms(event.id, user)

    def _send_confirmation_whatsapp(self, event: Event, user: User) -> None:
        """Send a WhatsApp with a random 6-digit confirmation code.

        Stores the code in the confirmation_codes DB table (persistent,
        survives restarts).
        """
        phone_number = user.phone_number
        event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)

        # Generate random 6-digit code
        code_str = f"{random.randint(100000, 999999)}"

        # Store in DB
        conf_code = ConfirmationCode(
            user_id=user.id,
            event_id=event.id,
            code=code_str,
        )
        self.db.insert_confirmation_code(conf_code)

        message = (
            f"🚨 PROJECT SENTINEL: {event_type_pl}\n\n"
            f"{event.summary_pl}\n\n"
            f"⚠️ Odpowiedz kodem aby potwierdzić odbiór alertu:\n\n"
            f"👉 {code_str}\n\n"
            f"Telefon będzie dzwonił dopóki nie potwierdzisz."
        )
        record = self.twilio.send_whatsapp(phone_number, message, event.id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.logger.info(
                "WhatsApp confirmation request sent for event %s user %s (code=%s)",
                event.id[:8],
                user.id[:8],
                code_str,
            )

    def _check_whatsapp_confirmation(
        self, since: datetime, user: User, event: Event
    ) -> bool:
        """Check if the user replied with the correct 6-digit code on WhatsApp.

        Looks up the active confirmation code from the DB instead of an
        instance variable. On match, marks the code as used.
        """
        phone_number = user.phone_number
        conf_code = self.db.get_active_confirmation_code(user.id, event.id)
        if conf_code is None:
            return False

        try:
            messages = self.twilio.client.messages.list(
                to=self.twilio.twilio_whatsapp,
                from_=f"whatsapp:{phone_number}",
                date_sent_after=since,
                limit=10,
            )
            for msg in messages:
                body = msg.body.strip() if msg.body else ""
                if conf_code.code in body:
                    self.db.mark_confirmation_code_used(conf_code.id)
                    self.logger.info(
                        "WhatsApp confirmation received (code=%s) from user %s",
                        conf_code.code,
                        user.id[:8],
                    )
                    return True
        except Exception as exc:
            self.logger.warning("Failed to check WhatsApp confirmations: %s", exc)
        return False

    def _wait_for_call_and_check_whatsapp(
        self,
        record: AlertRecord,
        whatsapp_since: datetime,
        user: User,
        event: Event,
    ) -> None:
        """Wait for a call to finish, checking WhatsApp confirmation in the meantime."""
        max_wait = 90
        poll_interval = 5
        waited = 0

        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval

            # Check WhatsApp while call is in progress
            if self._check_whatsapp_confirmation(whatsapp_since, user, event):
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

    def _execute_sms(self, event: Event, user: User) -> None:
        """Send an SMS alert."""
        phone_number = user.phone_number
        message = _format_sms_message(event, self.db, self.config)

        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="sms_sent")

    def _execute_whatsapp(self, event: Event, user: User) -> None:
        """Send a WhatsApp alert."""
        phone_number = user.phone_number
        message = _format_sms_message(event, self.db, self.config)

        record = self.twilio.send_whatsapp(phone_number, message, event.id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="whatsapp_sent")

    def _handle_call_result(
        self, record: AlertRecord, status: dict, user: User | None = None
    ) -> None:
        """Handle the result of a previously placed phone call.

        If the call was answered (duration > threshold), mark as acknowledged.
        Otherwise, retry or fall back to SMS.
        """
        call_status = status["status"]
        duration = status["duration"]
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
            if user is not None:
                self._send_followup_sms(record.event_id, user)
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

    def _send_followup_sms(self, event_id: str, user: User) -> None:
        """Send a follow-up SMS after a call is acknowledged."""
        event = self.db.get_event_by_id(event_id)
        if event is None:
            return

        phone_number = user.phone_number
        message = _format_sms_message(event, self.db, self.config)
        record = self.twilio.send_sms(phone_number, message, event_id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)

        # Also send WhatsApp with clickable article links
        self._send_article_links_whatsapp(event, user)

    def _send_article_links_whatsapp(self, event: Event, user: User) -> None:
        """Send a WhatsApp message with links to the source articles."""
        phone_number = user.phone_number
        message = _format_article_links_message(event, self.db)

        record = self.twilio.send_whatsapp(phone_number, message, event.id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.logger.info(
                "Article links WhatsApp sent for event %s user %s",
                event.id[:8],
                user.id[:8],
            )

    def _send_update_sms(self, event: Event, user: User) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        phone_number = user.phone_number
        message = _format_update_sms(event, self.db, self.config)
        record = self.twilio.send_sms(phone_number, message, event.id)
        if record is not None:
            record.user_id = user.id
            self.db.insert_alert_record(record)
            self.logger.info(
                "Update SMS sent for acknowledged event %s user %s",
                event.id[:8],
                user.id[:8],
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
