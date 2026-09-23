"""Run candidate models over the eval-suite items with the exact production prompt.

Single articles are classified with empty incident memory (as a first report would
be). Real incident chains are replayed in order through production incident memory,
grouping and a fake alert state machine, so duplicate or missing notifications show up.
Every request is one JSONL row; scoring happens later and offline (``score.py``).

Resumable: rows already on disk are skipped; a partially finished chain is redone.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import jsonschema
from dotenv import load_dotenv

from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.classification.policy import messages as production_messages
from sentinel.classification.policy import prompt_hash
from sentinel.classification.schema import CLASSIFICATION_SCHEMA
from sentinel.classification.summary_language import is_polish
from sentinel.eval.compare_models import (
    RecordingAlerts,
    RecordingTransport,
    ReplayClock,
    ReplayDatabase,
    make_article,
    make_config,
    parse_prediction,
)
from sentinel.eval.openrouter_client import BudgetLedger, OpenRouterEvalClient, fetch_model_catalogue

RUNS = Path("data/eval/suite/runs")
SCHEMA_SHA256 = hashlib.sha256(json.dumps(CLASSIFICATION_SCHEMA, sort_keys=True).encode()).hexdigest()


def parse_model_spec(spec: str) -> tuple[str, list[str] | None]:
    """``vendor/model`` or ``vendor/model@provider`` (pins the host, no fallback)."""
    model, _, provider = spec.partition("@")
    return model, ([provider] if provider else None)


def select_items(items: list[dict], pool: str) -> list[dict]:
    return [i for i in items if pool == "all" or i["pool"] == pool]


def units(items: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    singles = [i for i in items if not i["chain_id"]]
    chains: dict[str, list[dict]] = {}
    for item in items:
        if item["chain_id"]:
            chains.setdefault(item["chain_id"], []).append(item)
    ordered = [sorted(c, key=lambda i: (i["chain_pos"], i["article"]["fetched_at"])) for c in chains.values()]
    return singles, sorted(ordered, key=lambda c: c[0]["chain_id"])


def validate_output(data, article, model: str, usage: dict):
    """Production-strength validation: the JSON schema, then field-level checks."""
    try:
        jsonschema.Draft202012Validator(CLASSIFICATION_SCHEMA).validate(data)
        return parse_prediction(data, article, model, usage, require_facts=True)
    except (jsonschema.ValidationError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"invalid_output: {str(exc)[:200]}") from None


def base_row(model: str, repeat: int, item: dict, messages: list[dict], completion: dict) -> dict:
    row = {
        "model": model,
        "repeat": repeat,
        "item_id": item["id"],
        "chain_id": item["chain_id"],
        "request_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        **{k: completion.get(k) for k in ("usage", "cost_usd", "latency_seconds", "provider", "request_id")},
        "error_kind": completion.get("error_kind"),
        "error": completion.get("error"),
        "raw_content": completion.get("raw_content"),
        "budget_stopped": completion.get("budget_stopped", False),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    return row


def outcome_fields(result, config, data: dict) -> dict:
    languages = tuple(config.classification.summary_language.detector_languages)
    return {
        "urgency": result.urgency_score,
        "countries": sorted(result.affected_countries),
        "is_military_event": result.is_military_event,
        "event_type": result.event_type,
        "summary_pl": result.summary_pl,
        "summary_polish": is_polish(result.summary_pl, languages),
        "memory": result.incident_memory,
        "facts": data.get("facts") or {},
    }


async def classify_single(client, model: str, repeat: int, item: dict, config, policy: dict) -> dict:
    article = make_article({"id": item["id"], "article": item["article"]})
    messages = production_messages(article, [], policy)
    completion = (await client.complete(model_id=model, messages=messages, json_schema=CLASSIFICATION_SCHEMA)).to_dict()
    row = base_row(model, repeat, item, messages, completion)
    if completion.get("error"):
        return row
    try:
        result = validate_output(completion["data"], article, model, completion.get("usage") or {})
    except ValueError as exc:
        row.update(error_kind="invalid_output", error=str(exc), raw_content=json.dumps(completion["data"]))
        return row
    row.update(outcome_fields(result, config, completion["data"]))
    return row


async def replay_chain(client, model: str, repeat: int, chain: list[dict], config, policy: dict) -> list[dict]:
    rows = []
    db = ReplayDatabase(":memory:")
    memory = IncidentMemory(db, config)
    grouper = Corroborator(db, config)
    alerts = RecordingAlerts(db, RecordingTransport(), config, push_client=RecordingTransport())
    try:
        for item in chain:
            article = make_article({"id": item["id"], "article": item["article"]})
            ReplayClock.current = article.fetched_at
            db.insert_article(article)
            candidates = memory.candidates(article)
            messages = production_messages(article, candidates, policy)
            completion = (
                await client.complete(model_id=model, messages=messages, json_schema=CLASSIFICATION_SCHEMA)
            ).to_dict()
            row = base_row(model, repeat, item, messages, completion)
            row["candidate_ids"] = [c["id"] for c in candidates]
            rows.append(row)
            if completion.get("error"):
                continue
            try:
                result = validate_output(completion["data"], article, model, completion.get("usage") or {})
            except ValueError as exc:
                row.update(error_kind="invalid_output", error=str(exc), raw_content=json.dumps(completion["data"]))
                continue
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
            row.update(outcome_fields(result, config, completion["data"]))
            row.update(
                event_id=event.id if event else None,
                notification="silent" if len(after) == len(before) else ("update" if before else "initial"),
                channels=[r.alert_type for r in after[len(before) :]],
                accepted_memory=result.incident_memory,
            )
    finally:
        db.close()
    return rows


def load_done(path: Path, chains: list[list[dict]]) -> tuple[list[dict], set]:
    """Keep finished work; drop rows of chains that stopped half-way (they are redone)."""
    if not path.exists():
        return [], set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chain_size = {c[0]["chain_id"]: len(c) for c in chains}
    seen: dict[tuple, int] = {}
    for row in rows:
        if row["chain_id"]:
            key = (row["model"], row["repeat"], row["chain_id"])
            seen[key] = seen.get(key, 0) + 1
    kept = [
        r
        for r in rows
        if not r["chain_id"] or seen[(r["model"], r["repeat"], r["chain_id"])] == chain_size.get(r["chain_id"])
    ]
    # A budget stop is not a model answer: retry those rows on resume.
    kept = [r for r in kept if r.get("error_kind") != "budget_exhausted"]
    if len(kept) != len(rows):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    return kept, {(r["model"], r["repeat"], r["item_id"]) for r in kept}


async def run(args) -> int:
    data = json.loads(Path(args.items).read_text(encoding="utf-8"))
    items = select_items(data["items"], args.pool)
    singles, chains = units(items)
    config = make_config(args.config)
    policy = config.classification.policy
    specs = [parse_model_spec(s) for s in args.models]
    calls_per_model = args.repeats * len(items)
    out = RUNS / args.name
    manifest = {
        "name": args.name,
        "created_at": datetime.now(UTC).isoformat(),
        "items_sha256": data["items_sha256"],
        "pool": args.pool,
        "items": len(items),
        "singles": len(singles),
        "chains": len(chains),
        "repeats": args.repeats,
        "models": args.models,
        "prompt_sha256": prompt_hash(policy),
        "schema_sha256": SCHEMA_SHA256,
        "budget_usd": args.budget_usd,
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
    }
    print(json.dumps({k: manifest[k] for k in ("items", "singles", "chains", "repeats", "models")}), flush=True)
    print(f"Planned requests: {calls_per_model} per model, {calls_per_model * len(specs)} in total", flush=True)
    if not args.live:
        return 0
    if not args.budget_usd or not 0 < args.budget_usd <= 60:
        raise SystemExit("Live runs need --budget-usd between 0 and 60")
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("items_sha256", "prompt_sha256", "schema_sha256", "pool"):
            if previous[key] != manifest[key]:
                raise SystemExit(f"Resume refused: {key} changed since this run started")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    calls_path = out / "calls.jsonl"
    _, done = load_done(calls_path, chains)
    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model_ids = frozenset(m for m, _ in specs)
    catalogue = await fetch_model_catalogue(model_ids=model_ids)
    missing = model_ids - set(catalogue)
    if missing:
        raise SystemExit(f"Not in the OpenRouter catalogue: {sorted(missing)}")
    ledger = BudgetLedger(Decimal(str(args.budget_usd)))
    lock = asyncio.Lock()
    handle = calls_path.open("a", encoding="utf-8")
    stopped = False

    async def write(rows):
        nonlocal stopped
        async with lock:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                stopped = stopped or row.get("budget_stopped")
            handle.flush()

    try:
        for model, provider in specs:
            client = OpenRouterEvalClient(
                api_key=api_key,
                catalogue=catalogue,
                ledger=ledger,
                provider_only=provider,
                approved_models=model_ids,
                timeout_seconds=args.timeout_seconds,
            )
            semaphore = asyncio.Semaphore(args.concurrency)
            try:
                for repeat in range(args.repeats):
                    if stopped:
                        break

                    async def single(item, repeat=repeat, client=client, model=model, semaphore=semaphore):
                        if stopped or (model, repeat, item["id"]) in done:
                            return
                        async with semaphore:
                            await write([await classify_single(client, model, repeat, item, config, policy)])

                    async def all_chains(repeat=repeat, client=client, model=model):
                        for chain in chains:
                            if stopped or all((model, repeat, i["id"]) in done for i in chain):
                                continue
                            await write(await replay_chain(client, model, repeat, chain, config, policy))

                    await asyncio.gather(all_chains(), *(single(i) for i in singles))
                    print(f"{model} repeat {repeat + 1}: done; spent ${float(ledger.committed_usd):.4f}", flush=True)
            finally:
                await client.aclose()
    finally:
        handle.close()
        manifest["budget"] = ledger.summary()
        manifest_path.write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print(json.dumps(manifest["budget"], default=str), flush=True)
    return 1 if stopped else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default="data/eval/suite/items.json")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--pool", choices=["dev", "locked", "all"], default="dev")
    parser.add_argument("--models", nargs="+", required=True, help="vendor/model or vendor/model@provider")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--name", required=True, help="Run folder under data/eval/suite/runs/")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--live", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
