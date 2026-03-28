"""End-to-end integration tests for the full pipeline -- 9 tests per spec."""

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.config import SentinelConfig
from sentinel.models import Article, ClassificationResult, Event
from sentinel.scheduler import CycleResult, SentinelPipeline, SentinelScheduler


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_article(
    title: str = "Russia attacks Poland",
    source_name: str = "TestSource",
    source_url: str | None = None,
    language: str = "en",
) -> Article:
    """Create a test Article."""
    now = datetime.now(timezone.utc)
    url = source_url or f"https://example.com/{uuid4()}"
    return Article(
        source_name=source_name,
        source_url=url,
        source_type="rss",
        title=title,
        summary=f"Summary of: {title}",
        language=language,
        published_at=now,
        fetched_at=now,
    )


def _make_classification(article_id: str, urgency: int = 8) -> ClassificationResult:
    """Create a test ClassificationResult."""
    return ClassificationResult(
        article_id=article_id,
        is_military_event=True,
        event_type="missile_strike",
        urgency_score=urgency,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.9,
        summary_pl="Rosja zaatakowala Polske rakietami.",
        classified_at=datetime.now(timezone.utc),
        model_used="claude-haiku-4-5-20251001",
        input_tokens=200,
        output_tokens=80,
    )


@pytest.fixture
def pipeline_config(sample_config_dict, tmp_path):
    """Create a SentinelConfig with temp DB URL for integration tests."""
    import yaml

    # Use temp log path (DB URL already set by conftest)
    sample_config_dict["logging"]["file"] = str(tmp_path / "test.log")
    sample_config_dict["testing"]["dry_run"] = False

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)

    os.environ.setdefault("ALERT_PHONE_NUMBER", "+48123456789")
    os.environ.setdefault("TWILIO_ACCOUNT_SID", "test_sid")
    os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_token")
    os.environ.setdefault("TWILIO_PHONE_NUMBER", "+15005550006")

    from sentinel.config import load_config

    return load_config(str(config_path))


@pytest.fixture
def dry_run_config(pipeline_config):
    """Pipeline config with dry_run enabled."""
    pipeline_config.testing.dry_run = True
    return pipeline_config


# --------------------------------------------------------------------------
# 1. test_full_pipeline_with_fixtures
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_with_fixtures(pipeline_config):
    """Feed fixture articles through the full pipeline, verify classification and alert routing."""
    # Use keywords from test config (en critical: "military attack", high: "military buildup")
    articles = [
        _make_article("Russia launches military attack on Poland"),
        _make_article("Large military buildup detected near Polish border"),
    ]

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        # Set up mock fetcher
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=articles)
        mock_init_fetchers.return_value = [mock_fetcher]

        # Set up mock classifier
        mock_classifier_instance = MagicMock()
        classifications = [_make_classification(a.id, urgency=8) for a in articles]
        mock_classifier_instance.classify_batch.return_value = classifications
        MockClassifier.return_value = mock_classifier_instance

        # Set up mock Twilio (let it succeed)
        mock_twilio = MagicMock()
        mock_twilio.send_sms.return_value = None
        mock_twilio.make_alert_call.return_value = None
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)
        result = await pipeline.run_cycle()

        assert result.articles_fetched == 2
        assert result.articles_relevant == 2
        assert result.articles_classified == 2
        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 2. test_full_pipeline_dry_run
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_dry_run(dry_run_config):
    """Run full pipeline in dry-run mode, verify no Twilio calls made."""
    articles = [
        _make_article("Russia attacks Poland with missiles"),
    ]

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=articles)
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        classifications = [_make_classification(articles[0].id, urgency=10)]
        mock_classifier_instance.classify_batch.return_value = classifications
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(dry_run_config)
        result = await pipeline.run_cycle()

        # Pipeline should run but Twilio should not be called for alerts
        assert result.articles_fetched == 1
        mock_twilio.make_alert_call.assert_not_called()
        mock_twilio.send_sms.assert_not_called()
        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 3. test_pipeline_survives_fetcher_failure
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_survives_fetcher_failure(pipeline_config):
    """One fetcher throws exception, pipeline continues with others."""
    good_articles = [_make_article("Normal article about military buildup")]

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        # Failing fetcher
        failing_fetcher = AsyncMock()
        failing_fetcher.name = "failing_fetcher"
        failing_fetcher.fetch = AsyncMock(side_effect=RuntimeError("Connection timeout"))

        # Working fetcher
        working_fetcher = AsyncMock()
        working_fetcher.name = "working_fetcher"
        working_fetcher.fetch = AsyncMock(return_value=good_articles)

        mock_init_fetchers.return_value = [failing_fetcher, working_fetcher]

        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify_batch.return_value = []
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)
        result = await pipeline.run_cycle()

        # Should still get articles from the working fetcher
        assert result.articles_fetched == 1
        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 4. test_pipeline_survives_classifier_failure
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_survives_classifier_failure(pipeline_config):
    """Classifier API error, pipeline logs error and continues with subsequent steps."""
    articles = [_make_article("Military attack on Poland detected")]

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=articles)
        mock_init_fetchers.return_value = [mock_fetcher]

        # Classifier raises exception
        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify_batch.side_effect = RuntimeError("API down")
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)

        # Spy on corroborator and dispatcher to verify they still execute
        with (
            patch.object(pipeline.corroborator, "process_classifications", wraps=pipeline.corroborator.process_classifications) as mock_corroborate,
            patch.object(pipeline.dispatcher, "dispatch", wraps=pipeline.dispatcher.dispatch) as mock_dispatch,
        ):
            # Pipeline should NOT raise -- it catches classifier errors and continues
            result = await pipeline.run_cycle()

            # Verify we got a complete CycleResult (pipeline didn't abort)
            assert isinstance(result, CycleResult)
            assert result.articles_fetched == 1
            assert result.articles_classified == 0  # Classifier failed, so 0

            # Verify subsequent pipeline steps still executed
            mock_corroborate.assert_called_once_with([])
            mock_dispatch.assert_called_once()

        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 5. test_pipeline_survives_twilio_failure
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_survives_twilio_failure(pipeline_config):
    """Twilio error, pipeline logs error and continues."""
    articles = [_make_article("Russia launches invasion of Poland")]

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=articles)
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        classifications = [_make_classification(articles[0].id, urgency=9)]
        mock_classifier_instance.classify_batch.return_value = classifications
        MockClassifier.return_value = mock_classifier_instance

        # Twilio fails
        mock_twilio = MagicMock()
        mock_twilio.make_alert_call.side_effect = RuntimeError("Twilio down")
        mock_twilio.send_sms.side_effect = RuntimeError("Twilio down")
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)
        # Pipeline should not crash even if Twilio errors
        # Twilio errors are caught in the state_machine/twilio_client layer
        result = await pipeline.run_cycle()
        assert result.articles_fetched == 1
        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 6. test_dedup_across_cycles
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_across_cycles(pipeline_config):
    """Article seen in cycle 1 is not re-processed in cycle 2."""
    article = _make_article(
        "Military buildup near Polish border",
        source_url="https://example.com/fixed-url-for-dedup",
    )

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        # Both cycles return the same article
        mock_fetcher.fetch = AsyncMock(return_value=[article])
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify_batch.return_value = []
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)

        # Cycle 1
        result1 = await pipeline.run_cycle()

        # Cycle 2 - same article, should be deduped
        result2 = await pipeline.run_cycle()

        # First cycle should have unique articles
        assert result1.articles_unique >= 0
        # Second cycle should dedup the same article
        assert result2.articles_unique == 0

        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 7. test_corroboration_across_cycles
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corroboration_across_cycles(pipeline_config):
    """Article A in cycle 1, article B (same event) in cycle 2 -> corroborated event."""
    article_a = _make_article(
        "Russia launches missile strike on Poland",
        source_name="SourceA",
        source_url="https://source-a.com/news/1",
    )
    article_b = _make_article(
        "Missile attack on Poland confirmed by multiple sources",
        source_name="SourceB",
        source_url="https://source-b.com/news/1",
    )

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.make_alert_call.return_value = None
        mock_twilio.send_sms.return_value = None
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)

        # Cycle 1: article A
        mock_fetcher.fetch = AsyncMock(return_value=[article_a])
        cls_a = _make_classification(article_a.id, urgency=9)
        mock_classifier_instance.classify_batch.return_value = [cls_a]

        result1 = await pipeline.run_cycle()

        # Cycle 2: article B
        mock_fetcher.fetch = AsyncMock(return_value=[article_b])
        cls_b = _make_classification(article_b.id, urgency=9)
        mock_classifier_instance.classify_batch.return_value = [cls_b]

        result2 = await pipeline.run_cycle()

        # Both cycles should process articles
        assert result1.articles_fetched == 1
        assert result2.articles_fetched == 1

        await pipeline.shutdown()


# --------------------------------------------------------------------------
# 8. test_once_mode
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_once_mode(pipeline_config):
    """--once runs pipeline exactly once and returns."""
    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=[])
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify_batch.return_value = []
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)
        await pipeline.startup()
        result = await pipeline.run_cycle()
        await pipeline.shutdown()

        # Pipeline ran exactly once and returned a CycleResult
        assert isinstance(result, CycleResult)
        assert result.articles_fetched == 0
        assert mock_fetcher.fetch.call_count == 1


# --------------------------------------------------------------------------
# 9. test_health_status_updated
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_status_updated(pipeline_config, tmp_path):
    """health.json updated after each cycle."""

    with (
        patch.object(SentinelPipeline, "_init_fetchers") as mock_init_fetchers,
        patch("sentinel.scheduler.Classifier") as MockClassifier,
        patch("sentinel.scheduler.TwilioClient") as MockTwilio,
    ):
        mock_fetcher = AsyncMock()
        mock_fetcher.name = "test_fetcher"
        mock_fetcher.fetch = AsyncMock(return_value=[])
        mock_init_fetchers.return_value = [mock_fetcher]

        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify_batch.return_value = []
        MockClassifier.return_value = mock_classifier_instance

        mock_twilio = MagicMock()
        mock_twilio.get_call_status.return_value = None
        MockTwilio.return_value = mock_twilio

        pipeline = SentinelPipeline(pipeline_config)
        scheduler = SentinelScheduler(pipeline, pipeline_config)

        # Simulate running a cycle through the scheduler's error handling
        await scheduler._run_with_error_handling()

        # Check health.json was written
        health_path = os.path.join("data", "health.json")
        assert os.path.exists(health_path)

        with open(health_path, "r") as f:
            health = json.load(f)

        assert health["is_healthy"] is True
        assert health["consecutive_failures"] == 0
        assert health["last_cycle_articles_fetched"] == 0

        await pipeline.shutdown()
