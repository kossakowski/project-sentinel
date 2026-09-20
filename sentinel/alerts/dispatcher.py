import logging

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.config import SentinelConfig
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
            if db is not None:
                current_events.append(db.get_event_by_id(event.id) or event)
            else:
                current_events.append(event)

        sorted_events = sorted(current_events, key=lambda e: e.urgency_score, reverse=True)

        for event in sorted_events:
            if self.dry_run:
                self._log_dry_run(event)
                continue

            await self.state_machine.process_event(event)

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
