"""Report generation and the pre-registered decision rule, on synthetic results."""

import json
import random

from sentinel.eval.suite.price import price_table
from sentinel.eval.suite.report import build_html, decide, pareto
from sentinel.eval.suite.score import score_run

PRICES = {
    "base": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "cheap_good": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
    "cheap_broken": {"input": 0.05, "cached_input": 0.01, "output": 0.20},
}


def build_run(tmp_path):
    rng = random.Random(4)
    items, labels, rows = [], [], []
    for n in range(60):
        urgency = 9 if n < 20 else (6 if n < 40 else 2)
        tier = {9: "FLEE", 6: "NOTE", 2: "NOISE"}[urgency]
        items.append(
            {
                "id": f"i{n}",
                "origin": "production",
                "pool": "dev",
                "cluster_id": f"c{n // 3}",
                "chain_id": None,
                "chain_pos": None,
                "article": {"language": ["pl", "en", "uk"][n % 3]},
                "input": {"enrichment": "none", "fetched": False},
            }
        )
        labels.append(
            {
                "slot": f"s{n}",
                "item_id": f"i{n}",
                "retest_of": None,
                "tier": tier,
                "urgency": urgency,
                "urgency_alt": None,
                "countries": ["PL"] if urgency == 9 else [],
                "bad_input": False,
                "note": "",
                "same_as": None,
                "notify": None,
            }
        )
        for model, cost in (("base", 0.0008), ("cheap_good", 0.0004), ("cheap_broken", 0.0002)):
            for repeat in range(3):
                answer = urgency if rng.random() > 0.1 else max(1, urgency - 3)
                broken = model == "cheap_broken" and rng.random() < 0.2
                rows.append(
                    {
                        "model": model,
                        "repeat": repeat,
                        "item_id": f"i{n}",
                        "chain_id": None,
                        "usage": {"prompt_tokens": 2000, "completion_tokens": 260, "cached_tokens": 0},
                        "cost_usd": cost,
                        "latency_seconds": 3.0,
                        "error_kind": "invalid_output" if broken else None,
                        "urgency": None if broken else answer,
                        "countries": None if broken else (["PL"] if answer >= 9 else []),
                        "summary_polish": None if broken else True,
                    }
                )
    (tmp_path / "items.json").write_text(json.dumps({"items": items}))
    (tmp_path / "queue.json").write_text(
        json.dumps({"slots": [{"slot": f"s{n}", "item_id": f"i{n}"} for n in range(60)]})
    )
    (tmp_path / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels))
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"name": "t", "pool": "dev", "repeats": 3}))
    (run / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    score = score_run(run, tmp_path / "labels.jsonl", tmp_path / "queue.json", tmp_path / "items.json", "base")
    snapshot = {
        "daily": [{"n": 245}] * 20 + [{"n": 400}] * 3,
        "baseline_usage": {"input": 3900, "cached": 1700, "output": 266},
    }
    prices = price_table(score["models"], "base", snapshot, PRICES, monthly_cap=10)
    return score, prices


def test_pareto_front():
    points = [("a", 1.0, 0.9), ("b", 2.0, 0.8), ("c", 0.5, 0.7), ("d", 3.0, 0.95)]
    assert pareto(points) == {"a", "c", "d"}


def test_decision_rule_rejects_broken_and_accepts_cheap_equivalent(tmp_path):
    score, prices = build_run(tmp_path)
    broken = decide("cheap_broken", "base", score, prices)
    assert not broken["replace"] and not broken["checks"]["Zepsute odpowiedzi ≤ 0.5%"]
    good = decide("cheap_good", "base", score, prices)
    assert good["checks"]["Tańszy albo udowodnienie lepszy"]
    assert good["checks"]["Mieści się w limicie w tłocznym miesiącu"]


def test_build_html_contains_every_section(tmp_path):
    score, prices = build_run(tmp_path)
    page = build_html(score, prices, {"base": "GPT-5.6 Luna"})
    for heading in (
        "Werdykt",
        "Czy kandydat może zastąpić Lunę",
        "Jakość względem ceny",
        "Ile kosztowałby zamiast Luny",
        "Serie artykułów",
    ):
        assert heading in page
    assert "<svg" in page and "GPT-5.6 Luna" in page
    (tmp_path / "report.html").write_text(page)


def test_decision_rule_coverage_false_call_margin_and_pool(tmp_path):
    score, prices = build_run(tmp_path)
    score["models"]["cheap_good"]["missing_answers"] = 3
    assert not decide("cheap_good", "base", score, prices)["checks"]["Odpowiedział na każdy artykuł"]
    score["models"]["cheap_good"]["missing_answers"] = 0
    score["paired_vs_baseline"]["cheap_good"]["false_call"] = {
        "difference": (0.02, 0.0, 0.05),
        "verdict": "bez udowodnionej różnicy",
    }
    checks = decide("cheap_good", "base", score, prices)["checks"]
    assert not checks["Telefonów bez powodu najwyżej 1% pkt więcej"]
    page = build_html(score, prices, {})
    assert "To pula robocza" in page


def test_items_never_attempted_fail_coverage(tmp_path):
    score, prices = build_run(tmp_path)
    run = tmp_path / "run"
    rows = [json.loads(line) for line in (run / "calls.jsonl").read_text().splitlines()]
    kept = [r for r in rows if not (r["model"] == "cheap_good" and r["item_id"] == "i0")]  # never asked
    (run / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in kept))
    rescored = score_run(run, tmp_path / "labels.jsonl", tmp_path / "queue.json", tmp_path / "items.json", "base")
    report = rescored["models"]["cheap_good"]
    assert report["missing_answers"] == 3 and report["unavailable_items"] == 1
    assert not decide("cheap_good", "base", rescored, prices)["checks"]["Odpowiedział na każdy artykuł"]


def test_reasoning_specs_are_flagged_in_the_report(tmp_path):
    score, prices = build_run(tmp_path)
    score["models"]["z/glm@Together+reasoning"] = score["models"].pop("cheap_good")
    score["paired_vs_baseline"]["z/glm@Together+reasoning"] = score["paired_vs_baseline"].pop("cheap_good")
    prices["models"]["z/glm@Together+reasoning"] = prices["models"].pop("cheap_good")
    assert "inne warunki niż produkcja" in build_html(score, prices, {})
