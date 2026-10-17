"""Which channel an event is alerted on: the urgency-tier routing rule.

This is the life-safety decision between a phone call, an SMS, a push and
nothing. The dispatcher (for its dry-run log) and the state machine both ask
``resolve_action``; nothing else decides the channel.
"""

from collections.abc import Mapping
from enum import StrEnum

from sentinel.config import UrgencyLevel


class Action(StrEnum):
    """The delivery action for one event; the value is the logged and stored string."""

    PHONE_CALL = "phone_call"
    SMS = "sms"
    PUSH = "push"
    BOTH = "both"
    LOG_ONLY = "log_only"


def resolve_action(levels: Mapping[str, UrgencyLevel], score: int, source_count: int) -> Action:
    """Resolve the delivery action for an urgency score and source count.

    ``levels`` is ``config.alerts.urgency_levels``. They are tried from the
    highest ``min_score`` down, so their order in the config does not matter,
    and the first level whose ``min_score`` the score reaches decides:

    - a ``phone_call`` level gives ``phone_call`` when ``source_count``
      reaches its ``corroboration_required``, and ``sms`` otherwise;
    - an ``sms`` level gives its ``channel`` (``sms``, ``push`` or ``both``);
    - a ``log_only`` level gives ``log_only``.

    A score below every level gives ``log_only``. ``channel`` is read only on
    ``sms`` levels. The state machine adds the push to a ``phone_call`` itself
    (the push is additive there), so the call path is not a channel choice.
    """
    for level in sorted(levels.values(), key=lambda level: level.min_score, reverse=True):
        if score >= level.min_score:
            if level.action == "phone_call":
                return Action.PHONE_CALL if source_count >= level.corroboration_required else Action.SMS
            if level.action == "sms":
                return Action(level.channel)
            return Action(level.action)
    return Action.LOG_ONLY
