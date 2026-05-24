from datetime import UTC, datetime
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")


def to_warsaw(dt: datetime) -> datetime:
    """Convert a datetime to Europe/Warsaw. Naive inputs are assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(WARSAW)


def format_warsaw(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a datetime in Europe/Warsaw using strftime ``fmt``."""
    return to_warsaw(dt).strftime(fmt)
