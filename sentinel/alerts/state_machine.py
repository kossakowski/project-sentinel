import asyncio
import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import AlertRecord, Event
from sentinel.utils.datetime import format_warsaw

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

# Twilio rejects a concatenated SMS body over 1600 characters. Cap below that
# with a margin; the source list is trimmed to fit so heavily-corroborated
# events (many long Google News redirect URLs) don't blow past the limit and
# silently fail to send.
SMS_MAX_CHARS = 1500

# Bound the (otherwise unbounded) classifier summary so the fixed template
# overhead can never alone exceed SMS_MAX_CHARS and re-trigger Twilio's
# rejection, while leaving real budget for the source list. summary_pl is
# prompted for "1-2 zdania" upstream but is not capped anywhere.
SMS_SUMMARY_MAX_CHARS = 600

# Reserve room for the "- …i N więcej" trailer when trimming sources.
_SOURCES_TRAILER_RESERVE = 40

# Maximum serialized size of the push `data` dict, in UTF-8 bytes. APNs caps the
# whole notification payload at ~4096 bytes; this budget reserves headroom for
# the visible title/body and the aps overhead. `data` is measured with
# json.dumps(..., ensure_ascii=False) so Polish letters and emoji count as their
# real wire bytes, not as 6-char ASCII escapes. The builder trims its content
# (sources -> sms_body -> summary_pl) to stay within this limit.
PUSH_DATA_MAX_BYTES = 3500


def _build_sources_list(event: Event, db: Database, max_chars: int | None = None) -> str:
    """Build a formatted source list from event article_ids.

    Looks up each article in the database to get source_name, title,
    and source_url.  Each source is rendered as a title line followed
    by a clickable URL line so the recipient can immediately verify
    the article.

    When ``max_chars`` is given the list is bounded to that budget: as many
    whole source entries as fit are included, then a "- …i N innych źródeł"
    trailer accounts for the omitted ones. This keeps the SMS body under
    Twilio's limit even when an event carries many long URLs.
    """
    entries: list[str] = []
    for article_id in event.article_ids:
        article = db.get_article_by_id(article_id)
        if article is not None:
            entry = f"- {article.source_name}: {article.title}"
            if article.source_url:
                entry += f"\n  {article.source_url}"
            entries.append(entry)
        else:
            entries.append(f"- (źródło {article_id[:8]})")

    if not entries:
        return f"- {event.source_count} źródeł"

    if max_chars is None:
        return "\n".join(entries)

    full = "\n".join(entries)
    if len(full) <= max_chars:
        return full

    # Greedily include whole entries within budget, leaving room for the trailer.
    budget = max(0, max_chars - _SOURCES_TRAILER_RESERVE)
    included: list[str] = []
    used = 0
    for entry in entries:
        add_cost = len(entry) + (1 if included else 0)  # +1 for the joining newline
        if used + add_cost > budget:
            break
        included.append(entry)
        used += add_cost

    omitted = len(entries) - len(included)
    body = "\n".join(included)
    if omitted > 0:
        trailer = f"- …i {omitted} więcej"
        body = f"{body}\n{trailer}" if body else trailer
    # Hard clamp as a final guarantee (e.g. a single oversized entry).
    return body[:max_chars]


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
    first_seen_local = format_warsaw(event.first_seen_at)
    template = config.alerts.templates.sms

    # Bound the otherwise-unbounded classifier summary so fixed template overhead
    # can never alone exceed the budget and re-trigger Twilio's 1600-char
    # rejection. Truncating the summary -- not the rendered body -- preserves
    # trailing template fields like "Wykryto: {first_seen_at_local}".
    summary_pl = event.summary_pl
    if len(summary_pl) > SMS_SUMMARY_MAX_CHARS:
        summary_pl = summary_pl[: SMS_SUMMARY_MAX_CHARS - 1].rstrip() + "…"

    fields = {
        "event_type_pl": event_type_pl,
        "urgency_score": event.urgency_score,
        "affected_countries_str": countries_str,
        "aggressor": event.aggressor,
        "summary_pl": summary_pl,
        "source_count": event.source_count,
        "first_seen_at_local": first_seen_local,
    }

    # Measure the fixed overhead (template with an empty source list), then bound
    # the source list to the remaining budget so the whole body stays under
    # Twilio's limit. Long Google News URLs used to push corroborated events past
    # it, failing the send entirely.
    overhead = len(template.format(sources_list="", **fields))
    sources_list = _build_sources_list(event, db, max_chars=max(0, SMS_MAX_CHARS - overhead))
    return template.format(sources_list=sources_list, **fields)


def _format_update_sms(event: Event, db: Database, config: SentinelConfig) -> str:
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


def _format_push(event: Event, is_update: bool = False) -> tuple[str, str]:
    """Format a short push notification title + body in Polish."""
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    title = (
        f"ℹ️ SENTINEL — aktualizacja: {event_type_pl}" if is_update else f"\U0001f6a8 PROJECT SENTINEL: {event_type_pl}"
    )
    body = f"{event.summary_pl}\nPilność {event.urgency_score}/10 · źródła: {event.source_count}"
    return title, body


def _build_sources_payload(event: Event, db: Database) -> list[dict]:
    """Build the structured source list carried inside the push ``data`` dict.

    Mirrors the article ordering of ``_build_sources_list`` (the SMS string
    builder): iterates ``event.article_ids`` in order and looks each one up via
    ``db.get_article_by_id``. Each item is ``{"name", "title", "url"}`` where
    ``url`` is the article's ``source_url`` or ``None`` when absent/falsy. An
    article id that misses the DB lookup yields a placeholder entry mirroring the
    SMS ``- (źródło {id[:8]})`` fallback, so the count stays consistent and the
    builder never crashes.
    """
    sources: list[dict] = []
    for article_id in event.article_ids:
        article = db.get_article_by_id(article_id)
        if article is not None:
            sources.append(
                {
                    "name": article.source_name,
                    "title": article.title,
                    "url": article.source_url if article.source_url else None,
                }
            )
        else:
            sources.append(
                {
                    "name": "źródło",
                    "title": f"(źródło {article_id[:8]})",
                    "url": None,
                }
            )
    return sources


def _data_byte_size(data: dict) -> int:
    """Serialized UTF-8 byte size of the push ``data`` dict (the 1.2 budget metric)."""
    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _truncate_to_byte_budget(data: dict, field: str) -> None:
    """Codepoint-safe head-truncate ``data[field]`` until the whole dict fits.

    Slices the Python ``str`` by characters (never by encoded bytes, so a
    multibyte UTF-8 character is never split) and re-measures the entire
    serialized ``data`` after each shrink, since JSON escaping plus the rest of
    the dict count toward ``PUSH_DATA_MAX_BYTES``. A trailing ``…`` is appended
    when content is dropped. Binary-searches the codepoint length for speed.
    """
    text = data[field]
    if not text or _data_byte_size(data) <= PUSH_DATA_MAX_BYTES:
        return

    ellipsis = "…"

    def fits(n: int) -> bool:
        data[field] = (text[:n].rstrip() + ellipsis) if n > 0 else ""
        return _data_byte_size(data) <= PUSH_DATA_MAX_BYTES

    # Find the largest head length n (in codepoints) that still fits.
    lo, hi, best = 0, len(text), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    fits(best)


def _build_push_data(event: Event, db: Database, config: SentinelConfig, is_update: bool) -> dict:
    """Assemble the enriched Expo push ``data`` dict for one send (Phase 1).

    A pure, returnable builder (not inlined into the send call) so tests can
    build the dict directly. It stamps a fresh ``message_id`` per call, preserves
    the legacy scalars (``event_id``/``urgency_score``/``event_type``), carries
    the full untrimmed structured content plus ``event_type_pl``, the structured
    ``sources`` list, the UTC ISO ``first_seen_at``, and ``sms_body`` — the exact
    SMS string the server produces for this send (``_format_sms_message`` for an
    event, ``_format_update_sms`` for an update) — then trims the serialized dict
    to ``PUSH_DATA_MAX_BYTES`` (1.2): sources from the end, then ``sms_body``,
    then ``summary_pl``; the scalars and ``kind`` are never dropped or truncated.
    """
    sms_body = _format_update_sms(event, db, config) if is_update else _format_sms_message(event, db, config)

    first_seen_at = event.first_seen_at
    first_seen_at = first_seen_at.replace(tzinfo=UTC) if first_seen_at.tzinfo is None else first_seen_at.astimezone(UTC)

    data: dict = {
        "message_id": uuid.uuid4().hex,
        "event_id": event.id,
        "kind": "update" if is_update else "event",
        "event_type": event.event_type,
        "event_type_pl": EVENT_TYPE_PL.get(event.event_type, event.event_type),
        "urgency_score": event.urgency_score,
        "affected_countries": list(event.affected_countries),
        "aggressor": event.aggressor,
        "summary_pl": event.summary_pl,
        "sources": _build_sources_payload(event, db),
        "sms_body": sms_body,
        "first_seen_at": first_seen_at.isoformat(),
    }

    # Byte-budget trim (1.2), in the mandated order. message_id/event_id/
    # urgency_score/event_type/kind are never dropped or truncated.
    # (1) Drop trailing source entries one at a time until it fits.
    while data["sources"] and _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        data["sources"].pop()
    # (2) Truncate sms_body (head-slice) if still over with no sources left.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "sms_body")
    # (3) Truncate summary_pl (head-slice) as the last resort.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "summary_pl")

    return data


class AlertStateMachine:
    """Manages the lifecycle of event alerts."""

    def __init__(
        self,
        db: Database,
        twilio_client: TwilioClient,
        config: SentinelConfig,
        push_client: ExpoPushClient | None = None,
    ) -> None:
        self.db = db
        self.twilio = twilio_client
        self.config = config
        self.push = push_client or ExpoPushClient(config)
        self.logger = logging.getLogger("sentinel.alerts.state_machine")

    async def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event."""
        if self._is_in_cooldown(event):
            self.logger.debug("Event %s in cooldown, skipping", event.id)
            return

        existing_alerts = self.db.get_alert_records(event.id)

        if self._is_acknowledged(existing_alerts):
            if event.last_updated_at > self._last_alert_time(existing_alerts):
                # Acknowledged 9-10 escalation update: send the update SMS and an
                # additive Expo push (AD-3). The is_update dedup-bypass is
                # intended so each escalation update pushes the latest state.
                await self._send_update_sms(event)
                await self._maybe_send_push(event, existing_alerts, is_update=True)
            return

        # If there are pending call records (initiated but not yet resolved),
        # don't send another alert — the call check cycle will handle it
        if any(a.alert_type == "phone_call" and a.status in ("initiated", "ringing") for a in existing_alerts):
            self.logger.debug("Event %s has a pending call, skipping", event.id)
            return

        action = self._determine_action(event)
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
        send_push = action in ("push", "both", "phone_call")
        send_sms = action in ("sms", "both")

        # Existing re-alert suppression, now applied only to the SMS half: a
        # prior perceivable alert for this event suppresses a redundant re-SMS.
        # The push half is not gated by this — it self-dedups on a prior push
        # record inside _maybe_send_push.
        if send_sms and self._user_already_notified(existing_alerts):
            self.logger.debug(
                "Event %s already has prior alert; suppressing re-SMS",
                event.id,
            )
            send_sms = False

        # Push reaches the phone immediately and self-dedups on a prior push
        # record (so call-retry / re-corroboration cycles don't re-push).
        if send_push:
            await self._maybe_send_push(event, existing_alerts)

        if action == "phone_call":
            await self._execute_phone_call(event, existing_alerts)
        elif send_sms:
            await self._execute_sms(event)
        # push-only / suppressed-SMS / log_only -> no Twilio SMS

    async def check_pending_calls(self) -> None:
        """Check status of calls that were placed but not yet confirmed.

        Called on each scheduler cycle.
        """
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            status = await asyncio.to_thread(self.twilio.get_call_status, record.twilio_sid)
            if status is not None:
                await self._handle_call_result(record, status)

    def _determine_action(self, event: Event) -> str:
        """Resolve the delivery action for an event from the urgency tiers.

        Returns one of: "phone_call", "sms", "push", "both", "log_only".

        Decision matrix (from config urgency_levels):
          9-10 + 2+ sources -> phone_call          (never push/both — AD-2)
          9-10 + 1 source   -> sms                 (existing fallback)
          7-8               -> high.channel         (sms | push | both)
          5-6               -> medium.channel       (sms | push | both)
          1-4               -> log_only

        For the SMS-action tiers (5-8) the matched level's `channel` is returned
        so the operator can route that tier to SMS, push, or both. The 9-10
        phone_call path ignores `channel` entirely; log_only is returned as-is.

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

        for _level_name, level in sorted_levels:
            if score >= level.min_score:
                if level.action == "phone_call":
                    if source_count >= level.corroboration_required:
                        return "phone_call"
                    else:
                        return "sms"
                if level.action == "sms":
                    return level.channel  # "sms" | "push" | "both"
                return level.action  # e.g. "log_only"

        return "log_only"

    def _is_in_cooldown(self, event: Event) -> bool:
        """Check if the event is within the cooldown period after acknowledgment."""
        if event.acknowledged_at is None:
            return False

        cooldown_hours = self.config.alerts.acknowledgment.cooldown_hours
        cooldown_end = event.acknowledged_at + timedelta(hours=cooldown_hours)
        return datetime.now(UTC) < cooldown_end

    # Alert types that, once recorded, mean we have already notified the user
    # for this event and a further SMS would be a redundant ping.
    # A phone call counts because it ships its own confirmation SMS.
    # SMS→phone_call ESCALATION is still allowed: phone_call action skips
    # this suppression (its own retry-interval logic in _execute_phone_call
    # governs re-firing).
    _USER_NOTIFIED_ALERT_TYPES = ("sms", "whatsapp", "phone_call")

    def _user_already_notified(self, alerts: list[AlertRecord]) -> bool:
        """True if any prior alert that the user can perceive exists."""
        return any(a.alert_type in self._USER_NOTIFIED_ALERT_TYPES for a in alerts)

    def _is_acknowledged(self, alerts: list[AlertRecord]) -> bool:
        """Check if any alert for this event was acknowledged."""
        return any(a.status == "acknowledged" for a in alerts)

    def _last_alert_time(self, alerts: list[AlertRecord]) -> datetime:
        """Return the sent_at time of the most recent alert."""
        if not alerts:
            return datetime.min.replace(tzinfo=UTC)
        return max(a.sent_at for a in alerts)

    async def _execute_phone_call(self, event: Event, existing_alerts: list[AlertRecord] | None = None) -> None:
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
        call_records = [a for a in existing_alerts if a.alert_type == "phone_call"]
        if call_records:
            last_call_time = max(a.sent_at for a in call_records)
            retry_interval = timedelta(minutes=self.config.alerts.acknowledgment.retry_interval_minutes)
            if datetime.now(UTC) < last_call_time + retry_interval:
                self.logger.debug(
                    "Event %s: retry interval not elapsed, skipping call",
                    event.id,
                )
                return

        phone_number = self.config.alerts.phone_number
        message = _format_call_message(event, self.config)
        max_per_round = self.config.alerts.acknowledgment.max_call_retries
        total_attempts = len(call_records)
        call_placed_at = datetime.now(UTC)

        # Send SMS confirmation code — this is the ONLY confirmation mechanism
        await self._send_confirmation_sms(event)

        retry_pause = self.config.alerts.acknowledgment.call_retry_pause_seconds

        # Call loop — calls are alarms only, not confirmation
        for attempt in range(1, max_per_round + 1):
            # Check SMS reply before each call
            if await self._check_sms_confirmation(call_placed_at):
                await self._acknowledge_event(event, total_attempts)
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

            record = await asyncio.to_thread(self.twilio.make_alert_call, phone_number, message, event.id)
            if record is None:
                self.logger.error("Event %s: Twilio call failed to initiate", event.id[:8])
                continue

            record.attempt_number = total_attempts
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="call_placed")

            # Wait for call to finish, polling SMS in the meantime
            await self._wait_for_call_and_check_sms(record, call_placed_at)

            # Check SMS reply after call ends
            if await self._check_sms_confirmation(call_placed_at):
                await self._acknowledge_event(event, total_attempts)
                return

            # After first call, verify confirmation SMS was delivered; resend if failed
            if attempt == 1:
                delivery = await self._check_confirmation_sms_delivered()
                if delivery is False:
                    self.logger.warning(
                        "Event %s: confirmation SMS failed to deliver, resending",
                        event.id[:8],
                    )
                    await self._send_confirmation_sms(event)

            # Brief pause between retries
            if attempt < max_per_round:
                await asyncio.sleep(retry_pause)

        # Round exhausted — check SMS one more time
        if await self._check_sms_confirmation(call_placed_at):
            await self._acknowledge_event(event, total_attempts)
            return

        # Still not confirmed — mark for retry on next cycle
        self.logger.warning(
            "Event %s: %d calls this round, no SMS confirmation, retry in %d min",
            event.id[:8],
            max_per_round,
            self.config.alerts.acknowledgment.retry_interval_minutes,
        )
        self.db.update_event(event.id, alert_status="retry_pending")

    async def _acknowledge_event(self, event: Event, total_attempts: int) -> None:
        """Mark event as acknowledged and send follow-ups."""
        self.db.update_event(
            event.id,
            alert_status="acknowledged",
            acknowledged_at=datetime.now(UTC).isoformat(),
        )
        self.logger.info(
            "Event %s: confirmed via SMS after %d call attempts",
            event.id[:8],
            total_attempts,
        )
        await self._send_followup_sms(event.id)

    async def _send_confirmation_sms(self, event: Event) -> None:
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
        record = await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id)
        if record is not None:
            self._confirmation_sms_sid = record.twilio_sid
            self.db.insert_alert_record(record)
            self.logger.info(
                "SMS confirmation request sent for event %s (code=%s, SID=%s)",
                event.id[:8],
                self._confirmation_code,
                record.twilio_sid,
            )

    async def _check_sms_confirmation(self, since: datetime) -> bool:
        """Check if the user replied with the correct 6-digit code via SMS."""
        phone_number = self.config.alerts.phone_number
        code = getattr(self, "_confirmation_code", None)
        if not code:
            return False

        try:
            # Check inbound SMS from the user's phone to our Twilio number.
            # The synchronous Twilio SDK call is offloaded to a thread so it does
            # not block the event loop; the kwargs are passed via a lambda.
            messages = await asyncio.to_thread(
                lambda: self.twilio.client.messages.list(
                    to=self.twilio.twilio_phone,
                    from_=phone_number,
                    date_sent_after=since,
                    limit=10,
                )
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

    async def _check_confirmation_sms_delivered(self) -> bool | None:
        """Check if the confirmation SMS was delivered.

        Returns True if delivered, False if failed/undelivered, None if still pending.
        """
        sid = getattr(self, "_confirmation_sms_sid", None)
        if not sid:
            return None
        try:
            msg = await asyncio.to_thread(lambda: self.twilio.client.messages(sid).fetch())
            if msg.status == "delivered":
                return True
            if msg.status in ("failed", "undelivered"):
                self.logger.warning(
                    "Confirmation SMS %s status: %s (error=%s)",
                    sid,
                    msg.status,
                    msg.error_code,
                )
                return False
            return None  # still queued/sending/sent
        except Exception as exc:
            self.logger.warning("Failed to check SMS delivery status: %s", exc)
            return None

    async def _wait_for_call_and_check_sms(self, record: AlertRecord, sms_since: datetime) -> None:
        """Wait for a call to finish, checking SMS confirmation in the meantime."""
        max_wait = self.config.alerts.acknowledgment.call_poll_timeout_seconds
        poll_interval = self.config.alerts.acknowledgment.call_poll_interval_seconds
        waited = 0

        while waited < max_wait:
            await asyncio.sleep(poll_interval)
            waited += poll_interval

            # Check SMS while call is in progress
            if await self._check_sms_confirmation(sms_since):
                return

            # Check if call is done
            status = await asyncio.to_thread(self.twilio.get_call_status, record.twilio_sid)
            if status is None:
                continue

            call_status = status["status"]
            if call_status not in ("queued", "ringing", "in-progress"):
                # Call finished
                self._update_alert_record(
                    record,
                    status=call_status,
                    duration_seconds=status.get("duration", 0),
                )
                return

    async def _execute_sms(self, event: Event) -> None:
        """Send an SMS alert."""
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)

        record = await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="sms_sent")

    async def _handle_call_result(self, record: AlertRecord, status: dict) -> None:
        """Handle the result of a previously placed phone call.

        If the call was answered (duration > threshold), mark as acknowledged.
        Otherwise, retry or fall back to SMS.
        """
        call_status = status["status"]
        duration = status["duration"]
        if call_status in ("completed", "busy", "no-answer", "canceled", "failed"):
            # Call was not properly answered
            self._update_alert_record(record, status=call_status, duration_seconds=duration)
            if call_status in ("failed", "canceled"):
                self.logger.warning(
                    "Event %s call %s (duration=%ds), terminal status — moving to retry/fallback",
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
            self.db.update_event(record.event_id, alert_status="retry_pending")
        # If still in-progress/queued/ringing, leave as-is

    async def _send_followup_sms(self, event_id: str) -> None:
        """Send a follow-up SMS after a call is acknowledged."""
        event = self.db.get_event_by_id(event_id)
        if event is None:
            return

        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)
        record = await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event_id)
        if record is not None:
            self.db.insert_alert_record(record)

    async def _send_update_sms(self, event: Event) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        phone_number = self.config.alerts.phone_number
        message = _format_update_sms(event, self.db, self.config)
        record = await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id)
        if record is not None:
            self.db.insert_alert_record(record)
            self.logger.info("Update SMS sent for acknowledged event %s", event.id)

    async def _maybe_send_push(
        self,
        event: Event,
        existing_alerts: list[AlertRecord],
        is_update: bool = False,
    ) -> None:
        """Send an Expo push for the resolved channel, recording it as a 'push' alert.

        Invoked by process_event when the resolved tier channel is "push" or
        "both" (per-tier routing), additively on the 9-10 "phone_call" action
        (AD-2), and on acknowledged-event escalation updates (AD-3). No-op when
        push is disabled or no tokens are configured. The initial alert is deduped
        on the presence of a prior 'push' record so re-corroboration cycles don't
        re-push every few minutes. Updates (is_update=True) skip that dedup — the
        caller only invokes them when genuinely new corroboration arrived, and the
        new record's sent_at rate-limits the next one. The blocking HTTP POST is
        offloaded to a thread like the Twilio calls.
        """
        push_cfg = self.config.alerts.push
        if not push_cfg.enabled or not push_cfg.tokens:
            return
        if not is_update and any(a.alert_type == "push" for a in existing_alerts):
            return

        title, body = _format_push(event, is_update=is_update)
        data = _build_push_data(event, self.db, self.config, is_update)
        record = await asyncio.to_thread(
            self.push.send_push,
            title,
            body,
            event.id,
            data,
        )
        if record is not None:
            self.db.insert_alert_record(record)
            self.logger.info("Push alert recorded for event %s", event.id[:8])

    def _update_alert_record(
        self,
        record: AlertRecord,
        status: str,
        duration_seconds: int | None = None,
    ) -> None:
        """Update an existing alert record's status and duration in the DB."""
        self.db.update_alert_record(record.id, status=status, duration_seconds=duration_seconds)
