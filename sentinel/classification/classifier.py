"""Military news classifier: a facade over the configured classification backend.

``classification.provider`` chooses the backend. ``openai`` is the live
classifier (``OpenAIBackend`` below); ``anthropic`` is the legacy rollback
path in ``legacy_anthropic.py``, which loads the ``anthropic`` package only
when it is selected. There is no automatic fallback between them.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from sentinel.classification.legacy_anthropic import LegacyAnthropicBackend
from sentinel.classification.openai_provider import ClassificationError, OpenAIProvider
from sentinel.classification.policy import messages, prompt_hash
from sentinel.classification.schema import CLASSIFICATION_SCHEMA
from sentinel.classification.summary_language import GUARD_VERSION, ensure_polish
from sentinel.config import SentinelConfig
from sentinel.models import Article, ClassificationResult


class ClassificationBackend(Protocol):
    """One model provider behind ``Classifier``."""

    # Provider errors that ``Classifier.classify_batch`` logs, skipping the article.
    api_errors: tuple[type[Exception], ...]

    async def classify(self, article: Article, incident_context: list[dict] | None) -> ClassificationResult:
        """Classify one article, with the remembered incidents when memory is on."""
        ...

    def log_daily_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Log one UTC day's token usage."""
        ...

    async def aclose(self) -> None:
        """Close the provider's client."""
        ...


class OpenAIBackend:
    """The live classifier: OpenAI structured output under the clarified policy."""

    # OpenAIProvider reports every failure as ClassificationError, which
    # Classifier.classify_batch handles on its own.
    api_errors: tuple[type[Exception], ...] = ()

    def __init__(self, config: SentinelConfig, provider: OpenAIProvider, logger: logging.Logger) -> None:
        self.config = config
        self.provider = provider
        self.logger = logger

    async def classify(self, article: Article, incident_context: list[dict] | None) -> ClassificationResult:
        """Classify one article; raises ClassificationError when OpenAI gives no valid result."""
        cfg = self.config.classification
        reply = await self.provider.request(
            messages(article, incident_context or [], cfg.policy),
            CLASSIFICATION_SCHEMA,
            purpose="classification",
            max_tokens=cfg.max_tokens,
        )
        data = dict(reply.data)
        facts = data.pop("facts")
        if data["summary_pl"].strip():
            data["summary_pl"], summary_processing, repair = await ensure_polish(
                data["summary_pl"], self.provider, cfg.summary_language
            )
        else:
            # The danger assessment is valid; a missing summary must not suppress the alert.
            summary_processing = {
                "version": GUARD_VERSION,
                "original_summary": data["summary_pl"],
                "action": "fallback",
                "repair_error": "Empty model summary",
            }
            data["summary_pl"] = cfg.summary_language.fallback_pl
            repair = None
            self.logger.warning(
                "Empty classification summary for article %s; using the Polish fallback summary", article.id
            )
        calls = [reply] + ([repair] if repair is not None else [])
        return ClassificationResult(
            article_id=article.id,
            **data,
            facts=facts,
            summary_processing=summary_processing,
            classified_at=datetime.now(UTC),
            model_used=cfg.model,
            provider_used="openai",
            prompt_version="clarified-v2:" + prompt_hash(cfg.policy) + ":" + GUARD_VERSION,
            request_hash=reply.request_hash,
            response_id=reply.response_id,
            input_tokens=sum(call.input_tokens for call in calls),
            output_tokens=sum(call.output_tokens for call in calls),
            cached_input_tokens=sum(call.cached_tokens for call in calls),
            estimated_cost_usd=sum(call.cost_usd for call in calls),
        )

    def log_daily_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Log one day's tokens; the costs are in the model usage ledger."""
        self.logger.info(
            "Daily classification tokens: input=%d output=%d; costs in model usage ledger",
            input_tokens,
            output_tokens,
        )

    async def aclose(self) -> None:
        """Close the OpenAI provider and its owned resources."""
        await self.provider.aclose()


class Classifier:
    """Classify through the configured provider without automatic fallback."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("sentinel.classifier")
        # ``provider`` is the OpenAI provider (its budget ledger and client), or
        # None on the legacy path.
        self.provider: OpenAIProvider | None
        self.backend: ClassificationBackend
        if config.classification.provider == "openai":
            self.provider = OpenAIProvider(config.classification)
            self.backend = OpenAIBackend(config, self.provider, self.logger)
        else:
            self.provider = None
            self.backend = LegacyAnthropicBackend(config, self.logger)

        # Daily cost tracking
        self._daily_input_tokens = 0
        self._daily_output_tokens = 0
        self._daily_date: str | None = None

    async def classify(self, article: Article, *, incident_context: list[dict] | None = None) -> ClassificationResult:
        """Classify a single article.

        Raises json.JSONDecodeError, ClassificationError or one of the
        backend's ``api_errors`` on failure.
        """
        result = await self.backend.classify(article, incident_context)
        self._track_tokens(result.input_tokens, result.output_tokens)
        return result

    async def classify_batch(self, articles: list[Article]) -> list[ClassificationResult]:
        """Classify multiple articles sequentially. Skips articles that fail classification."""
        results = []
        for article in articles:
            try:
                result = await self.classify(article)
                results.append(result)
                self.logger.info(
                    "Classified '%s' -> urgency=%d, type=%s, military=%s",
                    article.title[:80],
                    result.urgency_score,
                    result.event_type,
                    result.is_military_event,
                )
            except json.JSONDecodeError as e:
                self.logger.error(
                    "Failed to parse LLM response for '%s': %s",
                    article.title[:80],
                    e,
                )
            except self.backend.api_errors as e:
                self.logger.error(
                    "API error classifying '%s': %s",
                    article.title[:80],
                    e,
                )
            except ClassificationError as e:
                self.logger.error("Classification unavailable for article %s: %s", article.id, e)
        return results

    async def aclose(self) -> None:
        """Close the selected provider and its owned resources."""
        await self.backend.aclose()

    def _track_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate daily token usage and log a summary at day rollover."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        if self._daily_date != today:
            # Log previous day's summary if there was one
            if self._daily_date is not None:
                self._log_daily_summary()
            self._daily_date = today
            self._daily_input_tokens = 0
            self._daily_output_tokens = 0

        self._daily_input_tokens += input_tokens
        self._daily_output_tokens += output_tokens

    def _log_daily_summary(self) -> None:
        """Log accumulated token usage for the day."""
        self.backend.log_daily_usage(self._daily_input_tokens, self._daily_output_tokens)
