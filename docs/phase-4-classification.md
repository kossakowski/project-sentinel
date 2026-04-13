# Phase 4: Classification Engine

> STATUS: COMPLETE — implemented in production
> KEY FILES: `sentinel/classification/classifier.py`, `sentinel/classification/corroborator.py`

## Objective
Use Claude Haiku 4.5 to classify pre-filtered articles, score urgency, and detect when multiple sources report the same event (corroboration).

## Deliverables

### 4.1 Classifier (`sentinel/classification/classifier.py`)

Sends each keyword-matched article to Claude Haiku for classification, extracting structured data about the event.

#### Classification Prompt

The system prompt and user prompt must be carefully engineered to produce reliable, structured output.

**System Prompt:**
```
You are a military intelligence analyst monitoring media for signs of military attacks
or invasions targeting Poland, Lithuania, Latvia, or Estonia by Russia, Belarus, or their allies.

Your task is to analyze a news article and determine:
1. Whether it describes an actual or imminent military attack (not exercises, not historical events, not analysis/opinion)
2. The type and severity of the event
3. A Polish-language summary suitable for an emergency phone alert

IMPORTANT DISTINCTIONS:
- An actual attack/invasion = troops crossing borders, missiles launched, bombs dropped, airspace violated by military aircraft with hostile intent
- NOT an attack = military exercises, diplomatic tensions, troop movements within own borders, historical references, analysis pieces, opinion articles, routine border patrols
- Airspace violation by drones/aircraft CAN be a precursor to attack -- score these 6-8 depending on scale
- A "special military operation" or similar euphemism from Russian media describing action against a target country IS an attack

Respond ONLY with valid JSON. No markdown, no explanation, no preamble.
```

**User Prompt Template:**
```
Analyze this article:

Source: {source_name} ({source_type})
Language: {language}
Published: {published_at}
Title: {title}
Summary: {summary}

Respond with JSON:
{{
  "is_military_event": true/false,
  "event_type": "invasion|airstrike|missile_strike|border_crossing|airspace_violation|naval_blockade|cyber_attack|troop_movement|artillery_shelling|drone_attack|other|none",
  "urgency_score": 1-10,
  "affected_countries": ["PL", "LT", "LV", "EE"],
  "aggressor": "RU|BY|unknown|none",
  "is_new_event": true/false,
  "confidence": 0.0-1.0,
  "summary_pl": "Krótkie podsumowanie po polsku (1-2 zdania) do komunikatu telefonicznego"
}}

Urgency scale:
1-2: Routine military news, no threat
3-4: Minor incident, low concern
5-6: Notable incident (airspace violation, border provocation, significant troop movement near border)
7-8: Serious escalation (shots fired at border, large-scale airspace violation, cyberattack on critical infrastructure, partial mobilization)
9-10: Active military attack or invasion (troops crossing border, missiles striking targets, declaration of war, Article 5 invoked)
```

#### API Call Implementation

```python
import anthropic
import json

class Classifier:
    def __init__(self, config: SentinelConfig):
        self.config = config
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
        self.logger = logging.getLogger("sentinel.classifier")

    def classify(self, article: Article) -> ClassificationResult:
        """Classify a single article."""
        response = self.client.messages.create(
            model=self.config.classification.model,
            max_tokens=self.config.classification.max_tokens,
            temperature=self.config.classification.temperature,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": self._build_user_prompt(article),
            }],
        )

        # Parse JSON response
        raw_json = response.content[0].text
        data = json.loads(raw_json)

        return ClassificationResult(
            article_id=article.id,
            is_military_event=data["is_military_event"],
            event_type=data["event_type"],
            urgency_score=data["urgency_score"],
            affected_countries=data["affected_countries"],
            aggressor=data["aggressor"],
            is_new_event=data["is_new_event"],
            confidence=data["confidence"],
            summary_pl=data["summary_pl"],
            classified_at=datetime.utcnow(),
            model_used=self.config.classification.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def classify_batch(self, articles: list[Article]) -> list[ClassificationResult]:
        """Classify multiple articles. Skips articles that fail classification."""
        results = []
        for article in articles:
            try:
                result = self.classify(article)
                results.append(result)
                self.logger.info(
                    f"Classified '{article.title[:80]}' -> "
                    f"urgency={result.urgency_score}, "
                    f"type={result.event_type}, "
                    f"military={result.is_military_event}"
                )
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse LLM response for '{article.title[:80]}': {e}")
            except anthropic.APIError as e:
                self.logger.error(f"API error classifying '{article.title[:80]}': {e}")
        return results
```

#### Classifier Behavior (live)

| Aspect | Value | Anchor |
|---|---|---|
| API calls | 1 per article; no batching | `classifier.py:138` |
| `anthropic.APIError` retry | ONCE after 5s sleep, then skip | `classifier.py:182-193` |
| `json.JSONDecodeError` retry | NONE — article skipped | `classifier.py:152-157` |
| JSON recovery | regex `\{.*\}` with `re.DOTALL` if direct `json.loads` fails | `classifier.py:209-227` |
| `urgency_score` clamp | clamped into 1–10 | `classifier.py` |
| `confidence` clamp | clamped into [0.0, 1.0] | `classifier.py` |
| Confidence gating | NONE — all results passed through regardless of confidence | — |

#### Cost Tracking

| Field | Value | Anchor |
|---|---|---|
| Accumulation | daily cumulative token counters | `classifier.py` |
| Flush trigger | UTC date rollover | `classifier.py:246-248` |
| Input price | `$0.80 / M tokens` (HARDCODED) | `classifier.py:246-248` |
| Output price | `$4.00 / M tokens` (HARDCODED) | `classifier.py:246-248` |
| Config override | NONE — prices are not configurable | — |

Example log line:
```
2025-09-10 [INFO] sentinel.classifier: Daily usage: 15,234 input tokens, 4,521 output tokens, estimated cost: $0.038
```

#### Output Schema

| Field | Type | Notes |
|---|---|---|
| `is_military_event` | bool | — |
| `event_type` | enum | includes `none` sentinel for non-military results |
| `urgency_score` | int 1–10 | clamped |
| `affected_countries` | list[str] | ISO codes |
| `aggressor` | enum | `RU` \| `BY` \| `unknown` \| `none` |
| `is_new_event` | bool | — |
| `confidence` | float [0.0, 1.0] | clamped; NOT thresholded |
| `summary_pl` | str | Polish summary for alert |

### 4.2 Corroborator (`sentinel/classification/corroborator.py`)

Groups classified articles into "events" -- the same real-world incident reported by multiple sources.

#### Event Creation Floor

| Rule | Value | Anchor |
|---|---|---|
| `_MIN_EVENT_URGENCY` | `5` — articles below urgency 5 never create/update an event | `corroborator.py:28` |
| `none` event_type | filtered out (sentinel for non-military results) | `corroborator.py` |

#### Event Match Criteria

All four must hold (`corroborator.py:87`):

| # | Criterion | Anchor |
|---|---|---|
| 1 | `event_type` compatible via `EVENT_COMPATIBILITY` dict | `corroborator.py` |
| 2 | `affected_countries` overlap (≥1 shared ISO code) | `corroborator.py:87` |
| 3 | time diff ≤ `corroboration_window_minutes` | `corroborator.py:87` |
| 4 | `fuzz.token_sort_ratio(summary_pl) >= 55` (`_SUMMARY_SIMILARITY_THRESHOLD`) | `corroborator.py:87` |

#### Compatible Event Types
```python
EVENT_COMPATIBILITY = {
    "invasion": {"invasion", "troop_movement", "border_crossing", "ground_assault"},
    "airstrike": {"airstrike", "missile_strike", "aerial_bombardment", "drone_attack"},
    "missile_strike": {"missile_strike", "airstrike", "artillery_shelling"},
    "border_crossing": {"border_crossing", "invasion", "troop_movement"},
    "airspace_violation": {"airspace_violation", "drone_attack"},
    "drone_attack": {"drone_attack", "airspace_violation", "airstrike"},
    "artillery_shelling": {"artillery_shelling", "missile_strike"},
    "naval_blockade": {"naval_blockade"},
    "cyber_attack": {"cyber_attack"},
}
```

#### Event Lifecycle

```
1. New classification arrives with urgency >= 5
2. Check existing active events for a match (same type + country + time window)
3. If match found:
   - Add article to existing event
   - Update event.source_count
   - Update event.urgency_score = max(current, new)
   - Update event.last_updated_at
4. If no match:
   - Create new event
   - Set source_count = 1
   - Set alert_status = "pending"
5. Check if event meets alert threshold (see table below)
```

#### Alert Thresholds (live)

Anchors: `sentinel/classification/corroborator.py:_determine_alert_status`, `sentinel/alerts/state_machine.py:_determine_action`.

| Action | Urgency | source_count | Notes |
|---|---|---|---|
| Phone call | `>= 9` | `>= config.classification.corroboration_required` | Pydantic default `2`; `config.example.yaml` AND live production both set `1` (live override) |
| SMS | `>= 7` | NOT CHECKED | No `source_count` gate — single source suffices |
| WhatsApp | `>= 5` | NOT CHECKED | Unreachable in production: `AlertStateMachine.process_event` routes `whatsapp` action into `_execute_sms` (`state_machine.py:190`) |

#### Interface

```python
class Corroborator:
    def __init__(self, db: Database, config: SentinelConfig):
        self.db = db
        self.config = config

    def process_classifications(self, results: list[ClassificationResult]) -> list[Event]:
        """Group classifications into events.
        Returns list of events that need alerting (new or updated)."""

    def _find_matching_event(self, result: ClassificationResult) -> Event | None:
        """Find an existing active event that matches this classification."""

    def _are_compatible_types(self, type1: str, type2: str) -> bool:
        """Check if two event types are compatible."""

    def _create_event(self, result: ClassificationResult, article: Article) -> Event:
        """Create a new event from a classification."""

    def _update_event(self, event: Event, result: ClassificationResult, article: Article) -> Event:
        """Add a new source to an existing event."""
```

#### Corroboration Source Independence

Two articles from the same underlying source don't count as independent corroboration:
- PAP wire story picked up by Onet, Gazeta, WP = 1 source (PAP), not 4
- Reuters story on BBC, CNN, Al Jazeera = 1 source (Reuters), not 4

Independence check (`corroborator.py:145`):

| Rule | Outcome |
|---|---|
| Same domain across two articles | NOT independent |
| `fuzz.ratio(title_normalized) >= 90` across sources | NOT independent (syndication) |
| Otherwise | Independent |

This is imperfect but practical. The key is: 2 truly independent confirmations before a phone call.

### 4.3 Dry-Run Mode for Classification

When `--dry-run` is active:
- Classifier still calls Claude Haiku (to test classification accuracy)
- Results are logged with full detail
- Events are created in the database
- But alert_status is set to "dry_run" instead of "pending"
- No alerts are dispatched

When `--test-headline` is used:
- Create a synthetic Article from the headline text
- Classify it
- Print the full ClassificationResult to stdout in a readable format
- Do not store in database
- Exit after printing

When `--test-file` is used:
- Load headlines from YAML file (see testing.md for format)
- Classify each one
- Print results in a table format
- Optionally compare against expected scores in the YAML
- Exit after printing

## Known Quirks

| # | Quirk |
|---|---|
| 1 | Two parallel urgency decision paths: `Corroborator._determine_alert_status` writes `event.alert_status` to DB; `AlertStateMachine._determine_action` ignores the stored value and re-decides from `config.alerts.urgency_levels`. They can disagree if `classification.*` and `alerts.urgency_levels` drift. |
| 2 | Classifier prices are HARDCODED (`$0.80/M input`, `$4.00/M output`) — config does not control this. If Anthropic pricing changes, daily cost log diverges from reality. |
| 3 | `confidence` is clamped to [0.0, 1.0] but NOT thresholded — low-confidence classifications still flow downstream to the corroborator and alerter. |
| 4 | `event_type = "none"` is a sentinel for non-military results; the corroborator must filter it out before event creation. |
| 5 | WhatsApp alert branch is unreachable in production: `AlertStateMachine.process_event` routes `whatsapp` → `_execute_sms` (`state_machine.py:190`). |
| 6 | SMS threshold has NO `source_count` gate — a single source at urgency ≥ 7 triggers SMS. Only phone calls require corroboration. |

## Acceptance Tests

### test_classifier.py
1. `test_classify_invasion_headline` -- "Russia invades Poland" → urgency 10, event_type "invasion"
2. `test_classify_exercise_headline` -- "NATO conducts military exercises in Poland" → is_military_event False, urgency 1-2
3. `test_classify_airspace_violation` -- "Russian drone violates Polish airspace" → urgency 6-8
4. `test_classify_historical` -- "Anniversary of WWII invasion of Poland" → is_military_event False, urgency 1
5. `test_classify_opinion_piece` -- "Analysis: Could Russia attack the Baltics?" → is_military_event False, urgency 2-3
6. `test_classify_polish_headline` -- "Rosja zaatakowała Polskę" → urgency 10, summary_pl is Polish
7. `test_classify_ukrainian_headline` -- "Росія вторглася в Польщу" → urgency 10
8. `test_classify_russian_provocation_framing` -- "Polska provocirovala Rossiju" → urgency 7+ (Russian media framing)
9. `test_classify_ambiguous` -- "Troops seen near Polish border" → urgency 4-6, confidence < 0.7
10. `test_json_parse_recovery` -- LLM returns JSON wrapped in markdown → extracted successfully
11. `test_api_error_handled` -- API returns 500 → logged, article skipped
12. `test_token_usage_logged` -- input/output tokens recorded in result

### test_corroborator.py
1. `test_single_source_creates_event` -- one classification → one event with source_count=1
2. `test_two_sources_same_event` -- two compatible classifications → one event with source_count=2
3. `test_different_events_separate` -- "invasion of Poland" and "cyberattack on Estonia" → two separate events
4. `test_compatible_types_grouped` -- "airstrike" and "missile_strike" on same country → same event
5. `test_incompatible_types_separate` -- "cyber_attack" and "naval_blockade" → separate events
6. `test_outside_time_window_separate` -- same event type but 2 hours apart → separate events
7. `test_source_independence` -- same Reuters story on 3 sites → source_count=1, not 3
8. `test_corroboration_threshold_met` -- 2 independent sources → event eligible for phone call
9. `test_corroboration_threshold_not_met` -- 1 source for critical event → SMS only, not phone call
10. `test_event_urgency_max` -- event with scores 7 and 9 → event urgency = 9
11. `test_event_updated_with_new_article` -- new article added to existing event
12. `test_low_urgency_no_event` -- urgency 1-4 → no event created (log only)

## Dependencies Added

```
anthropic>=0.40
```
