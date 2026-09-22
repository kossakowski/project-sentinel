"""Prepare or run a local Jev/Luna comparison; offline unless --live is supplied."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv

from sentinel.classification.openai_provider import BudgetExceeded, ClassificationError, OpenAIProvider
from sentinel.classification.policy import messages, prompt_hash
from sentinel.classification.schema import CLASSIFICATION_SCHEMA
from sentinel.eval.clarified_policy import load_policy
from sentinel.eval.compare_models import inventory, load_dataset, make_article, make_config, parse_time
from sentinel.eval.jev_questions import VERSION, build_request, decode
from sentinel.eval.reference_history import ReferenceHistory
from sentinel.eval.separate_metrics import aggregate_dimensions, score_dimensions
from sentinel.eval.typesafe_client import TypeSafeEvalClient, check_size, encoded

MEASURED = (
    "urgency_exact_range",
    "urgency_action_band",
    "affected_countries",
    "attack_countries",
    "protection",
    "status",
    "raw_incident_identity",
    "error_free",
)
LIMITATIONS = [
    "Exploratory comparison, not a release gate or an estimate of real-world accuracy.",
    "Reference history uses prior annotated grouping and source text; no model-generated history.",
    "No runtime retrieval, alert delivery, summary/evidence quality, or exact update/escalation labels are scored.",
    "Luna retains its full production output schema; cost/latency are not an equal-output token benchmark.",
    "Jev confidence is distribution concentration, not a per-item correctness guarantee.",
    "Existing development/holdout fixtures have been seen before; fresh human-labelled data is still needed.",
]


def load_settings(path):
    settings = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or settings.get("version") != 1:
        raise ValueError("Expected version-1 Jev evaluation settings")
    endpoint = urlsplit(settings["endpoint"])
    if (
        (endpoint.scheme, endpoint.netloc, endpoint.path) != ("https", "api.typesafe.ai", "/v1/systemone")
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("Jev evaluation credentials may only be sent to the official endpoint")
    if not re.fullmatch(r"jev-\d+\.\d+\.\d+", settings["model"]):
        raise ValueError("Pin an explicit Jev model version, not latest/preview")
    for key in ("input_per_million", "request_token_limit", "state_question_token_limit", "timeout_seconds"):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid evaluation setting: {key}")
    threshold = settings["confidence_review_threshold"]
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise ValueError("Invalid confidence review threshold")
    countries = settings["attack_countries"]
    if not isinstance(countries, list) or not countries or len(countries) != len(set(countries)):
        raise ValueError("Expected a nonempty unique attack-country list")
    if any(not isinstance(c, str) or not re.fullmatch(r"[A-Z]{2}", c) for c in countries):
        raise ValueError("Expected ISO country codes")
    return settings


def prepare(cases, config, policy, settings):
    prepared = []
    for sequence in sorted({c["sequence_id"] for c in cases}):
        history = ReferenceHistory(
            config.classification.incident_memory.max_candidates,
            config.classification.incident_memory.evidence_per_event,
        )
        for case in sorted(
            (c for c in cases if c["sequence_id"] == sequence), key=lambda c: parse_time(c["article"]["fetched_at"])
        ):
            article = make_article(case)
            candidates = history.candidates()
            payload = build_request(article, candidates, policy, settings)
            check_size(payload, settings)
            prepared.append(
                {
                    "case": case,
                    "jev": payload,
                    "luna": messages(article, candidates, policy),
                    "prior_events": dict(history.case_events),
                }
            )
            history.add(case)  # Only after constructing the current request.
    return prepared


def score_row(item, provider, result):
    case, payload = item["case"], item["jev"]
    row = {
        **result,
        "provider": provider,
        "case_id": case["id"],
        "sequence_id": case["sequence_id"],
        "split": case["split"],
        "label_status": case["label_status"],
        "expected": case["expected"],
        "language": case["provenance"].get("content_language", case["article"]["language"]),
        "context_mode": "reference",
        "candidate_ids": [c["id"] for c in payload["state"]["remembered_incidents"]],
        "state_sha256": hashlib.sha256(encoded(payload["state"])).hexdigest(),
    }
    row["evaluation"] = score_dimensions(case, row, item["prior_events"])
    # Exclude unimplemented dimensions rather than treating placeholders as failures.
    row["evaluation"]["dimensions"] = {name: row["evaluation"]["dimensions"][name] for name in MEASURED}
    row["review_dimensions"] = [name for name, correct in row["evaluation"]["dimensions"].items() if correct is False]
    return row


async def evaluate(prepared, jev, luna, settings, checkpoint, cached=None):
    rows = []
    for number, item in enumerate(prepared):
        # Alternate order to avoid always measuring one service first.
        for provider in ("jev", "luna") if number % 2 == 0 else ("luna", "jev"):
            saved = (cached or {}).get((item["case"]["id"], provider))
            if saved is not None:
                row = score_row(item, provider, saved)
                rows.append(row)
                checkpoint(row)
                continue
            start = time.perf_counter()
            result = {}
            stop = False
            try:
                if provider == "jev":
                    result = await jev.request(item["jev"])
                    result["data"], result["diagnostics"] = decode(item["jev"], result["raw_response"], settings)
                else:
                    reply = await luna.request(
                        item["luna"], CLASSIFICATION_SCHEMA, purpose="classification", max_tokens=luna.config.max_tokens
                    )
                    result = {
                        "data": reply.data,
                        "request_sha256": reply.request_hash,
                        "response_id": reply.response_id,
                        "cost_usd": reply.cost_usd,
                        "usage": {
                            "prompt_tokens": reply.input_tokens,
                            "completion_tokens": reply.output_tokens,
                            "cached_input_tokens": reply.cached_tokens,
                        },
                    }
            except (ClassificationError, ValueError) as exc:
                # Our clients expose only safe error messages, never provider bodies or keys.
                result["error"] = str(exc)
                result["budget_stopped"] = isinstance(exc, BudgetExceeded)
                stop = True
            result["latency_seconds"] = time.perf_counter() - start
            row = score_row(item, provider, result)
            rows.append(row)
            checkpoint(row)
            if stop:
                return rows
    return rows


def summarize(rows, planned, threshold, planned_languages=None):
    def group_summary(group, expected_count):
        metrics = aggregate_dimensions(group)
        scored = [r for r in group if r["label_status"] != "disputed"]
        metrics["dimensions"] = {name: metrics["dimensions"][name] for name in MEASURED}
        # Reference mode has no transports; reporting zero delivery failures would mislead.
        return {
            "rows": len(group),
            "planned": expected_count,
            "dimensions": metrics["dimensions"],
            "labels": metrics["status_counts"],
            "latency": metrics["latency"],
            "critical_score_undercalls": metrics["flags"]["critical_score_undercall"],
            "critical_cases_with_errors": sum(bool(r.get("error")) and r["expected"]["critical"] for r in scored),
            "raw_wrong_merges": metrics["flags"]["raw_wrong_merge"],
            "unnecessary_notification_tier_scores": sum(
                not r.get("error") and r["expected"]["urgency_max"] < 5 and r["data"]["urgency_score"] >= 5
                for r in scored
            ),
            "critical_tier_overcalls": sum(
                not r.get("error") and r["expected"]["urgency_max"] < 9 and r["data"]["urgency_score"] >= 9
                for r in scored
            ),
            "errors": sum(bool(r.get("error")) for r in group),
            "settled_estimated_cost_usd": sum(r.get("cost_usd", 0) for r in group),
            "unknown_cost_rows": sum("cost_usd" not in r for r in group),
            "review_case_ids": [r["case_id"] for r in group if r["review_dimensions"]],
        }

    output = {}
    for provider in ("jev", "luna"):
        group = [r for r in rows if r["provider"] == provider]
        output[provider] = group_summary(group, planned)
        output[provider]["by_language"] = {
            language: group_summary(
                [r for r in group if r["language"] == language], (planned_languages or {}).get(language)
            )
            for language in sorted(set(planned_languages or {}) | {r["language"] for r in group})
        }
        if provider == "jev":
            output[provider]["high_confidence_errors"] = [
                {"case_id": r["case_id"], "dimension": dimension, "confidence": answer["confidence"]}
                for r in group
                if r["label_status"] != "disputed" and not r.get("error")
                for dimension, key in (
                    ("urgency_action_band", "urgency"),
                    ("protection", "protection"),
                    ("status", "status"),
                )
                for answer in [r["raw_response"]["answers"][key]]
                if r["evaluation"]["dimensions"].get(dimension) is False and answer["confidence"] >= threshold
            ]
    paired = {}
    for row in rows:
        paired.setdefault(row["case_id"], {})[row["provider"]] = row
    output["disagreements"] = []
    for case_id, pair in paired.items():
        if set(pair) != {"jev", "luna"} or any(r.get("error") for r in pair.values()):
            continue

        def projection(row):
            data = row["data"]
            return {
                "urgency_score": data["urgency_score"],
                "affected_countries": sorted(data["affected_countries"]),
                "facts": {
                    key: sorted(data["facts"][key]) if key == "attack_countries" else data["facts"][key]
                    for key in ("attack_countries", "protection", "status")
                },
                "memory": {key: data["incident_memory"].get(key) for key in ("decision", "matched_event_id")},
            }

        a, b = projection(pair["jev"]), projection(pair["luna"])
        if a != b:
            output["disagreements"].append({"case_id": case_id, "jev": a, "luna": b})
    output["release_eligible"] = False
    return output


def load_cached(source, manifest, prepared, settings):
    previous = json.loads((source / "manifest.json").read_text())
    for key in ("dataset_sha256", "policy_sha256", "settings", "luna_request_settings"):
        if previous[key] != manifest[key]:
            raise ValueError(f"Cannot resume after changing {key}")
    expected_requests = [{"case_id": i["case"]["id"], "jev": i["jev"], "luna": i["luna"]} for i in prepared]
    previous_requests = [json.loads(line) for line in (source / "requests.jsonl").read_text().splitlines()]
    if previous_requests != expected_requests:
        raise ValueError("Cannot resume: exact model requests changed")
    report = json.loads((source / "report.json").read_text())
    by_id = {i["case"]["id"]: i for i in prepared}
    cached = {}
    for line in (source / "results.jsonl").read_text().splitlines():
        row = json.loads(line)
        key = (row["case_id"], row["provider"])
        if key in cached or key[0] not in by_id or key[1] not in {"jev", "luna"}:
            raise ValueError("Invalid or duplicate cached result")
        if key[1] == "jev" and "raw_response" in row and "cost_usd" in row:
            row["data"], row["diagnostics"] = decode(by_id[key[0]]["jev"], row["raw_response"], settings)
            if row.get("error"):
                row["recovered_validation_error"] = row.pop("error")
                row.pop("budget_stopped", None)
        elif row.get("error") or "data" not in row:
            raise ValueError("Unrecoverable cached API error; review it before starting another paid run")
        row["reused_from"] = str(source)
        cached[key] = row
    return cached, report


async def run(args):
    dataset = load_dataset(args.dataset)
    if dataset.get("policy_version") != 2:
        raise ValueError("Jev comparison requires version-2 factual annotations")
    policy = load_policy(args.policy_file)
    settings = load_settings(args.settings)
    config = make_config(args.config)
    if config.classification.provider != "openai" or config.classification.model != "gpt-5.6-luna":
        raise ValueError("Comparison requires the configured direct Luna baseline")
    cases = [c for c in dataset["cases"] if args.split == "all" or c["split"] == args.split]
    if args.max_sequences is not None:
        if args.max_sequences < 1:
            raise ValueError("--max-sequences must be positive")
        sequences = sorted({c["sequence_id"] for c in cases})[: args.max_sequences]
        cases = [c for c in cases if c["sequence_id"] in sequences]
    if not cases or any(c["expected"].get("policy_pending") for c in cases):
        raise ValueError("Select nonempty cases with resolved policy labels")
    if not set(policy["monitored_countries"]) <= set(settings["attack_countries"]):
        raise ValueError("Jev attack-country vocabulary must include monitored countries")
    prepared = prepare(cases, config, policy, settings)
    manifest = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "live": args.live,
        "inventory": inventory({"cases": cases}),
        "new_api_calls": None if args.live else 0,
        "planned_api_calls": 2 * len(cases),
        "dataset": args.dataset,
        "dataset_sha256": hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
        "policy_sha256": prompt_hash(policy),
        "question_version": VERSION,
        "settings": settings,
        "luna_model": config.classification.model,
        "luna_reasoning": config.classification.reasoning_effort,
        "luna_request_settings": config.classification.model_dump(),
        "implementation_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("jev_comparison.py", "jev_questions.py", "typesafe_client.py")
        },
        "limitations": LIMITATIONS,
        "release_eligible": False,
        "jev_full_context_reservation_per_request_usd": settings["request_token_limit"]
        * settings["input_per_million"]
        / 1_000_000,
    }
    cached = {}
    source = Path(args.resume_from) if args.resume_from else None
    if source:
        cached, previous_report = load_cached(source, manifest, prepared, settings)
        manifest.update(resume_from=str(source), reused_responses=len(cached))
        manifest["planned_api_calls"] -= len(cached)
        if args.live and args.budget_usd is not None and args.budget_usd > previous_report["budget_usd"]:
            raise ValueError("Resume must preserve or lower the original combined spending cap")
    if args.live:
        if args.budget_usd is None or not math.isfinite(args.budget_usd) or not 0 < args.budget_usd <= 5:
            raise ValueError("Live comparison requires an explicit --budget-usd >0 and <=5")
        if not args.output:
            raise ValueError("Live comparison requires a new --output directory")
        if not args.allow_provisional and any(c["label_status"] != "approved" for c in cases):
            raise ValueError("Existing labels are not approved; use --allow-provisional for exploratory results")
        load_dotenv(Path.cwd() / ".env")
        if any(not os.environ.get(key, "").strip() for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY")):
            raise ValueError("Set TYPESAFE_API_KEY and OPENAI_API_KEY in the ignored project .env")
    output = Path(args.output) if args.output else None
    if output:
        output.mkdir(parents=True, exist_ok=False)
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with (output / "requests.jsonl").open("x", encoding="utf-8") as file:
            for item in prepared:
                file.write(
                    json.dumps(
                        {"case_id": item["case"]["id"], "jev": item["jev"], "luna": item["luna"]}, ensure_ascii=False
                    )
                    + "\n"
                )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not args.live:
        return 0
    baseline = deepcopy(config.classification)
    baseline.budget.ledger_path = str(output / "usage.db")
    baseline.budget.monthly_usd = args.budget_usd
    if source:
        # Carry forward all charges and reservations; the old evidence stays intact.
        with (
            closing(sqlite3.connect(f"file:{source / 'usage.db'}?mode=ro", uri=True)) as old,
            closing(sqlite3.connect(baseline.budget.ledger_path)) as new,
        ):
            old.backup(new)
    jev = TypeSafeEvalClient(settings, baseline.budget.ledger_path, args.budget_usd)
    luna = None
    rows = []
    try:
        luna = OpenAIProvider(baseline)
        with (output / "results.jsonl").open("x", encoding="utf-8") as journal:

            def checkpoint(row):
                rows.append(row)
                journal.write(json.dumps(row, ensure_ascii=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                print(f"{row['provider']} {row['case_id']}: {'ERROR' if row.get('error') else 'recorded'}", flush=True)

            await evaluate(prepared, jev, luna, settings, checkpoint, cached)
    finally:
        report = {
            "complete": len(rows) == 2 * len(cases) and not any(r.get("error") for r in rows),
            "budget_usd": args.budget_usd,
            "charged_or_reserved_estimate_usd": jev.ledger.total(),
            "reused_responses": sum("reused_from" in r for r in rows),
            "new_result_rows": sum("reused_from" not in r for r in rows),
            "limitations": LIMITATIONS,
            **summarize(
                rows,
                len(cases),
                settings["confidence_review_threshold"],
                Counter(c["provenance"].get("content_language", c["article"]["language"]) for c in cases),
            ),
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await jev.aclose()
        if luna is not None:
            await luna.aclose()
    print(f"Saved comparison to {output / 'report.json'}")
    return 0 if report["complete"] else 1


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dataset", default="tests/fixtures/model_comparison_v2_development.yaml")
    result.add_argument("--policy-file", default="tests/fixtures/benchmark_policy_v2.yaml")
    result.add_argument("--settings", default="tests/fixtures/jev_evaluation.yaml")
    result.add_argument("--config", default="config/config.yaml")
    result.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    result.add_argument("--max-sequences", type=int, help="Limit complete sequences, never truncate incident history")
    result.add_argument("--output", help="New directory for manifest, exact requests, results and spending ledger")
    result.add_argument("--resume-from", help="Reuse saved responses and carry spending into a new output directory")
    result.add_argument("--live", action="store_true")
    result.add_argument("--budget-usd", type=float)
    result.add_argument("--allow-provisional", action="store_true")
    return result


def main():
    try:
        code = asyncio.run(run(parser().parse_args()))
    except (ValueError, FileExistsError, ClassificationError) as exc:
        raise SystemExit(str(exc)) from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
