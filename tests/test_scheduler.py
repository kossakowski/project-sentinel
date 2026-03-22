"""Tests for sentinel.scheduler -- 5 scheduler tests per spec."""

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sentinel.scheduler import (
    CycleResult,
    HealthStatus,
    PipelineStats,
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
                cycle_start=datetime.now(timezone.utc),
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

    with open(health_path, "r") as f:
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
