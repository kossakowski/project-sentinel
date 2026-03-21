import logging
import os
from datetime import datetime, timezone
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from sentinel.config import SentinelConfig
from sentinel.models import AlertRecord


class TwilioClient:
    """Wraps the Twilio SDK for outbound calls, SMS, and WhatsApp."""

    def __init__(self, config: SentinelConfig) -> None:
        self.logger = logging.getLogger("sentinel.alerts.twilio_client")
        self.config = config

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.twilio_phone = os.environ.get("TWILIO_PHONE_NUMBER", "")
        self.twilio_whatsapp = os.environ.get(
            "TWILIO_WHATSAPP_NUMBER", f"whatsapp:{self.twilio_phone}"
        )

        self.client = Client(account_sid, auth_token)

    def make_alert_call(
        self, phone_number: str, message_pl: str, event_id: str
    ) -> AlertRecord | None:
        """Place an outbound call with Polish TTS message.

        The message is spoken twice (for waking the user).
        Returns an AlertRecord on success, None on Twilio error.
        """
        safe_message = xml_escape(message_pl)
        twiml = (
            f"<Response>"
            f'<Say language="pl-PL" voice="Polly.Ewa">'
            f"Uwaga! Alert systemu Project Sentinel. {safe_message}"
            f"</Say>"
            f'<Pause length="2"/>'
            f'<Say language="pl-PL" voice="Polly.Ewa">'
            f"Powtarzam. {safe_message}"
            f"</Say>"
            f'<Pause length="1"/>'
            f'<Say language="pl-PL" voice="Polly.Ewa">'
            f"Koniec alertu. Dalsze aktualizacje otrzymasz SMS-em."
            f"</Say>"
            f"</Response>"
        )

        try:
            call = self.client.calls.create(
                from_=self.twilio_phone,
                to=phone_number,
                twiml=twiml,
            )
        except TwilioRestException as exc:
            self.logger.error(
                "Twilio call failed for event %s: %s", event_id, exc
            )
            return None

        record = AlertRecord(
            id=str(uuid4()),
            event_id=event_id,
            alert_type="phone_call",
            twilio_sid=call.sid,
            status="initiated",
            duration_seconds=None,
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body=message_pl,
        )
        self.logger.info(
            "Call placed for event %s, SID=%s", event_id, call.sid
        )
        return record

    def send_sms(
        self, phone_number: str, message: str, event_id: str
    ) -> AlertRecord | None:
        """Send an SMS alert.

        Truncates to 1600 chars if needed.
        Returns an AlertRecord on success, None on Twilio error.
        """
        if len(message) > 1600:
            message = message[:1597] + "..."

        try:
            msg = self.client.messages.create(
                from_=self.twilio_phone,
                to=phone_number,
                body=message,
            )
        except TwilioRestException as exc:
            self.logger.error(
                "Twilio SMS failed for event %s: %s", event_id, exc
            )
            return None

        record = AlertRecord(
            id=str(uuid4()),
            event_id=event_id,
            alert_type="sms",
            twilio_sid=msg.sid,
            status="sent",
            duration_seconds=None,
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body=message,
        )
        self.logger.info(
            "SMS sent for event %s, SID=%s", event_id, msg.sid
        )
        return record

    def send_whatsapp(
        self, phone_number: str, message: str, event_id: str
    ) -> AlertRecord | None:
        """Send a WhatsApp message.

        Returns an AlertRecord on success, None on Twilio error.
        """
        try:
            msg = self.client.messages.create(
                from_=self.twilio_whatsapp,
                to=f"whatsapp:{phone_number}",
                body=message,
            )
        except TwilioRestException as exc:
            self.logger.error(
                "Twilio WhatsApp failed for event %s: %s", event_id, exc
            )
            return None

        record = AlertRecord(
            id=str(uuid4()),
            event_id=event_id,
            alert_type="whatsapp",
            twilio_sid=msg.sid,
            status="sent",
            duration_seconds=None,
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body=message,
        )
        self.logger.info(
            "WhatsApp sent for event %s, SID=%s", event_id, msg.sid
        )
        return record

    def get_call_status(self, twilio_sid: str) -> dict | None:
        """Check the status of a previously placed call.

        Returns a dict with 'status' and 'duration' keys, or None on error.
        """
        try:
            call = self.client.calls(twilio_sid).fetch()
            return {
                "status": call.status,
                "duration": int(call.duration) if call.duration else 0,
            }
        except TwilioRestException as exc:
            self.logger.error(
                "Twilio call status fetch failed for SID %s: %s",
                twilio_sid,
                exc,
            )
            return None
