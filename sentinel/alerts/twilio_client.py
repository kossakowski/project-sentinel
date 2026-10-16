import logging
import os
import re
from datetime import UTC, datetime
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

import requests
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from sentinel.config import SentinelConfig
from sentinel.models import AlertRecord

# Errors of a Twilio request: API errors (TwilioRestException is a
# TwilioException) and transport errors, which the SDK raises as ``requests``
# exceptions (connection reset, timeout, DNS failure).
_TWILIO_REQUEST_ERRORS = (TwilioException, requests.RequestException)

# Twilio rejects a call whose ``twiml`` parameter is longer than 4000
# characters (Call resource, Create request), so the call would fail to
# initiate. The spoken message appears twice in the TwiML. Lengths are measured
# in UTF-8 bytes, which is never less than the character count, so the limit
# holds however Twilio counts Polish letters or emoji.
TWIML_MAX_CHARS = 4000


def _wire_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _alert_twiml(safe_message: str) -> str:
    """Build the alert-call TwiML around an already XML-escaped message."""
    # Simple alert call — no DTMF, no Gather.
    # The call is just an alarm to wake the user.
    # Confirmation happens via SMS reply only.
    return (
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
        f"Potwierdź odbiór alertu. Odpisz na SMS kodem, który otrzymałeś."
        f"</Say>"
        f"</Response>"
    )


_CUT_MARK = "…"

# Characters that XML 1.0 does not allow in a document at all, even escaped:
# C0 controls other than tab, newline and carriage return, lone surrogates,
# U+FFFE and U+FFFF. ``xml_escape`` passes them through, so one of them in the
# summary would make the call TwiML invalid.
_XML_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _strip_xml_illegal(text: str) -> str:
    """Remove the characters that cannot appear in an XML document."""
    return _XML_ILLEGAL_CHARS.sub("", text)


def _fit_call_message(message_pl: str) -> str:
    """Shorten ``message_pl`` only as far as needed for its TwiML to fit ``TWIML_MAX_CHARS``.

    A message that fits is returned unchanged. Otherwise the longest head of the
    message that still fits together with the cut mark "…" is kept. XML
    escaping and UTF-8 encoding both work one character at a time, so each
    character is charged exactly what it takes on the wire: one byte for a
    plain letter, two for a Polish or Cyrillic letter, four for an emoji and
    five for an escaped "&".
    """
    budget = (TWIML_MAX_CHARS - _wire_len(_alert_twiml(""))) // 2
    if _wire_len(xml_escape(message_pl)) <= budget:
        return message_pl
    room = budget - _wire_len(_CUT_MARK)
    keep = 0
    for char in message_pl:
        room -= _wire_len(xml_escape(char))
        if room < 0:
            break
        keep += 1
    return message_pl[:keep].rstrip() + _CUT_MARK


class TwilioClient:
    """Wraps the Twilio SDK for outbound calls and SMS.

    The call, SMS and call-status methods never raise: every failure is logged
    and reported as ``None``, so a Twilio problem with one message cannot stop
    the rest of the alert path (for example, the call after a failed
    confirmation SMS).
    """

    def __init__(self, config: SentinelConfig) -> None:
        self.logger = logging.getLogger("sentinel.alerts.twilio_client")
        self.config = config

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.twilio_phone = os.environ.get("TWILIO_PHONE_NUMBER", "")

        # The SDK default is no HTTP timeout, so a half-open connection would
        # block the worker thread, and with it the pipeline cycle, for good.
        http_client = TwilioHttpClient(timeout=config.alerts.twilio.http_timeout_seconds)
        self.client = Client(account_sid, auth_token, http_client=http_client)

    def make_alert_call(self, phone_number: str, message_pl: str, event_id: str) -> AlertRecord | None:
        """Place an outbound call with Polish TTS message.

        The message is spoken twice (for waking the user). Characters that XML
        does not allow are removed, and a message too long for Twilio's TwiML
        limit is shortened, so the call is still placed.
        Returns an AlertRecord on success, None on any error.
        """
        speakable = _strip_xml_illegal(message_pl)
        spoken = _fit_call_message(speakable)
        if spoken != speakable:
            self.logger.warning(
                "Call message for event %s shortened from %d to %d characters to fit the TwiML limit",
                event_id,
                len(speakable),
                len(spoken),
            )
        twiml = _alert_twiml(xml_escape(spoken))

        try:
            call = self.client.calls.create(
                from_=self.twilio_phone,
                to=phone_number,
                twiml=twiml,
            )
        except _TWILIO_REQUEST_ERRORS as exc:
            self.logger.error("Twilio call failed for event %s: %s", event_id, exc)
            return None
        except Exception:
            self.logger.exception("Twilio call failed for event %s with an unexpected error", event_id)
            return None

        record = AlertRecord(
            id=str(uuid4()),
            event_id=event_id,
            alert_type="phone_call",
            twilio_sid=call.sid,
            status="initiated",
            duration_seconds=None,
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=spoken,
        )
        self.logger.info("Call placed for event %s, SID=%s", event_id, call.sid)
        return record

    def send_sms(self, phone_number: str, message: str, event_id: str) -> AlertRecord | None:
        """Send an SMS alert.

        Truncates to 1600 chars if needed.
        Returns an AlertRecord on success, None on any error.
        """
        if len(message) > 1600:
            message = message[:1597] + "..."

        try:
            msg = self.client.messages.create(
                from_=self.twilio_phone,
                to=phone_number,
                body=message,
            )
        except _TWILIO_REQUEST_ERRORS as exc:
            self.logger.error("Twilio SMS failed for event %s: %s", event_id, exc)
            return None
        except Exception:
            self.logger.exception("Twilio SMS failed for event %s with an unexpected error", event_id)
            return None

        record = AlertRecord(
            id=str(uuid4()),
            event_id=event_id,
            alert_type="sms",
            twilio_sid=msg.sid,
            status="sent",
            duration_seconds=None,
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body=message,
        )
        self.logger.info("SMS sent for event %s, SID=%s", event_id, msg.sid)
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
                "answered_by": getattr(call, "answered_by", None),
            }
        except _TWILIO_REQUEST_ERRORS as exc:
            self.logger.error(
                "Twilio call status fetch failed for SID %s: %s",
                twilio_sid,
                exc,
            )
            return None
        except Exception:
            self.logger.exception("Twilio call status fetch failed for SID %s with an unexpected error", twilio_sid)
            return None
