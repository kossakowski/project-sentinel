"""Failure paths before alerting (refactor Phase 2: 2.9, 2.10, 2.11, 2.12).

A broken incident-memory row, a failed enrichment gate or a summary cut off
mid-entity must not stop an article from being classified and alerted, and a
dry run must not poll Twilio. The two cycle tests drive the real
``SentinelPipeline.run_cycle`` on the live config with the same edge fakes as
``test_safety_net_golden.py``: OpenAI through ``httpx.MockTransport``, the
Twilio SDK autospecced, ``ExpoPushClient.send_push`` autospecced.
"""

import asyncio
import functools
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import openai
import pytest

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.classification.classifier import Classifier
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.classification.openai_provider import ClassificationError
from sentinel.database import Database
from sentinel.models import AlertRecord, Article, Event
from sentinel.processing.enricher import ArticleEnricher
from sentinel.scheduler import SentinelPipeline
from sentinel.utils import strip_html
from tests.test_safety_net_golden import CRITICAL, GOLDEN_CODE, _FixedArticleFetcher, _responses_api_reply

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(title: str = "Atak na Polskę", summary: str = "Rosyjskie wojska przekroczyły granicę.") -> Article:
    now = datetime.now(UTC)
    return Article(
        source_name="PAP",
        source_url=f"https://www.pap.pl/aktualnosci/{uuid4()}",
        source_type="rss",
        title=title,
        summary=summary,
        language="pl",
        published_at=now,
        fetched_at=now,
    )


def _store_event(db: Database, summary_pl: str, *, minutes_ago: int, now: datetime | None = None) -> Event:
    when = (now or datetime.now(UTC)) - timedelta(minutes=minutes_ago)
    event = Event(
        event_type="drone_attack",
        urgency_score=7,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl=summary_pl,
        first_seen_at=when,
        last_updated_at=when,
        source_count=1,
        article_ids=[],
    )
    db.insert_event(event)
    return event


def _corrupt(db: Database, event_id: str, **columns: str) -> None:
    """Overwrite raw columns of one event row, as a manual edit or a bad migration would."""
    assignments = ", ".join(f"{column} = ?" for column in columns)
    with db.transaction():
        db.conn.execute(f"UPDATE events SET {assignments} WHERE id = ?", [*columns.values(), event_id])


@dataclass
class CycleOutcome:
    purposes: list[str]
    events: list[Event]
    queue: dict
    enrichment_seen_by_classifier: list[dict]


async def _run_critical_cycle(config, monkeypatch, now, *, gate_response: httpx.Response | None = None):
    """One real ``run_cycle`` for the golden urgency-10 Polish article.

    ``gate_response`` replaces the OpenAI answer to the enrichment gate.
    """
    purposes: list[str] = []
    model = config.classification.model

    def openai_handler(request: httpx.Request) -> httpx.Response:
        purpose = json.loads(request.content)["text"]["format"]["name"]
        purposes.append(purpose)
        if purpose == "enrichment_quality":
            if gate_response is not None:
                return gate_response
            data = {"needs_enrichment": False, "reason": "Tytuł i opis wskazują miejsce i zdarzenie."}
        elif purpose == "classification":
            data = CRITICAL.answer
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

    enrichment_seen: list[dict] = []
    real_classify = Classifier.classify

    async def classify_and_record_enrichment(self, article, **kwargs):
        enrichment_seen.append(dict(article.raw_metadata.get("enrichment", {})))
        return await real_classify(self, article, **kwargs)

    monkeypatch.setattr(Classifier, "classify", classify_and_record_enrichment)

    article = Article(
        source_name=CRITICAL.source_name,
        source_url=CRITICAL.source_url,
        source_type="rss",
        title=CRITICAL.title,
        summary=CRITICAL.summary,
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
        await pipeline.run_cycle()
        rows = pipeline.db.conn.execute("SELECT id FROM events WHERE summary_pl = ?", (CRITICAL.answer["summary_pl"],))
        events = [pipeline.db.get_event_by_id(row["id"]) for row in rows]
        queue = pipeline.db.classification_health()
    finally:
        await pipeline.shutdown()
    return CycleOutcome(purposes, events, queue, enrichment_seen)


# ---------------------------------------------------------------------------
# 2.9: a malformed memory row is skipped; a memory failure does not fail the article
# ---------------------------------------------------------------------------


def test_bad_memory_row_is_skipped(config, db, caplog):
    newest = _store_event(db, "Dron nad Rzeszowem.", minutes_ago=5)
    bad_json = _store_event(db, "Uszkodzony wiersz z listą artykułów.", minutes_ago=10)
    bad_time = _store_event(db, "Uszkodzony wiersz z datą.", minutes_ago=15)
    oldest = _store_event(db, "Dron nad Białymstokiem.", minutes_ago=20)
    _corrupt(db, bad_json.id, article_ids="not json")
    _corrupt(db, bad_time.id, first_seen_at="garbage")

    with caplog.at_level(logging.WARNING, logger="sentinel.classification.incident_memory"):
        candidates = IncidentMemory(db, config).candidates(_article())

    assert [candidate["id"] for candidate in candidates] == [newest.id, oldest.id]
    assert bad_json.id in caplog.text
    assert bad_time.id in caplog.text


def test_incident_that_cannot_be_described_is_skipped(config, db, monkeypatch, caplog):
    kept = _store_event(db, "Dron nad Rzeszowem.", minutes_ago=5)
    broken = _store_event(db, "Incydent bez dowodów.", minutes_ago=10)
    real_evidence = db.get_event_evidence

    def evidence(event_id, limit=3):
        if event_id == broken.id:
            raise ValueError("malformed classification row")
        return real_evidence(event_id, limit)

    monkeypatch.setattr(db, "get_event_evidence", evidence)

    with caplog.at_level(logging.WARNING, logger="sentinel.classification.incident_memory"):
        candidates = IncidentMemory(db, config).candidates(_article())

    assert [candidate["id"] for candidate in candidates] == [kept.id]
    assert broken.id in caplog.text


def test_healthy_memory_unchanged(config, db):
    """Without malformed rows the candidate list is what the database query returns."""
    events = [_store_event(db, f"Incydent {n}.", minutes_ago=n) for n in range(1, 4)]

    candidates = IncidentMemory(db, config).candidates(_article())

    assert {candidate["id"] for candidate in candidates} == {event.id for event in events}
    assert candidates[0]["id"] == events[0].id


@pytest.mark.asyncio
async def test_malformed_memory_row_does_not_block_a_critical_alert(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push
):
    """One corrupt row inside the lookback window used to fail every article until it aged out.

    The row's timestamp is corrupt. (A corrupt ``article_ids`` JSON is skipped by
    incident memory too, see above, but the corroborator's article-replay query
    reads that column with SQLite's ``json_each`` as well.)
    """
    db = Database(prod_config.database.path)
    try:
        corrupt = _store_event(db, "Wcześniejszy incydent.", minutes_ago=30, now=freeze_time)
        _corrupt(db, corrupt.id, first_seen_at="garbage")
    finally:
        db.close()

    outcome = await _run_critical_cycle(prod_config, monkeypatch, freeze_time)

    assert outcome.purposes == ["enrichment_quality", "classification"]
    assert outcome.queue["pending"] == 0
    assert [event.urgency_score for event in outcome.events] == [10]
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert expo_send_push.call_count == 1


@pytest.mark.asyncio
async def test_memory_failure_classifies_without_memory(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push, caplog
):
    def memory_unavailable(self, article):
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr(IncidentMemory, "candidates", memory_unavailable)

    with caplog.at_level(logging.ERROR, logger="sentinel.pipeline"):
        outcome = await _run_critical_cycle(prod_config, monkeypatch, freeze_time)

    assert "classifying it without memory" in caplog.text
    assert outcome.purposes == ["enrichment_quality", "classification"]
    # Classified (not failed and re-queued), grouped as a new event, and alerted.
    assert outcome.queue["pending"] == 0
    assert [event.urgency_score for event in outcome.events] == [10]
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries


# ---------------------------------------------------------------------------
# 2.10: the enrichment gate fails open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_gate_error_still_classifies(
    prod_config, monkeypatch, freeze_time, instant_alert_sleep, twilio_sdk, expo_send_push
):
    rate_limited = httpx.Response(
        429, json={"error": {"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}}
    )

    outcome = await _run_critical_cycle(prod_config, monkeypatch, freeze_time, gate_response=rate_limited)

    assert outcome.purposes == ["enrichment_quality", "classification"]
    assert outcome.enrichment_seen_by_classifier == [{"method": "gate_error", "error": "ClassificationError"}]
    assert outcome.queue["pending"] == 0
    assert [event.urgency_score for event in outcome.events] == [10]
    assert twilio_sdk.calls.create.call_count == prod_config.alerts.acknowledgment.max_call_retries
    assert expo_send_push.call_count == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_gate_error_is_recorded_and_no_page_is_fetched(provider, caplog):
    config = MagicMock()
    config.classification.provider = provider
    enricher = ArticleEnricher(config)
    article = _article(
        title="Dwa obce drony rozbiły się na Łotwie",
        summary="Dwa obce drony wleciały na Łotwę z Rosji i rozbiły się 40 km od granicy z Rosją, podała agencja.",
    )
    gate = "_check_vagueness_direct" if provider == "openai" else "_check_vagueness_llm"
    failure = ClassificationError("OpenAI refused classification; article remains pending")
    gate_mock = AsyncMock(side_effect=failure) if provider == "openai" else MagicMock(side_effect=failure)

    with (
        patch.object(enricher, gate, gate_mock),
        patch.object(enricher, "_fetch_body", new_callable=AsyncMock) as fetch_body,
        caplog.at_level(logging.WARNING, logger="sentinel.enricher"),
    ):
        result = asyncio.run(enricher.enrich_batch([article]))

    assert result == [article]
    assert article.raw_metadata["enrichment"] == {"method": "gate_error", "error": "ClassificationError"}
    assert article.summary.startswith("Dwa obce drony wleciały")
    fetch_body.assert_not_awaited()
    assert "Enrichment gate failed" in caplog.text


# ---------------------------------------------------------------------------
# 2.11: strip_html keeps text that ends in a cut-off entity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rosyjskie drony nad Polską. Więcej &raquo", "Rosyjskie drony nad Polską. Więcej »"),
        ("Russian missile hit Rzeszow &hellip", "Russian missile hit Rzeszow &hellip"),
        ("x <b>y</b> tail &", "x y tail &"),
        ("<p>Atak na <b>Polskę</b> &amp; Litwę</p>", "Atak na Polskę & Litwę"),
    ],
)
def test_strip_html_truncated_entity(raw, expected):
    assert strip_html(raw) == expected


# ---------------------------------------------------------------------------
# 2.12: --dry-run skips the pending-call check
# ---------------------------------------------------------------------------


def _pipeline_with_pending_call(config, tmp_path) -> SentinelPipeline:
    config.database.path = str(tmp_path / "sentinel.db")
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)
    pipeline.classifier.aclose = AsyncMock()
    event = _store_event(pipeline.db, "Rosyjskie wojska przekroczyły granicę.", minutes_ago=5)
    pipeline.db.insert_alert_record(
        AlertRecord(
            event_id=event.id,
            alert_type="phone_call",
            twilio_sid="CA00000000000000000000000000000001",
            status="initiated",
            attempt_number=1,
            sent_at=datetime.now(UTC),
            message_body="Alarm",
        )
    )
    pipeline.twilio_client.get_call_status.return_value = {"status": "no-answer", "duration": 0}
    return pipeline


@pytest.mark.asyncio
async def test_dry_run_skips_pending_calls(config, tmp_path):
    config.testing.dry_run = True
    pipeline = _pipeline_with_pending_call(config, tmp_path)
    try:
        await pipeline.run_cycle()

        pipeline.twilio_client.get_call_status.assert_not_called()
        assert [record.status for record in pipeline.db.get_pending_call_records()] == ["initiated"]
    finally:
        await pipeline.shutdown()


@pytest.mark.asyncio
async def test_live_run_still_checks_pending_calls(config, tmp_path):
    pipeline = _pipeline_with_pending_call(config, tmp_path)
    try:
        await pipeline.run_cycle()

        pipeline.twilio_client.get_call_status.assert_called_once_with("CA00000000000000000000000000000001")
        assert pipeline.db.get_pending_call_records() == []
    finally:
        await pipeline.shutdown()
