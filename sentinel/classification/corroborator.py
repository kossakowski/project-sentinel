"""Corroborator -- groups classified articles into events and determines alert levels."""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from rapidfuzz import fuzz

from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Article, ClassificationResult, Event, list_to_json

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

# Minimum urgency to create an event
_MIN_EVENT_URGENCY = 5

# Title similarity threshold for detecting syndicated content (same underlying source)
_SYNDICATION_SIMILARITY_THRESHOLD = 90

# Minimum summary_pl similarity (fuzzy) to consider two classifications as the same event
_SUMMARY_SIMILARITY_THRESHOLD = 55


class Corroborator:
    """Groups classifications into events and determines alert levels."""

    def __init__(self, db: Database, config: SentinelConfig, *, dry_run: bool = False) -> None:
        self.db = db
        self.config = config
        self.dry_run = dry_run or config.testing.dry_run
        self.logger = logging.getLogger("sentinel.corroborator")

    def process_classifications(
        self, results: list[ClassificationResult]
    ) -> list[Event]:
        """Group classifications into events.

        Returns list of events that need alerting (new or updated).
        Only events with urgency >= 5 are created.
        """
        alertable_events: list[Event] = []

        for result in results:
            # Store every classification for auditing/cost tracking
            self.db.insert_classification(result)

            # Only create events for military classifications with urgency >= 5
            if not result.is_military_event or result.urgency_score < _MIN_EVENT_URGENCY:
                self.logger.debug(
                    "Skipping low-urgency/non-military classification: article=%s urgency=%d",
                    result.article_id,
                    result.urgency_score,
                )
                continue

            # Try to match to an existing event
            matching_event = self._find_matching_event(result)

            if matching_event is not None:
                # Check source independence before incrementing source_count
                is_independent = self._is_independent_source(
                    result, matching_event
                )
                updated_event = self._update_event(
                    matching_event, result, is_independent
                )
                alertable_events.append(updated_event)
            else:
                new_event = self._create_event(result)
                alertable_events.append(new_event)

        return alertable_events

    def _find_matching_event(
        self, result: ClassificationResult
    ) -> Event | None:
        """Find an existing active event that matches this classification."""
        window_minutes = self.config.classification.corroboration_window_minutes
        # Convert window to hours (round up) for the DB query
        window_hours = max(1, (window_minutes + 59) // 60)
        active_events = self.db.get_active_events(within_hours=window_hours)

        for event in active_events:
            # Check event type compatibility
            if not self._are_compatible_types(result.event_type, event.event_type):
                continue

            # Check shared affected country
            if not set(result.affected_countries) & set(event.affected_countries):
                continue

            # Check time window
            time_diff = abs(
                (result.classified_at - event.first_seen_at).total_seconds()
            )
            if time_diff > window_minutes * 60:
                continue

            # Check summary_pl semantic similarity (fuzzy match)
            summary_similarity = fuzz.token_sort_ratio(
                result.summary_pl, event.summary_pl
            )
            if summary_similarity < _SUMMARY_SIMILARITY_THRESHOLD:
                self.logger.debug(
                    "Summary mismatch (%.0f%% < %d%%): '%s' vs '%s'",
                    summary_similarity,
                    _SUMMARY_SIMILARITY_THRESHOLD,
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
        if compatible_set is not None and type1 in compatible_set:
            return True

        return False

    def _is_independent_source(
        self, result: ClassificationResult, event: Event
    ) -> bool:
        """Determine if the new classification comes from an independent source.

        Two articles from the same underlying source don't count as independent:
        - Different source_type (rss vs gdelt vs telegram) -> likely independent
        - Different media organizations (different domains) -> independent
        - Same story syndicated (title similarity > 90%) -> count as 1 source
        """
        # Retrieve the article for this classification
        article_row = self.db.conn.execute(
            "SELECT * FROM articles WHERE id = ?", (result.article_id,)
        ).fetchone()
        if article_row is None:
            return True

        new_article = Article.from_row(article_row)

        # Check against all existing articles in the event
        for existing_article_id in event.article_ids:
            existing_row = self.db.conn.execute(
                "SELECT * FROM articles WHERE id = ?", (existing_article_id,)
            ).fetchone()
            if existing_row is None:
                continue

            existing_article = Article.from_row(existing_row)

            # Different source_type -> likely independent
            if new_article.source_type != existing_article.source_type:
                continue

            # Same source_type -- check domain
            new_domain = self._extract_domain(new_article.source_url)
            existing_domain = self._extract_domain(existing_article.source_url)

            if new_domain == existing_domain:
                # Same domain -> not independent
                return False

            # Different domain but check for syndication (high title similarity)
            title_similarity = fuzz.ratio(
                new_article.title_normalized, existing_article.title_normalized
            )
            if title_similarity >= _SYNDICATION_SIMILARITY_THRESHOLD:
                self.logger.debug(
                    "Syndicated content detected (%.0f%% title similarity): '%s' vs '%s'",
                    title_similarity,
                    new_article.title[:60],
                    existing_article.title[:60],
                )
                return False

        return True

    def _create_event(self, result: ClassificationResult) -> Event:
        """Create a new event from a classification."""
        now = datetime.now(timezone.utc)
        alert_status = self._determine_alert_status(
            urgency=result.urgency_score, source_count=1
        )

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
        is_independent: bool,
    ) -> Event:
        """Add a new source to an existing event."""
        # Update in-memory event
        event.article_ids.append(result.article_id)
        event.urgency_score = max(event.urgency_score, result.urgency_score)
        event.last_updated_at = datetime.now(timezone.utc)

        if is_independent:
            event.source_count += 1

        # Merge affected countries
        merged_countries = list(
            set(event.affected_countries) | set(result.affected_countries)
        )
        event.affected_countries = merged_countries

        # Re-evaluate alert status
        event.alert_status = self._determine_alert_status(
            urgency=event.urgency_score, source_count=event.source_count
        )

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
            "Event updated: id=%s, sources=%d (independent=%s), urgency=%d, alert=%s",
            event.id[:8],
            event.source_count,
            is_independent,
            event.urgency_score,
            event.alert_status,
        )
        return event

    def _determine_alert_status(self, urgency: int, source_count: int) -> str:
        """Determine the alert level for an event.

        When dry_run is active, always returns "dry_run" instead of a real status.

        - phone_call: urgency >= 9 AND source_count >= corroboration_required
        - sms: urgency >= 7
        - whatsapp: urgency >= 5
        """
        if self.dry_run:
            return "dry_run"

        corroboration_required = self.config.classification.corroboration_required

        if urgency >= 9 and source_count >= corroboration_required:
            return "phone_call"
        if urgency >= 7:
            return "sms"
        if urgency >= 5:
            return "whatsapp"
        return "pending"

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # Strip www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain.lower()
        except Exception:
            return url.lower()
