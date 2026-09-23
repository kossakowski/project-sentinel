"""Direct, bounded TypeSafe requests for local evaluation only."""

import asyncio
import hashlib
import json
import os
from copy import deepcopy

import httpx

from sentinel.classification.openai_provider import ClassificationError, UsageLedger
from sentinel.config import ModelBudgetConfig


def encoded(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()


def check_size(payload, settings):
    # UTF-8 byte length plus framing is intentionally more conservative than tokens.
    state_size = len(encoded(payload["state"]))
    largest = max(len(encoded(q)) for q in payload["questions"].values())
    if state_size + largest + 4096 > settings["state_question_token_limit"]:
        raise ValueError("Jev state plus longest question exceeds conservative input bound")
    if len(encoded(payload)) + 4096 > settings["request_token_limit"]:
        raise ValueError("Jev request exceeds conservative input bound")


def pack_request(payload, settings):
    """Pool identical source rules only when the original byte bound is exceeded.

    All article text, candidate incidents, choices and rule text remain present.
    Previously fitting requests stay byte-for-byte identical for cache recovery.
    """
    try:
        check_size(payload, settings)
        return payload, "inline"
    except ValueError:
        packed = deepcopy(payload)
        disciplines = {q["instructions"]["source_discipline"] for q in packed["questions"].values()}
        if len(disciplines) != 1 or "shared_source_discipline" in packed["state"]:
            raise ValueError("Oversized Jev request cannot safely pool its source rules") from None
        packed["state"]["shared_source_discipline"] = disciplines.pop()
        for question in packed["questions"].values():
            question["instructions"]["source_discipline"] = (
                "Follow the complete source rules in `shared_source_discipline`."
            )
        check_size(packed, settings)
        return packed, "shared-source-discipline-v1"


class TypeSafeEvalClient:
    def __init__(self, settings, ledger_path, budget_usd, *, transport=None):
        key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not key:
            raise ClassificationError("TYPESAFE_API_KEY is missing; store it in the ignored project .env")
        self.settings = settings
        self.ledger = UsageLedger(
            ModelBudgetConfig(
                ledger_path=str(ledger_path),
                monthly_usd=budget_usd,
                input_per_million=settings["input_per_million"],
                cached_input_per_million=settings["input_per_million"],
                cache_write_multiplier=1,
            )
        )
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {key}"},
            transport=transport,
            timeout=settings["timeout_seconds"],
            follow_redirects=False,
        )

    async def request(self, payload):
        check_size(payload, self.settings)
        digest = hashlib.sha256(encoded(payload)).hexdigest()
        # Reserve the full model context: unknown or timed-out charges stay reserved.
        bound = self.settings["request_token_limit"] * self.settings["input_per_million"] / 1_000_000
        reservation = self.ledger.reserve(bound, payload["model"], "jev_evaluation", digest)
        try:
            async with asyncio.timeout(self.settings["timeout_seconds"]):
                result = await self.client.post(self.settings["endpoint"], json=payload)
        except (httpx.HTTPError, TimeoutError):
            raise ClassificationError("TypeSafe transport failure; possible charge remains reserved") from None
        if result.status_code != 200:
            # Never include headers, response text or exception repr in the transcript.
            raise ClassificationError(f"TypeSafe HTTP {result.status_code}; possible charge remains reserved")
        try:
            raw = result.json()
            usage = raw["usage"]
            incoming, outgoing = usage["input_tokens"], usage["output_tokens"]
            if any(type(v) is not int or v < 0 for v in (incoming, outgoing)):
                raise ValueError
            if incoming > self.settings["request_token_limit"]:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ClassificationError("Invalid TypeSafe usage; possible charge remains reserved") from None
        # The shared ledger records billable tokens. Jev output is free; preserve
        # actual output counts separately in the response journal below.
        cost = self.ledger.settle(reservation, incoming, 0, 0, None)
        return {
            "raw_response": raw,
            "request_sha256": digest,
            "cost_usd": cost,
            "usage": {"prompt_tokens": incoming, "completion_tokens": outgoing},
        }

    async def aclose(self):
        try:
            await self.client.aclose()
        finally:
            self.ledger.close()
