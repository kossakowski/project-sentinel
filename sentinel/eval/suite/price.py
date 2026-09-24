"""What each candidate would cost as a substitute for the production model.

Method (measured, not list prices):
1. Take each model's own measured token counts per eval request (prompt, cached prompt,
   completion incl. reasoning), so tokenizer differences and caching are included, and
   its billed/list cost ratio on the eval (usually ~1) to catch extra provider charges.
2. Production requests carry remembered incidents, so only the prompt grows: every
   model's prompt is scaled by the baseline's production/eval prompt ratio. Extra prompt
   tokens are priced as uncached (the cached system prompt does not grow); completion
   tokens are kept as measured.
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


def per_article(report: dict, prompt_scale: float, cached_tokens: float, prices: dict) -> dict:
    """Projected production cost of one article for one model.

    ``cached_tokens`` is the production cache hit per request, already converted to this
    model's tokenizer (the eval runs requests back to back, so its own cache hits are
    higher than sparse production traffic would get).
    """
    prompt = report.get("mean_prompt_tokens") or 0.0
    eval_cached = min(report.get("mean_cached_tokens") or 0.0, prompt)
    output = report.get("mean_completion_tokens") or 0.0
    eval_listed = token_cost({"input": prompt, "cached": eval_cached, "output": output}, prices)
    eval_billed = report["cost_usd"] / max(1, report.get("known_cost_calls", report["calls"]))
    if not eval_listed or not eval_billed:
        raise ValueError("no measured tokens or cost for this model; cannot project its price")
    billed_ratio = eval_billed / eval_listed
    production_prompt = prompt * prompt_scale
    production_cached = min(cached_tokens, production_prompt) if eval_cached else 0.0
    classification = (
        token_cost({"input": production_prompt, "cached": production_cached, "output": output}, prices) * billed_ratio
    )
    invalid = (report["invalid_call_rate"] or (0.0,))[0]
    repair = repair_cost(report, prices)
    retry = invalid * classification
    return {
        "eval_cost_per_call": eval_billed,
        "billed_to_list_ratio": billed_ratio,
        "production_prompt_tokens": production_prompt,
        "production_cached_tokens": production_cached,
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
    # Production input tokens also include the baseline's own summary repairs; remove
    # them so the ratio covers the classification prompt only.
    not_polish = (base["summary_not_polish_rate"] or (0.0,))[0]
    production_prompt = (snapshot["baseline_usage"].get("input") or 0.0) - not_polish * REPAIR_INPUT_TOKENS
    eval_prompt = base.get("mean_prompt_tokens") or 0.0
    if not eval_prompt or production_prompt <= 0:
        raise ValueError("baseline has no measured prompt tokens; cannot scale to production")
    scale = production_prompt / eval_prompt
    production_cached = snapshot["baseline_usage"].get("cached") or 0.0
    volumes = volume_scenarios(snapshot["daily"])
    table = {}
    for model, report in reports.items():
        if model not in prices or not report["calls"]:
            continue
        # Same cached share of the prompt as production, in this model's own tokens.
        tokenizer_ratio = (report.get("mean_prompt_tokens") or 0.0) / eval_prompt
        article = per_article(report, scale, production_cached * tokenizer_ratio, prices[model])
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
        "prompt_scale_to_production": scale,
        "baseline_production_cost_per_article": base_prod_cost,
        "volumes": volumes,
        "monthly_cap_usd": monthly_cap,
        "models": table,
    }
