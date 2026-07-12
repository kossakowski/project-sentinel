"""Corroborator -- groups classified articles into events and determines alert levels."""

import logging
from datetime import UTC, datetime

from rapidfuzz import fuzz

from sentinel.alerts.policy import AlertPolicy, ChannelClass, EventDecision, Relation
from sentinel.classification.geo_weighter import GeoWeighter
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import ClassificationResult, Event, list_to_json

# Compatible event types -- if two event types are in each other's sets, they
# can be grouped into the same real-world event.
EVENT_COMPATIBILITY: dict[str, set[str]] = {
    "invasion": {"invasion", "troop_movement", "border_crossing", "ground_assault"},
    "airstrike": {"airstrike", "missile_strike", "aerial_bombardment", "drone_attack"},
    "missile_strike": {"missile_strike", "airstrike", "artillery_shelling"},
    "border_crossing": {"border_crossing", "invasion", "troop_movement"},
    "airspace_violation": {"airspace_violation", "drone_attack"},
    "drone_attack": {"drone_attack", "airspace_violation", "airstrike"},
    "artillery_shelling": {"artillery_shelling", "missile_strike"},
    "naval_blockade": {"naval_blockade"},
    "cyber_attack": {"cyber_attack"},
}

# event_type values whose event survives the pre-dedup gate even when the
# classifier marks is_military_event=false. These meta-event types (inert-debris
# recovery, official statements/reactions) are alert-relevant at their band; the
# military-flag drop must not silently kill an sms-tier meta-event (2.13). The
# exemption is deterministic here in code -- the classifier prompt rule (0.15)
# alone is not a gate.
_EVENT_GATE_EXEMPT_TYPES: frozenset[str] = frozenset({"debris_found", "official_statement"})

# Alert-lifecycle statuses owned by the alert state machine's bounded phone-retry
# loop. A merge must NOT re-derive an event's alert_status while it sits in one of
# these: ``retry_pending`` is the sole signal the cycle-driven retry sweep
# (AlertStateMachine.retry_pending_calls, via get_events_by_alert_status) uses to
# keep driving a failed call up to alerts.retry.max_rounds; ``failed_terminal`` is
# the terminal marker that routes genuinely new content to the post-cap SMS+push
# fallback; and ``acknowledged`` marks an event the operator already confirmed.
# Overwriting any of these during a merge would either silently strand a failed
# urgency-9/10 call (prime-directive miss) or knock an acknowledged event back to
# ``phone_call`` — where the sweep would re-call an already-confirmed event
# (one-call-per-event violation) — so these statuses are preserved.
_RETRY_LIFECYCLE_STATUSES: frozenset[str] = frozenset({"retry_pending", "failed_terminal", "acknowledged"})


class Corroborator:
    """Groups classifications into events and determines alert levels."""

    def __init__(self, db: Database, config: SentinelConfig, *, dry_run: bool = False) -> None:
        self.db = db
        self.config = config
        self.dry_run = dry_run or config.testing.dry_run
        self.logger = logging.getLogger("sentinel.corroborator")
        # The Corroborator no longer makes alert decisions: it delegates the
        # initial alert_status band to the single AlertPolicy authority. GeoWeighter
        # supplies the event-level geo tier the policy's call gate needs.
        self.policy = AlertPolicy(config)
        self.geo_weighter = GeoWeighter(config)

    def _passes_event_gate(self, result: ClassificationResult) -> bool:
        """Config-driven pre-dedup event-creation gate (2.13).

        A classification below ``dedup.min_event_urgency`` creates no event row
        (its classification is still persisted). The ``is_military_event`` drop is
        exempted for the 0.15 meta-event types so an sms-tier debris/statement
        story is not silently dropped before the deduplicator.
        """
        if result.urgency_score < self.config.dedup.min_event_urgency:
            return False
        # is_military_event drop, exempted for the 0.15 meta-event types.
        return result.event_type in _EVENT_GATE_EXEMPT_TYPES or result.is_military_event

    def process_classifications(self, results: list[ClassificationResult]) -> list[Event]:
        """Group classifications into events.

        Returns list of events that need alerting (new or updated). Events are
        created only for classifications that pass the config-driven pre-dedup
        gate (``dedup.min_event_urgency`` + the military-flag exemption, 2.13).
        """
        alertable_events: list[Event] = []

        for result in results:
            # Store every classification for auditing/cost tracking
            self.db.insert_classification(result)

            if not self._passes_event_gate(result):
                self.logger.debug(
                    "Skipping sub-threshold classification: article=%s urgency=%d type=%s military=%s",
                    result.article_id,
                    result.urgency_score,
                    result.event_type,
                    result.is_military_event,
                )
                continue

            # Try to match to an existing event
            matching_event = self._find_matching_event(result)

            if matching_event is not None:
                updated_event = self._update_event(matching_event, result)
                alertable_events.append(updated_event)
            else:
                new_event = self._create_event(result)
                alertable_events.append(new_event)

        return alertable_events

    def _find_matching_event(self, result: ClassificationResult) -> Event | None:
        """Find an existing active event that matches this classification."""
        window_minutes = self.config.classification.corroboration_window_minutes
        max_age_minutes = self.config.classification.corroboration_max_age_minutes
        summary_threshold = self.config.classification.summary_similarity_threshold
        metric_fn = getattr(fuzz, self.config.classification.summary_similarity_metric)
        phone_threshold = self._phone_call_threshold()
        # Convert window to hours (round up) for the DB candidate query
        window_hours = max(1, (window_minutes + 59) // 60)
        active_events = self.db.get_active_events(within_hours=window_hours)

        classified_at = self._as_utc(result.classified_at)

        for event in active_events:
            # Check event type compatibility
            if not self._are_compatible_types(result.event_type, event.event_type):
                continue

            # Check affected-country compatibility. Empty / "unknown" labels carry
            # no location signal and must NOT block a merge -- this is what shattered
            # a single real incident into dozens of events when the classifier
            # emitted ["RO"], [], and ["unknown"] for the same story. Two
            # concrete-but-different countries (e.g. PL vs RO) still stay separate,
            # and critical (phone-call-eligible) articles must match a concrete
            # country so a Poland alert can never be absorbed into another event.
            if not self._countries_compatible(
                result.affected_countries, event.affected_countries, urgency=result.urgency_score
            ):
                continue

            # SAFETY: a critical (phone-call-eligible) article must never be absorbed
            # into an event whose call channel is already spent -- one that has been
            # acknowledged (in/past its post-alert cooldown) OR that exhausted its
            # phone-retry cap (``failed_terminal``, call transport dead, new content
            # routed only to the SMS+push fallback). Either way the event would
            # silently swallow the new article and a genuinely new critical
            # escalation (e.g. a second missile wave) would never get its own phone
            # call. Force it to spawn its own event -- and its own call. This mirrors
            # the no-concrete-country critical guard in _countries_compatible.
            if result.urgency_score >= phone_threshold and (
                event.acknowledged_at is not None or event.alert_status == "failed_terminal"
            ):
                continue

            # Sliding time window: measure recency from the event's LAST activity
            # (last_updated_at), not its birth, so a continuously-updated incident
            # stays one event instead of re-fragmenting every window_minutes.
            recency = abs((classified_at - self._as_utc(event.last_updated_at)).total_seconds())
            if recency > window_minutes * 60:
                continue

            # Absolute age cap (from first_seen_at): retire a perpetually-touched
            # event so it can't chain-merge genuinely separate incidents. 0 disables.
            if (
                max_age_minutes
                and abs((classified_at - self._as_utc(event.first_seen_at)).total_seconds()) > max_age_minutes * 60
            ):
                continue

            # Check summary_pl semantic similarity (fuzzy match)
            summary_similarity = metric_fn(result.summary_pl, event.summary_pl)
            if summary_similarity < summary_threshold:
                self.logger.debug(
                    "Summary mismatch (%.0f%% < %d%%): '%s' vs '%s'",
                    summary_similarity,
                    summary_threshold,
                    result.summary_pl[:60],
                    event.summary_pl[:60],
                )
                continue

            return event

        return None

    def _are_compatible_types(self, type1: str, type2: str) -> bool:
        """Check if two event types are compatible."""
        if type1 == type2:
            return True

        compatible_set = EVENT_COMPATIBILITY.get(type1)
        if compatible_set is not None and type2 in compatible_set:
            return True

        compatible_set = EVENT_COMPATIBILITY.get(type2)
        return compatible_set is not None and type1 in compatible_set

    @staticmethod
    def _concrete_countries(countries: list[str]) -> set[str]:
        """Country codes carrying a real location signal.

        Drops empty/whitespace-only entries and the "unknown" placeholder the
        classifier emits when it cannot determine the target country, so they
        don't act as a (non-)match key during grouping. Normalizes to uppercase.
        """
        return {code for c in countries if c and (code := c.strip().upper()) and code != "UNKNOWN"}

    @staticmethod
    def _as_utc(dt: datetime) -> datetime:
        """Coerce a datetime to tz-aware UTC (assume UTC if naive).

        Timestamps are stored as UTC ISO strings; a naive value sneaking in would
        otherwise raise TypeError when subtracted from an aware value and crash the
        whole grouping loop.
        """
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    def _phone_call_threshold(self) -> int:
        """Lowest urgency whose configured action is a phone call.

        Read from config (alerts.urgency_levels) rather than hardcoded; falls
        back to 9 if no phone-call level is configured.
        """
        thresholds = [
            level.min_score for level in self.config.alerts.urgency_levels.values() if level.action == "phone_call"
        ]
        return min(thresholds) if thresholds else 9

    def _countries_compatible(self, result_countries: list[str], event_countries: list[str], urgency: int = 0) -> bool:
        """Decide whether affected-country labels permit grouping.

        - A critical (phone-call-eligible) article must share a CONCRETE country
          with the event; the empty/"unknown" no-signal relaxation is NOT applied
          to it. Otherwise an urgency-9/10 Poland article whose country the
          classifier failed to extract could be absorbed into another country's
          already-alerted event and silenced by its post-acknowledgment cooldown.
          Without a concrete match it spawns its own event -- and its own call.
        - Below the phone-call threshold, events are SMS-only and can never enter
          cooldown, so empty/"unknown" labels (no location signal) don't block a
          merge -- they fall back to event-type + summary matching. This is what
          stops one incident from shattering into many SMS-spamming events.
        - When both sides name concrete countries, require a non-empty
          intersection so explicitly-different incidents (e.g. PL vs RO) stay
          separate regardless of urgency.
        """
        result_set = self._concrete_countries(result_countries)
        event_set = self._concrete_countries(event_countries)
        if urgency >= self._phone_call_threshold():
            return bool(result_set & event_set)
        if not result_set or not event_set:
            return True
        return bool(result_set & event_set)

    def _create_event(self, result: ClassificationResult) -> Event:
        """Create a new event from a classification."""
        now = datetime.now(UTC)
        alert_status = self._alert_status_for(result.urgency_score, result.affected_countries)

        event = Event(
            event_type=result.event_type,
            urgency_score=result.urgency_score,
            affected_countries=list(result.affected_countries),
            aggressor=result.aggressor,
            summary_pl=result.summary_pl,
            first_seen_at=result.classified_at,
            last_updated_at=now,
            source_count=1,
            article_ids=[result.article_id],
            alert_status=alert_status,
        )

        self.db.insert_event(event)
        self.logger.info(
            "New event created: type=%s, urgency=%d, countries=%s, alert=%s",
            event.event_type,
            event.urgency_score,
            event.affected_countries,
            event.alert_status,
        )
        return event

    def _update_event(
        self,
        event: Event,
        result: ClassificationResult,
    ) -> Event:
        """Add a new article to an existing event.

        ``source_count`` now counts merged articles (corroboration / independent-
        source accounting is deleted -- it no longer gates any alert). Article-level
        URL/title dedup upstream (``processing/deduplicator.py``) already drops exact
        duplicates before classification.
        """
        # Update in-memory event
        event.article_ids.append(result.article_id)
        event.urgency_score = max(event.urgency_score, result.urgency_score)
        event.last_updated_at = datetime.now(UTC)
        event.source_count += 1

        # Merge affected countries through the same normalization the matching
        # gate uses (uppercased, "unknown"/blank dropped) so stored data and
        # alert text stay clean -- e.g. "RO", never "RO, unknown" or mixed case.
        merged = self._concrete_countries(event.affected_countries) | self._concrete_countries(
            result.affected_countries
        )
        event.affected_countries = sorted(merged)

        # Re-evaluate alert status -- but NEVER clobber a status owned by the alert
        # state machine's bounded phone-retry loop. A merge (even a non-independent
        # syndicated copy) runs on EVERY matched article, so re-deriving here would
        # knock a failed call out of ``retry_pending`` (dropping it from the
        # cycle-driven retry sweep) or erase ``failed_terminal`` (which routes
        # post-cap content to the SMS+push fallback). Preserve those; re-derive only
        # when the event is not mid-retry-lifecycle.
        if event.alert_status not in _RETRY_LIFECYCLE_STATUSES:
            event.alert_status = self._alert_status_for(event.urgency_score, event.affected_countries)

        # Persist changes
        self.db.update_event(
            event.id,
            urgency_score=event.urgency_score,
            source_count=event.source_count,
            article_ids=list_to_json(event.article_ids),
            affected_countries=list_to_json(event.affected_countries),
            alert_status=event.alert_status,
        )

        self.logger.info(
            "Event updated: id=%s, sources=%d, urgency=%d, alert=%s",
            event.id[:8],
            event.source_count,
            event.urgency_score,
            event.alert_status,
        )
        return event

    # Map the policy's channel class onto the event.alert_status vocabulary the
    # alert state machine keys off (its retry sweep queries the "phone_call"
    # status; "sms"/"pending" are non-call).
    _CLASS_TO_STATUS = {
        ChannelClass.CALL: "phone_call",
        ChannelClass.NOTIFY: "sms",
        ChannelClass.NONE: "pending",
    }

    def _alert_status_for(self, urgency: int, affected_countries: list[str]) -> str:
        """Initial ``alert_status`` for an event, delegated to the AlertPolicy.

        The Corroborator no longer decides alert levels itself: it asks the single
        AlertPolicy authority for the band (relation NEW; the deduplicator's
        relation logic is applied later at dispatch). ``dry_run`` short-circuits.
        """
        if self.dry_run:
            return "dry_run"

        geo_tier = self.geo_weighter.tier_for_affected(affected_countries)
        intent = self.policy.decide(EventDecision(Relation.NEW), urgency=urgency, geo_tier=geo_tier)
        return self._CLASS_TO_STATUS[intent.channel_class]
