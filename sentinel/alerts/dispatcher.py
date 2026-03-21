import logging

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.config import SentinelConfig
from sentinel.models import Event


class AlertDispatcher:
    """Routes events to the appropriate alert channel based on urgency."""

    def __init__(
        self, state_machine: AlertStateMachine, config: SentinelConfig
    ) -> None:
        self.state_machine = state_machine
        self.config = config
        self.dry_run = config.testing.dry_run
        self.logger = logging.getLogger("sentinel.alerts.dispatcher")

    def dispatch(self, events: list[Event]) -> None:
        """Process all events that need alerting.

        Events are sorted by urgency (highest first) before processing.
        In dry_run mode, logs the intended action without sending anything.
        """
        sorted_events = sorted(
            events, key=lambda e: e.urgency_score, reverse=True
        )

        for event in sorted_events:
            if self.dry_run:
                self._log_dry_run(event)
                continue

            self.state_machine.process_event(event)

    def _log_dry_run(self, event: Event) -> None:
        """Log what would happen without actually sending alerts."""
        action = self.state_machine._determine_action(event)
        self.logger.info(
            "[DRY RUN] Event %s: urgency=%d, sources=%d, "
            "would_trigger=%s, summary=%s",
            event.id,
            event.urgency_score,
            event.source_count,
            action,
            event.summary_pl,
        )
