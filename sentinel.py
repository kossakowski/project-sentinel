#!/usr/bin/env python3
"""Project Sentinel - Military Alert Monitoring System"""

import argparse
import sys

from sentinel import __version__
from sentinel.config import ConfigError, load_config
from sentinel.database import Database
from sentinel.logging_setup import setup_logging


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
        help="Run a health check and exit",
    )
    return parser


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

    import logging
    logger = logging.getLogger("sentinel")

    # Initialize database
    db = Database(config.database.path)

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
    logger.info("Database: %s", config.database.path)
    logger.info("Dry run: %s", config.testing.dry_run)

    # Phase 1 stubs for not-yet-implemented features
    if args.test_headline:
        print("Test headline mode not yet implemented")
        db.close()
        sys.exit(0)

    if args.test_file:
        print("Test file mode not yet implemented")
        db.close()
        sys.exit(0)

    if args.health:
        print("Health check not yet implemented")
        db.close()
        sys.exit(0)

    print("Project Sentinel initialized successfully. Pipeline execution will be implemented in Phase 6.")
    db.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
