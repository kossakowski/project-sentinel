"""Durable retry, atomic grouping and degraded health regression tests."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.classification.openai_provider import ClassificationError
from sentinel.database import Database
from sentinel.models import ClassificationResult
from sentinel.processing.deduplicator import Deduplicator
from sentinel.scheduler import PipelineStats, SentinelPipeline, SentinelScheduler


def build_pipeline(config, db, classifier):
    config.classification.incident_memory.enabled = True
    pipeline = SentinelPipeline.__new__(SentinelPipeline)
    pipeline.config = config
    pipeline.db = db
    pipeline.normalizer = SimpleNamespace(normalize_batch=lambda articles: articles)
    pipeline.deduplicator = Deduplicator(db, config)
    pipeline.keyword_filter = SimpleNamespace(filter_batch=lambda articles: articles)
    pipeline.enricher = SimpleNamespace(enrich_batch=AsyncMock(side_effect=lambda articles: articles))
    pipeline.classifier = classifier
    pipeline.corroborator = Corroborator(db, config)
    pipeline.incident_memory = IncidentMemory(db, config)
    pipeline.dispatcher = SimpleNamespace(dispatch=AsyncMock())
    pipeline.state_machine = SimpleNamespace(check_pending_calls=AsyncMock())
    pipeline.logger = logging.getLogger("test.queue")
    pipeline.stats = PipelineStats()
    pipeline.fetchers = []
    pipeline._cycle_lock = asyncio.Lock()
    pipeline.diagnostic_data = None
    return pipeline


def result_for(article):
    return ClassificationResult(
        article_id=article.id,
        is_military_event=True,
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.99,
        summary_pl="Rosja zaatakowała Polskę.",
        classified_at=datetime.now(UTC),
        model_used="fake",
        input_tokens=1,
        output_tokens=1,
        incident_memory=dict(decision="new", matched_event_id=None, confidence=0.99, reason="New attack"),
    )


@pytest.mark.asyncio
async def test_failed_article_retries_after_restart_without_refetch(config, sample_article, tmp_path):
    path = str(tmp_path / "queue.db")
    config.database.path = path
    first = Database(path)
    failed = build_pipeline(
        config, first, SimpleNamespace(classify=AsyncMock(side_effect=ClassificationError("quota")))
    )
    failed._fetch_all = AsyncMock(return_value=[sample_article])
    cycle = await failed.run_cycle()
    assert cycle.articles_classified == 0
    assert first.classification_health() == dict(pending=1, failed=1, degraded=True)
    scheduler = SentinelScheduler(failed, config)
    scheduler._update_health(True, cycle)
    health = json.loads((tmp_path / "health.json").read_text())
    assert health["is_healthy"] is False and health["classification_status"]["failed"] == 1
    assert first.pending_classifications(100) == []  # Backoff applies.
    first.close()
    second = Database(path)
    with second.conn:
        second.conn.execute("UPDATE classification_queue SET next_attempt_at='2000-01-01'")
    classifier = SimpleNamespace(classify=AsyncMock(side_effect=lambda article, **kw: result_for(article)))
    recovered = build_pipeline(config, second, classifier)
    recovered._fetch_all = AsyncMock(return_value=[])
    cycle = await recovered.run_cycle()
    assert cycle.articles_classified == 1
    assert classifier.classify.call_args.args[0].id == sample_article.id
    assert second.classification_health()["pending"] == 0
    assert second.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    recovered._fetch_all = AsyncMock(return_value=[sample_article])
    await recovered.run_cycle()
    assert classifier.classify.await_count == 1
    assert second.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    second.close()


@pytest.mark.asyncio
async def test_grouping_failure_rolls_back_classification_and_event(config, sample_article, db):
    classifier = SimpleNamespace(classify=AsyncMock(side_effect=lambda article, **kw: result_for(article)))
    pipeline = build_pipeline(config, db, classifier)
    pipeline._fetch_all = AsyncMock(return_value=[sample_article])
    original = pipeline.corroborator.process_classifications

    def broken(results):
        original(results)
        raise RuntimeError("Interrupted after event insertion")

    with patch.object(pipeline.corroborator, "process_classifications", side_effect=broken):
        await pipeline.run_cycle()
    assert db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert db.classification_health()["failed"] == 1
    with db.conn:
        db.conn.execute("UPDATE classification_queue SET next_attempt_at='2000-01-01'")
    pipeline._fetch_all = AsyncMock(return_value=[])
    await pipeline.run_cycle()
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert db.classification_health()["pending"] == 0


def test_pending_work_survives_retention_and_is_chronological(db, sample_article):
    old = sample_article
    old.fetched_at = datetime.now(UTC) - timedelta(days=50)
    db.insert_article(old)
    db.enqueue_classification(old)
    db.cleanup_old_records(article_days=1, event_days=1)
    assert db.pending_classifications(10)[0].id == old.id


def test_historic_articles_are_not_bulk_reclassified(db, sample_article):
    db.insert_article(sample_article)
    db._migrate_schema()
    assert db.pending_classifications(10) == []
    assert db.article_exists(sample_article.url_hash)
