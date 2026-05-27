"""Tests for sentinel.alerts.push_client.ExpoPushClient."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from sentinel.alerts.push_client import EXPO_PUSH_URL, ExpoPushClient


@pytest.fixture
def push_config(config):
    """The shared config fixture with push enabled and two tokens."""
    config.alerts.push.enabled = True
    config.alerts.push.tokens = ["ExponentPushToken[aaa]", "ExponentPushToken[bbb]"]
    return config


def _resp(json_data, raise_exc=None):
    """Build a fake httpx.Response."""
    resp = MagicMock()
    resp.raise_for_status.side_effect = raise_exc
    resp.json.return_value = json_data
    return resp


def test_ok_ticket_returns_record_with_payload_shape(push_config):
    client = ExpoPushClient(push_config)
    fake = _resp({"data": [{"status": "ok", "id": "ticket-1"}, {"status": "ok", "id": "ticket-2"}]})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake) as mock_post:
        record = client.send_push("Tytuł", "Treść", "evt-1", data={"event_id": "evt-1"})

    assert record is not None
    assert record.alert_type == "push"
    assert record.twilio_sid == "ticket-1"
    assert record.status == "sent"
    assert record.message_body == "Treść"

    args, kwargs = mock_post.call_args
    assert args[0] == EXPO_PUSH_URL
    body = kwargs["json"]
    assert body["to"] == push_config.alerts.push.tokens
    assert body["title"] == "Tytuł"
    assert body["body"] == "Treść"
    assert body["priority"] == "high"
    assert body["sound"] == "default"
    assert body["data"] == {"event_id": "evt-1"}


def test_single_ticket_dict_is_handled(push_config):
    """Expo returns a bare dict (not a list) for a single recipient."""
    client = ExpoPushClient(push_config)
    fake = _resp({"data": {"status": "ok", "id": "solo"}})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake):
        record = client.send_push("T", "B", "e")
    assert record is not None
    assert record.twilio_sid == "solo"


def test_no_auth_header_without_env(push_config, monkeypatch):
    monkeypatch.delenv("EXPO_ACCESS_TOKEN", raising=False)
    client = ExpoPushClient(push_config)
    fake = _resp({"data": [{"status": "ok", "id": "t"}]})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake) as mock_post:
        client.send_push("T", "B", "e")
    _, kwargs = mock_post.call_args
    assert "Authorization" not in kwargs["headers"]


def test_auth_header_when_env_set(push_config, monkeypatch):
    monkeypatch.setenv("EXPO_ACCESS_TOKEN", "secret-xyz")
    client = ExpoPushClient(push_config)
    fake = _resp({"data": [{"status": "ok", "id": "t"}]})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake) as mock_post:
        client.send_push("T", "B", "e")
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret-xyz"


def test_all_error_tickets_returns_none(push_config):
    client = ExpoPushClient(push_config)
    fake = _resp({"data": [{"status": "error", "message": "DeviceNotRegistered", "details": {}}]})
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake):
        record = client.send_push("T", "B", "e")
    assert record is None


def test_network_error_returns_none(push_config):
    client = ExpoPushClient(push_config)
    with patch("sentinel.alerts.push_client.httpx.post", side_effect=httpx.ConnectError("boom")):
        record = client.send_push("T", "B", "e")
    assert record is None


def test_http_status_error_returns_none(push_config):
    client = ExpoPushClient(push_config)
    err = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
    fake = _resp({}, raise_exc=err)
    with patch("sentinel.alerts.push_client.httpx.post", return_value=fake):
        record = client.send_push("T", "B", "e")
    assert record is None


def test_disabled_returns_none_without_network(config):
    client = ExpoPushClient(config)  # default config: push disabled
    with patch("sentinel.alerts.push_client.httpx.post") as mock_post:
        record = client.send_push("T", "B", "e")
    assert record is None
    mock_post.assert_not_called()


def test_no_tokens_returns_none_without_network(config):
    config.alerts.push.enabled = True
    config.alerts.push.tokens = []
    client = ExpoPushClient(config)
    with patch("sentinel.alerts.push_client.httpx.post") as mock_post:
        record = client.send_push("T", "B", "e")
    assert record is None
    mock_post.assert_not_called()
