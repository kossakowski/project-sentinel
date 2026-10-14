#!/usr/bin/env python3
"""Build the dated Hetzner provider reconciliation without network access."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from calendar import monthrange
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "reports/2026-10-11"
PRIOR = ROOT / "reports/2026-10-11-reconciliation-update"
OUT = ROOT / "reports/2026-10-11-hetzner-provider"
BILLING_INPUT = Path("/tmp/sentinel-hetzner-provider-billing.json")
PLAN_INPUT = Path("/tmp/sentinel-hetzner-reconciliation-plan.json")
TRANSACTIONS_INPUT = Path("/tmp/sentinel-hetzner-transactions.json")
PDF_EVIDENCE_INPUT = Path("/tmp/sentinel-uia-pdf-financial-evidence.json")
PUBLISHED_BILLING = OUT / "evidence/billing.json"
PUBLISHED_PLAN = OUT / "evidence/reconciliation-plan.json"
PUBLISHED_TRANSACTIONS = OUT / "evidence/transactions.json"
PUBLISHED_PDF_EVIDENCE = OUT / "evidence/pdf-financial-evidence.json"

D = Decimal
Q = D("0.0000000001")
EXPECTED_AS_OF = "2026-10-11T11:05:17.463462+00:00"
EXPECTED_TOTALS = {
    "EUR": {
        "verified_cost": D("28.0400000000"),
        "estimated_additions": D("1.8078349269"),
        "reconstructed_total": D("29.8478349269"),
    },
    "USD": {
        "verified_cost": D("3.2630141728"),
        "estimated_additions": D("506.9716139914"),
        "reconstructed_total": D("510.2346281642"),
    },
    "PLN": {
        "verified_cost": D("133.9095636493"),
        "estimated_additions": D("1874.3814642596"),
        "reconstructed_total": D("2008.2910279089"),
    },
}


def dec(value: object) -> Decimal:
    return D(str(value))


def q(value: Decimal) -> Decimal:
    return value.quantize(Q)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=D)


def read_published_or_seed(published: Path, seed: Path) -> object:
    """Prefer repository evidence after the initial sanitized publication."""
    return read_json(published if published.exists() else seed)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    if not rows and fields is None:
        raise ValueError(f"Cannot infer fields for empty CSV: {path}")
    selected = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def iso_provider_date(value: str) -> str:
    return datetime.strptime(value, "%b %d, %Y").date().isoformat()


def month_end(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    return f"{month}-{monthrange(year, number)[1]:02d}"


def fx_lookup(fx_data: dict, currency: str, event_date: str) -> tuple[Decimal, str, str]:
    date = event_date[:10]
    series = next(item for item in fx_data["evidence"]["series"] if item["code"] == currency)
    eligible = [row for row in series["rates"] if row["effectiveDate"] <= date]
    if not eligible:
        raise AssertionError(f"No {currency} FX rate on or before {date}")
    row = max(eligible, key=lambda item: item["effectiveDate"])
    return dec(row["mid"]), row["effectiveDate"], row["no"]


def validate_underlying_sources(
    billing: dict,
    plan: dict,
    transactions: dict,
    pdf_evidence: list[dict],
) -> None:
    invoices = billing["invoices"]
    assert len(invoices) == 4
    assert billing["transaction_coverage"] == {
        "rendered_transactions": 8,
        "rendered_payments": 4,
        "rendered_invoice_balance_debits": 4,
        "next_or_load_more_controls_found": False,
        "source": "authenticated transaction page and UI Automation pagination check",
        "invoices_rendered": 4,
    }
    assert all(invoice["settled"] for invoice in invoices)
    assert all(invoice["project_marker"] == "Sentinel" for invoice in invoices)
    assert all(dec(invoice["gross_eur"]) == dec(invoice["net_eur"]) for invoice in invoices)
    assert all(dec(invoice["tax_eur"]) == 0 for invoice in invoices)
    assert all(
        dec(invoice["gross_eur"]) == sum((dec(line["amount_eur"]) for line in invoice["service_periods"]), D(0))
        for invoice in invoices
    )
    gross = sum((dec(invoice["gross_eur"]) for invoice in invoices), D(0))
    assert gross == D("28.04") == dec(billing["invoice_total_eur"])
    assert gross == dec(billing["provider_received_cash_eur"])
    assert billing.get("balance_difference_for_observed_transactions_eur", "0.00") == "0.00"
    assert billing["private_identifiers_exported"] is False

    amount_tokens = [token for line in transactions["financial_lines"] for token in line.get("amounts", [])]
    positive = sorted(dec(token.replace("€", "")) for token in amount_tokens if not token.startswith("-"))
    negative = sorted(dec(token.replace("-€", "")) for token in amount_tokens if token.startswith("-"))
    expected = sorted(dec(invoice["gross_eur"]) for invoice in invoices)
    assert positive == expected == negative
    transaction_dates = {
        iso_provider_date(token) for line in transactions["financial_lines"] for token in line.get("dates", [])
    }
    assert {
        value for invoice in invoices for value in (invoice["issue_date"], invoice["payment_date"])
    } <= transaction_dates

    pdf_by_issue = {
        datetime.strptime(item["issue_date_tokens"][0], "%d/%m/%Y").date().isoformat(): item for item in pdf_evidence
    }
    for invoice in invoices[:2]:
        item = pdf_by_issue[invoice["issue_date"]]
        assert item["text_layer_present"] is True
        assert set(item["products_present"]) == {"CX23", "IPv4"}
        lines = {
            period: dec(line["decimal_values"][0])
            for line in item["project_summary_lines"]
            for period in line["periods"]
        }
        expected_lines = {
            f"{line['month'][5:]}/{line['month'][:4]}": dec(line["amount_eur"]) for line in invoice["service_periods"]
        }
        assert lines == expected_lines

    assert plan["overall_result"]["status"] == "ARITHMETIC_READY_FOR_IMPLEMENTATION"
    assert plan["overall_result"]["all_provider_goal"] == "INCOMPLETE"


def build_cost_items(
    billing: dict,
    fx_data: dict,
    prior_history: list[dict[str, str]],
    recorded_at: str,
) -> list[dict[str, str]]:
    rows = read_csv(BASE / "cost-items.csv")
    invoice_by_month: dict[str, tuple[dict, dict]] = {}
    for invoice in billing["invoices"]:
        for line in invoice["service_periods"]:
            invoice_by_month[line["month"]] = (invoice, line)
    assert set(invoice_by_month) == {
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    }

    rebuilt: list[dict[str, str]] = []
    for row in rows:
        if row["provider"] != "Hetzner" or row["model"] != "CX23 + IPv4":
            rebuilt.append(row)
            continue
        month = row["usage_start"][:7]
        if month in invoice_by_month:
            invoice, line = invoice_by_month[month]
            rate, rate_date, table = fx_lookup(fx_data, "EUR", invoice["issue_date"])
            amount = dec(line["amount_eur"])
            value = q(amount * rate)
            updated = dict(row)
            updated.update(
                evidence_category="Verified",
                transaction_kind="invoice_accrual",
                usage_start=f"{month}-01",
                usage_end=month_end(month),
                recorded_at=recorded_at,
                amount=f"{amount:.10f}",
                low=f"{amount:.10f}",
                high=f"{amount:.10f}",
                allocation_fraction="1.0000000000",
                formula="Provider invoice project line; gross equals net and tax is zero",
                source="evidence/billing.json",
                assumptions=(
                    "Every observed charge line is marked Sentinel and is allocated 100% to the project. "
                    "The invoice service month is not evidence of activation on its first day. "
                    "Whether the physical server hosts unrelated workloads outside this invoice allocation remains unconfirmed."
                ),
                confidence="high",
                fx_valuation_date=invoice["issue_date"],
                fx_rate_date=rate_date,
                fx_table=table,
                fx_pln_per_unit=f"{rate:.10f}",
                pln_equivalent=f"{value:.10f}",
                low_pln=f"{value:.10f}",
                high_pln=f"{value:.10f}",
                confirmed_cash_amount="",
                unknown_adjustments=(
                    "Provider payment is recorded separately in cash-payments.csv and does not add economic cost. "
                    "Bank settlement amount and currency remain unknown."
                ),
            )
            rebuilt.append(updated)
            continue
        if month == "2026-10":
            prior_row = next(item for item in prior_history if item["month"] == month and item["currency"] == "EUR")
            amount = dec(prior_row["reconstructed_total"])
            rate, rate_date, table = fx_lookup(fx_data, "EUR", EXPECTED_AS_OF)
            value = q(amount * rate)
            updated = dict(row)
            updated.update(
                usage_end=EXPECTED_AS_OF,
                recorded_at=recorded_at,
                amount=f"{amount:.10f}",
                low=f"{amount:.10f}",
                high=f"{amount:.10f}",
                formula="Elapsed October hosting accrual through the unchanged production as-of time; capped below monthly invoice",
                source="Prior local production observation and latest Sentinel invoice rate",
                assumptions=(
                    "Same legacy instance and zero-tax profile are assumed through the as-of time. "
                    "Current cloud extras and exact resource creation date remain unverified."
                ),
                fx_valuation_date=EXPECTED_AS_OF,
                fx_rate_date=rate_date,
                fx_table=table,
                fx_pln_per_unit=f"{rate:.10f}",
                pln_equivalent=f"{value:.10f}",
                low_pln=f"{value:.10f}",
                high_pln=f"{value:.10f}",
            )
            rebuilt.append(updated)
            continue
        raise AssertionError(f"Unexpected Hetzner cost month: {month}")

    additions = read_csv(PRIOR / "estimated-additions.csv")
    api_delta = next(row for row in additions if row["provider"] == "OpenAI")
    assert api_delta["currency"] == "USD"
    assert api_delta["effective_start"] == "2026-10-11T00:38:49+00:00"
    assert api_delta["effective_end"] == EXPECTED_AS_OF
    api_amount = dec(api_delta["amount"])
    api_rate, api_rate_date, api_table = fx_lookup(fx_data, "USD", EXPECTED_AS_OF)
    api_pln = q(api_amount * api_rate)
    delta_row = {field: "" for field in rows[0]}
    delta_row.update(
        item_id="cost-130",
        provider="OpenAI",
        model="gpt-5.6-luna",
        phase="production",
        evidence_category="Estimated",
        transaction_kind="estimated_consumption",
        usage_start=api_delta["effective_start"],
        usage_end=api_delta["effective_end"],
        recorded_at=recorded_at,
        currency="USD",
        amount=f"{api_amount:.10f}",
        low=f"{api_amount:.10f}",
        high=f"{api_amount:.10f}",
        allocation_fraction="1.0000000000",
        formula=api_delta["calculation"],
        source=(
            "../2026-10-11-reconciliation-update/estimated-additions.csv; "
            "../2026-10-11-reconciliation-update/evidence/production-today.json; "
            "../2026-10-11/evidence/production.json"
        ),
        assumptions=(
            "Local configured-tariff delta for the active production period. "
            "The same saved token rates and conservative cache-write treatment are retained. "
            "This is not an authoritative OpenAI bill or account-wide charge."
        ),
        confidence=api_delta["confidence"],
        fx_valuation_date=EXPECTED_AS_OF,
        fx_rate_date=api_rate_date,
        fx_table=api_table,
        fx_pln_per_unit=f"{api_rate:.10f}",
        pln_equivalent=f"{api_pln:.10f}",
        low_pln=f"{api_pln:.10f}",
        high_pln=f"{api_pln:.10f}",
        confirmed_cash_amount="",
        unknown_adjustments="Provider credits tax funding balance and billed failures remain unknown; cash payment is not inferred.",
    )
    rebuilt.append(delta_row)

    for row in rebuilt:
        rate = dec(row["fx_pln_per_unit"])
        if row["evidence_category"] == "Verified":
            aggregation = dec(row["amount"]) * rate
        else:
            aggregation = dec(row["pln_equivalent"])
        aggregation_low = dec(row["low_pln"])
        aggregation_high = dec(row["high_pln"])
        row["pln_aggregation_basis"] = f"{aggregation:.20f}"
        row["low_pln_aggregation_basis"] = f"{aggregation_low:.20f}"
        row["high_pln_aggregation_basis"] = f"{aggregation_high:.20f}"
        row["pln_aggregation_adjustment"] = "0.00000000000000000000"
        row["low_pln_aggregation_adjustment"] = "0.00000000000000000000"
        row["high_pln_aggregation_adjustment"] = "0.00000000000000000000"

    assert len(rows) == 129
    assert len(rebuilt) == 130
    assert len({row["item_id"] for row in rebuilt}) == len(rebuilt)
    assert {row["usage_start"][:7] for row in rebuilt if row["provider"] == "Hetzner"} == {
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
    }
    return rebuilt


def aggregate_history(
    cost_items: list[dict[str, str]],
    prior_history: list[dict[str, str]],
    plan: dict,
    fx_data: dict,
    recorded_at: str,
) -> tuple[list[dict[str, str]], dict[str, dict[str, Decimal]]]:
    plan_rows = {row["month"]: row for row in plan["revised_monthly_economic_totals"]}
    for month, planned_month in plan_rows.items():
        month_rows = [row for row in cost_items if row["usage_start"][:7] == month]
        for category, target_field in (
            ("Verified", "verified"),
            ("Estimated", "estimated"),
        ):
            selected = [row for row in month_rows if row["evidence_category"] == category]
            if not selected:
                assert dec(planned_month["PLN"][target_field]) == 0
                continue
            current = sum((dec(row["pln_aggregation_basis"]) for row in selected), D(0))
            target = dec(planned_month["PLN"][target_field])
            adjustment = target - current
            assert abs(adjustment) <= Q * 5, (
                month,
                category,
                current,
                target,
                adjustment,
            )
            selected[-1]["pln_aggregation_adjustment"] = f"{adjustment:.20f}"
            selected[-1]["pln_aggregation_basis"] = (
                f"{current + adjustment - sum((dec(row['pln_aggregation_basis']) for row in selected[:-1]), D(0)):.20f}"
            )
        for basis_field, adjustment_field, target_field in (
            ("low_pln_aggregation_basis", "low_pln_aggregation_adjustment", "low"),
            (
                "high_pln_aggregation_basis",
                "high_pln_aggregation_adjustment",
                "high",
            ),
        ):
            current = sum((dec(row[basis_field]) for row in month_rows), D(0))
            target = dec(planned_month["PLN"][target_field])
            adjustment = target - current
            assert abs(adjustment) <= Q * 5, (
                month,
                target_field,
                current,
                target,
                adjustment,
            )
            month_rows[-1][adjustment_field] = f"{adjustment:.20f}"
            month_rows[-1][basis_field] = (
                f"{current + adjustment - sum((dec(row[basis_field]) for row in month_rows[:-1]), D(0)):.20f}"
            )

    buckets: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {
            "verified": D(0),
            "estimated": D(0),
            "low": D(0),
            "high": D(0),
        }
    )
    for row in cost_items:
        month = row["usage_start"][:7]
        category = "verified" if row["evidence_category"] == "Verified" else "estimated"
        native = buckets[(month, row["currency"])]
        amount = dec(row["amount"])
        native[category] += amount
        native["low"] += dec(row["low"])
        native["high"] += dec(row["high"])
        pln = buckets[(month, "PLN")]
        pln[category] += dec(row["pln_aggregation_basis"])
        pln["low"] += dec(row["low_pln_aggregation_basis"])
        pln["high"] += dec(row["high_pln_aggregation_basis"])

    template = {(row["month"], row["currency"]): row for row in prior_history}
    rows: list[dict[str, str]] = []
    for month in sorted({month for month, _ in buckets}):
        for currency in ("EUR", "USD", "PLN"):
            values = {key: q(value) for key, value in buckets[(month, currency)].items()}
            total = q(values["verified"] + values["estimated"])
            original = template[(month, currency)]
            rows.append(
                {
                    "month": month,
                    "currency": currency,
                    "value_basis": (
                        "currency_equivalent_not_bank_debit" if currency == "PLN" else "native_tariff_or_invoice_amount"
                    ),
                    "verified_cost": f"{values['verified']:.10f}",
                    "estimated_additions": f"{values['estimated']:.10f}",
                    "reconstructed_total": f"{total:.10f}",
                    "reconstructed_low": f"{values['low']:.10f}",
                    "reconstructed_high": f"{values['high']:.10f}",
                    "confirmed_cash_payments": "",
                    "cash_status": "Provider cash is reported by payment date in cash-payments.csv and is not assigned to service months.",
                    "effective_start": original["effective_start"],
                    "effective_end": original["effective_end"],
                    "recorded_at": recorded_at,
                    "note": (
                        "Economic cost is assigned to service or usage month. March through September hosting uses provider invoices "
                        "valued at issue-date FX; October hosting remains an accrual through the unchanged as-of time. "
                        "Verified invoice cost does not mean bank-verified cash."
                    ),
                }
            )

    for row in rows:
        planned = plan_rows[row["month"]][row["currency"]]
        assert dec(row["verified_cost"]) == dec(planned["verified"]), (
            row["month"],
            row["currency"],
            "verified",
            row["verified_cost"],
            planned["verified"],
        )
        assert dec(row["estimated_additions"]) == dec(planned["estimated"]), (
            row["month"],
            row["currency"],
            "estimated",
            row["estimated_additions"],
            planned["estimated"],
        )
        assert dec(row["reconstructed_total"]) == dec(planned["reconstructed"]), (
            row["month"],
            row["currency"],
            "reconstructed",
            row["reconstructed_total"],
            planned["reconstructed"],
        )
        if row["currency"] == "PLN":
            assert dec(row["reconstructed_low"]) == dec(planned["low"]), (
                row["month"],
                "low",
                row["reconstructed_low"],
                planned["low"],
            )
            assert dec(row["reconstructed_high"]) == dec(planned["high"]), (
                row["month"],
                "high",
                row["reconstructed_high"],
                planned["high"],
            )

    totals: dict[str, dict[str, Decimal]] = {}
    for currency in ("EUR", "USD", "PLN"):
        selected = [row for row in rows if row["currency"] == currency]
        totals[currency] = {
            field: q(sum((dec(row[field]) for row in selected), D(0)))
            for field in (
                "verified_cost",
                "estimated_additions",
                "reconstructed_total",
                "reconstructed_low",
                "reconstructed_high",
            )
        }
        for field, expected in EXPECTED_TOTALS[currency].items():
            assert totals[currency][field] == expected
    planned_pln = plan["revised_dated_pln_totals"]
    for field in (
        "verified_cost",
        "estimated_additions",
        "reconstructed_total",
        "reconstructed_low",
        "reconstructed_high",
    ):
        assert totals["PLN"][field] == dec(planned_pln[field])
    return rows, totals


def build_cash_rows(
    billing: dict,
    fx_data: dict,
    recorded_at: str,
) -> tuple[list[dict[str, str]], dict[str, dict[str, Decimal]]]:
    rows: list[dict[str, str]] = []
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"eur": D(0), "pln": D(0)})
    for invoice in sorted(billing["invoices"], key=lambda item: item["payment_date"]):
        amount = dec(invoice["gross_eur"])
        rate, rate_date, table = fx_lookup(fx_data, "EUR", invoice["payment_date"])
        equivalent = q(amount * rate)
        month = invoice["payment_date"][:7]
        rows.append(
            {
                "payment_date": invoice["payment_date"],
                "cash_month": month,
                "currency": "EUR",
                "provider_received_amount": f"{amount:.10f}",
                "fx_rate_date": rate_date,
                "fx_table": table,
                "fx_pln_per_unit": f"{rate:.10f}",
                "pln_equivalent_not_bank_debit": f"{equivalent:.10f}",
                "effective_start": invoice["payment_date"],
                "effective_end": invoice["payment_date"],
                "recorded_at": recorded_at,
                "evidence_category": "ProviderConfirmedCash",
                "cash_basis": "Provider Payment transaction matched by date and amount to a unique invoice",
                "source": "evidence/billing.json",
                "bank_settlement_status": "Unknown; provider-received EUR is not a bank debit or settlement FX",
            }
        )
        monthly[month]["eur"] += amount
        monthly[month]["pln"] += equivalent
    assert sum((dec(row["provider_received_amount"]) for row in rows), D(0)) == D("28.04")
    assert q(sum((dec(row["pln_equivalent_not_bank_debit"]) for row in rows), D(0))) == D("121.4076440000")
    assert {month: q(values["eur"]) for month, values in monthly.items()} == {
        "2026-04": D("1.1000000000"),
        "2026-07": D("13.4700000000"),
        "2026-10": D("13.4700000000"),
    }
    return rows, monthly


def sanitized_billing(billing: dict, recorded_at: str) -> dict:
    invoices = []
    for index, invoice in enumerate(sorted(billing["invoices"], key=lambda item: item["issue_date"]), start=1):
        invoices.append(
            {
                "anonymous_source": f"provider-invoice-{index}",
                "issue_date": invoice["issue_date"],
                "service_periods": invoice["service_periods"],
                "gross_eur": invoice["gross_eur"],
                "net_eur": invoice["net_eur"],
                "tax_eur": invoice["tax_eur"],
                "payment_date": invoice["payment_date"],
                "settled": invoice["settled"],
                "project_marker": invoice["project_marker"],
                "allocation_fraction": "1.0",
            }
        )
    return {
        "recorded_at": recorded_at,
        "effective_period": billing["effective_period"],
        "evidence_category": "VerifiedInvoiceAndProviderCash",
        "invoices": invoices,
        "invoice_total_eur": billing["invoice_total_eur"],
        "provider_received_cash_eur": billing["provider_received_cash_eur"],
        "balance_difference_for_observed_transactions_eur": billing.get(
            "balance_difference_for_observed_transactions_eur", "0.00"
        ),
        "bank_settlement_currency_or_amount": None,
        "cash_payment_basis": billing["cash_payment_basis"],
        "double_count_rule": billing["double_count_rule"],
        "transaction_coverage": billing["transaction_coverage"],
        "allocation": (
            "All observed invoice charge lines identify Sentinel and are allocated 100%. "
            "Whether the physical server hosts unrelated workloads outside the invoice allocation is unconfirmed."
        ),
        "caveats": billing["caveats"],
        "private_identifiers_exported": False,
    }


def sanitized_transactions(transactions: dict) -> dict:
    return {
        "recorded_at": transactions["recorded_at"],
        "anonymous_source": "authenticated provider transaction table",
        "financial_lines": transactions["financial_lines"],
        "private_identifiers_exported": False,
    }


def sanitized_pdf_evidence(pdf_evidence: list[dict]) -> list[dict]:
    result = []
    for index, item in enumerate(sorted(pdf_evidence, key=lambda row: row["issue_date_tokens"][0]), start=1):
        result.append(
            {
                "anonymous_source": f"text-layer-provider-pdf-{index}",
                "text_layer_present": item["text_layer_present"],
                "issue_date_tokens": item["issue_date_tokens"],
                "project_summary_lines": item["project_summary_lines"],
                "totals": item["totals"],
                "products_present": item["products_present"],
            }
        )
    return result


def sanitized_plan(plan: dict) -> dict:
    remaining_limits = [
        item
        for item in plan["remaining_limits"]
        if "pagination" not in item.lower() and "full-history coverage" not in item.lower()
    ]
    return {
        "schema_version": plan["schema_version"],
        "prepared_at_utc": plan["prepared_at_utc"],
        "scope": "Independent arithmetic validation for the published sanitized provider evidence.",
        "overall_result": plan["overall_result"],
        "accounting_method": plan["accounting_method"],
        "fx_table": plan["fx_table"],
        "revised_native_totals": plan["revised_native_totals"],
        "revised_monthly_economic_totals": plan["revised_monthly_economic_totals"],
        "revised_dated_pln_totals": plan["revised_dated_pln_totals"],
        "cash_timeline": plan["cash_timeline"],
        "remaining_limits": remaining_limits,
        "private_identifiers_exported": False,
    }


def build_report_html(
    recorded_at: str,
    totals: dict[str, dict[str, Decimal]],
    history: list[dict[str, str]],
    current: list[dict[str, str]],
    cash_rows: list[dict[str, str]],
    cash_monthly: dict[str, dict[str, Decimal]],
    billing: dict,
    model_rows: list[dict[str, str]],
    current_pln: Decimal,
) -> str:
    native_rows = "".join(
        "<tr>"
        f"<td>{currency}</td>"
        f"<td>{values['verified_cost']:.4f}</td>"
        f"<td>{values['estimated_additions']:.4f}</td>"
        f"<td>{values['reconstructed_total']:.4f}</td>"
        "</tr>"
        for currency, values in totals.items()
        if currency != "PLN"
    )
    cumulative = D(0)
    monthly_rows = []
    for row in (item for item in history if item["currency"] == "PLN"):
        cumulative += dec(row["reconstructed_total"])
        monthly_rows.append(
            "<tr>"
            f"<td>{escape(row['month'])}</td>"
            f"<td>{dec(row['verified_cost']):.2f}</td>"
            f"<td>{dec(row['estimated_additions']):.2f}</td>"
            f"<td>{dec(row['reconstructed_total']):.2f}</td>"
            f"<td>{cumulative:.2f}</td>"
            "</tr>"
        )
    current_rows = "".join(
        "<tr>"
        f"<td>{escape(row['service'])}</td>"
        f"<td>{escape(row['provider'])}</td>"
        f"<td>{escape(row['evidence_category'])}</td>"
        f"<td>{escape(row['currency'])}</td>"
        f"<td>{escape(row['normalized_monthly']) if row['normalized_monthly'] else 'Unknown'}</td>"
        f"<td>{escape(row['pln_equivalent']) if row['pln_equivalent'] else 'Unknown'}</td>"
        "</tr>"
        for row in current
    )
    invoice_rows = "".join(
        "<tr>"
        f"<td>{escape(', '.join(line['month'] for line in invoice['service_periods']))}</td>"
        f"<td>{escape(invoice['issue_date'])}</td>"
        f"<td>{dec(invoice['net_eur']):.2f}</td>"
        f"<td>{dec(invoice['tax_eur']):.2f}</td>"
        f"<td>{dec(invoice['gross_eur']):.2f}</td>"
        f"<td>{escape(invoice['payment_date'])}</td>"
        "</tr>"
        for invoice in sorted(billing["invoices"], key=lambda item: item["issue_date"])
    )
    cash_event_rows = "".join(
        "<tr>"
        f"<td>{escape(row['payment_date'])}</td>"
        f"<td>{dec(row['provider_received_amount']):.2f} EUR</td>"
        f"<td>{escape(row['fx_rate_date'])}</td>"
        f"<td>{dec(row['pln_equivalent_not_bank_debit']):.4f} PLN</td>"
        "</tr>"
        for row in cash_rows
    )
    cash_month_rows = "".join(
        f"<tr><td>{escape(month)}</td><td>{q(values['eur']):.2f} EUR</td><td>{q(values['pln']):.4f} PLN</td></tr>"
        for month, values in sorted(cash_monthly.items())
    )
    model_table = "".join(
        "<tr>"
        f"<td>{escape(row['provider'])}</td>"
        f"<td>{escape(row['model'])}</td>"
        f"<td>{escape(row['phase'])}</td>"
        f"<td>{escape(row['currency'])}</td>"
        f"<td>{dec(row['verified']):.4f}</td>"
        f"<td>{dec(row['estimated']):.4f}</td>"
        f"<td>{dec(row['total']):.4f}</td>"
        "</tr>"
        for row in model_rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel costs — provider-confirmed Hetzner reconciliation</title>
<style>
body{{font:16px/1.55 system-ui,sans-serif;max-width:1100px;margin:auto;padding:24px;color:#17202a}}
h1,h2{{line-height:1.2}} .notice{{background:#fff3cf;border-left:5px solid #d49b00;padding:16px}}
.ok{{background:#eaf7ee;border-left:5px solid #2e7d32;padding:16px}} .scroll{{overflow:auto}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}} th,td{{padding:8px;text-align:left;border-bottom:1px solid #d8dde3;vertical-align:top}}
th{{background:#f4f6f8}} code{{overflow-wrap:anywhere}} a{{overflow-wrap:anywhere}}
</style>
</head>
<body>
<h1>Sentinel costs: provider-confirmed Hetzner reconciliation</h1>
<p>Recorded at {escape(recorded_at)}. Production usage and the October hosting accrual remain measured through {escape(EXPECTED_AS_OF)}. Earlier dated reports are preserved.</p>
<p class="notice"><strong>The all-provider reconciliation remains incomplete.</strong> Historical totals are a mix of verified attributable costs and dated estimates. Verified invoice cost is not the same as bank-verified cash.</p>

<h2>Current monthly planning cost</h2>
<p>The quantified 30-day planning estimate remains <strong>PLN {current_pln:.2f}</strong>, with a <strong>PLN 200 monthly reserve</strong>. Unknown categories remain blank and sit outside this total.</p>
<div class="scroll"><table><thead><tr><th>Service</th><th>Provider</th><th>Evidence</th><th>Currency</th><th>Monthly</th><th>PLN equivalent</th></tr></thead><tbody>{current_rows}</tbody></table></div>

<h2>Historical economic cost</h2>
<p class="ok">Hetzner invoices now replace the earlier March–June hosting estimates. They are not added on top of those estimates.</p>
<div class="scroll"><table><thead><tr><th>Currency</th><th>Verified</th><th>Estimated</th><th>Reconstructed total</th></tr></thead><tbody>{native_rows}</tbody></table></div>
<p>Dated PLN equivalent: <strong>{totals["PLN"]["reconstructed_total"]:.2f} PLN</strong> = {totals["PLN"]["verified_cost"]:.2f} verified + {totals["PLN"]["estimated_additions"]:.2f} estimated. PLN values use issue-date FX for invoice cost and are not bank debits.</p>
<p>The cost-item snapshot has 130 unique rows. Its final row records the local OpenAI production tariff delta from 00:38:49 to the unchanged 11:05:17 as-of time. It is an estimate with dated repository evidence, not an authoritative API bill. Each row publishes its PLN aggregation basis: verified rows use the unrounded amount × FX product, while previously recorded estimate scenarios retain their dated ten-decimal valuation. Explicit aggregation-adjustment columns disclose any canonical monthly rounding correction, each no larger than 0.0000000005 PLN. Subtotals are quantized once, avoiding hidden overrides and cumulative verified-row rounding drift.</p>

<h2>Hetzner invoice coverage</h2>
<p>Four settled invoices cover calendar service periods March–September. Every observed invoice charge line identifies Sentinel; allocation is therefore 100% for these invoice lines. Calendar month start does not prove activation on that date. Physical co-hosting outside the invoice allocation remains unconfirmed.</p>
<div class="scroll"><table><thead><tr><th>Service months</th><th>Issue date</th><th>Net EUR</th><th>Tax EUR</th><th>Gross EUR</th><th>Provider payment date</th></tr></thead><tbody>{invoice_rows}</tbody></table></div>
<p>Invoice total: <strong>EUR 28.04</strong>. No separate backups, storage, traffic overage or other paid extras appear on the observed March–September invoices. Current cloud extras and the exact resource creation date remain unverified.</p>

<h2>Provider-confirmed cash, kept separate</h2>
<p>Hetzner reports receiving EUR 28.04. These payment events do not add to economic cost and are not assigned to service months. Their dated PLN equivalent is <strong>121.407644 PLN</strong>. Actual bank debit amount, settlement currency, bank FX and fees remain unknown.</p>
<div class="scroll"><table><thead><tr><th>Payment date</th><th>Provider received</th><th>FX date</th><th>Dated PLN equivalent</th></tr></thead><tbody>{cash_event_rows}</tbody></table></div>
<div class="scroll"><table><thead><tr><th>Cash month</th><th>Provider received</th><th>Dated PLN equivalent</th></tr></thead><tbody>{cash_month_rows}</tbody></table></div>

<h2>Month-by-month economic cost</h2>
<p>March includes a partial EUR 1.10 invoice for the calendar month, but this does not establish the activation date. April–June hosting is now verified. July–September was already invoice-verified. October remains an uninvoiced hosting accrual through the stated as-of time.</p>
<div class="scroll"><table><thead><tr><th>Month</th><th>Verified PLN</th><th>Estimated PLN</th><th>Total PLN</th><th>Cumulative PLN</th></tr></thead><tbody>{"".join(monthly_rows)}</tbody></table></div>
<ul>
<li>May remains dominated by reconstructed Twilio activity. Provider invoices, trial credits and retained-resource charges are unresolved.</li>
<li>The Apple Developer purchase is confirmed as 100% Sentinel, while USD 99 remains a list-price proxy because the actual amount, currency and date are unknown.</li>
<li>September includes the direct-provider migration and attributable testing. USD funding, credits, taxes and refunds remain unresolved.</li>
<li>October recurring cost uses the unchanged production measurement window; cash receipts are not mixed into this service-month view.</li>
</ul>

<h2>Model and phase costs</h2>
<p>This table is unchanged from the prior latest report and already contains the production delta. The new cost-item row makes the same delta explicit for reconciliation and is not added again here. The table reports attributable consumption or reconstruction, not provider funding cash.</p>
<div class="scroll"><table><thead><tr><th>Provider</th><th>Model</th><th>Phase</th><th>Currency</th><th>Verified</th><th>Estimated</th><th>Total</th></tr></thead><tbody>{model_table}</tbody></table></div>

<h2>Renewals and remaining gaps</h2>
<div class="scroll"><table><thead><tr><th>Item</th><th>Current treatment</th><th>What remains unknown</th></tr></thead><tbody>
<tr><td>Hetzner hosting</td><td>EUR 4.49/month planning amount; March–September invoices verified</td><td>Current extras, resource inventory, exact creation date and physical co-hosting</td></tr>
<tr><td>Apple Developer</td><td>Confirmed Sentinel purchase; USD 99 annual proxy and USD 8.25/month normalization</td><td>Actual settlement amount, currency, purchase date and renewal date</td></tr>
<tr><td>Twilio retained number</td><td>USD 4/month estimate with zero lower bound</td><td>Retention status, trial credit, rental charges and historical communications bill</td></tr>
<tr><td>Model providers</td><td>Attributable request cost or reconstruction</td><td>Account-wide funding, balances, credits, discounts, taxes, refunds and failed billing</td></tr>
<tr><td>CI, EAS, domains, email and monitoring</td><td>Unknown amounts excluded from total</td><td>Provider billing and project allocation</td></tr>
</tbody></table></div>
<p>No whole-account provider charge is assigned to Sentinel without project-level evidence. A dashboard/news date is not used as a server creation date.</p>

<h2>Files and checks</h2>
<ul>
<li><a href="history-monthly.csv">Historical monthly economic cost</a></li>
<li><a href="current-monthly.csv">Current normalized monthly planning cost</a></li>
<li><a href="cash-payments.csv">Provider-confirmed cash timeline</a></li>
<li><a href="cost-items.csv">Cost items with hosting reconciliation</a></li>
<li><a href="llm-by-model-phase.csv">Prior model and phase detail</a></li>
<li><a href="ledger.csv">42-row ledger snapshot</a></li>
<li><a href="summary.json">Machine-readable summary and validations</a></li>
<li><a href="evidence/billing.json">Sanitized provider invoice and transaction evidence</a></li>
<li><a href="evidence/transactions.json">Sanitized external transaction-table evidence</a></li>
<li><a href="evidence/pdf-financial-evidence.json">Sanitized text-layer PDF financial evidence</a></li>
<li><a href="evidence/reconciliation-plan.json">Sanitized independent arithmetic plan</a></li>
<li><a href="../2026-10-11-reconciliation-update/report.html">Prior latest reconciliation</a></li>
</ul>
<p>Checked from published invoice lines, transaction amounts and dates, text-layer PDF evidence, saved FX series and 130 cost records; then matched to the independent reconciliation plan. Duplicate IDs, active-period dates, cash/consumption separation and all target totals are asserted by the generator. Rebuild and check prefer these published sanitized sources and do not require temporary capture files.</p>
</body></html>
"""


def update_index() -> None:
    html = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Sentinel finance</title>
<h1>Sentinel finance</h1>
<p><a href="reports/2026-10-11-hetzner-provider/report.html">Latest: provider-confirmed Hetzner reconciliation, October 11, 2026</a></p>
<p><a href="reports/2026-10-11-reconciliation-update/report.html">Earlier current-month and cumulative reconciliation</a></p>
<p><a href="reports/2026-10-11-hetzner-email-check/report.html">Earlier Hetzner email and payment recheck</a></p>
<p><a href="reports/2026-10-11/report.html">Original October 11 cost audit and reconstruction</a></p>
<p><a href="reports/2026-10-11/netcup-attribution-scenario.html">Conditional unallocated hosting scenario</a></p>
<p><a href="reports/2026-10-11-coding-usage/report.html">Coding usage appendix: billing unresolved; conditional tariff scenario</a></p>
<p><a href="maintenance-policy.html">Proposed shared maintenance policy</a></p>
</html>
"""
    (ROOT / "index.html").write_text(html, encoding="utf-8")


def main(check_only: bool = False) -> dict:
    billing = read_published_or_seed(PUBLISHED_BILLING, BILLING_INPUT)
    plan = read_published_or_seed(PUBLISHED_PLAN, PLAN_INPUT)
    transactions = read_published_or_seed(PUBLISHED_TRANSACTIONS, TRANSACTIONS_INPUT)
    pdf_evidence = read_published_or_seed(PUBLISHED_PDF_EVIDENCE, PDF_EVIDENCE_INPUT)
    fx_data = read_json(BASE / "evidence/fx.json")
    prior_summary = read_json(PRIOR / "summary.json")
    prior_history = read_csv(PRIOR / "history-monthly.csv")
    recorded_at = billing["recorded_at"]
    assert recorded_at > prior_summary["recorded_at"]
    assert prior_summary["effective_end"] == EXPECTED_AS_OF

    validate_underlying_sources(billing, plan, transactions, pdf_evidence)
    cost_items = build_cost_items(billing, fx_data, prior_history, recorded_at)
    assert len(cost_items) == 130
    assert len({row["item_id"] for row in cost_items}) == 130
    history, totals = aggregate_history(cost_items, prior_history, plan, fx_data, recorded_at)
    cash_rows, cash_monthly = build_cash_rows(billing, fx_data, recorded_at)

    current = read_csv(PRIOR / "current-monthly.csv")
    for row in current:
        row["recorded_at"] = recorded_at
        if row["service"] == "CX23 + IPv4":
            row["assumptions"] = (
                "Observed invoice charge lines identify Sentinel and support 1.0 cost allocation. "
                "Physical co-hosting outside that invoice allocation remains unconfirmed; current extras are separate Unknown categories."
            )
    current_pln = q(
        sum(
            (dec(row["pln_equivalent"]) for row in current if row["pln_equivalent"]),
            D(0),
        )
    )
    assert current_pln == D("134.0871134266")
    unknown = [row["service"] for row in current if row["evidence_category"] == "Unknown"]
    assert unknown == prior_summary["unpriced_current_categories"]
    assert all(not row["normalized_monthly"] for row in current if row["evidence_category"] == "Unknown")

    ledger = read_csv(ROOT / "ledger.csv")
    assert len(ledger) == 42
    assert len({row["transaction_id"] for row in ledger}) == 42
    hetzner_ledger = [
        row
        for row in ledger
        if row["provider"] == "Hetzner" and row["transaction_kind"] == "invoice_accrual" and row["currency"] == "EUR"
    ]
    assert len(hetzner_ledger) == 4
    assert sum((dec(row["amount"]) for row in hetzner_ledger), D(0)) == D("28.04")
    assert sum((dec(row["confirmed_cash_amount"]) for row in hetzner_ledger), D(0)) == D("28.04")
    assert all(row["payment_status"] == "paid_provider_confirmed" for row in hetzner_ledger)
    assert all(not row["confirmed_cash_payments"] for row in history)

    model_rows = read_csv(PRIOR / "llm-by-model-phase.csv")
    summary = {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "as_of_utc": EXPECTED_AS_OF,
        "status": "PROVISIONAL_ALL_PROVIDER_RECONCILIATION_INCOMPLETE",
        "historical_basis": (
            "Economic cost by service/usage month. Hetzner March-September uses verified invoice lines "
            "valued at issue-date FX. Provider payments are a separate cash view and do not add cost."
        ),
        "historical": {
            currency: {field: f"{value:.10f}" for field, value in values.items()} for currency, values in totals.items()
        },
        "current_monthly_pln_equivalent": f"{current_pln:.10f}",
        "recommended_budget_pln": "200",
        "current_native": prior_summary["current_monthly"],
        "provider_confirmed_cash": {
            "currency": "EUR",
            "amount": "28.0400000000",
            "dated_pln_equivalent_not_bank_debit": "121.4076440000",
            "bank_settlement_amount_or_currency": None,
            "by_month": {
                month: {
                    "provider_received_eur": f"{q(values['eur']):.10f}",
                    "dated_pln_equivalent": f"{q(values['pln']):.10f}",
                }
                for month, values in sorted(cash_monthly.items())
            },
        },
        "hetzner": {
            "verified_invoice_eur": "28.0400000000",
            "verified_service_period": "2026-03-01 through 2026-09-30",
            "invoice_tax_eur": "0.0000000000",
            "allocation_fraction": "1.0000000000",
            "allocation_basis": "Every observed invoice charge line identifies Sentinel.",
            "allocation_limit": "Physical co-hosting outside the invoice allocation is unconfirmed.",
            "october_uninvoiced_accrual_eur": "1.8078349269",
        },
        "monthly_changes": [
            {
                key: row[key]
                for key in (
                    "month",
                    "verified_cost",
                    "estimated_additions",
                    "reconstructed_total",
                    "reconstructed_low",
                    "reconstructed_high",
                )
            }
            for row in history
            if row["currency"] == "PLN"
        ],
        "unpriced_current_categories": unknown,
        "renewals_and_gaps": [
            "Apple purchase is 100% Sentinel; USD 99 is a list-price proxy because actual settlement amount, currency and date are unknown.",
            "Twilio retained-number status, trial credit, rental and historical communications billing remain unresolved.",
            "Hetzner current extras, resource inventory, exact creation date and physical co-hosting remain unverified.",
            "API-provider account-wide funding, balances, credits, taxes, refunds and failed billing remain unresolved and unallocated.",
            "CI, EAS, domains, operational email, managed monitoring and paid source add-ons remain Unknown unless project-level billing appears.",
        ],
        "files": {
            "billing_evidence": "evidence/billing.json",
            "transaction_evidence": "evidence/transactions.json",
            "pdf_financial_evidence": "evidence/pdf-financial-evidence.json",
            "independent_arithmetic_plan": "evidence/reconciliation-plan.json",
            "cash": "cash-payments.csv",
            "ledger_snapshot": "ledger.csv",
            "history": "history-monthly.csv",
            "current": "current-monthly.csv",
            "cost_items": "cost-items.csv",
            "model_phase": "llm-by-model-phase.csv",
        },
        "validation": {
            "underlying_invoice_lines_verified": True,
            "underlying_transaction_amounts_and_dates_verified": True,
            "source_fx_and_cost_records_recomputed": True,
            "independent_plan_matches": True,
            "target_native_and_pln_totals_match": True,
            "cost_items": 130,
            "cost_item_ids_unique": True,
            "cost_item_pln_basis_is_explicit_and_quantized_once": True,
            "openai_active_delta_period": {
                "start": "2026-10-11T00:38:49+00:00",
                "end": EXPECTED_AS_OF,
            },
            "ledger_rows": 42,
            "ledger_transaction_ids_unique": True,
            "cash_not_added_to_economic_cost": True,
            "cash_not_allocated_to_service_months": True,
            "prior_model_phase_costs_unchanged": True,
            "production_as_of_unchanged": EXPECTED_AS_OF,
            "all_provider_goal_complete": False,
        },
    }

    if check_only:
        existing = read_json(OUT / "summary.json")
        assert existing == summary
        assert read_csv(OUT / "history-monthly.csv") == history
        assert read_csv(OUT / "current-monthly.csv") == current
        assert read_csv(OUT / "cash-payments.csv") == cash_rows
        assert read_csv(OUT / "ledger.csv") == ledger
        assert read_csv(OUT / "cost-items.csv") == cost_items
        assert read_csv(OUT / "llm-by-model-phase.csv") == model_rows
        assert read_json(PUBLISHED_BILLING) == sanitized_billing(billing, recorded_at)
        assert read_json(PUBLISHED_TRANSACTIONS) == sanitized_transactions(transactions)
        assert read_json(PUBLISHED_PDF_EVIDENCE) == sanitized_pdf_evidence(pdf_evidence)
        assert read_json(PUBLISHED_PLAN) == sanitized_plan(plan)
        assert read_csv(ROOT / "history-monthly.csv") == history
        assert read_csv(ROOT / "current-monthly.csv") == current
    else:
        (OUT / "evidence").mkdir(parents=True, exist_ok=True)
        (OUT / "evidence/billing.json").write_text(
            json.dumps(sanitized_billing(billing, recorded_at), indent=2) + "\n",
            encoding="utf-8",
        )
        PUBLISHED_TRANSACTIONS.write_text(
            json.dumps(sanitized_transactions(transactions), indent=2) + "\n",
            encoding="utf-8",
        )
        PUBLISHED_PDF_EVIDENCE.write_text(
            json.dumps(sanitized_pdf_evidence(pdf_evidence), indent=2) + "\n",
            encoding="utf-8",
        )
        PUBLISHED_PLAN.write_text(
            json.dumps(sanitized_plan(plan), indent=2) + "\n",
            encoding="utf-8",
        )
        write_csv(OUT / "cash-payments.csv", cash_rows)
        write_csv(OUT / "history-monthly.csv", history)
        write_csv(OUT / "current-monthly.csv", current)
        write_csv(OUT / "cost-items.csv", cost_items)
        shutil.copyfile(PRIOR / "llm-by-model-phase.csv", OUT / "llm-by-model-phase.csv")
        shutil.copyfile(ROOT / "ledger.csv", OUT / "ledger.csv")
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        report = build_report_html(
            recorded_at,
            totals,
            history,
            current,
            cash_rows,
            cash_monthly,
            billing,
            model_rows,
            current_pln,
        )
        (OUT / "report.html").write_text(report, encoding="utf-8")
        write_csv(ROOT / "history-monthly.csv", history)
        write_csv(ROOT / "current-monthly.csv", current)
        update_index()

    return {
        "recorded_at": recorded_at,
        "as_of_utc": EXPECTED_AS_OF,
        "historical": {
            currency: {field: f"{value:.10f}" for field, value in values.items() if field in EXPECTED_TOTALS[currency]}
            for currency, values in totals.items()
        },
        "provider_cash_eur": "28.0400000000",
        "provider_cash_pln_equivalent": "121.4076440000",
        "current_monthly_pln": f"{current_pln:.10f}",
        "all_provider_goal_complete": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(main(check_only=args.check), indent=2))
