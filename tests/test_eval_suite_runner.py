"""Eval-suite runner with a fake client: no network, no spending."""

import asyncio
import json

from sentinel.eval.compare_models import make_config
from sentinel.eval.suite import runner
from sentinel.eval.suite.score import majority, model_fault, unavailable


def answer(urgency=9, countries=("PL",), summary="Rosyjski dron nad Polską."):
    return {
        "is_military_event": True,
        "event_type": "drone_incursion",
        "urgency_score": urgency,
        "affected_countries": list(countries),
        "aggressor": "Russia",
        "is_new_event": True,
        "confidence": 0.9,
        "summary_pl": summary,
        "incident_memory": {"decision": "new", "matched_event_id": None, "confidence": 0.9, "reason": "brak"},
        "facts": {
            "attack_countries": ["PL"],
            "protection": "none",
            "status": "active",
            "evidence": {"attack_countries": "x", "protection": "", "status": "y"},
        },
    }


class FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class FakeClient:
    """Returns queued completion dicts in order."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def complete(self, *, model_id, messages, json_schema):
        self.calls.append(messages)
        return FakeResult(self.payloads.pop(0))


def ok(data):
    return {"data": data, "error": None, "error_kind": None, "usage": {"prompt_tokens": 10}, "cost_usd": 0.0001}


def failure(kind, status=None):
    return {"data": None, "error": f"{kind}: x", "error_kind": kind, "http_status": status, "usage": {}}


def item(id_="i1", chain=None, pos=None, minute=0):
    return {
        "id": id_,
        "chain_id": chain,
        "chain_pos": pos,
        "article": {
            "source_name": "src",
            "source_url": "https://example.test/a",
            "source_type": "rss",
            "title": "Dron nad Polską",
            "summary": "Rosyjski dron wleciał nad Polskę.",
            "language": "pl",
            "published_at": f"2026-09-13T03:{minute:02d}:00+00:00",
            "fetched_at": f"2026-09-13T03:{minute + 1:02d}:00+00:00",
        },
    }


def config():
    return make_config("config/config.example.yaml")


def test_model_spec_parsing():
    assert runner.parse_model_spec("openai/gpt-6-luna") == ("openai/gpt-6-luna", None, False)
    assert runner.parse_model_spec("openai/gpt-6-luna@openai") == ("openai/gpt-6-luna", ["openai"], False)
    assert runner.parse_model_spec("z-ai/glm@DeepInfra+reasoning") == ("z-ai/glm", ["DeepInfra"], True)


def test_retry_on_overload_then_success(monkeypatch):
    monkeypatch.setattr(runner, "RETRY_DELAYS", (0, 0, 0))
    client = FakeClient(failure("http_error", 429), failure("timeout"), ok(answer()))
    result = asyncio.run(runner.complete_with_retry(client, "m", []))
    assert result["attempts"] == 3 and result["data"]["urgency_score"] == 9


def test_no_retry_for_model_faults_and_gives_up_on_persistent_outage(monkeypatch):
    monkeypatch.setattr(runner, "RETRY_DELAYS", (0, 0, 0))
    bad = asyncio.run(runner.complete_with_retry(FakeClient(failure("invalid_completion_json")), "m", []))
    assert bad["attempts"] == 1
    down = asyncio.run(runner.complete_with_retry(FakeClient(*[failure("http_error", 503)] * 4), "m", []))
    assert down["attempts"] == 4 and down["error_kind"] == "http_error"


def test_classify_single_uses_production_prompt_and_validates():
    cfg = config()
    policy = cfg.classification.policy
    client = FakeClient(ok(answer(urgency=10)))
    row = asyncio.run(runner.classify_single(client, "m", 0, item(), cfg, policy))
    assert row["urgency"] == 10 and row["countries"] == ["PL"] and row["summary_polish"]
    sent = json.loads(client.calls[0][1]["content"])
    assert sent["remembered_incidents"] == [] and sent["evaluation_time"].startswith("2026-09-13T03:01")

    broken = answer()
    broken["urgency_score"] = 11
    row = asyncio.run(runner.classify_single(FakeClient(ok(broken)), "m", 0, item(), cfg, policy))
    assert row["error_kind"] == "invalid_output" and row.get("urgency") is None and row["raw_content"]


def test_replay_chain_records_events_and_notifications():
    cfg = config()
    chain = [item("a", "ch", 0, 0), item("b", "ch", 1, 5)]
    client = FakeClient(ok(answer(urgency=9)), ok(answer(urgency=9)))
    rows = asyncio.run(runner.replay_chain(client, "m", 0, chain, cfg, cfg.classification.policy))
    assert [r["item_id"] for r in rows] == ["a", "b"]
    assert rows[0]["notification"] == "initial" and rows[0]["event_id"]
    assert "candidate_ids" in rows[1]


def test_load_done_drops_half_finished_chains(tmp_path):
    chains = [[item("a", "ch", 0), item("b", "ch", 1)]]
    path = tmp_path / "calls.jsonl"
    rows = [
        {"model": "m", "repeat": 0, "item_id": "s", "chain_id": None},
        {"model": "m", "repeat": 0, "item_id": "a", "chain_id": "ch"},
        {"model": "m", "repeat": 1, "item_id": "x", "chain_id": None, "error_kind": "budget_exhausted"},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    kept, done = runner.load_done(path, chains)
    assert done == {("m", 0, "s")} and len(path.read_text().splitlines()) == 1


def test_scoring_separates_model_faults_from_outages():
    fault = {"urgency": None, "error_kind": "invalid_output"}
    outage = {"urgency": None, "error_kind": "http_error"}
    assert model_fault(fault) and not unavailable(fault)
    assert unavailable(outage) and not model_fault(outage)
    assert majority([outage, outage, outage]).get("unavailable")
    assert majority([fault, fault, {"urgency": 9, "countries": []}])["invalid"]
