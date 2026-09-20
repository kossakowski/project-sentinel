"""Policy resolution and controlled-context tests; all model responses are local fakes."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from sentinel.eval import compare_models
from sentinel.eval.clarified_policy import load_policy, messages, system_prompt
from sentinel.eval.compare_models import make_article, replay_reference
from sentinel.eval.reference_history import ReferenceHistory
from sentinel.eval.rescore_dimensions import rescore
from sentinel.eval.separate_metrics import aggregate_dimensions, score_dimensions


def policy_values():
    from pathlib import Path

    value = yaml.safe_load(Path("tests/fixtures/benchmark_policy_v2.yaml").read_text())
    value.update(status="resolved", near_border_strike="awareness", neutralised_drone="current_danger")
    return value


def case(name="a", same_as=None):
    return {
        "id": name,
        "sequence_id": "test-sequence",
        "split": "development",
        "label_status": "reviewed",
        "article": {
            "title": "Poland scrambled jets",
            "summary": "No incursion into Poland. Russian drones attacked Ukraine.",
            "source_name": "Test source",
            "source_url": f"synthetic://{name}",
            "source_type": "synthetic",
            "language": "en",
            "published_at": "2026-09-20T06:00:00+00:00",
            "fetched_at": "2026-09-20T06:00:00+00:00" if name == "a" else "2026-09-20T07:00:00+00:00",
        },
        "provenance": {"kind": "synthetic"},
        "rationale": "PRIVATE-ANNOTATION",
        "expected": {
            "relation": "same" if same_as else "new",
            **({"same_as": same_as} if same_as else {}),
            "notification": "silent" if same_as else "initial",
            "critical": False,
            "urgency_min": 5,
            "urgency_max": 6,
            "affected_countries": ["PL"],
            "facts": {"attack_countries": ["UA"], "protection": "precaution", "status": "active"},
        },
    }


def prediction(match=None):
    return {
        "is_military_event": True,
        "event_type": "troop_movement",
        "urgency_score": 5,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "is_new_event": match is None,
        "confidence": 0.9,
        "summary_pl": "Polska poderwała myśliwce prewencyjnie.",
        "facts": {
            "attack_countries": ["UA"],
            "protection": "precaution",
            "status": "active",
            "evidence": {
                "attack_countries": "Russian drones attacked Ukraine.",
                "protection": "Poland scrambled jets",
                "status": "",
            },
        },
        "incident_memory": {
            "decision": "duplicate" if match else "new",
            "matched_event_id": match,
            "confidence": 0.7,
            "reason": "Same explicitly linked episode",
        },
    }


def test_unresolved_operator_choices_cannot_be_run(tmp_path):
    pending = policy_values()
    pending["near_border_strike"] = "pending"
    path = tmp_path / "pending.yaml"
    path.write_text(yaml.safe_dump(pending))
    with pytest.raises(ValueError, match="Operator choice"):
        load_policy(str(path))


def test_resolved_policy_is_explicit_and_preserves_factual_geography(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy_values()))
    policy = load_policy(str(path))
    prompt = system_prompt(policy)
    assert "attack_countries" in prompt and "affected_countries" in prompt
    assert "CURRENT remaining danger" in prompt
    assert "confirmed strike inside Ukraine very close to Poland" in prompt
    other = {**policy, "neutralised_drone": "original_severity"}
    assert "retain original incident severity" in system_prompt(other)
    assert "historical/reaction band below does not override this Poland-only exception" in system_prompt(other)
    assert "memory must still identify later reports as the same incident" in system_prompt(other)
    assert "use resolved even in a retrospective report" in system_prompt(other)


def test_reference_history_hides_answers_and_skips_disputed_rows():
    history = ReferenceHistory()
    first = case()
    assert history.candidates() == []
    history.add(first)
    candidate = history.candidates()[0]
    assert "urgency_score" not in candidate and "countries" not in candidate
    assert candidate["evidence"][0]["summary"] == first["article"]["summary"]
    assert "PRIVATE-ANNOTATION" not in json.dumps(candidate)
    second = case("b", "a")
    second["label_status"] = "disputed"
    history.add(second)
    assert history.case_events["b"] is None
    assert len(history.candidates()[0]["evidence"]) == 1


@pytest.mark.asyncio
async def test_all_models_get_identical_reference_context_even_after_prior_failure(config):
    fixtures = [case(), case("b", "a")]

    class Client:
        def __init__(self, fail_first):
            self.fail_first, self.inputs = fail_first, []

        async def complete(self, *, model_id, messages, json_schema):
            assert list(json_schema["properties"])[0] == "facts"
            self.inputs.append(deepcopy(messages))
            payload = json.loads(messages[-1]["content"])
            references = payload["remembered_incidents"]
            data = prediction(references[0]["id"] if references else None)
            error = "timeout" if self.fail_first and len(self.inputs) == 1 else None
            result = {
                "data": None if error else data,
                "error": error,
                "usage": {},
                "cost_usd": None,
                "latency_seconds": 0,
                "budget_stopped": False,
            }
            return SimpleNamespace(to_dict=lambda: result)

    clients = [Client(False), Client(True)]
    results = [
        await replay_reference(fixtures, str(index), client, config, policy=policy_values())
        for index, client in enumerate(clients)
    ]
    assert clients[0].inputs == clients[1].inputs
    assert results[1][1]["evaluation"]["dimensions"]["raw_incident_identity"] is True
    assert results[1][1]["evaluation"]["dimensions"]["notification"] is None
    assert results[1][1]["evaluation"]["program_gate_rejection"] is False
    assert "PRIVATE-ANNOTATION" not in json.dumps(clients[0].inputs)


def test_reference_mode_does_not_count_unsent_notifications_as_missed():
    sample = case()
    row = {"data": prediction(), "context_mode": "reference", "candidate_ids": [], "notification": None}
    result = score_dimensions(sample, row, {})
    assert result["dimensions"]["urgency_action_band"] is True
    assert result["dimensions"]["notification"] is None
    assert result["required_notification_miss"] is False


@pytest.mark.parametrize(
    "memory",
    [
        {"decision": [], "matched_event_id": None},
        {"decision": "duplicate", "matched_event_id": []},
        {"decision": "duplicate", "matched_event_id": {}},
    ],
)
def test_malformed_matching_fields_never_crash_metrics(memory):
    sample = case("b", "a")
    data = prediction()
    data["incident_memory"] = memory
    result = score_dimensions(sample, {"data": data, "candidate_ids": ["event-a"]}, {"a": "event-a"})
    assert result["dimensions"]["raw_incident_identity"] is False


def test_api_rate_limit_is_a_transport_error_not_a_semantic_score():
    result = score_dimensions(case(), {"error": "http_error: HTTP 429", "error_kind": "http_error"}, {})
    assert result["transport_error"] is True
    assert result["dimensions"]["urgency_exact_range"] is None


def test_critical_repeated_report_does_not_count_as_required_missed_alert():
    sample = case("b", "a")
    sample["expected"].update(critical=True, urgency_min=9, urgency_max=10)
    result = score_dimensions(
        sample,
        {"data": prediction("event-a"), "notification": "silent", "candidate_ids": ["event-a"]},
        {"a": "event-a"},
    )
    assert result["critical_score_undercall"] is True
    assert result["required_critical_notification_miss"] is False


def test_policy_input_has_only_current_source_and_prior_history():
    payload = messages(make_article(case()), [], policy_values())
    user = json.loads(payload[-1]["content"])
    assert set(user) == {"evaluation_time", "article", "remembered_incidents"}
    assert "expected" not in user and "rationale" not in user


@pytest.mark.asyncio
async def test_version_two_inventory_needs_neither_resolved_policy_nor_network(tmp_path, monkeypatch):
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "policy_version": 2, "cases": [case()]}))

    def no_http(*args, **kwargs):
        raise AssertionError("Offline validation must not construct a network client")

    monkeypatch.setattr("httpx.AsyncClient", no_http)
    args = SimpleNamespace(dataset=str(path), live=False, catalog=False)
    assert await compare_models.main_async(args) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["pending_annotations", "legacy_annotations", "reviewed_not_approved"])
async def test_live_label_guards_run_before_any_network(tmp_path, monkeypatch, failure):
    sample = case()
    if failure == "pending_annotations":
        sample["expected"]["policy_pending"] = True
    data = {"version": 1, "policy_version": 2, "cases": [sample]}
    if failure == "legacy_annotations":
        del data["policy_version"]
    dataset_path = tmp_path / "cases.yaml"
    dataset_path.write_text(yaml.safe_dump(data))
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy_values()))

    def no_http(*args, **kwargs):
        raise AssertionError("Invalid labels must fail before even catalogue access")

    monkeypatch.setattr("httpx.AsyncClient", no_http)
    args = SimpleNamespace(
        dataset=str(dataset_path),
        live=True,
        catalog=False,
        policy_file=str(policy_path),
        split="development",
        allow_provisional=failure != "reviewed_not_approved",
    )
    reason = {
        "pending_annotations": "still await operator",
        "legacy_annotations": "legacy labels cannot be reused",
        "reviewed_not_approved": "Unapproved labels",
    }[failure]
    with pytest.raises(ValueError, match=reason):
        await compare_models.main_async(args)


@pytest.mark.parametrize(
    "update",
    [
        {"decision": []},
        {"matched_event_id": []},
        {"confidence": True},
        {"confidence": float("nan")},
        {"reason": []},
    ],
)
def test_clarified_prediction_rejects_invalid_memory_contract(update):
    data = prediction()
    data["incident_memory"].update(update)
    with pytest.raises(ValueError, match="incident-memory"):
        compare_models.parse_prediction(data, make_article(case()), "fake", {}, require_facts=True)


def test_disputed_label_does_not_hide_a_transport_failure():
    row = {"label_status": "disputed", "error": "http_error: HTTP 429", "error_kind": "http_error"}
    row["evaluation"] = score_dimensions(case(), row, {})
    summary = aggregate_dimensions([row])
    assert summary["main_scored"] == 0
    assert summary["transport_errors"] == 1


def test_metric_only_rescoring_preserves_reference_history_and_original_report():
    fixtures = [case(), case("b", "a")]
    history = ReferenceHistory()
    history.add(fixtures[0])
    anchor = history.case_events["a"]
    rows = []
    for index, fixture in enumerate(fixtures):
        rows.append(
            {
                "case_id": fixture["id"],
                "sequence_id": fixture["sequence_id"],
                "label_status": "reviewed",
                "context_mode": "reference",
                "candidate_ids": [anchor] if index else [],
                "data": prediction(anchor if index else None),
                "expected": fixture["expected"],
                "event_id": None,
            }
        )
    original = {"models": {"fake": {"cases": rows}}}
    before = deepcopy(original)
    result = rescore(original, fixtures)
    assert original == before
    scores = result["models"]["fake"]["separate_summary"]["dimensions"]
    assert scores["raw_incident_identity"] == {"correct": 2, "scored": 2}
    assert scores["notification"]["scored"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("context_mode", ["reference", "model"])
async def test_complete_v2_run_writes_separate_metrics_using_only_fake_requests(
    tmp_path, monkeypatch, sample_config_yaml, context_mode
):
    from sentinel.eval import openrouter_client

    dataset_path = tmp_path / "cases.yaml"
    dataset_path.write_text(yaml.safe_dump({"version": 1, "policy_version": 2, "cases": [case()]}))
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy_values()))
    output_path = tmp_path / "report.json"
    clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.calls, self.closed = 0, False
            clients.append(self)

        async def complete(self, **kwargs):
            self.calls += 1
            row = {
                "data": prediction(),
                "error": None,
                "usage": {},
                "cost_usd": 0,
                "latency_seconds": 0,
            }
            return SimpleNamespace(to_dict=lambda: row)

        async def aclose(self):
            self.closed = True

    async def fake_catalogue():
        return {"fake/model": object()}

    def no_http(*args, **kwargs):
        raise AssertionError("The end-to-end software test must never access a real API")

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-only-test-key")
    monkeypatch.setattr("httpx.AsyncClient", no_http)
    monkeypatch.setattr(openrouter_client, "OpenRouterEvalClient", FakeClient)
    monkeypatch.setattr(openrouter_client, "fetch_model_catalogue", fake_catalogue)
    args = SimpleNamespace(
        dataset=str(dataset_path),
        policy_file=str(policy_path),
        config=sample_config_yaml,
        live=True,
        catalog=False,
        models=["fake/model"],
        split="development",
        allow_provisional=True,
        budget_usd=1,
        output=str(output_path),
        context_mode=context_mode,
    )
    assert await compare_models.main_async(args) == 0
    assert clients[0].calls == 1 and clients[0].closed
    report = json.loads(output_path.read_text())
    assert report["run_finished"] is True
    assert report["context_mode"] == context_mode
    model = report["models"]["fake/model"]
    assert model["summary"]["metrics_version"] == 2
    assert model["summary"]["release_eligible"] is False
    assert "passed" not in model["summary"]
    assert model["cases"][0]["data"]["incident_memory"] == prediction()["incident_memory"]
    scores = model["summary"]["separate_dimensions"]["dimensions"]
    assert scores["attack_countries"] == {"correct": 1, "scored": 1}
    assert scores["notification"]["scored"] == (0 if context_mode == "reference" else 1)
    assert "fake-only-test-key" not in output_path.read_text()
