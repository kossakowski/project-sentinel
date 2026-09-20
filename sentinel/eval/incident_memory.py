"""Opt-in live smoke evaluation of memory decisions, with no alert transports.

Run: python -m sentinel.eval.incident_memory --live
The default invocation only validates/prints case names and makes no API calls.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from sentinel.classification.classifier import Classifier
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Article


async def run(args: argparse.Namespace) -> int:
    with Path(args.fixtures).open(encoding="utf-8") as handle:
        cases = yaml.safe_load(handle)["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            raise ValueError(f"Unknown case: {args.case}")
    if not args.live:
        print(json.dumps({"live": False, "cases": [case["id"] for case in cases]}))
        return 0
    load_dotenv()
    with Path(args.config).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    # No fetchers, disk database or transports are constructed by this evaluator.
    raw["sources"]["telegram"].update(enabled=False, api_id=None, api_hash=None)
    raw["classification"].setdefault("incident_memory", {})["enabled"] = True
    config = SentinelConfig(**raw)
    db = Database(":memory:")
    memory = IncidentMemory(db, config)
    classifier = Classifier(config)
    rows = []
    try:
        for case in cases:
            now = datetime.now(UTC)
            article = Article(
                source_name="Memory evaluation",
                source_url=f"https://example.org/{case['id']}",
                source_type="rss",
                title=case["title"],
                summary=case["summary"],
                language=case.get("language", "pl"),
                published_at=now,
                fetched_at=now,
            )
            candidates = [
                {
                    "id": "remembered-incident",
                    "first_seen_at": (now - timedelta(hours=1)).isoformat(),
                    "last_updated_at": (now - timedelta(minutes=30)).isoformat(),
                    "event_type": case["prior_type"],
                    "countries": case.get("prior_countries", ["PL"]),
                    "urgency": case["prior_urgency"],
                    "summary_pl": case["prior"],
                    "notification_revision": 1,
                    "evidence": [],
                }
            ]
            result = await classifier.classify(article, incident_context=candidates)
            raw_decision = result.incident_memory
            memory.validate(result, candidates, article)
            decision = result.incident_memory
            passed = decision["decision"] in case["expected"]
            rows.append(
                {
                    "case": case["id"],
                    "passed": passed,
                    "expected": case["expected"],
                    "actual": decision,
                    "raw_decision": raw_decision,
                    "urgency": result.urgency_score,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    finally:
        await classifier.aclose()
        db.close()
    print(
        json.dumps(
            {
                "passed": sum(row["passed"] for row in rows),
                "total": len(rows),
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
            }
        )
    )
    return 0 if all(row["passed"] for row in rows) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make paid classifier calls; never send alerts")
    parser.add_argument("--fixtures", default="tests/fixtures/incident_memory_eval.yaml")
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument("--case", help="Run one named case")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
