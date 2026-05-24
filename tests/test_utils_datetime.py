from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sentinel.utils.datetime import WARSAW, format_warsaw, to_warsaw


def test_to_warsaw_summer_dst():
    # 2026-05-22 10:00 UTC → 12:00 Europe/Warsaw (CEST, UTC+2).
    utc = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    local = to_warsaw(utc)
    assert local.tzinfo == WARSAW
    assert local.hour == 12
    assert local.minute == 0


def test_to_warsaw_winter():
    # 2026-01-15 10:00 UTC → 11:00 Europe/Warsaw (CET, UTC+1).
    utc = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    local = to_warsaw(utc)
    assert local.hour == 11


def test_to_warsaw_naive_assumed_utc():
    # Naive datetimes are treated as UTC.
    naive = datetime(2026, 5, 22, 10, 0)
    local = to_warsaw(naive)
    assert local.hour == 12


def test_format_warsaw_default():
    utc = datetime(2026, 5, 22, 10, 4, tzinfo=UTC)
    assert format_warsaw(utc) == "2026-05-22 12:04"


def test_format_warsaw_custom_fmt():
    utc = datetime(2026, 5, 22, 10, 4, 30, tzinfo=UTC)
    assert format_warsaw(utc, "%Y-%m-%d %H:%M:%S") == "2026-05-22 12:04:30"


def test_to_warsaw_already_aware_non_utc():
    # Non-UTC tz-aware input is converted correctly.
    other = datetime(2026, 5, 22, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    local = to_warsaw(other)
    # NY 14:00 EDT (UTC-4) = 18:00 UTC = 20:00 Warsaw CEST.
    assert local.hour == 20
