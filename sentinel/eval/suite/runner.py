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
from sentinel.eval.suite.score import is_outage

RUNS = Path("data/eval/suite/runs")
SCHEMA_SHA256 = hashlib.sha256(json.dumps(CLASSIFICATION_SCHEMA, sort_keys=True).encode()).hexdigest()
# Provider-side failures (not the model's answer): retried, then recorded as unavailable.
TRANSIENT = {"timeout", "transport_error", "provider_error"}
# The key is wrong, out of credit or forbidden: stop instead of recording hundreds of outages.
FATAL_HTTP = {401, 402, 403}
RETRY_DELAYS = (3, 10, 30)


def _transient(completion: dict) -> bool:
    status = completion.get("http_status")
    kind = completion.get("error_kind")
    return kind in TRANSIENT or (kind == "http_error" and status is not None and (status == 429 or status >= 500))


# Failures raised before any request is sent: they cost nothing.
PRE_SEND = {
    "budget_exhausted",
    "model_not_approved",
    "model_not_in_catalogue",
    "reasoning_required",
    "max_tokens_unsupported",
}


def request_cost(completion: dict) -> float:
    """Billed cost, or the reservation the ledger kept when the provider reported none."""
    if completion.get("cost_usd") is not None:
        return completion["cost_usd"]
    if completion.get("error_kind") in PRE_SEND:
        return 0.0
    return completion.get("reserved_usd") or 0.0


async def complete_with_retry(client, model: str, messages: list[dict]) -> dict:
    """One model answer; provider overloads and network failures are retried with pauses.

    The cost of failed attempts is kept in ``retry_cost_usd`` so the budget sees it.
    """
    attempts, retry_cost = 0, 0.0
    while True:
        attempts += 1
        completion = (
            await client.complete(model_id=model, messages=messages, json_schema=CLASSIFICATION_SCHEMA)
        ).to_dict()
        if not _transient(completion) or attempts > len(RETRY_DELAYS):
            completion["attempts"] = attempts
            completion["retry_cost_usd"] = retry_cost
            return completion
        retry_cost += request_cost(completion)
        await asyncio.sleep(RETRY_DELAYS[attempts - 1])


def parse_model_spec(spec: str) -> tuple[str, list[str] | None, bool]:
    """``vendor/model[@provider][+reasoning]``.

    ``@provider`` pins the host with no fallback. ``+reasoning`` allows minimal ("low")
    reasoning, only for models that cannot run with reasoning off; results from such a
    model are not measured under production conditions and are labelled as such.
    """
    reasoning = spec.endswith("+reasoning")
    spec = spec.removesuffix("+reasoning")
    model, _, provider = spec.partition("@")
    return model, ([provider] if provider else None), reasoning


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


def base_row(spec: str, repeat: int, item: dict, messages: list[dict], completion: dict) -> dict:
    """``model`` is the full spec (host pin and reasoning flag included), so two setups of
    one model never mix; ``model_id`` is the bare catalogue id."""
    row = {
        "model": spec,
        "model_id": parse_model_spec(spec)[0],
        "reasoning": parse_model_spec(spec)[2],
        "repeat": repeat,
        "item_id": item["id"],
        "chain_id": item["chain_id"],
        "request_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        **{
            k: completion.get(k)
            for k in ("usage", "cost_usd", "reserved_usd", "latency_seconds", "provider", "request_id", "finish_reason")
        },
        "error_kind": completion.get("error_kind"),
        "http_status": completion.get("http_status"),
        "attempts": completion.get("attempts", 1),
        "retry_cost_usd": completion.get("retry_cost_usd", 0.0),
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


async def classify_single(client, spec: str, repeat: int, item: dict, config, policy: dict) -> dict:
    model = parse_model_spec(spec)[0]
    article = make_article({"id": item["id"], "article": item["article"]})
    messages = production_messages(article, [], policy)
    completion = await complete_with_retry(client, model, messages)
    row = base_row(spec, repeat, item, messages, completion)
    if completion.get("error"):
        return row
    try:
        result = validate_output(completion["data"], article, model, completion.get("usage") or {})
    except ValueError as exc:
        row.update(error_kind="invalid_output", error=str(exc), raw_content=json.dumps(completion["data"]))
        return row
    row.update(outcome_fields(result, config, completion["data"]))
    return row


async def replay_chain(client, spec: str, repeat: int, chain: list[dict], config, policy: dict) -> list[dict]:
    model = parse_model_spec(spec)[0]
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
            completion = await complete_with_retry(client, model, messages)
            row = base_row(spec, repeat, item, messages, completion)
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


def _retryable(row: dict) -> bool:
    """No answer because of an outage or a budget stop: redo it on resume."""
    return row.get("urgency") is None and is_outage(row)


def spent_so_far(rows: list[dict]) -> float:
    """Money committed by earlier sessions: every row ever written, superseded ones included."""
    return sum(request_cost(row) + (row.get("retry_cost_usd") or 0.0) for row in rows)


def load_done(path: Path, chains: list[list[dict]]) -> tuple[list[dict], set, float]:
    """Keep finished answers; supersede outages and any chain replay that is incomplete or had one.

    Superseded rows stay in the file (marked), so their cost is never forgotten.
    Returns the live rows, the (spec, repeat, item) keys already answered, and the money
    already spent by earlier sessions (so the budget cap spans resumes).
    """
    if not path.exists():
        return [], set(), 0.0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    spent = spent_so_far(rows)
    live = [r for r in rows if not r.get("superseded")]
    chain_size = {c[0]["chain_id"]: len(c) for c in chains}
    groups: dict[tuple, list[dict]] = {}
    for row in live:
        if row["chain_id"]:
            groups.setdefault((row["model"], row["repeat"], row["chain_id"]), []).append(row)
    broken = {
        key
        for key, group in groups.items()
        if len(group) != chain_size.get(key[2]) or any(_retryable(r) for r in group)
    }
    changed = False
    for row in live:
        drop = (row["chain_id"] and (row["model"], row["repeat"], row["chain_id"]) in broken) or (
            not row["chain_id"] and _retryable(row)
        )
        if drop:
            row["superseded"] = True
            changed = True
    if changed:
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    kept = [r for r in rows if not r.get("superseded")]
    return kept, {(r["model"], r["repeat"], r["item_id"]) for r in kept}, spent


async def run(args) -> int:
    data = json.loads(Path(args.items).read_text(encoding="utf-8"))
    items = select_items(data["items"], args.pool)
    if args.limit:
        # Smoke test: the first N single items only (no chains), for plumbing checks.
        items = [i for i in items if not i["chain_id"]][: args.limit]
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
        "timeout_seconds": args.timeout_seconds,
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
        for key in ("items_sha256", "prompt_sha256", "schema_sha256", "pool", "repeats", "timeout_seconds"):
            if previous.get(key) != manifest[key]:
                raise SystemExit(f"Resume refused: {key} changed since this run started")
        manifest["created_at"] = previous["created_at"]
        manifest["sessions"] = previous.get("sessions", [])
    manifest.setdefault("sessions", [])
    calls_path = out / "calls.jsonl"
    _, done, spent = load_done(calls_path, chains)
    remaining = args.budget_usd - spent
    if remaining <= 0:
        raise SystemExit(f"Budget used up: ${spent:.4f} of ${args.budget_usd} already spent in this run")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model_ids = frozenset(m for m, _, _ in specs)
    catalogue = await fetch_model_catalogue(model_ids=model_ids)
    missing = model_ids - set(catalogue)
    if missing:
        raise SystemExit(f"Not in the OpenRouter catalogue: {sorted(missing)}")
    ledger = BudgetLedger(Decimal(str(round(remaining, 6))))
    session = {"started_at": datetime.now(UTC).isoformat(), "spent_before_usd": spent, "stop_reason": None}
    lock = asyncio.Lock()
    handle = calls_path.open("a", encoding="utf-8")
    stopped = False

    async def write(rows):
        nonlocal stopped
        async with lock:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                if row.get("budget_stopped"):
                    stopped, session["stop_reason"] = True, "budget"
                elif row.get("http_status") in FATAL_HTTP:
                    stopped, session["stop_reason"] = True, f"http {row['http_status']} (key, credit or access)"
            handle.flush()

    try:
        for spec, (_model, provider, reasoning) in zip(args.models, specs, strict=True):
            client = OpenRouterEvalClient(
                reasoning={"effort": "low"} if reasoning else None,
                max_tokens=4096 if reasoning else 1024,
                max_reasoning_tokens=3072 if reasoning else 0,
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

                    async def single(item, repeat=repeat, client=client, spec=spec, semaphore=semaphore):
                        if stopped or (spec, repeat, item["id"]) in done:
                            return
                        async with semaphore:
                            if stopped:
                                return
                            await write([await classify_single(client, spec, repeat, item, config, policy)])

                    async def all_chains(repeat=repeat, client=client, spec=spec):
                        for chain in chains:
                            if stopped or all((spec, repeat, i["id"]) in done for i in chain):
                                continue
                            await write(await replay_chain(client, spec, repeat, chain, config, policy))

                    await asyncio.gather(all_chains(), *(single(i) for i in singles))
                    print(f"{spec} repeat {repeat + 1}: done; spent ${float(ledger.committed_usd):.4f}", flush=True)
            finally:
                await client.aclose()
    finally:
        handle.close()
        session["budget"] = ledger.summary()
        manifest["sessions"].append(session)
        manifest["spent_usd"] = spent + float(ledger.committed_usd)
        manifest_path.write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"spent_usd": manifest["spent_usd"], "stop_reason": session["stop_reason"]}), flush=True)
    return 1 if stopped else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default="data/eval/suite/items.json")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--pool", choices=["dev", "locked", "all"], default="dev")
    parser.add_argument("--models", nargs="+", required=True, help="vendor/model or vendor/model@provider")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--name", required=True, help="Run folder under data/eval/suite/runs/")
    parser.add_argument("--budget-usd", type=float, help="Total cap for this run, across resumes")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="Production uses 30 s")
    parser.add_argument("--limit", type=int, help="Smoke test: only the first N single items")
    parser.add_argument("--live", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
