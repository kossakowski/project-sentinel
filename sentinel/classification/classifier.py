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
    '- A "special military operation" or similar euphemism from Russian media describing action '
    "against a target country IS an attack\n"
    "- The 'Source:' field is metadata identifying WHERE the article was found, NOT what it says. "
    "For Google News sources (e.g. 'GoogleNews:drone incursion Poland'), the source name contains "
    "the search query -- this is NOT article content. Classify ONLY based on 'Title:' and 'Summary:'. "
    "Do NOT infer that a country is affected because it appears in the source name.\n"
    "- An attack on assets associated with country X but physically located in country Y is an attack on "
    "Y, NOT X. Score affected_countries based on the PHYSICAL LOCATION of the attack.\n"
    "- If the headline and summary do NOT explicitly state which country was attacked, do NOT assume "
    "it was a monitored country. Assign urgency 2-3 and confidence below 0.5.\n"
    "\n"
    "CALIBRATION RULES (apply these in order):\n"
    "\n"
    "R1 SHELTER/EVACUATION ORDERS: If authorities in PL/LT/LV/EE issue shelter-in-place orders, "
    "air raid alerts, or evacuation orders due to an aerial threat, score MINIMUM 9. This is "
    "non-negotiable. 'Told to shelter', 'find protection', 'seek cover', 'air alert issued' in "
    "a monitored country = 9-10. Do NOT score 7-8 for these. Shelter orders ARE the attack.\n"
    "\n"
    "R2 OFFENSIVE WEAPONS OVER MONITORED TERRITORY: If attack-capable weapons (Shaheds, cruise "
    "missiles, military drones designed for strikes) are named as flying over or present in "
    "PL/LT/LV/EE airspace, score MINIMUM 9. 'Shaheds over Poland' = 10. 'Drones violating "
    "airspace of NATO state' with shelter warnings = 9. Never score below 9 when named offensive "
    "weapons are over monitored territory.\n"
    "\n"
    "R3 STRIKE ON/AT MONITORED TERRITORY: If the article describes a strike ON or AT a monitored "
    "country's border or territory, score MINIMUM 9. 'Russian strike on NATO border' = 9. "
    "Do NOT downgrade to 'precautionary scramble' (5-6) if a STRIKE is described. The word "
    "'strike' means kinetic impact happened — score it as such.\n"
    "\n"
    "R4 POLAND PRIORITY: Events involving Poland score higher than equivalent events in LT/LV/EE. "
    "A drone found on Polish territory = 8; the same event in Latvia = 5-6. Poland is the "
    "primary monitored country.\n"
    "\n"
    "R5 NUCLEAR ACTIVITY NEAR BORDER: Nuclear drills, nuclear weapons deployment, movement of "
    "nuclear-capable units near PL/LT/LV/EE = urgency 7 minimum. The 'exercise/drill' exclusion "
    "does NOT apply to nuclear weapons activities. Nuclear + military + near border = at least 7.\n"
    "\n"
    "R6 POLITICAL AFTERMATH IS NOT THREAT: Articles about officials resigning over past incidents, "
    "NATO/EU solidarity statements, political analysis of consequences, diplomatic fallout, "
    "or post-event reporting ('after strike', 'in wake of', 'in turmoil after', 'quits after', "
    "'exposes gaps') = urgency 2-4 maximum, even if military keywords appear. KEY TEST: does the "
    "headline describe something HAPPENING NOW that poses PHYSICAL danger, or does it describe "
    "REACTIONS/CONSEQUENCES of something that already happened? Past-tense reporting about "
    "political fallout is NEVER above 4. A resignation, a solidarity statement, a 'what now?' "
    "article = 3-4 at most.\n"
    "\n"
    "R7 CRASH != ATTACK: A drone 'crashing', 'found on ground', or 'discovered' suggests "
    "accidental overflight, NOT intentional attack. If the drone is identified as UKRAINIAN "
    "or origin is unknown AND it crashed/was found (not fired/struck), score 4 maximum — this "
    "is an accident, not an attack. Only score 5+ for crashed drones if there is explicit "
    "evidence of hostile intent or Russian origin. 'Crashed' = accident = LOG; 'struck' = attack.\n"
    "\n"
    "R8 RHETORIC/THREATS WITHOUT ACTION: Warnings, threats, or statements by leaders without "
    "accompanying military action are primarily posturing. HOWEVER, distinguish two cases: "
    "(a) Generic posturing/bluster with no specific target = urgency 3-4. "
    "(b) Direct threats of RETALIATION against a monitored country (e.g. 'Putin warns Latvia', "
    "'Russia threatens retaliation against NATO allies') = urgency 7. Direct threats naming "
    "monitored countries are alarming even without immediate action.\n"
    "\n"
    "R9 UKRAINE-ONLY WARZONE: Attacks on Ukraine with no spillover to PL/LT/LV/EE = urgency "
    "1-3. EXCEPTION: if the article describes a significant CAPABILITY escalation that increases "
    "risk to monitored countries (e.g. massive drone production increase, new long-range weapons "
    "that can reach Poland), score 5.\n"
    "\n"
    "R10 SCALE MATTERS: Single drone/incident = lower urgency. Mass attack (multiple missiles, "
    "dozens of drones, large troop formations) = higher urgency. One unidentified drone = 5-6; "
    "swarm of Shaheds over territory = 9-10.\n"
    "\n"
    "PRECAUTIONARY SCRAMBLE RULE: A country scrambling jets or activating air defense as a "
    "PRECAUTION -- when NO strike or violation of monitored territory is described -- is urgency "
    "5-6. But if a strike IS described alongside the scramble, score based on the strike.\n"
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
    '  "summary_pl": "Krótkie podsumowanie po polsku (1-2 zdania) do komunikatu telefonicznego"\n'
    "}}\n"
    "\n"
    "Urgency scale:\n"
    "1-2: Routine military news, no threat (Ukraine warzone reporting, military tech articles, training)\n"
    "3-4: Minor incident or political aftermath (diplomatic reactions, commentary, rhetoric without action)\n"
    "5-6: Notable incident requiring awareness (single drone found near border, accidental overflight, "
    "capability escalation in adjacent theater)\n"
    "7-8: Serious escalation requiring monitoring (nuclear drills near border, air alerts in Baltic states, "
    "active air defense engagement, Putin directly threatening monitored countries)\n"
    "9-10: Active attack or imminent danger (shelter orders issued, offensive weapons over monitored "
    "territory, strikes on/at monitored borders, Article 5 invoked)\n"
    "\n"
    "CRITICAL RULES:\n"
    "- Urgency 9-10 is EXCLUSIVELY for attacks directly targeting PL, LT, LV, or EE territory.\n"
    "- Attacks on Ukraine or other non-monitored countries = urgency 1-3, UNLESS they represent "
    "a capability escalation threatening monitored countries (then 5 max).\n"
    "- affected_countries: ONLY list countries EXPLICITLY mentioned in the article as attacked. "
    "Do NOT infer affected countries from the monitoring scope. Use [] if none explicitly mentioned."
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
        prompt = USER_PROMPT_TEMPLATE.format(
            source_name=article.source_name,
            source_type=article.source_type,
            language=article.language,
            published_at=published,
            title=article.title,
            summary=article.summary,
        )
        enrichment = article.raw_metadata.get("enrichment", {})
        if enrichment.get("method") in ("heuristic", "llm") and not enrichment.get("fetched"):
            prompt = prompt.replace(
                f"Summary: {article.summary}",
                f"Summary: {article.summary}\n"
                "Note: Article body could not be fetched. The summary above may just be "
                "the headline repeated. Exercise extreme caution with country attribution "
                "— do not assume a monitored country is affected unless explicitly stated.",
            )
        return prompt

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
