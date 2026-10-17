"""Structure of the alert package (refactor Phase 4).

- ``resolve_action`` reproduces the routing table frozen from master (1.10).
- Only ``TwilioClient`` touches the Twilio SDK object.
- The status and type enums keep the strings stored in the database.
- The split alert modules stay small, and a push reads each article once.
- The delivery ledger reads an event's alert records by type, status and revision.
"""

import csv
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import requests
from twilio.base.exceptions import TwilioRestException

from sentinel.alerts.formatting import build_push_data, format_sms_message, format_update_sms
from sentinel.alerts.ledger import channel_delivered, has_new_delivered_revision, has_pending_call, is_acknowledged
from sentinel.alerts.routing import Action, resolve_action
from sentinel.alerts.twilio_client import SmsStatus, TwilioClient
from sentinel.database import Database
from sentinel.models import AlertRecord, AlertStatus, AlertType, Article, CallStatus, Event

REPO_ROOT = Path(__file__).resolve().parents[1]
SENTINEL_DIR = REPO_ROOT / "sentinel"
ROUTING_TABLE = Path(__file__).resolve().parent / "golden" / "routing_table.csv"

# ---------------------------------------------------------------------------
# 4.2, 4.7: routing
# ---------------------------------------------------------------------------


def test_routing_table_matches_master(prod_config):
    """Every row of the master routing table (urgency 0-10 x sources 1-3, live tiers) is reproduced."""
    with ROUTING_TABLE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 11 * 3

    for row in rows:
        action = resolve_action(prod_config.alerts.urgency_levels, int(row["urgency_score"]), int(row["source_count"]))
        assert isinstance(action, Action)
        assert action == row["action"], row


def test_production_code_routes_through_resolve_action():
    """No production module calls the state machine's private ``_determine_action``."""
    production = [*SENTINEL_DIR.rglob("*.py"), REPO_ROOT / "sentinel.py"]
    callers = [path for path in production if re.search(r"\._determine_action\(", path.read_text(encoding="utf-8"))]
    assert callers == []


# ---------------------------------------------------------------------------
# 4.3: the Twilio SDK stays inside TwilioClient
# ---------------------------------------------------------------------------

_TWILIO_SDK_USE = re.compile(
    r"^\s*(?:from|import)\s+twilio\b"  # importing the SDK
    r"|\b_*twilio\w*\.client\b"  # reaching through a TwilioClient into its SDK object
    r"|\.client\.calls\b"  # the SDK's call resource
    r"|\.client\.messages\s*\("  # messages(sid).fetch()
    r"|\.client\.messages\.list\b"  # the inbound-message query
    # Sending an SMS under any receiver name: only Twilio's messages.create
    # takes ``from_``, so the Anthropic SDK's messages.create does not match.
    r"|\.messages\.create\((?:[^()]|\([^()]*\))*?\bfrom_\s*=",
    re.MULTILINE,
)


def test_twilio_sdk_used_only_in_client():
    """Outside ``sentinel/alerts/twilio_client.py`` nothing in ``sentinel/`` imports or reaches the Twilio SDK."""
    client_module = SENTINEL_DIR / "alerts" / "twilio_client.py"
    offenders = {
        str(path.relative_to(REPO_ROOT)): [match.group(0).strip() for match in _TWILIO_SDK_USE.finditer(text)]
        for path in sorted(SENTINEL_DIR.rglob("*.py"))
        if path != client_module and _TWILIO_SDK_USE.search(text := path.read_text(encoding="utf-8"))
    }
    assert offenders == {}
    # The pattern does find the SDK where it legitimately lives.
    assert _TWILIO_SDK_USE.search(client_module.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "line",
    [
        "from twilio.rest import Client",
        "sdk = self._twilio.client",
        "sdk = machine.twilio.client",
        "self.sms.client.messages.create(\n    from_=self.sender,\n    to=to,\n    body=str(body),\n)",
        "gateway.messages.create(to=to, from_=sender, body=body)",
        "tc.client.messages.list(to=sender, limit=10)",
        "tc.client.messages(sid).fetch()",
    ],
)
def test_twilio_sdk_pattern_finds_sdk_use(line):
    """The pattern finds the SDK also when the client or the SDK object is held under another name."""
    assert _TWILIO_SDK_USE.search(line)


def test_twilio_sdk_pattern_ignores_the_anthropic_messages_call():
    """The Anthropic SDK's ``client.messages.create(...)`` has the same shape but is not the Twilio SDK."""
    source = (SENTINEL_DIR / "classification" / "legacy_anthropic.py").read_text(encoding="utf-8")
    assert ".client.messages.create(" in source
    assert not _TWILIO_SDK_USE.search(source)


def test_twilio_client_reads_inbound_sms_and_sms_status(prod_config, twilio_sdk):
    """The two read wrappers run the SDK queries the state machine used to make and return plain values."""
    client = TwilioClient(prod_config)
    since = datetime(2026, 10, 16, 12, tzinfo=UTC)
    twilio_sdk.messages.list.return_value = [SimpleNamespace(body=" 424242 \n"), SimpleNamespace(body=None)]
    twilio_sdk.messages.return_value.fetch.return_value = SimpleNamespace(status="undelivered", error_code=30003)

    assert client.list_inbound_sms(since) == ["424242", ""]
    twilio_sdk.messages.list.assert_called_once_with(
        to=os.environ["TWILIO_PHONE_NUMBER"],
        from_=prod_config.alerts.phone_number,
        date_sent_after=since,
        limit=10,
    )
    assert client.get_sms_status("SM1") == SmsStatus(status="undelivered", error_code=30003)
    twilio_sdk.messages.assert_called_with("SM1")


@pytest.mark.parametrize(
    "error",
    [
        TwilioRestException(status=401, uri="/Messages.json", msg="Account not active"),
        requests.ConnectionError("reset"),
    ],
    ids=["api-error", "transport-error"],
)
def test_twilio_client_read_errors_return_none(prod_config, twilio_sdk, error):
    client = TwilioClient(prod_config)
    twilio_sdk.messages.list.side_effect = error
    twilio_sdk.messages.return_value.fetch.side_effect = error

    assert client.list_inbound_sms(datetime.now(UTC)) is None
    assert client.get_sms_status("SM1") is None


# ---------------------------------------------------------------------------
# 4.4: enums keep today's stored strings
# ---------------------------------------------------------------------------


def test_enum_values_match_stored_strings(tmp_path):
    assert {member.name: member.value for member in AlertStatus} == {
        "PENDING": "pending",
        "PHONE_CALL": "phone_call",
        "SMS": "sms",
        "DRY_RUN": "dry_run",
        "SMS_SENT": "sms_sent",
        "CALL_PLACED": "call_placed",
        "RETRY_PENDING": "retry_pending",
        "ACKNOWLEDGED": "acknowledged",
        "EXPIRED": "expired",
        "PUSH": "push",
    }
    assert {member.name: member.value for member in AlertType} == {
        "PHONE_CALL": "phone_call",
        "SMS": "sms",
        "SMS_UPDATE": "sms_update",
        "PUSH": "push",
    }
    assert {member.name: member.value for member in CallStatus} == {
        "INITIATED": "initiated",
        "QUEUED": "queued",
        "RINGING": "ringing",
        "IN_PROGRESS": "in-progress",
        "COMPLETED": "completed",
        "BUSY": "busy",
        "NO_ANSWER": "no-answer",
        "CANCELED": "canceled",
        "FAILED": "failed",
    }
    for member in [*AlertStatus, *AlertType, *CallStatus]:
        assert member == member.value
        assert str(member) == f"{member}" == member.value

    # Written through the database, a member is stored as its plain string.
    db = Database(str(tmp_path / "enums.db"))
    try:
        now = datetime.now(UTC)
        event = Event(
            event_type="invasion",
            urgency_score=10,
            affected_countries=["PL"],
            aggressor="RU",
            summary_pl="Rosyjskie wojska przekroczyły granicę Polski.",
            first_seen_at=now,
            last_updated_at=now,
            source_count=1,
            article_ids=[],
            alert_status=AlertStatus.PHONE_CALL,
        )
        db.insert_event(event)
        db.update_event(event.id, alert_status=AlertStatus.RETRY_PENDING)
        record = AlertRecord(
            event_id=event.id,
            alert_type=AlertType.PHONE_CALL,
            twilio_sid="CA00000000000000000000000000000001",
            status=CallStatus.INITIATED,
            attempt_number=1,
            sent_at=now,
            message_body="Alarm",
        )
        db.insert_alert_record(record)
        db.update_alert_record(record.id, status=CallStatus.NO_ANSWER)

        stored_event = db.conn.execute(
            "SELECT alert_status, typeof(alert_status) FROM events WHERE id = ?", (event.id,)
        ).fetchone()
        assert tuple(stored_event) == ("retry_pending", "text")
        stored_record = db.conn.execute(
            "SELECT alert_type, typeof(alert_type), status, typeof(status) FROM alert_records WHERE id = ?",
            (record.id,),
        ).fetchone()
        assert tuple(stored_record) == ("phone_call", "text", "no-answer", "text")
        assert db.get_event_by_id(event.id).alert_status == AlertStatus.RETRY_PENDING
        (read_back,) = db.get_alert_records(event.id)
        assert (read_back.alert_type, read_back.status) == (AlertType.PHONE_CALL, CallStatus.NO_ANSWER)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.1, 4.5: module size and the shared source loader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["state_machine", "formatting", "routing", "ledger", "call_round"])
def test_alert_modules_under_400_lines(module):
    path = SENTINEL_DIR / "alerts" / f"{module}.py"
    lines = path.read_bytes().count(b"\n")  # what ``wc -l`` counts
    assert lines <= 400, f"{path.relative_to(REPO_ROOT)} has {lines} lines"


def _article(db: Database, number: int) -> Article:
    now = datetime.now(UTC)
    article = Article(
        source_name=f"Źródło {number}",
        source_url=f"https://example.com/{uuid4()}",
        source_type="rss",
        title=f"Atak na Polskę, relacja {number}",
        summary="Rosyjskie wojska przekroczyły granicę.",
        language="pl",
        published_at=now,
        fetched_at=now,
    )
    db.insert_article(article)
    return article


@pytest.mark.parametrize("is_update", [False, True], ids=["event", "update"])
def test_push_data_reads_each_article_once(db, config, is_update):
    """One push reads each article of the event once, for its SMS text and its source list together."""
    articles = [_article(db, number) for number in range(3)]
    now = datetime.now(UTC)
    event = Event(
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosyjskie wojska przekroczyły granicę Polski.",
        first_seen_at=now,
        last_updated_at=now,
        source_count=4,
        article_ids=[article.id for article in articles] + [str(uuid4())],
    )

    with patch.object(db, "get_article_by_id", wraps=db.get_article_by_id) as lookup:
        data = build_push_data(event, db, config, is_update=is_update)

    assert sorted(call.args[0] for call in lookup.call_args_list) == sorted(event.article_ids)
    sms_text = format_update_sms if is_update else format_sms_message
    assert data["sms_body"] == sms_text(event, db, config)
    assert [source["name"] for source in data["sources"]] == [article.source_name for article in articles] + ["źródło"]


# ---------------------------------------------------------------------------
# 4.1: the delivery ledger
# ---------------------------------------------------------------------------


def _record(alert_type: str, status: str, revision: int = 1) -> AlertRecord:
    return AlertRecord(
        event_id="event-1",
        alert_type=alert_type,
        twilio_sid=f"X{uuid4().hex}",
        status=status,
        attempt_number=1,
        sent_at=datetime.now(UTC),
        message_body="Alarm",
        event_revision=revision,
    )


@pytest.mark.parametrize(
    ("records", "channel", "revision", "delivered"),
    [
        ([], "sms", 1, False),
        ([("sms", "sent", 1)], "sms", 1, True),
        ([("sms_update", "delivered", 2)], "sms", 2, True),
        ([("sms", "acknowledged", 1)], "sms", 1, True),
        # A failed attempt never suppresses the retry.
        ([("sms", "failed", 1)], "sms", 1, False),
        ([("push", "failed", 1)], "push", 1, False),
        # Another revision or another channel does not count.
        ([("sms", "sent", 1)], "sms", 2, False),
        ([("sms", "sent", 1)], "push", 1, False),
        ([("phone_call", "acknowledged", 1)], "sms", 1, False),
        ([("push", "sent", 1)], "push", 1, True),
        ([("push", "failed", 2), ("push", "sent", 2)], "push", 2, True),
    ],
)
def test_channel_delivered(records, channel, revision, delivered):
    assert channel_delivered([_record(*record) for record in records], channel, revision) is delivered


@pytest.mark.parametrize(
    ("records", "new_revision"),
    [
        ([], False),
        ([("sms", "sent", 1)], True),
        ([("push", "delivered", 1)], True),
        # Only a successful earlier attempt makes the current revision an update.
        ([("sms", "failed", 1), ("push", "failed", 1)], False),
        ([("phone_call", "completed", 1)], False),
        # A delivery of the current revision is not an earlier one.
        ([("sms", "sent", 2), ("push", "sent", 2)], False),
    ],
)
def test_has_new_delivered_revision(records, new_revision):
    now = datetime.now(UTC)
    event = Event(
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosyjskie wojska przekroczyły granicę Polski.",
        first_seen_at=now,
        last_updated_at=now,
        source_count=1,
        article_ids=[],
        notification_revision=2,
    )
    assert has_new_delivered_revision(event, [_record(*record) for record in records]) is new_revision


def test_is_acknowledged_and_has_pending_call():
    assert is_acknowledged([_record("sms", "sent"), _record("phone_call", "acknowledged")]) is True
    assert is_acknowledged([_record("sms", "delivered"), _record("phone_call", "completed")]) is False
    assert is_acknowledged([]) is False

    assert has_pending_call([_record("phone_call", "initiated")]) is True
    assert has_pending_call([_record("phone_call", "ringing")]) is True
    assert has_pending_call([_record("phone_call", "no-answer"), _record("phone_call", "completed")]) is False
    assert has_pending_call([_record("sms", "initiated")]) is False
    assert has_pending_call([]) is False
