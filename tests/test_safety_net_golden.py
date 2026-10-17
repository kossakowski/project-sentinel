"""Golden end-to-end safety net for the alert path (refactor Phase 1).

These tests drive the real ``SentinelPipeline.run_cycle`` on the live
production config (``prod_config``): normalizer, dedup, keyword filter,
enricher, the OpenAI classifier with its budget ledger and Polish-summary
guard, incident memory, the corroborator, the dispatcher, the state machine
and the SQLite database are all real. Only the edges are fakes:

- the fetcher returns one fixed article;
- OpenAI answers through ``httpx.MockTransport`` (every provider instance,
  including the enricher's ``enrichment_quality`` gate);
- the Twilio SDK ``Client`` is autospecced, so the real ``TwilioClient`` runs;
- ``ExpoPushClient.send_push`` is autospecced;
- the clock is frozen (``freeze_time``) and the call-poll sleeps return at once;
- the confirmation code is the constant ``GOLDEN_CODE``.

The urgency-10 scenario writes nothing: it compares the exact push ``data``,
SMS bodies and TwiML against the files in ``tests/golden/``. Run pytest with
``--update-golden`` to rewrite them after an intended change, and review the
diff. The routing table golden pins ``resolve_action`` over urgency 0-10 and
1-3 sources on the live tiers; it is frozen, and ``--update-golden`` does not
rewrite it.
"""

import csv
import errno
import functools
import inspect
import io
import json
import re
import socket
from dataclasses import dataclass
from datetime import UTC, timedelta
from pathlib import Path

import httpx
import openai
import pytest

from sentinel.alerts.push_client import ExpoPushClient
from sentinel.alerts.routing import resolve_action
from sentinel.alerts.state_machine import SMS_SUMMARY_MAX_CHARS, AlertStateMachine
from sentinel.database import Database
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import AlertRecord, Article, Event
from sentinel.scheduler import CycleResult, SentinelPipeline

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_CODE = "246810"

# Keys of the push ``data`` dict that differ on every run; they are replaced
# with fixed placeholders (as is every ``*_at`` key) before comparing.
_VOLATILE_PUSH_KEYS = frozenset({"message_id", "event_id"})


# ---------------------------------------------------------------------------
# Scenario data
# ---------------------------------------------------------------------------

CRITICAL_SUMMARY_PL = (
    "Rosyjskie wojska przekroczyły granicę Polski od strony Białorusi i atakują pozycje "
    "Wojska Polskiego na Podlasiu. Władze wzywają mieszkańców regionu do pozostania w schronach."
)


def _answer(
    *,
    event_type: str,
    urgency: int,
    countries: list[str],
    summary_pl: str,
    is_military: bool = True,
    protection: str = "none",
) -> dict:
    """A schema-valid classification answer with a fresh-incident memory decision."""
    return {
        "is_military_event": is_military,
        "event_type": event_type,
        "urgency_score": urgency,
        "affected_countries": countries,
        "aggressor": "RU",
        "is_new_event": True,
        "confidence": 0.95,
        "summary_pl": summary_pl,
        "incident_memory": {
            "decision": "new",
            "matched_event_id": None,
            "confidence": 0.95,
            "reason": "Brak wcześniejszego incydentu w pamięci.",
        },
        "facts": {
            "attack_countries": countries,
            "protection": protection,
            "status": "active",
            "evidence": {"attack_countries": ", ".join(countries), "protection": "", "status": "trwa"},
        },
    }


@dataclass(frozen=True)
class Scenario:
    source_name: str
    source_url: str
    title: str
    summary: str
    answer: dict


CRITICAL = Scenario(
    source_name="PAP",
    source_url="https://www.pap.pl/aktualnosci/sentinel-golden-critical",
    title="Atak zbrojny na Polskę: rosyjskie wojska przekroczyły granicę pod Białymstokiem",
    summary=(
        "Rosyjskie oddziały pancerne wkroczyły na terytorium Polski od strony Białorusi. Wojsko Polskie "
        "prowadzi walki obronne, a władze wzywają mieszkańców województwa podlaskiego do pozostania w schronach."
    ),
    answer=_answer(
        event_type="invasion",
        urgency=10,
        countries=["PL"],
        summary_pl=CRITICAL_SUMMARY_PL,
        protection="official_warning",
    ),
)

MID_URGENCY = Scenario(
    source_name="PAP",
    source_url="https://www.pap.pl/aktualnosci/sentinel-golden-mid",
    title="Rosyjski dron uderzył w budynek na Litwie, trwa eskalacja napięcia",
    summary=(
        "Według litewskiej armii rosyjski dron uderzył w budynek gospodarczy w okolicach Wilna. "
        "Nikt nie został ranny, a wojsko zabezpiecza teren i bada szczątki maszyny."
    ),
    answer=_answer(
        event_type="drone_attack",
        urgency=7,
        countries=["LT"],
        summary_pl="Rosyjski dron uderzył w budynek gospodarczy na Litwie w okolicach Wilna; nikt nie został ranny.",
    ),
)

LOW_URGENCY = Scenario(
    source_name="PAP",
    source_url="https://www.pap.pl/aktualnosci/sentinel-golden-low",
    title="Atak militarny? Politycy komentują wypowiedź rosyjskiego ambasadora",
    summary=(
        "Polscy politycy krytykują wypowiedź rosyjskiego ambasadora o rzekomym ataku militarnym. "
        "Resort dyplomacji wezwał ambasadora na rozmowę, a wojsko nie odnotowało żadnego incydentu."
    ),
    # Military, so only the urgency (below the corroborator's _MIN_EVENT_URGENCY)
    # keeps this article from becoming an event.
    answer=_answer(
        event_type="other",
        urgency=3,
        countries=[],
        summary_pl="Polscy politycy krytykują wypowiedź rosyjskiego ambasadora; nie doszło do żadnego ataku.",
    ),
)


# ---------------------------------------------------------------------------
# Edge fakes and the cycle runner
# ---------------------------------------------------------------------------


class _FixedArticleFetcher(BaseFetcher):
    """Returns its articles on the first fetch, then nothing."""

    def __init__(self, config, articles: list[Article]) -> None:
        super().__init__(config)
        self._articles = list(articles)

    @property
    def name(self) -> str:
        return "golden_feed"

    async def fetch(self) -> list[Article]:
        batch, self._articles = self._articles, []
        return batch


def _responses_api_reply(data: dict, model: str) -> dict:
    """A completed OpenAI Responses API body carrying ``data`` as structured output."""
    return {
        "id": "resp_golden",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_golden",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(data, ensure_ascii=False), "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


@dataclass
class CycleOutcome:
    result: CycleResult
    events: list[Event]
    alert_records: list[AlertRecord]
    openai_purposes: list[str]


async def _run_golden_cycle(config, monkeypatch, scenario: Scenario, now) -> CycleOutcome:
    """Run one real ``run_cycle`` for ``scenario`` with only the edges faked."""
    purposes: list[str] = []
    model = config.classification.model

    def openai_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "api.openai.com":
            return httpx.Response(500, json={"error": {"message": f"unexpected host {request.url.host}"}})
        purpose = json.loads(request.content)["text"]["format"]["name"]
        purposes.append(purpose)
        if purpose == "enrichment_quality":
            data = {"needs_enrichment": False, "reason": "Tytuł i opis wskazują miejsce i zdarzenie."}
        elif purpose == "classification":
            data = scenario.answer
        else:
            return httpx.Response(500, json={"error": {"message": f"unexpected purpose {purpose}"}})
        return httpx.Response(200, json=_responses_api_reply(data, model))

    real_async_openai = openai.AsyncOpenAI

    def async_openai_on_mock_transport(**kwargs):
        kwargs["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(openai_handler))
        return real_async_openai(**kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(openai, "AsyncOpenAI", async_openai_on_mock_transport)

    article = Article(
        source_name=scenario.source_name,
        source_url=scenario.source_url,
        source_type="rss",
        title=scenario.title,
        summary=scenario.summary,
        language="pl",
        published_at=now - timedelta(minutes=5),
        fetched_at=now,
    )
    monkeypatch.setattr(SentinelPipeline, "_init_fetchers", lambda self: [_FixedArticleFetcher(self.config, [article])])
    monkeypatch.setattr(
        "sentinel.scheduler.AlertStateMachine",
        functools.partial(AlertStateMachine, code_factory=lambda: GOLDEN_CODE),
    )

    pipeline = SentinelPipeline(config)
    try:
        result = await pipeline.run_cycle()
        event_ids = [row["id"] for row in pipeline.db.conn.execute("SELECT id FROM events ORDER BY first_seen_at")]
        events = [pipeline.db.get_event_by_id(event_id) for event_id in event_ids]
        records = [record for event_id in event_ids for record in pipeline.db.get_alert_records(event_id)]
    finally:
        await pipeline.shutdown()
    return CycleOutcome(result=result, events=events, alert_records=records, openai_purposes=purposes)


def _push_data(call) -> dict:
    """The ``data`` argument of one recorded ``ExpoPushClient.send_push`` call."""
    bound = inspect.signature(ExpoPushClient.send_push).bind(*call.args, **call.kwargs)
    return bound.arguments["data"]


def _with_placeholders(value):
    """Replace run-specific ids and every ``*_at`` timestamp with fixed placeholders."""
    if isinstance(value, dict):
        return {
            key: f"<{key}>" if key in _VOLATILE_PUSH_KEYS or key.endswith("_at") else _with_placeholders(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_with_placeholders(item) for item in value]
    return value


def _assert_golden(name: str, text: str, update: bool) -> None:
    """Compare ``text`` with ``tests/golden/<name>`` byte for byte (or rewrite it under --update-golden)."""
    path = GOLDEN_DIR / name
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.is_file(), f"Missing golden file {path}; create it once with pytest --update-golden"
    expected = path.read_text(encoding="utf-8")
    if name.endswith(".json"):
        # Structured diff first, then the exact bytes (key order and formatting).
        assert json.loads(text) == json.loads(expected), f"{name} differs from the golden file"
    assert text == expected, f"{name} differs from the golden file"


def _json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# 1.6a / 1.6c: urgency 10 -> push, confirmation SMS, call round
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_article_calls_sms_and_pushes(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push, update_golden
):
    assert len(CRITICAL_SUMMARY_PL) < SMS_SUMMARY_MAX_CHARS

    outcome = await _run_golden_cycle(prod_config, monkeypatch, CRITICAL, freeze_time)

    # The article went through the enrichment gate and the classifier exactly once.
    assert outcome.openai_purposes == ["enrichment_quality", "classification"]
    assert outcome.result.articles_classified == 1
    assert len(outcome.events) == 1
    event = outcome.events[0]
    assert (event.urgency_score, event.source_count, event.affected_countries) == (10, 1, ["PL"])
    assert event.summary_pl == CRITICAL_SUMMARY_PL

    # One additive push, one confirmation SMS, max_call_retries calls.
    owner_phone = prod_config.alerts.phone_number
    max_calls = prod_config.alerts.acknowledgment.max_call_retries
    assert expo_send_push.call_count == 1
    assert twilio_sdk.messages.create.call_count == 1
    assert twilio_sdk.calls.create.call_count == max_calls
    assert all(call.kwargs["to"] == owner_phone for call in twilio_sdk.messages.create.call_args_list)
    assert all(call.kwargs["to"] == owner_phone for call in twilio_sdk.calls.create.call_args_list)
    sms_bodies = [call.kwargs["body"] for call in twilio_sdk.messages.create.call_args_list]
    assert GOLDEN_CODE in sms_bodies[0]

    # No reply arrived, so the round ends waiting for the next retry.
    assert event.alert_status == "retry_pending"
    assert event.acknowledged_at is None
    assert sorted(record.alert_type for record in outcome.alert_records) == ["phone_call"] * max_calls + [
        "push",
        "sms",
    ]

    # 1.6c: exact payloads against the golden files.
    push_data = _push_data(expo_send_push.call_args)
    assert push_data["event_id"] == event.id
    assert re.fullmatch(r"[0-9a-f]{32}", push_data["message_id"])
    assert push_data["first_seen_at"] == freeze_time.isoformat()
    twiml = [call.kwargs["twiml"] for call in twilio_sdk.calls.create.call_args_list]
    _assert_golden("critical_push_data.json", _json_text(_with_placeholders(push_data)), update_golden)
    _assert_golden("critical_sms_bodies.json", _json_text(sms_bodies), update_golden)
    _assert_golden("critical_call_twiml.json", _json_text(twiml), update_golden)


# ---------------------------------------------------------------------------
# 1.6b: urgency 7 -> push only; urgency 3 -> nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mid_urgency_article_pushes_only(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push
):
    outcome = await _run_golden_cycle(prod_config, monkeypatch, MID_URGENCY, freeze_time)

    assert outcome.openai_purposes == ["enrichment_quality", "classification"]
    assert [event.urgency_score for event in outcome.events] == [7]
    assert expo_send_push.call_count == 1
    assert twilio_sdk.messages.create.call_count == 0
    assert twilio_sdk.calls.create.call_count == 0
    assert [record.alert_type for record in outcome.alert_records] == ["push"]


@pytest.mark.asyncio
async def test_low_urgency_article_sends_nothing(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push
):
    outcome = await _run_golden_cycle(prod_config, monkeypatch, LOW_URGENCY, freeze_time)

    # Classified, but below every alerting tier: no event and no delivery.
    assert outcome.openai_purposes == ["enrichment_quality", "classification"]
    assert outcome.result.articles_classified == 1
    assert outcome.events == []
    assert expo_send_push.call_count == 0
    assert twilio_sdk.messages.create.call_count == 0
    assert twilio_sdk.calls.create.call_count == 0


def test_freeze_time_pins_python_and_sqlite_clock(freeze_time, tmp_path):
    """The helper pins datetime.now() in the alert-path modules and SQLite's 'now' in Database."""
    import sentinel.alerts.state_machine
    import sentinel.classification.classifier

    assert sentinel.classification.classifier.datetime.now(UTC) == freeze_time
    assert sentinel.alerts.state_machine.datetime.now(UTC) == freeze_time
    database = Database(str(tmp_path / "clock.db"))
    try:
        row = database.conn.execute(
            "SELECT datetime('now'), datetime('now', '-30 days'), julianday('now') = julianday(?)",
            (freeze_time.isoformat(),),
        ).fetchone()
    finally:
        database.close()
    assert tuple(row) == ("2026-10-16 12:00:00", "2026-09-16 12:00:00", 1)


# ---------------------------------------------------------------------------
# 1.10: routing table golden
# ---------------------------------------------------------------------------


def _routing_table_csv(config) -> str:
    """``resolve_action`` over urgency 0-10 x sources 1-3 on the given tiers, as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["urgency_score", "source_count", "action"])
    for score in range(0, 11):
        for source_count in (1, 2, 3):
            writer.writerow([score, source_count, resolve_action(config.alerts.urgency_levels, score, source_count)])
    return buffer.getvalue()


def test_routing_table_golden_matches_current_routing(prod_config):
    # 1.10: the table was generated once and is frozen, so --update-golden never rewrites it.
    _assert_golden("routing_table.csv", _routing_table_csv(prod_config), update=False)


# ---------------------------------------------------------------------------
# 1.3: the conftest network guard
# ---------------------------------------------------------------------------


def test_network_guard_blocks_outbound():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError, match="blocked during tests") as excinfo:
            sock.connect(("1.1.1.1", 443))
        assert excinfo.value.errno == errno.ENETUNREACH
        with pytest.raises(OSError, match="blocked during tests"):
            sock.connect_ex(("1.1.1.1", 443))
    finally:
        sock.close()
    datagram = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="blocked during tests"):
            datagram.sendto(b"probe", ("1.1.1.1", 53))
        with pytest.raises(OSError, match="blocked during tests"):
            datagram.sendmsg([b"probe"], [], 0, ("1.1.1.1", 53))
    finally:
        datagram.close()

    # A hostname is refused before any DNS query leaves the machine.
    with pytest.raises(OSError, match="blocked during tests"):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(OSError, match="blocked during tests"):
        socket.gethostbyname("example.com")
    with pytest.raises(OSError, match="blocked during tests"):
        socket.gethostbyname_ex("example.com")
    with pytest.raises(httpx.ConnectError, match="blocked during tests"):
        httpx.get("https://example.com/", timeout=1)


def test_network_guard_allows_loopback():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()
    assert socket.getaddrinfo("localhost", 80)
