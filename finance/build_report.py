#!/usr/bin/env python3
"""Build and independently validate the dated Sentinel finance snapshot.

No network calls, secrets, inference, or production writes. Currency equivalents
are explanatory valuations, never bank debits. Run with --check after building.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import html
import json
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "reports" / "2026-10-11"


def D(value):
    return Decimal(str(value))


ZERO = D(0)
AS_OF = "2026-10-11T00:38:49+00:00"
RECORDED = "2026-10-11"
MONTHS = [f"2026-{m:02}" for m in range(3, 11)]


def source(name):
    return json.loads((AUDIT / "evidence" / f"{name}.json").read_text())["evidence"]


def number(value):
    if value is None:
        return ""
    return format(D(value).quantize(D("0.0000000001"), rounding=ROUND_HALF_UP), "f")


def money(value, currency="USD"):
    return f"{currency} {D(value):,.2f}"


def csv_write(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: number(v) if isinstance(v, Decimal) else v for k, v in row.items()})


def month_end(month):
    year, m = map(int, month.split("-"))
    return date(year, m, calendar.monthrange(year, m)[1]).isoformat()


FX = {series["code"]: series["rates"] for series in source("fx")["series"]}


def fx(currency, valuation_date):
    candidates = [r for r in FX[currency] if r["effectiveDate"] <= valuation_date[:10]]
    if not candidates:
        raise ValueError(f"No dated FX for {currency}, {valuation_date}")
    r = candidates[-1]
    return D(r["mid"]), r["effectiveDate"], r["no"]


entries = []


def add(
    provider,
    model,
    phase,
    category,
    amount,
    start,
    end,
    formula,
    evidence,
    assumptions,
    confidence="medium",
    low=None,
    high=None,
    currency="USD",
    valuation=None,
    kind="estimated_consumption",
    unknown=None,
):
    amount = D(amount)
    low = amount if low is None else D(low)
    high = amount if high is None else D(high)
    assert ZERO <= low <= amount <= high
    valuation = valuation or min(end[:10], AS_OF[:10])
    rate, rate_date, table = fx(currency, valuation)
    row = dict(
        item_id=f"cost-{len(entries) + 1:03}",
        provider=provider,
        model=model,
        phase=phase,
        evidence_category=category,
        transaction_kind=kind,
        usage_start=start,
        usage_end=end,
        recorded_at=RECORDED,
        currency=currency,
        amount=amount,
        low=low,
        high=high,
        allocation_fraction=D(1),
        formula=formula,
        source=evidence,
        assumptions=assumptions,
        confidence=confidence,
        fx_valuation_date=valuation,
        fx_rate_date=rate_date,
        fx_table=table,
        fx_pln_per_unit=rate,
        pln_equivalent=amount * rate,
        low_pln=low * rate,
        high_pln=high * rate,
        confirmed_cash_amount=None,
        unknown_adjustments=unknown
        or "Provider funding, tax, discounts and credits not confirmed; cash payment unknown.",
    )
    entries.append(row)
    return row


def build():
    billing = source("billing")
    for invoice in billing["invoices"]:
        for month in invoice["service_months"]:
            add(
                "Hetzner",
                "CX23 + IPv4",
                "infrastructure",
                "Verified",
                "4.49",
                month + "-01",
                month_end(month),
                "3.99 server + 0.50 IPv4; invoice tax 0",
                invoice["reference"],
                "Invoice explicitly names Sentinel; no account-wide allocation.",
                confidence="high",
                currency="EUR",
                valuation=invoice["invoice_date"],
                kind="invoice_accrual",
                unknown="Invoice verified; debit announcement does not prove payment.",
            )
    # First deployment establishes the estimated start, not the server's exact purchase time.
    add(
        "Hetzner",
        "CX23 + IPv4",
        "infrastructure",
        "Estimated",
        D(216) * D("0.0072"),
        "2026-03-23",
        "2026-03-31",
        "9 days × 24 h × (0.0064 + 0.0008 EUR/h)",
        "repository first production deployment; official Hetzner old-rate table; July–September invoices",
        "Assume dedicated server started March 23. Pre-April tariff is unavailable despite an April price change; use post-April hourly tariff as a conservative proxy, not a verified March price. Lower scenario halves the server hourly component; upper starts March 22. No allocation to other projects found.",
        confidence="low",
        low=D(216) * (D("0.0032") + D("0.0008")),
        high=D(240) * D("0.0072"),
        currency="EUR",
    )
    for month in ["2026-04", "2026-05", "2026-06"]:
        add(
            "Hetzner",
            "CX23 + IPv4",
            "infrastructure",
            "Estimated",
            "4.49",
            month + "-01",
            month_end(month),
            "Full-month cap: 3.99 + 0.50",
            "July–September Sentinel invoices; deploy history; official tariff",
            "Use the later invoice rate throughout the active period; no evidenced rescale or separate hosting. Assume same zero-tax billing profile. June price increase affected new/rescaled instances, not this retained instance.",
            currency="EUR",
            confidence="medium",
        )
    hours = D(240) + D(38) / D(60) + D(49) / D(3600)
    add(
        "Hetzner",
        "CX23 + IPv4",
        "infrastructure",
        "Estimated",
        hours * D("0.0072"),
        "2026-10-01",
        AS_OF,
        "240 h 38 m 49 s × 0.0072 EUR/h; below monthly cap",
        "latest Sentinel invoice and live service/cron read",
        "Same legacy instance and billing profile after September; no provider-side inventory access. Local backups use included server disk, not paid cloud Backup slots.",
        currency="EUR",
        confidence="medium",
    )

    runtime = source("runtime")["daily"]
    haiku = [r for r in runtime if r["model"].startswith("claude")]
    by_month = defaultdict(list)
    for r in haiku:
        by_month[r["day"][:7]].append(r)

    def haiku_cost(rows):
        return sum((D(r["input_tokens"]) + D(r["output_tokens"]) * D(5)) / D(1_000_000) for r in rows)

    for month, rows in by_month.items():
        add(
            "Anthropic",
            "claude-haiku-4-5-20251001",
            "unclassified_project_usage" if month == "2026-03" else "production",
            "Estimated",
            haiku_cost(rows),
            min(r["day"] for r in rows),
            max(r["day"] for r in rows),
            f"{sum(r['input_tokens'] for r in rows)} input × $1/M + {sum(r['output_tokens'] for r in rows)} output × $5/M",
            "runtime.json: unique classification IDs across server backups and local snapshots; official Haiku tariff",
            "Provider-returned token counts, priced at Haiku 4.5 tariff. Historical code used $0.80/$4, understating by 20% of correct price; it is not billing evidence. No explicit cache controls or batch/tools. March local records cannot all be separated into production/tests.",
            confidence="high",
        )
    # Reconstruct each Haiku workload gap independently, using the closest retained phase.
    sample_cost = (D(699) + D(146) * D(5)) / D(1_000_000)
    early_total = (D(50) + D(51) / D(14) * D(24) * D(9)) * sample_cost
    early_known = haiku_cost(by_month["2026-03"])
    add(
        "Anthropic",
        "claude-haiku-4-5-20251001",
        "unclassified_project_usage",
        "Estimated",
        early_total - early_known,
        "2026-03-21",
        "2026-03-31",
        "(50 assumed initial test requests + 51/14 h × 24 h × 9 production days) × (699×1 +146×5)/1M − already recovered March cost",
        "March 24 tiered-model plan: 51 actual classifications in first ~14 h; first classifier/deploy commits; 42 local rows",
        "Explicit early-phase scenario: 50 initial test calls and continuation of initial observed production rate; recovered calls are subtracted to avoid counting them twice. March 23 counted as a full day because activation time is uncertain. Scenario range halves/doubles total expected load before subtracting recovered cost.",
        confidence="low",
        low=max(ZERO, early_total / D(2) - early_known),
        high=early_total * D(2) - early_known,
    )
    apr_daily = haiku_cost(by_month["2026-04"]) / D(4)
    add(
        "Anthropic",
        "claude-haiku-4-5-20251001",
        "production",
        "Estimated",
        apr_daily * D(26),
        "2026-04-01",
        "2026-04-26",
        "Mean priced usage Apr 27–30 × 26 missing days",
        "runtime.json: four retained late-April days",
        "Same pre-May classifier phase; use its own late-April traffic/token sample. Range 50–150% of sampled load; no Luna cost is applied here.",
        confidence="low",
        low=apr_daily * D(13),
        high=apr_daily * D(39),
    )
    june_sample = [r for r in by_month["2026-06"] if r["day"] <= "2026-06-03"]
    june_daily = haiku_cost(june_sample) / D(3)
    add(
        "Anthropic",
        "claude-haiku-4-5-20251001",
        "production",
        "Estimated",
        june_daily * D("25.5"),
        "2026-06-04",
        "2026-06-29",
        "Mean priced usage Jun 1–3 × (25 missing days + assumed half of Jun 4)",
        "runtime.json and June 4 noon backup boundary",
        "Use full Jun 1–3 after prompt calibration. Jun 4 boundary assumed half-day. Jun 30 retained records are included separately; exact boundary loss there is unquantifiable. Range 50–150% of sampled load.",
        confidence="low",
        low=june_daily * D("12.75"),
        high=june_daily * D("38.25"),
    )
    july_sample = [r for r in by_month["2026-07"] if r["day"] < "2026-07-31"]
    july_daily = haiku_cost(july_sample) / D(30)
    add(
        "Anthropic",
        "claude-haiku-4-5-20251001",
        "production",
        "Estimated",
        july_daily * D(23) / D(24),
        "2026-07-31T01:03:40+00:00",
        "2026-07-31T23:59:59+00:00",
        "Mean priced usage Jul 1–30 × 23/24 day",
        "July 31 backup boundary; runtime.json",
        "Approximate 23 missing hours after the last July snapshot. Range 50–150% of sample; already retained Jul 31 calls are separate.",
        confidence="medium",
        low=july_daily * D(23) / D(48),
        high=july_daily * D(23) / D(16),
    )
    aug_sample = [r for r in by_month["2026-08"] if r["day"] >= "2026-08-22"]
    aug_daily = haiku_cost(aug_sample) / D(10)
    add(
        "Anthropic",
        "claude-haiku-4-5-20251001",
        "production",
        "Estimated",
        aug_daily * D(20),
        "2026-08-01",
        "2026-08-20",
        "Mean priced usage Aug 22–31 × 20 missing days",
        "runtime.json: ten complete late-August days",
        "Same Haiku runtime, using August's own sample. Aug 21 retained rows stay separate. Range 50–150% of sampled load.",
        confidence="low",
        low=aug_daily * D(10),
        high=aug_daily * D(30),
    )

    # The live ledger contains a 51-request local test seed. Split, do not add it again.
    experiments = source("experiments")
    seed = experiments["excluded_or_overlapping"][0]
    production = source("production")["usage_daily"]
    grouped = defaultdict(list)
    for r in production:
        if r["status"] == "settled":
            grouped[(r["day"][:7], r["purpose"])].append(r)
    for (month, purpose), rows in grouped.items():
        subtotal = sum(D(r["configured_cost_usd"]) for r in rows)
        base = sum(
            (
                (D(r["input_tokens"]) - D(r["cached_tokens"])) * D("0.2")
                + D(r["cached_tokens"]) * D("0.02")
                + D(r["output_tokens"]) * D("1.2")
            )
            / D(1_000_000)
            for r in rows
        )
        if month == "2026-09":
            for item in seed["model_breakdown"]:
                if item["purpose"] == purpose:
                    subtotal -= D(item["charged_usd"])
                    base -= (
                        (D(item["input_tokens"]) - D(item["cached_tokens"])) * D("0.2")
                        + D(item["cached_tokens"]) * D("0.02")
                        + D(item["output_tokens"]) * D("1.2")
                    ) / D(1_000_000)
        add(
            "OpenAI",
            "gpt-5.6-luna",
            "production",
            "Estimated",
            subtotal,
            "2026-09-20T21:29:49+00:00" if month == "2026-09" else "2026-10-01",
            max(r["day"] for r in rows),
            f"Sum settled {purpose} costs; subtract migration test seed; input .20, cache-read .02, output 1.20 USD/M; uncached premium ×1.25",
            "production.json: persistent model_usage ledger; official Luna tariff",
            "Conservative point assumes uncached input is cache-write billed; lower scenario prices it as ordinary input. API exposes cached-read counts but stored records do not distinguish cache writes. Output already includes any reasoning; do not add reasoning again. Standard short-context requests, no tools or batch. Reservations are outside this total.",
            low=base,
            high=subtotal,
            confidence="medium",
        )
    for item in seed["model_breakdown"]:
        add(
            "OpenAI",
            item["model"],
            "testing_evaluation",
            "Estimated",
            item["charged_usd"],
            item["first_at"],
            item["last_at"],
            "Settled migration seed; reclassified from production, not duplicated",
            "experiments.json migration seed and production ledger",
            "51 calls were copied to live ledger; classification and translation test costs included exactly once.",
            confidence="high",
        )

    for r in experiments["runs"]:
        kind = r["artifact_cost_kind"]
        if kind == "ledger_estimate":
            for item in r["model_breakdown"]:
                add(
                    "TypeSafe" if item["model"].startswith("jev") else "OpenAI",
                    item["model"],
                    "testing_evaluation",
                    "Estimated",
                    item["charged_usd"],
                    item["first_at"],
                    item["last_at"],
                    "Final cumulative settled ledger only",
                    r["artifact"],
                    "Earlier pilot/recovery ledgers are cumulative copies. Jev cost is input tokens × .042 USD/M; the hybrid's Luna costs are separate. TypeSafe console balance/funding not accessible.",
                    confidence="high",
                )
            continue
        start = r.get("started_at") or r.get("created_at") or r.get("artifact_mtime_utc")
        assert start
        end = r.get("finished_at") or start
        model = r.get("model") or r.get("model_id") or r.get("model_spec")
        reported = r.get("artifact_cost_usd")
        if kind == "legacy_rate_estimate":
            amount = r["recalculated_at_1_5_usd"]
            provider = "Anthropic"
            category = "Estimated"
            formula = "Saved input tokens ×1/M + output ×5/M, replacing .80/4 report estimator"
            assumption = (
                "Haiku 4.5 standard tariff; no provider invoice. Original report remains unchanged in evidence."
            )
        elif kind == "isolated_session_cost":
            amount = r["isolated_session_cost_usd"]
            provider = "OpenAI"
            category = "Estimated"
            formula = "Approved per-run cap − remaining per-run allowance"
            assumption = "Use isolated allowance, not shared-ledger before/after delta. Three failures were invalid structured answers, priced before validation; no transport-failure reservation in these runs. Includes summary repairs."
        elif kind == "report_estimate":
            amount = reported
            provider = "OpenAI"
            category = "Estimated"
            formula = "Saved successful-result report cost"
            assumption = (
                "Human-labelled direct evaluation; failed invalid answers priced by a separate reconstruction below."
            )
        else:
            amount = reported or 0
            provider = "OpenRouter"
            category = "Verified"
            formula = "Provider-returned request cost sum; retry cost separately checked =0"
            assumption = (
                "Only provider-reported consumption, not cash funding. Endpoint: "
                + str(r.get("provider"))
                + ". Unknown-cost failed attempts are not converted into zero billing."
            )
            if D(amount) == ZERO and r.get("errors", 0):
                continue
        add(
            provider,
            model,
            "testing_evaluation",
            category,
            amount,
            start,
            end,
            formula,
            r["artifact"],
            assumption,
            confidence="high",
            kind="provider_usage" if category == "Verified" else "estimated_consumption",
        )
    failed_direct = [
        r for r in experiments["runs"] if r["phase"] == "gpt6_human_labelled_direct" and r["model"] == "gpt-6-luna"
    ]
    failures = sum(r["errors"] for r in failed_direct)
    successful = sum(r["logical_results"] - r["errors"] for r in failed_direct)
    failed_estimate = sum(D(r["artifact_cost_usd"]) for r in failed_direct) / D(successful) * D(failures)
    add(
        "OpenAI",
        "gpt-6-luna",
        "testing_evaluation",
        "Estimated",
        failed_estimate,
        "2026-09-23",
        "2026-09-23",
        f"{failures} invalid paid answers × mean successful same-model cost ({successful} results)",
        "experiments.json direct human-labelled runs; provider settles before structured validation",
        "These eight served invalid answers are absent from successful-result report cost. Assume their mean token cost equals successful same-model answers; 50–200% sensitivity.",
        confidence="medium",
        low=failed_estimate / D(2),
        high=failed_estimate * D(2),
    )
    router_total = sum(
        r["amount"] for r in entries if r["provider"] == "OpenRouter" and r["evidence_category"] == "Verified"
    )
    add(
        "OpenRouter",
        "credit-purchase fee allocation",
        "unclassified_project_usage",
        "Estimated",
        router_total * D("0.055"),
        "2026-09-20",
        "2026-09-24",
        "Attributable consumed credits × standard 5.5% funding fee",
        "OpenRouter official pricing; provider-reported Sentinel costs",
        "Explicit funding scenario: credits came from a standard paid purchase; allocate purchase fee in proportion to Sentinel consumption, never all shared-account funding. Lower zero if promotional/no-fee credits; upper .80 assumes one minimum-fee funding purchase. Multiple purchase minima remain unknown. Funding principal is NOT added to consumption.",
        confidence="low",
        low=ZERO,
        high=max(D("0.80"), router_total * D("0.055")),
    )

    alerts = source("alerts")["monthly"]
    for month, r in alerts.items():
        sms = D(r["sms_segments"]) * D("0.0457")
        voice = D(r["call_minutes"]) * D("0.0715")
        tts = D(r["voice_tts_upper_usd"])
        whatsapp = D(r["whatsapp"]) * D("0.005")
        for model, amount, formula, low, high in [
            ("outbound SMS", sms, f"{r['sms_segments']} segments × .0457 USD", sms * D("0.75"), sms * D("1.25")),
            (
                "outbound EEA voice",
                voice,
                f"{r['call_minutes']} started minutes × .0715 USD",
                voice * D("0.75"),
                max(voice * D("1.25"), D(r["call_minutes"]) * D(".2202")) if month == "2026-03" else voice * D("1.25"),
            ),
            ("Polly.Ewa TTS", tts, "Full repeated Say text; rounded per call to 100 chars × .0008 USD", ZERO, tts),
            ("WhatsApp sandbox", whatsapp, f"{r['whatsapp']} messages × .005 USD", whatsapp, whatsapp),
        ]:
            if amount:
                add(
                    "Twilio",
                    model,
                    "unclassified_project_usage",
                    "Estimated",
                    amount,
                    month + "-01",
                    month_end(month),
                    formula,
                    "alerts.json: unique real-looking provider SIDs; official Twilio pricing",
                    "Stored alerts cover the active months across 90-day-retention snapshots. Historical SMS/voice tariffs not retained publicly: assume current tariff throughout, range ±25%; March voice upper also covers non-EEA origin before the recovered March 28 Polish-number configuration. UCS2 multipart segmentation computed from stored bodies without retaining content. Voice zero-duration completed calls use one minute. TTS upper assumes every Say executes; early hangup/caching can reduce it. WhatsApp assumes sandbox/session messages without Meta template fees. Production and live tests cannot be distinguished consistently.",
                    low=low,
                    high=high,
                    confidence="medium",
                )
    # Phone-number recurring fees are anniversary billed, not partial calendar-month charges.
    for m in range(3, 10):
        start = f"2026-{m:02}-21"
        end = f"2026-{m + 1:02}-21"
        add(
            "Twilio",
            "Polish number rental",
            "infrastructure",
            "Estimated",
            4,
            start,
            end,
            "One retained +48 number × $4 monthly anniversary charge",
            "Configured Polish number; March 21 playground; suspension emails warn retained resources continue charging; official pricing/purchase flows",
            "Assume number bought March 21 and not released: seven charges through September 21, next October 21. Actual type/purchase date/retention and trial credits unknown. Low zero for trial/released number; high $4. Future monthly normalization still includes $4.",
            confidence="low",
            low=ZERO,
            high=4,
            valuation=start,
            kind="estimated_recurring_purchase",
        )
    add(
        "Twilio",
        "initial playground tests",
        "testing_evaluation",
        "Estimated",
        D(5) * D("0.0715") + D(10) * D("0.0457") + D(5) * D("0.005"),
        "2026-03-21",
        "2026-03-22",
        "Scenario: 5 one-minute calls +10 SMS segments +5 WhatsApp messages",
        "First playground/error-handling commits",
        "No surviving request log for original UI. Explicit scenario, not observed calls; assumes these UI tests are outside the bot's alert records. Range 0–5 USD covers small manual tests and origin-rate differences.",
        confidence="low",
        low=ZERO,
        high=5,
    )
    add(
        "Apple",
        "Developer Program annual membership",
        "infrastructure",
        "Estimated",
        99,
        "2026-06-01",
        "2026-06-01",
        "One annual purchase × official $99/year tariff",
        "Owner confirms project-only purchase; account documented active June 1; official Apple membership price",
        "100% Sentinel allocation confirmed. Assume first payment June 1 and annual service June 1 2026–June 1 2027. Amount/date/currency not on receipt: USD is a list-price proxy, not the known native settlement currency. Range includes up to 23% local tax; local-currency pricing can differ outside it. Full annual purchase counted here, never again as historical monthly accrual.",
        confidence="medium",
        low=99,
        high=D(99) * D("1.23"),
        kind="estimated_prepaid_purchase",
    )

    csv_write(AUDIT / "reconstruction.csv", [r for r in entries if r["evidence_category"] == "Estimated"])
    csv_write(AUDIT / "cost-items.csv", entries)
    # Actual events only in ledger: invoices, provider-returned usage, and amount-unknown confirmed purchase.
    ledger = []
    for invoice in billing["invoices"]:
        ledger.append(
            dict(
                transaction_id=invoice["reference"],
                provider="Hetzner",
                transaction_kind="invoice_accrual",
                effective_start=invoice["service_months"][0] + "-01",
                effective_end=month_end(invoice["service_months"][-1]),
                posted_at=invoice["invoice_date"],
                recorded_at=RECORDED,
                currency="EUR",
                amount=D(invoice["amount"]),
                evidence_category="Verified",
                allocation_fraction=D(1),
                confirmed_cash_amount=None,
                source="evidence/billing.json",
                note="Sentinel line items only; invoice amount is not proof of payment.",
            )
        )
    for r in entries:
        if r["transaction_kind"] == "provider_usage":
            ledger.append(
                dict(
                    transaction_id=r["item_id"],
                    provider=r["provider"],
                    transaction_kind="provider_usage",
                    effective_start=r["usage_start"],
                    effective_end=r["usage_end"],
                    posted_at=r["usage_start"],
                    recorded_at=RECORDED,
                    currency=r["currency"],
                    amount=r["amount"],
                    evidence_category="Verified",
                    allocation_fraction=D(1),
                    confirmed_cash_amount=None,
                    source=r["source"],
                    note="Provider-reported attributable consumption; no funding payment booked.",
                )
            )
    ledger.append(
        dict(
            transaction_id="apple-owner-confirmed-purchase",
            provider="Apple",
            transaction_kind="confirmed_purchase_amount_unknown",
            effective_start="2026-05-30",
            effective_end="2026-06-03",
            posted_at="",
            recorded_at=RECORDED,
            currency="UNKNOWN",
            amount=None,
            evidence_category="Unknown",
            allocation_fraction=D(1),
            confirmed_cash_amount=None,
            source="evidence/user-confirmations.json",
            note="Owner confirms purchase specifically for Sentinel; exact date, amount and currency unknown. The $99 scenario is only in reconstruction.csv.",
        )
    )
    csv_write(AUDIT / "ledger.csv", ledger)

    hist = []
    for month in MONTHS:
        for currency in ["EUR", "USD", "PLN"]:
            rows = [
                r for r in entries if r["usage_start"][:7] == month and (currency == "PLN" or r["currency"] == currency)
            ]

            def value(r, value_currency=currency):
                return r["pln_equivalent"] if value_currency == "PLN" else r["amount"]

            verified = sum((value(r) for r in rows if r["evidence_category"] == "Verified"), ZERO)
            estimated = sum((value(r) for r in rows if r["evidence_category"] == "Estimated"), ZERO)
            hist.append(
                dict(
                    month=month,
                    currency=currency,
                    value_basis="currency_equivalent_not_bank_debit"
                    if currency == "PLN"
                    else "native_tariff_or_invoice_amount",
                    verified_cost=verified,
                    estimated_additions=estimated,
                    reconstructed_total=verified + estimated,
                    reconstructed_low=sum((r["low_pln"] if currency == "PLN" else r["low"] for r in rows), ZERO),
                    reconstructed_high=sum((r["high_pln"] if currency == "PLN" else r["high"] for r in rows), ZERO),
                    confirmed_cash_payments=None,
                    cash_status="unknown_amounts; Apple purchase occurrence confirmed",
                    effective_start=max(month + "-01", "2026-03-21"),
                    effective_end=AS_OF if month == "2026-10" else month_end(month),
                    recorded_at=RECORDED,
                    note="Costs assigned to usage/purchase month; invoices valued at issue-date FX, estimates at dated period-end FX. Includes whole Apple annual purchase once; invoice/funding taxes or credits not known.",
                )
            )
    csv_write(AUDIT / "history-monthly.csv", hist)
    current = []
    planning_fx = {c: fx(c, "2026-10-11") for c in ["EUR", "USD"]}

    def recurring(service, provider, currency, amount, low, high, status, formula, assumptions):
        rate, rd, table = planning_fx[currency]
        current.append(
            dict(
                service=service,
                provider=provider,
                currency=currency,
                normalized_monthly=D(amount),
                low=D(low),
                high=D(high),
                pln_equivalent=D(amount) * rate,
                low_pln=D(low) * rate,
                high_pln=D(high) * rate,
                evidence_category=status,
                effective_date=RECORDED,
                recorded_at=RECORDED,
                measurement_start="2026-10-01" if provider == "OpenAI" else "2026-10-11",
                measurement_end="2026-10-10T23:59:59Z" if provider == "OpenAI" else AS_OF,
                fx_rate_date=rd,
                fx_pln_per_unit=rate,
                formula=formula,
                assumptions=assumptions,
            )
        )

    recent = [r for r in production if r["status"] == "settled" and "2026-10-01" <= r["day"] <= "2026-10-10"]
    recent_cost = sum(D(r["configured_cost_usd"]) for r in recent)
    recent_base = sum(
        (
            (D(r["input_tokens"]) - D(r["cached_tokens"])) * D(".2")
            + D(r["cached_tokens"]) * D(".02")
            + D(r["output_tokens"]) * D("1.2")
        )
        / D(1_000_000)
        for r in recent
    )
    daily_config = defaultdict(lambda: ZERO)
    daily_base = defaultdict(lambda: ZERO)
    for r in recent:
        daily_config[r["day"]] += D(r["configured_cost_usd"])
        daily_base[r["day"]] += (
            (D(r["input_tokens"]) - D(r["cached_tokens"])) * D(".2")
            + D(r["cached_tokens"]) * D(".02")
            + D(r["output_tokens"]) * D("1.2")
        ) / D(1_000_000)
    recurring(
        "CX23 + IPv4",
        "Hetzner",
        "EUR",
        "4.49",
        "4.49",
        "4.49",
        "Estimated",
        "Latest invoice 3.99 + .50",
        "Same legacy instance and zero-tax invoice profile; server exclusively Sentinel assumed from deployment/service marker.",
    )
    recurring(
        "Production classification + enrichment + summary translation",
        "OpenAI",
        "USD",
        recent_cost * D(3),
        min(daily_base.values()) * D(30),
        max(daily_config.values()) * D(30),
        "Estimated",
        "Ten complete UTC days × 30/10; 30-day planning month",
        "Conservative cache-write premium. Bounds repeat the quietest observed day with ordinary input or busiest day with cache-write premium for 30 days; sensitivity, not a statistical interval. Same-volume ordinary-input scenario is $14.94326448. Historical experiments excluded. October 31-day projection separately stated. Unverified account tax/credits not included.",
    )
    recurring(
        "Retained Polish number",
        "Twilio",
        "USD",
        4,
        0,
        4,
        "Estimated",
        "One number × $4/month",
        "Suspension can leave rental accruing. Current retention/trial status not accessible; lower released/free-trial scenario.",
    )
    recurring(
        "Developer Program",
        "Apple",
        "USD",
        D(99) / D(12),
        D(99) / D(12),
        D(99) * D("1.23") / D(12),
        "Estimated",
        "$99 annual purchase /12",
        "100% allocation confirmed; amount is USD tariff proxy, actual settlement currency unknown. Annual renewal, not monthly debit.",
    )
    for service, provider, assumption in [
        ("Expo Push", "Expo", "Official free push service; EAS paid plans separate."),
        (
            "Included disk + local backups",
            "Hetzner",
            "Daily seven-day DB backups and deploy snapshots on included disk; invoices show no separate cloud backups/storage.",
        ),
        ("Health monitoring", "Local cron", "Local health/cron/syslog; no Sentinel managed-monitoring bill found."),
        (
            "CI/builds",
            "Local/GitHub/Expo",
            "No paid CI configured in project or attributable paid EAS bill; paid plan/overage remains unverified.",
        ),
        (
            "Domains and operational email",
            "None evidenced",
            "Runtime uses server endpoints and existing owner mailboxes; no Sentinel-only purchase or evidence of a marginal shared allocation.",
        ),
        (
            "Source APIs",
            "RSS/Telegram/Google News/GDELT",
            "Configured public feeds/APIs; no paid source subscription found.",
        ),
        (
            "Ongoing testing",
            "Model providers",
            "Latest saved paid comparison/eval artifacts are September; no regular October paid-test schedule evidenced.",
        ),
        (
            "Suspended outbound alerts",
            "Twilio",
            "No successful September/October call/SMS rows; rejected 401 API calls are not delivered-message failures with a .001 fee.",
        ),
    ]:
        recurring(
            service,
            provider,
            "USD",
            0,
            0,
            0,
            "Estimated",
            "Zero marginal charge under evidenced current architecture",
            assumption + " Absence of a billing record is not proof of every account being free.",
        )
    csv_write(AUDIT / "current-monthly.csv", current)
    llm = defaultdict(lambda: {"verified": ZERO, "estimated": ZERO, "low": ZERO, "high": ZERO})
    for r in entries:
        if r["provider"] in ["Anthropic", "OpenAI", "OpenRouter", "TypeSafe"]:
            v = llm[(r["provider"], r["model"], r["phase"])]
            v["verified" if r["evidence_category"] == "Verified" else "estimated"] += r["amount"]
            v["low"] += r["low"]
            v["high"] += r["high"]
    llm_rows = [
        dict(
            provider=k[0],
            model=k[1],
            phase=k[2],
            currency="USD",
            verified=v["verified"],
            estimated=v["estimated"],
            total=v["verified"] + v["estimated"],
            low=v["low"],
            high=v["high"],
            recorded_at=RECORDED,
        )
        for k, v in sorted(llm.items())
    ]
    csv_write(AUDIT / "llm-by-model-phase.csv", llm_rows)
    timeline = []
    for k in sorted(llm):
        if k[1] == "credit-purchase fee allocation":
            continue
        rows = [r for r in entries if (r["provider"], r["model"], r["phase"]) == k]
        timeline.append(
            dict(
                billing_route=k[0],
                exact_model=k[1],
                phase=k[2],
                effective_start=min(r["usage_start"] for r in rows),
                effective_end=max(r["usage_end"] for r in rows),
                recorded_at=RECORDED,
                source="cost-items.csv; experiments.json; repository.json",
                date_confidence="See source rows: production deployment exact, missing historical periods reconstructed.",
            )
        )
    for model in ["qwen/qwen3.7-flash"]:
        timeline.append(
            dict(
                billing_route="OpenRouter",
                exact_model=model,
                phase="testing_evaluation",
                effective_start="2026-09-23",
                effective_end="2026-09-23",
                recorded_at=RECORDED,
                source="experiments.json smoke failure rows",
                date_confidence="Observed attempts; no provider-returned cost, billing unknown.",
            )
        )
    csv_write(AUDIT / "model-timeline.csv", timeline)
    totals = {}
    for currency in ["EUR", "USD", "PLN"]:
        h = [r for r in hist if r["currency"] == currency]
        totals[currency] = {
            k: number(sum((r[k] for r in h), ZERO))
            for k in [
                "verified_cost",
                "estimated_additions",
                "reconstructed_total",
                "reconstructed_low",
                "reconstructed_high",
            ]
        }
    monthly = sum((r["pln_equivalent"] for r in current), ZERO)
    reserved = sum((D(r["configured_cost_usd"]) for r in production if r["status"] == "reserved"), ZERO)
    summary = dict(
        schema_version=1,
        recorded_at=RECORDED,
        as_of_utc=AS_OF,
        historical_basis="Attributable invoice/provider-reported consumption plus tariff reconstruction and annual purchase scenario; not a cash-payment total. Unverified taxes/credits/funding remain outside base totals.",
        historical=totals,
        current_pln=number(monthly),
        current_low_pln=number(sum((r["low_pln"] for r in current), ZERO)),
        current_high_pln=number(sum((r["high_pln"] for r in current), ZERO)),
        current_native={
            c: number(sum((r["normalized_monthly"] for r in current if r["currency"] == c), ZERO))
            for c in ["EUR", "USD"]
        },
        production_api_30day_usd=number(recent_cost * D(3)),
        production_api_31day_usd=number(recent_cost * D("3.1")),
        production_api_ordinary_input_30day_usd=number(recent_base * D(3)),
        api_reservations_not_counted_usd=number(reserved),
        confirmed_cash_total=None,
        apple_annual_estimate_usd="99",
        apple_remaining_service_value_estimate_usd=number(D(99) * D(233) / D(365)),
        planning_fx={c: {"pln_per_unit": number(v[0]), "date": v[1], "table": v[2]} for c, v in planning_fx.items()},
        recommended_budget_pln="200",
        provider_rows=len(llm_rows),
        cost_items=len(entries),
        ledger_rows=len(ledger),
        instruction_files_changed=False,
        subagents={
            "count": 3,
            "peak_parallel": 3,
            "model": "gpt-5.6-sol",
            "repository_agent_reused_for_cost_refinement": True,
        },
    )
    (AUDIT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    render(summary, current, hist, llm_rows, entries)
    for name in ["ledger.csv", "current-monthly.csv", "history-monthly.csv"]:
        (ROOT / name).write_bytes((AUDIT / name).read_bytes())
    (ROOT / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Sentinel finance</title><h1>Sentinel finance</h1><p><a href="reports/2026-10-11/report.html">October 11, 2026 audit</a></p><p><a href="maintenance-policy.html">Proposed shared maintenance policy</a></p></html>'
    )
    return summary


def table(headers, rows):
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join("<th>" + html.escape(str(h)) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join("<td>" + html.escape(str(c)) + "</td>" for c in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def render(s, current, hist, llm, items):
    e = html.escape
    hist_rows = [r for r in hist if r["currency"] == "PLN"]
    totals = s["historical"]
    sections = []
    sections.append(
        f'<header><p class="eyebrow">PROJECT SENTINEL · FINANCE AUDIT · {RECORDED}</p><h1>What Sentinel costs</h1><p>Development and testing from March 21, 2026 through October 11, 2026 at 00:38:49 UTC (02:38:49 in Warsaw). The live production model is direct OpenAI <code>gpt-5.6-luna</code>.</p></header>'
    )
    sections.append(
        f'<div class="cards"><div><span>Current monthly planning cost</span><strong>PLN {D(s["current_pln"]):.2f}</strong><p>EUR {D(s["current_native"]["EUR"]):.2f} + USD {D(s["current_native"]["USD"]):.2f}</p></div><div><span>Recommended reserve</span><strong>PLN 200/month</strong><p>Includes annual Apple provision, retained-number scenario and margin for API variation/unverified tax. No plan or spending cap changed.</p></div></div>'
    )
    sections.append(
        "<aside><strong>These are cost records and a labelled reconstruction, not a bank-spending statement.</strong> Verified hosting invoices do not prove payment. Provider-reported request cost proves attributable usage cost, not the funding source. Apple purchase and 100% allocation are owner-confirmed, but its amount/date/currency are estimated. API top-ups, remaining balances, free credits, discounts and taxes are not reconciled without authenticated billing.</aside>"
    )
    sections.append(
        "<h2>Evidence and investigation</h2><p><b>Verified:</b> invoices or attributable provider-returned costs. <b>Estimated:</b> token pricing, sampled missing periods or explicit purchase/retention scenarios. <b>Unknown:</b> insufficient records; never silently booked as zero.</p><p>Read project CLAUDE.md, server runbook, relevant subsystem rules and all reachable Git refs. Root AGENTS.md and finance rules/structure were absent. Three inexpensive gpt-5.6-sol agents independently covered repository/history, both mailboxes and official pricing; peak parallelism three. Main session handled read-only production snapshots, billing/API access, allocation and arithmetic. No new inference/test-alert calls, purchases, plan changes or production edits.</p>"
    )
    sections.append(
        "<h2>Current normalized monthly costs</h2>"
        + table(
            ["Service", "Native amount/month", "Evidence", "Basis"],
            [
                (r["service"], money(r["normalized_monthly"], r["currency"]), r["evidence_category"], r["formula"])
                for r in current
            ],
        )
    )
    sections.append(
        f"<p>API window: October 1–10, ten complete UTC days, USD 5.69167721 at conservative configured rates. A 30-day planning month projects USD {D(s['production_api_30day_usd']):.2f}; October’s 31-day projection is USD {D(s['production_api_31day_usd']):.2f}. Ordinary-input rather than cache-write pricing lowers the 30-day API scenario to USD 14.94326448. Both enrichment and Polish-summary repairs are included. Annual Apple fee is divided by 12; occasional September experiments are historical only.</p><p>Current scenario range: PLN {D(s['current_low_pln']):.2f}–{D(s['current_high_pln']):.2f}, before additional unverified API tax and account adjustments. Planning FX: October 9 NBP USD 3.9022 and EUR 4.3775 PLN. Amounts are currency equivalents, not bank debits. Use PLN 200 as a planning reserve; the live app allowance remains USD 30, with provider cap last documented at USD 10 on September 20.</p>"
    )
    sections.append(
        "<h2>Historical totals: verified and reconstructed separately</h2>"
        + table(
            ["Basis", "EUR", "USD", "PLN equivalent"],
            [
                (label, totals["EUR"][key], totals["USD"][key], money(totals["PLN"][key], "PLN"))
                for label, key in [
                    ("Verified costs", "verified_cost"),
                    ("Estimated additions", "estimated_additions"),
                    ("Combined reconstruction", "reconstructed_total"),
                    ("Low scenario", "reconstructed_low"),
                    ("High scenario", "reconstructed_high"),
                ]
            ],
        )
    )
    sections.append(
        "<p>Verified EUR 13.47 is two invoices for three service months: July/August EUR 8.98 issued October 1, and September EUR 4.49 issued October 4; invoice tax is zero. Verified USD is OpenRouter-returned request consumption. Neither is a confirmed cash-payment total. Confirmed attributable cash amounts are <b>unknown</b>. Historical purchase/consumption totals include the full estimated USD 99 Apple annual purchase once, even though part of its service period lies after this audit; monthly Apple accrual is not added again.</p>"
    )
    sections.append(
        "<h2>Month-by-month reconstruction</h2>"
        + table(
            ["Month", "Verified PLN equivalent", "Estimated additions", "Combined", "Low–high"],
            [
                (
                    r["month"],
                    f"{r['verified_cost']:.2f}",
                    f"{r['estimated_additions']:.2f}",
                    f"{r['reconstructed_total']:.2f}",
                    f"{r['reconstructed_low']:.2f}–{r['reconstructed_high']:.2f}",
                )
                for r in hist_rows
            ],
        )
    )
    sections.append(
        "<p>Native EUR/USD rows and exact dated FX are in the CSVs. Usage is assigned to its service month; invoices use issue-date FX, not an invented payment date. Estimates use the nearest available NBP business-day rate at the stated valuation date. October is only through the observation cutoff. Scenario bounds are sensitivities, not statistical confidence intervals, and exclude unquantifiable billing adjustments.</p>"
    )
    sections.append(
        "<h2>Models, billing routes and phases</h2>"
        + table(
            ["Billing route", "Exact model / fee", "Phase", "Verified USD", "Estimated USD", "Total USD"],
            [
                (
                    r["provider"],
                    r["model"],
                    r["phase"],
                    f"{r['verified']:.6f}",
                    f"{r['estimated']:.6f}",
                    f"{r['total']:.6f}",
                )
                for r in llm
            ],
        )
    )
    sections.append(
        "<p>Haiku phase: March 21–September 20, exact ID <code>claude-haiku-4-5-20251001</code>, through Anthropic API. Luna production began September 20 at 21:29:49 UTC, exact ID <code>gpt-5.6-luna</code>, through OpenAI Responses API. Jev 1.13.0 was tested September 22–23 on an unmerged branch, including a Luna hybrid; TypeSafe usage is separate from the hybrid’s OpenAI usage. GPT-6 Luna was evaluated September 23 and abandoned. All recorded OpenRouter smoke models/endpoints, including failed candidates, appear in experiments.json; planned March Sonnet/Opus escalation was not deployed.</p>"
    )
    sections.append(
        "<h2>Reconstruction and duplicate controls</h2><ul><li>Runtime classification IDs are deduplicated across 18 server backups, live DB and local snapshots. Dashboard contributes only 418 new late-April rows; early local DB contributes 42. SMS/calls also checked by provider SID; no duplicate or simulated SID rows found.</li><li>Missing Haiku periods use phase-specific samples: early 51 calls/14 hours and 699/146 tokens, Apr 27–30, Jun 1–3, Jul 1–30 and Aug 22–31. Exact formulas, periods and sensitivities are in reconstruction.csv. May and the retained September window are not extrapolated merely because invoices are absent.</li><li>Historical Haiku report formula .80/4 USD/M is replaced by official 1/5 pricing for this audit; old artifacts are preserved. Cached/batch/tool charges are not invented for the legacy requests.</li><li>The 51 migration tests (USD .01801648) seeded into production are reclassified, not added twice. Jev uses only the final 407-row cumulative ledger, of which TypeSafe is USD .074125296 and the balance is OpenAI. Offline corrected replays cost no new calls.</li><li>Concurrent GPT-6 summaries overstated cost by USD .032474315. Run-isolated allowances replace shared-ledger deltas. Invalid served answers are billed before validation; eight human-labelled invalid answers are estimated from same-model successful calls.</li><li>Eval-suite has 985 logical rows and 1,017 attempts, including 32 retries. Provider-reported costs are used, rather than multiplying every failed HTTP attempt by a unit price. Unknown-cost failed attempts stay unknown.</li><li>Twilio counts 5,567 Unicode SMS segments, not 530 messages. May alone is 3,015 segments × .0457 = USD 137.7855; with rental/voice/TTS, about USD 144. This independently fits the archived approximate USD 150 Twilio note; the note is not booked as a payment.</li></ul>"
    )
    sections.append(
        "<h2>Prepaid funds, balances, credits and taxes</h2>"
        + table(
            ["Item", "Treatment"],
            [
                (
                    "API top-ups / cash receipts",
                    "No attributable successful top-up receipt or payment statement found; amount unknown. Funding principal never added to the same consumed credits.",
                ),
                (
                    "API credit consumption",
                    "OpenRouter provider-returned costs verified; Anthropic/OpenAI/TypeSafe token-derived consumption estimated. Credits or promotions may fund usage without owner cash.",
                ),
                (
                    "OpenRouter funding fee",
                    "5.5% of attributable consumption is an explicit allocation scenario; minimum .80 and funding history remain unresolved.",
                ),
                (
                    "Remaining provider balances",
                    "Unknown. October global Jev ledger balance is estimated, shared and unrelated to the September Sentinel ledger; excluded.",
                ),
                (
                    "Apple prepaid year",
                    f"USD 99 purchase scenario for Jun 1, 2026–Jun 1, 2027; unexpired service value about USD {D(s['apple_remaining_service_value_estimate_usd']):.2f}, not a refundable cash balance.",
                ),
                (
                    "Uncertain API reservations",
                    f"USD {D(s['api_reservations_not_counted_usd']):.8f} September reservations excluded from incurred cost; possible billed amount requires provider evidence.",
                ),
                (
                    "Taxes/refunds/discounts",
                    "Hetzner invoice tax verified zero. API/Apple actual invoice tax, credits and refunds are unknown. Base totals are tariff costs before unverified API tax; a 23% USD-cost tax scenario is provided below, not booked as payment.",
                ),
            ],
        )
    )
    usd_reconstructed = D(totals["USD"]["reconstructed_total"])
    sections.append(
        f"<p>Additional 23% tax sensitivity on all USD tariff/usage costs would add USD {usd_reconstructed * D('.23'):.2f}; this is a scenario only and may overstate business-account tax or tax already embedded in regional Apple pricing. No gross-to-net or free-trial discount is invented. Historical cash spending and net billable consumption after all account adjustments remain unresolved.</p>"
    )
    sections.append(
        "<h2>Renewals and exposure</h2><ul><li>Apple: provision USD 99/year; estimated renewal around June 1, 2027. Actual date/settlement currency await receipt.</li><li>Hetzner: EUR 4.49/month on the retained instance. A new/rescaled CX23 would be EUR 5.99 plus any extras; June price adjustment does not by itself prove an increase on this server. No new purchase or rescale performed.</li><li>Twilio: retained-number scenario USD 4/month despite suspended communications; assumed next anniversary October 21. Releasing/trial status is not confirmed. Resuming funded calling/SMS adds event-driven consumption beyond this current paused-channel baseline.</li><li>Cloud backups/storage: local included-disk backups evidenced. Paid cloud Backup slots would add 20% of server base price, but were not evidenced on the Sentinel invoices and are not booked.</li><li>OpenAI: app cap is USD 30/month; separate provider cap was last documented USD 10. Current API demand can exceed that old cap, so authenticated billing should confirm its present setting.</li></ul>"
    )
    sections.append(
        "<h2>Coverage gaps and attribution limits</h2><p>Both mailboxes were searched with in:anywhere including Spam/Trash, all available provider history and targeted 2026 billing queries. No relevant targeted result set hit the 100-message tool cap. Provider dashboards require login/security checks; Chrome extension connection timed out. Read-only billing API attempts returned OpenAI 403 and Anthropic/OpenRouter/Twilio 401. Normal inference credentials do not establish administrative billing access. No credential, cookie or token is published.</p><ul><li>Recovered server credentials show one Anthropic variant across March/June backups and one OpenAI production key introduced at migration. OpenRouter evaluation key/limit is documented; Jev experiment manifests provide usage. Deleted keys, all account organizations/workspaces and historic billing routes cannot be enumerated without billing access; no claim of exhaustive provider-account coverage is made.</li><li>Shared account spending is never assigned wholesale to Sentinel. Shared Claude Code/Codex subscriptions and Google Vision are explicitly excluded. Other consumer/API account purchases without a project allocation remain unallocated; unrelated project invoices/correspondence are not published.</li><li>Apple allocation is owner-confirmed 100%. Server allocation is assumed 100% because deployment and invoice service lines identify Sentinel, pending owner confirmation of any co-hosting. Provider-side backup inventory, EAS plans, regional taxes, inbound SMS, Meta template fees and initial UI tests lack full billing records. A shared-account Netcup VPS invoice has no Sentinel marker or deployment match; it remains unallocated pending the owner’s answer.</li><li>A September comparison note refers to an observed USD 22.18 Haiku bill without its invoice or billing period. It is not added as a second expense because it may overlap reconstructed production/tests; its reconciliation remains unknown.</li><li>Legacy API retries can be billed without a successful persisted result. Five early retry warnings and unknown-cost suite failures cannot be priced exactly. Paid workflow coding usage would be in scope if billed through project API keys, but saved workflow logs contain no cost/token fields or confirmed API billing route; shared-subscription work is excluded.</li><li>No additional Sentinel-specific domain, email, managed-monitoring, storage, paid-source or CI charge was found in repository, deploy/cron/config records or either mailbox. Zero marginal estimates follow the evidenced local/free architecture; missing account invoices are not treated as proof of zero.</li></ul>"
    )
    sections.append(
        '<h2>Audit files and maintenance proposal</h2><p><a href="current-monthly.csv">Current monthly CSV</a> · <a href="model-timeline.csv">Model/provider timeline</a> · <a href="history-monthly.csv">Monthly historical CSV</a> · <a href="ledger.csv">Actual invoice/usage ledger</a> · <a href="reconstruction.csv">Estimates and assumptions</a> · <a href="cost-items.csv">Full reconciled cost items</a> · <a href="llm-by-model-phase.csv">LLM provider/model/phase CSV</a> · <a href="summary.json">Machine totals</a> · <a href="coverage-gaps.csv">Unknowns and coverage gaps</a> · <a href="evidence/experiments.json">All saved model runs</a> · <a href="evidence/pricing.json">Official pricing sources/timelines</a> · <a href="evidence/fx.json">Dated NBP rates</a> · <a href="../../maintenance-policy.html">Shared maintenance policy proposal</a></p><p>CLAUDE.md and AGENTS.md were not edited. Proposed CLAUDE.md addition: <code>Confirmed Sentinel cost changes must update finance records, recalculate totals and preserve dated history under finance/maintenance-policy.html.</code> Proposed root AGENTS.md (currently absent): <code>Apply the shared finance maintenance policy in finance/maintenance-policy.html when confirming a Sentinel cost change.</code> One shared policy holds the detail; both instruction files only reference it.</p>'
    )
    urls = []
    for provider in source("pricing")["providers"].values():
        for url in provider.get("sources", []):
            if url not in urls:
                urls.append(url)
    urls += [
        "https://api.nbp.pl/",
        "https://help.twilio.com/articles/49521202710555-About-Purchase-Flows",
        "https://www.twilio.com/en-us/whatsapp/pricing",
    ]
    sections.append(
        "<details><summary>Official source links</summary><ul>"
        + "".join(f'<li><a href="{e(u)}">{e(u)}</a></li>' for u in urls)
        + "</ul></details>"
    )
    sections.append(
        "<footer>Arithmetic and CSV/JSON validation are reproducible with finance/build_report.py --check. The report is self-contained and contains no tracking or external assets. All evidence is sanitized; billing export coverage remains incomplete.</footer>"
    )
    css = "body{font:16px/1.55 system-ui,sans-serif;color:#172638;background:#f3f5f7;margin:0}main{max-width:1150px;margin:auto;padding:40px 28px;background:white}h1{font-size:44px;margin:8px 0}h2{margin-top:42px;font-size:25px}.eyebrow{font-size:12px;letter-spacing:.12em;color:#4b667d}p{max-width:1000px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:26px 0}.cards>div{background:#eef5f7;border-top:4px solid #126a7a;padding:20px}.cards span{display:block}.cards strong{font-size:32px;display:block}.cards p{font-size:14px}aside{border-left:4px solid #b37e28;background:#fff7e8;padding:20px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;background:#17364b;color:white}th,td{padding:11px 12px;border-bottom:1px solid #dce3e8;vertical-align:top}tr:nth-child(even){background:#f5f8fa}a{color:#0b657b}code{overflow-wrap:anywhere}li{margin-bottom:8px}footer{margin-top:40px;border-top:1px solid #ccd4da;padding-top:16px;color:#536778;font-size:13px}@media(max-width:680px){main{padding:24px 16px}h1{font-size:32px}.cards{grid-template-columns:1fr}}@media print{body{background:white}main{max-width:none;padding:0}details{display:block}h2{break-after:avoid}tr{break-inside:avoid}}"
    (AUDIT / "report.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sentinel cost audit · 2026-10-11</title><style>'
        + css
        + "</style></head><body><main>"
        + "".join(sections)
        + "</main></body></html>"
    )


def check():
    for p in (AUDIT / "evidence").glob("*.json"):
        json.loads(p.read_text())
    summary = json.loads((AUDIT / "summary.json").read_text())
    files = {p.name: list(csv.DictReader(p.open())) for p in AUDIT.glob("*.csv")}
    costs = files["cost-items.csv"]
    assert len({r["item_id"] for r in costs}) == len(costs)
    for r in costs:
        assert r["usage_start"][:10] <= r["usage_end"][:10]
        assert D(r["low"]) <= D(r["amount"]) <= D(r["high"])
        assert D(r["allocation_fraction"]) == 1
        rate, rd, _ = fx(r["currency"], r["fx_valuation_date"])
        assert rd == r["fx_rate_date"] and abs(D(r["amount"]) * rate - D(r["pln_equivalent"])) < D(".000000001")
    for h in files["history-monthly.csv"]:
        rows = [
            r
            for r in costs
            if r["usage_start"][:7] == h["month"] and (h["currency"] == "PLN" or r["currency"] == h["currency"])
        ]
        value = "pln_equivalent" if h["currency"] == "PLN" else "amount"
        for category, column in [("Verified", "verified_cost"), ("Estimated", "estimated_additions")]:
            expected = sum((D(r[value]) for r in rows if r["evidence_category"] == category), ZERO)
            assert abs(expected - D(h[column])) < D(".000000002")
        assert abs(D(h["verified_cost"]) + D(h["estimated_additions"]) - D(h["reconstructed_total"])) < D(".000000002")
    ledger = files["ledger.csv"]
    assert len({r["transaction_id"] for r in ledger}) == len(ledger)
    assert all(r["confirmed_cash_amount"] == "" for r in ledger)
    invoices = [r for r in ledger if r["transaction_kind"] == "invoice_accrual"]
    assert len(invoices) == 2 and sum(D(r["amount"]) for r in invoices) == D("13.47")
    verified_router = sum(D(r["amount"]) for r in ledger if r["transaction_kind"] == "provider_usage")
    assert abs(verified_router - D(summary["historical"]["USD"]["verified_cost"])) < D(".000000001")
    assert abs(sum(D(r["pln_equivalent"]) for r in files["current-monthly.csv"]) - D(summary["current_pln"])) < D(
        ".000000001"
    )
    assert D(summary["api_reservations_not_counted_usd"]) > 0
    assert summary["confirmed_cash_total"] is None
    assert D(summary["historical"]["EUR"]["verified_cost"]) == D("13.47")
    assert sum(1 for r in costs if r["provider"] == "Apple") == 1
    assert (
        len([r for r in costs if "migration seed" in r["formula"].lower() and r["phase"] == "testing_evaluation"]) == 2
    )
    assert sum(r["extra_attempts"] for r in source("experiments")["runs"] if r["phase"] == "eval_suite") == 32
    assert sum(r["sms_segments"] for r in source("alerts")["monthly"].values()) == 5567
    assert sum(r["sms"] for r in source("alerts")["monthly"].values()) == 530
    api_settled = sum(
        (D(r["configured_cost_usd"]) for r in source("production")["usage_daily"] if r["status"] == "settled"), ZERO
    )
    prod_plus_seed = sum(
        (
            D(r["amount"])
            for r in costs
            if r["provider"] == "OpenAI" and (r["phase"] == "production" or "Settled migration seed" in r["formula"])
        ),
        ZERO,
    )
    assert abs(api_settled - prod_plus_seed) < D(".000000001")
    runs = source("experiments")["runs"]
    expected_router = sum(
        (
            D(r.get("artifact_cost_usd") or 0)
            for r in runs
            if r["artifact_cost_kind"] in ["provider_reported", "provider_reported_or_reserved"]
        ),
        ZERO,
    )
    assert abs(expected_router - verified_router) < D(".000000001")
    may_expected = (
        sum(r["input_tokens"] for r in runs if r["phase"] == "may_haiku_calibration")
        + 5 * sum(r["output_tokens"] for r in runs if r["phase"] == "may_haiku_calibration")
    ) / 1_000_000
    assert abs(
        D(may_expected)
        - sum(
            (D(r["amount"]) for r in costs if r["provider"] == "Anthropic" and r["phase"] == "testing_evaluation"), ZERO
        )
    ) < D(".000000001")
    for r in files["llm-by-model-phase.csv"]:
        matched = [
            c for c in costs if (c["provider"], c["model"], c["phase"]) == (r["provider"], r["model"], r["phase"])
        ]
        assert abs(sum((D(c["amount"]) for c in matched), ZERO) - D(r["total"])) < D(".000000001")
    assert abs(sum((D(r["amount"]) for r in costs if r["provider"] == "TypeSafe"), ZERO) - D("0.074125296")) < D(
        ".000000001"
    )
    for name in ["ledger.csv", "current-monthly.csv", "history-monthly.csv"]:
        assert (ROOT / name).read_bytes() == (AUDIT / name).read_bytes()
    html_text = (AUDIT / "report.html").read_text()
    assert html_text.startswith("<!doctype html>") and "PLN 200/month" in html_text
    print(
        f"PASS: {len(costs)} cost items, {len(ledger)} ledger records, 24 monthly currency rows; sums, date ranges, FX, allocations, seed/retry/duplicate controls and JSON/CSV parsing."
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        build()
    check()
