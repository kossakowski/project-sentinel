"""Polish alert texts: the call script, the SMS bodies and the Expo push payload.

These functions only build text and data; they send nothing. The database is
read only to cite the event's sources.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC

from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Article, Event
from sentinel.utils.datetime import format_warsaw

# The alert path keeps logging under the state machine's logger name, which the
# log file and the tests filter on.
logger = logging.getLogger("sentinel.alerts.state_machine")

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
    # Fallback enum values from the classifier (classifier.py) that lack a specific
    # category. Without these, event_type_pl() leaks the raw English token
    # ("other"/"none") into the push title, SMS body, and call script.
    "other": "Inny incydent",
    "none": "Brak zagrożenia",
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
# (1.3b). The banner only needs a short snippet; the cap keeps the TOTAL
# Expo/APNs payload (title + body + the <=3500-byte `data` + aps overhead)
# under APNs' ~4096-byte limit. Only the body is capped: `data.summary_pl`
# still carries the full summary, which the inbox renders.
#
# Value: 80. The hard worst case is an all-emoji summary (each 🚨 is 4 UTF-8
# bytes) while `data` sits at the full 3500-byte budget. At 80 chars the body's
# summary portion is <=320 bytes and the assembled Expo message (excluding the
# per-recipient `to`) measures ~3999 bytes, ~97 bytes under the limit. 120 left
# no margin in that case (it overshot 4096).
PUSH_BODY_SUMMARY_MAX_CHARS = 80


@dataclass(frozen=True)
class SourceRef:
    """One article of an event as the alert texts cite it.

    ``article`` is None when the article is no longer in the database.
    """

    article_id: str
    article: Article | None


def _load_articles(article_ids: list[str], db: Database) -> list[SourceRef]:
    return [SourceRef(article_id, db.get_article_by_id(article_id)) for article_id in article_ids]


def load_sources(event: Event, db: Database) -> list[SourceRef]:
    """Read the event's articles in ``article_ids`` order, one query per article."""
    return _load_articles(event.article_ids, db)


def event_type_pl(event: Event) -> str:
    """The Polish name of the event's type; an unknown type is shown as it is."""
    return EVENT_TYPE_PL.get(event.event_type, event.event_type)


def cap_sms_summary(summary_pl: str) -> str:
    """Bound the classifier summary to ``SMS_SUMMARY_MAX_CHARS`` characters.

    The summary is truncated, never the rendered body, so the template text
    after it (the detection time, or the confirmation code) is always sent.
    """
    if len(summary_pl) > SMS_SUMMARY_MAX_CHARS:
        return summary_pl[: SMS_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return summary_pl


def build_sources_list(event: Event, sources: list[SourceRef], max_chars: int | None = None) -> str:
    """Build the SMS source list: per article a title line and a clickable URL line.

    A missing article is shown as "- (źródło <id>)", so the recipient still
    sees how many sources there are. When ``max_chars`` is given the list is
    bounded to that budget: as many whole entries as fit are included, then a
    "- …i N więcej" trailer accounts for the omitted ones. This keeps the SMS
    body under Twilio's limit even when an event carries many long URLs.
    """
    entries: list[str] = []
    for source in sources:
        article = source.article
        if article is not None:
            entry = f"- {article.source_name}: {article.title}"
            if article.source_url:
                entry += f"\n  {article.source_url}"
            entries.append(entry)
        else:
            entries.append(f"- (źródło {source.article_id[:8]})")

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


def build_sources_payload(sources: list[SourceRef]) -> list[dict]:
    """Build the structured source list carried inside the push ``data`` dict.

    The order is the SMS source list's order. Each item is ``{"name", "title",
    "url"}``, where ``url`` is None when the article has no ``source_url``. A
    missing article yields a placeholder entry mirroring the SMS
    "- (źródło <id>)" line, so the count stays consistent.
    """
    payload: list[dict] = []
    for source in sources:
        article = source.article
        if article is not None:
            payload.append(
                {
                    "name": article.source_name,
                    "title": article.title,
                    "url": article.source_url if article.source_url else None,
                }
            )
        else:
            payload.append(
                {
                    "name": "źródło",
                    "title": f"(źródło {source.article_id[:8]})",
                    "url": None,
                }
            )
    return payload


def format_call_message(event: Event, config: SentinelConfig) -> str:
    """Format the phone call TTS message in Polish using config template."""
    template = config.alerts.templates.call
    return template.format(
        event_type_pl=event_type_pl(event),
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        urgency_score=event.urgency_score,
    )


def format_sms_message(
    event: Event, db: Database, config: SentinelConfig, *, sources: list[SourceRef] | None = None
) -> str:
    """Format the SMS alert message in Polish using config template.

    Includes per-source detail lines; ``sources`` are read from the database
    when the caller has not loaded them.
    """
    if sources is None:
        sources = load_sources(event, db)
    template = config.alerts.templates.sms

    # Bound the otherwise-unbounded classifier summary so fixed template overhead
    # can never alone exceed the budget and re-trigger Twilio's 1600-char
    # rejection. Truncating the summary -- not the rendered body -- preserves
    # trailing template fields like "Wykryto: {first_seen_at_local}".
    fields = {
        "event_type_pl": event_type_pl(event),
        "urgency_score": event.urgency_score,
        "affected_countries_str": ", ".join(event.affected_countries),
        "aggressor": event.aggressor,
        "summary_pl": cap_sms_summary(event.summary_pl),
        "source_count": event.source_count,
        "first_seen_at_local": format_warsaw(event.first_seen_at),
    }

    # Measure the fixed overhead (template with an empty source list), then bound
    # the source list to the remaining budget so the whole body stays under
    # Twilio's limit. Long Google News URLs used to push corroborated events past
    # it, failing the send entirely.
    overhead = len(template.format(sources_list="", **fields))
    sources_list = build_sources_list(event, sources, max_chars=max(0, SMS_MAX_CHARS - overhead))
    return template.format(sources_list=sources_list, **fields)


def format_update_sms(
    event: Event, db: Database, config: SentinelConfig, *, sources: list[SourceRef] | None = None
) -> str:
    """Format SMS update for an already-acknowledged event.

    Includes the name of the most recent source (the last article id), or
    "nowe źródło" when that article is missing.
    """
    latest = sources[-1:] if sources is not None else _load_articles(event.article_ids[-1:], db)
    latest_article = latest[0].article if latest else None
    new_source_name = latest_article.source_name if latest_article is not None else "nowe źródło"

    template = config.alerts.templates.sms_update
    return template.format(
        event_type_pl=event_type_pl(event),
        new_source_name=new_source_name,
        summary_pl=event.summary_pl,
        source_count=event.source_count,
        urgency_score=event.urgency_score,
    )


def format_push(event: Event, is_update: bool = False) -> tuple[str, str]:
    """Format a short push notification title + body in Polish.

    The visible ``body`` embeds only the first ``PUSH_BODY_SUMMARY_MAX_CHARS``
    characters of ``summary_pl`` (1.3b), so the total Expo/APNs payload stays
    under the ~4096-byte limit. The slice is on the ``str``, never on encoded
    bytes, so a multibyte character is never split; "…" is appended only when
    the summary was cut. The full summary still travels in ``data.summary_pl``.
    """
    type_pl = event_type_pl(event)
    title = f"ℹ️ SENTINEL — aktualizacja: {type_pl}" if is_update else f"\U0001f6a8 PROJECT SENTINEL: {type_pl}"
    summary = event.summary_pl or ""
    if len(summary) > PUSH_BODY_SUMMARY_MAX_CHARS:
        summary = summary[:PUSH_BODY_SUMMARY_MAX_CHARS].rstrip() + "…"
    body = f"{summary}\nPilność {event.urgency_score}/10 · źródła: {event.source_count}"
    return title, body


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


def build_push_data(event: Event, db: Database, config: SentinelConfig, is_update: bool) -> dict:
    """Assemble the enriched Expo push ``data`` dict for one send.

    It stamps a fresh ``message_id`` per call, keeps the legacy scalars
    (``event_id``/``urgency_score``/``event_type``) and carries the full
    structured content: ``event_type_pl``, the ``sources`` list, the UTC ISO
    ``first_seen_at`` and ``sms_body``, the exact SMS text the server produces
    for this send (the alert SMS for an event, the update SMS for an update).
    The event's articles are read once for both. The dict is then trimmed to
    ``PUSH_DATA_MAX_BYTES`` (1.2): sources from the end, then ``sms_body``,
    then ``summary_pl``; the scalars and ``kind`` are never dropped or cut.
    """
    sources = load_sources(event, db)
    if is_update:
        sms_body = format_update_sms(event, db, config, sources=sources)
    else:
        sms_body = format_sms_message(event, db, config, sources=sources)

    first_seen_at = event.first_seen_at
    first_seen_at = first_seen_at.replace(tzinfo=UTC) if first_seen_at.tzinfo is None else first_seen_at.astimezone(UTC)

    data: dict = {
        "message_id": uuid.uuid4().hex,
        "event_id": event.id,
        "kind": "update" if is_update else "event",
        "event_type": event.event_type,
        "event_type_pl": event_type_pl(event),
        "urgency_score": event.urgency_score,
        "affected_countries": list(event.affected_countries),
        # aggressor/summary_pl are typed str and default to "" in the model, so
        # this coercion only guards the wire contract (never None) against a
        # malformed Event reaching this life-safety push path.
        "aggressor": event.aggressor or "",
        "summary_pl": event.summary_pl or "",
        "sources": build_sources_payload(sources),
        "sms_body": sms_body,
        "first_seen_at": first_seen_at.isoformat(),
    }

    # Byte-budget trim (1.2), in the mandated order.
    # (1) Drop trailing source entries one at a time until it fits.
    while data["sources"] and _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        data["sources"].pop()
    # (2) Truncate sms_body (head-slice) if still over with no sources left.
    # Order rationale (DO NOT reorder): sms_body is a redundant *fallback*
    # mirror of the SMS text, rendered only when the structured fields are
    # missing, so it goes *before* summary_pl, the inbox Detail screen's
    # primary content.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "sms_body")
    # (3) Truncate summary_pl (head-slice) as the last resort.
    if _data_byte_size(data) > PUSH_DATA_MAX_BYTES:
        _truncate_to_byte_budget(data, "summary_pl")

    # No silent overflow. After all three stages only the protected scalars
    # remain; they may not be dropped, so in the (unreachable with a normal
    # UUID event id) case where they alone exceed the budget, log loudly but
    # still return the dict, so a real send is never crashed by bad input.
    final_size = _data_byte_size(data)
    if final_size > PUSH_DATA_MAX_BYTES:
        logger.warning(
            "Push data for event %s is %d bytes after trimming, over the %d-byte budget; "
            "protected scalars alone exceed the limit and cannot be dropped, shipping over budget.",
            event.id,
            final_size,
            PUSH_DATA_MAX_BYTES,
        )

    return data
