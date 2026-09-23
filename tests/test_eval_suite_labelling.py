"""Eval-suite sampling and blind-labelling logic (no network, no production access)."""

import json
import random

import pytest

from sentinel.eval.suite.label_server import (
    LabelStore,
    build_queue,
    latest_labels,
    page_labels,
    public_view,
    validate_label,
)
from sentinel.eval.suite.sample import assign_pools, cluster, dedupe, pick_chains, stratum


def row(id_, day, urgency, countries=("PL",), source="A", title=None):
    return {
        "id": id_,
        "fetched_at": f"2026-09-{day:02d}T10:00:00+00:00",
        "prod_urgency": urgency,
        "prod_countries": json.dumps(list(countries)),
        "source_name": source,
        "title_normalized": title or id_,
    }


def item(id_, origin="production", chain=None, pos=None, cluster_id=None, urgency=5):
    return {
        "id": id_,
        "origin": origin,
        "chain_id": chain,
        "chain_pos": pos,
        "cluster_id": cluster_id or f"c-{id_}",
        "article": {
            "title": f"T {id_}",
            "summary": "S",
            "source_name": "src",
            "source_type": "rss",
            "language": "pl",
            "published_at": "2026-09-01T00:00:00+00:00",
            "fetched_at": f"2026-09-01T00:00:{(pos or 0):02d}+00:00",
        },
        "prod": {"urgency": urgency, "countries": [], "model": "m", "military": True},
        "target": "secret",
    }


def test_stratum_boundaries():
    assert [stratum(u) for u in (1, 4, 5, 6, 7, 8, 9, 10)] == ["1-4", "1-4", "5-6", "5-6", "7-8", "7-8", "9-10", "9-10"]


def test_dedupe_keeps_earliest_copy():
    rows = [row("b", 2, 9, title="same"), row("a", 1, 9, title="same"), row("c", 1, 3)]
    assert [r["id"] for r in dedupe(rows)] == ["a", "c"]


def test_cluster_links_same_day_country_and_events_but_never_across_days():
    rows = [row("a", 1, 9), row("b", 1, 7), row("c", 2, 9), row("d", 1, 9, countries=("LT",)), row("e", 1, 2, ())]
    events = [{"article_ids": json.dumps(["a", "c"])}, {"article_ids": json.dumps(["d", "e"])}]
    clusters = cluster(rows, events)
    assert clusters["a"] == clusters["b"]  # same day, same country
    assert clusters["a"] != clusters["c"]  # shared event, but a different day
    assert clusters["d"] == clusters["e"]  # shared event on the same day
    assert clusters["a"] != clusters["d"]  # same day, different country


def test_pick_chains_needs_critical_tier_and_several_sources():
    rows = [row(f"x{i}", 1, 9 if i == 0 else 4, source=f"s{i % 2}") for i in range(8)]
    rows += [row(f"y{i}", 2, 4, source=f"s{i}") for i in range(5)]
    clusters = {r["id"]: ("cx" if r["id"].startswith("x") else "cy") for r in rows}
    chains = pick_chains(rows, clusters)
    assert len(chains) == 1 and len(chains[0]) == 6
    assert chains[0][0]["id"] == "x0" and chains[0][-1]["id"] == "x7"


def test_assign_pools_keeps_clusters_whole_and_roughly_splits():
    items = [item(f"i{n}", cluster_id=f"c{n // 2}", urgency=9) for n in range(20)]
    assign_pools(items, random.Random(1), dev_share=0.4)
    by_cluster = {}
    for it in items:
        by_cluster.setdefault(it["cluster_id"], set()).add(it["pool"])
    assert all(len(pools) == 1 for pools in by_cluster.values())
    assert 6 <= sum(it["pool"] == "dev" for it in items) <= 10


def test_queue_keeps_chains_in_order_and_hides_repeats_at_end():
    items = [item(f"p{n}") for n in range(100)] + [item(f"k{n}", "holdout", "seq", n) for n in range(4)]
    queue = build_queue(items, seed=3, retest_count=10)
    ids = [s["item_id"] for s in queue]
    chain_positions = [ids.index(f"k{n}") for n in range(4)]
    assert chain_positions == sorted(chain_positions) and chain_positions[-1] - chain_positions[0] == 3
    repeats = [s for s in queue if s["retest_of"]]
    assert len(repeats) == 10 and all(s["retest_of"] == s["item_id"] for s in repeats)
    first_60 = {s["item_id"] for s in queue[: int(104 * 0.6)]}
    assert all(s["item_id"] in first_60 for s in repeats)
    assert all(queue.index(s) >= int(104 * 0.6) for s in repeats)
    assert queue[-10:] != repeats  # spread out, not a block at the end
    assert [s["slot"] for s in queue] == [f"s{n:03d}" for n in range(1, 115)]
    assert build_queue(items, seed=3, retest_count=10) == queue


def test_public_view_never_leaks_scores_origin_or_target():
    view = public_view(item("p1", urgency=10), {"slot": "s001", "retest_of": None}, [])
    assert set(view) == {
        "slot",
        "title",
        "summary",
        "source_name",
        "source_type",
        "language",
        "published_at",
        "in_chain",
        "chain_earlier",
        "translation",
    }
    translated = public_view(item("p1"), {"slot": "s001", "retest_of": None}, [], {"title_pl": "T", "summary_pl": "S"})
    assert translated["translation"] == {"title_pl": "T", "summary_pl": "S"}


def test_validate_label_enforces_tier_ranges_and_countries():
    slots = {"s001": {"slot": "s001", "item_id": "p1", "retest_of": None}}
    ok = validate_label({"slot": "s001", "tier": "WATCH", "urgency": 8, "countries": ["LT", "PL"]}, slots)
    assert ok["countries"] == ["LT", "PL"] and ok["item_id"] == "p1"
    for bad in (
        {"slot": "s001", "tier": "NOISE", "urgency": 9},
        {"slot": "s001", "tier": "FLEE", "urgency": 9, "countries": ["DE"]},
        {"slot": "s999", "tier": "FLEE", "urgency": 9},
        {"slot": "s001", "tier": "FLEE", "urgency": 9, "urgency_alt": 11},
        {"slot": "s001", "tier": "FLEE", "urgency": 9, "urgency_alt": 2},
        {"slot": "s001", "tier": "FLEE", "urgency": 9, "notify": "yes"},
    ):
        with pytest.raises(ValueError):
            validate_label(bad, slots)


def test_store_appends_and_last_answer_wins(tmp_path):
    items = [item("p1"), item("p2")]
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps({"items": items, "items_sha256": "abc"}))
    store = LabelStore(items_path, tmp_path / "queue.json", tmp_path / "labels.jsonl", seed=1)
    slot = store.slots[0]["slot"]
    store.save({"slot": slot, "tier": "NOTE", "urgency": 5})
    store.save({"slot": slot, "tier": "NOTE", "urgency": 6})
    assert latest_labels(tmp_path / "labels.jsonl")[slot]["urgency"] == 6
    assert len((tmp_path / "labels.jsonl").read_text().splitlines()) == 2
    items_path.write_text(json.dumps({"items": items, "items_sha256": "changed"}))
    with pytest.raises(SystemExit):
        LabelStore(items_path, tmp_path / "queue.json", tmp_path / "labels.jsonl", seed=1)


def test_page_labels_hide_item_ids(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps({"slot": "s001", "item_id": "syn-ru-01", "retest_of": None, "tier": "NOTE"}) + "\n")
    assert page_labels(path) == {"s001": {"slot": "s001", "tier": "NOTE"}}
