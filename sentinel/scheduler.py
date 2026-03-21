"""Pipeline orchestrator and scheduler for Project Sentinel.

Contains the SentinelPipeline (fetch -> process -> classify -> alert cycle)
and SentinelScheduler (APScheduler wrapper with jitter, coalesce, health monitoring).
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.classification.classifier import Classifier
from sentinel.classification.corroborator import Corroborator
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.fetchers import (
    GDELTFetcher,
    GoogleNewsFetcher,
    RSSFetcher,
    TelegramFetcher,
)
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import Article
from sentinel.processing.deduplicator import Deduplicator
from sentinel.processing.keyword_filter import KeywordFilter
from sentinel.processing.normalizer import Normalizer


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CycleResult:
    """Statistics from one pipeline run."""

    cycle_start: datetime
    duration_seconds: float
    articles_fetched: int
    articles_unique: int
    articles_relevant: int
    articles_classified: int
    events_created: int
    alerts_sent: int


@dataclass
class HealthStatus:
    """System health snapshot, written to data/health.json after each cycle."""

    is_healthy: bool
    last_cycle_at: str | None
    last_cycle_duration_seconds: float | None
    last_cycle_articles_fetched: int
    last_cycle_alerts_sent: int
    consecutive_failures: int
    last_error: str | None
    uptime_seconds: float
    db_size_bytes: int
    fetcher_status: dict[str, bool]


class PipelineStats:
    """Running statistics tracker across pipeline cycles."""

    def __init__(self) -> None:
        self.total_cycles: int = 0
        self.total_articles_fetched: int = 0
        self.total_events_detected: int = 0
        self.total_alerts_sent: int = 0
        self.consecutive_failures: int = 0
        self.fetcher_consecutive_failures: dict[str, int] = {}
        self.started_at: datetime = datetime.now(timezone.utc)
        self._daily_date: str | None = None
        self._daily_cycles: int = 0
        self._daily_articles: int = 0
        self._daily_events: int = 0
        self._daily_alerts: int = 0

    def record_cycle(self, result: CycleResult) -> None:
        """Record a successful cycle."""
        self.total_cycles += 1
        self.total_articles_fetched += result.articles_fetched
        self.total_events_detected += result.events_created
        self.total_alerts_sent += result.alerts_sent
        self.consecutive_failures = 0

        # Daily tracking
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_date != today:
            self._daily_date = today
            self._daily_cycles = 0
            self._daily_articles = 0
            self._daily_events = 0
            self._daily_alerts = 0

        self._daily_cycles += 1
        self._daily_articles += result.articles_fetched
        self._daily_events += result.events_created
        self._daily_alerts += result.alerts_sent

    def record_failure(self) -> None:
        """Record a pipeline failure."""
        self.consecutive_failures += 1

    def record_fetcher_success(self, fetcher_name: str) -> None:
        """Reset consecutive failure count for a fetcher."""
        self.fetcher_consecutive_failures[fetcher_name] = 0

    def record_fetcher_failure(self, fetcher_name: str) -> None:
        """Increment consecutive failure count for a fetcher."""
        current = self.fetcher_consecutive_failures.get(fetcher_name, 0)
        self.fetcher_consecutive_failures[fetcher_name] = current + 1

    def get_daily_summary(self) -> dict:
        """Return daily summary stats."""
        return {
            "cycles": self._daily_cycles,
            "articles_processed": self._daily_articles,
            "events_detected": self._daily_events,
            "alerts_sent": self._daily_alerts,
        }

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class SentinelPipeline:
    """Orchestrates the full fetch -> process -> classify -> alert pipeline."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.db = Database(config.database.path)
        self.fetchers: list[BaseFetcher] = self._init_fetchers()
        self.normalizer = Normalizer()
        self.deduplicator = Deduplicator(self.db, config)
        self.keyword_filter = KeywordFilter(config)
        self.classifier = Classifier(config)
        self.corroborator = Corroborator(self.db, config)
        self.twilio_client = TwilioClient(config)
        self.state_machine = AlertStateMachine(self.db, self.twilio_client, config)
        self.dispatcher = AlertDispatcher(self.state_machine, config)
        self.logger = logging.getLogger("sentinel.pipeline")
        self.stats = PipelineStats()

    def _init_fetchers(self) -> list[BaseFetcher]:
        """Initialize all fetchers based on config."""
        fetchers: list[BaseFetcher] = []

        # RSS is always added (individual source enabled/disabled handled internally)
        if self.config.sources.rss:
            fetchers.append(RSSFetcher(self.config))

        if self.config.sources.gdelt.enabled:
            fetchers.append(GDELTFetcher(self.config))

        if self.config.sources.google_news.enabled:
            fetchers.append(GoogleNewsFetcher(self.config))

        if self.config.sources.telegram.enabled:
            fetchers.append(TelegramFetcher(self.config))

        return fetchers

    async def startup(self) -> None:
        """Initialize components that need async startup (e.g. Telegram)."""
        for fetcher in self.fetchers:
            if hasattr(fetcher, "start"):
                try:
                    await fetcher.start()
                except Exception as e:
                    self.logger.error(
                        "Failed to start %s: %s", fetcher.name, e, exc_info=True
                    )

    async def shutdown(self) -> None:
        """Clean up components that need async shutdown."""
        for fetcher in self.fetchers:
            if hasattr(fetcher, "stop"):
                try:
                    await fetcher.stop()
                except Exception as e:
                    self.logger.error(
                        "Failed to stop %s: %s", fetcher.name, e, exc_info=True
                    )
        self.db.close()

    async def run_cycle(self) -> CycleResult:
        """Execute one full pipeline cycle. Returns stats about the run."""
        cycle_start = datetime.now(timezone.utc)
        self.logger.info("=== Pipeline cycle starting ===")

        # Step 1: Fetch from all sources
        raw_articles = await self._fetch_all()
        self.logger.info("Fetched %d raw articles", len(raw_articles))

        # Step 2: Normalize
        normalized = self.normalizer.normalize_batch(raw_articles)

        # Step 3: Deduplicate
        unique = self.deduplicator.deduplicate_batch(normalized)
        self.logger.info("After dedup: %d unique articles", len(unique))

        # Step 4: Keyword filter
        relevant = self.keyword_filter.filter_batch(unique)
        self.logger.info("After keyword filter: %d relevant articles", len(relevant))

        # Step 5: Classify (only if there are relevant articles)
        classifications = []
        if relevant:
            classifications = self.classifier.classify_batch(relevant)
            self.logger.info("Classified %d articles", len(classifications))

        # Step 6: Corroborate (group into events)
        events = self.corroborator.process_classifications(classifications)
        alertable_events = [e for e in events if e.alert_status != "pending"]
        self.logger.info("Events needing alerts: %d", len(alertable_events))

        # Step 7: Dispatch alerts
        self.dispatcher.dispatch(alertable_events)

        # Step 8: Check pending call statuses from previous cycles
        self.state_machine.check_pending_calls()

        # Step 9: Cleanup old records
        self.db.cleanup_old_records(
            article_days=self.config.database.article_retention_days,
            event_days=self.config.database.event_retention_days,
        )

        # Stats
        cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        result = CycleResult(
            cycle_start=cycle_start,
            duration_seconds=cycle_duration,
            articles_fetched=len(raw_articles),
            articles_unique=len(unique),
            articles_relevant=len(relevant),
            articles_classified=len(classifications),
            events_created=len(events),
            alerts_sent=len(alertable_events),
        )

        self.stats.record_cycle(result)

        self.logger.info(
            "=== Cycle complete in %.1fs: "
            "fetched=%d, unique=%d, relevant=%d, classified=%d, "
            "events=%d, alerts=%d ===",
            cycle_duration,
            result.articles_fetched,
            result.articles_unique,
            result.articles_relevant,
            result.articles_classified,
            result.events_created,
            result.alerts_sent,
        )

        return result

    async def _fetch_all(self) -> list[Article]:
        """Fetch from all enabled sources. Errors in one source don't affect others."""
        all_articles: list[Article] = []
        for fetcher in self.fetchers:
            try:
                articles = await fetcher.fetch()
                all_articles.extend(articles)
                self.logger.debug(
                    "%s: fetched %d articles", fetcher.name, len(articles)
                )
                self.stats.record_fetcher_success(fetcher.name)
            except Exception as e:
                self.logger.error(
                    "%s: fetch failed: %s", fetcher.name, e, exc_info=True
                )
                self.stats.record_fetcher_failure(fetcher.name)
                self._check_fetcher_health(fetcher.name)
        return all_articles

    def _check_fetcher_health(self, fetcher_name: str) -> None:
        """Check if a fetcher has failed too many times and take action."""
        failures = self.stats.fetcher_consecutive_failures.get(fetcher_name, 0)

        if failures >= 10:
            self.logger.error(
                "Fetcher %s has failed %d consecutive times",
                fetcher_name,
                failures,
            )
            # Send SMS notification (only once at the 10th failure)
            if failures == 10:
                self._send_system_sms(
                    f"Project Sentinel: zrodlo {fetcher_name} nie odpowiada "
                    f"od {failures} cykli. System nadal monitoruje pozostale zrodla."
                )
        elif failures >= 5:
            self.logger.warning(
                "Fetcher %s has failed %d consecutive times",
                fetcher_name,
                failures,
            )

    def _send_system_sms(self, message: str) -> None:
        """Send a system health SMS to the configured phone number."""
        try:
            phone = self.config.alerts.phone_number
            self.twilio_client.send_sms(phone, message, event_id="system")
        except Exception as e:
            self.logger.error("Failed to send system SMS: %s", e)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class SentinelScheduler:
    """APScheduler wrapper with jitter, max_instances=1, coalesce=True."""

    def __init__(self, pipeline: SentinelPipeline, config: SentinelConfig) -> None:
        self.pipeline = pipeline
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.logger = logging.getLogger("sentinel.scheduler")
        self._last_daily_summary: str | None = None

    def start(self) -> None:
        """Start the scheduler."""
        interval = self.config.scheduler.interval_minutes
        jitter = self.config.scheduler.jitter_seconds

        self.scheduler.add_job(
            self._run_with_error_handling,
            trigger=IntervalTrigger(minutes=interval, jitter=jitter),
            id="sentinel_pipeline",
            name="Project Sentinel Pipeline",
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.start()
        self.logger.info(
            "Scheduler started: interval=%dmin, jitter=%ds", interval, jitter
        )

    async def _run_with_error_handling(self) -> None:
        """Run the pipeline with top-level error handling."""
        try:
            result = await self.pipeline.run_cycle()
            self._update_health(healthy=True, result=result)
            self._maybe_log_daily_summary()
        except Exception as e:
            self.logger.critical("Pipeline cycle failed: %s", e, exc_info=True)
            self.pipeline.stats.record_failure()
            self._update_health(healthy=False, error=str(e))
            self._check_pipeline_health()

    def _check_pipeline_health(self) -> None:
        """Send SMS if the pipeline has failed too many consecutive times."""
        failures = self.pipeline.stats.consecutive_failures
        if failures == 3:
            self.pipeline._send_system_sms(
                "Project Sentinel: system napotkal krytyczny blad. Sprawdz logi."
            )

    def _update_health(
        self,
        healthy: bool,
        result: CycleResult | None = None,
        error: str | None = None,
    ) -> None:
        """Write health status to data/health.json."""
        stats = self.pipeline.stats

        # Compute DB file size
        db_path = self.config.database.path
        try:
            db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        except OSError:
            db_size = 0

        # Build per-fetcher health status
        fetcher_status = {}
        for fetcher in self.pipeline.fetchers:
            failures = stats.fetcher_consecutive_failures.get(fetcher.name, 0)
            fetcher_status[fetcher.name] = failures == 0

        health = HealthStatus(
            is_healthy=healthy,
            last_cycle_at=result.cycle_start.isoformat() if result else None,
            last_cycle_duration_seconds=result.duration_seconds if result else None,
            last_cycle_articles_fetched=result.articles_fetched if result else 0,
            last_cycle_alerts_sent=result.alerts_sent if result else 0,
            consecutive_failures=stats.consecutive_failures,
            last_error=error,
            uptime_seconds=stats.uptime_seconds,
            db_size_bytes=db_size,
            fetcher_status=fetcher_status,
        )

        health_path = os.path.join(
            os.path.dirname(self.config.database.path) or "data", "health.json"
        )
        os.makedirs(os.path.dirname(health_path) or ".", exist_ok=True)

        try:
            with open(health_path, "w", encoding="utf-8") as f:
                json.dump(asdict(health), f, indent=2, default=str)
        except OSError as e:
            self.logger.error("Failed to write health.json: %s", e)

    def _maybe_log_daily_summary(self) -> None:
        """Log a daily summary at date rollover."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_daily_summary != today:
            if self._last_daily_summary is not None:
                summary = self.pipeline.stats.get_daily_summary()
                self.logger.info(
                    "=== Daily summary: cycles=%d, articles_processed=%d, "
                    "events_detected=%d, alerts_sent=%d ===",
                    summary["cycles"],
                    summary["articles_processed"],
                    summary["events_detected"],
                    summary["alerts_sent"],
                )
            self._last_daily_summary = today

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self.scheduler.shutdown(wait=False)
        self.logger.info("Scheduler stopped")
