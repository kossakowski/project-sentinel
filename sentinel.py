#!/usr/bin/env python3
"""Project Sentinel - Military Alert Monitoring System"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import yaml

from sentinel import __version__
from sentinel.config import ConfigError, load_config
from sentinel.logging_setup import setup_logging
from sentinel.models import Article


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project Sentinel - Military Alert Monitoring System",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but don't send any Twilio alerts (log only)",
    )
    parser.add_argument(
        "--test-headline",
        metavar="TEXT",
        help="Feed a single headline through the classifier and print result",
    )
    parser.add_argument(
        "--test-file",
        metavar="FILE",
        help="Feed all headlines from a YAML file through the classifier",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        metavar="PATH",
        help="Path to config file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once and exit (don't schedule)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        metavar="LEVEL",
        help="Override config log level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print health status and exit",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Run one cycle and generate an HTML diagnostic report (data/diagnostic.html)",
    )
    parser.add_argument(
        "--test-alert",
        nargs="?",
        const="phone_call",
        choices=["phone_call", "sms", "whatsapp"],
        metavar="TYPE",
        help="Fire a real test alert through Twilio (default: phone_call). "
        "Choices: phone_call, sms, whatsapp. Bypasses fetching, classification, "
        "and corroboration — injects a synthetic event directly into the alert system.",
    )
    return parser


def print_health(config) -> None:
    """Read and print health.json."""
    health_path = os.path.join("data", "health.json")
    if not os.path.exists(health_path):
        print("No health data found. Has the pipeline run yet?")
        return

    with open(health_path, "r", encoding="utf-8") as f:
        health = json.load(f)

    print(json.dumps(health, indent=2))


def print_cycle_result(result) -> None:
    """Print a CycleResult summary to stdout."""
    print(f"\nPipeline cycle completed in {result.duration_seconds:.1f}s:")
    print(f"  Articles fetched:    {result.articles_fetched}")
    print(f"  Articles unique:     {result.articles_unique}")
    print(f"  Articles relevant:   {result.articles_relevant}")
    print(f"  Articles classified: {result.articles_classified}")
    print(f"  Events created:      {result.events_created}")
    print(f"  Alerts sent:         {result.alerts_sent}")
    print()


async def run_once(config) -> None:
    """Run the pipeline once and exit."""
    from sentinel.scheduler import SentinelPipeline

    pipeline = SentinelPipeline(config)
    try:
        await pipeline.startup()
        result = await pipeline.run_cycle()
        print_cycle_result(result)
    finally:
        await pipeline.shutdown()


async def run_diagnostic(config) -> None:
    """Run one pipeline cycle in diagnostic mode and generate HTML report."""
    from sentinel.diagnostic import generate_html
    from sentinel.scheduler import SentinelPipeline

    pipeline = SentinelPipeline(config)
    try:
        await pipeline.startup()
        result = await pipeline.run_cycle(diagnostic=True)
        print_cycle_result(result)

        if pipeline.diagnostic_data is not None:
            output_path = os.path.join("data", "diagnostic.html")
            abs_path = generate_html(pipeline.diagnostic_data, output_path)
            print(f"Diagnostic report: {abs_path}")
        else:
            print("Warning: no diagnostic data collected.", file=sys.stderr)
    finally:
        await pipeline.shutdown()


async def run_continuous(config) -> None:
    """Run the scheduler in continuous mode."""
    from sentinel.scheduler import SentinelPipeline, SentinelScheduler

    pipeline = SentinelPipeline(config)
    try:
        await pipeline.startup()
    except Exception as e:
        logging.getLogger("sentinel").error(
            "Pipeline startup failed: %s", e, exc_info=True
        )
        await pipeline.shutdown()
        raise

    scheduler = SentinelScheduler(pipeline, config)
    scheduler.start()

    # Run the first cycle immediately
    try:
        await pipeline.run_cycle()
    except Exception as e:
        logging.getLogger("sentinel").error(
            "Initial cycle failed: %s", e, exc_info=True
        )

    print("Project Sentinel started. Press Ctrl+C to stop.")

    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        scheduler.stop()
        await pipeline.shutdown()
        print("\nProject Sentinel stopped.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Load and validate config
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Apply CLI overrides
    if args.log_level:
        config.logging.level = args.log_level
    if args.dry_run:
        config.testing.dry_run = True

    # Set up logging
    setup_logging(config)

    logger = logging.getLogger("sentinel")

    # Count sources for log message
    rss_count = len([s for s in config.sources.rss if s.enabled])
    gn_count = len(config.sources.google_news.queries) if config.sources.google_news.enabled else 0
    gdelt_status = "enabled" if config.sources.gdelt.enabled else "disabled"
    telegram_status = "enabled" if config.sources.telegram.enabled else "disabled"

    logger.info("Project Sentinel v%s initialized successfully", __version__)
    logger.info(
        "Config loaded: %d RSS sources, %d Google News queries, GDELT %s, Telegram %s",
        rss_count,
        gn_count,
        gdelt_status,
        telegram_status,
    )
    logger.info("Database: %s", config.database.url)
    logger.info("Dry run: %s", config.testing.dry_run)

    # Test alert mode — fires a real Twilio alert
    if args.test_alert:
        _run_test_alert(args.test_alert, config, logger)
        sys.exit(0)

    # Classification dry-run modes
    if args.test_headline:
        _run_test_headline(args.test_headline, config, logger)
        sys.exit(0)

    if args.test_file:
        _run_test_file(args.test_file, config, logger)
        sys.exit(0)

    # Mode: health check
    if args.health:
        print_health(config)
        sys.exit(0)

    # Mode: diagnostic
    if args.diagnostic:
        config.testing.dry_run = True  # suppress all alerts
        asyncio.run(run_diagnostic(config))
        sys.exit(0)

    # Mode: run once
    if args.once:
        asyncio.run(run_once(config))
        sys.exit(0)

    # Mode: continuous (default)
    try:
        asyncio.run(run_continuous(config))
    except KeyboardInterrupt:
        print("\nProject Sentinel stopped.")


def _make_synthetic_article(headline: str, source_name: str = "test-headline") -> Article:
    """Create a synthetic Article from a headline for testing."""
    now = datetime.now(timezone.utc)
    return Article(
        source_name=source_name,
        source_url=f"https://test.sentinel/{uuid4().hex[:8]}",
        source_type="test",
        title=headline,
        summary=headline,
        language="en",
        published_at=now,
        fetched_at=now,
    )


def _print_classification_result(result, headline: str = "") -> None:
    """Print a ClassificationResult in a readable format."""
    if headline:
        print(f"\nHeadline: {headline}")
    print(f"  Military event:     {result.is_military_event}")
    print(f"  Event type:         {result.event_type}")
    print(f"  Urgency score:      {result.urgency_score}")
    print(f"  Affected countries: {result.affected_countries}")
    print(f"  Aggressor:          {result.aggressor}")
    print(f"  Confidence:         {result.confidence:.2f}")
    print(f"  Summary (PL):       {result.summary_pl}")
    print(f"  Tokens:             {result.input_tokens} in / {result.output_tokens} out")
    print()


def _run_test_headline(headline: str, config, logger) -> None:
    """Classify a single headline and print the result."""
    from sentinel.classification.classifier import Classifier

    logger.info("Test headline mode: '%s'", headline)
    classifier = Classifier(config)
    article = _make_synthetic_article(headline)

    try:
        result = classifier.classify(article)
        _print_classification_result(result, headline)
    except Exception as e:
        print(f"Classification failed: {e}", file=sys.stderr)
        sys.exit(1)


def _run_test_file(filepath: str, config, logger) -> None:
    """Load headlines from a YAML file, classify each, and print results."""
    from sentinel.classification.classifier import Classifier

    logger.info("Test file mode: %s", filepath)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML in {filepath}: {e}", file=sys.stderr)
        sys.exit(1)

    headlines = data.get("headlines", [])
    if not headlines:
        print("No headlines found in file.", file=sys.stderr)
        sys.exit(1)

    classifier = Classifier(config)

    print(f"\nClassifying {len(headlines)} headlines from {filepath}\n")
    print("-" * 80)

    for entry in headlines:
        if isinstance(entry, str):
            headline_text = entry
            expected = None
        elif isinstance(entry, dict):
            headline_text = entry.get("text", entry.get("headline", ""))
            expected = entry.get("expected", None)
        else:
            continue

        article = _make_synthetic_article(headline_text)
        try:
            result = classifier.classify(article)
            _print_classification_result(result, headline_text)

            # Compare against expected values if provided
            if expected:
                mismatches = []
                for key, exp_val in expected.items():
                    actual_val = getattr(result, key, None)
                    if actual_val != exp_val:
                        mismatches.append(f"  {key}: expected={exp_val}, got={actual_val}")
                if mismatches:
                    print("  MISMATCHES:")
                    for m in mismatches:
                        print(m)
                    print()
        except Exception as e:
            print(f"  FAILED: {e}\n")

    print("-" * 80)


def _run_test_alert(alert_type: str, config, logger) -> None:
    """Fire a real test alert through Twilio without fetching or classification.

    Creates a synthetic article + event with urgency=10 and source_count=2
    (bypassing corroboration), then dispatches through the real alert system.
    """
    from sentinel.alerts.state_machine import AlertStateMachine
    from sentinel.alerts.twilio_client import TwilioClient
    from sentinel.database import Database
    from sentinel.models import Event, User

    logger.info("Test alert mode: firing real %s alert", alert_type)

    # Force dry_run OFF — the whole point is to fire a real alert
    config.testing.dry_run = False

    db = Database(config.database.url)
    twilio_client = TwilioClient(config)
    state_machine = AlertStateMachine(db, twilio_client, config)

    now = datetime.now(timezone.utc)

    # Find the first active user to use for test alerts
    active_users = db.get_active_users()
    if not active_users:
        print("ERROR: No active users in the database. Create a user first.")
        print("  Use: python scripts/create_initial_user.py --help")
        return

    test_user = active_users[0]
    phone_number = test_user.phone_number

    # Create and persist a synthetic article so DB lookups in the alert
    # formatter don't fail
    article = _make_synthetic_article(
        headline="[TEST] Próba alertu systemu Project Sentinel",
        source_name="test-alert",
    )
    db.insert_article(article)

    # Build a synthetic event that satisfies all alert thresholds
    # urgency=10 + source_count=2 → phone_call eligible
    # We override alert_status to match the requested alert type
    alert_status_map = {
        "phone_call": "phone_call",
        "sms": "sms",
        "whatsapp": "whatsapp",
    }

    event = Event(
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="TEST",
        summary_pl="[TEST] To jest próba alertu systemu Project Sentinel. Nie ma zagrożenia.",
        first_seen_at=now,
        last_updated_at=now,
        source_count=2,
        article_ids=[article.id],
        alert_status=alert_status_map[alert_type],
    )
    db.insert_event(event)

    print(f"\nTest alert: {alert_type}")
    print(f"  Event ID:  {event.id}")
    print(f"  User:      {test_user.name} ({phone_number})")
    print(f"  Message:   {event.summary_pl}")
    print()

    # Bypass state machine routing — call the requested method directly
    # (process_event would iterate over users based on country matching)
    if alert_type == "phone_call":
        state_machine._execute_phone_call(event, test_user)
    elif alert_type == "sms":
        state_machine._execute_sms(event, test_user)
    elif alert_type == "whatsapp":
        state_machine._execute_whatsapp(event, test_user)

    print(f"Test alert dispatched. Check your phone ({phone_number}).")


if __name__ == "__main__":
    main()
