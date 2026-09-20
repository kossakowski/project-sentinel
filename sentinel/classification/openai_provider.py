"""Direct OpenAI structured requests with persistent, conservative spending control."""

import asyncio
import hashlib
import json
import logging
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jsonschema
import openai

from sentinel.config import ClassificationConfig, ModelBudgetConfig


class ClassificationError(RuntimeError):
    """Safe operator-facing failure, never a low-danger classification."""


class BudgetExceeded(ClassificationError):
    pass


class UsageLedger:
    """Reservations survive crashes; BEGIN IMMEDIATE serializes independent callers.

    Unknown charges keep their entire reservation. Estimates use configured rates;
    this cannot cap spending by other applications or guarantee provider billing.
    """

    def __init__(self, config: ModelBudgetConfig):
        self.config = config
        if config.ledger_path != ":memory:":
            Path(config.ledger_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.ledger_path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS model_usage (
            id TEXT PRIMARY KEY, month TEXT NOT NULL, model TEXT NOT NULL,
            purpose TEXT NOT NULL, request_hash TEXT NOT NULL, reserved_usd REAL NOT NULL,
            charged_usd REAL NOT NULL, status TEXT NOT NULL,
            input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
            response_id TEXT, created_at TEXT NOT NULL)""")
        self.db.commit()

    def total(self, month=None):
        month = month or datetime.now(UTC).strftime("%Y-%m")
        return self.db.execute(
            "SELECT COALESCE(SUM(charged_usd),0) FROM model_usage WHERE month=?", (month,)
        ).fetchone()[0]

    def reserve(self, amount: float, model: str, purpose: str, request_hash: str) -> str:
        if not math.isfinite(amount) or amount <= 0:
            raise ClassificationError("Invalid model cost reservation")
        now = datetime.now(UTC)
        month = now.strftime("%Y-%m")
        reservation = str(uuid4())
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.total(month) + amount > self.config.monthly_usd:
                raise BudgetExceeded(
                    "Model budget reached: classification paused; articles remain pending. "
                    "Review the usage ledger and billing before changing the spending policy."
                )
            self.db.execute(
                "INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,'reserved',NULL,NULL,NULL,NULL,?)",
                (reservation, month, model, purpose, request_hash, amount, amount, now.isoformat()),
            )
        return reservation

    def settle(self, reservation, input_tokens, cached_tokens, output_tokens, response_id):
        cfg = self.config
        # Conservatively apply the advertised cache-write premium to uncached input.
        # The API does not always expose cache-write counts separately.
        amount = (
            (input_tokens - cached_tokens) * cfg.input_per_million * cfg.cache_write_multiplier
            + cached_tokens * cfg.cached_input_per_million
            + output_tokens * cfg.output_per_million
        ) / 1_000_000
        with self.db:
            self.db.execute(
                "UPDATE model_usage SET charged_usd=?, status='settled', input_tokens=?, "
                "cached_tokens=?, output_tokens=?, response_id=? WHERE id=?",
                (amount, input_tokens, cached_tokens, output_tokens, response_id, reservation),
            )
        return amount

    def close(self):
        self.db.close()


@dataclass(frozen=True)
class StructuredReply:
    data: dict
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float
    request_hash: str
    response_id: str


def validate_json(raw: str, schema: dict) -> dict:
    try:

        def reject_constant(value):
            raise ValueError("Non-finite JSON number")

        data = json.loads(raw, parse_constant=reject_constant)
        jsonschema.Draft202012Validator(schema).validate(data)
    except (ValueError, TypeError, jsonschema.ValidationError):
        # Do not log raw provider responses (or untrusted article text).
        raise ClassificationError("Invalid structured model output; article remains pending") from None
    return data


class OpenAIProvider:
    def __init__(self, config: ClassificationConfig):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ClassificationError(
                "OPENAI_API_KEY is missing. Store a dedicated OpenAI project key in the ignored .env; "
                "API billing is separate from the Codex subscription."
            )
        self.config = config
        # Explicit base URL prevents OPENAI_BASE_URL from routing credentials elsewhere.
        self.client = openai.AsyncOpenAI(
            api_key=key,
            base_url=config.api_base_url,
            max_retries=0,
            timeout=config.timeout_seconds,
        )
        self.ledger = UsageLedger(config.budget)
        self.session_remaining: float | None = None
        self.logger = logging.getLogger("sentinel.openai")

    async def request(self, messages: list[dict], schema: dict, *, purpose: str, max_tokens: int) -> StructuredReply:
        cfg = self.config
        payload = dict(
            model=cfg.model,
            input=messages,
            reasoning={"effort": cfg.reasoning_effort},
            text={"format": {"type": "json_schema", "name": purpose, "strict": True, "schema": schema}},
            max_output_tokens=max_tokens,
            store=False,
            service_tier="default",
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        request_hash = hashlib.sha256(encoded).hexdigest()
        # UTF-8 bytes exceed text-token counts; include generous framing allowance.
        input_bound = len(encoded) + 4096
        if input_bound > 250_000:
            raise ClassificationError("Model input exceeds the bounded standard-price request size")
        budget = cfg.budget
        bound = (
            input_bound * budget.input_per_million * budget.cache_write_multiplier
            + max_tokens * budget.output_per_million
        ) / 1_000_000
        if self.session_remaining is not None:
            if bound > self.session_remaining:
                raise BudgetExceeded("Explicit test spending cap reached; no further request sent")
            self.session_remaining -= bound
        reservation = self.ledger.reserve(bound, cfg.model, purpose, request_hash)
        try:
            async with asyncio.timeout(cfg.timeout_seconds):
                response = await self.client.responses.create(**payload)
        except openai.AuthenticationError:
            raise ClassificationError("OpenAI rejected the key. Check the dedicated project's API key.") from None
        except openai.PermissionDeniedError:
            raise ClassificationError("OpenAI access denied. Check project model and Responses permissions.") from None
        except openai.RateLimitError as exc:
            if exc.code == "insufficient_quota":
                message = "OpenAI credit/quota exhausted. Check API billing; classification is paused."
            else:
                message = "OpenAI rate limit reached. Articles remain pending for a later retry."
            raise ClassificationError(message) from None
        except (openai.APIError, TimeoutError):
            raise ClassificationError(
                "OpenAI request failed or timed out. Article remains pending; possible charge reserved. "
                "Check API availability, model access and billing."
            ) from None
        usage = response.usage
        if usage is None:
            raise ClassificationError("OpenAI omitted usage; reservation retained and article remains pending")
        incoming, outgoing = usage.input_tokens, usage.output_tokens
        cached = usage.input_tokens_details.cached_tokens if usage.input_tokens_details else 0
        if (
            any(type(v) is not int or v < 0 for v in (incoming, outgoing, cached))
            or cached > incoming
            or incoming > input_bound
            or outgoing > max_tokens
        ):
            raise ClassificationError("OpenAI usage exceeded request bounds; reservation retained")
        cost = self.ledger.settle(reservation, incoming, cached, outgoing, response.id)
        if self.session_remaining is not None:
            self.session_remaining += bound - cost
        # Bill even refused, malformed or incomplete answers; no fresh call is hidden here.
        if response.status != "completed":
            raise ClassificationError("OpenAI response incomplete/failed; article remains pending")
        if usage.output_tokens_details and usage.output_tokens_details.reasoning_tokens:
            raise ClassificationError(
                "OpenAI reported reasoning tokens despite reasoning=none; article remains pending"
            )
        if response.model != cfg.model and not response.model.startswith(cfg.model + "-"):
            raise ClassificationError("OpenAI returned an unexpected model; article remains pending")
        for item in response.output:
            for content in getattr(item, "content", []):
                if content.type == "refusal":
                    raise ClassificationError("OpenAI refused classification; article remains pending")
        data = validate_json(response.output_text, schema)
        self.logger.info(
            "OpenAI %s: input=%d cached=%d output=%d estimated_usd=%.6f month_usd=%.4f",
            purpose,
            incoming,
            cached,
            outgoing,
            cost,
            self.ledger.total(),
        )
        return StructuredReply(data, incoming, cached, outgoing, cost, request_hash, response.id)

    async def aclose(self):
        try:
            await self.client.close()
        finally:
            self.ledger.close()
