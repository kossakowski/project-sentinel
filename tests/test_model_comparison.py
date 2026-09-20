"""Offline contract tests for the first-round model comparison runner."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy

import pytest
import yaml

from sentinel.eval import compare_models


def _case(
    case_id: str,
    *,
    sequence_id: str = "incident-1",
    split: str = "development",
    label_status: str = "approved",
    fetched_at: str = "2026-09-20T08:00:00+00:00",
    title: str | None = None,
    summary: str | None = None,
    source_url: str | None = None,
    relation: str = "new",
    same_as: str | None = None,
    notification: str = "initial",
    urgency_min: int = 7,
    urgency_max: int = 7,
    critical: bool = False,
) -> dict:
    expected = {
        "urgency_min": urgency_min,
        "urgency_max": urgency_max,
        "affected_countries": ["PL"],
        "notification": notification,
        "relation": relation,
        "critical": critical,
    }
    if same_as is not None:
        expected["same_as"] = same_as
    return {
        "id": case_id,
        "sequence_id": sequence_id,
        "split": split,
        "label_status": label_status,
        "provenance": {"kind": "synthetic", "note": f"PROVENANCE-{case_id}"},
        "article": {
            "title": title or f"TITLE-{case_id}",
            "summary": summary or f"SUMMARY-{case_id}",
            "source_name": f"SOURCE-{case_id}",
            "source_url": source_url or f"https://{case_id}.example/article",
            "source_type": "rss",
            "language": "en",
            "published_at": fetched_at,
            "fetched_at": fetched_at,
        },
        "expected": expected,
        "rationale": f"RATIONALE-{case_id}",
    }


def _write_dataset(tmp_path, cases: list[dict], *, version: int = 1):
    path = tmp_path / "dataset.yaml"
    path.write_text(
        yaml.safe_dump({"version": version, "description": "inline test set", "cases": cases}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _prediction(
    *,
    urgency: int,
    decision: str = "new",
    matched_event_id: str | None = None,
    summary: str = "Alarm wojskowy w Polsce",
) -> dict:
    return {
        "is_military_event": True,
        "event_type": "airspace_violation",
        "urgency_score": urgency,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "is_new_event": decision == "new",
        "confidence": 0.98,
        "summary_pl": summary,
        "incident_memory": {
            "decision": decision,
            "matched_event_id": matched_event_id,
            "confidence": 0.99,
            "reason": "Concrete incident facts match the requested test outcome",
        },
    }


class _Completion:
    def __init__(self, *, data=None, error=None, budget_stopped=False):
        self._row = {
            "data": data,
            "error": error,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "cost_usd": 0.001,
            "reserved_usd": 0.002,
            "latency_seconds": 0.01,
            "model": "test/model",
            "provider": "test-provider",
            "finish_reason": "stop" if error is None else None,
            "budget_stopped": budget_stopped,
        }

    def to_dict(self):
        return deepcopy(self._row)


class _ScriptedClient:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    async def complete(self, *, model_id, messages, json_schema):
        self.calls.append({"model_id": model_id, "messages": deepcopy(messages), "json_schema": deepcopy(json_schema)})
        return self.responder(len(self.calls) - 1, messages)


@pytest.mark.asyncio
async def test_low_tier_anchor_absence_is_unscorable_not_a_model_identity_error(config):
    config.classification.incident_memory.enabled = True
    cases = [
        _case("low-first", notification="silent", urgency_min=1, urgency_max=3),
        _case(
            "low-followup",
            fetched_at="2026-09-20T08:03:00+00:00",
            notification="silent",
            urgency_min=1,
            urgency_max=3,
            relation="same",
            same_as="low-first",
        ),
    ]
    rows = await compare_models.replay(
        cases, "test/model", _ScriptedClient(lambda *_args: _Completion(data=_prediction(urgency=3))), config
    )
    assert rows[1]["identity_unscorable"] is True
    assert "incident_identity" not in rows[1]["checks"]
    assert rows[1]["notification"] == "silent"


@pytest.mark.asyncio
async def test_missed_critical_anchor_does_not_hide_later_identity_failure(config):
    config.classification.incident_memory.enabled = True
    cases = [
        _case("critical-first", urgency_min=9, urgency_max=10, critical=True),
        _case(
            "critical-followup",
            fetched_at="2026-09-20T08:03:00+00:00",
            notification="silent",
            urgency_min=9,
            urgency_max=10,
            critical=True,
            relation="same",
            same_as="critical-first",
        ),
    ]
    rows = await compare_models.replay(
        cases,
        "test/model",
        _ScriptedClient(lambda index, _messages: _Completion(data=_prediction(urgency=3 if index == 0 else 9))),
        config,
    )
    assert rows[0]["critical_miss"] is True
    assert rows[1]["identity_unscorable"] is False
    assert rows[1]["checks"]["incident_identity"] is False


def _remembered_incidents(messages: list[dict]) -> list[dict]:
    prompt = messages[-1]["content"]
    marker = "Remembered incidents (JSON source data):\n"
    memory_json = prompt.split(marker, 1)[1].split("\nInclude incident_memory", 1)[0]
    return json.loads(memory_json)


def test_load_dataset_rejects_incident_crossing_splits(tmp_path):
    first = _case("first")
    second = _case("second", split="holdout", fetched_at="2026-09-20T09:00:00+00:00")
    path = _write_dataset(tmp_path, [first, second])

    with pytest.raises(ValueError, match="Incident leaks across splits"):
        compare_models.load_dataset(str(path))


@pytest.mark.parametrize("payload", [None, {}, {"version": 1, "cases": []}])
def test_load_dataset_rejects_empty_dataset(tmp_path, payload):
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="version 1 and a nonempty cases list"):
        compare_models.load_dataset(str(path))


@pytest.mark.parametrize("label", ["", "unreviewed", None, 7])
def test_load_dataset_rejects_invalid_label_status(tmp_path, label):
    path = _write_dataset(tmp_path, [_case("bad-label", label_status=label)])

    with pytest.raises(ValueError, match="Invalid label status"):
        compare_models.load_dataset(str(path))


@pytest.mark.parametrize("reference", [None, "missing", "later", "other-sequence"])
def test_same_relation_requires_an_earlier_case_in_the_same_sequence(tmp_path, reference):
    first = _case(
        "first",
        relation="same",
        same_as=reference,
        notification="silent",
        fetched_at="2026-09-20T08:00:00+00:00",
    )
    later = _case("later", fetched_at="2026-09-20T09:00:00+00:00")
    other = _case("other-sequence", sequence_id="incident-2", fetched_at="2026-09-20T07:00:00+00:00")
    path = _write_dataset(tmp_path, [first, later, other])

    with pytest.raises(ValueError, match="same_as must reference"):
        compare_models.load_dataset(str(path))


@pytest.mark.asyncio
async def test_replay_is_chronological_uses_runtime_memory_and_does_not_leak_labels(sample_config_yaml, monkeypatch):
    cases = [
        _case(
            "future-wave",
            fetched_at="2026-09-20T10:00:00+00:00",
            title="FUTURE-DATA-MARKER new drone wave tonight",
            summary="A distinct second drone wave crossed Poland tonight",
            urgency_min=9,
            urgency_max=9,
            critical=True,
        ),
        _case(
            "initial",
            fetched_at="2026-09-20T08:00:00+00:00",
            title="INITIAL-MARKER drone crossed Poland",
            summary="A drone crossed Poland near Lublin this morning",
        ),
        _case(
            "escalation",
            fetched_at="2026-09-20T11:00:00+00:00",
            title="ESCALATION-MARKER impact confirmed",
            summary="The same Lublin drone incident now has a confirmed impact",
            relation="same",
            same_as="initial",
            notification="update",
            urgency_min=9,
            urgency_max=9,
            critical=True,
        ),
        _case(
            "duplicate",
            fetched_at="2026-09-20T09:00:00+00:00",
            title="DUPLICATE-MARKER second outlet confirms crossing",
            summary="The same morning drone crossed Poland near Lublin",
            relation="same",
            same_as="initial",
            notification="silent",
            source_url="https://independent.example/duplicate",
        ),
    ]

    def fail_real_push_client(*_args, **_kwargs):
        raise AssertionError("replay attempted to construct a real push transport")

    monkeypatch.setattr("sentinel.alerts.state_machine.ExpoPushClient", fail_real_push_client)

    def respond(index, messages):
        prompt = messages[-1]["content"]
        current_article = prompt.split("Remembered incidents (JSON source data):", 1)[0]
        if "INITIAL-MARKER" in current_article:
            return _Completion(data=_prediction(urgency=7, summary="Dron przekroczył granicę koło Lublina"))
        if "DUPLICATE-MARKER" in current_article:
            initial = next(item for item in _remembered_incidents(messages) if "Lublina" in item["summary_pl"])
            return _Completion(
                data=_prediction(
                    urgency=7,
                    decision="duplicate",
                    matched_event_id=initial["id"],
                    summary="Dron przekroczył granicę koło Lublina",
                )
            )
        if "FUTURE-DATA-MARKER" in current_article:
            return _Completion(data=_prediction(urgency=9, summary="Nowa fala dronów nad Polską"))
        initial = next(item for item in _remembered_incidents(messages) if "Lublina" in item["summary_pl"])
        return _Completion(
            data=_prediction(
                urgency=9,
                decision="escalation",
                matched_event_id=initial["id"],
                summary="Potwierdzono uderzenie drona koło Lublina",
            )
        )

    client = _ScriptedClient(respond)
    config = compare_models.make_config(sample_config_yaml)
    rows = await compare_models.replay(cases, "test/model", client, config)

    assert [row["case_id"] for row in rows] == ["initial", "duplicate", "future-wave", "escalation"]
    assert [row["notification"] for row in rows] == ["initial", "silent", "initial", "update"]
    assert all(row["passed"] for row in rows)
    assert rows[1]["event_id"] == rows[0]["event_id"]
    assert rows[2]["event_id"] != rows[0]["event_id"]
    assert rows[3]["event_id"] == rows[0]["event_id"]
    assert rows[1]["candidate_ids"]
    assert rows[3]["accepted_memory"]["decision"] == "escalation"
    assert "phone_call" in rows[3]["channels"]

    ordered_markers = ["INITIAL-MARKER", "DUPLICATE-MARKER", "FUTURE-DATA-MARKER", "ESCALATION-MARKER"]
    forbidden = [
        '"split"',
        '"expected"',
        "urgency_min",
        "same_as",
    ]
    for index, call in enumerate(client.calls):
        serialized = json.dumps(call["messages"], ensure_ascii=False)
        assert all(f"RATIONALE-{case['id']}" not in serialized for case in cases)
        assert all(f"PROVENANCE-{case['id']}" not in serialized for case in cases)
        assert all(marker not in serialized for marker in forbidden)
        assert all(future not in serialized for future in ordered_markers[index + 1 :])
    assert all(call["model_id"] == "test/model" for call in client.calls)
    assert all(call["json_schema"] == compare_models.RESPONSE_SCHEMA for call in client.calls)


@pytest.mark.parametrize(
    ("rows", "planned"),
    [
        ([{"label_status": "provisional", "split": "holdout", "passed": True}], 1),
        ([{"label_status": "reviewed", "split": "holdout", "passed": True}], 1),
        ([{"label_status": "disputed", "split": "holdout", "passed": True}], 1),
        ([{"label_status": "approved", "split": "holdout", "passed": True}], 2),
        ([{"label_status": "approved", "split": "development", "passed": True}], 1),
        ([{"label_status": "approved", "split": "holdout", "error": "mock timeout"}], 1),
    ],
)
def test_release_is_never_eligible_for_provisional_disputed_or_incomplete_results(rows, planned):
    assert compare_models.summarize(rows, planned)["release_eligible"] is False


def test_complete_approved_holdout_is_release_eligible_even_when_model_has_scored_misses():
    rows = [{"label_status": "approved", "split": "holdout", "passed": False, "error": None}]

    assert compare_models.summarize(rows, planned=1)["release_eligible"] is True


@pytest.mark.asyncio
async def test_replay_counts_mocked_errors_and_stops_after_budget_exhaustion(sample_config_yaml):
    cases = [
        _case("provider-error", fetched_at="2026-09-20T08:00:00+00:00", critical=True),
        _case("budget-stop", fetched_at="2026-09-20T09:00:00+00:00"),
        _case("must-not-run", fetched_at="2026-09-20T10:00:00+00:00"),
    ]

    def respond(index, _messages):
        if index == 0:
            return _Completion(error="timeout: mocked failure")
        return _Completion(error="budget_exhausted: mocked limit", budget_stopped=True)

    client = _ScriptedClient(respond)
    rows = await compare_models.replay(cases, "test/model", client, compare_models.make_config(sample_config_yaml))
    summary = compare_models.summarize(rows, len(cases))

    assert [row["case_id"] for row in rows] == ["provider-error", "budget-stop"]
    assert len(client.calls) == 2
    assert summary["attempted"] == 2
    assert summary["error"] == 2
    assert summary["critical_miss"] == 1
    assert summary["release_eligible"] is False


@pytest.mark.asyncio
async def test_default_main_only_validates_dataset_without_api_access(tmp_path, monkeypatch, capsys):
    path = _write_dataset(tmp_path, [_case("offline")])

    class NoNetworkClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("offline validation attempted to construct an HTTP client")

    monkeypatch.setattr("httpx.AsyncClient", NoNetworkClient)
    args = argparse.Namespace(dataset=str(path), live=False, catalog=False)

    assert await compare_models.main_async(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["cases"] == 1
    assert output["approved_for_release"] is True
