"""Unlabelled comparisons never turn provider agreement into accuracy."""

import json
from copy import deepcopy

import pytest

from sentinel.classification.openai_provider import ClassificationError
from sentinel.eval import jev_pipeline
from sentinel.eval.clarified_policy import load_policy
from sentinel.eval.compare_models import load_dataset, make_article, make_config
from sentinel.eval.jev_comparison import load_settings
from sentinel.eval.jev_observations import load_observations, summarize_observations
from sentinel.eval.jev_pipeline_questions import SCOPED_VERSION, build_pipeline_request
from sentinel.eval.jev_questions import JevChoiceRankError
from sentinel.eval.typesafe_client import check_size, pack_request
from tests.test_jev_pipeline import oracle


@pytest.fixture
def observations():
    originals = load_dataset("tests/fixtures/jev_pipeline_fresh.yaml")["cases"][:3]
    copies = deepcopy(originals)
    for case in copies:
        case.pop("expected")
        case["label_status"] = "unlabelled"
        case["split"] = "observation"
    return originals, copies


def test_observation_loader_refuses_expected_labels(tmp_path, observations):
    _, cases = observations
    path = tmp_path / "cases.json"
    data = {"version": 1, "mode": "unlabelled", "policy_version": 2, "cases": cases}
    path.write_text(json.dumps(data))
    assert len(load_observations(path)["cases"]) == 3
    data["cases"][0]["expected"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="cannot contain expected"):
        load_observations(path)


@pytest.mark.asyncio
async def test_unlabelled_replay_has_no_scores_and_normalizes_event_ids(observations):
    originals, cases = observations
    config = make_config("config/config.example.yaml")
    config.classification.corroboration_required = 1
    for level in config.alerts.urgency_levels.values():
        level.corroboration_required = 1
    rows = await jev_pipeline.replay_pipeline(cases, config, oracle(originals), lambda row: None, score_labels=False)
    assert len(rows) == 6
    assert all("expected" not in row and row["evaluation"] is None for row in rows)
    report = summarize_observations(rows, cases)
    assert report["paired_cases"] == 3 and report["differences"] == []
    assert not report["accuracy_measured"] and not report["release_eligible"]
    for section in report["models"].values():
        assert "dimensions" not in section and "flags" not in section
        assert "false_alert" not in section and "correct" not in section
    changed = deepcopy(rows)
    next(r for r in changed if r["provider"] == "jev")["data"]["urgency_score"] = 5
    report = summarize_observations(changed, cases)
    assert report["difference_counts"]["tier"] == 1
    assert report["difference_counts"]["urgency"] == 1


@pytest.mark.asyncio
async def test_unlabelled_preflight_is_offline(tmp_path, observations, monkeypatch):
    _, cases = observations
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version": 1, "policy_version": 2, "mode": "unlabelled", "cases": cases}))
    config = make_config("config/config.example.yaml")
    config.classification.provider = "openai"
    config.classification.model = "gpt-5.6-luna"
    monkeypatch.setattr(jev_pipeline, "make_config", lambda path: config)
    monkeypatch.setattr(jev_pipeline, "PipelineModels", lambda *args: pytest.fail("Offline mode opened providers"))
    args = jev_pipeline.parser().parse_args(
        ["--unlabelled", "--dataset", str(path), "--output", str(tmp_path / "preview")]
    )
    assert await jev_pipeline.run(args) == 0
    manifest = json.loads((tmp_path / "preview/manifest.json").read_text())
    assert manifest["unlabelled"] and manifest["inventory"]["labels"] == {"unlabelled": 3}
    assert not (tmp_path / "preview/usage.db").exists()


def test_each_independent_question_has_explicit_scope_without_changing_v2(observations):
    _, cases = observations
    settings = load_settings("tests/fixtures/jev_pipeline.yaml")
    policy = load_policy("tests/fixtures/benchmark_policy_v2.yaml")
    article = make_article(cases[0])
    original = build_pipeline_request(article, [], policy, settings)
    assert "monitoring_scope" not in original["state"]
    settings["question_version"] = SCOPED_VERSION
    scoped = build_pipeline_request(article, [], policy, settings)
    assert set(scoped["state"]["monitoring_scope"]) == set(policy["monitored_countries"])
    assert "DE" not in scoped["state"]["monitoring_scope"]
    assert all("monitoring_scope" in q["instructions"] for q in scoped["questions"].values())
    # The scope comes from policy, not source metadata or fixed geopolitical assumptions.
    policy["monitored_countries"] = ["PL"]
    scoped = build_pipeline_request(article, [], policy, settings)
    assert set(scoped["state"]["monitoring_scope"]) == {"PL"}


def test_oversize_packing_preserves_sources_candidates_and_complete_rules():
    rule = "Use current article only; memory identifies continuity. " * 55
    payload = {
        "model": "jev-1.13.0",
        "state": {"article": {"title": "Verbatim"}, "remembered_incidents": [{"id": "prior"}]},
        "questions": {
            f"q{i}": {
                "type": "choice",
                "instructions": {"question": f"Question {i}", "source_discipline": rule},
                "criteria": {"yes": "Yes", "no": "No"},
            }
            for i in range(4)
        },
    }
    before = deepcopy(payload)
    settings = {"request_token_limit": 12000, "state_question_token_limit": 16000}
    with pytest.raises(ValueError):
        check_size(payload, settings)
    packed, encoding = pack_request(payload, settings)
    check_size(packed, settings)
    assert encoding == "shared-source-discipline-v1" and payload == before
    assert packed["state"]["shared_source_discipline"] == rule
    assert {k: packed["state"][k] for k in before["state"]} == before["state"]
    for name in payload["questions"]:
        assert packed["questions"][name]["criteria"] == before["questions"][name]["criteria"]
    unchanged, encoding = pack_request(payload, {"request_token_limit": 64000, "state_question_token_limit": 32000})
    assert unchanged == before and encoding == "inline"


@pytest.mark.asyncio
async def test_diagnostic_rank_errors_are_recorded_without_safe_defaults(observations):
    originals, cases = observations
    config = make_config("config/config.example.yaml")
    good = oracle(originals)

    async def classify(provider, article, candidates):
        if provider == "jev":
            error = JevChoiceRankError("Invalid Jev winning choice")
            error.reused_api_response = True
            raise error
        return await good(provider, article, candidates)

    rows = await jev_pipeline.replay_pipeline(
        cases, config, classify, lambda r: None, score_labels=False, continue_rank_errors=True
    )
    assert len(rows) == 6
    failed = [r for r in rows if r["provider"] == "jev"]
    assert all("data" not in r and "notification" not in r and r["evaluation"] is None for r in failed)
    assert all(r["latency_seconds"] is None for r in failed)
    report = summarize_observations(rows, cases)
    assert report["models"]["jev"]["rank_errors"] == 3
    assert report["paired_cases"] == 0 and len(report["unpaired_or_invalid_case_ids"]) == 3

    async def transport_failure(*args):
        raise ClassificationError("Provider unavailable")

    rows = await jev_pipeline.replay_pipeline(
        cases, config, transport_failure, lambda r: None, score_labels=False, continue_rank_errors=True
    )
    assert len(rows) == 1
