"""Phase 2 acceptance tests for the single AlertPolicy authority + decision consolidation."""

import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from sentinel.alerts.policy import (
    AlertPolicy,
    ChannelClass,
    EventDecision,
    GeoTier,
    Relation,
    call_tier_min,
)
from sentinel.alerts.state_machine import EVENT_TYPE_PL, AlertStateMachine
from sentinel.classification import classifier as classifier_module
from sentinel.classification.corroborator import Corroborator
from sentinel.config import ChannelBand
from sentinel.eval import harness as harness_module
from sentinel.models import Article, ClassificationResult, Event

_FIXTURE = Path(__file__).parent / "fixtures" / "dedup_traps.yaml"


@pytest.fixture
def policy(config):
    return AlertPolicy(config)


def _new(relation=Relation.NEW, matched_event_id=None):
    return EventDecision(relation=relation, matched_event_id=matched_event_id)


def _all_keys(obj):
    """Recursively yield every dict key anywhere in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_keys(item)


# --------------------------------------------------------------------------
# 1. [2.4, 2.5, 2.6] NEW, urgency 9, geo HIGH -> CALL.
# --------------------------------------------------------------------------
def test_new_critical_high_calls(policy):
    intent = policy.decide(_new(), urgency=9, geo_tier=GeoTier.HIGH)
    assert intent.channel_class is ChannelClass.CALL


# --------------------------------------------------------------------------
# 2. [2.6] ESCALATION on an event already alerted at CALL -> NOTIFY, not a 2nd CALL.
# --------------------------------------------------------------------------
def test_escalation_high_notifies_not_recall(policy):
    intent = policy.decide(
        _new(Relation.ESCALATION), urgency=9, geo_tier=GeoTier.HIGH, already_alerted_at=ChannelClass.CALL
    )
    assert intent.channel_class is ChannelClass.NOTIFY


# --------------------------------------------------------------------------
# 2b. [2.6] ESCALATION on an event previously alerted at NOTIFY only, now 10/HIGH -> CALL (first call).
# --------------------------------------------------------------------------
def test_escalation_first_call_fires(policy):
    intent = policy.decide(
        _new(Relation.ESCALATION), urgency=10, geo_tier=GeoTier.HIGH, already_alerted_at=ChannelClass.NOTIFY
    )
    assert intent.channel_class is ChannelClass.CALL


# --------------------------------------------------------------------------
# 3. [2.3] SAME on an already-alerted event -> no alert.
# --------------------------------------------------------------------------
def test_same_already_alerted_suppresses(policy):
    intent = policy.decide(_new(Relation.SAME), urgency=9, geo_tier=GeoTier.HIGH, already_alerted_at=ChannelClass.CALL)
    assert intent.channel_class is ChannelClass.NONE
    # A SAME at NOTIFY band on an already-alerted event is also suppressed.
    intent2 = policy.decide(
        _new(Relation.SAME), urgency=7, geo_tier=GeoTier.HIGH, already_alerted_at=ChannelClass.NOTIFY
    )
    assert intent2.channel_class is ChannelClass.NONE


# --------------------------------------------------------------------------
# 4. [2.2] NEW, urgency 9, geo HIGH, single source -> still CALL; no corroboration key in config.
# --------------------------------------------------------------------------
def test_no_corroboration_gate(policy, config):
    # Source count is never an input to decide() -> a single source still CALLs.
    intent = policy.decide(_new(), urgency=9, geo_tier=GeoTier.HIGH)
    assert intent.channel_class is ChannelClass.CALL

    # Neither corroboration_required key exists anywhere in the loaded config.
    assert "corroboration_required" not in set(_all_keys(config.model_dump()))
    assert not hasattr(config.classification, "corroboration_required")
    assert not hasattr(next(iter(config.alerts.urgency_levels.values())), "corroboration_required")


# --------------------------------------------------------------------------
# 5. [2.5] NEW, urgency 9, geo LOW (inside-UA) -> demoted to NOTIFY (not CALL, not NONE).
# --------------------------------------------------------------------------
def test_low_geo_critical_does_not_call(policy):
    intent = policy.decide(_new(), urgency=9, geo_tier=GeoTier.LOW)
    assert intent.channel_class is ChannelClass.NOTIFY
    assert intent.channel_class is not ChannelClass.CALL
    assert intent.channel_class is not ChannelClass.NONE


# --------------------------------------------------------------------------
# 6. [2.5a] NEW, urgency 9, geo UNKNOWN -> treated HIGH -> CALL (fail toward firing).
# --------------------------------------------------------------------------
def test_unknown_geo_critical_fails_open(policy):
    intent = policy.decide(_new(), urgency=9, geo_tier=GeoTier.UNKNOWN)
    assert intent.channel_class is ChannelClass.CALL


# --------------------------------------------------------------------------
# 7. [2.4] NEW, urgency 5, geo HIGH -> NOTIFY, not CALL.
# --------------------------------------------------------------------------
def test_lower_urgency_notifies(policy):
    intent = policy.decide(_new(), urgency=5, geo_tier=GeoTier.HIGH)
    assert intent.channel_class is ChannelClass.NOTIFY


# --------------------------------------------------------------------------
# 11. [2.8] Move the call-tier threshold in config -> the CALL boundary shifts.
# --------------------------------------------------------------------------
def test_thresholds_config_driven(config):
    assert call_tier_min(config) == 9
    default_policy = AlertPolicy(config)
    assert default_policy.decide(_new(), urgency=9, geo_tier=GeoTier.HIGH).channel_class is ChannelClass.CALL

    # Raise the call tier to 10: urgency 9 now resolves to NOTIFY, 10 still CALLs.
    config.alerts.channel_bands = [
        ChannelBand(min_score=10, channel_class="call"),
        ChannelBand(min_score=5, channel_class="notify"),
        ChannelBand(min_score=1, channel_class="none"),
    ]
    raised = AlertPolicy(config)
    assert call_tier_min(config) == 10
    assert raised.decide(_new(), urgency=9, geo_tier=GeoTier.HIGH).channel_class is ChannelClass.NOTIFY
    assert raised.decide(_new(), urgency=10, geo_tier=GeoTier.HIGH).channel_class is ChannelClass.CALL


# --------------------------------------------------------------------------
# 12. [2.1] The three old decision sites are removed / delegating; MONITORED_COUNTRIES survives.
# --------------------------------------------------------------------------
def test_old_decision_sites_removed(db, config):
    assert not hasattr(Corroborator, "_determine_alert_status")
    assert not hasattr(harness_module, "_action_for_urgency")
    assert hasattr(harness_module, "MONITORED_COUNTRIES")
    assert "RO" in harness_module.MONITORED_COUNTRIES

    sm = AlertStateMachine(db, MagicMock(), config, push_client=MagicMock())
    assert isinstance(sm.policy, AlertPolicy)

    # _determine_action delegates the band decision to the AlertPolicy.
    sm.policy.decide = MagicMock(wraps=sm.policy.decide)
    event = Event(
        event_type="missile_strike",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosja wystrzeliła rakiety.",
        first_seen_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
        source_count=1,
        article_ids=["a"],
    )
    action = sm._determine_action(event)
    sm.policy.decide.assert_called()
    assert action == "phone_call"


# --------------------------------------------------------------------------
# 13. [2.9, 2.10] The EventDecision contract exposes relation + matched_event_id.
# --------------------------------------------------------------------------
def test_event_decision_contract(policy):
    d = EventDecision(relation=Relation.ESCALATION, matched_event_id="evt-123")
    assert d.relation is Relation.ESCALATION
    assert d.matched_event_id == "evt-123"

    d2 = EventDecision(Relation.NEW)
    assert d2.relation is Relation.NEW
    assert d2.matched_event_id is None

    # AlertPolicy consumes an EventDecision and echoes its relation in the AlertIntent.
    intent = policy.decide(d, urgency=9, geo_tier=GeoTier.HIGH, already_alerted_at=ChannelClass.CALL)
    assert intent.relation is Relation.ESCALATION


# --------------------------------------------------------------------------
# 14. [2.4, 2.3] NEW, urgency 2 and 4, any geo -> NONE (no alert), by banding.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("urgency", [1, 2, 4])
@pytest.mark.parametrize("geo", [GeoTier.HIGH, GeoTier.LOW, GeoTier.UNKNOWN])
def test_none_band_silent(policy, urgency, geo):
    intent = policy.decide(_new(), urgency=urgency, geo_tier=geo)
    assert intent.channel_class is ChannelClass.NONE


# --------------------------------------------------------------------------
# 15. [2.12, 2.4] For every labeled event in the ground truth, the band map matches the owner action.
# --------------------------------------------------------------------------
_ACTION_TO_CLASS = {"call": ChannelClass.CALL, "sms": ChannelClass.NOTIFY, "none": ChannelClass.NONE}


def _ground_truth_events():
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    out = []
    for pile in data["piles"]:
        for ev in pile["label"]["events"]:
            out.append((pile["id"], ev["event"], ev["urgency"], ev["action"]))
    return out


@pytest.mark.parametrize("pile_id,event_no,urgency,action", _ground_truth_events())
def test_policy_bands_match_ground_truth(policy, pile_id, event_no, urgency, action):
    assert policy.band_for_urgency(urgency) is _ACTION_TO_CLASS[action], (
        f"{pile_id} event {event_no}: urgency {urgency} -> {policy.band_for_urgency(urgency)}, owner action {action}"
    )


# --------------------------------------------------------------------------
# 16. [2.13] The pre-event urgency gate follows config; the military-flag drop is exempted for 0.15 types.
# --------------------------------------------------------------------------
def _insert_article(db, url):
    article = Article(
        source_name="Test",
        source_url=url,
        source_type="rss",
        title="Oświadczenie rządu w sprawie zagrożenia",
        summary="test",
        language="pl",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    db.insert_article(article)
    return article


def _statement_result(article_id, urgency, *, is_military=True, summary="Oświadczenie rządu."):
    return ClassificationResult(
        article_id=article_id,
        is_military_event=is_military,
        event_type="official_statement",
        urgency_score=urgency,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.9,
        summary_pl=summary,
        classified_at=datetime.now(UTC),
        model_used="claude-haiku-4-5-20251001",
        input_tokens=1,
        output_tokens=1,
    )


def test_min_event_urgency_config_driven(db, config):
    # Gate = 3: an urgency-5 official_statement creates an event.
    config.dedup.min_event_urgency = 3
    art = _insert_article(db, "https://example.com/a1")
    events = Corroborator(db, config).process_classifications([_statement_result(art.id, 5, summary="Oświadczenie A.")])
    assert len(events) == 1

    # Gate = 6: the same urgency-5 official_statement does NOT create an event.
    config.dedup.min_event_urgency = 6
    art2 = _insert_article(db, "https://example.com/a2")
    events2 = Corroborator(db, config).process_classifications(
        [_statement_result(art2.id, 5, summary="Oświadczenie B.")]
    )
    assert events2 == []

    # is_military_event=false, urgency 6 -> still creates an event (military-flag drop exempted for 0.15 types).
    config.dedup.min_event_urgency = 5
    art3 = _insert_article(db, "https://example.com/a3")
    events3 = Corroborator(db, config).process_classifications(
        [_statement_result(art3.id, 6, is_military=False, summary="Oświadczenie C.")]
    )
    assert len(events3) == 1


# --------------------------------------------------------------------------
# 17. [2.14] Every classifier event_type enum value has a Polish rendering in the alert-template mapping.
# --------------------------------------------------------------------------
def test_event_type_pl_covers_enum():
    match = re.search(r'"event_type":\s*"([^"]+)"', classifier_module.USER_PROMPT_TEMPLATE)
    assert match, "event_type enum not found in the classifier prompt"
    enum_values = match.group(1).split("|")

    assert "debris_found" in enum_values
    assert "official_statement" in enum_values

    missing = [v for v in enum_values if v not in EVENT_TYPE_PL]
    assert not missing, f"event_type values without a Polish rendering: {missing}"
