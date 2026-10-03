"""Substitute-cost projection with hand-computed numbers."""

import pytest

from sentinel.eval.suite.price import per_article, price_table, token_cost, volume_scenarios

LUNA = {"input": 0.20, "cached_input": 0.02, "output": 1.20}
CHEAP = {"input": 0.10, "cached_input": 0.01, "output": 0.50}


def report(prompt, cached, output, prices, calls=100, invalid=0.0, not_polish=0.0, billed_ratio=1.0):
    listed = token_cost({"input": prompt, "cached": cached, "output": output}, prices)
    return {
        "cost_usd": listed * billed_ratio * calls,
        "calls": calls,
        "known_cost_calls": calls,
        "mean_prompt_tokens": prompt,
        "mean_cached_tokens": cached,
        "mean_completion_tokens": output,
        "invalid_call_rate": (invalid,),
        "summary_not_polish_rate": (not_polish,),
    }


def test_token_cost_matches_production_luna_figure():
    # Production Luna since the switch: 3,902 input (1,728 cached), 266 output tokens.
    cost = token_cost({"input": 3902, "cached": 1728, "output": 266}, LUNA)
    assert cost == pytest.approx((2174 * 0.20 + 1728 * 0.02 + 266 * 1.20) / 1e6)


def test_volume_scenarios():
    daily = [{"n": n} for n in (100, 200, 300, 400, 1000)]
    v = volume_scenarios(daily)
    assert v["average_day"] == 400 and v["busiest_day"] == 1000 and v["busy_day_p90"] == 1000 and v["days"] == 5


def test_per_article_scales_only_the_prompt_and_adds_retries_and_repairs():
    row = per_article(
        report(2000, 1500, 260, CHEAP, invalid=0.1, not_polish=0.5), prompt_scale=2.0, cached_tokens=1500, prices=CHEAP
    )
    # production prompt 4000 = 1500 cached + 2500 fresh; output unchanged
    assert row["classification"] == pytest.approx((2500 * 0.10 + 1500 * 0.01 + 260 * 0.50) / 1e6)
    assert row["retry_after_invalid"] == pytest.approx(0.1 * row["classification"])
    assert row["summary_repair"] == pytest.approx(0.5 * (350 * 0.10 + 160 * 0.50) / 1e6)
    doubled = per_article(report(2000, 1500, 260, CHEAP, billed_ratio=2.0), 2.0, 1500, CHEAP)
    assert doubled["classification"] == pytest.approx(2 * row["classification"])


def test_price_table_projects_the_baseline_to_its_production_usage():
    snapshot = {"daily": [{"n": 250}] * 10, "baseline_usage": {"input": 3902, "cached": 1728, "output": 266}}
    reports = {"luna": report(1900, 1728, 266, LUNA), "cheap": report(1900, 1728, 266, CHEAP)}
    table = price_table(reports, "luna", snapshot, {"luna": LUNA, "cheap": CHEAP}, monthly_cap=10)
    luna, cheap = table["models"]["luna"], table["models"]["cheap"]
    assert luna["total"] == pytest.approx(token_cost(snapshot["baseline_usage"], LUNA))
    assert cheap["vs_baseline"] == pytest.approx(token_cost(snapshot["baseline_usage"], CHEAP) / luna["total"])
    assert luna["monthly"]["average_day"] == pytest.approx(luna["total"] * 250 * 30.4)
    assert luna["within_cap_busy_month"]


def test_price_uses_production_cache_share_and_refuses_missing_data():
    no_cache = per_article(report(2000, 0, 260, CHEAP), 2.0, 1500, CHEAP)  # model without caching
    assert no_cache["production_cached_tokens"] == 0
    cached = per_article(report(2000, 1900, 260, CHEAP), 2.0, 800, CHEAP)  # eval over-caches
    assert cached["production_cached_tokens"] == 800
    with pytest.raises(ValueError):
        per_article(report(2000, 0, 260, CHEAP, billed_ratio=0.0), 2.0, 0, CHEAP)
