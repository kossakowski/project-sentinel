# Corroboration Removal — Agent Directive

You are making a config-only change to Project Sentinel: reducing the corroboration threshold for phone call alerts from 2 independent sources to 1. This means a single source reporting a critical threat is enough to trigger a phone call. Follow each step in order.

<context>
Project Sentinel monitors news in PL/EN/UA/RU for military attacks on Poland and the Baltic states. When an article scores urgency 9+, the system decides whether to alert via phone call or SMS.

Two independent checks gate phone calls on corroboration:

1. **Corroborator** (`sentinel/classification/corroborator.py` ~line 290): reads `config.classification.corroboration_required` — if `source_count >= corroboration_required` AND urgency >= 9, returns `"phone_call"`, otherwise falls through to SMS.

2. **State machine** (`sentinel/alerts/state_machine.py` ~line 229): reads `alerts.urgency_levels.critical.corroboration_required` — if `source_count >= level.corroboration_required`, returns `"phone_call"`, otherwise returns `"sms"`.

Both must be changed. Changing only one leaves the other still blocking single-source phone calls.
</context>

<critical_safety_rules>
- Do NOT modify any Python files — this is config-only
- Do NOT SSH to or modify files on the production server
- Do NOT change any config values other than `corroboration_required` in the locations specified below
- Do NOT bundle any other changes into this commit
- After making changes, run the specified tests. Stop and report if any test fails.
</critical_safety_rules>

---

## EXECUTION

### Step 1: Verify Workstream B is in the codebase

Read `sentinel/classification/classifier.py` and confirm the SYSTEM_PROMPT contains urgency scoring rules that prevent over-scoring Ukraine-only events (these were added in commit 7651e3f). If the rules are not present, stop and report — do not proceed.

### Step 2: Change `config/config.yaml`

Make exactly two edits in this file:

**Edit A** — under the `classification:` section (~line 391):
```yaml
# BEFORE
corroboration_required: 2

# AFTER
corroboration_required: 1
```

**Edit B** — under `alerts.urgency_levels.critical:` (~line 400):
```yaml
# BEFORE
corroboration_required: 2

# AFTER
corroboration_required: 1
```

Do NOT touch `corroboration_required` under `high`, `medium`, or `low` tiers — they are already set to 1.

### Step 3: Change `config/config.example.yaml`

Make the same two edits in the repo template:

**Edit A** — under the `classification:` section (~line 463):
```yaml
corroboration_required: 2  →  corroboration_required: 1
```

**Edit B** — under `alerts.urgency_levels.critical:` (~line 477):
```yaml
corroboration_required: 2  →  corroboration_required: 1
```

### Step 4: Verify state machine compatibility

Read `sentinel/alerts/state_machine.py` around line 226-232 and confirm the logic is:
```python
if source_count >= level.corroboration_required:
    return "phone_call"
```
With `corroboration_required: 1`, any event (which always has at least 1 source) passes this check. Confirm this is the case — no code change needed.

Read `sentinel/classification/corroborator.py` around line 290-293 and confirm the same pattern:
```python
if urgency >= 9 and source_count >= corroboration_required:
    return "phone_call"
```
Same logic — `>= 1` is always true. Confirm no code change needed.

### Step 5: Run tests

```bash
.venv/bin/pytest tests/ -v
```

All tests should pass. The test fixtures in `tests/conftest.py` and `tests/test_telegram.py` hardcode `corroboration_required: 2` in their own fixture data — this is expected and correct. Those tests exercise corroboration logic with their own values and are not affected by config file changes.

If any test fails, stop and report the failure. Do not proceed to commit.

### Step 6: Commit

Commit the two changed config files with this message:

```
Reduce corroboration threshold from 2 to 1 for critical phone call alerts

Single source is now sufficient to trigger a phone call when urgency >= 9.
Both classification.corroboration_required and
alerts.urgency_levels.critical.corroboration_required updated.

Depends on classifier prompt fixes (7651e3f) being deployed.
```

### Step 7: Report completion

Tell the user:
- The config changes are committed locally
- Deployment to production is a separate step (use `/deploy`)
