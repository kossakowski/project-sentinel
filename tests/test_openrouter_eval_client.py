"""Offline tests for the paid, opt-in OpenRouter eval boundary."""

import asyncio
import json
import time
from decimal import Decimal

import httpx
import pytest

from sentinel.eval.openrouter_client import (
    BudgetLedger,
    CatalogueModel,
    ModelPricing,
    OpenRouterEvalClient,
    fetch_model_catalogue,
)

MODEL_ID = "deepseek/deepseek-v4.1-flash"
MESSAGES = [
    {"role": "system", "content": "Return a classification."},
    {"role": "user", "content": "Title: Test\nSummary: Test"},
]
SCHEMA = {
    "type": "object",
    "properties": {"urgency_score": {"type": "integer"}},
    "required": ["urgency_score"],
    "additionalProperties": False,
}


def _model(*, pricing: ModelPricing | None = None) -> CatalogueModel:
    return CatalogueModel(
        id=MODEL_ID,
        pricing=pricing
        or ModelPricing(
            prompt=Decimal("0.000001"),
            completion=Decimal("0.000002"),
            input_cache_write=Decimal("0.0000005"),
        ),
        supported_parameters=frozenset({"structured_outputs", "max_tokens", "reasoning"}),
        max_completion_tokens=4096,
    )


def _success_payload(**overrides):
    payload = {
        "id": "gen-test",
        "model": MODEL_ID,
        "provider": "TestProvider",
        "latency": 12.5,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"urgency_score": 4}),
                    "refusal": None,
                    "reasoning": None,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 12},
            "completion_tokens": 5,
            "total_tokens": 25,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "cost": 0.00003,
        },
    }
    payload.update(overrides)
    return payload


def _client(
    handler,
    *,
    budget="1",
    model: CatalogueModel | None = None,
    max_tokens=100,
    key="test-secret-key",
    timeout_seconds=60.0,
    provider_only=None,
):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = OpenRouterEvalClient(
        api_key=key,
        catalogue={MODEL_ID: model or _model()},
        budget_usd=budget,
        max_tokens=max_tokens,
        input_overhead_tokens=10,
        timeout_seconds=timeout_seconds,
        provider_only=provider_only,
        http_client=http_client,
    )
    return client, http_client


@pytest.mark.asyncio
async def test_fetch_catalogue_is_public_and_uses_worst_override_prices():
    seen_headers = None

    def handler(request: httpx.Request):
        nonlocal seen_headers
        seen_headers = request.headers
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openrouter/auto",
                        "pricing": {"prompt": "special", "completion": "-1"},
                        "supported_parameters": "not-a-list",
                    },
                    {
                        "id": MODEL_ID,
                        "pricing": {
                            "prompt": "0.000001",
                            "completion": "0.000002",
                            "input_cache_write": "0.0000003",
                            "overrides": [
                                {
                                    "context_length": 200_000,
                                    "prompt": "0.000004",
                                    "pricing": {
                                        "completion": "0.000007",
                                        "input_cache_write": "0.0000009",
                                    },
                                }
                            ],
                        },
                        "supported_parameters": ["structured_outputs", "reasoning"],
                        "top_provider": {"max_completion_tokens": 2048},
                        "reasoning": {"mandatory": False},
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        catalogue = await fetch_model_catalogue(http_client=http_client, base_url="https://openrouter.invalid/api/v1")

    assert "authorization" not in seen_headers
    assert catalogue[MODEL_ID].pricing.prompt == Decimal("0.000004")
    assert catalogue[MODEL_ID].pricing.completion == Decimal("0.000007")
    assert catalogue[MODEL_ID].pricing.input_cache_write == Decimal("0.0000009")


@pytest.mark.asyncio
async def test_complete_sends_strict_controlled_request_and_parses_metadata():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json=_success_payload())

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is True
    assert result.data == {"urgency_score": 4}
    assert result.returned_model == MODEL_ID
    assert result.returned_provider == "TestProvider"
    assert result.request_id == "gen-test"
    assert result.usage.cached_tokens == 12
    assert result.usage.reasoning_tokens == 0
    assert result.provider_latency_ms == 12.5
    assert result.usage.cost_usd == Decimal("0.00003")
    assert client.ledger.actual_cost_usd == Decimal("0.00003")
    assert len(requests) == 1

    body = json.loads(requests[0].content)
    assert body["model"] == MODEL_ID
    assert body["stream"] is False
    assert body["max_tokens"] == 100
    assert body["reasoning"] == {"enabled": False}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"]["require_parameters"] is True
    assert body["provider"]["allow_fallbacks"] is False
    assert body["provider"]["max_price"] == {"prompt": 1.0, "completion": 2.0}
    assert "only" not in body["provider"]
    assert "tools" not in body
    report = result.to_dict()
    assert report["cost_usd"] == 0.00003
    assert report["error"] is None
    assert report["error_kind"] is None
    assert report["http_status"] is None
    assert report["request_id"] == "gen-test"
    assert report["requested_model"] == MODEL_ID
    assert report["model"] == MODEL_ID
    assert report["provider"] == "TestProvider"
    assert report["reasoning_mode"] is False
    assert report["usage"]["cached_tokens"] == 12
    assert "test-secret-key" not in json.dumps(report)


@pytest.mark.asyncio
async def test_provider_only_is_propagated_without_enabling_fallbacks():
    captured = None

    def handler(request: httpx.Request):
        nonlocal captured
        captured = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    client, http_client = _client(handler, provider_only=["Nebius", "Novita"])
    try:
        await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert captured["provider"]["only"] == ["Nebius", "Novita"]
    assert captured["provider"]["allow_fallbacks"] is False


@pytest.mark.asyncio
async def test_budget_rejection_happens_before_http_call():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client, http_client = _client(handler, budget="0.000001")
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is False
    assert result.error.kind == "budget_exhausted"
    assert calls == 0
    assert client.ledger.committed_usd == 0
    assert result.to_dict()["budget_stopped"] is True


@pytest.mark.asyncio
async def test_max_price_uses_worst_catalogue_overrides():
    captured = None
    pricing = ModelPricing.from_catalogue(
        {
            "prompt": "0.000001",
            "completion": "0.000002",
            "internal_reasoning": "0.000003",
            "overrides": [{"prompt": "0.000009", "completion": "0.000008"}],
        }
    )

    def handler(request: httpx.Request):
        nonlocal captured
        captured = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    client, http_client = _client(handler, model=_model(pricing=pricing))
    try:
        await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert captured["provider"]["max_price"] == {"prompt": 9.0, "completion": 8.0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (
            _success_payload(
                choices=[
                    {
                        "finish_reason": "stop",
                        "message": {"content": "not JSON", "refusal": None},
                    }
                ]
            ),
            "invalid_completion_json",
        ),
        (
            _success_payload(
                choices=[
                    {
                        "finish_reason": "length",
                        "message": {"content": "{}", "refusal": None},
                    }
                ]
            ),
            "incomplete",
        ),
        (
            _success_payload(
                choices=[
                    {
                        "finish_reason": "error",
                        "message": {"content": "{}", "refusal": None},
                    }
                ]
            ),
            "provider_error",
        ),
        (
            _success_payload(
                choices=[
                    {
                        "finish_reason": "stop",
                        "message": {"content": "{}", "refusal": "cannot comply"},
                    }
                ]
            ),
            "refusal",
        ),
    ],
)
async def test_invalid_completion_states_are_data(payload, kind):
    def handler(request: httpx.Request):
        return httpx.Response(200, json=payload)

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is False
    assert result.error.kind == kind
    assert client.ledger.actual_cost_usd == Decimal("0.00003")


@pytest.mark.asyncio
async def test_http_error_is_data_and_retains_unknown_cost_reservation():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json={
                "id": "gen-rate-limited",
                "model": MODEL_ID,
                "provider": "TestProvider",
                "error": {"message": "rate limited"},
            },
        )

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.error.kind == "http_error"
    assert result.error.http_status == 429
    assert result.to_dict()["error_kind"] == "http_error"
    assert result.to_dict()["http_status"] == 429
    assert result.to_dict()["request_id"] == "gen-rate-limited"
    assert result.to_dict()["model"] == MODEL_ID
    assert result.to_dict()["provider"] == "TestProvider"
    assert calls == 1
    assert client.ledger.retained_reservation_usd == result.reservation_usd


@pytest.mark.asyncio
async def test_timeout_is_not_retried_retains_bound_and_redacts_key():
    calls = 0
    key = "super-secret-value"

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout(f"timeout involving {key}", request=request)

    client, http_client = _client(handler, key=key)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert calls == 1
    assert result.error.kind == "timeout"
    assert key not in result.error.message
    assert "[redacted]" in result.error.message
    assert key not in json.dumps(result.to_dict())
    assert client.ledger.retained_reservation_usd == result.reservation_usd


class _HeartbeatStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(30):
            await asyncio.sleep(0.01)
            yield b" "


@pytest.mark.asyncio
@pytest.mark.parametrize("heartbeat", [False, True])
async def test_wall_time_timeout_stops_slow_or_heartbeat_response(heartbeat):
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if heartbeat:
            return httpx.Response(200, stream=_HeartbeatStream())
        await asyncio.sleep(0.3)
        return httpx.Response(200, json=_success_payload())

    client, http_client = _client(handler, timeout_seconds=0.04)
    started = time.monotonic()
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    elapsed = time.monotonic() - started
    assert calls == 1
    assert elapsed < 0.2
    assert result.error.kind == "timeout"
    assert client.ledger.retained_reservation_usd == result.reservation_usd
    assert client.ledger.active_reservation_usd == 0


@pytest.mark.asyncio
async def test_external_cancellation_retains_bound_and_propagates():
    request_started = asyncio.Event()

    async def handler(request: httpx.Request):
        request_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    client, http_client = _client(handler)
    task = asyncio.create_task(client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA))
    try:
        await asyncio.wait_for(request_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await http_client.aclose()

    assert client.ledger.retained_reservation_usd > 0
    assert client.ledger.active_reservation_usd == 0


@pytest.mark.asyncio
async def test_returned_wrong_model_is_rejected():
    def handler(request: httpx.Request):
        return httpx.Response(200, json=_success_payload(model="openai/gpt-5.6-luna"))

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is False
    assert result.error.kind == "model_mismatch"
    assert result.returned_model == "openai/gpt-5.6-luna"


@pytest.mark.asyncio
async def test_missing_usage_cost_keeps_full_reservation():
    def handler(request: httpx.Request):
        return httpx.Response(200, json=_success_payload(usage={"prompt_tokens": 20}))

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is True
    assert result.usage.cost_usd is None
    assert client.ledger.retained_reservation_usd == result.reservation_usd


@pytest.mark.asyncio
async def test_unexpected_reasoning_is_recorded_despite_disabled_request():
    payload = _success_payload()
    payload["choices"][0]["message"]["reasoning"] = "provider-generated reasoning"
    payload["usage"]["completion_tokens_details"]["reasoning_tokens"] = 7

    def handler(request: httpx.Request):
        assert json.loads(request.content)["reasoning"]["enabled"] is False
        return httpx.Response(200, json=payload)

    client, http_client = _client(handler)
    try:
        result = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert result.ok is True
    assert result.reasoning == "provider-generated reasoning"
    assert result.usage.reasoning_tokens == 7
    assert result.to_dict()["reasoning_mode"] is True


@pytest.mark.asyncio
async def test_actual_cost_overrun_stops_later_calls():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload(usage={"cost": 0.5}))

    client, http_client = _client(handler, budget="0.01")
    try:
        first = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
        second = await client.complete(model_id=MODEL_ID, messages=MESSAGES, json_schema=SCHEMA)
    finally:
        await http_client.aclose()

    assert first.ok is True
    assert client.ledger.overrun is True
    assert first.to_dict()["budget_stopped"] is True
    assert second.error.kind == "budget_exhausted"
    assert calls == 1
    assert client.ledger.summary()["remaining_usd"] == 0.0


def test_budget_summary_explains_estimate_is_not_hard_limit():
    summary = BudgetLedger("1.00").summary()
    assert summary["budget_usd"] == 1.0
    assert "not a hard provider billing guarantee" in summary["warning"]
    assert "OpenRouter key limit" in summary["warning"]


@pytest.mark.parametrize("pricing", [{}, {"prompt": "0.1"}, {"prompt": "0.1", "completion": None}])
def test_missing_catalogue_prices_fail_closed(pricing):
    with pytest.raises(ValueError, match="explicitly price"):
        ModelPricing.from_catalogue(pricing)
