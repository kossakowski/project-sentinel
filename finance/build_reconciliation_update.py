"""Refresh today's usage without overwriting earlier dated audit snapshots."""

import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "reports/2026-10-11"
OUT = ROOT / "reports/2026-10-11-reconciliation-update"
D = Decimal
Q = D("0.0000000001")


def read_json(path):
    return json.loads(path.read_text(), parse_float=D)


def read_csv(path):
    with path.open() as file:
        return list(csv.DictReader(file))


def write_csv(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    fresh = read_json(OUT / "evidence/production-today.json")
    old = read_json(BASE / "evidence/production.json")["evidence"]
    summary = read_json(BASE / "summary.json")
    recorded = fresh["recorded_at"]
    now = datetime.fromisoformat(recorded)
    prior_today = sum(
        (
            D(str(r["configured_cost_usd"]))
            for r in old["usage_daily"]
            if r["day"] == "2026-10-11" and r["status"] == "settled"
        ),
        D(0),
    )
    current_today = sum((D(r["configured_cost_usd"]) for r in fresh["usage_daily"] if r["status"] == "settled"), D(0))
    api_delta = current_today - prior_today
    assert api_delta >= 0
    old_host = next(
        r for r in read_csv(BASE / "cost-items.csv") if r["provider"] == "Hetzner" and r["usage_start"] == "2026-10-01"
    )
    elapsed_seconds = D(str((now - datetime.fromisoformat("2026-10-01T00:00:00+00:00")).total_seconds()))
    new_host = min(elapsed_seconds / D(3600) * D(".0072"), D("4.49")).quantize(Q)
    host_delta = new_host - D(old_host["amount"])
    assert host_delta >= 0
    deltas = {"EUR": host_delta, "USD": api_delta}
    deltas["PLN"] = sum(deltas[c] * D(summary["planning_fx"][c]["pln_per_unit"]) for c in ["EUR", "USD"])
    rows = read_csv(BASE / "history-monthly.csv")
    for row in rows:
        row["recorded_at"] = recorded
        if row["month"] == "2026-10":
            delta = deltas[row["currency"]]
            for field in ["estimated_additions", "reconstructed_total", "reconstructed_low", "reconstructed_high"]:
                row[field] = str((D(row[field]) + delta).quantize(Q))
            row["effective_end"] = recorded
        row["cash_status"] = "Payment dates/settlements unknown; monthly cash allocation unavailable"
        row["note"] += (
            " Later update replaces today's cumulative API subset and extends hourly hosting; no top-ups added."
        )
    totals = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        assert D(row["verified_cost"]) + D(row["estimated_additions"]) == D(row["reconstructed_total"])
        for field in ["verified_cost", "estimated_additions", "reconstructed_total"]:
            totals[row["currency"]][field] += D(row[field])
    for currency in ["EUR", "USD", "PLN"]:
        assert abs(
            totals[currency]["reconstructed_total"]
            - D(summary["historical"][currency]["reconstructed_total"])
            - deltas[currency]
        ) < D(".000000001")
    ledger = read_csv(ROOT / "ledger.csv")
    cash = sum(
        (D(r["confirmed_cash_amount"]) for r in ledger if r["currency"] == "EUR" and r["confirmed_cash_amount"]), D(0)
    )
    assert cash == D("13.47")
    detail = [
        dict(
            provider="OpenAI",
            currency="USD",
            effective_start=summary["as_of_utc"],
            effective_end=recorded,
            recorded_at=recorded,
            evidence_category="Estimated",
            amount=str(api_delta),
            source="evidence/production-today.json; ../2026-10-11/evidence/production.json",
            calculation=f"Today's cumulative settled configured cost {current_today} less already counted {prior_today}",
            assumptions="Same conservative configured token tariff; provider credits/tax/billed failures unknown.",
            confidence="High for local delta; medium for billable amount",
        ),
        dict(
            provider="Hetzner",
            currency="EUR",
            effective_start=summary["as_of_utc"],
            effective_end=recorded,
            recorded_at=recorded,
            evidence_category="Estimated",
            amount=str(host_delta),
            source="Prior cost-items.csv and observed continued production availability",
            calculation=f"Elapsed seconds since October 1 {elapsed_seconds} / 3600 * .0072, capped4.49, less prior {old_host['amount']}",
            assumptions="Same instance and hourly price; no provider extras or account credits confirmed.",
            confidence="Medium",
        ),
    ]
    write_csv(OUT / "estimated-additions.csv", detail)
    write_csv(OUT / "history-monthly.csv", rows)
    write_csv(ROOT / "history-monthly.csv", rows)
    model_rows = read_csv(BASE / "llm-by-model-phase.csv")
    cost_items = read_csv(BASE / "cost-items.csv")
    for row in model_rows:
        items = [r for r in cost_items if all(r[k] == row[k] for k in ["provider", "model", "phase"])]
        row["effective_start"] = min(r["usage_start"] for r in items)
        row["effective_end"] = max(r["usage_end"] for r in items)
        row["recorded_at"] = recorded
        if row["provider"] == "OpenAI" and row["phase"] == "production" and row["model"] == "gpt-5.6-luna":
            for field in ["estimated", "total", "low", "high"]:
                row[field] = str(D(row[field]) + api_delta)
            row["effective_end"] = recorded
        assert D(row["verified"]) + D(row["estimated"]) == D(row["total"])
    write_csv(OUT / "llm-by-model-phase.csv", model_rows)
    current_rows = read_csv(BASE / "current-monthly.csv")
    unresolved_services = {"CI/builds", "Domains and operational email", "Ongoing testing"}
    for row in current_rows:
        row["recorded_at"] = recorded
        row["included_in_total"] = "true"
        if row["service"] in unresolved_services:
            for field in ["normalized_monthly", "low", "high", "pln_equivalent", "low_pln", "high_pln"]:
                row[field] = ""
            row["evidence_category"] = "Unknown"
            row["included_in_total"] = "false; amount unknown"
            row["formula"] = "No defensible billed amount; not assumed zero"
        elif D(row["normalized_monthly"]) == 0:
            row["assumptions"] = row["assumptions"].split(" Absence of a billing record")[0]
            row["assumptions"] += " Zero is scoped to this observed component; unknown paid add-ons are separate."
    for service, provider in [
        ("Cloud storage/backups or hosting add-ons", "Hetzner"),
        ("Managed email/monitoring or paid source add-ons", "Unconfirmed"),
    ]:
        row = {k: "" for k in current_rows[0]}
        row.update(
            service=service,
            provider=provider,
            currency="UNKNOWN",
            evidence_category="Unknown",
            effective_date=recorded,
            recorded_at=recorded,
            measurement_start="2026-10-11",
            measurement_end=recorded,
            included_in_total="false; amount unknown",
            formula="No defensible billed amount; not assumed zero",
            assumptions="No attributable paid add-on established; provider account inventory and allocation still required.",
        )
        current_rows.append(row)
    assert sum((D(r["pln_equivalent"]) for r in current_rows if r["pln_equivalent"]), D(0)) == D(summary["current_pln"])
    write_csv(OUT / "current-monthly.csv", current_rows)
    write_csv(ROOT / "current-monthly.csv", current_rows)
    windows = []
    for start, length in [("2026-10-04", 7), ("2026-10-01", 10), ("2026-09-21", 20)]:
        selected = [r for r in old["usage_daily"] if r["status"] == "settled" and start <= r["day"] <= "2026-10-10"]
        cost = sum((D(str(r["configured_cost_usd"])).quantize(Q) for r in selected), D(0))
        windows.append(
            dict(
                effective_start=start,
                effective_end="2026-10-10T23:59:59Z",
                recorded_at=recorded,
                complete_days=length,
                currency="USD",
                configured_cost=str(cost),
                production_monthly_30day=str((cost * D(30) / D(length)).quantize(Q)),
                formula="Sum settled configured-cost daily aggregates *30/complete days",
                evidence_category="Estimated",
                source="../2026-10-11/evidence/production.json",
                assumptions="Luna production only; no September20 migration test seeds in these periods; cache-write premium remains a conservative scenario; provider account adjustments unknown.",
                confidence="Medium; workload sensitivity, not a billing interval",
            )
        )
    (OUT / "measurement-windows.json").write_text(json.dumps(windows, indent=2) + "\n")
    result = {
        "recorded_at": recorded,
        "effective_end": recorded,
        "historical": {c: {k: str(v) for k, v in values.items()} for c, values in totals.items()},
        "changes_since_prior_snapshot": {c: str(v) for c, v in deltas.items()},
        "current_monthly": summary["current_native"],
        "current_monthly_pln_equivalent": summary["current_pln"],
        "recommended_budget_pln": summary["recommended_budget_pln"],
        "supersedes": ["2026-10-11/report.html", "2026-10-11-hetzner-email-check/report.html"],
        "range_is_complete": False,
        "unpriced_current_categories": [r["service"] for r in current_rows if r["evidence_category"] == "Unknown"],
        "api_measurement_windows": windows,
        "owner_confirmed_invoiced_cash_eur": str(cash),
        "provider_or_bank_verified_cash_total": None,
        "unresolved": [
            "Actual API consumption after provider credits, discounts, free allowances, taxes, refunds and billed failures.",
            "Historical provider organizations/workspaces and rotated/deleted key coverage.",
            "Apple payment amount/currency/date; current $99 annual proxy remains Estimated.",
            "Twilio retained number, trial credit and historical rental/communications bill.",
            "Hetzner exact creation/prior plans, storage/backups/extras and co-hosting allocation.",
            "Netcup project allocation and paid EAS or CI overages, if any.",
            "Project-specific coding paid extras/API routing; conditional valuation remains outside spending.",
        ],
        "validation": {
            "monthly_and_aggregate_sums": True,
            "old_today_usage_subtracted": True,
            "cash_not_added_to_consumption": True,
            "current_api_window_unchanged": "October 1–10 complete UTC days",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    history = []
    cumulative = D(0)
    for month in sorted({r["month"] for r in rows}):
        r = next(r for r in rows if r["month"] == month and r["currency"] == "PLN")
        cumulative += D(r["reconstructed_total"])
        history.append((r, cumulative))
    table = "".join(
        f"<tr><td>{r['month']}</td><td>{D(r['verified_cost']):.2f}</td><td>{D(r['estimated_additions']):.2f}</td><td>{D(r['reconstructed_total']):.2f}</td><td>{c:.2f}</td></tr>"
        for r, c in history
    )
    native = "".join(
        f"<tr><td>{c}</td><td>{v['verified_cost']:.4f}</td><td>{v['estimated_additions']:.4f}</td><td>{v['reconstructed_total']:.4f}</td></tr>"
        for c, v in totals.items()
        if c != "PLN"
    )
    gaps = "".join(f"<li>{escape(g)}</li>" for g in result["unresolved"])
    h = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel costs — reconciliation in progress</title><style>body{{font:16px/1.5 system-ui;max-width:1000px;margin:auto;padding:24px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}.notice{{background:#fff3cf;padding:16px}}a{{overflow-wrap:anywhere}}</style>
<h1>Sentinel costs: reconciliation in progress</h1><p>Usage checked through {escape(recorded)}. Recorded at the same time. Earlier dated reports are preserved.</p>
<p class="notice"><strong>These are provisional reconstructed costs, not a complete verified payment total.</strong> Open billing and allocation gaps can change both current and aggregate costs.</p>
<h2>Current monthly cost</h2><p>The present 30-day planning estimate is <strong>PLN {D(summary["current_pln"]):.2f}</strong> = EUR4.49 hosting plus USD29.3250 for API consumption, assumed phone rental and Apple annual membership averaged over 12 months. Reserve <strong>PLN200/month</strong> pending billing reconciliation. Sensitivity is PLN88.32–161.81 for quantified components only; unknown credits/taxes/additional services sit outside that range.</p>
<p>The API part is USD17.0750/month, extrapolated from ten complete UTC days, October 1–10. A seven-day window projects USD18.4288 and a twenty-day window USD16.8986; these support a similar current order of cost, while the later days show rising usage. Historical one-off tests are excluded from recurring production. Today's partial usage updates history only. Apple actual payment and Twilio retention remain unresolved. FX planning rates are dated October 9; these are equivalents, not bank debits.</p>
<h2>Aggregate cost since March 21</h2><div class="scroll"><table><tr><th>Native currency</th><th>Verified cost</th><th>Estimated additions</th><th>Reconstructed total</th></tr>{native}</table></div>
<p>The dated PLN equivalent is <strong>{totals["PLN"]["reconstructed_total"]:.2f}</strong>, comprising verified costs {totals["PLN"]["verified_cost"]:.2f} plus estimated additions {totals["PLN"]["estimated_additions"]:.2f}. Verified means attributable invoice or provider-returned request cost; it does not mean verified bank settlement.</p>
<p>Two Hetzner invoices total EUR13.47 and you confirmed they are paid. Payment dates and bank settlement amounts are unknown. That cash confirmation is attached to the existing ledger entries, with no additional expense. API funding payments and remaining balances are still unknown.</p>
<h2>How cost changed month by month</h2><p>All figures below are dated PLN equivalents. March begins on March21; October ends at the check time above. Monthly reconstruction includes experiments and the whole estimated Apple annual purchase once, so it differs from normalized ongoing cost.</p><div class="scroll"><table><tr><th>Month</th><th>Verified</th><th>Estimated</th><th>Reconstructed</th><th>Cumulative</th></tr>{table}</table></div>
<ul><li>March: development started March21 and production hosting is estimated from the March23 deployment. Haiku and communications tests are included.</li><li>May: heavy Twilio message/call activity drives the reconstructed communications cost; invoices and trial-credit effects are still missing.</li><li>June: the Apple membership was active June1. Its full USD99 tariff proxy is assigned once to this purchase period; you confirmed it was project-specific.</li><li>September: production switched from direct Anthropic Haiku4.5 to direct OpenAI gpt-5.6-luna on September20 at21:29:49UTC. OpenRouter, Jev and abandoned model tests are included in historical costs.</li><li>October: the recurring estimate uses the deployed Luna workload. Twilio calls/SMS fail while the account is unfunded; assumed number rental remains pending confirmation.</li></ul>
<p>Unknown ongoing CI/EAS charges, domains/email, testing and paid provider add-ons have blank amounts in the current CSV. They are not assumed zero. Free components and included local disk/cron are scoped separately.</p><h2>Remaining evidence needed</h2><ul>{gaps}</ul>
<h2>Detailed files</h2><ul><li><a href="history-monthly.csv">Updated monthly historical CSV</a></li><li><a href="estimated-additions.csv">New estimated deltas with dates, calculation and assumptions</a></li><li><a href="summary.json">Totals, gaps and validation</a></li><li><a href="measurement-windows.json">Seven-, ten- and twenty-day API measurement comparison</a></li><li><a href="llm-by-model-phase.csv">Updated LLM provider/model/phase costs</a></li><li><a href="../../current-monthly.csv">Current normalized monthly CSV, with unresolved costs marked Unknown</a></li><li><a href="../../ledger.csv">Actual evidence ledger and owner payment confirmation</a></li><li><a href="../2026-10-11/report.html">Original detailed report, model phases and reconstruction methods</a></li><li><a href="../2026-10-11-coding-usage/report.html">Coding usage: billing Unknown and separate conditional scenario</a></li><li><a href="../2026-10-11-hetzner-email-check/report.html">Invoice/payment email recheck</a></li><li><a href="evidence/production-today.json">Sanitized latest production aggregate</a></li><li><a href="evidence/download-search.json">Downloaded invoice search coverage</a></li><li><a href="evidence/local-key-history.json">Sanitized local credential-route history</a></li><li><a href="evidence/key-route-comparison.json">Anonymous local/server billing-route matches</a></li><li><a href="evidence/completion-review.json">Independent requirement and correction review</a></li></ul>
<p>Checked: monthly and cumulative sums, native currency separation, October usage replacement, hourly hosting period, cash-versus-consumption separation, and unchanged completed-day measurement window.</p></html>"""
    (OUT / "report.html").write_text(h)
    print(
        json.dumps(
            {
                "recorded_at": recorded,
                "estimated_deltas": result["changes_since_prior_snapshot"],
                "reconstructed_pln": str(totals["PLN"]["reconstructed_total"]),
            }
        )
    )


if __name__ == "__main__":
    main()
