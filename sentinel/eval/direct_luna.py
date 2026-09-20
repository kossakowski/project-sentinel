"""Offline-first, capped direct-Luna checks with real classification and fake alerts."""

import argparse
import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
from dotenv import load_dotenv

from sentinel.classification.classifier import Classifier
from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.classification.openai_provider import BudgetExceeded, ClassificationError
from sentinel.classification.policy import messages
from sentinel.classification.summary_language import is_polish
from sentinel.eval.compare_models import (
    RecordingAlerts,
    RecordingTransport,
    ReplayClock,
    ReplayDatabase,
    make_article,
    make_config,
)


def cases_for_run(fresh_path, repeats):
    source = yaml.safe_load(Path("tests/fixtures/model_comparison_v2_holdout.yaml").read_text())
    known = next(c for c in source["cases"] if c["id"] == "v2h-ru-01-a")
    # Each repeat starts with no memory and exactly the historical message input.
    cases = []
    for number in range(repeats):
        cases.append(
            dict(
                id=f"known-{number + 1}",
                sequence=f"known-{number + 1}",
                article=make_article(known),
                expected=dict(band=[5, 6], countries=["LT"], notification="initial"),
                reused=True,
            )
        )
    fresh = yaml.safe_load(Path(fresh_path).read_text())
    start = make_article(known).fetched_at
    for number, case in enumerate(fresh["cases"]):
        article = dict(
            title=case["title"],
            summary=case["summary"],
            language=case["language"],
            source_name="Synthetic direct migration check",
            source_type="rss",
            source_url=f"https://example.invalid/{case['id']}",
            published_at=(start + timedelta(minutes=number)).isoformat(),
            fetched_at=(start + timedelta(minutes=number)).isoformat(),
        )
        cases.append(
            dict(
                id=case["id"],
                sequence=case["sequence"],
                article=make_article(dict(id=case["id"], article=article)),
                expected={k: case[k] for k in ("band", "countries", "notification")},
                reused=False,
            )
        )
    return cases


async def run(args):
    cases = cases_for_run(args.fresh, args.repeats)
    # Offline mode loads config and cases only: no key, client, DB writes or billing.
    config = make_config(args.config)
    if config.classification.provider != "openai" or config.classification.model != "gpt-5.6-luna":
        raise ValueError("This verification command requires the selected direct Luna configuration")
    if not args.live:
        print(json.dumps(dict(cases=len(cases), known_repeats=args.repeats, live=False, new_api_calls=0)))
        return 0
    if args.max_cost_usd is None or not 0 < args.max_cost_usd <= 0.5:
        raise ValueError("Live tests require an explicitly approved --max-cost-usd between 0 and 0.50")
    if not args.output:
        raise ValueError("Live tests require a new --output JSONL path")
    load_dotenv()
    # Exclusive creation prevents accidentally rerunning a paid test over prior evidence.
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("x", encoding="utf-8") as output:
        classifier = Classifier(config)
        classifier.provider.session_remaining = args.max_cost_usd
        databases = {}
        failures = 0
        before_cost = classifier.provider.ledger.total()
        try:
            for case in cases:
                db = databases.setdefault(case["sequence"], None)
                if db is None:
                    db = databases[case["sequence"]] = ReplayDatabase(":memory:")
                article = case["article"]
                ReplayClock.current = article.fetched_at
                db.insert_article(article)
                memory = IncidentMemory(db, config)
                candidates = memory.candidates(article)
                row = dict(case_id=case["id"], reused=case["reused"], expected=case["expected"])
                content = messages(article, candidates, config.classification.policy)
                row["messages_sha256"] = hashlib.sha256(
                    json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                stop = False
                try:
                    result = await classifier.classify(article, incident_context=candidates)
                    row["raw_result"] = result.to_dict()
                    result.classified_at = ReplayClock.current
                    memory.validate(result, candidates, article)
                    alerts = RecordingAlerts(db, RecordingTransport(), config, push_client=RecordingTransport())
                    with (
                        patch("sentinel.classification.corroborator.datetime", ReplayClock),
                        patch("sentinel.database.datetime", ReplayClock),
                        patch("sentinel.alerts.state_machine.datetime", ReplayClock),
                    ):
                        events = Corroborator(db, config).process_classifications([result])
                        event = events[0] if events else None
                        before = db.get_alert_records(event.id) if event else []
                        if event and event.alert_status != "pending":
                            await alerts.process_event(event)
                        after = db.get_alert_records(event.id) if event else []
                    notification = "silent" if len(before) == len(after) else ("update" if before else "initial")
                    expected = case["expected"]
                    behavior_passed = (
                        expected["band"][0] <= result.urgency_score <= expected["band"][1]
                        and set(result.affected_countries) == set(expected["countries"])
                        and notification == expected["notification"]
                    )
                    summary_polish = is_polish(
                        result.summary_pl, tuple(config.classification.summary_language.detector_languages)
                    )
                    summary_fallback = result.summary_processing.get("action") == "fallback"
                    row.update(
                        urgency=result.urgency_score,
                        notification=notification,
                        channels=[r.alert_type for r in after[len(before) :]],
                        memory=result.incident_memory,
                        behavior_passed=behavior_passed,
                        summary_polish=summary_polish,
                        summary_fallback=summary_fallback,
                        passed=behavior_passed and summary_polish and not summary_fallback,
                    )
                except ClassificationError as exc:
                    row.update(error=str(exc), passed=False)
                    stop = isinstance(exc, BudgetExceeded)
                failures += not row["passed"]
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                print(f"{case['id']}: {'PASS' if row['passed'] else 'FAIL'}", flush=True)
                if stop:
                    break
            summary = dict(
                type="summary",
                failures=failures,
                estimated_usd=classifier.provider.ledger.total() - before_cost,
                remaining_test_allowance=classifier.provider.session_remaining,
                limits="Synthetic/reused inputs; no real alerts. Not proof of real-world reliability.",
            )
            output.write(json.dumps(summary) + "\n")
            output.flush()
            return int(failures > 0)
        finally:
            await classifier.aclose()
            for db in databases.values():
                db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--fresh", default="tests/fixtures/luna_direct_fresh.yaml")
    parser.add_argument("--repeats", type=int, choices=range(2, 21), default=10)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--output")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
