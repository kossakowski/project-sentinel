# Testing Strategy

## Overview

Every phase must pass its tests before the next phase begins. Tests are organized by type:
- **Unit tests** -- test individual functions with mocked dependencies
- **Integration tests** -- test against real APIs (marked `@pytest.mark.integration`)
- **End-to-end tests** -- full pipeline with fixtures or live data

## Running Tests

```bash
# All unit tests
pytest tests/ -v

# Skip integration tests (no API calls)
pytest tests/ -v -m "not integration"

# Only integration tests
pytest tests/ -v -m integration

# Specific phase
pytest tests/test_config.py tests/test_database.py tests/test_models.py -v  # Phase 1
pytest tests/test_fetchers/ -v                                                # Phase 2
pytest tests/test_processing/ -v                                              # Phase 3
pytest tests/test_classification/ -v                                          # Phase 4
pytest tests/test_alerts/ -v                                                  # Phase 5
pytest tests/test_integration.py tests/test_scheduler.py -v                   # Phase 6

# With coverage
pytest tests/ -v --cov=sentinel --cov-report=term-missing
```

## Test Modes

### 1. Dry Run Mode (`--dry-run`)

Runs the full pipeline but suppresses all Twilio calls. Classification still runs (to test accuracy), events are created in the database, but no phone calls, SMS, or WhatsApp messages are sent.

```bash
# Run one cycle in dry-run mode
python sentinel.py --dry-run --once

# Run continuously in dry-run mode
python sentinel.py --dry-run
```

**What to check:**
- Log output shows articles being fetched, deduped, filtered, classified
- Events are created with correct urgency scores
- Log shows `[DRY RUN] would_trigger=phone_call` for critical events
- No Twilio charges incurred

### 2. Test Headline Mode (`--test-headline`)

Feed a single headline through the classifier to see how it scores. Does NOT fetch from any source, does NOT store in database.

```bash
# Test a critical headline
python sentinel.py --test-headline "Russia launches full-scale invasion of Poland"

# Test a benign headline
python sentinel.py --test-headline "NATO conducts routine military exercises in Baltic region"

# Test a Polish headline
python sentinel.py --test-headline "Rosja zaatakowała Polskę rakietami balistycznymi"

# Test an ambiguous headline
python sentinel.py --test-headline "Large military convoy spotted near Polish border"
```

**Expected output format:**
```
═══════════════════════════════════════════════════════════
PROJECT SENTINEL TEST CLASSIFICATION
═══════════════════════════════════════════════════════════
Headline:    Russia launches full-scale invasion of Poland
───────────────────────────────────────────────────────────
Military event:     YES
Event type:         invasion
Urgency score:      10/10
Affected countries: ['PL']
Aggressor:          RU
New event:          YES
Confidence:         0.95
Summary (PL):       Rosja rozpoczęła pełnoskalową inwazję na
                    Polskę. Natychmiastowe zagrożenie bezpieczeństwa.
───────────────────────────────────────────────────────────
Would trigger:      PHONE CALL (if corroborated by 2+ sources)
Tokens used:        input=287, output=94
Estimated cost:     $0.0008
═══════════════════════════════════════════════════════════
```

### 3. Test File Mode (`--test-file`)

Classify multiple headlines from a YAML file and optionally compare against expected scores.

```bash
python sentinel.py --test-file tests/fixtures/test_headlines.yaml
```

### 4. Test Headlines Fixture Format

`tests/fixtures/test_headlines.yaml`:

```yaml
# Test headlines with expected classification results.
# Used for regression testing and classifier accuracy validation.

headlines:
  # === CRITICAL (expected urgency 9-10) ===
  - text: "Russia launches full-scale invasion of Poland"
    language: en
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10
      event_type: invasion
      affected_countries: ["PL"]
      aggressor: RU

  - text: "Rosja zaatakowała Polskę. Wojska przekroczyły granicę"
    language: pl
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10
      event_type: invasion

  - text: "Ракетний удар по Варшаві. Польща оголосила стан війни"
    language: uk
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10

  - text: "NATO invokes Article 5 after Russian attack on Lithuania"
    language: en
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10
      event_type: invasion
      affected_countries: ["LT"]

  - text: "Belarus forces cross Lithuanian border in coordinated attack"
    language: en
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10
      affected_countries: ["LT"]
      aggressor: BY

  - text: "Масована ракетна атака на Польщу та країни Балтії"
    language: uk
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10

  # === HIGH (expected urgency 7-8) ===
  - text: "Multiple Russian drones violate Polish airspace in overnight attack on Ukraine"
    language: en
    expected:
      is_military_event: true
      urgency_min: 6
      urgency_max: 8
      event_type: airspace_violation

  - text: "Naruszenie przestrzeni powietrznej RP przez rosyjskie drony"
    language: pl
    expected:
      is_military_event: true
      urgency_min: 6
      urgency_max: 8

  - text: "Russia mobilizes additional 300,000 troops near Baltic border"
    language: en
    expected:
      is_military_event: true
      urgency_min: 7
      urgency_max: 8

  - text: "Shots fired at Polish-Belarusian border during migrant crisis"
    language: en
    expected:
      is_military_event: true
      urgency_min: 6
      urgency_max: 8

  - text: "Провокация на границе с Польшей. Белорусские силы открыли огонь"
    language: ru
    expected:
      is_military_event: true
      urgency_min: 7
      urgency_max: 9

  # === MEDIUM (expected urgency 5-6) ===
  - text: "Large Russian military convoy spotted 50km from Estonian border"
    language: en
    expected:
      is_military_event: true
      urgency_min: 4
      urgency_max: 6

  - text: "Rosja zamknęła przestrzeń powietrzną nad Kaliningradem"
    language: pl
    expected:
      is_military_event: true
      urgency_min: 4
      urgency_max: 6

  - text: "Cyberattack takes down Polish government websites"
    language: en
    expected:
      is_military_event: true
      urgency_min: 5
      urgency_max: 7
      event_type: cyber_attack

  # === LOW / NOT MILITARY (expected urgency 1-4) ===
  - text: "NATO conducts routine military exercises in Poland"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 3

  - text: "Poland commemorates anniversary of WWII invasion"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 2

  - text: "Ćwiczenia wojskowe NATO w Polsce przebiegają zgodnie z planem"
    language: pl
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 2

  - text: "Analysis: Could Russia realistically invade the Baltics?"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 3

  - text: "New military museum opens in Warsaw"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 1

  - text: "Poland signs $2 billion defense contract with South Korea"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 2

  - text: "Film o inwazji na Polskę bije rekordy oglądalności"
    language: pl
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 1

  - text: "Weather forecast: rain expected in Warsaw this weekend"
    language: en
    expected:
      is_military_event: false
      urgency_min: 1
      urgency_max: 1

  # === EDGE CASES ===
  - text: "Russia warns of 'serious consequences' if Poland continues arming Ukraine"
    language: en
    expected:
      is_military_event: false
      urgency_min: 2
      urgency_max: 4

  - text: "Специальная военная операция против Польши"
    language: ru
    expected:
      is_military_event: true
      urgency_min: 9
      urgency_max: 10

  - text: "BREAKING: Explosions reported in Vilnius, Lithuania"
    language: en
    expected:
      is_military_event: true
      urgency_min: 6
      urgency_max: 9
      affected_countries: ["LT"]
```

### 5. Test File Output Format

```
═══════════════════════════════════════════════════════════════════════════
PROJECT SENTINEL TEST FILE: tests/fixtures/test_headlines.yaml (25 headlines)
═══════════════════════════════════════════════════════════════════════════

# | Headline (first 60 chars)                          | Score | Expected | PASS?
──┼────────────────────────────────────────────────────┼───────┼──────────┼──────
1 │ Russia launches full-scale invasion of Poland       │ 10    │ 9-10     │ ✓
2 │ Rosja zaatakowała Polskę. Wojska przekroczyły g... │ 10    │ 9-10     │ ✓
3 │ NATO conducts routine military exercises in Poland  │ 2     │ 1-3      │ ✓
4 │ Shots fired at Polish-Belarusian border during...   │ 7     │ 6-8      │ ✓
5 │ New military museum opens in Warsaw                 │ 1     │ 1-1      │ ✓
...
──┼────────────────────────────────────────────────────┼───────┼──────────┼──────
   PASS: 23/25 (92%)  FAIL: 2/25
   Total cost: $0.019 (input: 7,150 tokens, output: 2,350 tokens)
═══════════════════════════════════════════════════════════════════════════
```

A test run is considered passing if **90%+ of headlines fall within their expected urgency range**. LLM classification is probabilistic, so occasional off-by-one deviations are acceptable.

## Testing During Development

### Testing with Real Current Events

To test that the system picks up real news, find a current headline you know exists:

```bash
# 1. Run a single fetch cycle and see what comes back
python sentinel.py --once --dry-run --log-level DEBUG

# 2. Check the database for fetched articles
sqlite3 data/sentinel.db "SELECT source_name, title, urgency_score FROM articles a LEFT JOIN classifications c ON a.id = c.article_id ORDER BY a.fetched_at DESC LIMIT 20;"
```

### Testing Twilio Integration

Before going live, verify Twilio works:

```bash
# Use the existing Flask app to test a call
curl -X POST http://localhost:5000/api/call \
  -H "Content-Type: application/json" \
  -d '{"to": "+48XXXXXXXXX", "message": "Test alertu Project Sentinel. To jest test.", "language": "pl-PL"}'
```

### Testing the Full Alert Flow

1. Set `testing.dry_run: false` in config
2. Modify `test_headlines.yaml` to have a single critical headline
3. Run: `python sentinel.py --test-headline "Russia invades Poland"` -- verify classification is correct
4. Temporarily lower `corroboration_required` to 1
5. Run: `python sentinel.py --once` -- verify phone call received
6. Restore `corroboration_required` to 2

## pytest Configuration

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests that require network/API access",
]
testpaths = ["tests"]
asyncio_mode = "auto"
```

## Dependencies for Testing

```
pytest>=8.0
pytest-asyncio>=0.23
pytest-mock>=3.12
pytest-cov>=5.0
```
