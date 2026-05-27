"""Tests for sentinel.alerts.dispatcher.

The dispatch path is async (SPEC_ASYNC_REFACTOR.md Phase 3): ``dispatch`` is a
coroutine that awaits ``state_machine.process_event`` for each non-dry-run event
SEQUENTIALLY (no gather/TaskGroup), preserving urgency-descending order. The
dry-run path stays synchronous (it only calls the sync ``_determine_action``).
"""

import asyncio
import inspect
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from sentinel.alerts.dispatcher import AlertDispatcher
from sentinel.alerts.state_machine import AlertStateMachine
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
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=source_count,
        article_ids=[str(uuid4())],
        alert_status="pending",
    )


@pytest.fixture
def mock_state_machine(config):
    """Create a mock AlertStateMachine.

    ``process_event`` is now a coroutine, so it must be awaitable; ``spec``
    autospecs it as an AsyncMock, but we set it explicitly for clarity.
    ``_determine_action`` stays a plain (sync) MagicMock for the dry-run path.
    """
    sm = MagicMock(spec=AlertStateMachine)
    sm.config = config
    sm.process_event = AsyncMock()
    # _determine_action needs to work for dry run tests
    sm._determine_action = MagicMock(return_value="phone_call")
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
# 1. test_dispatch_dry_run_logs_without_alerting  [3.3b]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_dry_run_logs_without_alerting(dry_run_dispatcher, mock_state_machine):
    """Dry run mode logs but doesn't call process_event (no Twilio)."""
    events = [_make_event(urgency_score=10, source_count=2)]

    await dry_run_dispatcher.dispatch(events)

    mock_state_machine.process_event.assert_not_called()
    mock_state_machine._determine_action.assert_called_once()


# --------------------------------------------------------------------------
# 2. test_multiple_events_all_processed
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_events_all_processed(dispatcher, mock_state_machine):
    """3 events -> all 3 processed."""
    events = [
        _make_event(urgency_score=10),
        _make_event(urgency_score=8),
        _make_event(urgency_score=5),
    ]

    await dispatcher.dispatch(events)

    assert mock_state_machine.process_event.await_count == 3


# --------------------------------------------------------------------------
# 3. test_events_sorted_by_urgency
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_events_sorted_by_urgency(dispatcher, mock_state_machine):
    """Highest urgency processed first."""
    event_low = _make_event(urgency_score=3)
    event_high = _make_event(urgency_score=10)
    event_mid = _make_event(urgency_score=7)

    await dispatcher.dispatch([event_low, event_high, event_mid])

    calls = mock_state_machine.process_event.await_args_list
    processed_scores = [call.args[0].urgency_score for call in calls]
    assert processed_scores == [10, 7, 3]


# --------------------------------------------------------------------------
# 4. test_dry_run_log_format
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dry_run_log_format(dry_run_dispatcher, mock_state_machine, caplog):
    """Dry run log contains urgency, action, summary."""
    event = _make_event(
        urgency_score=9,
        source_count=2,
        summary_pl="Test summary in Polish",
    )
    mock_state_machine._determine_action.return_value = "phone_call"

    with caplog.at_level(logging.INFO, logger="sentinel.alerts.dispatcher"):
        await dry_run_dispatcher.dispatch([event])

    assert len(caplog.records) >= 1
    log_message = caplog.records[0].message
    assert "[DRY RUN]" in log_message
    assert "urgency=9" in log_message
    assert "would_trigger=phone_call" in log_message
    assert "Test summary in Polish" in log_message


# --------------------------------------------------------------------------
# 5. test_dispatch_is_async_and_sequential  [3.3a, 3.3c]
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_is_async_and_sequential(dispatcher, mock_state_machine):
    """dispatch is a coroutine; events are processed one-at-a-time in urgency-desc order."""
    assert inspect.iscoroutinefunction(AlertDispatcher.dispatch)

    state = {"current": 0, "max": 0}
    order = []

    async def tracking_process_event(event):
        order.append(event.urgency_score)
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        # Yield control so a concurrent invocation could interleave if dispatch
        # used gather/TaskGroup instead of sequential awaits.
        await asyncio.sleep(0)
        state["current"] -= 1

    mock_state_machine.process_event = AsyncMock(side_effect=tracking_process_event)

    events = [
        _make_event(urgency_score=5),
        _make_event(urgency_score=10),
        _make_event(urgency_score=7),
    ]

    await dispatcher.dispatch(events)

    # Sequential dispatch -> never more than one process_event in flight.
    assert state["max"] == 1
    # Urgency-descending order preserved.
    assert order == [10, 7, 5]
    assert mock_state_machine.process_event.await_count == 3
