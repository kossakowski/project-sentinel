"""Value observed coding tokens conditionally; never book them as spending."""

import csv
import json
from collections import defaultdict
from decimal import Decimal
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports/2026-10-11-coding-usage"
RECORDED = "2026-10-11"
FIELDS = {
    "input_tokens": "input",
    "cache_creation_ephemeral_5m_input_tokens": "cache_write_5m",
    "cache_creation_ephemeral_1h_input_tokens": "cache_write_1h",
    "cache_read_input_tokens": "cache_read",
    "output_tokens": "output",
}


def read(path):
    return json.loads(path.read_text(), parse_float=Decimal)


def main():
    usage = read(OUT / "evidence/usage.json")
    pricing = read(OUT / "evidence/pricing.json")
    models = {m["model_id"]: m for m in pricing["models"]}
    rows = []
    totals = defaultdict(Decimal)
    for u in usage["by_model_month"]:
        if u["model"] == "<synthetic>":
            assert all(u[f] == 0 for f in FIELDS)
            continue
        m = models[u["model"]]
        rates = m["standard_global_price"]
        start, end = u["first_timestamp"][:10], u["last_timestamp"][:10]
        assert start >= m["release_date"] and start >= rates["effective_from"]
        assert not rates["effective_to"] or end <= rates["effective_to"]
        assert u["cache_creation_unspecified_input_tokens"] == 0
        assert u["cache_creation_input_tokens"] == (
            u["cache_creation_ephemeral_5m_input_tokens"] + u["cache_creation_ephemeral_1h_input_tokens"]
        )
        value = sum(Decimal(u[f]) * Decimal(str(rates[r])) for f, r in FIELDS.items())
        value /= 1_000_000
        totals[u["model"]] += value
        rows.append(
            {
                "month": u["month"],
                "model": u["model"],
                "phase": "development/coding",
                "effective_start": start,
                "effective_end": end,
                "recorded_at": RECORDED,
                "currency": "USD",
                "evidence_category": "Estimated conditional scenario",
                "conditional_token_valuation": str(value),
                "attributable_actual_spending": "",
                "actual_spending_status": "Unknown; not booked",
                **{f: u[f] for f in FIELDS},
                **{f"rate_{r}_usd_per_million": str(rates[r]) for r in FIELDS.values()},
                "assumption": "All observed tokens separately billed at first-party Standard global API rates; no discounts, credits, tax or regional premium. Missing speed assumes Standard.",
                "calculation": "sum(observed token category * matching rate) / 1000000; thinking included in output",
                "source": "evidence/usage.json; evidence/pricing.json",
                "confidence": "Token valuation medium; actual paid amount unknown",
                "included_in_finance_baseline": "false",
            }
        )
    total = sum(totals.values(), Decimal(0))
    assert total == Decimal("1792.96201335")
    for f in FIELDS:
        assert sum(r[f] for r in rows) == usage["usage_total"][f]
    with (OUT / "conditional-by-model-month.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "recorded_at": RECORDED,
        "effective_period": usage["effective_period"],
        "conditional_standard_global_token_valuation_usd": str(total),
        "attributable_paid_cost": None,
        "paid_cost_status": "Unknown; not booked",
        "finance_baseline_change": "None",
        "by_model": {k: str(v) for k, v in sorted(totals.items())},
        "scenarios": [
            "If usage was entirely included in excluded shared subscriptions, incremental project spending is zero.",
            "If all observed usage was separately paid via the Standard global API, token consumption would be USD 1792.96201335 before taxes, credits, discounts or tool charges.",
            "Mixed subscription and paid usage requires request-level allocation; neither endpoint is established as the actual bill.",
        ],
        "gaps": [
            "No matching coding transcripts before May 28; no invented tokens for March 21–May 27.",
            "No historical session billing-route metadata or authoritative provider balance ledger.",
            "Partial virtual cost-state records report 40 web searches while per-message counters report zero. Separate tool costs remain unresolved; virtual states are not added.",
            "Failed or unrecorded requests and background provider usage may be absent.",
            "Current Claude Max and Codex ChatGPT authentication do not prove historical routes or absence of paid extra usage.",
            "Shared extra-usage purchase exists but Sentinel allocation is unknown.",
        ],
        "currency_conversion": "No PLN equivalent: this hypothetical tariff valuation is not a payment or established historical cost.",
        "validation": {
            "priced_model_month_rows": len(rows),
            "unique_assistant_records": usage["deduplication"]["unique_assistant_messages"],
            "duplicates_removed": usage["deduplication"]["stream_duplicate_records_removed"],
            "token_totals_reconciled": True,
            "release_and_rate_date_checks": True,
            "thinking_not_counted_twice": True,
            "virtual_costs_not_added": True,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = "".join(f"<tr><td>{escape(k)}</td><td>${v:,.4f}</td></tr>" for k, v in sorted(totals.items()))
    gaps = "".join(f"<li>{escape(g)}</li>" for g in summary["gaps"])
    sources = sorted({s for m in pricing["models"] for s in m["sources"]})
    links = "".join(f'<li><a href="{escape(s)}">{escape(s)}</a></li>' for s in sources)
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel coding usage — billing unresolved</title>
<style>body{{font:16px/1.5 system-ui;max-width:960px;margin:auto;padding:24px;color:#17252f}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #ccd;text-align:left}}a{{overflow-wrap:anywhere}}.notice{{padding:16px;background:#fff3cf}}code{{overflow-wrap:anywhere}}</style>
<h1>Sentinel coding usage: billing unresolved</h1>
<p>Recorded October 11, 2026. Observed usage: May 28–October 10, 2026.</p>
<p class="notice"><strong>Actual attributable paid cost: Unknown.</strong> This appendix adds no spending to the ledger, historical reconstruction or monthly operating total. Shared Claude Code and Codex subscriptions remain excluded.</p>
<p>The project-specific local logs contain 11,002 distinct assistant responses, including subagents, across 53 sessions. Deduplication removed 17,279 streaming copies. Message text, credentials and account identifiers are excluded from the evidence.</p>
<h2>Explicit scenario, not a bill</h2>
<p>If every observed token had been separately billed at the applicable first-party Standard global API rate, its token-only valuation would be <strong>${total:,.2f}</strong>. If the work was wholly included in the excluded subscriptions, its incremental cost would be zero. Neither billing scenario is established. The full API scenario is not an upper bound for missing usage, tools or taxes.</p>
<p>Input, output, five-minute cache creation, one-hour cache creation and cached reads have separate rates. Thinking tokens are already in output. No batch or fast mode was observed. Missing speed metadata assumes Standard. Current authentication shows Claude Max and Codex ChatGPT; this is current evidence only.</p>
<table><thead><tr><th>Exact model ID</th><th>Conditional token valuation (USD)</th></tr></thead><tbody>{table}</tbody><tfoot><tr><th>Total</th><th>${total:,.4f}</th></tr></tfoot></table>
<p>Four partial session virtual cost states total $263.64213515. They overlap the tokens above and are neither an invoice nor another expense. They are not added. No currency equivalent or bank debit is claimed.</p>
<h2>Coverage and attribution gaps</h2><ul>{gaps}</ul>
<h2>Files and sources</h2><ul>
<li><a href="conditional-by-model-month.csv">Conditional model-by-month CSV</a></li>
<li><a href="summary.json">Scenario, gaps and validation JSON</a></li>
<li><a href="evidence/usage.json">Sanitized usage evidence</a></li>
<li><a href="evidence/pricing.json">Exact model pricing timeline</a></li>
<li><a href="../2026-10-11/report.html">Operating cost and historical reconstruction</a></li>
<li><a href="../2026-10-11-hetzner-email-check/report.html">Later Hetzner payment confirmation</a></li></ul>
<p>Pricing references were retrieved from the official provider by the audit's pricing researcher. Their effective dates are recorded alongside each model.</p><ul>{links}</ul>
<p>Validation: token categories and model totals reconcile; model releases and tariff start dates precede usage; streaming copies, thinking tokens and virtual costs are not counted twice.</p></html>"""
    (OUT / "report.html").write_text(html)
    print(f"Saved {len(rows)} conditional model-month rows; USD {total}; actual spending Unknown.")


if __name__ == "__main__":
    main()
