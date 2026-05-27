"""Tests for sentinel.scheduler -- 5 scheduler tests per spec."""

import asyncio
import json
import os
import warnings
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sentinel.scheduler import (
    CycleResult,
    SentinelPipeline,
    SentinelScheduler,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def scheduler_config(sample_config_dict, tmp_path):
    """Create a SentinelConfig for scheduler tests with short interval."""
    sample_config_dict["database"]["path"] = str(tmp_path / "test.db")
    sample_config_dict["logging"]["file"] = str(tmp_path / "test.log")
    # Use very short interval for testing
    sample_config_dict["scheduler"]["interval_minutes"] = 1
    sample_config_dict["scheduler"]["jitter_seconds"] = 0

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
def mock_pipeline(scheduler_config):
    """Create a mocked pipeline for scheduler tests."""
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(scheduler_config)
        pipeline.run_cycle = AsyncMock(
            return_value=CycleResult(
                cycle_start=datetime.now(UTC),
                duration_seconds=1.0,
                articles_fetched=10,
                articles_unique=5,
                articles_relevant=2,
                articles_classified=2,
                events_created=0,
                alerts_sent=0,
            )
        )
        yield pipeline


# --------------------------------------------------------------------------
# 1. test_scheduler_fires_at_interval
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_fires_at_interval(mock_pipeline, scheduler_config):
    """Scheduler triggers pipeline at configured interval."""
    scheduler = SentinelScheduler(mock_pipeline, scheduler_config)
    scheduler.start()

    try:
        # Verify both fast-lane and slow-lane jobs were added
        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) == 2
        job_ids = {j.id for j in jobs}
        assert "sentinel_fast_lane" in job_ids
        assert "sentinel_slow_lane" in job_ids

        # The slow-lane trigger should have the configured interval
        slow_job = next(j for j in jobs if j.id == "sentinel_slow_lane")
        assert slow_job.trigger.interval.total_seconds() == scheduler_config.scheduler.interval_minutes * 60

        # The fast-lane trigger should use fast_interval_minutes
        fast_job = next(j for j in jobs if j.id == "sentinel_fast_lane")
        assert fast_job.trigger.interval.total_seconds() == scheduler_config.scheduler.fast_interval_minutes * 60
    finally:
        scheduler.stop()


# --------------------------------------------------------------------------
# 2. test_scheduler_jitter_applied
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_jitter_applied(sample_config_dict, tmp_path):
    """Execution time varies within jitter window."""
    sample_config_dict["database"]["path"] = str(tmp_path / "test.db")
    sample_config_dict["logging"]["file"] = str(tmp_path / "test.log")
    sample_config_dict["scheduler"]["interval_minutes"] = 15
    sample_config_dict["scheduler"]["jitter_seconds"] = 30

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)

    os.environ.setdefault("ALERT_PHONE_NUMBER", "+48123456789")

    from sentinel.config import load_config

    config = load_config(str(config_path))

    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)
        scheduler = SentinelScheduler(pipeline, config)
        scheduler.start()

        try:
            jobs = scheduler.scheduler.get_jobs()
            assert len(jobs) == 2

            # The slow-lane trigger should have full jitter
            slow_job = next(j for j in jobs if j.id == "sentinel_slow_lane")
            trigger = slow_job.trigger
            assert trigger.jitter is not None
            jitter_val = trigger.jitter
            if hasattr(jitter_val, "total_seconds"):
                assert jitter_val.total_seconds() == 30
            else:
                assert jitter_val == 30
        finally:
            scheduler.stop()


# --------------------------------------------------------------------------
# 3. test_max_instances_enforced
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_instances_enforced(mock_pipeline, scheduler_config):
    """Slow cycle doesn't cause concurrent execution."""
    scheduler = SentinelScheduler(mock_pipeline, scheduler_config)
    scheduler.start()

    try:
        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) == 2
        # max_instances is set on both jobs
        for job in jobs:
            assert job.max_instances == 1
    finally:
        scheduler.stop()


# --------------------------------------------------------------------------
# 4. test_scheduler_continues_after_error
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_continues_after_error(mock_pipeline, scheduler_config, tmp_path):
    """Pipeline error doesn't stop scheduler."""
    scheduler_config.database.path = str(tmp_path / "test.db")
    mock_pipeline.run_cycle = AsyncMock(side_effect=RuntimeError("Pipeline exploded"))

    scheduler = SentinelScheduler(mock_pipeline, scheduler_config)

    # Run the error handling wrapper directly -- should not raise
    await scheduler._run_with_error_handling()

    # Pipeline should have recorded a failure
    assert mock_pipeline.stats.consecutive_failures == 1

    # Health file should be written with is_healthy=False
    health_path = str(tmp_path / "health.json")
    assert os.path.exists(health_path)

    with open(health_path) as f:
        health = json.load(f)

    assert health["is_healthy"] is False
    assert health["last_error"] == "Pipeline exploded"


# --------------------------------------------------------------------------
# 5. test_graceful_shutdown
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_shutdown(mock_pipeline, scheduler_config):
    """Ctrl+C triggers clean shutdown."""
    scheduler = SentinelScheduler(mock_pipeline, scheduler_config)
    scheduler.start()

    # Verify scheduler is running
    assert scheduler.scheduler.running

    # Graceful shutdown should not raise
    scheduler.stop()

    # Yield control to the event loop so shutdown completes
    await asyncio.sleep(0.1)

    # After shutdown the internal state should indicate not running
    from apscheduler.schedulers.base import STATE_STOPPED

    assert scheduler.scheduler.state == STATE_STOPPED


# --------------------------------------------------------------------------
# Cycle serialization lock (SPEC_ASYNC_REFACTOR.md Phase 1)
# --------------------------------------------------------------------------


@pytest.fixture
def real_cycle_pipeline(scheduler_config):
    """Build a SentinelPipeline whose run_cycle is the real coroutine.

    Unlike ``mock_pipeline`` (which replaces run_cycle with an AsyncMock),
    this fixture keeps the real run_cycle so the cycle lock is exercised,
    but stubs out every component the cycle touches so no network/DB-heavy
    work runs. With no fetchers, _fetch_all returns [], which makes
    ``relevant`` empty so enrich/classify are skipped; the remaining steps
    are stubbed for safety.
    """
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(scheduler_config)

    # Stub the synchronous tail steps so a cycle completes cleanly.
    pipeline.normalizer.normalize_batch = MagicMock(return_value=[])
    pipeline.deduplicator.deduplicate_batch = MagicMock(return_value=[])
    pipeline.keyword_filter.filter_batch = MagicMock(return_value=[])
    pipeline.corroborator.process_classifications = MagicMock(return_value=[])
    # dispatch / check_pending_calls are now awaited by run_cycle, so they must
    # be AsyncMocks (a plain MagicMock is not awaitable).
    pipeline.dispatcher.dispatch = AsyncMock()
    pipeline.state_machine.check_pending_calls = AsyncMock()
    pipeline.db.cleanup_old_records = MagicMock()
    return pipeline


@pytest.mark.asyncio
async def test_run_cycle_serializes_concurrent_invocations(real_cycle_pipeline):
    """Two concurrent run_cycle calls never overlap (cross-lane serialization)."""
    state = {"current": 0, "max": 0}

    async def tracking_fetch_all(*args, **kwargs):
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        # Yield control so a second coroutine could interleave if unlocked.
        await asyncio.sleep(0)
        state["current"] -= 1
        return []

    real_cycle_pipeline._fetch_all = tracking_fetch_all

    await asyncio.gather(
        real_cycle_pipeline.run_cycle(),
        real_cycle_pipeline.run_cycle(),
    )

    # The lock must keep observed concurrency at 1 at all times.
    assert state["max"] == 1


@pytest.mark.asyncio
async def test_run_cycle_releases_lock_on_error(real_cycle_pipeline):
    """A failing cycle releases the lock so a later cycle still runs (no deadlock)."""
    boom = AsyncMock(side_effect=RuntimeError("fetch exploded"))
    real_cycle_pipeline._fetch_all = boom

    with pytest.raises(RuntimeError, match="fetch exploded"):
        await real_cycle_pipeline.run_cycle()

    # Lock must have been released by ``async with`` despite the exception.
    assert not real_cycle_pipeline._cycle_lock.locked()

    # A subsequent cycle must acquire the lock and complete normally.
    real_cycle_pipeline._fetch_all = AsyncMock(return_value=[])
    result = await asyncio.wait_for(real_cycle_pipeline.run_cycle(), timeout=5)
    assert isinstance(result, CycleResult)


@pytest.mark.asyncio
async def test_run_cycle_returns_result(real_cycle_pipeline):
    """A single run_cycle returns a CycleResult (existing behavior preserved)."""
    real_cycle_pipeline._fetch_all = AsyncMock(return_value=[])

    result = await real_cycle_pipeline.run_cycle()

    assert isinstance(result, CycleResult)
    assert result.articles_fetched == 0
    assert result.articles_classified == 0
    assert result.alerts_sent == 0


def test_cycle_lock_is_asyncio_lock(real_cycle_pipeline):
    """The pipeline's _cycle_lock attribute is an asyncio.Lock instance."""
    assert isinstance(real_cycle_pipeline._cycle_lock, asyncio.Lock)


# --------------------------------------------------------------------------
# Classifier client cleanup on shutdown (SPEC_ASYNC_REFACTOR.md req 2.5b)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_awaits_classifier_aclose(real_cycle_pipeline):
    """shutdown() awaits the classifier's aclose() exactly once (req 2.5b)."""
    real_cycle_pipeline.classifier.aclose = AsyncMock()

    await real_cycle_pipeline.shutdown()

    real_cycle_pipeline.classifier.aclose.assert_awaited_once()


# --------------------------------------------------------------------------
# Alert-path await wiring (SPEC_ASYNC_REFACTOR.md Phase 3, req 3.4a)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_awaits_dispatch_and_check_pending(real_cycle_pipeline):
    """Non-diagnostic run_cycle awaits dispatcher.dispatch and state_machine.check_pending_calls.

    Both are AsyncMocks; the cycle must await both exactly once and complete
    without raising an un-awaited-coroutine RuntimeWarning.
    """
    pipeline = real_cycle_pipeline

    # Produce one alertable event so dispatch is driven with real data
    # (alert_status != "pending" => included in alertable_events).
    event = SimpleNamespace(alert_status="phone_call")
    pipeline.corroborator.process_classifications = MagicMock(return_value=[event])

    dispatch = AsyncMock()
    check_pending = AsyncMock()
    pipeline.dispatcher.dispatch = dispatch
    pipeline.state_machine.check_pending_calls = check_pending

    # Turn an un-awaited-coroutine warning into an error so it fails the test.
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = await pipeline.run_cycle()

    dispatch.assert_awaited_once_with([event])
    check_pending.assert_awaited_once_with()
    assert isinstance(result, CycleResult)
