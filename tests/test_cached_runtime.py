"""Offline contracts for replaying saved model responses through runtime logic."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from sentinel.eval import cached_runtime, compare_models
from sentinel.eval.clarified_policy import load_policy, prompt_hash

MODEL = "test/cached-model"
POLICY_PATH = "tests/fixtures/benchmark_policy_v2.yaml"


def _case(case_id: str, fetched_at: str, *, relation: str = "new", same_as: str | None = None) -> dict:
    expected = {
        "urgency_min": 7,
        "urgency_max": 8,
        "affected_countries": ["PL"],
        "notification": "initial" if relation == "new" else "silent",
        "relation": relation,
        "critical": False,
        "facts": {
            "attack_countries": ["PL"],
            "protection": "none",
            "status": "active",
        },
    }
    if same_as:
        expected["same_as"] = same_as
    return {
        "id": case_id,
        "sequence_id": "cached-sequence",
        "split": "development",
        "label_status": "approved",
        "provenance": {"kind": "synthetic"},
        "rationale": "Cached runtime replay test",
        "article": {
            "title": f"Drone incident {case_id}",
            "summary": "A Russian military drone crossed Polish airspace near Lublin.",
            "source_name": f"Source {case_id}",
            "source_url": f"https://{case_id}.example/news",
            "source_type": "rss",
            "language": "en",
            "published_at": fetched_at,
            "fetched_at": fetched_at,
        },
        "expected": expected,
    }


def _prediction(*, decision: str = "new", event_id: str | None = None) -> dict:
    return {
        "facts": {
            "attack_countries": ["PL"],
            "protection": "none",
            "status": "active",
            "evidence": {
                "attack_countries": "crossed Polish airspace",
                "protection": "",
                "status": "crossed",
            },
        },
        "is_military_event": True,
        "event_type": "airspace_violation",
        "urgency_score": 7,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "is_new_event": decision == "new",
        "confidence": 0.99,
        "summary_pl": "Rosyjski dron naruszył polską przestrzeń powietrzną koło Lublina.",
        "incident_memory": {
            "decision": decision,
            "matched_event_id": event_id,
            "confidence": 0.99,
            "reason": "The same concrete drone incident is explicitly described.",
        },
    }


class _Completion:
    def __init__(self, data=None, error: str | None = None):
        self.data = data
        self.error = error

    def to_dict(self) -> dict:
        return {
            "data": deepcopy(self.data),
            "error": self.error,
            "error_kind": "refusal" if self.error else None,
            "http_status": None,
            "usage": {
                "prompt_tokens": 100,
                "cached_tokens": 80,
                "completion_tokens": 20,
                "total_tokens": 120,
                "reasoning_tokens": 0,
            },
            "cost_usd": 0.001,
            "reserved_usd": 0.01,
            "latency_seconds": 2.5,
            "request_id": "saved-request",
            "requested_model": MODEL,
            "model": MODEL,
            "provider": "SavedProvider",
            "finish_reason": None if self.error else "stop",
            "reasoning": None,
            "reasoning_mode": False,
            "provider_latency_seconds": 2.0,
            "budget_stopped": False,
        }


class _SourceClient:
    def __init__(self, *, refuse_second: bool = False):
        self.calls = 0
        self.refuse_second = refuse_second

    async def complete(self, *, model_id, messages, json_schema):
        del model_id, json_schema
        self.calls += 1
        if self.calls == 1:
            return _Completion(_prediction())
        if self.refuse_second:
            return _Completion(error="refusal: saved provider refusal")
        candidates = json.loads(messages[-1]["content"])["remembered_incidents"]
        return _Completion(_prediction(decision="duplicate", event_id=candidates[0]["id"]))


async def _source_report(tmp_path: Path, config_path: str, *, refuse_second: bool = False):
    cases = [
        _case("cached-a", "2026-09-20T08:00:00+00:00"),
        _case("cached-b", "2026-09-20T08:05:00+00:00", relation="same", same_as="cached-a"),
    ]
    dataset_path = tmp_path / "dataset.yaml"
    dataset_path.write_text(
        yaml.safe_dump(
            {"version": 1, "policy_version": 2, "description": "cached test", "cases": cases},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    policy = load_policy(POLICY_PATH)
    config = compare_models.make_config(config_path)
    rows = await compare_models.replay(cases, MODEL, _SourceClient(refuse_second=refuse_second), config, policy=policy)
    report = {
        "run_finished": True,
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "prompt_sha256": prompt_hash(policy),
        "classification_config": config.classification.model_dump(),
        "alert_levels": {name: value.model_dump() for name, value in config.alerts.urgency_levels.items()},
        "evaluation_policy": policy,
        "context_mode": "model",
        "models": {MODEL: {"summary": compare_models.summarize_v2(rows, len(cases)), "cases": rows}},
    }
    report_path = tmp_path / "source.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path, dataset_path, rows


@pytest.mark.asyncio
async def test_offline_replay_rebuilds_identical_inputs_and_original_event_ids(
    tmp_path, sample_config_yaml, monkeypatch
):
    report_path, dataset_path, source_rows = await _source_report(tmp_path, sample_config_yaml)
    original_event_id = source_rows[0]["event_id"]
    source = json.loads(report_path.read_text(encoding="utf-8"))
    # These are runtime-derived fields and must never be used as cached model output.
    source["models"][MODEL]["cases"][1]["accepted_memory"] = {"decision": "poisoned"}
    source["models"][MODEL]["cases"][1]["evaluation"] = {"poisoned": True}
    report_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    source_before = report_path.read_bytes()
    output = tmp_path / "derived.json"

    def no_network(*_args, **_kwargs):
        raise AssertionError("cached replay attempted network access")

    monkeypatch.setattr("httpx.AsyncClient", no_network)
    code, derived = await cached_runtime.replay_report(
        report_path=report_path,
        dataset_path=dataset_path,
        config_path=Path(sample_config_yaml),
        output_path=output,
    )

    rows = derived["models"][MODEL]["cases"]
    assert code == 0
    assert [row["event_id"] for row in rows] == [original_event_id, original_event_id]
    assert rows[1]["candidate_ids"] == [original_event_id]
    assert rows[1]["accepted_memory"]["decision"] == "duplicate"
    assert rows[1]["evaluation"] != {"poisoned": True}
    assert rows[0]["provider"] == "SavedProvider"
    assert rows[0]["cost_usd"] == 0.001
    assert derived["cached_offline"] is True
    assert derived["new_api_requests"] == 0
    assert derived["new_api_cost_usd"] == 0.0
    assert derived["models"][MODEL]["summary"]["metrics_version"] == 2
    assert report_path.read_bytes() == source_before
    assert json.loads(output.read_text(encoding="utf-8")) == derived


@pytest.mark.asyncio
async def test_cached_client_refuses_changed_model_input_before_releasing_response():
    messages = [{"role": "user", "content": "original"}]
    row = {
        "case_id": "changed",
        "requested_model": MODEL,
        "request_sha256": cached_runtime._messages_sha256(messages),
        "data": _prediction(),
    }
    client = cached_runtime.CachedClient(MODEL, [row])

    with pytest.raises(ValueError, match="Cached request hash mismatch"):
        await client.complete(
            model_id=MODEL,
            messages=[{"role": "user", "content": "changed"}],
            json_schema={},
        )
    assert client.calls == 0


@pytest.mark.asyncio
async def test_saved_refusal_row_is_replayed_without_model_or_network_call(tmp_path, sample_config_yaml):
    report_path, dataset_path, _ = await _source_report(tmp_path, sample_config_yaml, refuse_second=True)
    output = tmp_path / "refusal-derived.json"

    code, derived = await cached_runtime.replay_report(
        report_path=report_path,
        dataset_path=dataset_path,
        config_path=Path(sample_config_yaml),
        output_path=output,
    )

    refusal = derived["models"][MODEL]["cases"][1]
    assert code == 1
    assert refusal["error"] == "refusal: saved provider refusal"
    assert refusal["error_kind"] == "refusal"
    assert refusal["provider"] == "SavedProvider"


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["dataset", "config", "output"])
async def test_preflight_refuses_dataset_config_and_output_mismatches(
    mismatch, tmp_path, sample_config_yaml, sample_config_dict
):
    report_path, dataset_path, _ = await _source_report(tmp_path, sample_config_yaml)
    output = tmp_path / "derived.json"
    selected_dataset = dataset_path
    selected_config = Path(sample_config_yaml)
    expected = {
        "dataset": "Dataset SHA-256 mismatch",
        "config": "classification settings differ",
        "output": "refusing to overwrite",
    }[mismatch]

    if mismatch == "dataset":
        changed = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
        changed["cases"][0]["article"]["title"] = "Changed input"
        selected_dataset = tmp_path / "changed-dataset.yaml"
        selected_dataset.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    elif mismatch == "config":
        changed = deepcopy(sample_config_dict)
        changed["classification"]["summary_similarity_threshold"] += 1
        selected_config = tmp_path / "changed-config.yaml"
        selected_config.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    else:
        output.write_text("preserve me", encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        await cached_runtime.replay_report(
            report_path=report_path,
            dataset_path=selected_dataset,
            config_path=selected_config,
            output_path=output,
        )
    if mismatch == "output":
        assert output.read_text(encoding="utf-8") == "preserve me"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_finished", False, "unfinished"),
        ("context_mode", "reference", "context_mode=model"),
        ("prompt_sha256", "0" * 64, "Prompt SHA-256 mismatch"),
    ],
)
async def test_source_report_must_be_finished_model_context_with_matching_policy_prompt(
    field, value, message, tmp_path, sample_config_yaml
):
    report_path, dataset_path, _ = await _source_report(tmp_path, sample_config_yaml)
    source = json.loads(report_path.read_text(encoding="utf-8"))
    source[field] = value
    report_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        await cached_runtime.replay_report(
            report_path=report_path,
            dataset_path=dataset_path,
            config_path=Path(sample_config_yaml),
            output_path=tmp_path / "never-written.json",
        )
