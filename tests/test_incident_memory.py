"""Regression coverage for the opt-in incident-memory grouping path.

All model and delivery seams in this module are fakes.  These tests exercise
identity decisions and the sequential pipeline wiring, not Haiku accuracy.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sentinel.classification.classifier import Classifier
from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.database import Database
from sentinel.models import Article, ClassificationResult, Event
from sentinel.scheduler import SentinelPipeline


def _enable_memory(config, *, max_candidates=5, max_text_chars=300):
    memory = config.classification.incident_memory
    memory.enabled = True
    memory.lookback_hours = 168
    memory.candidate_pool_size = 20
    memory.max_candidates = max_candidates
    memory.evidence_per_event = 2
    memory.max_text_chars = max_text_chars
    memory.min_confidence = 0.9
    return config


def _article(number, *, source="Example", title="Russian incident in Poland", summary="Incident details"):
    return Article(
        source_name=source,
        source_url=f"https://{source.lower()}.example/{number}",
        source_type="rss",
        title=title,
        summary=summary,
        language="pl",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )


def _result(
    article, *, event_type="airstrike", urgency=7, countries=None, summary="Rosyjski incydent w Polsce.", memory=None
):
    return ClassificationResult(
        article_id=article.id,
        is_military_event=True,
        event_type=event_type,
        urgency_score=urgency,
        affected_countries=countries if countries is not None else ["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.95,
        summary_pl=summary,
        classified_at=datetime.now(UTC),
        model_used="fake-haiku",
        input_tokens=1,
        output_tokens=1,
        incident_memory=memory
        or {"decision": "new", "matched_event_id": None, "confidence": 0.99, "reason": "new facts"},
    )


def _match(event_id, decision="duplicate", confidence=0.99):
    return {
        "decision": decision,
        "matched_event_id": event_id,
        "confidence": confidence,
        "reason": "Same place, time and physical incident.",
        "candidate_ids": [event_id],
    }


def _store_first(corroborator, db, article, **kwargs):
    assert db.insert_article(article)
    return corroborator.process_classifications([_result(article, **kwargs)])[0]


def test_onet_polsat_cross_type_duplicate_merges_with_memory(db, config):
    """The same scramble must merge even where old type compatibility rejects it."""
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    onet = _article(1, source="Onet", title="Polska poderwała myśliwce podczas rosyjskiego ataku")
    event = _store_first(
        corroborator,
        db,
        onet,
        event_type="airstrike",
        urgency=7,
        summary="Polska poderwała myśliwce podczas porannego ataku Rosji na Ukrainę.",
    )

    polsat = _article(2, source="Polsat", title="Alarm i start polskich samolotów po rosyjskim ostrzale")
    assert db.insert_article(polsat)
    updated = corroborator.process_classifications(
        [
            _result(
                polsat,
                event_type="troop_movement",
                urgency=7,
                summary="Te same poranne działania polskiego lotnictwa po ataku Rosji na Ukrainę.",
                memory=_match(event.id),
            )
        ]
    )[0]

    assert updated.id == event.id
    assert updated.source_count == 2
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_rusinowo_recovery_is_update_not_new_or_revision(db, config):
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    first = _article(1, source="Onet", title="Dron znaleziony na plaży w Rusinowie")
    event = _store_first(
        corroborator,
        db,
        first,
        event_type="drone_attack",
        urgency=7,
        summary="Dron znaleziono na plaży w Rusinowie.",
    )
    recovery = _article(2, source="Polsat", title="Wojsko zabrało drona z plaży w Rusinowie")
    assert db.insert_article(recovery)
    updated = corroborator.process_classifications(
        [
            _result(
                recovery,
                event_type="airspace_violation",
                urgency=7,
                summary="Ten sam dron z Rusinowa przekazano do badań.",
                memory=_match(event.id, "update"),
            )
        ]
    )[0]

    assert updated.id == event.id
    assert updated.notification_revision == 1
    assert updated.summary_pl == "Dron znaleziono na plaży w Rusinowie."


def test_acknowledged_critical_duplicate_stays_on_same_event(db, config):
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    first = _article(1, source="Onet")
    event = _store_first(corroborator, db, first, urgency=10, summary="Rakieta uderzyła w Polsce.")
    db.update_event(event.id, acknowledged_at=datetime.now(UTC).isoformat())

    repeat = _article(2, source="Polsat")
    assert db.insert_article(repeat)
    updated = corroborator.process_classifications(
        [
            _result(
                repeat,
                urgency=10,
                summary="To samo uderzenie rakiety w Polsce.",
                memory=_match(event.id),
            )
        ]
    )[0]

    assert updated.id == event.id
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_explicit_new_keeps_identical_critical_attack_separate(db, config):
    """Memory mode intentionally does not fall back to generic fuzzy grouping."""
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    first = _article(1, source="Onet")
    event = _store_first(corroborator, db, first, urgency=10, summary="Rakieta uderzyła w Polsce.")
    new_wave = _article(2, source="Polsat")
    assert db.insert_article(new_wave)
    created = corroborator.process_classifications(
        [
            _result(
                new_wave,
                urgency=10,
                summary="Rakieta uderzyła w Polsce.",
                memory={"decision": "new", "matched_event_id": None, "confidence": 0.99, "reason": "Nowa fala ataku."},
            )
        ]
    )[0]

    assert created.id != event.id
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_memory_match_cannot_cross_concrete_country_boundary(db, config):
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    poland = _article(1, source="Onet")
    event = _store_first(corroborator, db, poland, countries=["PL"], urgency=10)
    latvia = _article(2, source="Polsat")
    assert db.insert_article(latvia)
    created = corroborator.process_classifications(
        [
            _result(
                latvia,
                countries=["LV"],
                urgency=10,
                memory=_match(event.id),
            )
        ]
    )[0]

    assert created.id != event.id
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


@pytest.mark.parametrize(
    "raw_memory",
    [
        {"decision": "duplicate", "matched_event_id": "foreign-id", "confidence": 0.99, "reason": "same"},
        {"decision": "duplicate", "matched_event_id": "placeholder", "confidence": float("nan"), "reason": "same"},
    ],
    ids=["foreign-id", "nan-confidence"],
)
def test_invalid_memory_decisions_fail_open_to_new_event(db, config, raw_memory):
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    memory = IncidentMemory(db, config)
    first = _article(1, source="Onet")
    event = _store_first(corroborator, db, first)
    candidates = memory.candidates(_article(99, source="Probe"))
    assert candidates and candidates[0]["id"] == event.id

    incoming = _article(2, source="Polsat")
    assert db.insert_article(incoming)
    result = _result(incoming, memory=raw_memory)
    memory.validate(result, candidates)
    created = corroborator.process_classifications([result])[0]

    assert result.incident_memory["decision"] == "uncertain"
    assert created.id != event.id
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_first_critical_escalation_revises_summary_once(db, config):
    _enable_memory(config)
    corroborator = Corroborator(db, config)
    first = _article(1, source="Onet")
    event = _store_first(corroborator, db, first, urgency=7, summary="Wykryto niezidentyfikowany dron.")
    impact = _article(2, source="Polsat")
    assert db.insert_article(impact)
    escalated = corroborator.process_classifications(
        [
            _result(
                impact,
                urgency=10,
                summary="Potwierdzono uderzenie rosyjskiej rakiety w Polsce.",
                memory=_match(event.id),
            )
        ]
    )[0]
    repeat = _article(3, source="TVN")
    assert db.insert_article(repeat)
    stable = corroborator.process_classifications(
        [
            _result(
                repeat,
                urgency=10,
                summary="Potwierdzono uderzenie rosyjskiej rakiety w Polsce.",
                memory=_match(event.id),
            )
        ]
    )[0]

    assert escalated.notification_revision == 2
    assert escalated.summary_pl == "Potwierdzono uderzenie rosyjskiej rakiety w Polsce."
    assert stable.id == event.id
    assert stable.notification_revision == 2
    assert stable.summary_pl == escalated.summary_pl


class _IdentityStage:
    def normalize_batch(self, articles):
        return articles

    def deduplicate_batch(self, articles, **_kwargs):
        return articles

    def filter_batch(self, articles):
        return articles

    async def enrich_batch(self, articles):
        return articles


class _SequentialFakeClassifier:
    def __init__(self):
        self.contexts = []

    async def classify(self, article, *, incident_context):
        self.contexts.append(incident_context)
        if not incident_context:
            return _result(article)
        return _result(article, event_type="troop_movement", memory=_match(incident_context[0]["id"]))


@pytest.mark.asyncio
async def test_same_batch_second_classification_receives_first_event_memory(db, config):
    _enable_memory(config)
    first = _article(1, source="Onet")
    second = _article(2, source="Polsat")
    fake_classifier = _SequentialFakeClassifier()

    pipeline = SentinelPipeline.__new__(SentinelPipeline)
    pipeline.config = config
    pipeline.db = db
    pipeline.normalizer = _IdentityStage()
    pipeline.deduplicator = _IdentityStage()
    pipeline.keyword_filter = _IdentityStage()
    pipeline.enricher = _IdentityStage()
    pipeline.classifier = fake_classifier
    pipeline.corroborator = Corroborator(db, config)
    pipeline.incident_memory = IncidentMemory(db, config)
    pipeline.logger = logging.getLogger("test.incident_memory.pipeline")
    pipeline._cycle_lock = asyncio.Lock()
    pipeline.stats = SimpleNamespace(record_cycle=lambda _result: None)
    pipeline.diagnostic_data = None
    pipeline._fetch_all = AsyncMock(return_value=[first, second])
    pipeline.dispatcher = SimpleNamespace(dispatch=AsyncMock())
    pipeline.state_machine = SimpleNamespace(check_pending_calls=AsyncMock())

    result = await pipeline.run_cycle()

    assert result.articles_classified == 2
    assert fake_classifier.contexts[0] == []
    assert len(fake_classifier.contexts[1]) == 1
    assert fake_classifier.contexts[1][0]["id"] == db.get_memory_events(168, 1)[0].id
    assert db.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_candidate_context_is_bounded_and_survives_database_restart(tmp_path, config):
    config = _enable_memory(config, max_candidates=2, max_text_chars=100)
    path = str(tmp_path / "incident-memory-restart.db")
    first_db = Database(path)
    try:
        now = datetime.now(UTC)
        for number in range(4):
            first_db.insert_event(
                Event(
                    event_type="airstrike",
                    urgency_score=7,
                    affected_countries=["PL"],
                    aggressor="RU",
                    summary_pl=(f"Zdarzenie {number}: " + "x" * 300),
                    first_seen_at=now - timedelta(minutes=number),
                    last_updated_at=now - timedelta(minutes=number),
                    source_count=1,
                    article_ids=[],
                    notification_revision=2 if number == 0 else 1,
                )
            )
        before = IncidentMemory(first_db, config).candidates(_article(99, source="Probe"))
        assert len(before) == 2
        assert all(len(item["summary_pl"]) <= 100 for item in before)
        remembered_id = before[0]["id"]
    finally:
        first_db.close()

    restarted_db = Database(path)
    try:
        after = IncidentMemory(restarted_db, config).candidates(_article(100, source="Probe"))
        assert len(after) == 2
        assert after[0]["id"] == remembered_id
        assert after[0]["notification_revision"] == 2
    finally:
        restarted_db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("countries", [["PL"], None, "PL", [None, "PL", 4]])
async def test_classifier_uses_one_fake_provider_request_with_memory_context(config, countries):
    """Memory augments the existing request; it never creates a resolver request."""
    _enable_memory(config)
    article = _article(1)
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                text=(
                    '{"is_military_event":true,"event_type":"airstrike","urgency_score":7,'
                    '"affected_countries":["PL"],"aggressor":"RU","is_new_event":true,'
                    '"confidence":0.9,"summary_pl":"Test",'
                    '"incident_memory":{"decision":"uncertain","matched_event_id":null,"confidence":0.0,"reason":"none"}}'
                )
            )
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    payload = json.loads(response.content[0].text)
    payload["affected_countries"] = countries
    response.content[0].text = json.dumps(payload)
    create = AsyncMock(return_value=response)
    classifier = Classifier.__new__(Classifier)
    classifier.config = config
    classifier.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    classifier.logger = logging.getLogger("test.incident_memory.classifier")
    classifier._daily_input_tokens = 0
    classifier._daily_output_tokens = 0
    classifier._daily_date = None

    result = await classifier.classify(article, incident_context=[{"id": "event-1"}])
    assert result.affected_countries == (["PL"] if isinstance(countries, list) else [])

    create.assert_awaited_once()
    request = create.await_args.kwargs
    assert "INCIDENT MEMORY" in request["system"]
    assert request["messages"][0]["content"].count("Remembered incidents") == 1


def test_memory_keeps_similar_headlines_from_other_urls_but_not_exact_url_replays(config, db):
    from sentinel.processing.deduplicator import Deduplicator

    _enable_memory(config)
    first = _article(1)
    second = _article(2)
    second.title = first.title
    second.title_normalized = first.title_normalized
    dedup = Deduplicator(db, config)
    assert len(dedup.deduplicate_batch([first, second])) == 2
    assert dedup.deduplicate_batch([first, second]) == []


@pytest.mark.parametrize("invalid_decision", [[], {}, True, None])
def test_malformed_memory_decision_does_not_crash_classification(config, db, sample_classification, invalid_decision):
    _enable_memory(config)
    sample_classification.incident_memory = {"decision": invalid_decision, "confidence": 1, "reason": "invalid"}
    IncidentMemory(db, config).validate(sample_classification, [])
    assert sample_classification.incident_memory["decision"] == "uncertain"


@pytest.mark.parametrize(
    "old_text,new_text,expected",
    [
        ("Poniedziałkowy nalot drona", "Drone incursion on Tuesday", "new"),
        ("Incydent z 2026-09-14", "Incydent z 15.09.2026", "new"),
        ("Incydent z 2026-09-14", "Potwierdzono incydent z 14.09.2026", "duplicate"),
        ("Incydent we wtorek", "Tuesday's incident confirmed", "duplicate"),
    ],
)
def test_explicit_incident_time_conflicts_override_confident_model_match(config, db, old_text, new_text, expected):
    _enable_memory(config)
    config.classification.incident_memory.weekday_aliases = {
        "monday": ["monday", "poniedziałkowy"],
        "tuesday": ["wtorek", "tuesday"],
    }
    article = _article(1, title=new_text, summary=new_text)
    result = _result(article, urgency=9, memory=_match("old-event"))
    IncidentMemory(db, config).validate(result, [{"id": "old-event", "summary_pl": old_text}], article)
    assert result.incident_memory["decision"] == expected


@pytest.mark.parametrize("candidate_ids", [None, "old-event", [None]])
def test_corroborator_rejects_malformed_candidate_allowlist(config, db, candidate_ids):
    _enable_memory(config)
    article = _article(1)
    db.insert_article(article)
    memory = _match("old-event")
    memory["candidate_ids"] = candidate_ids
    events = Corroborator(db, config).process_classifications([_result(article, memory=memory)])
    assert len(events) == 1
    assert events[0].id != "old-event"
