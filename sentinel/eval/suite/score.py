"""Score eval-suite runs against the operator's labels. Offline: no API calls.

Truth comes from the operator's first (non-repeat) answer per item, overridden by an
adjudicated answer when one exists. Each model's official prediction per item is the
majority of its repeats; an item whose repeats are mostly invalid counts as invalid,
which is a miss wherever a response was required.
"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from sentinel.eval.suite.stats import mcnemar_exact, paired_bootstrap, verdict, wilson

ACTION_ORDER = {"log": 0, "alert": 1, "call": 2}
# Provider-side or harness failures that say nothing about the model: overloads, timeouts,
# server errors, the run's own budget stop, and a rejected key/credit. Every other request
# that produced no answer (bad JSON, refusal, 4xx, wrong model returned) counts against it.
OUTAGE_KINDS = {"timeout", "transport_error", "provider_error", "budget_exhausted"}
OUTAGE_HTTP = {401, 402, 403, 429}


def is_outage(row: dict) -> bool:
    kind, status = row.get("error_kind"), row.get("http_status")
    return kind in OUTAGE_KINDS or (
        kind == "http_error" and status is not None and (status in OUTAGE_HTTP or status >= 500)
    )


def model_fault(row: dict) -> bool:
    return row.get("urgency") is None and not is_outage(row)


def unavailable(row: dict) -> bool:
    return row.get("urgency") is None and is_outage(row)


def action(urgency: int) -> str:
    """Production alert tiers: phone call 9-10, SMS/push 5-8, log only 1-4."""
    if urgency >= 9:
        return "call"
    if urgency >= 5:
        return "alert"
    return "log"


def load_jsonl(path: Path) -> list[dict]:
    """Rows of a JSONL file, without rows a resumed run superseded (redone later)."""
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if not r.get("superseded")]


def truth_from_labels(labels: list[dict], queue: list[dict], adjudicated: list[dict] | None = None) -> dict:
    """item_id -> truth. Repeat answers are kept aside for the self-consistency check."""
    slot_item = {s["slot"]: s["item_id"] for s in queue}
    latest = {}
    for row in labels:
        latest[row["slot"]] = row
    truth = {}
    for row in latest.values():
        if row.get("retest_of"):
            continue
        low, high = sorted((row["urgency"], row["urgency_alt"] or row["urgency"]))
        truth[row["item_id"]] = {
            "urgency": row["urgency"],
            "low": low,
            "high": high,
            "tier": row["tier"],
            "actions": {action(u) for u in range(low, high + 1)},
            "critical": row["tier"] == "FLEE",
            "possible_call": high >= 9,
            "countries": set(row["countries"]),
            "bad_input": row["bad_input"],
            "same_as": slot_item.get(row["same_as"]) if row.get("same_as") else None,
            "notify": row.get("notify"),
            "adjudicated": False,
        }
    for row in adjudicated or []:
        if row["item_id"] in truth:
            base = truth[row["item_id"]]
            low, high = sorted((row["urgency"], row.get("urgency_alt") or row["urgency"]))
            base.update(
                urgency=row["urgency"],
                low=low,
                high=high,
                tier=row["tier"],
                actions={action(u) for u in range(low, high + 1)},
                critical=row["tier"] == "FLEE",
                possible_call=high >= 9,
                countries=set(row.get("countries", base["countries"])),
                adjudicated=True,
            )
    return truth


def retest_agreement(labels: list[dict]) -> dict:
    latest = {}
    for row in labels:
        latest[row["slot"]] = row
    first = {r["item_id"]: r for r in latest.values() if not r.get("retest_of")}
    pairs = [(first[r["retest_of"]], r) for r in latest.values() if r.get("retest_of") and r["retest_of"] in first]
    if not pairs:
        return {"pairs": 0}
    same_action = sum(action(a["urgency"]) == action(b["urgency"]) for a, b in pairs)
    same_tier = sum(a["tier"] == b["tier"] for a, b in pairs)
    return {
        "pairs": len(pairs),
        "same_action": wilson(same_action, len(pairs)),
        "same_tier": wilson(same_tier, len(pairs)),
        "mean_abs_urgency_diff": statistics.mean(abs(a["urgency"] - b["urgency"]) for a, b in pairs),
    }


def majority(rows: list[dict]) -> dict:
    """Aggregate one model's repeats of one item."""
    valid = [r for r in rows if r.get("urgency") is not None]
    invalid = [r for r in rows if model_fault(r)]
    if not valid and not invalid:
        return {"invalid": False, "unavailable": True, "repeats": len(rows), "valid": 0}
    if len(valid) <= len(invalid):
        return {"invalid": True, "repeats": len(rows), "valid": len(valid)}
    urgency = int(statistics.median_low(r["urgency"] for r in valid))
    # With an even number of valid repeats a tie is scored pessimistically per metric:
    # the lower middle value decides a missed call, the higher one a false call.
    urgency_high = int(statistics.median_high(r["urgency"] for r in valid))
    actions = Counter(action(r["urgency"]) for r in valid)
    countries = Counter(frozenset(r["countries"]) for r in valid).most_common(1)[0][0]
    return {
        "invalid": False,
        "repeats": len(rows),
        "valid": len(valid),
        "urgency": urgency,
        "urgency_high": urgency_high,
        "action": action(urgency),
        "countries": set(countries),
        "flip": len(actions) > 1,
        "flip_call_boundary": ("call" in actions) and len(actions) > 1,
        "urgency_spread": max(r["urgency"] for r in valid) - min(r["urgency"] for r in valid),
    }


def item_outcomes(pred: dict, truth: dict) -> dict:
    """Binary per-item outcomes used for rates and paired tests (None = not applicable)."""
    call = not pred["invalid"] and pred["action"] == "call"
    call_on_tie = not pred["invalid"] and action(pred["urgency_high"]) == "call"
    return {
        "critical_hit": call if truth["critical"] else None,
        "false_call": call_on_tie if not truth["possible_call"] else None,
        "tier_ok": (not pred["invalid"]) and pred["action"] in truth["actions"],
        "urgency_in_range": (not pred["invalid"]) and truth["low"] <= pred["urgency"] <= truth["high"],
        "countries_ok": (not pred["invalid"]) and pred["countries"] == truth["countries"],
        "pl_error": None if pred["invalid"] else (("PL" in pred["countries"]) != ("PL" in truth["countries"])),
        "abs_error": None
        if pred["invalid"]
        else max(0, truth["low"] - pred["urgency"], pred["urgency"] - truth["high"]),
    }


def quadratic_weighted_kappa(a: list[int], b: list[int], k: int = 10) -> float | None:
    if len(a) < 2:
        return None
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[x - 1][y - 1] += 1
    n = len(a)
    hist_a = [sum(row) for row in observed]
    hist_b = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            weight = (i - j) ** 2 / (k - 1) ** 2
            num += weight * observed[i][j]
            den += weight * hist_a[i] * hist_b[j] / n
    return None if den == 0 else 1 - num / den


def rate(values: list) -> tuple | None:
    present = [v for v in values if v is not None]
    return wilson(sum(bool(v) for v in present), len(present)) + (len(present),) if present else None


def sequence_metrics(calls: list[dict], truth: dict, items: dict) -> dict:
    """Incident identity and notification behaviour on chains, per repeat, summed.

    A chain replay with a provider outage is skipped: the missing answer changes every
    later memory lookup, so its notifications say nothing about the model. Same-incident
    pairs are not scored when either article is below urgency 5, because production
    creates no event for them and a correct low score would look like a miss.
    """
    counts = Counter()
    by_run = defaultdict(dict)
    for row in calls:
        if row.get("chain_id"):
            by_run[(row["repeat"], row["chain_id"])][row["item_id"]] = row
    for rows in by_run.values():
        if any(unavailable(r) for r in rows.values()):
            counts["chain_runs_skipped_outage"] += 1
            continue
        for item_id, row in rows.items():
            label = truth.get(item_id)
            item = items[item_id]
            if label is None or not item["chain_pos"]:
                continue
            if model_fault(row):
                counts["invalid"] += 1
                continue
            earlier = [r.get("event_id") for i, r in rows.items() if items[i]["chain_pos"] < item["chain_pos"]]
            event = row.get("event_id")
            counts["scored"] += 1
            if label["same_as"]:
                target_row = rows.get(label["same_as"], {})
                target_label = truth.get(label["same_as"])
                if (
                    label["low"] < 5
                    or target_label is None
                    or target_label["low"] < 5
                    or target_row.get("urgency") is None
                ):
                    counts["same_unscorable"] += 1
                else:
                    counts["same_expected"] += 1
                    counts["same_ok"] += bool(event and event == target_row.get("event_id"))
            else:
                counts["new_expected"] += 1
                merged = bool(event and event in earlier)
                counts["wrong_merge"] += merged
                counts["wrong_merge_critical"] += merged and label["critical"]
            if label["notify"] is False:
                counts["silent_expected"] += 1
                counts["duplicate_notification"] += row.get("notification") not in (None, "silent")
            elif label["notify"] is True:
                counts["notify_expected"] += 1
                counts["missed_notification"] += row.get("notification") in (None, "silent")
    return dict(counts)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def model_report(model: str, calls: list[dict], truth: dict, items: dict, expected: list[str], repeats: int) -> dict:
    """Metrics for one model spec over the labelled items of the run's pool.

    ``expected`` is every labelled item the run should have answered; coverage is judged
    against it (items never attempted count as missing, not as silently absent).
    """
    wanted = set(expected)
    rows = [c for c in calls if c["model"] == model and c["item_id"] in wanted]
    per_item = defaultdict(list)
    for row in rows:
        per_item[row["item_id"]].append(row)
    all_preds = {i: majority(r) for i, r in per_item.items() if i in truth}
    preds = {i: p for i, p in all_preds.items() if not p.get("unavailable")}
    outcomes = {i: item_outcomes(p, truth[i]) for i, p in preds.items()}
    paid = [r for r in rows if not unavailable(r)]
    answered = {(r["item_id"], r["repeat"]) for r in paid}
    usage = [r["usage"] for r in paid if (r.get("usage") or {}).get("prompt_tokens") is not None]
    valid_preds = {i: p for i, p in preds.items() if not p["invalid"]}

    def slice_rate(key, predicate):
        return rate([outcomes[i][key] for i in outcomes if predicate(items[i])])

    slices = {}
    for name, predicate in {
        **{
            f"lang:{lang}": (lambda it, lang=lang: it["article"]["language"] == lang)
            for lang in ("pl", "en", "uk", "ru")
        },
        "input:headline_only": lambda it: it["input"]["enrichment"] == "heuristic" and not it["input"]["fetched"],
        "input:enriched": lambda it: it["input"]["fetched"],
        "input:full_summary": lambda it: it["input"]["enrichment"] == "none",
        "origin:synthetic": lambda it: it["origin"] == "synthetic",
    }.items():
        slices[name] = {
            "tier_ok": slice_rate("tier_ok", predicate),
            "critical_hit": slice_rate("critical_hit", predicate),
        }
    return {
        "model": model,
        "items_scored": len(preds),
        "calls": len(paid),
        "critical_recall": rate([o["critical_hit"] for o in outcomes.values()]),
        "false_call_rate": rate([o["false_call"] for o in outcomes.values()]),
        "tier_accuracy": rate([o["tier_ok"] for o in outcomes.values()]),
        "urgency_in_range": rate([o["urgency_in_range"] for o in outcomes.values()]),
        "countries_exact": rate([o["countries_ok"] for o in outcomes.values()]),
        "pl_error_rate": rate([o["pl_error"] for o in outcomes.values()]),
        "mean_abs_error": statistics.mean([o["abs_error"] for o in outcomes.values() if o["abs_error"] is not None])
        if valid_preds
        else None,
        "qwk": quadratic_weighted_kappa(
            [truth[i]["urgency"] for i in valid_preds], [p["urgency"] for p in valid_preds.values()]
        ),
        "invalid_call_rate": rate([model_fault(r) for r in paid]),
        "unavailable_calls": sum(unavailable(r) for r in rows),
        "unavailable_items": len(wanted) - len(preds),
        "planned_answers": len(wanted) * repeats,
        "missing_answers": len(wanted) * repeats - len(answered),
        "retried_calls": sum((r.get("attempts") or 1) > 1 for r in rows),
        "invalid_item_rate": rate([p["invalid"] for p in preds.values()]),
        "invalid_on_critical_calls": sum(
            1 for r in paid if model_fault(r) and truth.get(r["item_id"], {}).get("critical")
        ),
        "flip_rate": rate([p["flip"] for p in valid_preds.values()]),
        "flip_call_boundary_rate": rate([p["flip_call_boundary"] for p in valid_preds.values()]),
        "summary_not_polish_rate": rate([not r["summary_polish"] for r in paid if r.get("summary_polish") is not None]),
        "latency_p50": percentile([r["latency_seconds"] for r in paid if r.get("latency_seconds")], 0.5),
        "latency_p95": percentile([r["latency_seconds"] for r in paid if r.get("latency_seconds")], 0.95),
        "cost_usd": sum(r.get("cost_usd") or 0 for r in paid),
        "known_cost_calls": sum(r.get("cost_usd") is not None for r in paid),
        "unknown_cost_calls": sum(r.get("cost_usd") is None for r in paid),
        "mean_prompt_tokens": statistics.mean([u.get("prompt_tokens") or 0 for u in usage]) if usage else None,
        "mean_cached_tokens": statistics.mean([u.get("cached_tokens") or 0 for u in usage]) if usage else None,
        "mean_completion_tokens": statistics.mean([u.get("completion_tokens") or 0 for u in usage]) if usage else None,
        "mean_reasoning_tokens": statistics.mean([u.get("reasoning_tokens") or 0 for u in usage]) if usage else None,
        "sequences": sequence_metrics(rows, truth, items),
        "slices": slices,
        "_outcomes": outcomes,
    }


def paired(baseline: dict, candidate: dict, items: dict) -> dict:
    """Candidate minus baseline on items both answered, clustered by incident."""
    result = {}
    for key, higher_better in (
        ("critical_hit", True),
        ("false_call", False),
        ("tier_ok", True),
        ("countries_ok", True),
    ):
        shared = [
            {
                "cluster_id": items[i]["cluster_id"],
                "a": baseline["_outcomes"][i][key],
                "b": candidate["_outcomes"][i][key],
            }
            for i in baseline["_outcomes"]
            if i in candidate["_outcomes"] and baseline["_outcomes"][i][key] is not None
        ]
        if not shared:
            result[key] = None
            continue

        def diff(sample):
            return sum(bool(r["b"]) - bool(r["a"]) for r in sample) / len(sample) if sample else None

        interval = paired_bootstrap(shared, diff, resamples=2000, seed=7)
        only_candidate = sum(bool(r["b"]) and not r["a"] for r in shared)
        only_baseline = sum(bool(r["a"]) and not r["b"] for r in shared)
        result[key] = {
            "n": len(shared),
            "difference": interval,
            "mcnemar_p": mcnemar_exact(only_candidate, only_baseline),
            "verdict": verdict(interval, higher_is_better=higher_better),
        }
    return result


def score_run(run_dir: Path, labels_path: Path, queue_path: Path, items_path: Path, baseline: str) -> dict:
    items = {i["id"]: i for i in json.loads(items_path.read_text(encoding="utf-8"))["items"]}
    queue = json.loads(queue_path.read_text(encoding="utf-8"))["slots"]
    labels = load_jsonl(labels_path)
    adjudicated = load_jsonl(labels_path.with_name("adjudicated.jsonl"))
    truth = truth_from_labels(labels, queue, adjudicated)
    calls = load_jsonl(run_dir / "calls.jsonl")
    models = list(dict.fromkeys(c["model"] for c in calls))
    if baseline not in models:
        # Accept the bare id for a spec such as "openai/gpt-5.6-luna@openai".
        matches = [m for m in models if m.removesuffix("+reasoning").partition("@")[0] == baseline]
        if len(matches) == 1:
            baseline = matches[0]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    pool = manifest.get("pool", "all")
    repeats = manifest.get("repeats", 1)
    expected = sorted(i for i in truth if i in items and (pool == "all" or items[i].get("pool") == pool))
    run_pool = [i for i, it in items.items() if pool == "all" or it.get("pool") == pool]
    reports = {m: model_report(m, calls, truth, items, expected, repeats) for m in models}
    comparisons = {
        m: paired(reports[baseline], reports[m], items) for m in models if m != baseline and baseline in reports
    }
    for report in reports.values():
        report.pop("_outcomes")
    return {
        "run": run_dir.name,
        "manifest": manifest,
        "labelled_items": len(expected),
        "critical_items": sum(truth[i]["critical"] for i in expected),
        "unlabelled_items_in_pool": len(run_pool) - len(expected),
        "retest": retest_agreement(labels),
        "baseline": baseline,
        "models": reports,
        "paired_vs_baseline": comparisons,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="Run folder, e.g. data/eval/suite/runs/dev-baseline")
    parser.add_argument("--labels", default="data/eval/suite/labels.jsonl")
    parser.add_argument("--queue", default="data/eval/suite/queue.json")
    parser.add_argument("--items", default="data/eval/suite/items.json")
    parser.add_argument("--baseline", default="openai/gpt-5.6-luna")
    parser.add_argument("--output")
    args = parser.parse_args()
    run_dir = Path(args.run)
    scored = score_run(run_dir, Path(args.labels), Path(args.queue), Path(args.items), args.baseline)
    output = Path(args.output) if args.output else run_dir / "score.json"
    output.write_text(json.dumps(scored, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    for model, report in scored["models"].items():
        recall = report["critical_recall"]
        print(model, "critical recall", recall and f"{recall[0]:.0%} [{recall[1]:.0%}-{recall[2]:.0%}] n={recall[3]}")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
