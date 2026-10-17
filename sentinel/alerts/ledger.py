"""The delivery ledger: what an event's alert records say was already delivered.

Pure reads over the records of one event. They decide which channel still
owes the event's current ``notification_revision``, so a failed attempt is
retried and a delivered one is not repeated.
"""

from sentinel.models import PENDING_CALL_STATUSES, AlertRecord, AlertType, Event

# ``sms_update`` is accepted for historical/operational compatibility even
# though the current transport returns ``sms`` for both bodies.
SMS_ALERT_TYPES = (AlertType.SMS, AlertType.SMS_UPDATE)
# Record statuses of an attempt that reached the transport.
SUCCESSFUL_DELIVERY_STATUSES = ("sent", "delivered", "acknowledged")
# The record status that marks an acknowledged alert.
ACKNOWLEDGED_RECORD_STATUS = "acknowledged"


def channel_delivered(alerts: list[AlertRecord], channel: str, revision: int) -> bool:
    """Return whether ``channel`` ("sms" or "push") successfully delivered ``revision``.

    A database migration gives legacy records revision 1. Looking at both
    type and successful status is important: a retained failed push/SMS
    attempt must never suppress the next retry.
    """
    alert_types = SMS_ALERT_TYPES if channel == "sms" else (AlertType.PUSH,)
    return any(
        alert.alert_type in alert_types
        and alert.status in SUCCESSFUL_DELIVERY_STATUSES
        and alert.event_revision == revision
        for alert in alerts
    )


def has_new_delivered_revision(event: Event, alerts: list[AlertRecord]) -> bool:
    """True when the event advanced beyond a previously delivered revision.

    Do not compare only against the maximum delivery revision: after the
    SMS half of a revision succeeds, a failed push half still needs a retry.
    Any earlier successful revision establishes that this is an update;
    per-channel checks decide which outstanding half to send.
    """
    return any(
        alert.status in SUCCESSFUL_DELIVERY_STATUSES and alert.event_revision < event.notification_revision
        for alert in alerts
    )


def is_acknowledged(alerts: list[AlertRecord]) -> bool:
    """Check if any alert for this event was acknowledged."""
    return any(alert.status == ACKNOWLEDGED_RECORD_STATUS for alert in alerts)


def has_pending_call(alerts: list[AlertRecord]) -> bool:
    """True when a placed call of this event has no known result yet."""
    return any(alert.alert_type == AlertType.PHONE_CALL and alert.status in PENDING_CALL_STATUSES for alert in alerts)
