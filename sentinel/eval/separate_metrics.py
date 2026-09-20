"""Independent, denominator-aware metrics for the model-comparison evaluator.

The functions in this module are deliberately pure.  They neither replay cases nor
know about a particular model client.  This keeps classification facts, incident
identity, runtime policy, and infrastructure failures from being collapsed into one
misleading pass/fail value.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

DIMENSION_NAMES = (
    "urgency_exact_range",
    "urgency_action_band",
    "affected_countries",
    "attack_countries",
    "protection",
    "status",
    "attack_countries_evidence",
    "protection_evidence",
    "status_evidence",
    "raw_incident_identity",
    "accepted_incident_identity",
    "persisted_incident_identity",
    "notification",
    "error_free",
)

_MATCH_DECISIONS = {"duplicate", "update", "escalation"}
_NOTIFICATIONS = {"initial", "silent", "update"}
_FLAG_NAMES = (
    "error",
    "retrieval_failure",
    "program_gate_rejection",
    "required_notification_miss",
    "required_critical_notification_miss",
    "critical_score_undercall",
    "duplicate_notification",
    "wrong_merge",
    "raw_wrong_merge",
    "false_alert",
    "transport_error",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_set(value: Any) -> set[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return set(value)


def _set_dimension(actual: Any, expected: Any) -> bool:
    actual_set = _string_set(actual)
    expected_set = _string_set(expected)
    return actual_set is not None and expected_set is not None and actual_set == expected_set


def _action_band(urgency: int) -> str:
    if urgency >= 9:
        return "phone_call"
    if urgency >= 5:
        return "message"
    return "silent"


def _valid_urgency(value: Any) -> int | None:
    if type(value) is int and 1 <= value <= 10:
        return value
    return None


def _identity(memory: Mapping[str, Any], relation: str, anchor_id: str | None) -> bool:
    decision = memory.get("decision")
    matched_id = memory.get("matched_event_id")
    if relation == "same":
        return isinstance(decision, str) and decision in _MATCH_DECISIONS and matched_id == anchor_id
    return decision == "new" and matched_id is None


def _evidence_dimension(actual: Any, expected: Any) -> bool:
    """Compare explicit evidence labels without treating mere presence as truth."""

    if isinstance(expected, bool):
        return bool(isinstance(actual, str) and actual.strip()) is expected
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        return isinstance(actual, str) and actual in expected
    return actual == expected


def _is_transport_error(row: Mapping[str, Any]) -> bool:
    for key in ("error_kind", "error_type", "error_code", "failure_kind"):
        value = row.get(key)
        if isinstance(value, str) and value.casefold() in {"transport", "transport_error", "http_error", "timeout"}:
            return True
    error = row.get("error")
    if not isinstance(error, str):
        return False
    normalized = error.casefold().replace("-", "_").replace(" ", "_")
    return "transport_error" in normalized or normalized.startswith(("timeout", "network_error", "http_error"))


def score_dimensions(case: Mapping[str, Any], row: Mapping[str, Any], prior_events: Mapping[str, str | None]) -> dict:
    """Score one replay result without collapsing independent dimensions.

    ``prior_events`` maps earlier case IDs to the event IDs actually created by
    replay.  Identity dimensions are ``None`` when the expected anchor did not
    exist at runtime or was not included in the candidates shown to the model.
    Such a case contributes to no identity denominator.
    """

    expected = _mapping(case.get("expected"))
    data = _mapping(row.get("data"))
    facts = _mapping(data.get("facts"))
    evidence = _mapping(facts.get("evidence"))
    accepted = _mapping(row.get("accepted_memory"))
    has_error = bool(row.get("error"))
    reference_mode = row.get("context_mode") == "reference"

    dimensions: dict[str, bool | None] = {name: None for name in DIMENSION_NAMES}
    dimensions["error_free"] = not has_error

    urgency = _valid_urgency(data.get("urgency_score"))
    urgency_min = expected.get("urgency_min")
    urgency_max = expected.get("urgency_max")

    if not has_error:
        valid_range = type(urgency_min) is int and type(urgency_max) is int and urgency_min <= urgency_max
        dimensions["urgency_exact_range"] = bool(
            valid_range and urgency is not None and urgency_min <= urgency <= urgency_max
        )
        if valid_range and urgency is not None:
            expected_bands = {_action_band(score) for score in range(urgency_min, urgency_max + 1)}
            dimensions["urgency_action_band"] = _action_band(urgency) in expected_bands
        else:
            dimensions["urgency_action_band"] = False

        if "affected_countries" in expected:
            dimensions["affected_countries"] = _set_dimension(
                data.get("affected_countries"), expected["affected_countries"]
            )

        expected_facts = _mapping(expected.get("facts"))
        if "attack_countries" in expected_facts:
            dimensions["attack_countries"] = _set_dimension(
                facts.get("attack_countries"), expected_facts["attack_countries"]
            )
        for name in ("protection", "status"):
            if name in expected_facts:
                dimensions[name] = facts.get(name) == expected_facts[name]
        expected_evidence = _mapping(expected_facts.get("evidence"))
        for name in ("attack_countries", "protection", "status"):
            if name in expected_evidence:
                dimensions[f"{name}_evidence"] = _evidence_dimension(evidence.get(name), expected_evidence[name])

        notification = row.get("notification")
        if not reference_mode:
            dimensions["notification"] = (
                notification == expected.get("notification") if notification in _NOTIFICATIONS else False
            )

    relation = expected.get("relation")
    same_as = expected.get("same_as")
    candidate_ids = _string_set(row.get("candidate_ids"))
    anchor_known = relation == "same" and isinstance(same_as, str) and same_as in prior_events
    anchor_id = prior_events.get(same_as) if anchor_known else None
    anchor_created = isinstance(anchor_id, str) and bool(anchor_id)
    anchor_presented = anchor_created and candidate_ids is not None and anchor_id in candidate_ids
    retrieval_failure = bool(anchor_created and not anchor_presented)
    identity_scorable = relation == "new" or (relation == "same" and anchor_presented)

    raw_memory = _mapping(data.get("incident_memory"))
    raw_identity: bool | None = None
    accepted_identity: bool | None = None
    if not has_error and identity_scorable:
        raw_identity = _identity(raw_memory, relation, anchor_id)
        accepted_identity = None if reference_mode else _identity(accepted, relation, anchor_id)
        dimensions["raw_incident_identity"] = raw_identity
        dimensions["accepted_incident_identity"] = accepted_identity

        event_id = row.get("event_id")
        if reference_mode:
            pass
        elif relation == "same":
            # Low-tier classifications are deliberately not materialized as event
            # updates.  The accepted memory decision remains the observable identity.
            if event_id is None and urgency is not None and urgency < 5 and accepted_identity:
                dimensions["persisted_incident_identity"] = None
            else:
                dimensions["persisted_incident_identity"] = event_id == anchor_id
        else:
            prior_ids = {value for value in prior_events.values() if isinstance(value, str)}
            if event_id is None and urgency is not None and urgency < 5 and accepted_identity:
                dimensions["persisted_incident_identity"] = None
            else:
                dimensions["persisted_incident_identity"] = isinstance(event_id, str) and event_id not in prior_ids

    program_gate_rejection = bool(raw_identity is True and accepted_identity is False)

    notification = row.get("notification")
    expected_notification = expected.get("notification")
    required_notification = expected_notification in {"initial", "update"}
    required_notification_miss = bool(
        not reference_mode
        and required_notification
        and (has_error or notification == "silent" or notification not in _NOTIFICATIONS)
    )
    critical_score_undercall = bool(
        not has_error and expected.get("critical") is True and urgency is not None and urgency < 9
    )
    required_critical_notification_miss = bool(
        not reference_mode
        and required_notification
        and expected.get("critical") is True
        and (has_error or required_notification_miss or urgency is None or urgency < 9)
    )
    duplicate_notification = bool(
        not reference_mode
        and not has_error
        and relation == "same"
        and expected_notification == "silent"
        and notification in {"initial", "update"}
    )
    false_alert = bool(
        not reference_mode
        and not has_error
        and expected_notification == "silent"
        and notification in {"initial", "update"}
    )

    prior_ids = {value for value in prior_events.values() if isinstance(value, str)}
    raw_decision, accepted_decision = raw_memory.get("decision"), accepted.get("decision")
    raw_merge = (
        isinstance(raw_decision, str)
        and raw_decision in _MATCH_DECISIONS
        and isinstance(raw_memory.get("matched_event_id"), str)
        and raw_memory.get("matched_event_id") in prior_ids
    )
    accepted_merge = (isinstance(accepted_decision, str) and accepted_decision in _MATCH_DECISIONS) or accepted.get(
        "matched_event_id"
    ) is not None
    persisted_merge = isinstance(row.get("event_id"), str) and row.get("event_id") in prior_ids
    wrong_merge = bool(
        not reference_mode and not has_error and relation == "new" and (accepted_merge or persisted_merge)
    )
    raw_wrong_merge = bool(not has_error and relation == "new" and raw_merge)

    expected_facts = _mapping(expected.get("facts"))
    evidence_reported = {
        name: bool(isinstance(evidence.get(name), str) and evidence[name].strip())
        if not has_error and name in expected_facts
        else None
        for name in ("attack_countries", "protection", "status")
    }

    return {
        "dimensions": dimensions,
        "evidence_reported": evidence_reported,
        "error": has_error,
        "retrieval_failure": retrieval_failure,
        "program_gate_rejection": program_gate_rejection,
        "required_notification_miss": required_notification_miss,
        "required_critical_notification_miss": required_critical_notification_miss,
        "critical_score_undercall": critical_score_undercall,
        "duplicate_notification": duplicate_notification,
        "wrong_merge": wrong_merge,
        "raw_wrong_merge": raw_wrong_merge,
        "false_alert": false_alert,
        "transport_error": _is_transport_error(row),
    }


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def aggregate_dimensions(rows: Sequence[Mapping[str, Any]]) -> dict:
    """Aggregate dimension numerators/denominators and operational outcomes.

    Disputed labels remain represented in ``status_counts`` and the caller's raw
    report, but are excluded from semantic and alert counters.  Latency describes
    requests rather than label correctness, so it is calculated independently over
    every row with a finite measurement.
    """

    status_counts = Counter(str(row.get("label_status") or "unknown") for row in rows)
    main_rows = [row for row in rows if row.get("label_status") != "disputed"]

    def evaluation(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return _mapping(row.get("evaluation"))

    dimension_names = list(DIMENSION_NAMES)
    extras = sorted(
        {
            name
            for row in main_rows
            for name in _mapping(evaluation(row).get("dimensions"))
            if name not in DIMENSION_NAMES
        }
    )
    dimensions: dict[str, dict[str, int]] = {}
    for name in (*dimension_names, *extras):
        values = [_mapping(evaluation(row).get("dimensions")).get(name) for row in main_rows]
        scored = [value for value in values if isinstance(value, bool)]
        dimensions[name] = {"correct": sum(value is True for value in scored), "scored": len(scored)}

    flags = {name: sum(bool(evaluation(row).get(name)) for row in main_rows) for name in _FLAG_NAMES}

    evidence_reporting = {}
    for name in ("attack_countries", "protection", "status"):
        values = [_mapping(evaluation(row).get("evidence_reported")).get(name) for row in main_rows]
        eligible = [value for value in values if isinstance(value, bool)]
        evidence_reporting[name] = {
            "reported": sum(value is True for value in eligible),
            "eligible": len(eligible),
        }

    by_sequence: dict[str, dict[str, int]] = {}
    for row in main_rows:
        if row.get("context_mode") == "reference":
            continue
        expected = _mapping(row.get("expected"))
        sequence = str(row.get("sequence_id") or "unknown")
        counts = by_sequence.setdefault(
            sequence,
            {"required": 0, "delivered": 0, "missed": 0, "unexpected": 0},
        )
        required = expected.get("notification") in {"initial", "update"}
        delivered = row.get("notification") in {"initial", "update"} and not row.get("error")
        if required:
            counts["required"] += 1
            counts["missed"] += int(bool(evaluation(row).get("required_notification_miss")))
            counts["delivered"] += int(delivered)
        elif delivered:
            counts["unexpected"] += 1

    alert_events = {
        "required": sum(counts["required"] for counts in by_sequence.values()),
        "delivered": sum(counts["delivered"] for counts in by_sequence.values()),
        "missed": sum(counts["missed"] for counts in by_sequence.values()),
        "unexpected": sum(counts["unexpected"] for counts in by_sequence.values()),
        "by_sequence": by_sequence,
        "sequences_with_required_critical_miss": sorted(
            {
                str(row.get("sequence_id"))
                for row in main_rows
                if evaluation(row).get("required_critical_notification_miss")
            }
        ),
    }

    latencies = [
        float(row["latency_seconds"])
        for row in rows
        if isinstance(row.get("latency_seconds"), (int, float))
        and not isinstance(row.get("latency_seconds"), bool)
        and math.isfinite(float(row["latency_seconds"]))
        and row["latency_seconds"] >= 0
    ]

    return {
        "reported": len(rows),
        "main_scored": len(main_rows),
        "status_counts": dict(status_counts),
        "dimensions": dimensions,
        "flags": flags,
        "evidence_reporting": evidence_reporting,
        "alert_events": alert_events,
        # Label uncertainty does not make a failed HTTP request disappear.
        "transport_errors": sum(
            bool(evaluation(row).get("transport_error")) or _is_transport_error(row) for row in rows
        ),
        "latency": {
            "count": len(latencies),
            "median_seconds": statistics.median(latencies) if latencies else None,
            "p95_seconds": _percentile_95(latencies),
        },
    }
