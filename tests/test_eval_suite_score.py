"""Eval-suite scoring on hand-made labels and model rows with known answers."""

import json

import pytest

from sentinel.eval.suite.score import (
    action,
    item_outcomes,
    majority,
    quadratic_weighted_kappa,
    retest_agreement,
    score_run,
    sequence_metrics,
    truth_from_labels,
)


def label(slot, item_id, tier, urgency, alt=None, countries=(), same_as=None, notify=None, retest_of=None):
    return {
        "slot": slot,
        "item_id": item_id,
        "retest_of": retest_of,
        "tier": tier,
        "urgency": urgency,
        "urgency_alt": alt,
        "countries": list(countries),
        "bad_input": False,
        "note": "",
        "same_as": same_as,
        "notify": notify,
    }


def call(model, item_id, urgency, repeat=0, countries=("PL",), chain_id=None, event_id=None, notification=None):
    row = {
        "model": model,
        "repeat": repeat,
        "item_id": item_id,
        "chain_id": chain_id,
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 0},
        "cost_usd": 0.001,
        "latency_seconds": 2.0,
        "error_kind": None,
        "urgency": urgency,
        "countries": list(countries),
        "summary_polish": True,
        "event_id": event_id,
        "notification": notification,
    }
    if urgency is None:
        row.update(error_kind="invalid_output", countries=None)
    return row


def item(id_, cluster="c1", chain=None, pos=None, lang="pl"):
    return {
        "id": id_,
        "origin": "production",
        "cluster_id": cluster,
        "chain_id": chain,
        "chain_pos": pos,
        "article": {"language": lang},
        "input": {"enrichment": "none", "fetched": False},
    }


def test_action_tiers_match_production():
    assert [action(u) for u in (1, 4, 5, 8, 9, 10)] == ["log", "log", "alert", "alert", "call", "call"]


def test_truth_uses_first_answer_range_and_adjudication():
    queue = [{"slot": "s1", "item_id": "a"}, {"slot": "s2", "item_id": "b"}, {"slot": "s3", "item_id": "a"}]
    labels = [
        label("s1", "a", "WATCH", 8, alt=9, countries=["PL"]),
        label("s2", "b", "NOTE", 5, same_as="s1", notify=False),
        label("s3", "a", "FLEE", 9, retest_of="a"),
    ]
    truth = truth_from_labels(labels, queue)
    assert truth["a"]["actions"] == {"alert", "call"} and truth["a"]["possible_call"] and not truth["a"]["critical"]
    assert truth["b"]["same_as"] == "a" and truth["b"]["notify"] is False
    adjudicated = truth_from_labels(labels, queue, [{"item_id": "a", "tier": "FLEE", "urgency": 10}])
    assert adjudicated["a"]["critical"] and adjudicated["a"]["adjudicated"]


def test_retest_agreement_counts_pairs():
    labels = [label("s1", "a", "WATCH", 8), label("s3", "a", "FLEE", 9, retest_of="a")]
    result = retest_agreement(labels)
    assert result["pairs"] == 1 and result["same_action"][0] == 0.0 and result["mean_abs_urgency_diff"] == 1


def test_majority_invalid_and_flips():
    assert majority([call("m", "a", None), call("m", "a", None), call("m", "a", 9)])["invalid"]
    agg = majority([call("m", "a", 9), call("m", "a", 8), call("m", "a", 10)])
    assert agg["urgency"] == 9 and agg["action"] == "call" and agg["flip"] and agg["flip_call_boundary"]


def test_item_outcomes_critical_false_call_and_invalid():
    critical = {"critical": True, "possible_call": True, "actions": {"call"}, "low": 9, "high": 9, "countries": {"PL"}}
    calm = {"critical": False, "possible_call": False, "actions": {"log"}, "low": 2, "high": 2, "countries": set()}
    miss = item_outcomes(majority([call("m", "a", 7)] * 3), critical)
    assert miss["critical_hit"] is False and miss["false_call"] is None and miss["abs_error"] == 2
    false_alarm = item_outcomes(majority([call("m", "a", 9, countries=["PL"])] * 3), calm)
    assert false_alarm["false_call"] is True and false_alarm["pl_error"] is True
    broken = item_outcomes(majority([call("m", "a", None)] * 3), critical)
    assert broken["critical_hit"] is False and broken["tier_ok"] is False


def test_quadratic_weighted_kappa_perfect_and_reversed():
    assert quadratic_weighted_kappa([1, 5, 9, 10], [1, 5, 9, 10]) == pytest.approx(1.0)
    assert quadratic_weighted_kappa([1, 10, 1, 10], [10, 1, 10, 1]) < 0


def test_sequence_metrics_wrong_merge_and_duplicate_notification():
    items = {
        "x0": item("x0", chain="ch", pos=0),
        "x1": item("x1", chain="ch", pos=1),
        "x2": item("x2", chain="ch", pos=2),
    }
    truth = {
        "x0": {"same_as": None, "notify": None, "critical": True, "low": 9},
        "x1": {"same_as": "x0", "notify": False, "critical": True, "low": 9},
        "x2": {"same_as": None, "notify": True, "critical": True, "low": 9},
    }
    calls = [
        call("m", "x0", 9, chain_id="ch", event_id="e1", notification="initial"),
        call("m", "x1", 9, chain_id="ch", event_id="e1", notification="update"),
        call("m", "x2", 9, chain_id="ch", event_id="e1", notification="silent"),
    ]
    result = sequence_metrics(calls, truth, items)
    assert result["same_ok"] == 1 and result["duplicate_notification"] == 1
    assert result["wrong_merge_critical"] == 1 and result["missed_notification"] == 1


def test_score_run_end_to_end(tmp_path):
    items = [item("a", "c1"), item("b", "c2"), item("c", "c3")]
    (tmp_path / "items.json").write_text(json.dumps({"items": items}))
    queue = [{"slot": f"s{i}", "item_id": i, "retest_of": None} for i in "abc"]
    (tmp_path / "queue.json").write_text(json.dumps({"slots": queue}))
    labels = [label("sa", "a", "FLEE", 9, countries=["PL"]), label("sb", "b", "NOISE", 2), label("sc", "c", "NOTE", 5)]
    (tmp_path / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels))
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"name": "t"}))
    rows = [call("base", "a", 7), call("base", "b", 2, countries=[]), call("base", "c", 5, countries=[])]
    rows += [call("cand", "a", 9), call("cand", "b", 9, countries=[]), call("cand", "c", None)]
    (run / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = score_run(run, tmp_path / "labels.jsonl", tmp_path / "queue.json", tmp_path / "items.json", "base")
    base, cand = result["models"]["base"], result["models"]["cand"]
    assert base["critical_recall"][0] == 0.0 and cand["critical_recall"][0] == 1.0
    assert cand["false_call_rate"][0] == 0.5 and cand["invalid_call_rate"][0] == pytest.approx(1 / 3)
    assert result["paired_vs_baseline"]["cand"]["critical_hit"]["n"] == 1
    assert result["critical_items"] == 1


def test_sequence_metrics_skips_low_pairs_and_outage_runs():
    items = {"y0": item("y0", chain="ch", pos=0), "y1": item("y1", chain="ch", pos=1)}
    truth = {
        "y0": {"same_as": None, "notify": None, "critical": False, "low": 2},
        "y1": {"same_as": "y0", "notify": False, "critical": False, "low": 2},
    }
    low = [call("m", "y0", 2, chain_id="ch"), call("m", "y1", 2, chain_id="ch", notification="silent")]
    result = sequence_metrics(low, truth, items)
    assert result["same_unscorable"] == 1 and result.get("same_expected", 0) == 0
    outage = dict(call("m", "y0", None, chain_id="ch"), error_kind="timeout")
    result = sequence_metrics([outage, call("m", "y1", 2, chain_id="ch")], truth, items)
    assert result == {"chain_runs_skipped_outage": 1}


def test_even_repeat_ties_are_scored_pessimistically():
    critical = {"critical": True, "possible_call": True, "actions": {"call"}, "low": 9, "high": 9, "countries": set()}
    calm = {"critical": False, "possible_call": False, "actions": {"alert"}, "low": 8, "high": 8, "countries": set()}
    tie = majority([call("m", "a", 9, countries=()), call("m", "a", 8, countries=()), call("m", "a", None)])
    assert item_outcomes(tie, critical)["critical_hit"] is False
    assert item_outcomes(tie, calm)["false_call"] is True
