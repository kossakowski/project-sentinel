"""The comparison harness is exercised entirely with local model responses."""

import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from sentinel.classification.openai_provider import BudgetExceeded, ClassificationError, UsageLedger
from sentinel.config import ModelBudgetConfig
from sentinel.eval import jev_comparison as comparison
from sentinel.eval.clarified_policy import load_policy
from sentinel.eval.compare_models import load_dataset, make_config
from sentinel.eval.jev_questions import decode, validate_answers
from sentinel.eval.typesafe_client import TypeSafeEvalClient


@pytest.fixture
def settings():
    return comparison.load_settings("tests/fixtures/jev_evaluation.yaml")


@pytest.fixture
def prepared(settings):
    cases = load_dataset("tests/fixtures/model_comparison_v2_holdout.yaml")["cases"]
    sequence = cases[0]["sequence_id"]
    return comparison.prepare(
        [c for c in cases if c["sequence_id"] == sequence],
        make_config("config/config.example.yaml"),
        load_policy("tests/fixtures/benchmark_policy_v2.yaml"),
        settings,
    )


def fake_response(item):
    """A test oracle only; annotations never enter the real request builders."""
    expected = item["case"]["expected"]
    answers = {}
    for name, question in item["jev"]["questions"].items():
        if name == "urgency":
            value = str(expected["urgency_min"])
        elif name in {"status", "protection"}:
            value = expected["facts"][name]
        elif name.startswith("memory_"):
            candidate = item["jev"]["state"]["remembered_incidents"][int(name.removeprefix("memory_"))]
            value = "duplicate" if candidate["id"] == item["prior_events"].get(expected.get("same_as")) else "unrelated"
        elif name.startswith("affected_"):
            value = "yes" if name.removeprefix("affected_") in expected["affected_countries"] else "no"
        else:
            value = "yes" if name.removeprefix("attack_") in expected["facts"]["attack_countries"] else "no"
        answers[name] = {
            "type": "choice",
            "choice": value,
            "confidence": 1.0,
            "probabilities": {key: float(key == value) for key in question["criteria"]},
        }
    return {"model": item["jev"]["model"], "answers": answers, "usage": {"input_tokens": 2000, "output_tokens": 100}}


def set_choice(response, question, value):
    answer = response["answers"][question]
    answer["choice"] = value
    answer["probabilities"] = {key: float(key == value) for key in answer["probabilities"]}


def test_identical_source_context_and_no_annotation_leak(prepared):
    for item in prepared:
        assert item["jev"]["state"] == json.loads(item["luna"][1]["content"])
        text = json.dumps(item["jev"], ensure_ascii=False)
        assert item["case"]["rationale"] not in text
        assert '"expected"' not in text
        assert '"label_status"' not in text
        assert '"same_as"' not in text
    assert prepared[0]["jev"]["state"]["remembered_incidents"] == []
    assert prepared[-1]["jev"]["state"]["remembered_incidents"]


def test_correct_decisions_and_conflicting_candidate_matches(prepared, settings):
    item = prepared[2]  # Third article is a report on the second incident.
    raw = fake_response(item)
    data, diagnostics = decode(item["jev"], raw, settings)
    row = comparison.score_row(item, "jev", {"data": data, "raw_response": raw})
    assert all(value is True for value in row["evaluation"]["dimensions"].values())
    assert diagnostics["competing_matches"] == 1
    for name in raw["answers"]:
        if name.startswith("memory_"):
            set_choice(raw, name, "duplicate")
    data, diagnostics = decode(item["jev"], raw, settings)
    assert diagnostics["competing_matches"] > 1
    assert data["incident_memory"]["decision"] == "uncertain"
    assert data["incident_memory"]["matched_event_id"] is None


@pytest.mark.parametrize("defect", ["model", "missing", "nan", "wrong_winner", "sum", "extra"])
def test_reject_malformed_answers(prepared, defect):
    payload = prepared[0]["jev"]
    raw = fake_response(prepared[0])
    if defect == "model":
        raw["model"] = "jev-latest"
    elif defect == "missing":
        raw["answers"].pop("urgency")
    elif defect == "nan":
        raw["answers"]["urgency"]["confidence"] = float("nan")
    elif defect == "wrong_winner":
        raw["answers"]["urgency"]["choice"] = "10"
    elif defect == "sum":
        raw["answers"]["urgency"]["probabilities"]["10"] = 0.5
    else:
        raw["answers"]["invented"] = {}
    with pytest.raises(ValueError):
        validate_answers(payload, raw)


@pytest.mark.asyncio
async def test_mocked_comparison_reports_errors_without_real_alerts(prepared, settings):
    class Jev:
        async def request(self, payload):
            item = next(i for i in prepared if i["jev"] == payload)
            raw = fake_response(item)
            if item == prepared[1]:
                set_choice(raw, "urgency", "1")  # Deliberate high-confidence critical miss.
            return {"raw_response": raw, "cost_usd": 0.000084}

    class Luna:
        config = SimpleNamespace(max_tokens=1024)

        async def request(self, messages, schema, **kwargs):
            item = next(i for i in prepared if i["luna"] == messages)
            data, _ = decode(item["jev"], fake_response(item), settings)
            return SimpleNamespace(
                data=data,
                request_hash="test",
                response_id="test",
                cost_usd=0.001,
                input_tokens=1000,
                output_tokens=200,
                cached_tokens=0,
            )

    saved = []
    rows = await comparison.evaluate(prepared, Jev(), Luna(), settings, saved.append)
    assert rows == saved and len(rows) == 2 * len(prepared)
    report = comparison.summarize(rows, len(prepared), settings["confidence_review_threshold"])
    assert report["jev"]["critical_score_undercalls"] == 1
    assert report["luna"]["critical_score_undercalls"] == 0
    assert report["jev"]["high_confidence_errors"][0]["case_id"] == prepared[1]["case"]["id"]
    assert not report["release_eligible"]
    assert "notification" not in report["jev"]["dimensions"]
    assert len(report["disagreements"]) == 1


@pytest.mark.asyncio
async def test_offline_run_never_constructs_clients(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline mode constructed a provider")

    monkeypatch.setattr(comparison, "TypeSafeEvalClient", forbidden)
    monkeypatch.setattr(comparison, "OpenAIProvider", forbidden)
    args = comparison.parser().parse_args(["--output", str(tmp_path / "preview")])
    # The shipped example config deliberately retains the old runtime provider.
    config = make_config("config/config.example.yaml")
    config.classification.provider = "openai"
    config.classification.model = "gpt-5.6-luna"
    monkeypatch.setattr(comparison, "make_config", lambda path: config)
    assert await comparison.run(args) == 0
    manifest = json.loads((tmp_path / "preview/manifest.json").read_text())
    assert manifest["new_api_calls"] == 0 and not manifest["live"]
    assert not (tmp_path / "preview/usage.db").exists()
    with pytest.raises(FileExistsError):
        await comparison.run(args)


@pytest.mark.asyncio
async def test_client_charges_input_only_and_shares_budget(tmp_path, monkeypatch, settings, prepared):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-secret")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=fake_response(prepared[0]))

    path = tmp_path / "usage.db"
    client = TypeSafeEvalClient(settings, path, 0.01, transport=httpx.MockTransport(handler))
    try:
        reply = await client.request(prepared[0]["jev"])
        assert reply["cost_usd"] == pytest.approx(2000 * 0.042 / 1_000_000)
        other = UsageLedger(ModelBudgetConfig(ledger_path=str(path), monthly_usd=0.01))
        other.reserve(0.009, "luna-test", "test", "hash")
        other.close()
        with pytest.raises(BudgetExceeded):
            await client.request(prepared[0]["jev"])
        assert len(requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "http", "usage"])
async def test_failures_keep_reservations_without_retry_or_secret_leak(
    tmp_path, monkeypatch, settings, prepared, failure
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-secret")
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("test-secret")
        return httpx.Response(429, text="test-secret") if failure == "http" else httpx.Response(200, json={"usage": {}})

    client = TypeSafeEvalClient(settings, tmp_path / "usage.db", 0.1, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ClassificationError) as exc:
            await client.request(prepared[0]["jev"])
        assert "test-secret" not in str(exc.value)
        assert len(calls) == 1
        assert client.ledger.total() == pytest.approx(64000 * 0.042 / 1_000_000)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_api_failure_stops_paired_run(prepared, settings):
    class FailedJev:
        async def request(self, payload):
            raise ClassificationError("TypeSafe HTTP 402")

    rows = await comparison.evaluate(prepared, FailedJev(), None, settings, lambda row: None)
    assert len(rows) == 1 and rows[0]["error"] == "TypeSafe HTTP 402"


def test_disputed_labels_are_excluded_from_accuracy(prepared, settings):
    item = deepcopy(prepared[1])
    item["case"]["label_status"] = "disputed"
    raw = fake_response(item)
    set_choice(raw, "urgency", "1")
    data, _ = decode(item["jev"], raw, settings)
    row = comparison.score_row(item, "jev", {"data": data, "raw_response": raw})
    summary = comparison.summarize([row], 1, 0.9)
    assert summary["jev"]["dimensions"]["urgency_action_band"]["scored"] == 0
    assert summary["jev"]["critical_score_undercalls"] == 0


def test_settings_reject_credential_redirect(tmp_path, settings):
    import yaml

    settings["endpoint"] = "https://example.invalid/v1/systemone"
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError, match="official endpoint"):
        comparison.load_settings(path)


def test_rounded_live_probabilities_are_preserved(prepared):
    raw = fake_response(prepared[1])
    answer = raw["answers"]["urgency"]
    answer["choice"] = "10"
    answer["probabilities"] = {str(n): 0.0 for n in range(1, 11)}
    answer["probabilities"].update({"1": 0.01, "2": 0.01, "9": 0.4, "10": 0.5700000000000001})
    before = deepcopy(raw)
    validate_answers(prepared[1]["jev"], raw)
    assert raw == before
    assert sum(answer["probabilities"].values()) == pytest.approx(0.99)
    answer["probabilities"]["10"] = 0.3
    with pytest.raises(ValueError):
        validate_answers(prepared[1]["jev"], raw)


@pytest.mark.asyncio
async def test_saved_responses_recover_without_new_calls_and_reject_changed_requests(tmp_path, prepared, settings):
    manifest = {
        "dataset_sha256": "test",
        "policy_sha256": "test",
        "settings": settings,
        "luna_request_settings": {"model": "test"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    requests = [{"case_id": i["case"]["id"], "jev": i["jev"], "luna": i["luna"]} for i in prepared]
    (tmp_path / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in requests))
    (tmp_path / "report.json").write_text(json.dumps({"budget_usd": 0.25}))
    rows = []
    for item in prepared:
        raw = fake_response(item)
        data, _ = decode(item["jev"], raw, settings)
        for provider in ["jev", "luna"]:
            result = {"data": data, "cost_usd": 0.001, "latency_seconds": 2.0}
            if provider == "jev":
                result.update(raw_response=raw, error="Old local validation error")
            rows.append(comparison.score_row(item, provider, result))
    (tmp_path / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    original = (tmp_path / "results.jsonl").read_bytes()
    cached, _ = comparison.load_cached(tmp_path, manifest, prepared, settings)
    recovered = await comparison.evaluate(prepared, None, None, settings, lambda row: None, cached)
    assert len(recovered) == 2 * len(prepared)
    assert not any(row.get("error") for row in recovered)
    assert all(row["latency_seconds"] == 2 for row in recovered)
    assert (tmp_path / "results.jsonl").read_bytes() == original
    changed = deepcopy(prepared)
    changed[0]["jev"]["state"]["article"]["title"] = "Changed input"
    with pytest.raises(ValueError, match="exact model requests changed"):
        comparison.load_cached(tmp_path, manifest, changed, settings)
