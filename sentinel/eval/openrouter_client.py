"""Strict, budgeted OpenRouter client used only by the model-comparison eval.

The production classifier does not import this module.  The client deliberately
has no retry or fallback path: one reservation permits at most one paid HTTP
request, and the response must identify the exact requested model.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EVAL_MODEL_IDS = (
    "anthropic/claude-haiku-4.5",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3.8-flash",
    "openai/gpt-5.6-luna",
    "openai/gpt-6-luna",
)
APPROVED_MODEL_IDS = frozenset(EVAL_MODEL_IDS)

_MILLION = Decimal("1000000")
_PRICE_FIELDS = (
    "prompt",
    "completion",
    "request",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)


def _decimal(value: object, *, default: Decimal = Decimal("0")) -> Decimal:
    """Parse an OpenRouter decimal string without introducing float error."""
    if value is None or value == "":
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid OpenRouter price: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"Invalid OpenRouter price: {value!r}")
    return parsed


@dataclass(frozen=True)
class ModelPricing:
    """Worst advertised model prices, in USD per token/request."""

    prompt: Decimal = Decimal("0")
    completion: Decimal = Decimal("0")
    request: Decimal = Decimal("0")
    internal_reasoning: Decimal = Decimal("0")
    input_cache_read: Decimal = Decimal("0")
    input_cache_write: Decimal = Decimal("0")

    @classmethod
    def from_catalogue(cls, pricing: Mapping[str, Any]) -> ModelPricing:
        """Take the maximum base/override value for every billable dimension.

        OpenRouter currently places overridden prices directly on each override.
        The nested ``pricing`` form is also accepted so a schema evolution cannot
        accidentally make the eval underestimate a request.
        """
        if any(pricing.get(name) in (None, "") for name in ("prompt", "completion")):
            raise ValueError("Catalogue must explicitly price both input and output tokens")
        worst = {name: _decimal(pricing.get(name)) for name in _PRICE_FIELDS}
        overrides = pricing.get("overrides") or []
        if not isinstance(overrides, list):
            raise ValueError("OpenRouter pricing.overrides must be a list")
        for override in overrides:
            if not isinstance(override, Mapping):
                raise ValueError("OpenRouter pricing override must be an object")
            nested = override.get("pricing")
            sources = [override]
            if isinstance(nested, Mapping):
                sources.append(nested)
            for source in sources:
                for name in _PRICE_FIELDS:
                    if name in source and source[name] is not None:
                        worst[name] = max(worst[name], _decimal(source[name]))
        return cls(**worst)

    def max_price_per_million(self) -> dict[str, float]:
        """Return OpenRouter routing ceilings (whose unit is USD/million)."""
        # Internal reasoning is an output price.  Use the more expensive output
        # dimension as the completion ceiling so routing cannot exceed our bound.
        output_price = max(self.completion, self.internal_reasoning)
        return {
            "prompt": float(self.prompt * _MILLION),
            "completion": float(output_price * _MILLION),
        }

    def conservative_bound(
        self,
        *,
        input_tokens: int,
        output_tokens_including_reasoning: int,
    ) -> Decimal:
        """Bound a request, charging all potentially additive token prices.

        Cache-write and internal-reasoning prices are added, not substituted.
        This intentionally overestimates providers that charge only one of those
        dimensions.  It is a runner guard, not a hard billing guarantee.
        """
        if input_tokens < 0 or output_tokens_including_reasoning < 0:
            raise ValueError("Token bounds must be non-negative")
        input_price = self.prompt + self.input_cache_read + self.input_cache_write
        output_price = self.completion + self.internal_reasoning
        return (
            self.request
            + Decimal(input_tokens) * input_price
            + Decimal(output_tokens_including_reasoning) * output_price
        )


@dataclass(frozen=True)
class CatalogueModel:
    id: str
    pricing: ModelPricing
    supported_parameters: frozenset[str] = frozenset()
    max_completion_tokens: int | None = None
    reasoning_mandatory: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CatalogueModel:
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("OpenRouter catalogue model is missing its id")
        pricing = raw.get("pricing")
        if not isinstance(pricing, Mapping):
            raise ValueError(f"OpenRouter catalogue model {model_id!r} has no pricing")
        top_provider = raw.get("top_provider")
        maximum = top_provider.get("max_completion_tokens") if isinstance(top_provider, Mapping) else None
        if maximum is not None and (not isinstance(maximum, int) or maximum <= 0):
            raise ValueError(f"Invalid max_completion_tokens for {model_id!r}")
        reasoning = raw.get("reasoning")
        mandatory = bool(reasoning.get("mandatory", False)) if isinstance(reasoning, Mapping) else False
        parameters = raw.get("supported_parameters") or []
        if not isinstance(parameters, list) or not all(isinstance(item, str) for item in parameters):
            raise ValueError(f"Invalid supported_parameters for {model_id!r}")
        return cls(
            id=model_id,
            pricing=ModelPricing.from_catalogue(pricing),
            supported_parameters=frozenset(parameters),
            max_completion_tokens=maximum,
            reasoning_mandatory=mandatory,
        )


async def fetch_model_catalogue(
    *,
    http_client: httpx.AsyncClient | None = None,
    base_url: str = OPENROUTER_BASE_URL,
    timeout_seconds: float = 15.0,
    model_ids: frozenset[str] = APPROVED_MODEL_IDS,
) -> dict[str, CatalogueModel]:
    """Fetch the public model catalogue.  No API key is sent."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
    try:
        response = await client.get(f"{base_url.rstrip('/')}/models")
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("OpenRouter catalogue response has no data list")
        # The public catalogue also contains routers and special/free entries with
        # pricing shapes irrelevant to this frozen comparison.  Parse only the
        # exact allow-list so an unrelated catalogue entry cannot block preflight.
        models = [
            CatalogueModel.from_dict(row) for row in rows if isinstance(row, Mapping) and row.get("id") in model_ids
        ]
        return {model.id: model for model in models}
    finally:
        if owns_client:
            await client.aclose()


@dataclass
class BudgetReservation:
    amount_usd: Decimal
    active: bool = True
    actual_cost_usd: Decimal | None = None


@dataclass
class BudgetLedger:
    """Local conservative budget guard for a bounded paid eval run.

    This estimate cannot guarantee provider billing.  A separate OpenRouter key
    limit remains the independent hard ceiling.
    """

    budget_usd: Decimal | str | float
    actual_cost_usd: Decimal = field(default=Decimal("0"), init=False)
    retained_reservation_usd: Decimal = field(default=Decimal("0"), init=False)
    overrun: bool = field(default=False, init=False)
    _active: list[BudgetReservation] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.budget_usd = _decimal(self.budget_usd)

    @property
    def active_reservation_usd(self) -> Decimal:
        return sum((item.amount_usd for item in self._active if item.active), Decimal("0"))

    @property
    def committed_usd(self) -> Decimal:
        return self.actual_cost_usd + self.retained_reservation_usd + self.active_reservation_usd

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal("0"), self.budget_usd - self.committed_usd)

    def reserve(self, amount_usd: Decimal) -> BudgetReservation | None:
        amount = _decimal(amount_usd)
        if self.overrun or amount > self.remaining_usd:
            return None
        reservation = BudgetReservation(amount)
        self._active.append(reservation)
        return reservation

    def settle(self, reservation: BudgetReservation, actual_cost_usd: Decimal) -> None:
        """Replace a conservative reservation with returned actual API cost."""
        if not reservation.active:
            raise ValueError("Budget reservation is already finalized")
        actual = _decimal(actual_cost_usd)
        reservation.active = False
        reservation.actual_cost_usd = actual
        self.actual_cost_usd += actual
        self.overrun = self.committed_usd > self.budget_usd

    def retain(self, reservation: BudgetReservation) -> None:
        """Keep the full bound after a timeout, failed call, or unknown cost."""
        if not reservation.active:
            raise ValueError("Budget reservation is already finalized")
        reservation.active = False
        self.retained_reservation_usd += reservation.amount_usd
        self.overrun = self.committed_usd > self.budget_usd

    def summary(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot for the eval report."""
        return {
            "budget_usd": float(self.budget_usd),
            "actual_cost_usd": float(self.actual_cost_usd),
            "retained_reservation_usd": float(self.retained_reservation_usd),
            "active_reservation_usd": float(self.active_reservation_usd),
            "committed_usd": float(self.committed_usd),
            "remaining_usd": float(self.remaining_usd),
            "overrun": self.overrun,
            "warning": (
                "Conservative runner estimate; not a hard provider billing guarantee. "
                "Use a separate OpenRouter key limit."
            ),
        }


@dataclass(frozen=True)
class CompletionUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: Decimal | None = None
    cached_tokens: int | None = None


@dataclass(frozen=True)
class CompletionError:
    kind: str
    message: str
    http_status: int | None = None


@dataclass(frozen=True)
class CompletionResult:
    ok: bool
    data: dict[str, Any] | None
    requested_model: str
    returned_model: str | None
    returned_provider: str | None
    usage: CompletionUsage
    finish_reason: str | None
    refusal: Any | None
    reasoning: Any | None
    latency_ms: float
    provider_latency_ms: float | None
    reservation_usd: Decimal
    error: CompletionError | None = None
    budget_stopped: bool = False
    request_id: str | None = None
    raw_content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the compact JSON-safe record consumed by the eval runner."""
        reasoning_used = (
            self.usage.reasoning_tokens is not None and self.usage.reasoning_tokens > 0
        ) or self.reasoning not in (None, "")
        return {
            "data": self.data,
            "error": (f"{self.error.kind}: {self.error.message}" if self.error is not None else None),
            "error_kind": self.error.kind if self.error is not None else None,
            "http_status": self.error.http_status if self.error is not None else None,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "cached_tokens": self.usage.cached_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens,
            },
            "cost_usd": float(self.usage.cost_usd) if self.usage.cost_usd is not None else None,
            "reserved_usd": float(self.reservation_usd),
            "latency_seconds": self.latency_ms / 1000,
            "request_id": self.request_id,
            "requested_model": self.requested_model,
            "model": self.returned_model,
            "provider": self.returned_provider,
            "finish_reason": self.finish_reason,
            "reasoning": self.reasoning,
            "reasoning_mode": reasoning_used,
            "provider_latency_seconds": (
                self.provider_latency_ms / 1000 if self.provider_latency_ms is not None else None
            ),
            "budget_stopped": self.budget_stopped,
            "raw_content": self.raw_content,
        }


class OpenRouterEvalClient:
    """One-shot, non-retrying client for controlled eval completions."""

    def __init__(
        self,
        *,
        api_key: str,
        catalogue: Mapping[str, CatalogueModel],
        budget_usd: Decimal | str | float | None = None,
        ledger: BudgetLedger | None = None,
        max_tokens: int = 1024,
        input_overhead_tokens: int = 256,
        max_reasoning_tokens: int = 0,
        timeout_seconds: float = 60.0,
        provider_only: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        approved_models: frozenset[str] = APPROVED_MODEL_IDS,
        reasoning: Mapping[str, Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("An OpenRouter API key is required for live eval calls")
        if (budget_usd is None) == (ledger is None):
            raise ValueError("Provide exactly one of budget_usd or ledger")
        if max_tokens <= 0 or input_overhead_tokens < 0 or max_reasoning_tokens < 0:
            raise ValueError("Invalid eval token bounds")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        if provider_only is not None and not all(isinstance(item, str) and item for item in provider_only):
            raise ValueError("provider_only entries must be non-empty strings")
        self._api_key = api_key
        self.approved_models = frozenset(approved_models)
        # None keeps reasoning disabled (production setting); a mapping such as
        # {"effort": "low"} is only for models whose reasoning cannot be turned off.
        self.reasoning = dict(reasoning) if reasoning is not None else None
        self.catalogue = dict(catalogue)
        self.ledger = ledger or BudgetLedger(budget_usd)  # type: ignore[arg-type]
        self.max_tokens = max_tokens
        self.input_overhead_tokens = input_overhead_tokens
        self.max_reasoning_tokens = max_reasoning_tokens
        self.timeout_seconds = timeout_seconds
        self.provider_only = list(provider_only) if provider_only is not None else None
        self.base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    def _request_body(
        self,
        model: CatalogueModel,
        messages: Sequence[Mapping[str, Any]],
        json_schema: Mapping[str, Any],
        *,
        schema_name: str,
    ) -> dict[str, Any]:
        provider: dict[str, Any] = {
            "require_parameters": True,
            "allow_fallbacks": False,
            "max_price": model.pricing.max_price_per_million(),
        }
        if self.provider_only is not None:
            provider["only"] = list(self.provider_only)
        return {
            "model": model.id,
            "messages": [dict(message) for message in messages],
            "max_tokens": self.max_tokens,
            "stream": False,
            "reasoning": self.reasoning if self.reasoning is not None else {"enabled": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(json_schema),
                },
            },
            "provider": provider,
        }

    def estimate_reservation(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        json_schema: Mapping[str, Any],
        *,
        schema_name: str = "sentinel_classification",
    ) -> Decimal:
        model = self.catalogue.get(model_id)
        if model is None:
            raise ValueError(f"Model {model_id!r} is absent from the fetched catalogue")
        body = self._request_body(model, messages, json_schema, schema_name=schema_name)
        # UTF-8 bytes are used as a deliberately conservative token upper bound.
        # Count only input and schema material, plus a configurable routing/tokenizer
        # overhead; control fields do not vary with article content.
        bounded_input = {
            "messages": body["messages"],
            "response_format": body["response_format"],
        }
        input_bytes = len(json.dumps(bounded_input, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return model.pricing.conservative_bound(
            input_tokens=input_bytes + self.input_overhead_tokens,
            output_tokens_including_reasoning=self.max_tokens + self.max_reasoning_tokens,
        )

    async def complete(
        self,
        *,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        json_schema: Mapping[str, Any],
        schema_name: str = "sentinel_classification",
    ) -> CompletionResult:
        """Make exactly one paid request, or return an error without making one."""
        started = time.monotonic()
        model = self.catalogue.get(model_id)
        if model_id not in self.approved_models:
            return self._failure(
                model_id, started, Decimal("0"), "model_not_approved", "Model is not approved for this eval"
            )
        if model is None:
            return self._failure(
                model_id, started, Decimal("0"), "model_not_in_catalogue", "Model is absent from catalogue"
            )
        if model.reasoning_mandatory and self.reasoning is None:
            return self._failure(
                model_id,
                started,
                Decimal("0"),
                "reasoning_required",
                "Catalogue says reasoning cannot be disabled for this model",
            )
        if model.max_completion_tokens is not None and self.max_tokens > model.max_completion_tokens:
            return self._failure(
                model_id,
                started,
                Decimal("0"),
                "max_tokens_unsupported",
                "Configured max_tokens exceeds the catalogue maximum",
            )

        body = self._request_body(model, messages, json_schema, schema_name=schema_name)
        reservation_amount = self.estimate_reservation(model_id, messages, json_schema, schema_name=schema_name)
        reservation = self.ledger.reserve(reservation_amount)
        if reservation is None:
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "budget_exhausted",
                "Conservative request bound does not fit the remaining budget",
            )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await self._http.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except asyncio.CancelledError:
            self.ledger.retain(reservation)
            raise
        except TimeoutError as exc:
            self.ledger.retain(reservation)
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "timeout",
                self._safe_exception("OpenRouter request exceeded its wall-time limit", exc),
            )
        except httpx.TimeoutException as exc:
            self.ledger.retain(reservation)
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "timeout",
                self._safe_exception("OpenRouter request timed out", exc),
            )
        except httpx.HTTPError as exc:
            self.ledger.retain(reservation)
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "transport_error",
                self._safe_exception("OpenRouter transport error", exc),
            )
        except Exception as exc:
            self.ledger.retain(reservation)
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "transport_error",
                self._safe_exception("OpenRouter request failed", exc),
            )

        payload: Mapping[str, Any] | None = None
        try:
            decoded = response.json()
            if isinstance(decoded, Mapping):
                payload = decoded
        except (json.JSONDecodeError, ValueError):
            pass

        usage = self._parse_usage(payload.get("usage") if payload else None)
        if usage.cost_usd is None:
            self.ledger.retain(reservation)
        else:
            self.ledger.settle(reservation, usage.cost_usd)

        request_id = payload.get("id") if payload and isinstance(payload.get("id"), str) else None
        returned_model = payload.get("model") if payload and isinstance(payload.get("model"), str) else None
        returned_provider = payload.get("provider") if payload and isinstance(payload.get("provider"), str) else None
        provider_latency = self._optional_number(payload.get("latency")) if payload else None

        if response.is_error:
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "http_error",
                f"OpenRouter returned HTTP {response.status_code}",
                http_status=response.status_code,
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                provider_latency_ms=provider_latency,
            )
        if payload is None:
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_response_json",
                "OpenRouter returned a non-object JSON response",
                usage=usage,
            )

        if returned_model != model_id:
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "model_mismatch",
                "OpenRouter returned a different model than requested",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                provider_latency_ms=provider_latency,
            )

        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_choices",
                "OpenRouter response must contain exactly one choice",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                provider_latency_ms=provider_latency,
            )
        choice = choices[0]
        finish_reason = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
        message = choice.get("message")
        if not isinstance(message, Mapping):
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_message",
                "OpenRouter choice has no message object",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                provider_latency_ms=provider_latency,
            )
        refusal = message.get("refusal")
        reasoning = message.get("reasoning")
        if refusal not in (None, ""):
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "refusal",
                "Model refused the eval request",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                refusal=refusal,
                reasoning=reasoning,
                provider_latency_ms=provider_latency,
            )
        if finish_reason != "stop":
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "incomplete",
                f"Completion did not finish normally ({finish_reason or 'missing'})",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                reasoning=reasoning,
                provider_latency_ms=provider_latency,
            )
        content = message.get("content")
        if not isinstance(content, str):
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_content",
                "Completion content is not a string",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                reasoning=reasoning,
                provider_latency_ms=provider_latency,
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_completion_json",
                "Completion content is not valid JSON",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                reasoning=reasoning,
                provider_latency_ms=provider_latency,
                raw_content=content,
            )
        if not isinstance(parsed, dict):
            return self._failure(
                model_id,
                started,
                reservation_amount,
                "invalid_completion_json",
                "Completion JSON must be an object",
                usage=usage,
                request_id=request_id,
                returned_model=returned_model,
                returned_provider=returned_provider,
                finish_reason=finish_reason,
                reasoning=reasoning,
                provider_latency_ms=provider_latency,
                raw_content=content,
            )
        return CompletionResult(
            ok=True,
            data=parsed,
            requested_model=model_id,
            request_id=request_id,
            returned_model=returned_model,
            returned_provider=returned_provider,
            usage=usage,
            finish_reason=finish_reason,
            refusal=refusal,
            reasoning=reasoning,
            latency_ms=(time.monotonic() - started) * 1000,
            provider_latency_ms=provider_latency,
            reservation_usd=reservation_amount,
            budget_stopped=self.ledger.overrun,
        )

    def _failure(
        self,
        model_id: str,
        started: float,
        reservation_usd: Decimal,
        kind: str,
        message: str,
        *,
        http_status: int | None = None,
        usage: CompletionUsage | None = None,
        request_id: str | None = None,
        returned_model: str | None = None,
        returned_provider: str | None = None,
        finish_reason: str | None = None,
        refusal: Any | None = None,
        reasoning: Any | None = None,
        provider_latency_ms: float | None = None,
        raw_content: str | None = None,
    ) -> CompletionResult:
        return CompletionResult(
            ok=False,
            data=None,
            requested_model=model_id,
            request_id=request_id,
            returned_model=returned_model,
            returned_provider=returned_provider,
            usage=usage or CompletionUsage(),
            finish_reason=finish_reason,
            refusal=refusal,
            reasoning=reasoning,
            latency_ms=(time.monotonic() - started) * 1000,
            provider_latency_ms=provider_latency_ms,
            reservation_usd=reservation_usd,
            error=CompletionError(kind=kind, message=message, http_status=http_status),
            budget_stopped=kind == "budget_exhausted" or self.ledger.overrun,
            raw_content=raw_content,
        )

    def _safe_exception(self, prefix: str, exc: Exception) -> str:
        message = str(exc).replace(self._api_key, "[redacted]")
        return f"{prefix}: {message}" if message else prefix

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            return float(value)
        return None

    @classmethod
    def _parse_usage(cls, raw: object) -> CompletionUsage:
        if not isinstance(raw, Mapping):
            return CompletionUsage()
        details = raw.get("completion_tokens_details")
        reasoning_tokens = cls._optional_int(details.get("reasoning_tokens")) if isinstance(details, Mapping) else None
        prompt_details = raw.get("prompt_tokens_details")
        cached_tokens = (
            cls._optional_int(prompt_details.get("cached_tokens")) if isinstance(prompt_details, Mapping) else None
        )
        try:
            cost = _decimal(raw["cost"]) if raw.get("cost") is not None else None
        except ValueError:
            cost = None
        return CompletionUsage(
            prompt_tokens=cls._optional_int(raw.get("prompt_tokens")),
            completion_tokens=cls._optional_int(raw.get("completion_tokens")),
            total_tokens=cls._optional_int(raw.get("total_tokens")),
            reasoning_tokens=reasoning_tokens,
            cost_usd=cost,
            cached_tokens=cached_tokens,
        )
