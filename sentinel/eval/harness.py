"""Eval harness: run the classifier against a labeled eval set and report metrics.

Usage (via CLI): ./run.sh --eval [PATH]

Output:
- Human-readable terminal report
- JSON file in data/eval/eval-<timestamp>.json for tracking over time

Eval-set schema: see tests/fixtures/eval_set.yaml.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

import yaml

from sentinel.classification.classifier import Classifier
from sentinel.config import SentinelConfig
from sentinel.models import Article, ClassificationResult

MONITORED_COUNTRIES = {"PL", "LT", "LV", "EE"}

# Haiku 4.5 pricing (USD per million tokens)
HAIKU_INPUT_PRICE_PER_M = 0.80
HAIKU_OUTPUT_PRICE_PER_M = 4.00


def _action_for_urgency(urgency: int, has_monitored_country: bool) -> str:
    """Derive the alert action tier from classifier output alone.

    Phone calls require urgency >= 9 AND the article to name a monitored country
    as the target. SMS covers 5-8. Everything else is log-only.

    Note: the live system also requires source corroboration before a phone call.
    The eval can't check that — it tests the classifier in isolation.
    """
    if urgency >= 9 and has_monitored_country:
        return "phone_call"
    if urgency >= 5:
        return "sms"
    return "log_only"


@dataclass
class EvalCase:
    id: str
    input_title: str
    input_summary: str
    input_source_name: str
    input_source_type: str
    input_language: str
    expected_is_military_event: bool
    expected_urgency_min: int
    expected_urgency_max: int
    expected_action: str
    expected_affected_countries: list[str] | None = None
    expected_affected_countries_must_not_contain: list[str] | None = None
    expected_aggressor: str | None = None
    expected_aggressor_any_of: list[str] | None = None
    expected_event_type_any_of: list[str] | None = None
    failure_mode: str = "other"
    audit_source: str | None = None
    notes: str | None = None
    haiku_output: dict | None = None


@dataclass
class CaseResult:
    case_id: str
    failure_mode: str
    actual: dict
    expected_action: str
    actual_action: str
    checks: dict[str, bool]
    overall_pass: bool
    error: str | None = None


@dataclass
class EvalReport:
    started_at: str
    finished_at: str
    duration_seconds: float
    eval_set_path: str
    eval_set_count: int
    model: str
    case_results: list[CaseResult]
    metrics: dict
    cost_estimate_usd: float


def load_eval_set(path: str) -> list[EvalCase]:
    """Load and validate eval set YAML.

    Accepts two layouts:
      flat:    top-level list, each case has headline/source/language at root
      nested:  top-level dict with 'cases', each case has input/expected nested
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Empty eval set: {path}")

    if isinstance(data, list):
        raw_cases = data
    elif isinstance(data, dict):
        raw_cases = data.get("cases", [])
    else:
        raise ValueError(f"Unexpected YAML root type in {path}: {type(data).__name__}")

    if not raw_cases:
        raise ValueError(f"No cases found in {path}")

    return [_parse_case(raw) for raw in raw_cases]


def _parse_case(raw: dict) -> EvalCase:
    """Parse one raw dict into an EvalCase. Supports flat or nested schema."""
    if "input" in raw:
        inp = raw["input"]
        title = inp["title"]
        summary = inp.get("summary")
        source_name = inp["source_name"]
        source_type = inp.get("source_type", "test")
        language = inp["language"]
    else:
        title = raw["headline"]
        summary = raw.get("summary")
        source_name = raw["source"]
        source_type = raw.get("source_type", "test")
        language = raw["language"]

    if summary is None or summary == "":
        summary = title

    exp = raw["expected"]

    event_type_any_of = exp.get("event_type_any_of")
    if event_type_any_of is None and exp.get("event_type"):
        event_type_any_of = [exp["event_type"]]

    return EvalCase(
        id=raw["id"],
        input_title=title,
        input_summary=summary,
        input_source_name=source_name,
        input_source_type=source_type,
        input_language=language,
        expected_is_military_event=exp["is_military_event"],
        expected_urgency_min=exp["urgency_min"],
        expected_urgency_max=exp["urgency_max"],
        expected_action=exp["expected_action"],
        expected_affected_countries=exp.get("affected_countries"),
        expected_affected_countries_must_not_contain=exp.get("affected_countries_must_not_contain"),
        expected_aggressor=exp.get("aggressor"),
        expected_aggressor_any_of=exp.get("aggressor_any_of"),
        expected_event_type_any_of=event_type_any_of,
        failure_mode=raw.get("failure_mode", "other"),
        audit_source=raw.get("audit_date") or raw.get("audit_source"),
        notes=raw.get("notes"),
        haiku_output=raw.get("haiku_output"),
    )


def _make_article(case: EvalCase) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_name=case.input_source_name,
        source_url=f"https://eval.sentinel/{uuid4().hex[:8]}",
        source_type=case.input_source_type,
        title=case.input_title,
        summary=case.input_summary,
        language=case.input_language,
        published_at=now,
        fetched_at=now,
    )


def _check_case(case: EvalCase, result: ClassificationResult) -> CaseResult:
    checks: dict[str, bool] = {}

    checks["is_military_event"] = result.is_military_event == case.expected_is_military_event
    checks["urgency_in_range"] = case.expected_urgency_min <= result.urgency_score <= case.expected_urgency_max

    if case.expected_affected_countries is not None:
        checks["affected_countries_match"] = sorted(result.affected_countries) == sorted(
            case.expected_affected_countries
        )
    if case.expected_affected_countries_must_not_contain is not None:
        forbidden = set(case.expected_affected_countries_must_not_contain)
        checks["affected_countries_no_forbidden"] = not (forbidden & set(result.affected_countries))

    if case.expected_aggressor is not None:
        checks["aggressor_match"] = result.aggressor == case.expected_aggressor
    if case.expected_aggressor_any_of is not None:
        checks["aggressor_in_set"] = result.aggressor in case.expected_aggressor_any_of

    if case.expected_event_type_any_of is not None:
        checks["event_type_in_set"] = result.event_type in case.expected_event_type_any_of

    has_monitored = bool(set(result.affected_countries) & MONITORED_COUNTRIES)
    actual_action = _action_for_urgency(result.urgency_score, has_monitored)
    checks["action_match"] = actual_action == case.expected_action

    return CaseResult(
        case_id=case.id,
        failure_mode=case.failure_mode,
        actual={
            "is_military_event": result.is_military_event,
            "event_type": result.event_type,
            "urgency_score": result.urgency_score,
            "affected_countries": result.affected_countries,
            "aggressor": result.aggressor,
            "confidence": result.confidence,
            "summary_pl": result.summary_pl,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
        expected_action=case.expected_action,
        actual_action=actual_action,
        checks=checks,
        overall_pass=all(checks.values()),
    )


async def run_eval(eval_set_path: str, config: SentinelConfig) -> EvalReport:
    """Load eval set, run classifier on each case, return a structured report."""
    started_at = datetime.now(UTC)

    cases = load_eval_set(eval_set_path)
    classifier = Classifier(config)
    case_results: list[CaseResult] = []

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.id}", file=sys.stderr)
        article = _make_article(case)
        try:
            result = await classifier.classify(article)
            case_results.append(_check_case(case, result))
        except Exception as e:
            case_results.append(
                CaseResult(
                    case_id=case.id,
                    failure_mode=case.failure_mode,
                    actual={},
                    expected_action=case.expected_action,
                    actual_action="error",
                    checks={},
                    overall_pass=False,
                    error=str(e),
                )
            )

    finished_at = datetime.now(UTC)
    metrics = compute_metrics(case_results)
    cost = compute_cost(case_results)

    return EvalReport(
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=(finished_at - started_at).total_seconds(),
        eval_set_path=eval_set_path,
        eval_set_count=len(cases),
        model=config.classification.model,
        case_results=case_results,
        metrics=metrics,
        cost_estimate_usd=cost,
    )


def compute_metrics(results: list[CaseResult]) -> dict:
    """Aggregate metrics across all case results."""
    n = len(results)
    if n == 0:
        return {}

    check_keys: set[str] = set()
    for r in results:
        check_keys.update(r.checks.keys())

    per_check: dict[str, dict] = {}
    for key in sorted(check_keys):
        applicable = [r for r in results if key in r.checks]
        if not applicable:
            continue
        passed = sum(1 for r in applicable if r.checks[key])
        per_check[key] = {
            "passed": passed,
            "total": len(applicable),
            "rate": passed / len(applicable),
        }

    overall_passed = sum(1 for r in results if r.overall_pass)

    actions = ["phone_call", "sms", "log_only"]
    confusion: dict[str, dict[str, int]] = {a: {b: 0 for b in actions + ["error"]} for a in actions}
    for r in results:
        if r.expected_action in confusion:
            target = r.actual_action if r.actual_action in actions else "error"
            confusion[r.expected_action][target] += 1

    by_mode: dict[str, dict] = {}
    for r in results:
        d = by_mode.setdefault(r.failure_mode, {"passed": 0, "total": 0})
        d["total"] += 1
        if r.overall_pass:
            d["passed"] += 1
    for mode in by_mode:
        t = by_mode[mode]["total"]
        by_mode[mode]["rate"] = by_mode[mode]["passed"] / t if t else 0.0

    return {
        "total_cases": n,
        "overall_passed": overall_passed,
        "overall_pass_rate": overall_passed / n,
        "per_check": per_check,
        "action_confusion": confusion,
        "per_failure_mode": by_mode,
    }


def compute_cost(results: list[CaseResult]) -> float:
    total_input = sum(r.actual.get("input_tokens", 0) or 0 for r in results)
    total_output = sum(r.actual.get("output_tokens", 0) or 0 for r in results)
    return (total_input * HAIKU_INPUT_PRICE_PER_M + total_output * HAIKU_OUTPUT_PRICE_PER_M) / 1_000_000


def format_report(report: EvalReport) -> str:
    """Render a human-readable terminal report."""
    lines = []
    sep = "=" * 80
    lines.append(sep)
    lines.append("Project Sentinel — Classification Eval Report")
    lines.append(sep)
    lines.append(f"Eval set:    {report.eval_set_path} ({report.eval_set_count} cases)")
    lines.append(f"Model:       {report.model}")
    lines.append(f"Duration:    {report.duration_seconds:.1f}s")
    lines.append(f"Cost:        ${report.cost_estimate_usd:.4f}")
    lines.append("")

    m = report.metrics
    lines.append(f"Overall:     {m['overall_passed']}/{m['total_cases']} passed ({m['overall_pass_rate'] * 100:.1f}%)")
    lines.append("")

    actions = ["phone_call", "sms", "log_only", "error"]
    lines.append("Action confusion matrix (rows=expected, cols=actual):")
    lines.append("  expected\\actual  " + "  ".join(f"{a:>11}" for a in actions))
    for exp_action in ["phone_call", "sms", "log_only"]:
        row = m["action_confusion"][exp_action]
        lines.append(f"  {exp_action:>16}  " + "  ".join(f"{row[a]:>11}" for a in actions))
    lines.append("")

    lines.append("Per-check pass rates:")
    for key, d in m["per_check"].items():
        lines.append(f"  {key:<40}  {d['passed']:>3}/{d['total']:>3}  {d['rate'] * 100:>5.1f}%")
    lines.append("")

    lines.append("Per failure-mode pass rates:")
    for mode, d in sorted(m["per_failure_mode"].items()):
        lines.append(f"  {mode:<40}  {d['passed']:>3}/{d['total']:>3}  {d['rate'] * 100:>5.1f}%")
    lines.append("")

    failures = [r for r in report.case_results if not r.overall_pass]
    if failures:
        lines.append(f"Failed cases ({len(failures)}):")
        for r in failures:
            failed_checks = [k for k, v in r.checks.items() if not v]
            lines.append(f"  {r.case_id}")
            lines.append(f"    failure_mode: {r.failure_mode}")
            lines.append(f"    expected_action: {r.expected_action} | actual: {r.actual_action}")
            if r.error:
                lines.append(f"    ERROR: {r.error}")
            else:
                lines.append(f"    failed: {', '.join(failed_checks)}")
                lines.append(
                    f"    actual: urgency={r.actual.get('urgency_score')}  "
                    f"countries={r.actual.get('affected_countries')}  "
                    f"aggressor={r.actual.get('aggressor')}  "
                    f"conf={r.actual.get('confidence')}"
                )
            lines.append("")

    lines.append(sep)
    return "\n".join(lines)


def save_report_json(report: EvalReport, output_dir: str = "data/eval") -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.fromisoformat(report.started_at).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(output_dir, f"eval-{timestamp}.json")

    serializable = {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": report.duration_seconds,
        "eval_set_path": report.eval_set_path,
        "eval_set_count": report.eval_set_count,
        "model": report.model,
        "metrics": report.metrics,
        "cost_estimate_usd": report.cost_estimate_usd,
        "case_results": [asdict(r) for r in report.case_results],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    return path
