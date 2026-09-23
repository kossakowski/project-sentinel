"""Substitute-cost projection with hand-computed numbers."""

import pytest

from sentinel.eval.suite.price import per_article, price_table, token_cost, volume_scenarios

LUNA = {"input": 0.20, "cached_input": 0.02, "output": 1.20}
CHEAP = {"input": 0.10, "cached_input": 0.01, "output": 0.50}


def report(cost, calls=100, invalid=0.0, not_polish=0.0):
    return {"cost_usd": cost, "calls": calls, "invalid_call_rate": (invalid,), "summary_not_polish_rate": (not_polish,)}


def test_token_cost_matches_production_luna_figure():
    # Production Luna since the switch: 3,902 input (1,728 cached), 266 output tokens.
    cost = token_cost({"input": 3902, "cached": 1728, "output": 266}, LUNA)
    assert cost == pytest.approx((2174 * 0.20 + 1728 * 0.02 + 266 * 1.20) / 1e6)


def test_volume_scenarios():
    daily = [{"n": n} for n in (100, 200, 300, 400, 1000)]
    v = volume_scenarios(daily)
    assert v["average_day"] == 400 and v["busiest_day"] == 1000 and v["busy_day_p90"] == 1000 and v["days"] == 5


def test_per_article_adds_retries_and_summary_repairs():
    row = per_article(report(0.05, invalid=0.1, not_polish=0.5), scale=2.0, prices=CHEAP)
    assert row["classification"] == pytest.approx(0.001)
    assert row["retry_after_invalid"] == pytest.approx(0.0001)
    assert row["summary_repair"] == pytest.approx(0.5 * (350 * 0.10 + 160 * 0.50) / 1e6)


def test_price_table_scales_every_model_by_the_baseline_ratio():
    reports = {"luna": report(0.05), "cheap": report(0.02)}
    snapshot = {"daily": [{"n": 250}] * 10, "baseline_usage": {"input": 3902, "cached": 1728, "output": 266}}
    table = price_table(reports, "luna", snapshot, {"luna": LUNA, "cheap": CHEAP}, monthly_cap=10)
    luna, cheap = table["models"]["luna"], table["models"]["cheap"]
    assert luna["total"] == pytest.approx(token_cost(snapshot["baseline_usage"], LUNA))
    assert cheap["vs_baseline"] == pytest.approx(0.4)
    assert luna["monthly"]["average_day"] == pytest.approx(luna["total"] * 250 * 30.4)
    assert luna["within_cap_busy_month"]
