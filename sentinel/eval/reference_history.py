"""Identical prior-source context for controlled model-understanding tests."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5


class ReferenceHistory:
    """Use prior annotations for grouping, never current/future answers in input.

    History contains only raw prior source text and timing. Prior expected scores,
    countries, rationale and evaluator provenance are deliberately not exposed.
    Disputed rows are not seeded into the reference history.
    """

    def __init__(self, max_candidates: int = 5, evidence_per_event: int = 2) -> None:
        self.max_candidates = max_candidates
        self.evidence_per_event = evidence_per_event
        self.case_events: dict[str, str | None] = {}
        self._episodes: dict[str, dict] = {}

    def candidates(self) -> list[dict]:
        episodes = sorted(self._episodes.values(), key=lambda item: item["last_updated_at"], reverse=True)
        return deepcopy(episodes[: self.max_candidates])

    def add(self, case: dict) -> None:
        if case["label_status"] == "disputed":
            self.case_events[case["id"]] = None
            return
        expected = case["expected"]
        event_id = self.case_events.get(expected.get("same_as")) if expected["relation"] == "same" else None
        if event_id is None:
            event_id = str(uuid5(NAMESPACE_URL, "sentinel-reference:" + case["sequence_id"] + ":" + case["id"]))
        article = case["article"]
        arrival = datetime.fromisoformat(str(article["fetched_at"])).astimezone(UTC).isoformat()
        episode = self._episodes.setdefault(
            event_id,
            {
                "id": event_id,
                "first_seen_at": arrival,
                "last_updated_at": arrival,
                "evidence": [],
            },
        )
        episode["last_updated_at"] = arrival
        episode["evidence"].append({key: str(article[key]) for key in ("title", "summary", "published_at", "language")})
        episode["evidence"] = episode["evidence"][-self.evidence_per_event :]
        self.case_events[case["id"]] = event_id
