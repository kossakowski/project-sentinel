import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from sentinel.config import SentinelConfig


def setup_logging(config: SentinelConfig) -> None:
    """Configure logging based on config settings.

    Sets up a root 'sentinel' logger with a rotating file handler and a
    stdout stream handler. Idempotent -- calling twice does not add
    duplicate handlers.
    """
    logger = logging.getLogger("sentinel")

    # Idempotency: skip if handlers are already attached
    if logger.handlers:
        return

    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Create parent directories for log file if needed
    log_dir = os.path.dirname(config.logging.file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Rotating file handler
    max_bytes = config.logging.max_size_mb * 1024 * 1024
    file_handler = RotatingFileHandler(
        config.logging.file,
        maxBytes=max_bytes,
        backupCount=config.logging.backup_count,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # Stdout stream handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
