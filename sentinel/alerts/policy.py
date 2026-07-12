"""AlertPolicy -- the single authority that decides what alert fires.

This module consolidates the three historical decision sites into one pure,
config-driven policy:

  * ``corroborator._determine_alert_status`` (deleted)
  * ``state_machine._determine_action`` (now delegates here)
  * ``harness._action_for_urgency`` (deleted; harness derives via this policy)

Corroboration is gone: no source-count / independent-source gate can suppress or
delay an alert. Deduplication -- expressed as the :class:`EventDecision` relation
this policy consumes -- is the only thing that can suppress an *alert-eligible*
event. Everything at/below the ``none`` band produces no alert purely by band
mapping (that is banding, not suppression).

Prime directive: never miss an urgency 9-10. Every ambiguity resolves toward
firing (an unknown geo tier at call urgency is treated HIGH; a defective ``SAME``
that carries a first call-tier crossing still fires the call).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sentinel.config import SentinelConfig


class ChannelClass(StrEnum):
    """Transport-agnostic alert class an :class:`AlertIntent` carries."""

    CALL = "call"
    NOTIFY = "notify"
    NONE = "none"


class GeoTier(StrEnum):
    """Geography weight of an event's physical target."""

    HIGH = "high"
    LOW = "low"
    UNKNOWN = "unknown"


class Relation(StrEnum):
    """How a classified article relates to events already alerted on.

    Produced by the deduplicator (Phase 3) and consumed by :class:`AlertPolicy`.
    """

    NEW = "new"
    SAME = "same"
    ESCALATION = "escalation"


@dataclass(frozen=True)
class EventDecision:
    """The deduplicator's verdict for one classified article.

    This is the interface Phase 3's ``EventDeduplicator`` produces and
    ``AlertPolicy`` consumes. ``matched_event_id`` is the id of the event the
    article was matched to (``None`` for a ``NEW`` event).
    """

    relation: Relation
    matched_event_id: str | None = None


@dataclass(frozen=True)
class AlertIntent:
    """The policy's decision for one event: a transport-agnostic channel class."""

    channel_class: ChannelClass
    urgency: int
    geo_tier: GeoTier
    relation: Relation
    reason: str = ""


# Belt-and-braces call tier used only if a config object somehow reaches this
# module without a CALL band. Config load is the real guard: AlertsConfig's
# validator rejects a channel_bands map with no call band / incomplete urgency
# coverage, so a misconfigured band map fails fast at startup rather than
# silently disabling every phone call in production.
_FALLBACK_CALL_TIER = 9


def call_tier_min(config: SentinelConfig) -> int:
    """Lowest urgency mapped to the CALL band, read from ``alerts.channel_bands``.

    The single source of truth for "what counts as call tier" -- every caller
    (policy, corroborator, geo floor) derives it from here, so the call tier can
    never diverge between two knobs.
    """
    for band in config.alerts.channel_bands:
        if band.channel_class == ChannelClass.CALL.value:
            return band.min_score
    return _FALLBACK_CALL_TIER


class AlertPolicy:
    """The single, pure, config-driven alert-decision authority."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        # Highest-threshold band first so band_for_urgency picks the top match.
        self._bands = sorted(
            config.alerts.channel_bands,
            key=lambda b: b.min_score,
            reverse=True,
        )

    def band_for_urgency(self, urgency: int) -> ChannelClass:
        """Pure urgency -> channel-class band mapping (no geo, no relation).

        Rubric v2 bands (config-driven): >= call-tier -> CALL; notify-tier -> NOTIFY;
        below -> NONE.
        """
        for band in self._bands:
            if urgency >= band.min_score:
                return ChannelClass(band.channel_class)
        return ChannelClass.NONE

    def decide(
        self,
        decision: EventDecision,
        urgency: int,
        geo_tier: GeoTier,
        already_alerted_at: ChannelClass | None = None,
    ) -> AlertIntent:
        """Decide the alert action for one event.

        Pure function of its inputs (no I/O). ``already_alerted_at`` is the
        highest channel class already *dispatched* for the event (``None`` if
        none yet), needed for the one-call-per-event and dedup-suppression rules.

        ``ChannelClass.NONE`` is normalized to ``None``: "decided, nothing
        dispatched" is NOT "already alerted", and treating it as such would let a
        SAME relation suppress an event that has never produced an alert (2.3
        permits no-alert only for a SAME on an ALREADY-alerted event).
        """
        relation = decision.relation
        already = None if already_alerted_at is ChannelClass.NONE else already_alerted_at
        base = self.band_for_urgency(urgency)

        # Geography gate (2.5 / 2.5a): only a would-be CALL is geo-gated.
        resolved_geo = geo_tier
        band = base
        if base is ChannelClass.CALL:
            if geo_tier is GeoTier.UNKNOWN:
                resolved_geo = GeoTier.HIGH  # 2.5a: unknown geo at call urgency fails toward firing
            # 2.5: a LOW-tier call urgency demotes to NOTIFY (never to NONE -- demotion is not suppression).
            band = ChannelClass.NOTIFY if resolved_geo is GeoTier.LOW else ChannelClass.CALL

        # NONE band produces no alert by band mapping (2.4) -- this is banding, not suppression.
        if band is ChannelClass.NONE:
            return AlertIntent(ChannelClass.NONE, urgency, resolved_geo, relation, "none-band")

        # First call-tier intent for this event fires regardless of relation (2.6):
        # a NEW or an ESCALATION crossing the call tier on a never-called event is
        # that event's one call. A defective SAME carrying a first tier-crossing
        # still fires (fail toward firing) because a SAME cannot legally cross tiers.
        if band is ChannelClass.CALL and already is not ChannelClass.CALL:
            return AlertIntent(ChannelClass.CALL, urgency, resolved_geo, relation, "first-call")

        # Deduplication is the sole suppressor (2.3): a SAME relation on an event
        # already alerted on returns no-alert.
        if relation is Relation.SAME and already is not None:
            return AlertIntent(ChannelClass.NONE, urgency, resolved_geo, relation, "same-suppressed")

        # An escalation on an event already called uses NOTIFY, not a second call
        # (one call per event, 2.6).
        if band is ChannelClass.CALL:
            return AlertIntent(ChannelClass.NOTIFY, urgency, resolved_geo, relation, "recall-downgraded")

        return AlertIntent(ChannelClass.NOTIFY, urgency, resolved_geo, relation, "notify")
