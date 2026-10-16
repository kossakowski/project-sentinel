import logging

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Event


class AlertDispatcher:
    """Routes events to the appropriate alert channel based on urgency."""

    def __init__(self, state_machine: AlertStateMachine, config: SentinelConfig) -> None:
        self.state_machine = state_machine
        self.config = config
        self.dry_run = config.testing.dry_run
        self.logger = logging.getLogger("sentinel.alerts.dispatcher")

    async def dispatch(self, events: list[Event]) -> None:
        """Process all events that need alerting.

        Events are sorted by urgency (highest first) and processed
        sequentially (each ``process_event`` is awaited before the next),
        so per-event confirmation state on the shared state machine is not
        clobbered by concurrent events.
        In dry_run mode, logs the intended action without sending anything.

        Events are isolated from each other: an exception while one event is
        alerted is logged and the remaining events are still processed, so a
        fault in one incident can never cost another incident its call. The
        method itself does not raise, so the caller's pending-call check and
        cleanup still run.
        """
        # Classification can emit the same incident more than once in a batch
        # (for example, after sequential corroboration).  Alerting is an
        # event-level side effect, so process each id once and resolve the
        # persisted row before sorting/dispatching rather than trust a stale
        # in-memory snapshot from earlier in that batch.
        current_events: list[Event] = []
        seen_event_ids: set[str] = set()
        db = None if self.dry_run else getattr(self.state_machine, "db", None)
        for event in events:
            if event.id in seen_event_ids:
                continue
            seen_event_ids.add(event.id)
            current_events.append(self._persisted_or_snapshot(db, event))

        sorted_events = sorted(current_events, key=lambda e: e.urgency_score, reverse=True)

        for event in sorted_events:
            try:
                if self.dry_run:
                    self._log_dry_run(event)
                else:
                    await self.state_machine.process_event(event)
            except Exception:
                self.logger.critical(
                    "Alerting failed for event %s (urgency %s); continuing with the remaining events",
                    event.id,
                    event.urgency_score,
                    exc_info=True,
                )

    def _persisted_or_snapshot(self, db: Database | None, event: Event) -> Event:
        """Return the persisted row of ``event``, or the snapshot when it cannot be read."""
        if db is None:
            return event
        try:
            return db.get_event_by_id(event.id) or event
        except Exception:
            self.logger.error(
                "Could not re-read event %s before alerting; using the in-memory snapshot",
                event.id,
                exc_info=True,
            )
            return event

    def _log_dry_run(self, event: Event) -> None:
        """Log what would happen without actually sending alerts."""
        action = self.state_machine._determine_action(event)
        self.logger.info(
            "[DRY RUN] Event %s: urgency=%d, sources=%d, would_trigger=%s, summary=%s",
            event.id,
            event.urgency_score,
            event.source_count,
            action,
            event.summary_pl,
        )
