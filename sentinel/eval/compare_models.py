"""Offline-first model comparison. Run without --live to validate the dataset."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml

from sentinel.alerts.state_machine import AlertStateMachine
from sentinel.classification.classifier import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, Classifier
from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import MEMORY_INSTRUCTIONS, IncidentMemory
from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import AlertRecord, Article, ClassificationResult, Event

DEFAULT_DATASET = "tests/fixtures/model_comparison_first50.yaml"
DEFAULT_MODELS = [
    "anthropic/claude-haiku-4.5",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3.8-flash",
    "openai/gpt-5.6-luna",
]
FIELDS = {
    "is_military_event": {"type": "boolean"},
    "event_type": {"type": "string"},
    "urgency_score": {"type": "integer", "minimum": 1, "maximum": 10},
    "affected_countries": {"type": "array", "items": {"type": "string"}},
    "aggressor": {"type": "string"},
    "is_new_event": {"type": "boolean"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "summary_pl": {"type": "string"},
    "incident_memory": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": ["new", "duplicate", "update", "escalation", "uncertain"]},
            "matched_event_id": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["decision", "matched_event_id", "confidence", "reason"],
    },
}
RESPONSE_SCHEMA = {"type": "object", "properties": FIELDS, "required": list(FIELDS), "additionalProperties": False}


def parse_time(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("Replay timestamps must include a timezone")
    return result.astimezone(UTC)


def load_dataset(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not data.get("cases"):
        raise ValueError("Expected version 1 and a nonempty cases list")
    ids, splits, seen = set(), {}, {}
    for case in data["cases"]:
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError(f"Invalid or duplicate case id: {case_id}")
        ids.add(case_id)
        sequence = case["sequence_id"]
        if case["split"] not in {"development", "holdout"}:
            raise ValueError(f"Invalid split: {case_id}")
        if sequence in splits and splits[sequence] != case["split"]:
            raise ValueError(f"Incident leaks across splits: {sequence}")
        splits[sequence] = case["split"]
        if case["label_status"] not in {"approved", "provisional", "disputed"}:
            raise ValueError(f"Invalid label status: {case_id}")
        article = case["article"]
        for key in ("title", "summary", "source_name", "source_url", "source_type", "language"):
            if not isinstance(article.get(key), str):
                raise ValueError(f"Missing article.{key}: {case_id}")
        parse_time(article["published_at"])
        arrival = parse_time(article["fetched_at"])
        expected = case["expected"]
        if not 1 <= expected["urgency_min"] <= expected["urgency_max"] <= 10:
            raise ValueError(f"Invalid urgency range: {case_id}")
        if expected["notification"] not in {"initial", "silent", "update"} or expected["relation"] not in {
            "new",
            "same",
        }:
            raise ValueError(f"Invalid expected outcome: {case_id}")
        if not isinstance(expected["critical"], bool):
            raise ValueError(f"critical must be a boolean: {case_id}")
        if not isinstance(case.get("provenance"), dict) or not case.get("rationale"):
            raise ValueError(f"Missing provenance/rationale: {case_id}")
        seen[case_id] = (sequence, arrival)
    for case in data["cases"]:
        reference = case["expected"].get("same_as")
        if case["expected"]["relation"] == "same":
            if reference not in seen or seen[reference][0] != case["sequence_id"]:
                raise ValueError(f"same_as must reference this sequence: {case['id']}")
            if seen[reference][1] >= seen[case["id"]][1]:
                raise ValueError(f"same_as must reference an earlier arrival: {case['id']}")
        elif reference is not None:
            raise ValueError(f"new relation cannot have same_as: {case['id']}")
    return data


def inventory(data: dict) -> dict:
    cases = data["cases"]
    return {
        "cases": len(cases),
        "sequences": len({c["sequence_id"] for c in cases}),
        "splits": dict(Counter(c["split"] for c in cases)),
        "labels": dict(Counter(c["label_status"] for c in cases)),
        "content_languages": dict(
            Counter(c["provenance"].get("content_language", c["article"]["language"]) for c in cases)
        ),
        "approved_for_release": all(c["label_status"] == "approved" for c in cases),
    }


def make_article(case: dict) -> Article:
    data = dict(case["article"])
    return Article(
        id=case["id"],
        **{key: data[key] for key in ("source_name", "source_url", "source_type", "title", "summary", "language")},
        published_at=parse_time(data["published_at"]),
        fetched_at=parse_time(data["fetched_at"]),
    )


def request_messages(article: Article, candidates: list[dict]) -> list[dict]:
    # Reuse the exact runtime builder without constructing an Anthropic client.
    prompt = Classifier._build_user_prompt(None, article, candidates)
    return [{"role": "system", "content": SYSTEM_PROMPT + MEMORY_INSTRUCTIONS}, {"role": "user", "content": prompt}]


class ReplayClock(datetime):
    current = datetime.now(UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class ReplayDatabase(Database):
    """The production candidate query evaluated at a historical replay clock."""

    def get_memory_events(self, within_hours: int, limit: int) -> list[Event]:
        since = ReplayClock.current - timedelta(hours=within_hours)
        rows = self.conn.execute(
            "SELECT * FROM events WHERE julianday(last_updated_at) >= julianday(?) "
            "AND julianday(last_updated_at) <= julianday(?) ORDER BY julianday(last_updated_at) DESC, id DESC LIMIT ?",
            (since.isoformat(), ReplayClock.current.isoformat(), limit),
        )
        return [Event.from_row(row) for row in rows]


class RecordingTransport:
    """Pure local transport: constructing it cannot create a network client."""

    @staticmethod
    def record(event_id: str, alert_type: str, body: str) -> AlertRecord:
        return AlertRecord(
            event_id=event_id,
            alert_type=alert_type,
            twilio_sid="eval-only",
            status="sent",
            attempt_number=1,
            sent_at=ReplayClock.current,
            message_body=body,
        )

    def send_sms(self, _phone, message, event_id):
        return self.record(event_id, "sms", message)

    def send_push(self, _title, body, event_id, data=None):
        return self.record(event_id, "push", body)


class RecordingAlerts(AlertStateMachine):
    async def _execute_phone_call(self, event: Event, existing_alerts=None) -> None:
        # Simulate one answered and acknowledged alarm, without any retry timers,
        # telephony SDK or inbound SMS polling. This measures notification policy.
        record = RecordingTransport.record(event.id, "phone_call", event.summary_pl)
        record.status = "acknowledged"
        self._record_alert(record, event)
        self.db.update_event(event.id, acknowledged_at=ReplayClock.current.isoformat(), alert_status="acknowledged")


def make_config(path: str) -> SentinelConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    raw["sources"]["telegram"].update(enabled=False, api_id=None, api_hash=None)
    raw["database"]["path"] = ":memory:"
    raw["alerts"]["phone_number"] = "eval-only"
    raw["alerts"]["push"] = {"enabled": True, "tokens": ["eval-only"]}
    raw["testing"]["dry_run"] = False  # All transports above are pure local fakes.
    raw["classification"].setdefault("incident_memory", {})["enabled"] = True
    return SentinelConfig(**raw)


def parse_prediction(data: dict, article: Article, model: str, usage: dict) -> ClassificationResult:
    if not isinstance(data, dict) or set(FIELDS) - set(data):
        raise ValueError("Incomplete classification object")
    for key in ("is_military_event", "is_new_event"):
        if not isinstance(data[key], bool):
            raise ValueError(f"Invalid boolean {key}")
    if type(data["urgency_score"]) is not int or not 1 <= data["urgency_score"] <= 10:
        raise ValueError("Invalid urgency score")
    if not isinstance(data["affected_countries"], list) or not all(
        isinstance(c, str) for c in data["affected_countries"]
    ):
        raise ValueError("Invalid countries")
    for key in ("event_type", "aggressor", "summary_pl"):
        if not isinstance(data[key], str):
            raise ValueError(f"Invalid text {key}")
    confidence = data["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Invalid confidence")
    return ClassificationResult(
        article_id=article.id,
        **{key: data[key] for key in FIELDS},
        classified_at=ReplayClock.current,
        model_used=model,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )


def score(
    case: dict,
    result: ClassificationResult,
    event: Event | None,
    notification: str,
    prior_events: dict[str, str | None],
) -> dict:
    expected = case["expected"]
    event_id = event.id if event else result.incident_memory.get("matched_event_id")
    identity_unscorable = (
        expected["relation"] == "same" and prior_events.get(expected["same_as"]) is None and expected["urgency_max"] < 5
    )
    if expected["relation"] == "same":
        identity_ok = event_id is not None and event_id == prior_events.get(expected["same_as"])
    else:
        identity_ok = event_id is None or event_id not in prior_events.values()
    checks = {
        "urgency": expected["urgency_min"] <= result.urgency_score <= expected["urgency_max"],
        "notification": notification == expected["notification"],
    }
    if not identity_unscorable:
        checks["incident_identity"] = identity_ok
    if "affected_countries" in expected:
        checks["countries"] = set(result.affected_countries) == set(expected["affected_countries"])
    critical_miss = expected["critical"] and (
        result.urgency_score < 9 or (expected["notification"] != "silent" and notification == "silent")
    )
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "identity_unscorable": identity_unscorable,
        "critical_miss": critical_miss,
        "wrong_merge": expected["relation"] == "new" and not identity_ok,
        "duplicate_notification": expected["relation"] == "same"
        and expected["notification"] == "silent"
        and notification != "silent",
        "false_alert": expected["urgency_max"] < 5 and notification != "silent",
    }


async def replay(cases: list[dict], model: str, client, config: SentinelConfig, on_result=None) -> list[dict]:
    reports = []
    sequences = sorted({case["sequence_id"] for case in cases})
    for sequence in sequences:
        db = ReplayDatabase(":memory:")
        memory = IncidentMemory(db, config)
        grouper = Corroborator(db, config)
        alerts = RecordingAlerts(db, RecordingTransport(), config, push_client=RecordingTransport())
        prior_events = {}
        try:
            for case in sorted(
                (c for c in cases if c["sequence_id"] == sequence), key=lambda c: parse_time(c["article"]["fetched_at"])
            ):
                article = make_article(case)
                ReplayClock.current = article.fetched_at
                db.insert_article(article)
                candidates = memory.candidates(article)
                messages = request_messages(article, candidates)
                completion = await client.complete(model_id=model, messages=messages, json_schema=RESPONSE_SCHEMA)
                row = completion.to_dict()
                row["request_sha256"] = hashlib.sha256(
                    json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                row.update(
                    case_id=case["id"],
                    sequence_id=sequence,
                    split=case["split"],
                    label_status=case["label_status"],
                    expected=case["expected"],
                    candidate_ids=[c["id"] for c in candidates],
                )
                if row.get("error"):
                    row.update(passed=False, critical_miss=case["expected"]["critical"])
                    reports.append(row)
                    if on_result:
                        on_result(row)
                    if row.get("budget_stopped"):
                        return reports
                    continue
                try:
                    result = parse_prediction(row["data"], article, model, row.get("usage") or {})
                    memory.validate(result, candidates, article)
                    with (
                        patch("sentinel.classification.corroborator.datetime", ReplayClock),
                        patch("sentinel.alerts.state_machine.datetime", ReplayClock),
                        patch("sentinel.database.datetime", ReplayClock),
                    ):
                        events = grouper.process_classifications([result])
                        event = events[0] if events else None
                        before = db.get_alert_records(event.id) if event else []
                        if event and event.alert_status != "pending":
                            await alerts.process_event(event)
                        after = db.get_alert_records(event.id) if event else []
                    notification = "silent" if len(after) == len(before) else ("update" if before else "initial")
                    row.update(score(case, result, event, notification, prior_events))
                    row.update(
                        notification=notification,
                        event_id=event.id if event else None,
                        accepted_memory=result.incident_memory,
                        channels=[r.alert_type for r in after[len(before) :]],
                    )
                    prior_events[case["id"]] = event.id if event else None
                except (TypeError, ValueError, KeyError) as exc:
                    row.update(error=str(exc), passed=False, critical_miss=case["expected"]["critical"])
                reports.append(row)
                if on_result:
                    on_result(row)
        finally:
            db.close()
    return reports


def summarize(rows: list[dict], planned: int) -> dict:
    scored = [row for row in rows if row["label_status"] != "disputed"]
    latencies = sorted(row["latency_seconds"] for row in rows if isinstance(row.get("latency_seconds"), (int, float)))
    return {
        "planned": planned,
        "attempted": len(rows),
        "scored": len(scored),
        "passed": sum(bool(row.get("passed")) for row in scored),
        "identity_unscorable": sum(bool(row.get("identity_unscorable")) for row in rows),
        "median_latency_seconds": statistics.median(latencies) if latencies else None,
        "p95_latency_seconds": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
        "reported_cost_usd": sum(row.get("cost_usd") or 0 for row in rows),
        "unknown_cost_requests": sum(row.get("cost_usd") is None for row in rows),
        "prompt_tokens": sum((row.get("usage") or {}).get("prompt_tokens") or 0 for row in rows),
        "completion_tokens": sum((row.get("usage") or {}).get("completion_tokens") or 0 for row in rows),
        "reasoning_tokens": sum((row.get("usage") or {}).get("reasoning_tokens") or 0 for row in rows),
        **{
            key: sum(bool(row.get(key)) for row in scored)
            for key in ("critical_miss", "wrong_merge", "duplicate_notification", "false_alert", "error")
        },
        "release_eligible": len(rows) == planned
        and bool(rows)
        and all(row["label_status"] == "approved" and row["split"] == "holdout" for row in rows)
        and not any(row.get("error") for row in rows),
        "note": "Provisional/selected-case results are not a production accuracy or monthly-cost guarantee.",
    }


async def main_async(args: argparse.Namespace) -> int:
    data = load_dataset(args.dataset)
    print(json.dumps(inventory(data), ensure_ascii=False))
    if not args.live and not args.catalog:
        return 0
    from sentinel.eval.openrouter_client import BudgetLedger, OpenRouterEvalClient, fetch_model_catalogue

    catalogue = await fetch_model_catalogue()
    if args.catalog:
        for model in args.models:
            print(model, catalogue.get(model))
        return int(any(model not in catalogue for model in args.models))
    if len(args.models) != len(set(args.models)):
        raise ValueError("Each model must appear only once per report")
    if any(model not in catalogue for model in args.models):
        raise ValueError("Requested model is absent from the approved current catalogue")
    if args.budget_usd is None or not 0 < args.budget_usd <= 5:
        raise ValueError("Live preparation runs require --budget-usd >0 and <=5")
    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("Set OPENROUTER_API_KEY in the ignored .env file")
    cases = [c for c in data["cases"] if args.split == "all" or c["split"] == args.split]
    if not cases:
        raise ValueError("No cases in the requested split")
    if any(c["label_status"] != "approved" for c in cases) and not args.allow_provisional:
        raise ValueError("Unapproved labels: review them or explicitly use --allow-provisional for exploratory results")
    config = make_config(args.config)
    ledger = BudgetLedger(args.budget_usd)
    client = OpenRouterEvalClient(api_key=key, ledger=ledger, catalogue=catalogue)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "dataset": args.dataset,
        "dataset_sha256": hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(
            (SYSTEM_PROMPT + MEMORY_INSTRUCTIONS + USER_PROMPT_TEMPLATE).encode()
        ).hexdigest(),
        "classification_config": config.classification.model_dump(),
        "alert_levels": {key: value.model_dump() for key, value in config.alerts.urgency_levels.items()},
        "mode": "memory; simulated immediate acknowledgement; no real transports",
        "models": {},
    }
    output = Path(args.output or f"data/eval/model-comparison-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json")
    if output.exists():
        await client.aclose()
        raise ValueError(f"Report already exists; refusing to overwrite or silently rerun: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report["run_finished"] = False
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for model in args.models:
            report["models"][model] = {"cases": []}

            def checkpoint(row, current_model=model):
                report["models"][current_model]["cases"].append(row)
                report["budget"] = ledger.summary()
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            rows = await replay(cases, model, client, config, on_result=checkpoint)
            report["models"][model] = {"summary": summarize(rows, len(cases)), "cases": rows}
            report["budget"] = ledger.summary()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"model": model, **report["models"][model]["summary"]}))
    finally:
        await client.aclose()
    report["run_finished"] = True
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {output}")
    return int(any(row.get("error") for model in report["models"].values() for row in model["cases"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--allow-provisional", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
