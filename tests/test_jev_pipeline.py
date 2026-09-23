"""Full local routing checks with deterministic predictions, never paid requests."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from sentinel.classification.openai_provider import ClassificationError
from sentinel.eval import jev_pipeline
from sentinel.eval.clarified_policy import load_policy
from sentinel.eval.compare_models import load_dataset, make_article, make_config
from sentinel.eval.jev_comparison import load_settings
from sentinel.eval.jev_pipeline_questions import build_pipeline_request, decode_pipeline, enforce_geography
from sentinel.models import ClassificationResult


@pytest.fixture
def cases():
    return load_dataset("tests/fixtures/jev_pipeline_fresh.yaml")["cases"]


@pytest.fixture
def settings():
    return load_settings("tests/fixtures/jev_pipeline.yaml")


@pytest.fixture
def config():
    result = make_config("config/config.example.yaml")
    result.classification.corroboration_required = 1
    for level in result.alerts.urgency_levels.values():
        level.corroboration_required = 1
    return result


def response(payload, selected):
    answers = {}
    for name, question in payload["questions"].items():
        options = question["criteria"]
        value = selected.get(name, "no" if "no" in options else "none" if "none" in options else next(iter(options)))
        answers[name] = {
            "type": "choice",
            "choice": value,
            "confidence": 1.0,
            "probabilities": {key: float(key == value) for key in options},
        }
    return {"model": payload["model"], "answers": answers}


def test_full_names_and_geography_invariant_preserve_raw_answers(cases, settings):
    article = make_article(cases[0])
    policy = load_policy("tests/fixtures/benchmark_policy_v2.yaml")
    payload = build_pipeline_request(article, [], policy, settings)
    assert "Latvia (Łotwa" in payload["questions"]["affected_LV"]["instructions"]["question"]
    assert "Lithuania (Litwa" in payload["questions"]["affected_LT"]["instructions"]["question"]
    raw = response(payload, {"attack_PL": "yes", "affected_PL": "no", "urgency": "10", "military": "yes"})
    before = deepcopy(raw)
    result, diagnostics = decode_pipeline(payload, raw, settings, policy["monitored_countries"])
    assert result["affected_countries"] == ["PL"]
    assert diagnostics["raw_affected_countries"] == [] and diagnostics["added_affected_countries"] == ["PL"]
    assert raw == before
    assert all(
        value == "" or value in article.title or value in article.summary
        for value in result["facts"]["evidence"].values()
    )


def test_ukrainian_attack_does_not_add_monitored_country():
    source = {"affected_countries": [], "facts": {"attack_countries": ["UA"]}}
    result, added = enforce_geography(source, ["PL", "LT", "LV", "EE"])
    assert result == source and added == []


def test_identity_confidence_is_separate_from_update_label(cases, settings):
    policy = load_policy("tests/fixtures/benchmark_policy_v2.yaml")
    payload = build_pipeline_request(
        make_article(cases[1]), [{"id": "episode", "summary_pl": "Prior article"}], policy, settings
    )
    raw = response(payload, {"memory_0": "duplicate", "identity_0": "same"})
    raw["answers"]["memory_0"].update(
        confidence=0.1,
        probabilities={"duplicate": 0.51, "update": 0.49, "escalation": 0, "unrelated": 0, "uncertain": 0},
    )
    data, _ = decode_pipeline(payload, raw, settings, policy["monitored_countries"])
    assert data["incident_memory"]["confidence"] == 1
    assert data["incident_memory"]["decision"] == "duplicate"
    raw["answers"]["identity_0"] = {
        "type": "choice",
        "choice": "different",
        "confidence": 1,
        "probabilities": {"same": 0, "different": 1, "uncertain": 0},
    }
    data, diagnostics = decode_pipeline(payload, raw, settings, policy["monitored_countries"])
    assert data["incident_memory"]["decision"] == "uncertain"
    assert diagnostics["identity_conflicts"] == ["episode"]


def oracle(cases, *, weak_identity=False):
    by_id = {c["id"]: c for c in cases}

    async def classify(provider, article, candidates):
        case = by_id[article.id]
        expected = case["expected"]
        decision = expected["incident_decisions"][0]
        target = (
            str(uuid5(NAMESPACE_URL, f"jev-pipeline:{provider}:{expected['same_as']}"))
            if expected["relation"] == "same"
            else None
        )
        if target:
            assert target in [c["id"] for c in candidates]
        facts = {**expected["facts"], "evidence": {key: "" for key in ("attack_countries", "protection", "status")}}
        result = ClassificationResult(
            article_id=article.id,
            is_military_event=bool(facts["attack_countries"] or expected["urgency_min"] >= 5),
            event_type="missile_strike",
            urgency_score=expected["urgency_min"],
            affected_countries=expected["affected_countries"],
            aggressor="unknown",
            is_new_event=decision == "new",
            confidence=1,
            summary_pl="To jest testowe podsumowanie informacji o zdarzeniu. Szczegóły podano w dołączonym źródle.",
            incident_memory={
                "decision": decision,
                "matched_event_id": target,
                "confidence": 0.1 if weak_identity and target else 1,
                "reason": "Deterministic local test oracle.",
            },
            facts=facts,
            classified_at=article.fetched_at,
            model_used="offline-oracle",
            input_tokens=0,
            output_tokens=0,
        )
        return result, {}

    return classify


@pytest.mark.asyncio
async def test_complete_recording_alert_pipeline_has_one_call_per_episode(cases, config, monkeypatch):
    import httpx

    async def network_forbidden(*args, **kwargs):
        pytest.fail("A recording-transport replay attempted network access")

    monkeypatch.setattr(httpx.AsyncClient, "send", network_forbidden)
    rows = await jev_pipeline.replay_pipeline(cases, config, oracle(cases), lambda row: None)
    report = jev_pipeline.summarize(rows, cases)
    assert len(rows) == 80 and not any(r.get("error") for r in rows)
    for provider in ("jev", "luna"):
        section = report["models"][provider]
        assert section["simulated_channels"]["phone_call"] == 8
        assert section["dimensions"]["notification"] == {"correct": 40, "scored": 40}
        assert section["flags"]["required_critical_notification_miss"] == 0
        assert section["flags"]["duplicate_notification"] == 0
        assert section["non_polish_summaries"] == 0
    assert not report["release_eligible"]


@pytest.mark.asyncio
async def test_uncalibrated_identity_confidence_exposes_repeat_alerts(cases, config):
    rows = await jev_pipeline.replay_pipeline(cases[:3], config, oracle(cases, weak_identity=True), lambda row: None)
    report = jev_pipeline.summarize(rows, cases[:3])
    assert report["models"]["jev"]["flags"]["program_gate_rejection"] > 0
    assert report["models"]["jev"]["flags"]["duplicate_notification"] > 0


@pytest.mark.asyncio
async def test_error_is_not_a_safe_prediction(cases, config):
    async def unavailable(*args):
        raise ClassificationError("Provider unavailable")

    rows = await jev_pipeline.replay_pipeline(cases, config, unavailable, lambda row: None)
    assert len(rows) == 1 and rows[0]["evaluation"]["required_critical_notification_miss"]


@pytest.mark.asyncio
async def test_offline_preflight_never_opens_providers(tmp_path, config, monkeypatch):
    config.classification.provider = "openai"
    config.classification.model = "gpt-5.6-luna"
    monkeypatch.setattr(jev_pipeline, "make_config", lambda path: config)
    monkeypatch.setattr(jev_pipeline, "PipelineModels", lambda *args: pytest.fail("Constructed paid clients"))
    args = jev_pipeline.parser().parse_args(["--output", str(tmp_path / "preview")])
    assert await jev_pipeline.run(args) == 0
    saved = json.loads((tmp_path / "preview/manifest.json").read_text())
    assert saved["inventory"]["cases"] == 40 and not saved["live"]
    assert not (tmp_path / "preview/usage.db").exists()


def test_invalid_optional_quote_cannot_discard_a_valid_critical_decision(cases, settings):
    policy = load_policy("tests/fixtures/benchmark_policy_v2.yaml")
    payload = build_pipeline_request(make_article(cases[0]), [], policy, settings)
    raw = response(payload, {"attack_PL": "yes", "urgency": "10", "military": "yes"})
    raw["answers"]["evidence_attack_countries"]["choice"] = "span_1"  # Winner disagrees with probabilities.
    data, diagnostics = decode_pipeline(payload, raw, settings, policy["monitored_countries"])
    assert data["urgency_score"] == 10 and data["affected_countries"] == ["PL"]
    assert data["facts"]["evidence"]["attack_countries"] == ""
    assert "attack_countries" in diagnostics["evidence_validation_errors"]
    raw["answers"]["urgency"]["choice"] = "1"
    with pytest.raises(ValueError, match="winning choice"):
        decode_pipeline(payload, raw, settings, policy["monitored_countries"])


@pytest.mark.asyncio
async def test_resume_reuses_exact_jev_and_writer_calls_without_network(tmp_path, cases, settings, config, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Sent a new paid request instead of replaying the saved response")

    monkeypatch.setattr(
        jev_pipeline, "Classifier", lambda cfg: SimpleNamespace(provider=SimpleNamespace(request=forbidden))
    )
    monkeypatch.setattr(jev_pipeline, "TypeSafeEvalClient", lambda *args: SimpleNamespace(request=forbidden))
    article = make_article(cases[0])
    policy = load_policy("tests/fixtures/benchmark_policy_v2.yaml")
    payload = build_pipeline_request(article, [], policy, settings)
    summary = "Wrogi pocisk nadal znajduje się nad Polską. Nie wydano ostrzeżenia dla mieszkańców."
    cached = {
        ("typesafe", "jev", article.id, None): {
            "request": payload,
            "raw_response": response(payload, {"attack_PL": "yes", "military": "yes", "urgency": "10"}),
            "request_sha256": "hash",
            "cost_usd": 0.001,
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
        ("openai", "jev", article.id, "jev_summary"): {
            "messages": [
                {"role": "system", "content": jev_pipeline.SUMMARY_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"title": article.title, "summary": article.summary}, ensure_ascii=False),
                },
            ],
            "schema": jev_pipeline.TRANSLATION_SCHEMA,
            "options": {"purpose": "jev_summary", "max_tokens": settings["summary_max_tokens"]},
            "data": {"summary_pl": summary},
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_input_tokens": 0,
            "cost_usd": 0.001,
            "request_sha256": "hash",
            "response_id": "id",
        },
    }
    with (tmp_path / "calls.jsonl").open("x") as journal:
        models = jev_pipeline.PipelineModels(config, policy, settings, journal, cached)
        result, diagnostics = await models.classify("jev", article, [])
        assert result.summary_pl == summary and diagnostics["reused_api_response"]
        assert result.urgency_score == 10
        cached[("typesafe", "jev", article.id, None)]["raw_response"]["answers"]["urgency"]["choice"] = "1"
        with pytest.raises(jev_pipeline.JevChoiceRankError) as exc:
            await models.classify("jev", article, [])
        assert exc.value.reused_api_response
        altered = deepcopy(article)
        altered.summary += " Changed source."
        with pytest.raises(ClassificationError, match="exact request changed"):
            await models.classify("jev", altered, [])
    logs = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(logs) == 4 and logs[0]["cached"] and logs[1]["cached"]
