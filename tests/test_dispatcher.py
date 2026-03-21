"""Tests for sentinel.alerts.dispatcher — 4 tests per spec."""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.config import UrgencyLevel
from sentinel.models import Event


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_event(
    urgency_score: int = 10,
    source_count: int = 2,
    event_type: str = "missile_strike",
    summary_pl: str = "Rosja wystrzeliła rakiety.",
) -> Event:
    return Event(
        id=str(uuid4()),
        event_type=event_type,
        urgency_score=urgency_score,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl=summary_pl,
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
        source_count=source_count,
        article_ids=[str(uuid4())],
        alert_status="pending",
    )


@pytest.fixture
def mock_state_machine(config):
    """Create a mock AlertStateMachine."""
    sm = MagicMock(spec=AlertStateMachine)
    sm.config = config
    # _determine_action needs to work for dry run tests
    sm._determine_action.return_value = "phone_call"
    return sm


@pytest.fixture
def dispatcher(mock_state_machine, config):
    """Create an AlertDispatcher with a mocked state machine."""
    return AlertDispatcher(mock_state_machine, config)


@pytest.fixture
def dry_run_config(config):
    """Return a config with dry_run enabled."""
    config.testing.dry_run = True
    return config


@pytest.fixture
def dry_run_dispatcher(mock_state_machine, dry_run_config):
    """Create an AlertDispatcher in dry-run mode."""
    return AlertDispatcher(mock_state_machine, dry_run_config)


# --------------------------------------------------------------------------
# 1. test_dry_run_no_calls
# --------------------------------------------------------------------------
def test_dry_run_no_calls(dry_run_dispatcher, mock_state_machine):
    """Dry run mode logs but doesn't call Twilio."""
    events = [_make_event(urgency_score=10, source_count=2)]

    dry_run_dispatcher.dispatch(events)

    mock_state_machine.process_event.assert_not_called()
    mock_state_machine._determine_action.assert_called_once()


# --------------------------------------------------------------------------
# 2. test_multiple_events_all_processed
# --------------------------------------------------------------------------
def test_multiple_events_all_processed(dispatcher, mock_state_machine):
    """3 events -> all 3 processed."""
    events = [
        _make_event(urgency_score=10),
        _make_event(urgency_score=8),
        _make_event(urgency_score=5),
    ]

    dispatcher.dispatch(events)

    assert mock_state_machine.process_event.call_count == 3


# --------------------------------------------------------------------------
# 3. test_events_sorted_by_urgency
# --------------------------------------------------------------------------
def test_events_sorted_by_urgency(dispatcher, mock_state_machine):
    """Highest urgency processed first."""
    event_low = _make_event(urgency_score=3)
    event_high = _make_event(urgency_score=10)
    event_mid = _make_event(urgency_score=7)

    dispatcher.dispatch([event_low, event_high, event_mid])

    calls = mock_state_machine.process_event.call_args_list
    processed_scores = [call.args[0].urgency_score for call in calls]
    assert processed_scores == [10, 7, 3]


# --------------------------------------------------------------------------
# 4. test_dry_run_log_format
# --------------------------------------------------------------------------
def test_dry_run_log_format(dry_run_dispatcher, mock_state_machine, caplog):
    """Dry run log contains urgency, action, summary."""
    event = _make_event(
        urgency_score=9,
        source_count=2,
        summary_pl="Test summary in Polish",
    )
    mock_state_machine._determine_action.return_value = "phone_call"

    with caplog.at_level(logging.INFO, logger="sentinel.alerts.dispatcher"):
        dry_run_dispatcher.dispatch([event])

    assert len(caplog.records) >= 1
    log_message = caplog.records[0].message
    assert "[DRY RUN]" in log_message
    assert "urgency=9" in log_message
    assert "would_trigger=phone_call" in log_message
    assert "Test summary in Polish" in log_message
