"""Classification-path fixes: budget release for unbilled requests, empty-summary fallback.

Every request goes to a fake OpenAI client (or the real SDK on an
``httpx.MockTransport``) and a temporary SQLite usage ledger. Nothing reaches the
network and no ``.env`` is read.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from sentinel.classification.classifier import Classifier
from sentinel.classification.openai_provider import BudgetExceeded, ClassificationError, OpenAIProvider
from sentinel.classification.summary_language import GUARD_VERSION

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
MESSAGES = [{"role": "user", "content": "Czy to działa?"}]


def _status_error(cls, status: int, code: str):
    return cls(
        f"Error code: {status}",
        response=httpx.Response(status, request=REQUEST),
        body={"message": "provider text", "type": code, "code": code},
    )


def _connection_error(cause: Exception | None):
    """``APIConnectionError`` as the SDK raises it: chained from the httpx transport error."""
    exc = openai.APIConnectionError(request=REQUEST)
    exc.__cause__ = cause
    return exc


def _reply(data: dict, model: str) -> dict:
    return {
        "id": "resp_budget",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_budget",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(data, ensure_ascii=False), "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


async def _provider_raising(config, monkeypatch, exc_factory) -> OpenAIProvider:
    """A real provider and ledger whose client raises ``exc_factory()`` on every request."""
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    provider = OpenAIProvider(config.classification)
    await provider.client.close()

    async def create(**payload):
        raise exc_factory()

    async def close():
        return None

    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create), close=close)
    return provider


async def _provider_on_transport(config, monkeypatch, handler) -> OpenAIProvider:
    """A real provider, ledger and SDK client whose HTTP transport is ``handler``."""
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    provider = OpenAIProvider(config.classification)
    await provider.client.close()
    provider.client = openai.AsyncOpenAI(
        api_key="local-test-placeholder",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


def _rows(provider: OpenAIProvider) -> list[tuple[float, str]]:
    return provider.ledger.db.execute("SELECT charged_usd, status FROM model_usage ORDER BY rowid").fetchall()


# ---------------------------------------------------------------------------
# 3.1: a request the provider certainly did not bill releases its reservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_releases_reservation(direct_config, monkeypatch):
    """A burst of 429s does not use up the monthly cap; the next good request still succeeds."""
    direct_config.classification.budget.monthly_usd = 0.02  # about four retained reservations
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) <= 50:
            return httpx.Response(
                429, json={"error": {"message": "slow down", "type": "requests", "code": "rate_limit_exceeded"}}
            )
        return httpx.Response(200, json=_reply({"ok": True}, direct_config.classification.model))

    provider = await _provider_on_transport(direct_config, monkeypatch, handler)
    try:
        for _ in range(50):
            with pytest.raises(ClassificationError, match="rate limit"):
                await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        assert provider.ledger.total() == 0
        rows = _rows(provider)
        assert len(rows) == 50
        assert all(row == (0, "released") for row in rows)

        reply = await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        assert reply.data == {"ok": True}
        assert len(calls) == 51
        assert provider.ledger.total() == pytest.approx(reply.cost_usd)
        assert _rows(provider)[-1][1] == "settled"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_factory,message",
    [
        (lambda: _status_error(openai.AuthenticationError, 401, "invalid_api_key"), "key"),
        (lambda: _status_error(openai.PermissionDeniedError, 403, "permission_denied"), "permissions"),
        (lambda: _status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "rate limit"),
        (lambda: _status_error(openai.RateLimitError, 429, "insufficient_quota"), "billing"),
        (lambda: _status_error(openai.RateLimitError, 429, "project_spend_limit_exceeded"), "spending limit"),
        (
            lambda: _connection_error(httpx.ConnectError("[Errno 111] Connection refused", request=REQUEST)),
            "could not be reached",
        ),
    ],
    ids=["401", "403", "429-rate", "429-quota", "429-spend", "connect-refused"],
)
async def test_unbilled_failures_release_reservation(direct_config, monkeypatch, exc_factory, message):
    provider = await _provider_raising(direct_config, monkeypatch, exc_factory)
    try:
        with pytest.raises(ClassificationError, match=message) as raised:
            await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        assert "provider text" not in str(raised.value)
        assert _rows(provider) == [(0, "released")]
        assert provider.ledger.total() == 0
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_connect_error_through_the_sdk_releases_reservation(direct_config, monkeypatch):
    """The real SDK chains the transport error that the release decision reads."""

    def refuse(request):
        raise httpx.ConnectError("[Errno 111] Connection refused", request=request)

    provider = await _provider_on_transport(direct_config, monkeypatch, refuse)
    try:
        with pytest.raises(ClassificationError, match="could not be reached"):
            await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        assert _rows(provider) == [(0, "released")]
        assert provider.ledger.total() == 0
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["sdk_timeout", "deadline"],
)
async def test_timeout_keeps_reservation(direct_config, monkeypatch, kind):
    """A timeout may follow a request the provider received and billed: the reservation stays."""
    if kind == "sdk_timeout":
        provider = await _provider_raising(direct_config, monkeypatch, lambda: openai.APITimeoutError(request=REQUEST))
        timeout_seconds = None
    else:

        async def slow(request):
            await asyncio.sleep(5)
            return httpx.Response(200, json=_reply({"ok": True}, direct_config.classification.model))

        provider = await _provider_on_transport(direct_config, monkeypatch, slow)
        timeout_seconds = 0.05
    try:
        with pytest.raises(ClassificationError, match="timed out"):
            await provider.request(
                MESSAGES, SCHEMA, purpose="classification", max_tokens=256, timeout_seconds=timeout_seconds
            )
        rows = _rows(provider)
        assert len(rows) == 1 and rows[0][1] == "reserved" and rows[0][0] > 0
        assert provider.ledger.total() == rows[0][0]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: _status_error(openai.InternalServerError, 500, "server_error"),
        lambda: _status_error(openai.InternalServerError, 503, "service_unavailable"),
        lambda: _connection_error(httpx.ReadError("connection reset", request=REQUEST)),
        lambda: _connection_error(
            httpx.RemoteProtocolError("Server disconnected without sending a response.", request=REQUEST)
        ),
        lambda: _connection_error(None),
    ],
    ids=["500", "503", "read-error", "server-disconnected", "unknown-cause"],
)
async def test_possibly_billed_failures_keep_reservation(direct_config, monkeypatch, exc_factory):
    """A 5xx, or a connection lost after the request may have been sent, keeps the reservation."""
    provider = await _provider_raising(direct_config, monkeypatch, exc_factory)
    try:
        with pytest.raises(ClassificationError, match="possible charge reserved"):
            await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        rows = _rows(provider)
        assert len(rows) == 1 and rows[0][1] == "reserved" and rows[0][0] > 0
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_release_restores_explicit_session_cap(direct_config, monkeypatch):
    """The explicit test spending cap gets a released reservation back, so retries are not refused."""
    provider = await _provider_raising(
        direct_config, monkeypatch, lambda: _status_error(openai.RateLimitError, 429, "rate_limit_exceeded")
    )
    provider.session_remaining = 0.05
    try:
        for _ in range(20):
            with pytest.raises(ClassificationError, match="rate limit"):
                await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
        assert provider.session_remaining == pytest.approx(0.05)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_retained_reservations_still_reach_the_cap(direct_config, monkeypatch):
    """Possibly billed failures keep counting, so the monthly cap still stops spending."""
    direct_config.classification.budget.monthly_usd = 0.02
    provider = await _provider_raising(
        direct_config, monkeypatch, lambda: _status_error(openai.InternalServerError, 500, "server_error")
    )
    try:
        for _ in range(50):
            try:
                await provider.request(MESSAGES, SCHEMA, purpose="classification", max_tokens=256)
            except BudgetExceeded:
                break
            except ClassificationError as exc:
                assert "possible charge reserved" in str(exc)
        else:
            pytest.fail("Retained reservations never reached the monthly cap")
        assert 0 < provider.ledger.total() <= 0.02
    finally:
        await provider.aclose()


def test_release_leaves_settled_rows_alone(tmp_path):
    from sentinel.classification.openai_provider import UsageLedger
    from sentinel.config import ModelBudgetConfig

    ledger = UsageLedger(ModelBudgetConfig(ledger_path=str(tmp_path / "usage.db")))
    try:
        settled = ledger.reserve(0.004, "gpt-5.6-luna", "classification", "a")
        cost = ledger.settle(settled, 100, 0, 20, "resp_a")
        ledger.release(settled)
        released = ledger.reserve(0.004, "gpt-5.6-luna", "classification", "b")
        ledger.release(released)
        rows = dict(ledger.db.execute("SELECT id, status FROM model_usage").fetchall())
        assert rows == {settled: "settled", released: "released"}
        assert ledger.total() == pytest.approx(cost)
    finally:
        ledger.close()


# ---------------------------------------------------------------------------
# 3.2: an empty model summary uses the Polish fallback instead of failing
# ---------------------------------------------------------------------------


def _classification(summary_pl: str) -> dict:
    return dict(
        is_military_event=True,
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        is_new_event=True,
        confidence=0.95,
        summary_pl=summary_pl,
        incident_memory=dict(decision="new", matched_event_id=None, confidence=0.9, reason="Nowy atak"),
        facts=dict(
            attack_countries=["PL"],
            protection="none",
            status="active",
            evidence=dict(attack_countries="Poland", protection="", status="invades"),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_pl", ["", "   \n"], ids=["empty", "blank"])
async def test_empty_summary_uses_fallback(direct_config, sample_article, monkeypatch, summary_pl):
    purposes = []

    def handler(request):
        purposes.append(json.loads(request.content)["text"]["format"]["name"])
        return httpx.Response(200, json=_reply(_classification(summary_pl), direct_config.classification.model))

    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    classifier = Classifier(direct_config)
    await classifier.provider.client.close()
    classifier.provider.client = openai.AsyncOpenAI(
        api_key="local-test-placeholder",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        result = await classifier.classify(sample_article)
        fallback = direct_config.classification.summary_language.fallback_pl
        assert result.summary_pl == fallback
        assert result.urgency_score == 10 and result.affected_countries == ["PL"]
        assert result.summary_processing["action"] == "fallback"
        assert result.summary_processing["version"] == GUARD_VERSION
        assert result.summary_processing["original_summary"] == summary_pl
        # No translation request: one classification call, one settled ledger row.
        assert purposes == ["classification"]
        assert _rows(classifier.provider) == [(pytest.approx(result.estimated_cost_usd), "settled")]
    finally:
        await classifier.aclose()
