# Phase 6: Scheduler & Integration

## Objective
Wire all components together into a single pipeline, run it on a 15-minute schedule with APScheduler, handle errors gracefully so that a failure in one component doesn't crash the system, and provide health monitoring.

## Deliverables

### 6.1 Pipeline Orchestrator (`sentinel/scheduler.py`)

The core loop that runs every 15 minutes:

```python
class SentinelPipeline:
    """Orchestrates the full fetch → process → classify → alert pipeline."""

    def __init__(self, config: SentinelConfig):
        self.config = config
        self.db = Database(config.database.path)
        self.fetchers = self._init_fetchers()
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

    async def run_cycle(self) -> CycleResult:
        """Execute one full pipeline cycle. Returns stats about the run."""
        cycle_start = datetime.utcnow()
        self.logger.info("=== Pipeline cycle starting ===")

        # Step 1: Fetch from all sources
        raw_articles = await self._fetch_all()
        self.logger.info(f"Fetched {len(raw_articles)} raw articles")

        # Step 2: Normalize
        normalized = self.normalizer.normalize_batch(raw_articles)

        # Step 3: Deduplicate
        unique = self.deduplicator.deduplicate_batch(normalized)
        self.logger.info(f"After dedup: {len(unique)} unique articles")

        # Step 4: Keyword filter
        relevant = self.keyword_filter.filter_batch(unique)
        self.logger.info(f"After keyword filter: {len(relevant)} relevant articles")

        # Step 5: Classify (only if there are relevant articles)
        classifications = []
        if relevant:
            classifications = self.classifier.classify_batch(relevant)
            self.logger.info(f"Classified {len(classifications)} articles")

            # Store classifications in DB
            for cls in classifications:
                self.db.insert_classification(cls)

        # Step 6: Corroborate (group into events)
        events = self.corroborator.process_classifications(classifications)
        alertable_events = [e for e in events if e.alert_status == "pending"]
        self.logger.info(f"Events needing alerts: {len(alertable_events)}")

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
        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
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

        self.logger.info(
            f"=== Cycle complete in {cycle_duration:.1f}s: "
            f"fetched={result.articles_fetched}, "
            f"unique={result.articles_unique}, "
            f"relevant={result.articles_relevant}, "
            f"classified={result.articles_classified}, "
            f"events={result.events_created}, "
            f"alerts={result.alerts_sent} ==="
        )

        return result

    async def _fetch_all(self) -> list[Article]:
        """Fetch from all enabled sources. Errors in one source don't affect others."""
        all_articles = []
        for fetcher in self.fetchers:
            try:
                articles = await fetcher.fetch()
                all_articles.extend(articles)
                self.logger.debug(f"{fetcher.name}: fetched {len(articles)} articles")
            except Exception as e:
                self.logger.error(f"{fetcher.name}: fetch failed: {e}", exc_info=True)
        return all_articles
```

### 6.2 Scheduler Setup

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import random

class SentinelScheduler:
    def __init__(self, pipeline: SentinelPipeline, config: SentinelConfig):
        self.pipeline = pipeline
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.logger = logging.getLogger("sentinel.scheduler")

    def start(self):
        """Start the scheduler."""
        interval = self.config.scheduler.interval_minutes
        jitter = self.config.scheduler.jitter_seconds

        self.scheduler.add_job(
            self._run_with_error_handling,
            trigger=IntervalTrigger(minutes=interval, jitter=jitter),
            id="sentinel_pipeline",
            name="Sentinel Pipeline",
            max_instances=1,  # Never run two cycles concurrently
            coalesce=True,    # If missed, run once (not N times)
        )

        self.scheduler.start()
        self.logger.info(
            f"Scheduler started: interval={interval}min, jitter={jitter}s"
        )

    async def _run_with_error_handling(self):
        """Run the pipeline with top-level error handling."""
        try:
            result = await self.pipeline.run_cycle()
            self._update_health(healthy=True, result=result)
        except Exception as e:
            self.logger.critical(f"Pipeline cycle failed: {e}", exc_info=True)
            self._update_health(healthy=False, error=str(e))
            # Don't re-raise -- let the scheduler continue on next cycle

    def stop(self):
        """Stop the scheduler gracefully."""
        self.scheduler.shutdown(wait=True)
        self.logger.info("Scheduler stopped")
```

#### Jitter
The `jitter` parameter adds a random offset (up to ±30 seconds by default) to each scheduled run. This avoids polling sources exactly on the quarter-hour when many other bots do the same.

#### Coalesce & Max Instances
- `max_instances=1`: If a cycle takes longer than 15 minutes (unlikely), don't start another one concurrently.
- `coalesce=True`: If the system was suspended/sleeping and missed a run, only run once when it wakes up (not multiple make-up runs).

### 6.3 CLI Entry Point (`sentinel.py`)

The full CLI, building on Phase 1's skeleton:

```python
import argparse
import asyncio
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel - Military Alert Monitoring System"
    )
    parser.add_argument("--dry-run", action="store_true",
        help="Run pipeline but don't send Twilio alerts")
    parser.add_argument("--test-headline", type=str, metavar="TEXT",
        help="Classify a single headline and print result")
    parser.add_argument("--test-file", type=str, metavar="FILE",
        help="Classify headlines from a YAML file and print results")
    parser.add_argument("--config", type=str, default="config/config.yaml",
        help="Path to config file")
    parser.add_argument("--once", action="store_true",
        help="Run pipeline once and exit")
    parser.add_argument("--log-level", type=str, choices=["DEBUG","INFO","WARNING","ERROR"],
        help="Override log level")
    parser.add_argument("--health", action="store_true",
        help="Print health status and exit")

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    if args.dry_run:
        config.testing.dry_run = True
    if args.log_level:
        config.logging.level = args.log_level

    # Setup logging
    setup_logging(config)

    # Mode: test single headline
    if args.test_headline:
        asyncio.run(test_single_headline(config, args.test_headline))
        sys.exit(0)

    # Mode: test headline file
    if args.test_file:
        asyncio.run(test_headline_file(config, args.test_file))
        sys.exit(0)

    # Mode: health check
    if args.health:
        print_health(config)
        sys.exit(0)

    # Mode: run once
    pipeline = SentinelPipeline(config)
    if args.once:
        result = asyncio.run(pipeline.run_cycle())
        print_cycle_result(result)
        sys.exit(0)

    # Mode: continuous (default)
    scheduler = SentinelScheduler(pipeline, config)
    print("Sentinel started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        scheduler.stop()
        print("Sentinel stopped.")

if __name__ == "__main__":
    main()
```

### 6.4 Health Monitoring

The system tracks its own health:

```python
@dataclass
class HealthStatus:
    is_healthy: bool
    last_cycle_at: datetime | None
    last_cycle_duration_seconds: float | None
    last_cycle_articles_fetched: int
    last_cycle_alerts_sent: int
    consecutive_failures: int
    last_error: str | None
    uptime_seconds: float
    db_size_bytes: int
    fetcher_status: dict[str, bool]  # per-fetcher health
```

Health status is written to `data/health.json` after each cycle. This allows external monitoring tools to check if Sentinel is running.

#### Self-Healing

If a fetcher fails 5 consecutive times:
- Log a WARNING
- Continue running other fetchers
- After 10 consecutive failures:
  - Log an ERROR
  - Send an SMS to the user: "Sentinel: źródło {source_name} nie odpowiada od {N} cykli. System nadal monitoruje pozostałe źródła."

If the entire pipeline fails 3 consecutive times:
- Send an SMS: "Sentinel: system napotkał krytyczny błąd. Sprawdź logi."
- Continue attempting on next cycle

### 6.5 Telegram Lifecycle Integration

The Telegram fetcher is special -- it needs to be started before the first cycle and stopped on shutdown:

```python
class SentinelPipeline:
    async def startup(self):
        """Initialize components that need async startup."""
        for fetcher in self.fetchers:
            if hasattr(fetcher, 'start'):
                await fetcher.start()

    async def shutdown(self):
        """Clean up components."""
        for fetcher in self.fetchers:
            if hasattr(fetcher, 'stop'):
                await fetcher.stop()
```

### 6.6 Cycle Result Logging

Each cycle logs a structured summary:

```
2025-09-10 14:15:32 [INFO] sentinel.pipeline: === Cycle complete in 8.3s: fetched=347, unique=42, relevant=7, classified=7, events=1, alerts=0 ===
```

Daily summary logged at midnight:
```
2025-09-10 00:00:00 [INFO] sentinel.pipeline: === Daily summary: cycles=96, articles_processed=4032, events_detected=3, alerts_sent=1, api_cost=$0.04 ===
```

## Acceptance Tests

### test_integration.py (End-to-End)
1. `test_full_pipeline_with_fixtures` -- feed fixture articles through the full pipeline, verify correct classification and alert routing
2. `test_full_pipeline_dry_run` -- run full pipeline in dry-run mode, verify no Twilio calls made
3. `test_pipeline_survives_fetcher_failure` -- one fetcher throws exception, pipeline continues with others
4. `test_pipeline_survives_classifier_failure` -- classifier API error, pipeline logs error and continues
5. `test_pipeline_survives_twilio_failure` -- Twilio error, pipeline logs error and continues
6. `test_dedup_across_cycles` -- article seen in cycle 1 is not re-processed in cycle 2
7. `test_corroboration_across_cycles` -- article A in cycle 1, article B (same event) in cycle 2 → corroborated event
8. `test_once_mode` -- `--once` runs pipeline exactly once and exits
9. `test_health_status_updated` -- health.json updated after each cycle

### test_scheduler.py
1. `test_scheduler_fires_at_interval` -- scheduler triggers pipeline at configured interval
2. `test_scheduler_jitter_applied` -- execution time varies within jitter window
3. `test_max_instances_enforced` -- slow cycle doesn't cause concurrent execution
4. `test_scheduler_continues_after_error` -- pipeline error doesn't stop scheduler
5. `test_graceful_shutdown` -- Ctrl+C triggers clean shutdown

## Dependencies Added

```
apscheduler>=3.10
```
