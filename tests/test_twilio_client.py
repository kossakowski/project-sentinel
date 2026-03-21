"""Tests for sentinel.alerts.twilio_client — 8 tests per spec."""

from unittest.mock import MagicMock, patch

import pytest
from twilio.base.exceptions import TwilioRestException

from sentinel.alerts.twilio_client import TwilioClient


@pytest.fixture
def twilio_client(config):
    """Create a TwilioClient with mocked Twilio SDK."""
    with patch.dict(
        "os.environ",
        {
            "TWILIO_ACCOUNT_SID": "ACtest123",
            "TWILIO_AUTH_TOKEN": "authtoken123",
            "TWILIO_PHONE_NUMBER": "+15551234567",
        },
    ):
        with patch("sentinel.alerts.twilio_client.Client") as mock_cls:
            client = TwilioClient(config)
            # Replace the SDK client with a fresh mock for test control
            client.client = MagicMock()
            yield client


# --------------------------------------------------------------------------
# 1. test_make_call_returns_record
# --------------------------------------------------------------------------
def test_make_call_returns_record(twilio_client):
    """Call creates AlertRecord with correct fields."""
    mock_call = MagicMock()
    mock_call.sid = "CA_test_sid_123"
    twilio_client.client.calls.create.return_value = mock_call

    record = twilio_client.make_alert_call(
        "+48123456789", "Testowy alert", "evt-001"
    )

    assert record is not None
    assert record.event_id == "evt-001"
    assert record.alert_type == "phone_call"
    assert record.twilio_sid == "CA_test_sid_123"
    assert record.status == "initiated"
    assert record.message_body == "Testowy alert"
    assert record.duration_seconds is None


# --------------------------------------------------------------------------
# 2. test_call_twiml_polish
# --------------------------------------------------------------------------
def test_call_twiml_polish(twilio_client):
    """TwiML contains Polish language tag and Polly.Ewa voice."""
    mock_call = MagicMock()
    mock_call.sid = "CA_twiml_test"
    twilio_client.client.calls.create.return_value = mock_call

    twilio_client.make_alert_call(
        "+48123456789", "Testowy alert", "evt-002"
    )

    call_kwargs = twilio_client.client.calls.create.call_args
    twiml = call_kwargs.kwargs.get("twiml", "")
    assert 'language="pl-PL"' in twiml
    assert 'voice="Polly.Ewa"' in twiml


# --------------------------------------------------------------------------
# 3. test_call_message_repeated
# --------------------------------------------------------------------------
def test_call_message_repeated(twilio_client):
    """TwiML contains the message twice (for waking the user)."""
    mock_call = MagicMock()
    mock_call.sid = "CA_repeat_test"
    twilio_client.client.calls.create.return_value = mock_call

    message = "Inwazja wykryta na granicy"
    twilio_client.make_alert_call("+48123456789", message, "evt-003")

    call_kwargs = twilio_client.client.calls.create.call_args
    twiml = call_kwargs.kwargs.get("twiml", "")
    assert twiml.count(message) == 2


# --------------------------------------------------------------------------
# 4. test_send_sms_returns_record
# --------------------------------------------------------------------------
def test_send_sms_returns_record(twilio_client):
    """SMS creates AlertRecord with correct fields."""
    mock_msg = MagicMock()
    mock_msg.sid = "SM_test_sid_456"
    twilio_client.client.messages.create.return_value = mock_msg

    record = twilio_client.send_sms(
        "+48123456789", "Alert SMS", "evt-004"
    )

    assert record is not None
    assert record.event_id == "evt-004"
    assert record.alert_type == "sms"
    assert record.twilio_sid == "SM_test_sid_456"
    assert record.status == "sent"


# --------------------------------------------------------------------------
# 5. test_sms_truncation
# --------------------------------------------------------------------------
def test_sms_truncation(twilio_client):
    """Message > 1600 chars is truncated with '...'."""
    mock_msg = MagicMock()
    mock_msg.sid = "SM_truncate"
    twilio_client.client.messages.create.return_value = mock_msg

    long_message = "A" * 2000
    record = twilio_client.send_sms(
        "+48123456789", long_message, "evt-005"
    )

    assert record is not None
    assert len(record.message_body) == 1600
    assert record.message_body.endswith("...")


# --------------------------------------------------------------------------
# 6. test_send_whatsapp_returns_record
# --------------------------------------------------------------------------
def test_send_whatsapp_returns_record(twilio_client):
    """WhatsApp creates AlertRecord with correct fields."""
    mock_msg = MagicMock()
    mock_msg.sid = "SM_wa_789"
    twilio_client.client.messages.create.return_value = mock_msg

    record = twilio_client.send_whatsapp(
        "+48123456789", "WhatsApp alert", "evt-006"
    )

    assert record is not None
    assert record.event_id == "evt-006"
    assert record.alert_type == "whatsapp"
    assert record.twilio_sid == "SM_wa_789"
    assert record.status == "sent"

    # Verify the 'to' field uses whatsapp: prefix
    call_kwargs = twilio_client.client.messages.create.call_args
    assert call_kwargs.kwargs["to"] == "whatsapp:+48123456789"


# --------------------------------------------------------------------------
# 7. test_get_call_status
# --------------------------------------------------------------------------
def test_get_call_status(twilio_client):
    """Fetches call status from Twilio API."""
    mock_call = MagicMock()
    mock_call.status = "completed"
    mock_call.duration = "30"
    twilio_client.client.calls.return_value.fetch.return_value = mock_call

    result = twilio_client.get_call_status("CA_status_test")

    assert result is not None
    assert result["status"] == "completed"
    assert result["duration"] == 30


# --------------------------------------------------------------------------
# 8. test_twilio_error_handled
# --------------------------------------------------------------------------
def test_twilio_error_handled(twilio_client):
    """TwilioRestException is logged but not raised."""
    twilio_client.client.calls.create.side_effect = TwilioRestException(
        status=500, uri="/test", msg="Server error"
    )

    # Should not raise
    record = twilio_client.make_alert_call(
        "+48123456789", "Test", "evt-err"
    )
    assert record is None

    # SMS error
    twilio_client.client.messages.create.side_effect = TwilioRestException(
        status=500, uri="/test", msg="Server error"
    )
    record = twilio_client.send_sms("+48123456789", "Test", "evt-err2")
    assert record is None

    record = twilio_client.send_whatsapp("+48123456789", "Test", "evt-err3")
    assert record is None
