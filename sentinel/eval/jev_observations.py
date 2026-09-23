"""Unlabelled real-article observations: differences, never invented accuracy."""

import json
from collections import Counter
from pathlib import Path

from sentinel.eval.compare_models import make_article
from sentinel.eval.separate_metrics import aggregate_dimensions


def load_observations(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("mode") != "unlabelled":
        raise ValueError("Expected a version-1 unlabelled observation dataset")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Observation cases must be a nonempty list")
    seen = set()
    for case in cases:
        if "expected" in case or case.get("label_status") != "unlabelled" or case.get("split") != "observation":
            raise ValueError("Observation mode cannot contain expected answers or scored labels")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("Invalid or duplicate observation id")
        seen.add(case_id)
        if not isinstance(case.get("sequence_id"), str) or not case["sequence_id"]:
            raise ValueError("Observation requires an explicit chronological stream")
        if not isinstance(case.get("provenance"), dict):
            raise ValueError("Observation requires source provenance")
        for field in ("title", "summary", "source_name", "source_url", "source_type", "language"):
            if not isinstance(case.get("article", {}).get(field), str):
                raise ValueError(f"Missing observation article.{field}")
        make_article(case)  # Validates timezone-aware timestamps without a provider.
    return data


def summarize_observations(rows, cases):
    anchors = {}
    for row in rows:
        if row.get("event_id"):
            anchors.setdefault((row["provider"], row["event_id"]), row["case_id"])

    def identity(row, value):
        target = value.get("matched_event_id")
        return {
            "decision": value.get("decision"),
            "anchor_case_id": anchors.get((row["provider"], target), "unknown") if target else None,
        }

    def projection(row):
        data = row["data"]
        score = data["urgency_score"]
        return {
            "urgency": score,
            "tier": "call" if score >= 9 else "message" if score >= 5 else "silent",
            "military": data["is_military_event"],
            "affected_countries": sorted(data["affected_countries"]),
            "attack_countries": sorted(data["facts"]["attack_countries"]),
            "protection": data["facts"]["protection"],
            "status": data["facts"]["status"],
            "raw_identity": identity(row, data["incident_memory"]),
            "accepted_identity": identity(row, row["accepted_memory"]),
            "notification": row["notification"],
            "channels": sorted(row["channels"]),
        }

    report = {"mode": "unlabelled", "accuracy_measured": False, "release_eligible": False, "models": {}}
    for provider in ("jev", "luna"):
        group = [r for r in rows if r["provider"] == provider]
        report["models"][provider] = {
            "planned": len(cases),
            "observed": len(group),
            "errors": sum(bool(r.get("error")) for r in group),
            "simulated_notifications": dict(Counter(r.get("notification", "error") for r in group)),
            "simulated_channels": dict(Counter(c for r in group for c in r.get("channels", []))),
            "urgency_counts": dict(Counter(str(r["data"]["urgency_score"]) for r in group if not r.get("error"))),
            "language_counts": dict(Counter(r["language"] for r in group)),
            "summary_fallbacks": sum(bool(r.get("summary_fallback")) for r in group),
            "non_polish_summaries": sum(r.get("summary_polish") is False for r in group),
            "discarded_quote_answers": sum(
                len(r.get("diagnostics", {}).get("evidence_validation_errors", {})) for r in group
            ),
            "memory_gate_rejections": sum("model_decision" in r.get("accepted_memory", {}) for r in group),
            "latency": aggregate_dimensions(group)["latency"],
        }
    pairs = {}
    for row in rows:
        pairs.setdefault(row["case_id"], {})[row["provider"]] = row
    report["differences"] = []
    paired = 0
    for case_id, pair in pairs.items():
        if set(pair) != {"jev", "luna"} or any(r.get("error") for r in pair.values()):
            continue
        paired += 1
        a, b = projection(pair["jev"]), projection(pair["luna"])
        fields = [name for name in a if a[name] != b[name]]
        if fields:
            report["differences"].append({"case_id": case_id, "fields": fields, "jev": a, "luna": b})
    report["paired_cases"] = paired
    report["difference_counts"] = dict(Counter(field for d in report["differences"] for field in d["fields"]))
    report["interpretation"] = (
        "Agreement is not correctness. Without reviewed labels, missed/false/duplicate alerts and accuracy are not measured."
    )
    return report
