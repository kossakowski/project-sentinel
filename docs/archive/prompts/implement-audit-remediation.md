# Sentinel Audit Remediation — Agent Directive

You are implementing fixes to Project Sentinel based on a production audit. You will modify exactly 2 files and 1 YAML config. Follow each step in order. Do not skip steps. Do not add anything beyond what is specified.

<context>
Project Sentinel is a military alert system that monitors news in PL/EN/UK/RU for attacks on Poland and the Baltic states. It has two bugs:

1. **Classifier over-scoring:** Claude Haiku 4.5 classifies articles about Ukraine being attacked as urgency 9 "attack on Poland" — triggering false SMS alerts. Root causes: Google News search queries leaking into classification, defensive jet-scrambles scored as direct attacks, Lviv heritage sites counted as Polish territory, and Ukraine-only events scored at 9-10.

2. **Keyword gaps:** The Polish keyword `"drony"` (plural) fails to match `"dron"` (singular) via substring matching, causing a drone crash in Lithuania (a monitored country) to be completely missed. The word `"poderwał"` (scrambled jets) is absent, causing ~15 articles about Poland scrambling fighter jets to be missed.
</context>

<critical_safety_rules>
- Do NOT modify any file not listed in this directive
- Do NOT change the JSON output schema of the classifier
- Do NOT remove any existing keywords — only add new ones or replace where specified
- Do NOT touch alert logic, state machine, corroboration, or any other system
- After each workstream, run the specified tests. Stop and report if any test fails.
</critical_safety_rules>

---

## EXECUTION ORDER

**Step 1:** Workstream B (classifier prompt) — must be done FIRST
**Step 2:** Workstream A (keyword config) — done AFTER B
**Step 3:** Run full verification

---

## WORKSTREAM B: Classifier Prompt Fixes

**File:** `sentinel/classification/classifier.py`

### B-1: Add 4 new rules to SYSTEM_PROMPT

Find this exact text in the `SYSTEM_PROMPT` constant:

```
    "against a target country IS an attack\n"
    "\n"
    "Respond ONLY with valid JSON. No markdown, no explanation, no preamble."
```

Replace it with:

```
    "against a target country IS an attack\n"
    "- The 'Source:' field is metadata identifying WHERE the article was found, NOT what it says. "
    "For Google News sources (e.g. 'GoogleNews:drone incursion Poland'), the source name contains "
    "the search query -- this is NOT article content. Classify ONLY based on 'Title:' and 'Summary:'. "
    "Do NOT infer that a country is affected because it appears in the source name.\n"
    "- A country scrambling jets or activating air defense as a PRECAUTION in response to attacks on a "
    "NEIGHBORING country is urgency 5-6, NOT 7-10. Urgency 7+ requires evidence that the country's own "
    "territory or airspace was directly attacked or breached.\n"
    "- An attack on assets associated with country X but physically located in country Y is an attack on "
    "Y, NOT X. Score affected_countries based on the PHYSICAL LOCATION of the attack.\n"
    "- If the headline and summary do NOT explicitly state which country was attacked, do NOT assume "
    "it was a monitored country. Assign urgency 2-3 and confidence below 0.5.\n"
    "\n"
    "Respond ONLY with valid JSON. No markdown, no explanation, no preamble."
```

### B-2: Add urgency cap and affected_countries rule to USER_PROMPT_TEMPLATE

Find this exact text at the END of the `USER_PROMPT_TEMPLATE` constant:

```
    "9-10: Active military attack or invasion (troops crossing border, missiles striking targets, "
    "declaration of war, Article 5 invoked)"
```

Replace it with:

```
    "9-10: Active military attack or invasion (troops crossing border, missiles striking targets, "
    "declaration of war, Article 5 invoked)\n"
    "\n"
    "CRITICAL RULES:\n"
    "- Urgency 9-10 is EXCLUSIVELY for attacks directly targeting PL, LT, LV, or EE territory. "
    "Attacks on Ukraine or other countries MUST NOT exceed urgency 4, "
    "UNLESS they directly impact monitored country territory.\n"
    "- affected_countries: ONLY list countries EXPLICITLY mentioned in the article as attacked. "
    "Do NOT infer affected countries from the monitoring scope. Use [] if none explicitly mentioned."
```

### B-VERIFY: Run classifier tests

```bash
pytest tests/test_classifier.py -v
```

All tests must pass. If any fail, stop and report the failure.

---

## WORKSTREAM A: Keyword Configuration Updates

**File:** `config/config.example.yaml`

All changes below are to the `monitoring.keywords` section. Apply them in order.

### A-1: Replace `"drony"` with `"dron"` in `pl.high`

Find `- "drony"` in the Polish `high` keyword list. Replace it with `- "dron"`.

### A-2: Add new keywords to `pl.high`

Append these entries to the end of the `pl.high` list:

```yaml
        - "poderwał"
        - "Szahed"
        - "bezzałogowc"
        - "rakiet"
        - "sabotaż"
        - "wojna hybrydowa"
```

### A-3: Add new keywords to `pl.critical`

Append these entries to the end of the `pl.critical` list:

```yaml
        - "alarm lotniczy"
        - "atak na Polskę"
        - "zaatakować Polskę"
```

### A-4: Add new keywords to `en.high`

Append these entries to the end of the `en.high` list:

```yaml
        - "drone crash"
        - "drone crashed"
        - "drone strike"
        - "UAV"
        - "scramble"
        - "scrambled"
        - "scrambles"
        - "sabotage"
        - "GPS jamming"
        - "cyberattack"
        - "cyberattacks"
        - "Baltic states"
```

### A-5: Replace `"дрони"` with `"дрон"` in `uk.high`

Find `- "дрони"` in the Ukrainian `high` keyword list. Replace it with `- "дрон"`.

### A-6: Add new keywords to `uk.high`

Append these entries to the end of the `uk.high` list:

```yaml
        - "безпілотник"
        - "крилат"
        - "пуски ракет"
```

### A-VERIFY: Run keyword filter tests

```bash
pytest tests/test_keyword_filter.py -v
```

All tests must pass. These tests use their own fixture configs, so config.example.yaml changes cannot break them.

---

## FINAL VERIFICATION

Run the full test suite:

```bash
pytest tests/ -v
```

All tests must pass.

Then validate that the new keywords catch previously-missed headlines. Run each of these locally:

```bash
./run.sh --test-headline "Dron spadł na terytorium Litwy"
./run.sh --test-headline "Polska poderwała myśliwce"
./run.sh --test-headline "Szahedy atakują w ciągu dnia"
./run.sh --test-headline "GPS jamming incidents reported by pilots in Lithuania"
./run.sh --test-headline "Ukraine-launched UAV crashes on Lithuanian territory"
```

Each should produce a keyword match and a classification result. Report the urgency scores.

Then validate that real threats still score correctly:

```bash
./run.sh --test-headline "Russian troops cross Polish border in armed invasion"
./run.sh --test-headline "Rosyjskie rakiety uderzyły w terytorium Polski"
```

These must produce urgency 9-10. If they score below 8, the classifier prompt is over-corrected — stop and report.

---

## AFTER IMPLEMENTATION

Commit the changes with this message:

```
Implement audit remediation: classifier prompt fixes + keyword updates

Classifier (B1-B6): prevent query contamination, defensive-activation
inflation, Lviv/heritage confusion, Ukraine urgency inflation,
clickbait misclassification, hallucinated country scope.

Keywords (A1-A21): fix dron/drony declension gap, add poderwał,
alarm lotniczy, Szahed, UAV, drone crash, scramble, sabotage,
GPS jamming, cyberattack, Baltic states, and UK/PL synonyms.
```

Do NOT deploy to production. Report results and stop.
