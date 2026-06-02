import logging
import os
from datetime import UTC, datetime

import httpx

from sentinel.config import SentinelConfig
from sentinel.models import AlertRecord

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class ExpoPushClient:
    """Sends push notifications to the companion mobile app via the Expo Push Service.

    One of the per-tier delivery channels for the SMS-action urgency tiers (5-8):
    a level's `channel` (sms | push | both) selects whether that tier is delivered
    by Twilio SMS, this Expo push, or both. No account or secret is required for
    basic sends; an optional EXPO_ACCESS_TOKEN (set only when "Enhanced Security
    for Push Notifications" is turned on in the Expo project) is forwarded as a
    bearer token when present.
    """

    def __init__(self, config: SentinelConfig) -> None:
        self.logger = logging.getLogger("sentinel.alerts.push_client")
        self.config = config
        self.access_token = os.environ.get("EXPO_ACCESS_TOKEN", "")

    def send_push(
        self,
        title: str,
        body: str,
        event_id: str,
        data: dict | None = None,
    ) -> AlertRecord | None:
        """Send one push to every configured Expo token.

        Returns an AlertRecord when at least one ticket is accepted; None when
        push is disabled, no tokens are configured, the HTTP call fails, or every
        ticket is rejected. Mirrors the failure contract of the Twilio methods.
        """
        push_cfg = self.config.alerts.push
        if not push_cfg.enabled or not push_cfg.tokens:
            return None

        payload: dict = {
            "to": push_cfg.tokens,
            "title": title,
            "body": body,
            "sound": "default",
            "priority": "high",
            # Best-effort background wake (AD-3). Expo derives the APNs
            # `content-available` key from this; we MUST NOT set that key here.
            "_contentAvailable": True,
        }
        if data is not None:
            payload["data"] = data

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            response = httpx.post(EXPO_PUSH_URL, json=payload, headers=headers, timeout=15.0)
            response.raise_for_status()
            tickets = response.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            self.logger.error("Expo push failed for event %s: %s", event_id, exc)
            return None

        # The Expo API returns a single ticket dict for one recipient, or a list
        # of tickets (one per token) when `to` is an array.
        if isinstance(tickets, dict):
            tickets = [tickets]

        ok_ids = [t.get("id", "") for t in tickets if t.get("status") == "ok"]
        for err in (t for t in tickets if t.get("status") != "ok"):
            self.logger.warning(
                "Expo push ticket error for event %s: %s (%s)",
                event_id,
                err.get("message"),
                err.get("details"),
            )

        if not ok_ids:
            self.logger.error("Expo push for event %s: no tickets accepted", event_id)
            return None

        self.logger.info(
            "Push sent for event %s to %d token(s), ticket=%s",
            event_id,
            len(ok_ids),
            ok_ids[0],
        )
        return AlertRecord(
            event_id=event_id,
            alert_type="push",
            twilio_sid=ok_ids[0],
            status="sent",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=body,
        )
