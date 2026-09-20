"""Contract tests for independent model-comparison metrics."""

from sentinel.eval.separate_metrics import aggregate_dimensions, score_dimensions


def _case(
    *,
    relation="new",
    same_as=None,
    notification="initial",
    urgency_min=9,
    urgency_max=10,
    critical=True,
    facts=None,
):
    expected = {
        "urgency_min": urgency_min,
        "urgency_max": urgency_max,
        "affected_countries": ["PL"],
        "notification": notification,
        "relation": relation,
        "critical": critical,
    }
    if same_as is not None:
        expected["same_as"] = same_as
    if facts is not None:
        expected["facts"] = facts
    return {"expected": expected}


def _row(
    *,
    urgency=9,
    decision="new",
    matched_event_id=None,
    confidence=0.99,
    accepted=None,
    event_id="event-new",
    notification="initial",
    candidate_ids=(),
    error=None,
    facts=None,
):
    raw_memory = {
        "decision": decision,
        "matched_event_id": matched_event_id,
        "confidence": confidence,
        "reason": "test",
    }
    return {
        "data": {
            "urgency_score": urgency,
            "affected_countries": ["PL"],
            "facts": facts or {},
            "incident_memory": raw_memory,
        },
        "accepted_memory": accepted if accepted is not None else dict(raw_memory),
        "event_id": event_id,
        "notification": notification,
        "channels": [],
        "candidate_ids": list(candidate_ids),
        "error": error,
    }


def test_noncritical_anchor_missing_is_unscorable_not_model_ignorance():
    case = _case(
        relation="same",
        same_as="low-anchor",
        notification="silent",
        urgency_min=1,
        urgency_max=4,
        critical=False,
    )
    row = _row(urgency=3, decision="new", event_id=None, notification="silent")

    scored = score_dimensions(case, row, {"low-anchor": None})

    assert scored["dimensions"]["raw_incident_identity"] is None
    assert scored["dimensions"]["accepted_incident_identity"] is None
    assert scored["dimensions"]["persisted_incident_identity"] is None
    assert scored["retrieval_failure"] is False


def test_raw_correct_match_rejected_by_confidence_gate_is_visible():
    case = _case(relation="same", same_as="anchor", notification="silent")
    accepted = {
        "decision": "uncertain",
        "matched_event_id": None,
        "confidence": 0,
        "reason": "confidence gate",
    }
    row = _row(
        decision="duplicate",
        matched_event_id="event-anchor",
        confidence=0.85,
        accepted=accepted,
        event_id="event-new",
        notification="silent",
        candidate_ids=["event-anchor"],
    )

    scored = score_dimensions(case, row, {"anchor": "event-anchor"})

    assert scored["dimensions"]["raw_incident_identity"] is True
    assert scored["dimensions"]["accepted_incident_identity"] is False
    assert scored["program_gate_rejection"] is True


def test_retrieval_exclusion_is_reported_and_identity_has_no_denominator():
    case = _case(relation="same", same_as="anchor", notification="silent")
    row = _row(decision="uncertain", event_id="event-new", notification="silent", candidate_ids=["other"])

    scored = score_dimensions(case, row, {"anchor": "event-anchor"})

    assert scored["retrieval_failure"] is True
    assert scored["dimensions"]["raw_incident_identity"] is None
    assert scored["dimensions"]["accepted_incident_identity"] is None


def test_required_critical_duplicate_silent_is_not_a_separate_missed_attack():
    case = _case(relation="same", same_as="anchor", notification="silent", critical=True)
    row = _row(
        urgency=9,
        decision="duplicate",
        matched_event_id="event-anchor",
        event_id="event-anchor",
        notification="silent",
        candidate_ids=["event-anchor"],
    )

    scored = score_dimensions(case, row, {"anchor": "event-anchor"})

    assert scored["required_notification_miss"] is False
    assert scored["critical_score_undercall"] is False
    assert scored["dimensions"]["notification"] is True


def test_api_failure_misses_first_critical_but_not_its_silent_duplicate():
    first = score_dimensions(_case(), _row(error="transport_error: timeout", event_id=None), {})
    duplicate = score_dimensions(
        _case(relation="same", same_as="first", notification="silent"),
        _row(error="transport_error: timeout", event_id=None, notification=None),
        {"first": None},
    )

    assert first["error"] is True
    assert first["transport_error"] is True
    assert first["required_notification_miss"] is True
    assert first["dimensions"]["urgency_exact_range"] is None
    assert duplicate["required_notification_miss"] is False
    assert duplicate["critical_score_undercall"] is False


def test_new_attack_wave_merged_into_prior_event_is_wrong_merge():
    row = _row(
        decision="duplicate",
        matched_event_id="old-event",
        accepted={
            "decision": "duplicate",
            "matched_event_id": "old-event",
            "confidence": 0.99,
            "reason": "wrong wave",
        },
        event_id="old-event",
        candidate_ids=["old-event"],
    )

    scored = score_dimensions(_case(relation="new"), row, {"old-case": "old-event"})

    assert scored["dimensions"]["raw_incident_identity"] is False
    assert scored["dimensions"]["accepted_incident_identity"] is False
    assert scored["dimensions"]["persisted_incident_identity"] is False
    assert scored["wrong_merge"] is True


def test_facts_are_independent_from_urgency_and_from_each_other():
    facts = {"attack_countries": ["UA"], "protection": "official_warning", "status": "active"}
    case = _case(urgency_min=8, urgency_max=8, facts=facts)
    row = _row(
        urgency=6,
        facts={"attack_countries": ["PL"], "protection": "official_warning", "status": "resolved"},
    )

    dimensions = score_dimensions(case, row, {})["dimensions"]

    assert dimensions["urgency_exact_range"] is False
    assert dimensions["affected_countries"] is True
    assert dimensions["attack_countries"] is False
    assert dimensions["protection"] is True
    assert dimensions["status"] is False


def test_evidence_presence_is_not_grounding_correctness_without_an_explicit_label():
    expected_facts = {
        "attack_countries": ["UA"],
        "protection": "official_warning",
        "status": "active",
    }
    actual_facts = {
        **expected_facts,
        "evidence": {
            "attack_countries": "Russian missiles struck Ukraine",
            "protection": "Residents were told to seek shelter",
            "status": "The attack is under way",
        },
    }

    scored = score_dimensions(_case(facts=expected_facts), _row(facts=actual_facts), {})

    assert scored["evidence_reported"] == {
        "attack_countries": True,
        "protection": True,
        "status": True,
    }
    assert scored["dimensions"]["attack_countries_evidence"] is None


def test_explicit_evidence_label_is_scored_as_its_own_dimension():
    expected_facts = {
        "attack_countries": ["UA"],
        "evidence": {"attack_countries": "Russian missiles struck Ukraine"},
    }
    actual_facts = {
        "attack_countries": ["UA"],
        "evidence": {"attack_countries": "An unrelated quote"},
    }

    dimensions = score_dimensions(_case(facts=expected_facts), _row(facts=actual_facts), {})["dimensions"]

    assert dimensions["attack_countries"] is True
    assert dimensions["attack_countries_evidence"] is False


def test_grade_six_and_eight_miss_exact_range_but_share_action_band():
    dimensions = score_dimensions(
        _case(urgency_min=8, urgency_max=8, critical=False),
        _row(urgency=6),
        {},
    )["dimensions"]

    assert dimensions["urgency_exact_range"] is False
    assert dimensions["urgency_action_band"] is True


def test_low_tier_match_uses_accepted_identity_when_no_event_is_returned():
    case = _case(
        relation="same",
        same_as="anchor",
        notification="silent",
        urgency_min=1,
        urgency_max=4,
        critical=False,
    )
    row = _row(
        urgency=3,
        decision="duplicate",
        matched_event_id="event-anchor",
        event_id=None,
        notification="silent",
        candidate_ids=["event-anchor"],
    )

    dimensions = score_dimensions(case, row, {"anchor": "event-anchor"})["dimensions"]

    assert dimensions["accepted_incident_identity"] is True
    assert dimensions["persisted_incident_identity"] is None


def test_aggregate_uses_explicit_denominators_and_excludes_disputed_semantics():
    approved = {
        "case_id": "first",
        "sequence_id": "seq-a",
        "label_status": "approved",
        "expected": {"notification": "initial"},
        "notification": "silent",
        "latency_seconds": 2.0,
        "evaluation": score_dimensions(_case(), _row(notification="silent"), {}),
    }
    provisional = {
        "case_id": "duplicate",
        "sequence_id": "seq-a",
        "label_status": "assistant-reviewed",
        "expected": {"notification": "silent"},
        "notification": "silent",
        "latency_seconds": 4.0,
        "evaluation": score_dimensions(
            _case(relation="same", same_as="first", notification="silent"),
            _row(error="transport_error: mocked", notification=None, event_id=None),
            {"first": None},
        ),
    }
    disputed = {
        "case_id": "disputed",
        "sequence_id": "seq-b",
        "label_status": "disputed",
        "expected": {"notification": "initial"},
        "notification": "initial",
        "latency_seconds": 20.0,
        "evaluation": score_dimensions(_case(), _row(), {}),
    }

    result = aggregate_dimensions([approved, provisional, disputed])

    assert result["reported"] == 3
    assert result["main_scored"] == 2
    assert result["status_counts"] == {"approved": 1, "assistant-reviewed": 1, "disputed": 1}
    assert result["dimensions"]["urgency_exact_range"] == {"correct": 1, "scored": 1}
    assert result["dimensions"]["error_free"] == {"correct": 1, "scored": 2}
    assert result["alert_events"]["required"] == 1
    assert result["alert_events"]["missed"] == 1
    assert result["transport_errors"] == 1
    assert result["latency"] == {"count": 3, "median_seconds": 4.0, "p95_seconds": 20.0}
    assert "accuracy" not in result
