"""Replay a finished model-context eval report through current runtime logic.

This module is deliberately offline.  It never imports or constructs the paid
eval client: saved raw completions are released only after the current request
messages reproduce the request hash stored in the source report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sentinel.eval import compare_models
from sentinel.eval.clarified_policy import prompt_hash
from sentinel.models import Event

RAW_COMPLETION_FIELDS = (
    "data",
    "error",
    "error_kind",
    "http_status",
    "usage",
    "cost_usd",
    "reserved_usd",
    "latency_seconds",
    "request_id",
    "requested_model",
    "model",
    "provider",
    "finish_reason",
    "reasoning",
    "reasoning_mode",
    "provider_latency_seconds",
    "budget_stopped",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _messages_sha256(messages: Sequence[Mapping]) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _require_mapping(value, message: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _validate_policy(policy) -> dict:
    policy = dict(_require_mapping(policy, "Source report has no resolved evaluation_policy"))
    if policy.get("version") != 2 or policy.get("scope") != "evaluation_only":
        raise ValueError("Source report evaluation_policy must be evaluation-only version 2")
    if policy.get("status") != "resolved":
        raise ValueError("Source report evaluation_policy is not resolved")
    if policy.get("near_border_strike") not in {"awareness", "log_only", "critical"}:
        raise ValueError("Source report evaluation_policy has no resolved near_border_strike choice")
    if policy.get("neutralised_drone") not in {"current_danger", "original_severity"}:
        raise ValueError("Source report evaluation_policy has no resolved neutralised_drone choice")
    return policy


class CachedCompletion:
    """A defensive copy of only the provider/request result fields."""

    def __init__(self, source_row: Mapping) -> None:
        self._raw = {name: deepcopy(source_row.get(name)) for name in RAW_COMPLETION_FIELDS}

    def to_dict(self) -> dict:
        return deepcopy(self._raw)


class CachedClient:
    """Bounded response queue which proves every current model input is identical."""

    def __init__(self, model: str, source_rows: Sequence[Mapping]) -> None:
        self.model = model
        self.source_rows = list(source_rows)
        self.calls = 0

    async def complete(self, *, model_id: str, messages: list[dict], json_schema: dict) -> CachedCompletion:
        del json_schema  # The saved report authenticates the messages, not a provider schema echo.
        if self.calls >= len(self.source_rows):
            raise ValueError(f"Cached response queue exhausted for {self.model}")

        row = self.source_rows[self.calls]
        case_id = row.get("case_id", f"request-{self.calls + 1}")
        expected_model = row.get("requested_model") or self.model
        if model_id != self.model or expected_model != self.model:
            raise ValueError(
                f"Cached model mismatch for {case_id}: replay={model_id!r}, "
                f"report={expected_model!r}, section={self.model!r}"
            )

        expected_hash = row.get("request_sha256")
        actual_hash = _messages_sha256(messages)
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise ValueError(
                f"Cached request hash mismatch for {self.model} case {case_id}: "
                f"current={actual_hash}, saved={expected_hash!r}"
            )

        self.calls += 1
        return CachedCompletion(row)

    def assert_exhausted(self) -> None:
        if self.calls != len(self.source_rows):
            raise ValueError(
                f"Cached responses not fully consumed for {self.model}: "
                f"used={self.calls}, saved={len(self.source_rows)}"
            )


class EventIdQueue:
    """Supply only the Event IDs created during the original model run."""

    def __init__(self, source_rows: Sequence[Mapping]) -> None:
        seen: set[str] = set()
        ordered: list[str] = []
        for row in source_rows:
            event_id = row.get("event_id")
            if event_id is None:
                continue
            if not isinstance(event_id, str) or not event_id:
                raise ValueError(f"Invalid saved event_id in case {row.get('case_id')}")
            if event_id not in seen:
                seen.add(event_id)
                ordered.append(event_id)
        self._ids = deque(ordered)
        self.total = len(ordered)

    def construct(self, **kwargs) -> Event:
        if not self._ids:
            raise ValueError("Runtime created more events than the source report")
        return Event(id=self._ids.popleft(), **kwargs)

    def assert_exhausted(self, model: str) -> None:
        if self._ids:
            raise ValueError(
                f"Runtime created fewer events than the source report for {model}: "
                f"{len(self._ids)} of {self.total} saved event IDs remain"
            )


def _ordered_case_ids(cases: Sequence[dict]) -> list[str]:
    result: list[str] = []
    for sequence in sorted({case["sequence_id"] for case in cases}):
        ordered = sorted(
            (case for case in cases if case["sequence_id"] == sequence),
            key=lambda case: compare_models.parse_time(case["article"]["fetched_at"]),
        )
        result.extend(case["id"] for case in ordered)
    return result


def _validate_source_rows(model: str, section: Mapping, cases: Sequence[dict]) -> list[Mapping]:
    rows = section.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Source report model {model!r} has no cached cases")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError(f"Source report model {model!r} has an invalid case row")

    expected_ids = _ordered_case_ids(cases)
    actual_ids = [row.get("case_id") for row in rows]
    if actual_ids != expected_ids[: len(rows)]:
        raise ValueError(f"Source report case order does not match the dataset for {model}")
    if len(rows) > len(expected_ids):
        raise ValueError(f"Source report contains more cases than the dataset for {model}")
    if len(rows) < len(expected_ids) and not rows[-1].get("budget_stopped"):
        raise ValueError(f"Source report is incomplete without a terminal budget stop for {model}")
    return rows


def _preflight(report_path: Path, dataset_path: Path, config_path: Path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report = _require_mapping(report, "Source report must be a JSON object")
    if report.get("run_finished") is not True:
        raise ValueError("Source report is unfinished; cached replay is refused")
    if report.get("context_mode") != "model":
        raise ValueError("Cached runtime replay requires source context_mode=model")

    saved_dataset_hash = report.get("dataset_sha256")
    current_dataset_hash = _sha256(dataset_path)
    if current_dataset_hash != saved_dataset_hash:
        raise ValueError(f"Dataset SHA-256 mismatch: current={current_dataset_hash}, saved={saved_dataset_hash!r}")
    dataset = compare_models.load_dataset(str(dataset_path))

    policy = _validate_policy(report.get("evaluation_policy"))
    current_prompt_hash = prompt_hash(policy)
    if current_prompt_hash != report.get("prompt_sha256"):
        raise ValueError(
            f"Prompt SHA-256 mismatch: policy={current_prompt_hash}, saved={report.get('prompt_sha256')!r}"
        )

    config = compare_models.make_config(str(config_path))
    classification = config.classification.model_dump()
    alert_levels = {name: level.model_dump() for name, level in config.alerts.urgency_levels.items()}
    if classification != report.get("classification_config"):
        raise ValueError("Current make_config classification settings differ from the source report")
    if alert_levels != report.get("alert_levels"):
        raise ValueError("Current make_config alert levels differ from the source report")

    models = _require_mapping(report.get("models"), "Source report has no model results")
    if not models:
        raise ValueError("Source report has no model results")
    prepared = {}
    for model, section in models.items():
        if not isinstance(model, str) or not model:
            raise ValueError("Source report has an invalid model id")
        prepared[model] = _validate_source_rows(
            model,
            _require_mapping(section, f"Source report model {model!r} is invalid"),
            dataset["cases"],
        )
    return report, dataset, policy, config, classification, alert_levels, prepared


async def replay_report(
    *, report_path: Path, dataset_path: Path, config_path: Path, output_path: Path
) -> tuple[int, dict]:
    """Replay one immutable source report and write one derived offline report."""

    if output_path.exists():
        raise ValueError(f"Report already exists; refusing to overwrite: {output_path}")
    source_hash = _sha256(report_path)
    report, dataset, policy, config, classification, alert_levels, model_rows = _preflight(
        report_path, dataset_path, config_path
    )

    started_at = datetime.now(UTC)
    derived_models: dict[str, dict] = {}
    for model, source_rows in model_rows.items():
        client = CachedClient(model, source_rows)
        event_ids = EventIdQueue(source_rows)
        with patch("sentinel.classification.corroborator.Event", new=event_ids.construct):
            rows = await compare_models.replay(dataset["cases"], model, client, config, policy=policy)
        client.assert_exhausted()
        event_ids.assert_exhausted(model)
        for row in rows:
            row["cached_response"] = True
            row["original_cost_and_timing_evidence"] = True
        derived_models[model] = {
            "summary": compare_models.summarize_v2(rows, len(dataset["cases"])),
            "cases": rows,
        }

    finished_at = datetime.now(UTC)
    original_rows = [row for rows in model_rows.values() for row in rows]
    derived = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "run_finished": True,
        "cached_offline": True,
        "source_report": str(report_path.resolve()),
        "source_report_sha256": source_hash,
        "dataset": str(dataset_path),
        "dataset_sha256": report["dataset_sha256"],
        "prompt_sha256": report["prompt_sha256"],
        "classification_config": classification,
        "alert_levels": alert_levels,
        "evaluation_policy": policy,
        "context_mode": "model",
        "mode": "cached/offline replay through current memory, grouping, and alert logic; no real transports",
        "new_api_requests": 0,
        "new_api_cost_usd": 0.0,
        "original_api_requests_replayed": len(original_rows),
        "original_reported_cost_usd": sum(row.get("cost_usd") or 0 for row in original_rows),
        "evidence_note": (
            "Per-case provider, usage, cost, and latency fields are reused from the source report as "
            "historical evidence; they were not charged or measured again."
        ),
        "models": derived_models,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(derived, ensure_ascii=False, indent=2))
    has_errors = any(row.get("error") for section in derived_models.values() for row in section["cases"])
    return int(has_errors), derived


async def main_async(args: argparse.Namespace) -> int:
    code, derived = await replay_report(
        report_path=Path(args.report),
        dataset_path=Path(args.dataset),
        config_path=Path(args.config),
        output_path=Path(args.output),
    )
    for model, section in derived["models"].items():
        print(json.dumps({"model": model, **section["summary"]}, ensure_ascii=False))
    print(f"Saved {args.output} (cached/offline; new API requests: 0; new API cost: $0)")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Finished model-context source report")
    parser.add_argument("--dataset", required=True, help="Exact dataset used by the source report")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--output", required=True, help="New derived report; never overwritten")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
