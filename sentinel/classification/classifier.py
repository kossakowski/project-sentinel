"""Classifier -- sends articles to Claude Haiku 4.5 for military event classification."""

import json
import logging
import re
import time
from datetime import datetime, timezone

import anthropic

from sentinel.config import SentinelConfig
from sentinel.models import Article, ClassificationResult

SYSTEM_PROMPT = (
    "You are a military intelligence analyst monitoring media for signs of military attacks "
    "or invasions targeting Poland, Lithuania, Latvia, or Estonia by Russia, Belarus, or their allies.\n"
    "\n"
    "Your task is to analyze a news article and determine:\n"
    "1. Whether it describes an actual or imminent military attack (not exercises, not historical events, not analysis/opinion)\n"
    "2. The type and severity of the event\n"
    "3. A Polish-language summary suitable for an emergency phone alert\n"
    "\n"
    "IMPORTANT DISTINCTIONS:\n"
    "- An actual attack/invasion = troops crossing borders, missiles launched, bombs dropped, "
    "airspace violated by military aircraft with hostile intent\n"
    "- NOT an attack = military exercises, diplomatic tensions, troop movements within own borders, "
    "historical references, analysis pieces, opinion articles, routine border patrols\n"
    "- Airspace violation by drones/aircraft CAN be a precursor to attack -- score these 6-8 depending on scale\n"
    '- A "special military operation" or similar euphemism from Russian media describing action '
    "against a target country IS an attack\n"
    "\n"
    "Respond ONLY with valid JSON. No markdown, no explanation, no preamble."
)

USER_PROMPT_TEMPLATE = (
    "Analyze this article:\n"
    "\n"
    "Source: {source_name} ({source_type})\n"
    "Language: {language}\n"
    "Published: {published_at}\n"
    "Title: {title}\n"
    "Summary: {summary}\n"
    "\n"
    "Respond with JSON:\n"
    "{{\n"
    '  "is_military_event": true/false,\n'
    '  "event_type": "invasion|airstrike|missile_strike|border_crossing|airspace_violation'
    '|naval_blockade|cyber_attack|troop_movement|artillery_shelling|drone_attack|other|none",\n'
    '  "urgency_score": 1-10,\n'
    '  "affected_countries": ["PL", "LT", "LV", "EE"],\n'
    '  "aggressor": "RU|BY|unknown|none",\n'
    '  "is_new_event": true/false,\n'
    '  "confidence": 0.0-1.0,\n'
    '  "summary_pl": "Krotkie podsumowanie po polsku (1-2 zdania) do komunikatu telefonicznego"\n'
    "}}\n"
    "\n"
    "Urgency scale:\n"
    "1-2: Routine military news, no threat\n"
    "3-4: Minor incident, low concern\n"
    "5-6: Notable incident (airspace violation, border provocation, significant troop movement near border)\n"
    "7-8: Serious escalation (shots fired at border, large-scale airspace violation, "
    "cyberattack on critical infrastructure, partial mobilization)\n"
    "9-10: Active military attack or invasion (troops crossing border, missiles striking targets, "
    "declaration of war, Article 5 invoked)"
)

# Regex to extract JSON from markdown-wrapped responses
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class Classifier:
    """Classifies articles using Claude Haiku 4.5."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
        self.logger = logging.getLogger("sentinel.classifier")

        # Daily cost tracking
        self._daily_input_tokens = 0
        self._daily_output_tokens = 0
        self._daily_date: str | None = None

    def classify(self, article: Article) -> ClassificationResult:
        """Classify a single article.

        Raises json.JSONDecodeError or anthropic.APIError on failure.
        """
        response = self._call_api(article)

        # Parse JSON response
        raw_text = response.content[0].text.strip()
        data = self._parse_json(raw_text)

        # Clamp values to valid ranges
        urgency = max(1, min(10, int(data.get("urgency_score", 1))))
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

        result = ClassificationResult(
            article_id=article.id,
            is_military_event=bool(data.get("is_military_event", False)),
            event_type=data.get("event_type", "none"),
            urgency_score=urgency,
            affected_countries=data.get("affected_countries", []),
            aggressor=data.get("aggressor", "none"),
            is_new_event=bool(data.get("is_new_event", True)),
            confidence=confidence,
            summary_pl=data.get("summary_pl", ""),
            classified_at=datetime.now(timezone.utc),
            model_used=self.config.classification.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # Track tokens
        self._track_tokens(response.usage.input_tokens, response.usage.output_tokens)

        return result

    def classify_batch(self, articles: list[Article]) -> list[ClassificationResult]:
        """Classify multiple articles. Skips articles that fail classification."""
        results = []
        for article in articles:
            try:
                result = self.classify(article)
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
            except anthropic.APIError as e:
                self.logger.error(
                    "API error classifying '%s': %s",
                    article.title[:80],
                    e,
                )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_prompt(self, article: Article) -> str:
        """Build the user prompt for classification."""
        published = article.published_at.isoformat() if article.published_at else "unknown"
        return USER_PROMPT_TEMPLATE.format(
            source_name=article.source_name,
            source_type=article.source_type,
            language=article.language,
            published_at=published,
            title=article.title,
            summary=article.summary,
        )

    def _call_api(self, article: Article) -> anthropic.types.Message:
        """Call the Anthropic API with one retry on API errors."""
        try:
            return self._send_request(article)
        except anthropic.APIError as e:
            self.logger.warning(
                "API error (will retry in 5s) for '%s': %s",
                article.title[:80],
                e,
            )
            time.sleep(5)
            return self._send_request(article)

    def _send_request(self, article: Article) -> anthropic.types.Message:
        """Send a single request to the Anthropic API."""
        return self.client.messages.create(
            model=self.config.classification.model,
            max_tokens=self.config.classification.max_tokens,
            temperature=self.config.classification.temperature,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": self._build_user_prompt(article),
            }],
        )

    @staticmethod
    def _parse_json(raw_text: str) -> dict:
        """Parse JSON from the LLM response, with regex recovery for markdown-wrapped output."""
        if not raw_text:
            raise json.JSONDecodeError("Empty response from LLM", "", 0)

        # Try direct parse first
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON block from markdown
        match = _JSON_BLOCK_RE.search(raw_text)
        if match:
            return json.loads(match.group(0))

        raise json.JSONDecodeError(
            "Could not extract JSON from LLM response", raw_text, 0
        )

    def _track_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate daily token usage and log a summary at day rollover."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
        # Haiku pricing: $0.80/M input, $4.00/M output (Claude Haiku 4.5)
        input_cost = self._daily_input_tokens * 0.80 / 1_000_000
        output_cost = self._daily_output_tokens * 4.00 / 1_000_000
        total_cost = input_cost + output_cost

        self.logger.info(
            "Daily usage: %s input tokens, %s output tokens, estimated cost: $%.3f",
            f"{self._daily_input_tokens:,}",
            f"{self._daily_output_tokens:,}",
            total_cost,
        )
