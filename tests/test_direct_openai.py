"""Direct SDK HTTP contract and spending tests. No live credentials or transports."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import openai
import pytest
import yaml

from sentinel.classification.classifier import Classifier
from sentinel.classification.openai_provider import BudgetExceeded, ClassificationError, UsageLedger, validate_json
from sentinel.classification.policy import messages
from sentinel.classification.schema import CLASSIFICATION_SCHEMA
from sentinel.config import ModelBudgetConfig
from sentinel.models import ClassificationResult


def answer():
    return dict(
        is_military_event=True,
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.95,
        summary_pl="Rosja zaatakowała Polskę.",
        incident_memory=dict(decision="new", matched_event_id=None, confidence=0.9, reason="Nowy atak"),
        facts=dict(
            attack_countries=["PL"],
            protection="none",
            status="active",
            evidence=dict(attack_countries="Poland", protection="", status="invades"),
        ),
    )


def response(data=None, **kwargs):
    return dict(
        id="resp_test",
        object="response",
        created_at=1,
        status="completed",
        model="gpt-5.6-luna",
        output=[
            dict(
                type="message",
                id="msg",
                role="assistant",
                status="completed",
                content=[dict(type="output_text", text=json.dumps(data or answer()), annotations=[])],
            )
        ],
        usage=dict(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=dict(cached_tokens=20),
            output_tokens_details=dict(reasoning_tokens=0),
        ),
        **kwargs,
    )


async def classifier_with_http(config, monkeypatch, handler):
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    classifier = Classifier(config)
    await classifier.provider.client.close()
    classifier.provider.client = openai.AsyncOpenAI(
        api_key="local-test-placeholder",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return classifier


@pytest.mark.asyncio
async def test_direct_request_and_persistence(direct_config, sample_article, monkeypatch, db):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.url.host == "api.openai.com"
        return httpx.Response(200, json=response())

    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    try:
        result = await classifier.classify(sample_article)
        sent = requests[0]
        assert sent["reasoning"] == {"effort": "none"}
        assert sent["store"] is False and sent["max_output_tokens"] == 1024
        assert sent["text"]["format"]["strict"] is True
        assert "temperature" not in sent and "tools" not in sent
        assert sent["input"] == messages(sample_article, [], direct_config.classification.policy)
        assert result.urgency_score == 10 and result.cached_input_tokens == 20
        assert result.provider_used == "openai" and result.prompt_version.startswith("clarified-v2:")
        assert result.estimated_cost_usd > 0 and result.request_hash
        db.insert_article(sample_article)
        db.insert_classification(result)
        restored = ClassificationResult.from_row(db.conn.execute("SELECT * FROM classifications").fetchone())
        assert restored == result
        assert classifier.provider.ledger.total() == result.estimated_cost_usd
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["refusal", "incomplete", "missing", "invalid", "wrong_model", "no_usage"])
async def test_bad_response_never_classifies(direct_config, sample_article, monkeypatch, kind):
    raw = response()
    if kind == "refusal":
        raw["output"][0]["content"] = [dict(type="refusal", refusal="Declined")]
    if kind == "incomplete":
        raw["status"] = "incomplete"
    if kind == "missing":
        raw["output"] = []
    if kind == "invalid":
        raw["output"][0]["content"][0]["text"] = "{}"
    if kind == "wrong_model":
        raw["model"] = "gpt-6-astra"
    if kind == "no_usage":
        raw["usage"] = None
    classifier = await classifier_with_http(direct_config, monkeypatch, lambda request: httpx.Response(200, json=raw))
    try:
        with pytest.raises(ClassificationError):
            await classifier.classify(sample_article)
        assert classifier.provider.ledger.total() > 0
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,match",
    [
        (401, "invalid_api_key", "key"),
        (403, "permission_denied", "permissions"),
        (429, "insufficient_quota", "billing"),
        (429, "credit_balance_exhausted", "billing"),
        (429, "project_spend_limit_exceeded", "spending limit"),
        (429, "organization_spend_limit_exceeded", "spending limit"),
        (429, "organization_usage_limit_exceeded", "usage limit"),
        (429, "rate_limit_exceeded", "rate limit"),
        (500, "server_error", "failed"),
    ],
)
async def test_api_errors_are_safe_no_retry(direct_config, sample_article, monkeypatch, status, code, match):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret_must_not_escape", "type": code, "code": code}})

    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    try:
        with pytest.raises(ClassificationError, match=match) as exc:
            await classifier.classify(sample_article)
        assert "secret_must_not_escape" not in str(exc.value)
        assert len(calls) == 1
        assert classifier.provider.ledger.total() > 0
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
async def test_total_timeout(direct_config, sample_article, monkeypatch):
    direct_config.classification.timeout_seconds = 0.01

    async def handler(request):
        await asyncio.sleep(1)

    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    try:
        with pytest.raises(ClassificationError, match="timed out"):
            await classifier.classify(sample_article)
        assert classifier.provider.ledger.total() > 0
    finally:
        await classifier.aclose()


def test_missing_key_actionable(direct_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ClassificationError, match="ignored .env"):
        Classifier(direct_config)


def test_production_budget_cap_is_accepted_and_typos_are_rejected():
    configured = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    monthly = configured["classification"]["budget"]["monthly_usd"]
    assert ModelBudgetConfig(monthly_usd=monthly).monthly_usd == 30
    with pytest.raises(ValueError):
        ModelBudgetConfig(monthly_usd=300)


def test_production_ledger_lives_next_to_the_production_database():
    # /deploy copies config/config.yaml to the server; a relative ledger path cannot be opened
    # there and stopped the service on 2026-09-25.
    configured = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    ledger = Path(configured["classification"]["budget"]["ledger_path"])
    database = Path(configured["database"]["path"])
    assert ledger.is_absolute() and ledger.parent == database.parent


def test_budget_survives_restart_and_shared_callers(tmp_path):
    cfg = ModelBudgetConfig(ledger_path=str(tmp_path / "usage.db"), monthly_usd=0.01)
    a, b = UsageLedger(cfg), UsageLedger(cfg)
    try:
        a.reserve(0.006, "gpt-5.6-luna", "classification", "hash")
        with pytest.raises(BudgetExceeded):
            b.reserve(0.006, "gpt-5.6-luna", "quality", "other")
    finally:
        a.close()
        b.close()
    c = UsageLedger(cfg)
    try:
        assert c.total() == 0.006
        with pytest.raises(BudgetExceeded):
            c.reserve(0.005, "gpt-5.6-luna", "classification", "x")
    finally:
        c.close()


@pytest.mark.parametrize(
    "key,value",
    [
        ("urgency_score", 0),
        ("urgency_score", True),
        ("confidence", float("nan")),
        ("is_military_event", "false"),
        ("affected_countries", "PL"),
        ("summary_pl", None),
    ],
)
def test_strict_schema(key, value):
    data = answer()
    data[key] = value
    with pytest.raises(ClassificationError):
        validate_json(json.dumps(data), CLASSIFICATION_SCHEMA)


def test_shared_prompt_matches_frozen_known_miss():
    from sentinel.eval.compare_models import make_article

    # Message hash from both historical calls, before any direct migration.
    dataset = yaml.safe_load(Path("tests/fixtures/model_comparison_v2_holdout.yaml").read_text())
    case = next(c for c in dataset["cases"] if c["id"] == "v2h-ru-01-a")
    policy = yaml.safe_load(Path("tests/fixtures/benchmark_policy_v2.yaml").read_text())
    article = make_article(case)
    content = messages(article, [], policy)
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert digest == "0563d8bbcf1c2d6673450cf9ba8d1f283dfea171f17c296dfc7dec70518f6622"


@pytest.mark.asyncio
async def test_budget_refuses_before_http(direct_config, sample_article, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    direct_config.classification.budget.monthly_usd = 0.000001
    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    try:
        with pytest.raises(BudgetExceeded):
            await classifier.classify(sample_article)
        assert calls == []
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
async def test_explicit_test_cap_before_http(direct_config, sample_article, monkeypatch):
    classifier = await classifier_with_http(direct_config, monkeypatch, lambda request: pytest.fail("Unexpected HTTP"))
    classifier.provider.session_remaining = 0.000001
    try:
        with pytest.raises(BudgetExceeded):
            await classifier.classify(sample_article)
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
async def test_enrichment_uses_openai_and_shared_ledger(direct_config, sample_article, monkeypatch):
    from sentinel.processing.enricher import ArticleEnricher

    raw = response(data={"needs_enrichment": False, "reason": "Specific title and summary"})
    classifier = await classifier_with_http(direct_config, monkeypatch, lambda request: httpx.Response(200, json=raw))
    enricher = ArticleEnricher(direct_config)
    enricher._openai_provider = classifier.provider
    try:
        assert await enricher._check_vagueness_direct(sample_article) is False
        assert classifier.provider.ledger.total() > 0
        assert enricher._client is None
    finally:
        await enricher.aclose()


@pytest.mark.asyncio
async def test_reasoning_off_is_verified(direct_config, sample_article, monkeypatch):
    raw = response()
    raw["usage"]["output_tokens_details"]["reasoning_tokens"] = 1
    classifier = await classifier_with_http(direct_config, monkeypatch, lambda request: httpx.Response(200, json=raw))
    try:
        with pytest.raises(ClassificationError, match="reasoning=none"):
            await classifier.classify(sample_article)
        assert classifier.provider.ledger.total() > 0
    finally:
        await classifier.aclose()


def test_budget_concurrent_reservations(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    cfg = ModelBudgetConfig(ledger_path=str(tmp_path / "concurrent.db"), monthly_usd=0.01)
    UsageLedger(cfg).close()
    barrier = Barrier(2)

    def reserve():
        ledger = UsageLedger(cfg)
        try:
            barrier.wait()
            try:
                ledger.reserve(0.006, "gpt-5.6-luna", "classification", "hash")
                return True
            except BudgetExceeded:
                return False
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))
    assert sorted(results) == [False, True]


@pytest.mark.asyncio
async def test_no_send_runner_uses_real_direct_classifier(tmp_path, monkeypatch):
    from argparse import Namespace

    from sentinel.eval import direct_luna

    cases = direct_luna.cases_for_run("tests/fixtures/luna_direct_fresh.yaml", 2)
    by_title = {case["article"].title: case for case in cases}
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        message = json.loads(payload["input"][1]["content"])
        case = by_title[message["article"]["title"]]
        data = answer()
        expected = case["expected"]
        data.update(urgency_score=expected["band"][0], affected_countries=expected["countries"])
        candidates = message["remembered_incidents"]
        if expected["notification"] in ("update", "silent") and candidates:
            data["incident_memory"].update(
                decision="escalation" if expected["notification"] == "update" else "duplicate",
                matched_event_id=candidates[0]["id"],
                confidence=0.99,
            )
            data["is_new_event"] = False
        captured.append(payload)
        return httpx.Response(200, json=response(data=data))

    # Keep constructors and ledger real; only the HTTP transport is replaced.
    real_client = openai.AsyncOpenAI

    def client_factory(**kwargs):
        kwargs["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return real_client(**kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.setattr(openai, "AsyncOpenAI", client_factory)
    real_config = direct_luna.make_config

    def config_factory(path):
        config = real_config(path)
        config.classification.budget.ledger_path = str(tmp_path / "usage.db")
        return config

    monkeypatch.setattr(direct_luna, "make_config", config_factory)
    args = Namespace(
        config="config/config.example.yaml",
        fresh="tests/fixtures/luna_direct_fresh.yaml",
        repeats=2,
        live=True,
        max_cost_usd=0.25,
        output=str(tmp_path / "report.jsonl"),
    )
    assert await direct_luna.run(args) == 0
    assert len(captured) == 12
    rows = [json.loads(line) for line in Path(args.output).read_text().splitlines()]
    assert rows[0]["messages_sha256"] == rows[1]["messages_sha256"]
    assert rows[-1]["estimated_usd"] < 0.25
    assert rows[-1]["failures"] == 0
    assert rows[4]["notification"] == "update"
    assert "phone_call" in rows[4]["channels"]
    assert "phone_call" in rows[5]["channels"]
    with pytest.raises(FileExistsError):
        await direct_luna.run(args)
    assert len(captured) == 12
