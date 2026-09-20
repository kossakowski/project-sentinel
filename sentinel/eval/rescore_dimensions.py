"""Decompose an existing report without inference, changing labels or overwriting it."""

import argparse
import hashlib
import json
from pathlib import Path

from sentinel.eval.compare_models import DEFAULT_DATASET, load_dataset
from sentinel.eval.reference_history import ReferenceHistory
from sentinel.eval.separate_metrics import aggregate_dimensions, score_dimensions


def rescore(report: dict, cases: list[dict]) -> dict:
    by_id = {case["id"]: case for case in cases}
    result = json.loads(json.dumps(report))
    result["analysis_version"] = "separate-dimensions-v2"
    for model in result["models"].values():
        prior_by_sequence = {}
        reference_by_sequence = {}
        for row in model["cases"]:
            case = by_id[row["case_id"]]
            if row.get("context_mode") == "reference":
                history = reference_by_sequence.setdefault(case["sequence_id"], ReferenceHistory())
                row["evaluation"] = score_dimensions(case, row, history.case_events)
                history.add(case)
                continue
            prior = prior_by_sequence.setdefault(case["sequence_id"], {})
            row["evaluation"] = score_dimensions(case, row, prior)
            prior[case["id"]] = row.get("event_id")
        model["separate_summary"] = aggregate_dimensions(model["cases"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.report)
    output = Path(args.output)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError("Choose a new output path; historical reports cannot be overwritten")
    report = json.loads(source.read_text(encoding="utf-8"))
    digest = hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest()
    if digest != report["dataset_sha256"]:
        raise ValueError("Dataset changed; metric-only rescoring requires the original labels")
    result = rescore(report, load_dataset(args.dataset)["cases"])
    result["derived_from"] = str(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for model, values in result["models"].items():
        print(json.dumps({"model": model, "summary": values["separate_summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
