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
    "debris_found": "Znalezione szczątki",
    "official_statement": "Oświadczenie oficjalne",
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

# Maximum number of summary characters embedded in the *visible* push `body`
# (1.3b). The notification banner only needs a short snippet; capping it here
# keeps the TOTAL Expo/APNs payload (title + body + the <=3500-byte `data` +
# aps overhead) comfortably under APNs' ~4096-byte limit, so a long-summary
# event can't push the whole message past the limit and get rejected. The cap
# is on the body only — `data.summary_pl` still carries the full, untrimmed
# summary (the inbox renders the full text from `data`, never from `body`), so
# bounding the body loses no content.
#
# Value: 80. The hard worst case is an all-emoji summary (each 🚨 is 4 UTF-8
# bytes) while `data` sits at the full 3500-byte budget. At 80 chars the body's
# summary portion is <=320 bytes; the assembled Expo message (excluding the
# per-recipient `to`) then measures ~3999 bytes — ~97 bytes under the 4096
# limit. 120 left no margin in that case (it overshot 4096), so the cap was
# lowered to 80 for comfortable headroom; for normal Polish prose the margin is
# far larger.
PUSH_BODY_SUMMARY_MAX_CHARS = 80


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
    """Format a short push notification title + body in Polish.

    The visible ``body`` embeds only a bounded snippet of ``summary_pl`` —
    head-sliced to ``PUSH_BODY_SUMMARY_MAX_CHARS`` codepoints (1.3b) so the
    total Expo/APNs payload stays under the ~4096-byte limit. The slice is on
    the Python ``str`` (never the encoded bytes), so a multibyte UTF-8 character
    is never split; a trailing ``…`` is appended only when the summary was
    actually truncated. The full untrimmed summary still travels in
    ``data.summary_pl`` (the inbox renders from ``data``, not ``body``).
    """
    event_type_pl = EVENT_TYPE_PL.get(event.event_type, event.event_type)
    title = (
        f"ℹ️ SENTINEL — aktualizacja: {event_type_pl}" if is_update else f"\U0001f6a8 PROJECT SENTINEL: {event_type_pl}"
    )
    summary = event.summary_pl or ""
    if len(summary) > PUSH_BODY_SUMMARY_MAX_CHARS:
        summary = summary[:PUSH_BODY_SUMMARY_MAX_CHARS].rstrip() + "…"
    body = f"{summary}\nPilność {event.urgency_score}/10 · źródła: {event.source_count}"
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
        # 1.1d/1.1: these two fields are typed str and default to "" in the
        # model, so this coercion is a no-op for all real data. It only hardens
        # the contract (aggressor/summary_pl are never None on the wire) against
        # a malformed Event reaching this life-safety push path.
        "aggressor": event.aggressor or "",
        "summary_pl": event.summary_pl or "",
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
    # Order rationale (DO NOT reorder): sms_body is a redundant *fallback*
    # mirror of the SMS text — it is only rendered when the structured fields
    # are missing, so it is sacrificed *before* summary_pl, which is the inbox
    # Detail screen's primary rendered content. Sacrificing summary_pl first
    # would silently shorten what the user actually reads.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "sms_body")
    # (3) Truncate summary_pl (head-slice) as the last resort.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "summary_pl")

    # No-silent-overflow guard (1.2 honesty). After all three trim stages, the
    # only remaining content is the undroppable protected scalars (message_id/
    # event_id/event_type/kind/urgency_score/affected_countries/aggressor). The
    # spec forbids dropping or truncating those, so in the (unreachable with a
    # normal UUID event id) degenerate case where they alone exceed the budget,
    # we must not ship over budget *silently*: log loudly, but still return the
    # dict unchanged so a real send is never crashed by an adversarial input.
    final_size = _data_byte_size(data)
    if final_size > PUSH_DATA_MAX_BYTES:
        logging.getLogger("sentinel.alerts.state_machine").warning(
            "Push data for event %s is %d bytes after trimming, over the %d-byte budget; "
            "protected scalars alone exceed the limit and cannot be dropped, shipping over budget.",
            event.id,
            final_size,
            PUSH_DATA_MAX_BYTES,
        )

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
        # Per-event confirmation state (1.5): keyed by event_id so a reply to one
        # event's code can never acknowledge a different event. Previously bare
        # instance attributes, which were only safe because dispatch is serialized.
        #
        # ``_confirmation_codes`` holds the latest ACTIVE (successfully-delivered)
        # code, paired with ``_confirmation_sms_sids`` for the within-round
        # delivery re-check. ``_confirmation_code_history`` accumulates EVERY code
        # successfully sent for the event across all retry rounds: each round
        # regenerates and rotates the active code, so matching only the latest
        # would drop a correct operator reply that carries an EARLIER round's code
        # (which, under the bounded retry cap 1.2, would burn a call-tier event to
        # ``failed_terminal`` despite the operator answering). ``_check_sms_confirmation``
        # matches against this whole set. ``_confirmation_window_start`` pins the
        # earliest instant from which to scan for the event's replies — the first
        # round's placement — so a reply that lands in the gap between rounds
        # (before the current round's ``call_placed_at``) is not excluded on the
        # timestamp axis either. Codes are per-event, so widening the scan window
        # can never let one event's reply acknowledge a different event.
        self._confirmation_codes: dict[str, str] = {}
        self._confirmation_code_history: dict[str, set[str]] = {}
        self._confirmation_sms_sids: dict[str, str] = {}
        self._confirmation_window_start: dict[str, datetime] = {}
        # Per-event post-cap fallback throttle state: the wall-clock time of the
        # last capped-fallback SMS/push and the event's source_count at that
        # moment. The corroborator re-dispatches a failed_terminal event on EVERY
        # merged article — including non-independent syndicated copies — so an
        # unthrottled _send_capped_fallback would fire an SMS + dedup-bypassing
        # push on each cycle a syndicated copy re-merges. These let the fallback
        # suppress that redundant re-send while still firing for genuinely-new
        # independent corroboration (source_count grew) or once the interval
        # elapses. In-memory is sufficient: it only rate-limits within a running
        # process, and resetting on restart errs toward firing (prime directive).
        self._last_fallback_at: dict[str, datetime] = {}
        self._last_fallback_source_count: dict[str, int] = {}

    def _as_record(
        self,
        raw: AlertRecord | None,
        alert_type: str,
        event_id: str,
        message_body: str,
    ) -> AlertRecord:
        """Normalize a client send result into a concrete AlertRecord (never None).

        The Twilio/push clients now return a ``status="failed"`` record on a
        transport error (1.4). A bare ``None`` can still arrive (a legacy/unexpected
        return) — turn it into a synthesized failure record so the failure is
        always durably recordable and never a silent drop (1.1/1.3).
        """
        if raw is not None:
            return raw
        return AlertRecord(
            event_id=event_id,
            alert_type=alert_type,
            twilio_sid="",
            status="failed",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=message_body,
            error_code="unknown",
            error_detail="alert client returned no result",
        )

    async def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event.

        A ``failed_terminal`` event is NOT blanket-skipped here: the bounded
        retry cap (1.2) terminates only the phone-call channel. Once that cap is
        exhausted the call channel is dead, so a call-tier event with new merged
        content is routed to the SMS + dedup-bypassing push fallback
        (``_send_capped_fallback``) instead of being fully silenced — otherwise a
        post-cap escalation would produce zero perceivable output (no call by the
        cap, no SMS because the ``phone_call`` action carries none, no push once
        any earlier push succeeded). Prime directive: fail toward firing, never
        toward suppression.
        """
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

        # Post-cap fallback (prime directive): a call-tier event whose phone-retry
        # cap (1.2) is already exhausted has a dead call channel. New content that
        # merged into it must still reach the user via SMS + a dedup-bypassing
        # push, or a post-cap escalation is fully silenced (call suppressed by the
        # cap; the phone_call action carries no SMS; the push self-dedups on any
        # prior successful push). This never re-opens the spec-mandated call cap.
        if action == "phone_call" and self._call_cap_reached(event):
            await self._send_capped_fallback(event, existing_alerts)
            return

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

        Called on each scheduler cycle. After polling in-flight calls it runs the
        cycle-driven retry sweep (1.3) so a fully-failed round — which leaves no
        in-flight call record for the poll above to pick up — is still retried
        every cycle, not only when a new article happens to merge into the event.
        """
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            status = await asyncio.to_thread(self.twilio.get_call_status, record.twilio_sid)
            if status is not None:
                await self._handle_call_result(record, status)

        await self.retry_pending_calls()

    # Event alert_status values the cycle-driven sweep re-enters. Beyond the
    # normal ``retry_pending`` (a completed-but-unacknowledged round), it also
    # RECOVERS events stranded mid-round by a crash/restart:
    #   * ``call_placed`` — a call was placed, then the process died before the
    #     round-end transition to ``retry_pending``; its call record was already
    #     resolved to a terminal status by ``_wait_for_call_and_check_sms``, so the
    #     poll (``get_pending_call_records`` needs ``initiated``/``ringing``) finds
    #     nothing.
    #   * ``phone_call`` — the corroborator's initial call-tier status, entered but
    #     crashed before any call landed.
    # Neither leaves an in-flight record for the poll, and a single-source
    # urgency-9 event attracts no further merging article to re-dispatch it via
    # ``process_event`` — so without sweeping these it is silently stranded and
    # never retried, a fail-silent 9-10 miss the prime directive forbids.
    _RETRY_SWEEP_STATUSES = ("retry_pending", "call_placed", "phone_call")

    async def retry_pending_calls(self) -> None:
        """Re-enter the bounded phone-retry loop for events awaiting a call round.

        A phone-call round that completes without acknowledgment leaves the event
        in ``alert_status="retry_pending"`` (``_execute_phone_call`` /
        ``_handle_call_result``) but produces no ``initiated``/``ringing`` call
        record, so ``check_pending_calls``'s poll — which only sees in-flight
        calls — never re-touches it. The sweep also recovers events stranded
        mid-round by a crash/restart (``call_placed`` / ``phone_call`` — see
        ``_RETRY_SWEEP_STATUSES``), which likewise have no in-flight record for the
        poll. Without this cycle-driven sweep such a round would be retried only if
        a NEW article merged into the event: a single-source urgency-9 event whose
        call round fails at transport (or whose process crashed mid-round) would be
        durably recorded (1.1) yet never retried (1.3 — fail-loud, never
        fail-silent). This drives each such event back through
        ``_execute_phone_call`` every cycle, where the durable ``alert_round_count``
        enforces the ``max_rounds`` cap (1.2) and moves the event to
        ``failed_terminal`` once exhausted. The per-event ``retry_interval_minutes``
        gate inside ``_execute_phone_call`` still spaces out the rounds.

        The sweep is a second dispatch path into ``_execute_phone_call``, so it
        must honor the same guards ``process_event`` applies:
          * dry-run — a ``--dry-run`` cycle must place NO real call/SMS. Without
            this gate the sweep would fire real Twilio calls for any DB
            ``retry_pending`` row (e.g. an unacknowledged ``--test-alert``),
            breaking the run-locally-by-default contract.
          * recency — bounded by ``alerts.retry.sweep_max_age_minutes`` so a stale
            row does not restart phone rounds on deploy.
          * acknowledged / cooldown — an event that was acknowledged (or is in its
            post-ack cooldown) is never re-called, preserving one-call-per-event.
          * in-flight call — an event whose call record is still
            ``initiated``/``ringing`` is owned by the poll above; re-entering it
            here would place a SECOND concurrent call, so it is skipped (this
            matters once ``call_placed`` is swept — the crash may have happened
            while the call was still live).
        """
        if self.config.testing.dry_run:
            return

        window = self.config.alerts.retry.sweep_max_age_minutes
        for status in self._RETRY_SWEEP_STATUSES:
            for event in self.db.get_events_by_alert_status(status, within_minutes=window):
                if self._is_in_cooldown(event):
                    continue
                existing_alerts = self.db.get_alert_records(event.id)
                if self._is_acknowledged(existing_alerts):
                    continue
                if any(a.alert_type == "phone_call" and a.status in ("initiated", "ringing") for a in existing_alerts):
                    continue
                await self._execute_phone_call(event, existing_alerts)

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
        """True if any prior *delivered* alert that the user can perceive exists.

        Failed sends don't count — a call/SMS that never left Twilio hasn't
        notified anyone, so it must not suppress a fallback notification.
        """
        return any(a.alert_type in self._USER_NOTIFIED_ALERT_TYPES and a.status != "failed" for a in alerts)

    def _is_acknowledged(self, alerts: list[AlertRecord]) -> bool:
        """Check if any alert for this event was acknowledged."""
        return any(a.status == "acknowledged" for a in alerts)

    def _last_alert_time(self, alerts: list[AlertRecord]) -> datetime:
        """Return the sent_at time of the most recent alert."""
        if not alerts:
            return datetime.min.replace(tzinfo=UTC)
        return max(a.sent_at for a in alerts)

    def _mark_failed_terminal(self, event: Event) -> None:
        """Move an event to the terminal ``failed_terminal`` status (idempotent).

        Called once the durable retry-round counter reaches
        ``alerts.retry.max_rounds`` (1.2). Fail-loud: logs an error so an
        exhausted life-safety call channel leaves a durable, visible trace instead
        of a silent drop. Reached from both re-entry paths — ``_execute_phone_call``
        (the retry sweep) and ``_send_capped_fallback`` (a new-content dispatch) —
        so the transition is consistent whichever path observes the cap first.
        """
        current = self.db.get_event_by_id(event.id) or event
        if current.alert_status != "failed_terminal":
            self.db.update_event(event.id, alert_status="failed_terminal")
            self.logger.error(
                "Event %s: %d retry rounds exhausted, marking failed_terminal (fail-loud, no silent drop)",
                event.id[:8],
                self.config.alerts.retry.max_rounds,
            )

    def _call_cap_reached(self, event: Event) -> bool:
        """True when the phone-call retry cap (1.2) is exhausted for this event.

        Reads the durable round counter from the DB (survives restarts). Catches
        both the already-terminal state and the transition entry where the counter
        has reached the cap but the status has not yet been flipped, so a
        new-content dispatch routes to the fallback instead of calling
        ``_execute_phone_call``, which would refuse the call anyway.
        """
        max_rounds = self.config.alerts.retry.max_rounds
        current = self.db.get_event_by_id(event.id) or event
        return current.alert_status == "failed_terminal" or current.alert_round_count >= max_rounds

    def _fallback_throttled(self, event: Event) -> bool:
        """True when a capped-fallback SMS/push for this event should be suppressed.

        The corroborator re-dispatches a ``failed_terminal`` event on EVERY merged
        article — including non-independent syndicated copies that add no new
        information — so an unthrottled fallback would fire an SMS + dedup-bypassing
        push on each cycle a syndicated copy re-merges (a "don't spam" violation).
        A fallback is allowed when ANY of:
          * it is the first fallback for this event (never rate-limit the first
            post-cap notification);
          * genuinely-new independent corroboration arrived — the event's
            ``source_count`` grew since the last fallback (prime directive: new
            escalation content must still reach the user, even inside the window);
          * the throttle interval has elapsed since the last fallback.
        Otherwise (a syndicated re-merge inside the interval, no new independent
        source) it is suppressed. The interval reuses
        ``acknowledgment.retry_interval_minutes`` — the same cadence that spaces the
        pre-cap call rounds — so the post-cap fallback re-contacts at most that
        often. A value of 0 disables the throttle (every dispatch fires).
        """
        last_at = self._last_fallback_at.get(event.id)
        if last_at is None:
            return False
        if event.source_count > self._last_fallback_source_count.get(event.id, 0):
            return False
        window = timedelta(minutes=self.config.alerts.acknowledgment.retry_interval_minutes)
        return datetime.now(UTC) < last_at + window

    async def _send_capped_fallback(self, event: Event, existing_alerts: list[AlertRecord]) -> None:
        """Deliver new content on a call-capped event via SMS + a dedup-bypassing push.

        Once the phone-call retry cap (1.2) is exhausted the call channel is dead,
        so a fresh escalation/corroboration merged into the event would otherwise
        be fully silenced. This fires an additive push (``is_update=True`` bypasses
        the prior-push dedup so it shows even when an earlier push succeeded) and
        an SMS, without re-opening the spec-mandated call cap. The SMS is sent
        directly (not via ``_execute_sms``) so it does not overwrite the
        ``failed_terminal`` status. Ensures the event is marked terminal first so
        the state is consistent no matter which path first observes the cap.

        The SMS/push sends are throttled (``_fallback_throttled``) so a
        syndicated copy re-merging every cycle does not re-spam the user, while a
        genuinely-new independent escalation still gets through. The terminal-state
        transition is applied regardless of the throttle so the event's state stays
        consistent whichever path first observes the cap.
        """
        self._mark_failed_terminal(event)
        if self._fallback_throttled(event):
            self.logger.debug(
                "Event %s: capped fallback throttled (no new independent source within interval)",
                event.id[:8],
            )
            return
        self.logger.warning(
            "Event %s: phone-call cap exhausted (failed_terminal); routing new content to SMS + push fallback",
            event.id[:8],
        )
        # Additive push, bypassing the prior-push dedup so a post-cap escalation is
        # visible even when an earlier push already succeeded.
        await self._maybe_send_push(event, existing_alerts, is_update=True)

        # SMS fallback for the dead call channel. Sent directly so the
        # failed_terminal status is preserved (unlike _execute_sms, which flips it).
        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)
        record = self._as_record(
            await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id),
            "sms",
            event.id,
            message,
        )
        self.db.insert_alert_record(record)
        if record.status == "failed":
            self.logger.error(
                "Event %s: post-cap fallback SMS failed to send (error_code=%s)",
                event.id[:8],
                record.error_code,
            )

        # Record the throttle checkpoint so the next syndicated re-merge inside the
        # interval (with no new independent source) is suppressed instead of
        # re-firing an SMS + push.
        self._last_fallback_at[event.id] = datetime.now(UTC)
        self._last_fallback_source_count[event.id] = event.source_count

    async def _execute_phone_call(self, event: Event, existing_alerts: list[AlertRecord] | None = None) -> None:
        """Place a phone call alert with aggressive immediate retries.

        Calls up to max_call_retries times in a tight loop, polling Twilio
        for call status between attempts. If the entire round completes without
        an SMS acknowledgment, sets status to retry_pending so the next pipeline
        cycle triggers another round.

        Retry-cap semantics (1.2): the durable ``alert_round_count`` counter is
        incremented exactly once per completed-but-unacknowledged round, whatever
        the transport outcome — a full transport outage (Twilio accepted no call),
        a carrier-fault round (a call was accepted but ended in a terminal Twilio
        failure), and a delivered-but-never-answered round all count the same. At
        ``alerts.retry.max_rounds`` the event moves to ``failed_terminal`` and
        stops re-entering the retry loop, so no failure mode can loop forever. An
        acknowledged round returns before the increment and never counts.
        """
        if existing_alerts is None:
            existing_alerts = self.db.get_alert_records(event.id)

        # Bounded cross-cycle retry rounds (1.2). Read the durable round counter
        # from the DB so the cap survives restarts and is never trusted from a
        # possibly-stale event argument. When it reaches the config cap, the event
        # moves to a terminal failed status and stops re-entering the retry loop.
        max_rounds = self.config.alerts.retry.max_rounds
        current = self.db.get_event_by_id(event.id) or event
        if current.alert_round_count >= max_rounds:
            # Before burning a call-tier event to a terminal failed status, honor a
            # correct operator reply that may have landed after the previous
            # round's final SMS check and before this cap-exhausting re-entry. The
            # scan reads from the event's window start against EVERY code sent for
            # it, so a reply carrying an earlier round's rotated code still matches;
            # without this, a timely acknowledgment on the exhausting round is
            # silently lost and the event is wrongly marked failed_terminal.
            if await self._check_sms_confirmation(datetime.now(UTC), event.id):
                await self._acknowledge_event(event, current.alert_round_count)
                return
            self._mark_failed_terminal(event)
            return

        # Enforce the retry interval by the last call ATTEMPT time regardless of
        # transport outcome — INCLUDING transport-failed rounds. During a full
        # Twilio outage every phone_call record is status="failed"; if those did
        # not count toward spacing, no interval would apply and the rounds would
        # burn back-to-back — a dispatch round plus the same-cycle retry sweep,
        # then one round per fast-lane cycle — exhausting the max_rounds cap in
        # minutes instead of spanning retry_interval_minutes * max_rounds. Spacing
        # by every round's attempt time makes the cap span the configured window
        # even during an outage AND stops dispatch and the sweep from both
        # advancing a round for one event within a single cycle.
        phone_records = [a for a in existing_alerts if a.alert_type == "phone_call"]
        if phone_records:
            last_call_time = max(a.sent_at for a in phone_records)
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
        # total_attempts numbers delivered attempts for logging / attempt_number;
        # transport-failed placements are excluded so the number tracks calls that
        # actually left Twilio (the spacing anchor above already counts failures).
        total_attempts = len([a for a in phone_records if a.status != "failed"])
        call_placed_at = datetime.now(UTC)
        # Pin the confirmation-scan window to the FIRST round's placement so a
        # reply carrying an earlier round's code — which lands in the gap between
        # rounds and predates this round's ``call_placed_at`` — is still inside the
        # queried window. Later rounds keep the original start (setdefault).
        self._confirmation_window_start.setdefault(event.id, call_placed_at)

        # Send SMS confirmation code — this is the ONLY confirmation mechanism
        await self._send_confirmation_sms(event)

        retry_pause = self.config.alerts.acknowledgment.call_retry_pause_seconds

        # Call loop — calls are alarms only, not confirmation
        for attempt in range(1, max_per_round + 1):
            # Check SMS reply before each call
            if await self._check_sms_confirmation(call_placed_at, event.id):
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

            record = self._as_record(
                await asyncio.to_thread(self.twilio.make_alert_call, phone_number, message, event.id),
                "phone_call",
                event.id,
                message,
            )
            record.attempt_number = total_attempts
            if record.status == "failed":
                # Fail-loud (1.1/1.3): persist a durable failure row with the
                # transport error code instead of a bare log line + zero rows.
                self.db.insert_alert_record(record)
                self.logger.error(
                    "Event %s: Twilio call failed to initiate (error_code=%s)",
                    event.id[:8],
                    record.error_code,
                )
                continue

            self.db.insert_alert_record(record)
            self.db.update_event(event.id, alert_status="call_placed")

            # Wait for call to finish, polling SMS in the meantime
            await self._wait_for_call_and_check_sms(record, call_placed_at)

            # Check SMS reply after call ends
            if await self._check_sms_confirmation(call_placed_at, event.id):
                await self._acknowledge_event(event, total_attempts)
                return

            # After first call, verify confirmation SMS was delivered; resend if failed
            if attempt == 1:
                delivery = await self._check_confirmation_sms_delivered(event.id)
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
        if await self._check_sms_confirmation(call_placed_at, event.id):
            await self._acknowledge_event(event, total_attempts)
            return

        # Advance the durable retry counter (1.2) once for this completed-but-
        # unacknowledged round, whatever the transport outcome — a transport
        # outage, a carrier-fault round (call accepted then ended 'failed'), and a
        # delivered-but-never-answered round all count the same, so no failure
        # mode loops forever. An acknowledged round returns above and never reaches
        # here. The next entry sees the cap and moves the event to failed_terminal.
        self.db.update_event(event.id, alert_round_count=current.alert_round_count + 1)
        self.logger.warning(
            "Event %s: round complete without SMS confirmation, round count now %d/%d, retry in %d min",
            event.id[:8],
            current.alert_round_count + 1,
            max_rounds,
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
        # Resolve any still-in-flight call record for this event. An SMS ack can
        # arrive while a call is 'initiated'/'ringing'; if that record is left
        # in-flight, the next cycle's poll (get_pending_call_records) re-touches it
        # and _handle_call_result would knock the just-acknowledged event back to
        # retry_pending, which the retry sweep then turns into a SECOND call on an
        # already-acknowledged event. Marking it 'acknowledged' removes it from the
        # pending poll so one-call-per-event holds.
        for rec in self.db.get_alert_records(event.id):
            if rec.alert_type == "phone_call" and rec.status in ("initiated", "ringing"):
                self.db.update_alert_record(rec.id, status="acknowledged")
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

        # Generate a candidate 6-digit code, but only register it (as the active
        # code, in the matchable history set, and paired with its SID) once the SMS
        # actually leaves Twilio. A failed send must NOT register a code the
        # operator never received. Every successfully-sent code stays matchable
        # across rounds (see ``_check_sms_confirmation``), so a correct reply
        # carrying any earlier round's code still acknowledges instead of being
        # lost when the per-round code rotates — which, under the bounded retry cap
        # (1.2), would otherwise burn a call-tier event to failed_terminal despite
        # the operator answering. The recorded SID tracks the latest confirmation
        # SMS for the within-round delivery re-check. Stored per-event (1.5) so a
        # reply to one event's code can never acknowledge a different event.
        code = f"{random.randint(100000, 999999)}"

        message = (
            f"PROJECT SENTINEL: {event_type_pl}\n\n"
            f"{event.summary_pl}\n\n"
            f"Odpowiedz kodem aby potwierdzic odbior alertu: {code}\n\n"
            f"Telefon bedzie dzwonil dopoki nie potwierdzisz."
        )
        record = self._as_record(
            await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id),
            "sms",
            event.id,
            message,
        )
        self.db.insert_alert_record(record)
        if record.status != "failed":
            self._confirmation_codes[event.id] = code
            self._confirmation_code_history.setdefault(event.id, set()).add(code)
            self._confirmation_sms_sids[event.id] = record.twilio_sid
            self.logger.info(
                "SMS confirmation request sent for event %s (code=%s, SID=%s)",
                event.id[:8],
                code,
                record.twilio_sid,
            )
        else:
            self.logger.error(
                "Event %s: confirmation SMS failed to send (error_code=%s); keeping prior delivered code active",
                event.id[:8],
                record.error_code,
            )

    async def _check_sms_confirmation(self, since: datetime, event_id: str) -> bool:
        """Check if the user replied with a valid confirmation code for this event.

        Matches against EVERY code sent for the event (across all retry rounds),
        not only the latest: the per-round confirmation SMS rotates the active
        code, so matching only the newest would drop a correct reply that carries
        an earlier round's code and, under the bounded cap (1.2), wrongly burn the
        event to ``failed_terminal``.

        The scan window is widened to the event's first-round placement
        (``_confirmation_window_start``) whenever that predates ``since``: a reply
        arriving in the gap between rounds is sent BEFORE the current round's
        ``call_placed_at``, so filtering only by the current ``since`` would exclude
        it on the timestamp axis. Codes are per-event, so widening the window can
        never acknowledge a different event.
        """
        phone_number = self.config.alerts.phone_number
        codes = self._confirmation_code_history.get(event_id)
        if not codes:
            return False

        window_start = self._confirmation_window_start.get(event_id)
        effective_since = min(since, window_start) if window_start is not None else since

        try:
            # Check inbound SMS from the user's phone to our Twilio number.
            # The synchronous Twilio SDK call is offloaded to a thread so it does
            # not block the event loop; the kwargs are passed via a lambda.
            messages = await asyncio.to_thread(
                lambda: self.twilio.client.messages.list(
                    to=self.twilio.twilio_phone,
                    from_=phone_number,
                    date_sent_after=effective_since,
                    limit=10,
                )
            )
            for msg in messages:
                body = msg.body.strip() if msg.body else ""
                matched = next((code for code in codes if code in body), None)
                if matched is not None:
                    self.logger.info(
                        "SMS confirmation received (code=%s) from %s",
                        matched,
                        phone_number,
                    )
                    return True
        except Exception as exc:
            self.logger.warning("Failed to check SMS confirmations: %s", exc)
        return False

    async def _check_confirmation_sms_delivered(self, event_id: str) -> bool | None:
        """Check if this event's confirmation SMS was delivered.

        Returns True if delivered, False if failed/undelivered, None if still pending.
        """
        sid = self._confirmation_sms_sids.get(event_id)
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
            if await self._check_sms_confirmation(sms_since, record.event_id):
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

        record = self._as_record(
            await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id),
            "sms",
            event.id,
            message,
        )
        self.db.insert_alert_record(record)
        if record.status != "failed":
            self.db.update_event(event.id, alert_status="sms_sent")
        else:
            self.logger.error("Event %s: SMS alert failed to send (error_code=%s)", event.id[:8], record.error_code)

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
            # Retry logic is handled by process_event / the retry sweep on the next
            # cycle. Do NOT re-arm retry_pending if the event has already been
            # resolved between placing the call and this poll: an SMS ack may have
            # marked it 'acknowledged' (its confirmation resolves out-of-band), or
            # the round cap may have moved it to 'failed_terminal'. Overwriting
            # either back to retry_pending would re-enter the retry sweep and place
            # a SECOND call on an already-acknowledged event (breaking
            # one-call-per-event) or re-open the exhausted cap.
            current = self.db.get_event_by_id(record.event_id)
            if current is not None and (
                current.acknowledged_at is not None or current.alert_status in ("acknowledged", "failed_terminal")
            ):
                return
            self.db.update_event(record.event_id, alert_status="retry_pending")
        # If still in-progress/queued/ringing, leave as-is

    async def _send_followup_sms(self, event_id: str) -> None:
        """Send a follow-up SMS after a call is acknowledged."""
        event = self.db.get_event_by_id(event_id)
        if event is None:
            return

        phone_number = self.config.alerts.phone_number
        message = _format_sms_message(event, self.db, self.config)
        record = self._as_record(
            await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event_id),
            "sms",
            event_id,
            message,
        )
        self.db.insert_alert_record(record)
        if record.status == "failed":
            self.logger.error("Event %s: follow-up SMS failed to send (error_code=%s)", event_id[:8], record.error_code)

    async def _send_update_sms(self, event: Event) -> None:
        """Send an SMS update for an event that was already acknowledged."""
        phone_number = self.config.alerts.phone_number
        message = _format_update_sms(event, self.db, self.config)
        record = self._as_record(
            await asyncio.to_thread(self.twilio.send_sms, phone_number, message, event.id),
            "sms",
            event.id,
            message,
        )
        self.db.insert_alert_record(record)
        if record.status != "failed":
            self.logger.info("Update SMS sent for acknowledged event %s", event.id)
        else:
            self.logger.error("Event %s: update SMS failed to send (error_code=%s)", event.id[:8], record.error_code)

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
        # Dedup only on a *successful* prior push — a failed push must not
        # suppress a later retry.
        if not is_update and any(a.alert_type == "push" and a.status != "failed" for a in existing_alerts):
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
        # None is the no-op case (push disabled / no tokens) — nothing to record.
        # A transport failure now returns a status="failed" record, persisted
        # like a success so a failed push is never a silent drop (1.1/1.3).
        if record is None:
            return
        self.db.insert_alert_record(record)
        if record.status != "failed":
            self.logger.info("Push alert recorded for event %s", event.id[:8])
        else:
            self.logger.error("Event %s: push failed to send (error_code=%s)", event.id[:8], record.error_code)

    def _update_alert_record(
        self,
        record: AlertRecord,
        status: str,
        duration_seconds: int | None = None,
    ) -> None:
        """Update an existing alert record's status and duration in the DB."""
        self.db.update_alert_record(record.id, status=status, duration_seconds=duration_seconds)
