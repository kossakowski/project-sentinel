"""What each candidate would cost as a substitute for the production model.

Method (measured, not list prices):
1. Start from each model's average *charged* cost per eval request (OpenRouter's billed
   amount, so tokenizer differences, cache discounts and reasoning are already included).
2. Production requests are longer (remembered incidents are attached). The baseline's
   production/eval cost ratio, measured on the same items, scales every model to
   production-sized requests.
3. Add the expected cost of re-asking after an invalid answer and of the Polish-summary
   repair call for summaries not written in Polish.
4. Multiply by real production volume: average day, busy day (90th percentile) and the
   busiest day since 2026-08-24; compare with the monthly model budget.
"""

import json
import shlex
import statistics
import subprocess
from pathlib import Path

from sentinel.eval.suite.sample import PROD_DB, SSH

DAYS_PER_MONTH = 30.4
REPAIR_INPUT_TOKENS = 350
REPAIR_OUTPUT_TOKENS = 160
VOLUME_SQL = (
    "SELECT substr(classified_at,1,10) AS day, count(*) AS n FROM classifications "
    "WHERE classified_at >= '2026-08-24' GROUP BY day ORDER BY day"
)
BASELINE_SQL = (
    "SELECT count(*) AS n, avg(input_tokens) AS input, avg(cached_input_tokens) AS cached, "
    "avg(output_tokens) AS output FROM classifications "
    "WHERE model_used = 'gpt-5.6-luna' AND classified_at >= '2026-09-20T21:30'"
)


def snapshot_production(path: Path) -> dict:
    """Read-only production volume and baseline token usage; cached to ``path``."""

    def query(sql):
        command = f"sqlite3 -readonly -json {PROD_DB} " + shlex.quote(sql)
        return json.loads(subprocess.run([*SSH, command], check=True, capture_output=True, text=True).stdout)

    days = [row for row in query(VOLUME_SQL) if row["n"] >= 20]  # drop outage/partial days
    snapshot = {"daily": days, "baseline_usage": query(BASELINE_SQL)[0]}
    path.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    return snapshot


def volume_scenarios(daily: list[dict]) -> dict:
    counts = sorted(row["n"] for row in daily)
    if not counts:
        raise ValueError("no production volume")
    return {
        "average_day": statistics.mean(counts),
        "busy_day_p90": counts[min(len(counts) - 1, int(round(0.9 * (len(counts) - 1))))],
        "busiest_day": counts[-1],
        "days": len(counts),
    }


def token_cost(usage: dict, prices: dict) -> float:
    """List-price cost of a usage mix; prices in USD per million tokens."""
    cached = usage.get("cached") or 0
    fresh = max(0.0, (usage.get("input") or 0) - cached)
    return (
        fresh * prices["input"]
        + cached * prices.get("cached_input", prices["input"])
        + (usage.get("output") or 0) * prices["output"]
    ) / 1e6


def repair_cost(report: dict, prices: dict) -> float:
    """Expected cost of the Polish-summary repair call per article."""
    not_polish = (report["summary_not_polish_rate"] or (0.0,))[0]
    return not_polish * (REPAIR_INPUT_TOKENS * prices["input"] + REPAIR_OUTPUT_TOKENS * prices["output"]) / 1e6


def per_article(report: dict, scale: float, prices: dict) -> dict:
    """Projected production cost of one article for one model."""
    calls = max(1, report.get("known_cost_calls", report["calls"]))
    eval_cost = report["cost_usd"] / calls
    classification = eval_cost * scale
    invalid = (report["invalid_call_rate"] or (0.0,))[0]
    repair = repair_cost(report, prices)
    retry = invalid * classification
    return {
        "eval_cost_per_call": eval_cost,
        "classification": classification,
        "retry_after_invalid": retry,
        "summary_repair": repair,
        "total": classification + retry + repair,
    }


def price_table(reports: dict, baseline: str, snapshot: dict, prices: dict, monthly_cap: float) -> dict:
    """Substitute-cost table for every scored model.

    ``prices`` maps model id -> {"input", "cached_input", "output"} in USD per million.
    """
    base = reports[baseline]
    base_prod_cost = token_cost(snapshot["baseline_usage"], prices[baseline])
    # Production token counts already include the baseline's own summary repairs; take
    # them out so the scale covers the classification request only (repairs are added
    # back per model from its own measured non-Polish rate).
    base_prod_classification = max(0.0, base_prod_cost - repair_cost(base, prices[baseline]))
    base_eval_cost = base["cost_usd"] / max(1, base.get("known_cost_calls", base["calls"]))
    scale = base_prod_classification / base_eval_cost if base_eval_cost else 1.0
    volumes = volume_scenarios(snapshot["daily"])
    table = {}
    for model, report in reports.items():
        if model not in prices or not report["calls"]:
            continue
        article = per_article(report, scale, prices[model])
        monthly = {
            name: article["total"] * volumes[name] * DAYS_PER_MONTH
            for name in ("average_day", "busy_day_p90", "busiest_day")
        }
        table[model] = {
            **article,
            "per_1000_articles": article["total"] * 1000,
            "monthly": monthly,
            "within_cap_busy_month": monthly["busy_day_p90"] <= monthly_cap,
        }
    base_total = table[baseline]["total"] if baseline in table else None
    for row in table.values():
        row["vs_baseline"] = row["total"] / base_total if base_total else None
    return {
        "method": __doc__,
        "scale_to_production": scale,
        "baseline_production_cost_per_article": base_prod_cost,
        "volumes": volumes,
        "monthly_cap_usd": monthly_cap,
        "models": table,
    }
