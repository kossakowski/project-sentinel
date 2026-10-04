# Documentation-truth audit — findings register (2026-10-03)

Source: `FINDINGS.json` (378 raw findings from 26 auditors, 0 failed). After near-duplicate merge: **290 findings** — 24 blocker, 150 major, 116 minor. IDs are stable in file order. Each entry lists the raw `FINDINGS.json` index (0-based) of its primary record and of any merged duplicates.

## Summary

| docFile | blocker | major | minor | total |
|---|---:|---:|---:|---:|
| `CLAUDE.md` | 2 | 5 | 5 | 12 |
| `.claude/rules/corroboration.md` | 2 | 2 | 2 | 6 |
| `dashboard/CLAUDE.md` | 0 | 0 | 3 | 3 |
| `mobile/AGENTS.md` | 0 | 1 | 0 | 1 |
| `docs/how-to/server-runbook.md` | 2 | 11 | 6 | 19 |
| `docs/how-to/security/vps-hardening.md` | 2 | 7 | 9 | 18 |
| `.claude/skills/deploy/SKILL.md` | 0 | 4 | 5 | 9 |
| `.claude/skills/sentinel-audit/SKILL.md` | 0 | 6 | 3 | 9 |
| `.claude/skills/dashboard/SKILL.md` | 0 | 2 | 1 | 3 |
| `README.md` | 0 | 1 | 0 | 1 |
| `docs/README.md` | 0 | 4 | 2 | 6 |
| `TODO.md` | 1 | 18 | 17 | 36 |
| `SPEC.md` | 0 | 3 | 3 | 6 |
| `mobile/PUSH_APP_SPEC.md` | 0 | 0 | 1 | 1 |
| `mobile/INBOX_APP_SPEC.md` | 0 | 0 | 1 | 1 |
| `docs/tutorials/getting-started.md` | 1 | 3 | 2 | 6 |
| `docs/how-to/api-setup.md` | 1 | 5 | 1 | 7 |
| `docs/how-to/testing.md` | 0 | 5 | 6 | 11 |
| `docs/how-to/mobile-push-setup.md` | 1 | 4 | 2 | 7 |
| `docs/how-to/mobile-inbox-verification.md` | 0 | 1 | 2 | 3 |
| `docs/how-to/model-comparison.md` | 1 | 3 | 1 | 5 |
| `docs/explanation/architecture.md` | 3 | 19 | 10 | 32 |
| `docs/explanation/pipeline.md` | 3 | 7 | 6 | 16 |
| `docs/explanation/mobile-app.md` | 2 | 5 | 2 | 9 |
| `docs/reference/config-reference.md` | 2 | 13 | 10 | 25 |
| `docs/reference/cli.md` | 0 | 6 | 3 | 9 |
| `docs/reference/sources.md` | 0 | 1 | 2 | 3 |
| `docs/reference/luna-deployment-20260920.md` | 0 | 2 | 0 | 2 |
| `docs/ideas/HANDOFF-fix-vague-inputs.md` | 1 | 0 | 1 | 2 |
| `docs/ideas/classifier-calibration-roadmap.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/incident-memory-plan.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/luna-direct-api-migration-plan.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/luna-direct-api-validation-20260920.md` | 0 | 0 | 1 | 1 |
| `docs/ideas/model-comparison-labels.md` | 0 | 0 | 1 | 1 |
| `docs/ideas/model-comparison-plan.md` | 0 | 0 | 1 | 1 |
| `docs/ideas/model-comparison-v2-holdout-notes.md` | 0 | 0 | 1 | 1 |
| `docs/ideas/model-comparison-v2-plan.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/model-comparison-v2-run-record.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/model-runtime-comparison-20260920.md` | 0 | 1 | 0 | 1 |
| `docs/ideas/polish-summary-guard.md` | 0 | 0 | 1 | 1 |
| `docs/archive/HANDOFF_audit-findings-2026-05-23.md` | 0 | 0 | 2 | 2 |
| `docs/archive/README.md` | 0 | 0 | 1 | 1 |
| `docs/archive/prompts/corroboration-removal.md` | 0 | 0 | 1 | 1 |
| `docs/archive/prompts/implement-audit-remediation.md` | 0 | 1 | 0 | 1 |
| `docs/archive/prompts/phase-1-orchestrator.md` | 0 | 1 | 0 | 1 |
| `docs/archive/prompts/sentinel-audit.md` | 0 | 1 | 0 | 1 |
| `DECISIONS.md` | 0 | 1 | 1 | 2 |
| `MOBILE_APP_START_HERE.md` | 0 | 1 | 0 | 1 |
| `review_report_pending.md` | 0 | 1 | 0 | 1 |
| **Total** | **24** | **150** | **116** | **290** |

## Coverage gaps

- Failed auditors: none. All 26 auditors returned results.
- Standards file: no finding targets a standards document, so that group is empty. The separate `STANDARDS-REPORT.md` in this folder covers documentation standards.
- Merge: 88 raw findings were folded into 66 primary entries because two or more auditors reported the same discrepancy. The primary keeps the strongest evidence (live server or DB evidence beats repo-only evidence); duplicate evidence is listed under "Also reported".
- UNVERIFIABLE or partly unverified items (rely on owner memory, run context, or could not be re-checked in this run): F-049, F-113, F-143, F-160, F-222, F-224, F-240.
- Known state, not a defect: the Twilio account is deliberately unfunded since 2026-09-21 (HTTP 401 "status 4 is not active"); SMS for tiers 5-8 is off by owner decision. Findings about this ask for docs to record the state, not to fix it.

## `CLAUDE.md`

### F-001 [BLOCKER]

- **Claim:** Critical rules, line 21: "**Corroboration required** before a phone call (independent source)."
- **Actual:** Live behavior: one source triggers a phone call. Both gates are set to 1 in the live config: the top-level `classification.corroboration_required` and `alerts.urgency_levels.critical.corroboration_required`. No independent second source is needed today. Only the Pydantic default for the top-level key is 2.
- **Evidence:** config/config.yaml:561 `corroboration_required: 1` (classification); config/config.yaml:585 `corroboration_required: 1` (critical tier); sentinel/classification/corroborator.py:440 `if urgency >= 9 and source_count >= corroboration_required`; sentinel/alerts/state_machine.py:503 `if source_count >= level.corroboration_required: return "phone_call"`; sentinel/classification/corroborator.py:339 a new event starts with source_count=1
- **Suggested fix:** Reword the rule to state that one source triggers a phone call today, because the live critical tier and the classification key are both set to 1 (see corroboration.md). Keep 'do not restate numbers' as a pointer. Add or extend a TODO.md item (TODO.md:17 already touches this) asking the owner whether the call tier should require 2 independent sources. Do not change the config.
- **Source:** FINDINGS.json #1 (merged with #286)
- **Also reported (duplicate evidence):**
  - #286 (blocker): config/config.yaml:561 `corroboration_required: 1` (classification), :585 critical `corroboration_required: 1`; sentinel/alerts/state_machine.py:500-505; sentinel/classification/corroborator.py:437-440

### F-002 [BLOCKER]

- **Claim:** L25: "Classification model: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) — cost-efficient."
- **Actual:** Live classifier is OpenAI gpt-5.6-luna through sentinel/classification/openai_provider.py, using OPENAI_API_KEY. Anthropic Haiku is only the code default (sentinel/config.py:232 provider='anthropic', :266 model='claude-haiku-4-5-20251001') and serves as the explicit legacy rollback. Paid classification is capped by a persistent budget ledger (classification.budget.monthly_usd: 30 live). When the cap is hit, the provider raises BudgetExceeded and articles stay pending.
- **Evidence:** config/config.yaml:472 `provider: openai`, :558 `model: gpt-5.6-luna`, :483-485 budget ledger_path + monthly_usd 30; sentinel/classification/classifier.py:164-165 (OpenAIProvider when provider=='openai', else anthropic.AsyncAnthropic); sentinel/classification/openai_provider.py:123 OPENAI_API_KEY, :65-66 BudgetExceeded 'classification paused; articles remain pending'
- **Suggested fix:** Replace L25 with: "Classification: OpenAI `gpt-5.6-luna` (`classification.provider: openai`, `sentinel/classification/openai_provider.py`, key `OPENAI_API_KEY`). Anthropic Haiku 4.5 is legacy, for explicit rollback only (`provider: anthropic`; it is also the Pydantic default in `sentinel/config.py`). Paid calls are capped by `classification.budget` (ledger + `monthly_usd`); when the cap is exhausted, classification pauses and articles stay pending."
- **Source:** FINDINGS.json #285 (merged with #0)
- **Also reported (duplicate evidence):**
  - #0 (blocker): config/config.yaml:472 `provider: openai`; config/config.yaml:558 `model: gpt-5.6-luna`; sentinel/config.py:232 `provider ... = "anthropic"` and :266 `model: str = "claude-haiku-4-5-20251001"` (code defaults only); sentinel/classification/openai_provider.py:123 reads OPENAI_API_KEY

### F-003 [MAJOR]

- **Claim:** Lines 3-7: alerts go out "via Twilio **phone call + SMS** plus an optional Expo **push**". Each SMS tier has a channel with default `both`. The file does not describe the live routing or the Twilio account state.
- **Actual:** Live tiers 5-8 have `channel: push`, so they are push-only and send no Twilio SMS. Twilio SMS is used only around the 9-10 call (confirmation code SMS, fallback, update SMS). Push is enabled and is the primary channel for 5-8, not optional. The owner leaves the Twilio account unfunded on purpose. Since 2026-09-21 every Twilio call and SMS fails with HTTP 401 'account ... with status 4 is not active'. This is a known state, and calls return when the account is recharged. Neither CLAUDE.md nor the runbook mentions it, so an agent seeing 401s would treat them as an outage.
- **Evidence:** config/config.yaml:590-603 high/medium `channel: push` with comment 'tiers 5-8 ... deliver via app push only — no Twilio SMS'; config/config.yaml:650-651 `push: enabled: true`; sentinel/alerts/state_machine.py:434-435 send_push/send_sms routing; grep for '401|status 4|unfunded' in docs/how-to/server-runbook.md returns nothing
- **Suggested fix:** Add one sentence to the intro: "Live routing: tiers 5–8 are push-only (`channel: push`, SMS off by owner decision); 9–10 = phone call + confirmation SMS + additive push. The Twilio account is deliberately unfunded, so since 2026-09-21 calls/SMS fail with HTTP 401 'status 4 is not active' — a known state, not an outage; see the runbook troubleshooting section." Add the matching runbook troubleshooting entry.
- **Source:** FINDINGS.json #2 (merged with #287)
- **Also reported (duplicate evidence):**
  - #287 (major): config/config.yaml:597 `channel: push` (high), :603 `channel: push` (medium), :650-655 `push: enabled: true` + tokens ${EXPO_PUSH_TOKEN}; sentinel/config.py:105 `channel: str = "both"` (default only); sentinel/alerts/state_machine.py:435-459

### F-004 [MAJOR]

- **Claim:** Critical rule line 17: "**Run and test locally by default.**" Quick reference lines 28-31 give `./run.sh`, `--once`, `--dry-run`, `--health` and `--diagnostic` with no `--config` argument.
- **Actual:** The tracked config/config.yaml, which run.sh uses by default, is the production file. It holds absolute server paths: database `/var/lib/sentinel/sentinel.db`, ledger `/var/lib/sentinel/model-usage.db`, log `/var/log/sentinel/sentinel.log`. Database() calls os.makedirs on the parent folder. A non-root local user cannot write to /var/lib or /var/log, so these commands fail locally or look in the wrong place (for example `--health` reads /var/lib/sentinel/health.json) unless `--config` points to a local copy with local paths.
- **Evidence:** config/config.yaml:484, :662, :667; commit 02c2fea (2026-04-04) 'Fix config paths to use absolute server paths'; sentinel/database.py:18-21 `os.makedirs(parent, exist_ok=True)`; sentinel.py:42 default `config/config.yaml`; local check: os.access('/var/lib', W_OK) == False and /var/lib/sentinel does not exist
- **Suggested fix:** Add a quick-reference line: "config/config.yaml is the live production config (server absolute paths under /var/lib/sentinel and /var/log/sentinel); for local runs pass `--config <local copy>` with data/ paths (see getting-started)."
- **Source:** FINDINGS.json #3

### F-005 [MAJOR]

- **Claim:** Critical rules, line 20: "**Don't spam.** One phone call per event, then SMS for updates."
- **Actual:** Acknowledgement works only through an SMS reply with a 6-digit code. Until that reply arrives, an event is called again whenever it is re-dispatched after `retry_interval_minutes`, and the event moves to retry_pending. Each round places `max_call_retries` calls. With incident memory (live), updates for an acknowledged event go out only when the event's notification_revision increments, which happens on an escalation decision. Each such update sends an update SMS and an update push. Same-incident duplicates and updates send nothing.
- **Evidence:** sentinel/alerts/state_machine.py:579-580 (confirmation SMS is 'the ONLY confirmation mechanism'), :562-571 (retry interval), :637-645 (retry_pending), :403-414 (acknowledged path notifies only on _has_new_delivered_revision); sentinel/classification/corroborator.py:379-381 (revision += 1 only on escalation); config/config.yaml:647-648 max_call_retries: 1, retry_interval_minutes: 5
- **Suggested fix:** Reword: "Don't spam. One call round per event (re-called only until acknowledged via the SMS confirmation code); after acknowledgement, only a new notification revision (an incident-memory escalation) sends an update SMS + push — duplicates/plain updates are silent."
- **Source:** FINDINGS.json #4 (merged with #289)
- **Also reported (duplicate evidence):**
  - #289 (major): sentinel/alerts/state_machine.py:550-557 docstring, :563-571 retry interval, :576-580 confirmation SMS, :584 loop over max_call_retries, :403-414 acknowledged-update path; config/config.yaml:576-582, :640-647 max_call_retries: 1

### F-006 [MAJOR]

- **Claim:** L17: "Use local env vars for Twilio/Anthropic/Telegram credentials."
- **Actual:** The live classifier needs OPENAI_API_KEY. ANTHROPIC_API_KEY is needed only for the legacy rollback (provider: anthropic). Push uses the optional EXPO_ACCESS_TOKEN and EXPO_PUSH_TOKEN (substituted into alerts.push.tokens).
- **Evidence:** sentinel/classification/openai_provider.py:123-126; .env.example ('Anthropic (only for explicit legacy rollback)'); sentinel/alerts/push_client.py:27; config/config.yaml:655 `${EXPO_PUSH_TOKEN}`
- **Suggested fix:** Change to: "Use local env vars (`.env`, template `.env.example`) for Twilio, OpenAI (`OPENAI_API_KEY`), Telegram and Expo credentials. `ANTHROPIC_API_KEY` is only for the legacy Haiku rollback."
- **Source:** FINDINGS.json #288 (merged with #5)
- **Also reported (duplicate evidence):**
  - #5 (minor): sentinel/classification/openai_provider.py:123-126 (OPENAI_API_KEY required); config/config.yaml env refs: ALERT_PHONE_NUMBER, EXPO_PUSH_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH; sentinel/alerts/push_client.py:27 EXPO_ACCESS_TOKEN

### F-007 [MAJOR]

- **Claim:** L29: "Config: `config/config.yaml` (template `config/config.example.yaml`)"
- **Actual:** Omission. config/config.yaml is tracked, even though .gitignore also lists it. It is the live production config: /deploy step 6c copies it to /etc/sentinel/config.yaml, and step 6a (at HEAD) stops the deploy when the server has its own edits. The repo is public, so secrets must stay as ${VAR} placeholders that resolve from /etc/sentinel/sentinel.env. Code defaults in sentinel/config.py differ materially from live values (provider anthropic vs openai, corroboration_required 2 vs 1, max_call_retries 3 vs 1, channel both vs push, budget 10 vs 30).
- **Evidence:** git ls-files config/ -> config/config.yaml tracked; .gitignore:15 `config/config.yaml`; .claude/skills/deploy/SKILL.md:180-268 (6a drift check, 6c sync); config/config.yaml:649-655 comment 'PUBLIC repo'; sentinel/config.py:118, :195, :232
- **Suggested fix:** Expand L29: "Config: `config/config.yaml` is tracked and IS the live production config. `/deploy` syncs it to `/etc/sentinel/config.yaml` and stops if the server has its own edits. Edit and commit it here; never hand-edit the server copy. The repo is PUBLIC: secrets only as `${VAR}` resolved from `/etc/sentinel/sentinel.env`. Template: `config/config.example.yaml`. Code defaults (`sentinel/config.py`) differ from live values, so always check the YAML."
- **Source:** FINDINGS.json #290

### F-008 [MINOR]

- **Claim:** Quick reference, line 31: "Diagnostic: `./run.sh --diagnostic` (writes `data/diagnostic.html`)"
- **Actual:** The report goes to dirname(database.path)/diagnostic.html. With the tracked config that path is /var/lib/sentinel/diagnostic.html, not data/diagnostic.html. The diagnostic run also runs a full cycle with live, paid classifier calls; only alert dispatch is skipped.
- **Evidence:** sentinel.py:139-143 `os.path.join(os.path.dirname(config.database.path) or "data", "diagnostic.html")`; config/config.yaml:662 database path /var/lib/sentinel/sentinel.db; sentinel/scheduler.py:287-298 (diagnostic skips dispatch only)
- **Suggested fix:** Write "(writes diagnostic.html next to the configured database; data/ with a local config; makes live classifier calls, no alerts)".
- **Source:** FINDINGS.json #6

### F-009 [MINOR]

- **Claim:** Critical rules, line 24: "**Nothing is hardcoded.** All keywords, sources, countries, thresholds, and URLs live in `config/config.yaml`."
- **Actual:** The corroborator hardcodes several values. The alertable urgency cuts are 9, 7 and 5. The minimum event urgency is 5 (`_MIN_EVENT_URGENCY`). The event-type compatibility map (EVENT_COMPATIBILITY) is in code. corroboration.md itself admits the 'hardcoded urgency cuts'.
- **Evidence:** sentinel/classification/corroborator.py:15-28 (EVENT_COMPATIBILITY, _MIN_EVENT_URGENCY = 5), :440-445 (hardcoded 9/7/5); .claude/rules/corroboration.md:38-40
- **Suggested fix:** Keep the rule but state the known exceptions: "(known exceptions: corroborator urgency cuts 9/7/5, _MIN_EVENT_URGENCY, EVENT_COMPATIBILITY — see corroboration.md)".
- **Source:** FINDINGS.json #8 (merged with #292)
- **Also reported (duplicate evidence):**
  - #292 (minor): sentinel/classification/corroborator.py:439-444, :70 (_MIN_EVENT_URGENCY); .claude/rules/corroboration.md:38-39

### F-010 [MINOR]

- **Claim:** L33: "Classifier eval harness: `./run.sh --eval [PATH]` (... scored, CI gate)". L32 and L34 list --test-headline and --test-alert without cost or Twilio-state caveats.
- **Actual:** The repo has no CI (no .github/ or other CI config). --eval only exits 1 unless overall_pass_rate == 1.0. --eval and --test-headline hit the live paid OpenAI API (help text: 'Hits the live API'). --test-alert phone_call and --test-alert sms currently fail with Twilio HTTP 401 (known unfunded-account state); only push works.
- **Evidence:** ls .github -> No such file; sentinel.py:84-85 'Hits the live API', :408 exit code; .pre-commit-config.yaml (ruff only)
- **Suggested fix:** Change 'CI gate' to 'exits non-zero unless every case passes (no CI is configured)'. Add: "`--eval`, `--test-headline`, `--test-file` spend real OpenAI money. `--test-alert` phone_call/sms place real Twilio traffic, which fails with 401 while the account is unfunded."
- **Source:** FINDINGS.json #291 (merged with #7)
- **Also reported (duplicate evidence):**
  - #7 (minor): sentinel.py:83-85 help 'Hits the live API'; sentinel.py:73-76 '--test-alert' 'Fire a real test alert'; sentinel.py:254-256 test modes set dry_run but still classify

### F-011 [MINOR]

- **Claim:** L40-46 Docs list (and docs/README.md index).
- **Actual:** Neither index links docs/how-to/model-comparison.md (living how-to), docs/reference/luna-deployment-20260920.md (the deployment and rollback record the runbook relies on), or docs/ideas/. The runbook is the only path to the rollback record.
- **Evidence:** grep 'model-comparison\|luna-deployment\|ideas/' CLAUDE.md docs/README.md -> no hits; git ls-files docs/how-to/model-comparison.md docs/reference/luna-deployment-20260920.md
- **Suggested fix:** Add to CLAUDE.md Docs and to docs/README.md: "Model comparison (eval-only) → docs/how-to/model-comparison.md · Luna deployment/rollback record → docs/reference/luna-deployment-20260920.md · Design notes/plans → docs/ideas/".
- **Source:** FINDINGS.json #293

### F-012 [MINOR]

- **Claim:** L50: "recreate the venv: `rm -rf .venv && python -m venv .venv && pip install -r requirements.txt`"
- **Actual:** A bare `pip` without activating the venv installs into whatever pip is on PATH, not into .venv. run.sh uses "$VENV/bin/pip".
- **Evidence:** run.sh:19-20 `python3 -m venv "$VENV"; "$VENV/bin/pip" install -r ...`
- **Suggested fix:** Use `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (or simply `rm -rf .venv && ./run.sh --help`, which rebuilds it).
- **Source:** FINDINGS.json #294

## `.claude/rules/corroboration.md`

### F-013 [BLOCKER]

- **Claim:** Lines 16-31: "How an incoming classification is grouped into an `events` row". It lists a sliding window (`corroboration_window_minutes`), an absolute age cap (`corroboration_max_age_minutes`), a summary match (`summary_similarity_metric/threshold`) and a country gate, all as the current grouping logic.
- **Actual:** Incident memory is live: `classification.incident_memory.enabled: true`, shipped in 8864861 (2026-09-20), which is an ancestor of the deployed commit 6429124. In memory mode, process_classifications calls `_find_memory_match` instead of `_find_matching_event`. Grouping then follows the model's validated incident decision: duplicate, update or escalation, with confidence ≥ min_confidence 0.85, or ≥ critical_min_confidence 0.9 for critical articles. The match must also be in the candidate list, pass the country gate, have no explicit weekday or date conflict, and fall within lookback_hours 168. The sliding window, age cap, summary-similarity and event-type compatibility settings are unused in production. Memory mode also classifies articles one by one, in sentinel/scheduler.py.
- **Evidence:** config/config.yaml:540-549 incident_memory enabled: true; sentinel/classification/corroborator.py:82-83 `matching_event = self._find_memory_match(result) if memory_enabled else self._find_matching_event(result)`; corroborator.py:98-144; sentinel/classification/incident_memory.py:122-184 (validate, thresholds, _time_conflict); sentinel/scheduler.py:248-277; git merge-base --is-ancestor 8864861 6429124 = true
- **Suggested fix:** Split the section in two. "Live: incident memory (`classification.incident_memory.*`, sentinel/classification/incident_memory.py + Corroborator._find_memory_match)" should describe the decision/confidence/candidate/country/time-conflict/lookback gates. "Legacy fuzzy path (only when incident_memory.enabled is false)" should keep the current bullets. Add `sentinel/scheduler.py` to the description of per-article sequential classification.
- **Source:** FINDINGS.json #9 (merged with #295)
- **Also reported (duplicate evidence):**
  - #295 (major): config/config.yaml:540-549 incident_memory enabled: true, min_confidence 0.85, critical_min_confidence 0.9; sentinel/classification/corroborator.py:82-83 (memory path replaces fuzzy path), :98-144 _find_memory_match (no acknowledged_at check; escalation only when event.urgency < threshold), :178-183 (ack guard exists only in _find_matching_event); sentinel/alerts/state_machine.py:403-414

### F-014 [BLOCKER]

- **Claim:** Lines 32-35: "**Critical-urgency safety guard** — a phone-call-eligible article is NEVER absorbed into an event that already has `acknowledged_at` set ... it forces a NEW event and a NEW call ... This is a life-safety invariant — do not weaken it without explicit sign-off."
- **Actual:** This guard exists only in the legacy `_find_matching_event`. In the live memory path, `_find_memory_match` has no acknowledged_at check. A critical article that the model marks duplicate or update with confidence ≥ 0.9 is absorbed into the acknowledged event, with no new event and no new call. If the revision does not change, no notification goes out at all. A test enshrines this. The current protection works differently: the model's 'new' decision creates a separate event and call, a critical report into a noncritical event is forced to 'escalation', and an escalation on an acknowledged event sends an update SMS plus push, not a call. The doc still calls the removed guard an invariant.
- **Evidence:** sentinel/classification/corroborator.py:182-183 (guard only in legacy path) vs :98-144 (memory path, no acknowledged_at check), :140-143 (escalation override); tests/test_incident_memory.py:150-171 test_acknowledged_critical_duplicate_stays_on_same_event; sentinel/alerts/state_machine.py:403-414; docs/ideas/incident-memory-plan.md:38,47-49
- **Suggested fix:** Rewrite the bullet. The acknowledged_at guard applies only to the legacy path. In live memory mode, same-incident critical repeats merge into the acknowledged event silently. A model-judged 'new' incident gets its own event and call. An escalation sends an update SMS + push, not a call. Keep the life-safety warning on the current mechanism. Add a TODO.md item asking the owner to confirm sign-off on this change to the former invariant.
- **Source:** FINDINGS.json #10

### F-015 [MAJOR]

- **Claim:** Lines 48-49: "Note `classification.corroboration_required` Pydantic default is `2`, but live `config/config.yaml` sets `1`." The doc does not spell out what that means in practice.
- **Actual:** Both gates are 1 live: the classification key used by _determine_alert_status and `alerts.urgency_levels.critical.corroboration_required` used by _determine_action. A brand-new event has source_count=1. So a single source with urgency ≥ 9 triggers a phone call today, and the source-independence check never gates the first call.
- **Evidence:** config/config.yaml:561 and :585 (both 1); sentinel/classification/corroborator.py:339 (source_count=1 on create), :440; sentinel/alerts/state_machine.py:501-506; TODO.md:12,17 (open question on single-source exposure)
- **Suggested fix:** Add: "Consequence today: one source triggers a phone call (both the classification key and the critical tier's `corroboration_required` are 1); independence only affects later source_count." Point to or extend the TODO.md item that asks the owner whether to require 2. Do not change the config.
- **Source:** FINDINGS.json #11

### F-016 [MAJOR]

- **Claim:** Lines 37-46 describe two alert-level decisions (_determine_alert_status and _determine_action) as the whole notification logic.
- **Actual:** The revision-aware notification layer from 8864861 is missing. Delivery dedup is per channel and per `notification_revision`, through `_channel_delivered` and `_has_new_delivered_revision`. A failed SMS or push stays retryable. For an acknowledged event, process_event sends no new call and notifies (update SMS plus push) only when the revision advanced. Only an escalation increments the revision; source count and timestamp changes do not. In memory mode, _update_event raises urgency only on escalation. It also keeps the lifecycle status (acknowledged, retry_pending, call_placed, expired) instead of recomputing it.
- **Evidence:** sentinel/alerts/state_machine.py:403-414, :438-452, :518-544; sentinel/classification/corroborator.py:375-381, :398-401
- **Suggested fix:** Add a third item, "Revision-aware delivery", that summarises these rules and names the functions (`_channel_delivered`, `_has_new_delivered_revision`, `notification_revision`).
- **Source:** FINDINGS.json #12

### F-017 [MINOR]

- **Claim:** Frontmatter `paths:` lists only `sentinel/classification/**`, `sentinel/alerts/state_machine.py` and `config/config.yaml`.
- **Actual:** The rule also governs code outside those paths. sentinel/scheduler.py orchestrates memory-mode classification and grouping. sentinel/config.py holds the Pydantic defaults the note cites (corroboration_required = 2, IncidentMemoryConfig). config/config.example.yaml mirrors the keys. sentinel/alerts/dispatcher.py dedups and re-reads events before process_event. Editing these files does not load the rule.
- **Evidence:** .claude/rules/corroboration.md:1-6; sentinel/scheduler.py:248-277; sentinel/config.py:172-190, 268; sentinel/alerts/dispatcher.py:26-50
- **Suggested fix:** Add `sentinel/scheduler.py`, `sentinel/config.py`, `config/config.example.yaml` and `sentinel/alerts/dispatcher.py` to `paths:`.
- **Source:** FINDINGS.json #13

### F-018 [MINOR]

- **Claim:** The legacy grouping list (lines 18-35) gives window, age cap, summary match, source independence, country gate and acknowledged guard as the matching criteria.
- **Actual:** The list leaves out two gates that the legacy matcher applies first. Event-type compatibility comes from the hardcoded EVENT_COMPATIBILITY map. The hardcoded `_MIN_EVENT_URGENCY = 5` filter means non-military or urgency < 5 results never create or join events.
- **Evidence:** sentinel/classification/corroborator.py:15-28, :71-79, :160-162
- **Suggested fix:** Add bullets: "Event-type gate — EVENT_COMPATIBILITY (hardcoded) in the legacy path" and "Only military results with urgency ≥ 5 (`_MIN_EVENT_URGENCY`, hardcoded) create/join events."
- **Source:** FINDINGS.json #14

## `dashboard/CLAUDE.md`

### F-019 [MINOR]

- **Claim:** Routes (line 26): '`/articles/:id` (classifier view + event timeline + annotation panel)'. dashboard/classifier_input.py is listed as a module (line 10) without saying what it does.
- **Actual:** The 'classifier view' rebuilds the LEGACY Anthropic user prompt: a 5-line 'Source/Language/Published/Title/Summary' block from Classifier._build_user_prompt. The live Luna path sends a policy-v2 system prompt plus a JSON user message with evaluation_time, article fields and remembered_incidents (incident-memory candidates). So the dashboard shows an input that the live classifier did not receive.
- **Evidence:** dashboard/classifier_input.py:1-30 (docstring: reproduces USER_PROMPT_TEMPLATE / _build_user_prompt); sentinel/classification/classifier.py:178-184 (live OpenAI path uses messages()); sentinel/classification/policy.py:136-152 (JSON payload with remembered_incidents)
- **Suggested fix:** Add a note: 'The classifier view reconstructs the legacy Anthropic prompt block. The live gpt-5.6-luna path uses sentinel/classification/policy.py messages() (system policy v2 + JSON with remembered_incidents), so the view is only approximate for Luna-era rows.'
- **Source:** FINDINGS.json #253

### F-020 [MINOR]

- **Claim:** Event grouping section (line 44): '`GET /api/events/<event_id>` returns `{event, articles[], alert_records[]}`'.
- **Actual:** The response is FLAT: the event fields sit at the top level next to articles[] and alert_records[], with no nested 'event' key.
- **Evidence:** dashboard/api/events.py:22-26 docstring 'The response shape is {id, event_type, urgency_score, affected_countries, aggressor, summary_pl, first_seen_at, last_updated_at, source_count, article_ids, alert_status, acknowledged_at, articles[], alert_records[]}'
- **Suggested fix:** Change to: 'returns the event's fields flat plus `articles[]` and `alert_records[]` (404 on unknown id)'.
- **Source:** FINDINGS.json #256

### F-021 [MINOR]

- **Claim:** Line 9-10: the API package has 'cli.py, config.py, db.py, sync.py, annotations.py, and classifier_input.py modules'.
- **Actual:** The doc omits dashboard/app.py, the Flask app factory create_app(). It registers the /api blueprints, sets up CORS for :5173 and serves frontend/dist at '/'. It also omits the sync blueprint's endpoints, POST /api/sync and GET /api/sync/status.
- **Evidence:** dashboard/app.py:19-78 (CORS, register_blueprint url_prefix='/api'), :132-159 (serves dist); dashboard/api/sync.py:57 '/sync' POST, :92 '/sync/status' GET
- **Suggested fix:** Add app.py (create_app factory: blueprints, CORS, dist serving) to the module list, and list POST /api/sync and GET /api/sync/status.
- **Source:** FINDINGS.json #257

## `mobile/AGENTS.md`

### F-022 [MAJOR]

- **Claim:** The whole file reads: '# Expo HAS CHANGED / Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.' mobile/CLAUDE.md is only `@AGENTS.md`, so this is the complete agent guidance for the mobile/ subtree.
- **Actual:** The SDK-54 pin is accurate (package.json `expo ~54.0.33`). But an agent editing mobile/ is not told facts it needs to avoid breaking a live, life-safety-adjacent app: (1) the app is LIVE on the owner's iPhone as a standalone EAS `preview` build, and changes reach it only via `eas build --profile preview --platform ios` plus a reinstall; (2) the gates are `npm test` (jest-expo) and `npm run typecheck`; (3) native modules must be added with `npx expo install` (SDK-aligned versions), and `.npmrc` has `legacy-peer-deps=true`; (4) the push `data` contract in src/messages/types.ts is coupled to the server builder `_build_push_data` in sentinel/alerts/state_machine.py, so one side must not change without the other; (5) the device token is set on the server as EXPO_PUSH_TOKEN in /etc/sentinel/sentinel.env (a server write that needs the owner's permission), never in tracked config.
- **Evidence:** mobile/AGENTS.md:1-3; mobile/CLAUDE.md:1; mobile/package.json scripts; mobile/.npmrc; mobile/src/messages/types.ts:185-205 (PushPayload 'Appendix A, Phase 1 contract'); sentinel/alerts/state_machine.py:301-330; TODO.md:97; config/config.yaml:652-656.
- **Suggested fix:** Keep the Expo v54 docs line and add 5 short bullets to mobile/AGENTS.md (mobile/CLAUDE.md stays `@AGENTS.md`): live status and the preview-build rebuild path; the test and typecheck commands; `npx expo install` for native deps plus the .npmrc note; the types.ts ↔ `_build_push_data` payload coupling; token handling via EXPO_PUSH_TOKEN in sentinel.env (owner permission, never a literal in config). Link docs/explanation/mobile-app.md for the rest.
- **Source:** FINDINGS.json #89

## `docs/how-to/server-runbook.md`

### F-023 [BLOCKER]

- **Claim:** Known Server Hazards #1 (line 264): 'Detached HEAD ... git pull origin master fails ... RESOLVED 2026-05-25–27. Repo back on master. If it recurs: cd /home/deploy/sentinel && git checkout master && git pull origin master'
- **Actual:** Detached HEAD is now the intended production state. The /deploy skill step 6b runs `git checkout $DEPLOY_TAG` and says 'detached HEAD — expected for production'. Production runs tag deploy-20260925-143105 (6429124), not master. Following the documented 'fix' would move production onto undeployed master HEAD without backup, config sync or drift check.
- **Evidence:** .claude/skills/deploy/SKILL.md:252-258 (6b checkout tag, 'detached HEAD — expected for production'); docs/how-to/server-runbook.md:264
- **Suggested fix:** Rewrite row #1 to say: 'Detached HEAD on a deploy-* tag is EXPECTED (set by /deploy step 6b). Do not check out master on the server. Use `git describe --tags` to see the deployed tag.' Keep the 2026-04-12 history only as context.
- **Source:** FINDINGS.json #182 (merged with #326)
- **Also reported (duplicate evidence):**
  - #326 (major): ssh: git rev-parse --abbrev-ref HEAD → 'HEAD'; git log -1 → '(HEAD, tag: deploy-20260925-143105, origin/master)'; .claude/skills/deploy/SKILL.md:252-258

### F-024 [BLOCKER]

- **Claim:** Configuration (line 180): 'The live /etc/sentinel/config.yaml omits the block, so push is disabled; add the block and tokens here to enable it ... With push disabled, a both/push tier still sends SMS only, so the deployed behavior is unchanged until you enable push.'
- **Actual:** Live config has `alerts.push.enabled: true` with `tokens: ['${EXPO_PUSH_TOKEN}']`. Tiers high and medium have `channel: push`, so urgency 5–8 is push-only and SMS is off on purpose. The token must come from the env var, because the config is copied from a PUBLIC repo. Putting a literal token 'here' would leak it, since /deploy 6c overwrites the live file from the tracked config/config.yaml anyway.
- **Evidence:** config/config.yaml:651-657 (push enabled, ${EXPO_PUSH_TOKEN}, comment 'NEVER hardcode it here — this is a PUBLIC repo'); config/config.yaml:590-604 (high/medium channel: push); sentinel/config.py:153-154 (PushConfig.enabled default False; example has enabled: false at config/config.example.yaml:668-669)
- **Suggested fix:** Replace the note with: 'Push is ON in production (alerts.push.enabled: true, token from EXPO_PUSH_TOKEN in sentinel.env). Urgency 5–8 are push-only (channel: push) by owner decision, so no SMS is sent for them. Urgency 9–10 places a call with SMS fallback plus an additive push. Change routing by editing config/config.yaml in the repo and running /deploy. Never put a literal token in the config.' Keep the three-way distinction: code default (push off), example (push off, channel both), live (push on, channel push).
- **Source:** FINDINGS.json #183 (merged with #317, #334, #370)
- **Also reported (duplicate evidence):**
  - #317 (blocker): config/config.yaml:650-656 (push: enabled: true, tokens: - "${EXPO_PUSH_TOKEN}"), config/config.yaml:597 and :603 (channel: push). The orchestrator verified that the server file is byte-identical to config/config.yaml. Server log shows 13 sentinel.alerts.push_client lines in today's sentinel.log.
  - #334 (blocker): config/config.yaml:650-656 and 597/603 (byte-identical to the server: both sha256 156746ac...bdce4). Live query: SELECT alert_type,status,COUNT(*) FROM alert_records WHERE sent_at>=now-14d returned 'push|sent|282'. The EXPO_PUSH_TOKEN key is present in /etc/sentinel/sentinel.env (key names only).
  - #370 (major): config/config.yaml:650-656 (enabled: true, tokens: ['${EXPO_PUSH_TOKEN}']), :597/:603 channel: push. 159x 'sentinel.alerts.push_client: Push sent for event … ticket=…' in sentinel.log*; DB alert_records 'push|sent|159'.

### F-025 [MAJOR]

- **Claim:** Lines 20-23: 'Preserve live settings when deploying: merge reviewed classification fields instead of copying the repository YAML wholesale. The old /deploy skill also excludes the existing secrets file'
- **Actual:** The current /deploy skill is the routine path, not an 'old' one. It copies config/config.yaml to /etc/sentinel/config.yaml wholesale in step 6c. First, step 6a runs a key-by-key drift check that stops the deploy when the server has server-only edits. The tracked config is the source of truth, and the live file is byte-identical to it. The hand-merge describes the one-off Luna rollout of 2026-09-20 only.
- **Evidence:** .claude/skills/deploy/SKILL.md:180-250 (6a drift check), 262-268 (6c wholesale cp + chown/chmod); docs/reference/luna-deployment-20260920.md:52-53 (merge was specific to that rollout)
- **Suggested fix:** Replace with: 'Deploy with /deploy. It backs up the server, checks config drift (6a: stops if the live config has server-only edits), checks out the tag, and copies config/config.yaml to /etc/sentinel/config.yaml (6c). To change live settings, edit config/config.yaml, commit, and run /deploy. The secrets files are never touched.' Note that the 2026-09-20 field merge was a one-off.
- **Source:** FINDINGS.json #185 (merged with #319)
- **Also reported (duplicate evidence):**
  - #319 (major): .claude/skills/deploy/SKILL.md:180-249 (6a config drift check, STOP on unexpected keys), :262-268 (6c 'sudo cp /home/deploy/sentinel/config/config.yaml /etc/sentinel/config.yaml'). The orchestrator verified that /etc/sentinel/config.yaml is byte-identical to config/config.yaml.

### F-026 [MAJOR]

- **Claim:** Deployment (git-based), 'Standard deploy' (lines 118-139): push master, ssh, `git checkout master` / `git pull origin master`, pip install, restart
- **Actual:** The real routine is the /deploy skill. Its steps are: 1 preflight, 2 merge, 3 tag, 4 push master and tag, 5 full server backup, 6a config drift check, 6b checkout of the deploy tag (detached), 6c config sync to /etc/sentinel/config.yaml, 6d pip install, 6e restart, 6f prune of snapshots to the last 10, and 7 verify. The documented manual procedure skips the backup, the tag, the drift check and the config sync. Skipping the sync is exactly what produced Hazard #4. It also leaves the server on master instead of a tag. The runbook never mentions /deploy as the standard path.
- **Evidence:** .claude/skills/deploy/SKILL.md:58-324; memory/owner rule 'deploys from master via /deploy'; docs/how-to/server-runbook.md:118-139
- **Suggested fix:** Make /deploy the standard deploy and list its steps 1–7 (including 6a–6f) in one short table. Keep the manual commands only as an emergency fallback. That fallback must check out the tag (not master), copy config/config.yaml to /etc/sentinel/config.yaml with root:sentinel 640, and take a backup first.
- **Source:** FINDINGS.json #186 (merged with #327)
- **Also reported (duplicate evidence):**
  - #327 (major): .claude/skills/deploy/SKILL.md:95-120 (tag), :155 (backup), :180-268 (6a-6c); server HEAD at tag deploy-20260925-143105; /home/deploy/backups contains 10 deploy-* snapshot dirs

### F-027 [MAJOR]

- **Claim:** Rollback (lines 141-148): 'git fetch --tags; git checkout <last-good-tag> # e.g. v1.0.0; sudo systemctl restart sentinel'
- **Actual:** Deploy tags are named deploy-YYYYMMDD-HHMMSS, and v1.0.0 is an ancient pre-deploy-skill tag. Each deploy also replaces /etc/sentinel/config.yaml (6c), so checking out old code without restoring the matching config can break startup. For example, pre-Luna code cannot handle the openai provider and budget keys. The Luna record defines a specific rollback: restore the backed-up config as root:sentinel 0640, remove only the 20-openai.conf drop-in, daemon-reload, keep the current DB and the usage ledger. The deploy skill's own rollback hint is `git tag -l 'deploy-*'` plus restoring the deploy-<ts> backup.
- **Evidence:** git tag -l (deploy-* tags, v1.0.0); .claude/skills/deploy/SKILL.md:150-155, 349-354; docs/reference/luna-deployment-20260920.md:85-97
- **Suggested fix:** Use `git tag -l 'deploy-*'` as the example. Add 'restore the config.yaml from /home/deploy/backups/deploy-<ts>/ (root:sentinel 640) along with the code'. Add 'never restore the old sentinel.db over the live one'. Link to the Luna record's rollback for the Luna→Anthropic case (drop-in removal + daemon-reload).
- **Source:** FINDINGS.json #193

### F-028 [MAJOR]

- **Claim:** Current deployment (lines 16-18): 'Deployed tag: `deploy-20260920-232235`, code commit `7048a91`.' Header line 4: 'Last updated: 2026-09-20'.
- **Actual:** Production runs tag deploy-20260925-143105 = commit 6429124 ('Point the cost ledger at the production data directory'). HEAD is detached at that tag. The server working tree is clean.
- **Evidence:** ssh: git -C /home/deploy/sentinel log -1 → '6429124  (HEAD, tag: deploy-20260925-143105, origin/master) Point the cost ledger at the production data directory'; git describe --tags --exact-match → deploy-20260925-143105; git status --short → empty
- **Suggested fix:** Change the Current deployment line to: deployed tag `deploy-20260925-143105`, code commit `6429124`. Say that the 2026-09-20 Luna record is the migration record, not the current deployment. Bump 'Last updated'.
- **Source:** FINDINGS.json #318 (merged with #184, #343, #363, #312, #239)
- **Also reported (duplicate evidence):**
  - #184 (major): git tag -l: deploy-20260925-141910, deploy-20260925-143105; git show 6429124 (commit message describes the ~10 min outage); git log -- docs/how-to/server-runbook.md → last commit dbeaaf9
  - #343 (major): Server: git describe --tags gives deploy-20260925-143105, and git rev-parse --short HEAD gives 6429124.
  - #363 (major): Run context (orchestrator-verified 2026-10-03): production tag deploy-20260925-143105 = 6429124. server-runbook.md:16-19.
  - #312 (major): git tag -l 'deploy-*' -> deploy-20260925-143105 latest; .claude/skills/deploy/SKILL.md:262-268 (6c sync), :180-250 (6a); config/config.yaml:650-655
  - #239 (major): docs/how-to/server-runbook.md:17-22, :114-148, :75-76, :268; SKILL.md:180-268, :288-294; `git tag -l 'deploy-*'` (latest deploy-20260925-143105, rev 6429124); no v* tags

### F-029 [MAJOR]

- **Claim:** Prerequisites line 12 and Secrets lines 186 and 192-201: the required variables are TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, ALERT_PHONE_NUMBER, OPENAI_API_KEY, TELEGRAM_API_ID, TELEGRAM_API_HASH; '/etc/sentinel/sentinel.env retains the existing Twilio/Telegram credentials and legacy Anthropic key.'
- **Actual:** /etc/sentinel/sentinel.env holds these key names: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, TWILIO_WHATSAPP_NUMBER, ALERT_PHONE_NUMBER, ANTHROPIC_API_KEY, TELEGRAM_API_ID, TELEGRAM_API_HASH, EXPO_PUSH_TOKEN, EXPO_ACCESS_TOKEN. /etc/sentinel/openai.env holds OPENAI_API_KEY only. EXPO_PUSH_TOKEN is substituted into alerts.push.tokens, and EXPO_ACCESS_TOKEN is read by push_client. Together they carry the only live channel for tiers 5-8, yet the runbook never lists them.
- **Evidence:** ssh: sudo sed 's/=.*//' /etc/sentinel/sentinel.env (key names above); config/config.yaml:652-656; sentinel/alerts/push_client.py:27 os.environ.get("EXPO_ACCESS_TOKEN", "")
- **Suggested fix:** Add EXPO_PUSH_TOKEN (device token, substituted into alerts.push.tokens) and EXPO_ACCESS_TOKEN (Expo Enhanced Push Security) to the required-variable lists in Prerequisites and Secrets. Change the sentinel.env description to 'Twilio, Telegram, Expo push credentials and the legacy Anthropic key (rollback only)'. Optionally note that TWILIO_WHATSAPP_NUMBER is present but unused.
- **Source:** FINDINGS.json #321 (merged with #188, #341)
- **Also reported (duplicate evidence):**
  - #188 (major): config/config.yaml:656-657; sentinel/config.py:350-361 (raises ConfigError on missing var); sentinel/alerts/push_client.py:19-27 (EXPO_ACCESS_TOKEN); sentinel/alerts/twilio_client.py:21-23; sentinel/classification/openai_provider.py:123-126
  - #341 (major): Server key names in /etc/sentinel/sentinel.env (listed above). systemd shows EnvironmentFile=/etc/sentinel/sentinel.env and EnvironmentFile=/etc/sentinel/openai.env. config/config.yaml:656. sentinel/config.py:350-360.

### F-030 [MAJOR]

- **Claim:** Health Check line 238 and cron table line 246: '/home/deploy/check-health.sh runs every 30 min. If health.json is missing or older than 30 min, sends SMS via Twilio.' Known Server Hazards #3 (line 266): 'the legacy venv/ is harmless if still present'. File Layout line 56 lists '.venv/ ... venv/ # Legacy venv — stale, do not use'.
- **Actual:** check-health.sh hardcodes PYTHON="/home/deploy/sentinel/venv/bin/python", the legacy venv. That directory no longer exists, so the guard [ -x "$PYTHON" ] fails and no SMS is ever attempted. The script only echoes the message to syslog (tag sentinel-health) and exits 1. Even with the path fixed, the alert would go by Twilio SMS. SMS is off on purpose, and the Twilio account is unfunded (HTTP 401 since 2026-09-21). There is currently no working out-of-band alert when the service stalls. The cron schedule itself is correct, and every check since 2026-09-01 logged 'healthy'.
- **Evidence:** server: cat /home/deploy/check-health.sh line 9 PYTHON="/home/deploy/sentinel/venv/bin/python"; 'ls /home/deploy/sentinel/venv' → No such file or directory; repo copy deploy/scripts/check-health.sh:9 is identical (also in deployed commit 6429124); crontab -l → '*/30 * * * * /home/deploy/check-health.sh 2>&1 | logger -t sentinel-health'
- **Suggested fix:** Rewrite the Health Check paragraph. The script detects a stale or missing health.json and logs it to syslog (journalctl -t sentinel-health). Its SMS fallback is currently inert for two reasons: the script points at the removed legacy venv/, and Twilio SMS is off and unfunded. Say there is no working out-of-band staleness alert today and link the TODO item. Remove venv/ from File Layout. Change Hazard #3 to say the legacy venv/ is gone and that check-health.sh still referenced it.
- **Source:** FINDINGS.json #322 (merged with #190, #344, #366, #194)
- **Also reported (duplicate evidence):**
  - #190 (major): deploy/scripts/check-health.sh:22-31; sentinel/scheduler.py:449-477, 554-557 (system SMS via twilio_client); sentinel/scheduler.py:578-597 (health.json is_healthy / classification_status degraded)
  - #344 (major): Server: ls /home/deploy/sentinel/venv returns 'No such file or directory'; only .venv exists. /home/deploy/check-health.sh line 9 and deploy/scripts/check-health.sh:9 both set PYTHON="/home/deploy/sentinel/venv/bin/python". crontab: '*/30 * * * * /home/deploy/check-health.sh 2>&1 | logger -t sentinel-health'. journalctl -t sentinel-health shows 'Project Sentinel healthy' every 30 minutes.
  - #366 (major): /home/deploy/check-health.sh:3 ('Sends an SMS via Twilio if the service appears stuck or dead'), :22-29 (TwilioClient). Crontab: '*/30 * * * * /home/deploy/check-health.sh 2>&1 | logger -t sentinel-health'. journalctl -t sentinel-health over 7 days shows 336x 'Project Sentinel healthy'. Twilio 401 'status 4 is not active' on every send (see the census).
  - #194 (major): deploy/scripts/check-health.sh:9,23-31; deploy/02-deploy-app.sh:61-69,121; deploy/configs/sentinel.service:11 (.venv)

### F-031 [MAJOR]

- **Claim:** Known Server Hazards #2 (line 265): 'RESOLVED 2026-05-25–27. Stray .env files removed; secrets live only in /etc/sentinel/sentinel.env'.
- **Actual:** A stray /home/deploy/sentinel/.env still exists. It is deploy:deploy with mode 0644 (world-readable), dated Mar 28, and git-ignored. It contains the key names TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, TWILIO_WHATSAPP_NUMBER, ALERT_PHONE_NUMBER, ANTHROPIC_API_KEY, TELEGRAM_API_ID and TELEGRAM_API_HASH. World-readable Telegram session files also remain: /home/deploy/sentinel/sentinel_session.session (0644) with its -journal file, and /home/deploy/sentinel.bak-20260324/sentinel_session.session (0644). The whole sentinel.bak-20260324 directory still exists. The /home/deploy/sentinel.bak-20260324/.env and nested project-sentinel/.env listed in the hazard are gone. Secrets also live in /etc/sentinel/openai.env and in four root-only .bak copies in /etc/sentinel.
- **Evidence:** ssh: ls -la /home/deploy/sentinel → '-rw-r--r-- 1 deploy deploy 418 Mar 28 2026 .env', '-rw-r--r-- ... 28672 Mar 23 2026 sentinel_session.session'; sed 's/=.*//' .env (names above); ls -la /home/deploy/sentinel.bak-20260324 → sentinel_session.session 0644; git status --ignored → '!! .env', '!! sentinel_session.session'
- **Suggested fix:** Change Hazard #2 status to OPEN (re-audit 2026-10-03). List the remaining files: /home/deploy/sentinel/.env (0644, Twilio, Anthropic and Telegram key names), the two 0644 Telegram session files and the sentinel.bak-20260324 directory. Correct 'secrets live only in sentinel.env' to name sentinel.env, openai.env and the root-only .bak copies in /etc/sentinel. Link the TODO item.
- **Source:** FINDINGS.json #324

### F-032 [MAJOR]

- **Claim:** Configuration section (lines 158-178): 'Key overrides vs. config.example.yaml' shows only the three path overrides. The edit procedure is 'sudo nano /etc/sentinel/config.yaml; sudo systemctl restart sentinel'. Current deployment (lines 20-23): 'merge reviewed classification fields instead of copying the repository YAML wholesale'.
- **Actual:** The live /etc/sentinel/config.yaml is byte-identical to the tracked config/config.yaml (sha256 156746ac...bdce4 on both sides). /deploy syncs the tracked file to the server, and at HEAD it stops on server-only edits (step 6a). The live overrides against the template are much wider than the three paths: push enabled with the token, high and medium channel push, max_call_retries 1, budget.ledger_path /var/lib/sentinel/model-usage.db, monthly_usd 30. Hand edits on the server would now be flagged as drift.
- **Evidence:** sha256sum: local config/config.yaml and server /etc/sentinel/config.yaml are identical. config/config.yaml:484-485, 597, 603, 647, 650-656 differ from config/config.example.yaml:509-510, 631, 637, 649, 668-669. Repo HEAD 282947f 'deploy: stop before syncing config when the server has its own edits'.
- **Suggested fix:** Change this section to say that config/config.yaml in the repo is the live config and /deploy copies it to /etc/sentinel/config.yaml. To change production, edit and commit config/config.yaml, then run /deploy; do not hand-edit the server file. List the real live-vs-template differences, or link config-reference.md. Remove the 'merge classification fields instead of copying wholesale' sentence.
- **Source:** FINDINGS.json #342 (merged with #187, #320)
- **Also reported (duplicate evidence):**
  - #187 (major): config/config.yaml:484 (ledger_path), 598/604 (channel: push), 651-657 (push); config/config.example.yaml:509 (ledger_path data/model-usage.db), 631/637 (channel: both), 668-669 (push enabled: false); .claude/skills/deploy/SKILL.md:180-187
  - #320 (major): server: sudo grep /etc/sentinel/config.yaml → 483: budget:, 484: ledger_path: /var/lib/sentinel/model-usage.db, 485: monthly_usd: 30; config/config.yaml:650-656 push block; .claude/skills/deploy/SKILL.md:249

### F-033 [MAJOR]

- **Claim:** Troubleshooting row 'No alerts firing' (line 277): 'verify Twilio creds in sentinel.env → Re-auth Twilio; check ALERT_PHONE_NUMBER'. Line 101: '[ALERT] = phone/SMS triggered'. Nothing in the runbook describes the current Twilio state.
- **Actual:** The Twilio account is unfunded on purpose (known state). Every Twilio call and SMS fails with HTTP 401. In the last 14 days, 26 urgency 9-10 events (23 at score 9, 3 at score 10) all ended at alert_status retry_pending. Each one received its additive push (35 push records), but no phone_call or sms record exists after 2026-08-23. Failed Twilio attempts are not written to alert_records, so the DB shows no trace of the call attempts; only the log does. Following the row's advice to 're-auth Twilio' would chase a non-problem.
- **Evidence:** Live alert_records: last phone_call 'completed' row and last sms 'sent' row are both on 2026-08-23. Live events (last 14 days, urgency>=7): '9|retry_pending|23', '10|retry_pending|3'. sentinel.log 2026-10-03 04:38:40: 'Twilio call failed ... HTTP 401 ... authentication failed' followed by 'Twilio call failed to initiate'. sentinel/alerts/state_machine.py:600-603: a None record means no alert_record is written, then alert_status is set to retry_pending at line 645.
- **Suggested fix:** Add a troubleshooting row titled 'Twilio 401 / account not active — KNOWN STATE (owner left account unfunded since 2026-09-21)'. Say that calls and SMS stay configured and return when the account is recharged, and that urgency 9-10 events sit at retry_pending while their additive push still arrives. Also say that failed Twilio attempts leave no alert_records row, so the log is the place to check them. Describe this as a known state, not an outage.
- **Source:** FINDINGS.json #346 (merged with #189, #313, #329, #365)
- **Also reported (duplicate evidence):**
  - #189 (major): sentinel/alerts/twilio_client.py:59-61, 90-92 (error log format); sentinel/alerts/push_client.py:68,86 ('Expo push failed', 'no tickets accepted'); config/config.yaml:598,604 (channel: push)
  - #313 (major): docs/how-to/server-runbook.md:238, :277; grep -i 'unfunded\|status 4\|401' docs/how-to/server-runbook.md -> no hits; sentinel/alerts/twilio_client.py (Twilio SDK path for both calls and SMS)
  - #329 (major): server /var/log/sentinel/sentinel.log: '2026-10-02 09:44:05,598 [ERROR] sentinel.alerts.twilio_client: Twilio call failed for event 03ec67e2-...: HTTP 401 error: Unable to create record: authentication failed, account AC*** with status 4 is not active'; zgrep -c 'is not active' across sentinel.log* → nonzero in 11 of 15 files (e.g. log.5.gz:108)
  - #365 (major): 7-day error census, /var/log/sentinel/sentinel.log*: about 70x '[ERROR] sentinel.alerts.twilio_client: Twilio call failed for event … HTTP 401 error: Unable to create record: authentication failed, account AC*** with status 4 is not active', the same number of 'Twilio SMS failed …' lines and '[ERROR] sentinel.alerts.state_machine: Event …: Twilio call failed to initiate', and 140x '[WARNING] sentinel.alerts.state_machine: Failed to check SMS confirmations: (… HTTP 401 {"code":20003,"message":"Authenticate"…})'. Example: event 4fc335a6 retried 47 rounds between 2026-09-28 14:55 and 22:24 ('1 calls this round, no SMS confirmation, retry in 5 min').

### F-034 [MAJOR]

- **Claim:** Prerequisites (line 10) and SSH Access (line 45): '5 failures in 10 min trips fail2ban, banning your IP for 1 hour.'
- **Actual:** The live sshd jail uses maxretry=3, findtime=600 and bantime=86400 (24 h). bantime.increment=true with maxtime=604800 makes repeat bans double, up to 7 days. The admin home IP is in ignoreip, so it is never banned. /etc/fail2ban/jail.d/whitelist.conf tries to set '5 retries, 1h ban', but fail2ban reads jail.local after jail.d/*.conf, so jail.local's [sshd] maxretry=3 / bantime=86400 wins.
- **Evidence:** ssh deploy@prod 'sudo fail2ban-client get sshd maxretry|findtime|bantime' returned 3 / 600 / 86400. 'sudo fail2ban-client get sshd bantime.increment' returned True, and maxtime returned 604800. ignoreip lists 127.0.0.0/8, ::1 and the documented home IP. /etc/fail2ban/jail.local [sshd] sets maxretry=3 and bantime=86400. whitelist.conf [sshd] sets maxretry=5 and bantime=3600 with the comment 'More forgiving: 5 retries in 10 min, 1h ban'.
- **Suggested fix:** Replace both sentences with this text: '3 failed logins within 10 min ban the source IP for 24 h. Repeat bans double, up to 7 days (bantime.increment). The home IP in ignoreip is never banned. Note: whitelist.conf contains a 5-try / 1 h override, but it has no effect because jail.local is read after jail.d/*.conf.'
- **Source:** FINDINGS.json #351 (merged with #192)
- **Also reported (duplicate evidence):**
  - #192 (major): deploy/configs/fail2ban-jail.local:2-15; deploy/01-harden-server.sh:130-131; docs/how-to/security/vps-hardening.md:252-273

### F-035 [MAJOR]

- **Claim:** Logs (line 101): 'Key log signals: `[ALERT]` = phone/SMS triggered; `[CLASSIFY]` = LLM call; `[FETCH ERROR]` = source down; `[PIPELINE]` = cycle heartbeat.' Troubleshooting lines 277-278 tell the operator to grep for `[CLASSIFY]`, `[ALERT]` and `[FETCH ERROR]` + `telethon`.
- **Actual:** None of these tags exist. The real format is '<ts> [LEVEL] <logger>: <message>'. Real signals: 'sentinel.pipeline: === Pipeline cycle starting [FAST] ===' / '[FULL]' and '=== Cycle complete in Ns: fetched=… classified=… alerts=… ==='; 'sentinel.openai: OpenAI classification: input=… cached=… output=… estimated_usd=… month_usd=…'; 'sentinel.alerts.state_machine: Event …: urgency=N, sources=N, action=push|phone_call'; 'sentinel.alerts.push_client: Push sent for event … ticket=…'; 'sentinel.fetcher.rss: Failed to fetch RSS source X: …'; 'sentinel.fetcher.telegram: Telegram fetcher started, monitoring 4 channels'. The word 'telethon' appears 0 times in the logs.
- **Evidence:** 7 days of logs, grep -cF counts: '[ALERT]'=0, '[CLASSIFY]'=0, '[FETCH ERROR]'=0, '[PIPELINE]'=0, 'telethon'=0. Logger census: sentinel.fetcher.google_news 67440, sentinel.fetcher.rss 25306, sentinel.pipeline 21085, sentinel.openai 5813, sentinel.alerts.push_client 159, sentinel.alerts.twilio_client 140, sentinel.fetcher.telegram 2.
- **Suggested fix:** Replace line 101 with the real logger/message patterns listed above, including ready-made grep commands. In the 'No alerts firing' row, grep for 'action=' and 'month_usd'. In the 'Telegram not connecting' row, check that 'Telegram fetcher started, monitoring 4 channels' appears after each restart and that health.json fetcher_status.telegram is true.
- **Source:** FINDINGS.json #367 (merged with #191, #328)
- **Also reported (duplicate evidence):**
  - #191 (major): grep for '[ALERT]|[CLASSIFY]|FETCH ERROR|[PIPELINE]' in sentinel/ → no hits; sentinel/logging_setup.py:25; sentinel/scheduler.py:227,257,443,544; sentinel/classification/openai_provider.py:65-66; sentinel/alerts/twilio_client.py:60,74,91; sentinel/alerts/state_machine.py:866; sentinel/alerts/push_client.py:68
  - #328 (major): ssh: grep -c of '[ALERT]', '[CLASSIFY]', '[FETCH ERROR]', '[PIPELINE]' in /var/log/sentinel/sentinel.log → 0 each; awk logger-name counts: sentinel.fetcher.google_news 4528, sentinel.fetcher.rss 1683, sentinel.pipeline 1415, sentinel.openai 290, sentinel.alerts.state_machine 42, sentinel.alerts.push_client 13, sentinel.alerts.twilio_client 2

### F-036 [MINOR]

- **Claim:** Troubleshooting table (lines 273-283) and permission row (line 276) list only /etc/sentinel, config.yaml, sentinel.env and /var/lib/sentinel
- **Actual:** Two cases are missing. (1) Classification can be paused by the model budget ledger (monthly_usd 30). Articles then stay pending, the log says 'Model budget reached: classification paused; articles remain pending', and health.json shows classification_status.degraded = true with is_healthy false. (2) OpenAI key or permission errors ('OpenAI rejected the key', 'OpenAI access denied'). The permission row also omits openai.env (root:root 600) and model-usage.db (sentinel:sentinel 600), whose wrong ownership would break classification.
- **Evidence:** config/config.yaml:484-485; sentinel/classification/openai_provider.py:65-66,181-183; sentinel/scheduler.py:578-580; sentinel/database.py:186-190
- **Suggested fix:** Add rows 'Classification paused / health degraded' (check the ledger budget and the OpenAI error lines; check monthly_usd in config/config.yaml) and 'OpenAI key rejected' (check /etc/sentinel/openai.env and the 20-openai.conf drop-in). Extend the permission row with openai.env root:root 600 and model-usage.db sentinel:sentinel 600.
- **Source:** FINDINGS.json #198

### F-037 [MINOR]

- **Claim:** Secrets (line 188): '/etc/systemd/system/sentinel.service.d/20-openai.conf adds the OpenAI environment file'
- **Actual:** The drop-in exists only on the server. deploy/configs/ contains only sentinel.service, with EnvironmentFile=/etc/sentinel/sentinel.env, and 03-setup-services.sh installs only that unit. A rebuild from the repo scripts would therefore start without OPENAI_API_KEY. The runbook does not say the drop-in is unmanaged, and it does not give its content.
- **Evidence:** ls deploy/configs (no drop-in); deploy/configs/sentinel.service:19; deploy/03-setup-services.sh:39-43
- **Suggested fix:** Add: 'The drop-in is server-only (not in deploy/configs). Its content is [Service] EnvironmentFile=/etc/sentinel/openai.env. Recreate it by hand on a rebuild, then run daemon-reload.' Optionally log a TODO to version it in deploy/configs.
- **Source:** FINDINGS.json #199

### F-038 [MINOR]

- **Claim:** Known Server Hazards #5 (line 268): 'Retention rule added for deploy snapshots (e.g. find /home/deploy/backups -maxdepth 1 -name 'deploy-*' -mtime +30 -exec rm -rf {} +)'. File Layout line 75-76: '/home/deploy/backups/ # Daily SQLite backups (7-day retention) └── sentinel_YYYYMMDD.db'.
- **Actual:** Deploy snapshots are pruned by count, not age. /deploy keeps the 10 newest (ls -1dt ... | tail -n +11 | xargs rm -rf). The oldest kept snapshot is deploy-20260529-193238, about 127 days old. The directory also holds loose root:root 0640 config copies (config-before-mute2-082052.yaml, config-pre-push-20260603-101805.yaml). It contains 20 entries and totals 1.6G. The daily DB retention matches: 8 sentinel_YYYYMMDD.db files (20260926-20261003), pruned with -mtime +7 by backup-db.sh at 03:00.
- **Evidence:** ssh: ls -la /home/deploy/backups (10 deploy-* dirs, 8 sentinel_*.db, 2 config-*.yaml), du -sh → 1.6G; .claude/skills/deploy/SKILL.md:291; /home/deploy/backup-db.sh 'find ... -name "sentinel_*.db" -mtime +7 -delete'
- **Suggested fix:** Change the Hazard #5 example to the real rule: /deploy keeps the 10 newest deploy-* snapshots. In File Layout, list deploy-YYYYMMDD-HHMMSS/ snapshot dirs (10 newest kept) and ad-hoc root-only config-*.yaml copies next to the daily sentinel_YYYYMMDD.db files.
- **Source:** FINDINGS.json #330 (merged with #197)
- **Also reported (duplicate evidence):**
  - #197 (minor): .claude/skills/deploy/SKILL.md:140-169 (backup contents), 288-294 (6f keep last 10)

### F-039 [MINOR]

- **Claim:** File Layout lines 61-64: /etc/sentinel/ contains config.yaml, sentinel.env and openai.env.
- **Actual:** The directory also holds four root:root 0640 backup copies: config.yaml.bak.20260328, config.yaml.bak-20260604-pre-pushonly, sentinel.env.bak-20260604-pre-accesstoken and sentinel.env.bak-20260604-pre-pushtoken. The documented ownership and modes of the three main files and the directory are correct.
- **Evidence:** ssh: sudo ls -la /etc/sentinel → 'drwxr-x--- root sentinel', config.yaml root:sentinel 640, openai.env root:root 600, sentinel.env root:deploy 640, plus the four .bak files listed
- **Suggested fix:** Add a line under /etc/sentinel/ in File Layout: '*.bak* — root-only copies of earlier config and env files (contain secrets; root:root 640)'.
- **Source:** FINDINGS.json #331

### F-040 [MINOR]

- **Claim:** Known Server Hazards #6 (line 269): 'TVN24 and LSM Latvia 403ing … LSM Latvia: confirm current state at next audit.'
- **Actual:** LSM Latvia is healthy. It fetched on 709 of 710 slow-lane cycles in 7 days, with 1 transient server error and no 403. The open question can be closed.
- **Evidence:** 7-day counts: 'RSS source LSM Latvia: fetched' 709, error/warning 1 ('RSS source LSM Latvia: server error (5xx)'). DB articles from LSM Latvia in the last 7 days: 14.
- **Suggested fix:** Change hazard #6 status to 'LSM Latvia: verified healthy 2026-10-03 (709/710 cycles OK, no 403)'.
- **Source:** FINDINGS.json #374 (merged with #332)
- **Also reported (duplicate evidence):**
  - #332 (minor): ssh: cat sentinel.log sentinel.log.1 | grep -i 403 | grep -oiE '(rzeczpospolita|rp\.pl|lsm|tvn24|pap)' | uniq -c → 142 rp.pl, 142 Rzeczpospolita, 4 pap.pl, 0 lsm

### F-041 [MINOR]

- **Claim:** Known Issues and Troubleshooting (lines 271-330) cover only feed blocks, permissions, Telegram, disk and SSH. There are no rows for classifier-side warnings, and nothing explains why the service restarts.
- **Actual:** The logs show three recurring classes the runbook does not mention. (1) '[WARNING] sentinel.summary_language: Polish summary unavailable: Translation failed Polish-language validation. Original danger and incident decision preserved.' appeared 40 times in 7 days, about 17% of 232 summary_translation calls. (2) '[ERROR] sentinel.pipeline: Classification failed for …: OpenAI request failed or timed out. Article remains pending; possible charge reserved…' appeared 10 times; the articles were later retried (health.json classification_status pending 0, failed 0). (3) RMF24 returned intermittent 5xx errors (27 server-error warnings and 3 fetch errors), e.g. a burst of 503s on 2026-09-26 around 04:48. In addition, sentinel restarted twice in 7 days (2026-09-26 06:41 and 2026-10-02 06:39). Both restarts came from unattended-upgrades (apt-daily-upgrade, systemd re-exec), not from crashes. The unit has NRestarts=0.
- **Evidence:** Error census above. journalctl 2026-10-02 06:39:14 'Starting apt-daily-upgrade.service', then 06:39:26 'Stopping sentinel.service'. /var/log/apt/history.log: unattended-upgrade upgraded libssl3t64/openssl at 06:39:24. systemctl show sentinel: NRestarts=0, ActiveEnterTimestamp=Fri 2026-10-02 06:39:27 UTC. Only 1 systemd[1] line for the unit in 7 days. Server line 238 of the runbook and config-reference.md:172-178 describe the summary fallback; api-setup.md:68-72 describes pending retries.
- **Suggested fix:** Add troubleshooting rows. (1) 'Polish summary unavailable' = expected degraded summary; the alert still proceeds with fallback_pl; see config-reference summary_language. (2) 'Classification failed … remains pending' = provider timeout; the article is retried; check health.json classification_status and do not delete the queue or ledger. (3) An RMF24 5xx is transient. In Security Stack, note that unattended-upgrades may restart sentinel (seen about twice a week, ~06:40 UTC) and that this is expected.
- **Source:** FINDINGS.json #375

## `docs/how-to/security/vps-hardening.md`

### F-042 [BLOCKER]

- **Claim:** Step 9 (line 435): 'Secure the admin home directory: chmod 750 /home/deploy'.
- **Actual:** The script sets /home/deploy to 755 on purpose. The service runs as User=sentinel with WorkingDirectory=/home/deploy/sentinel. With 750 on a deploy:deploy home directory, the sentinel user cannot enter /home/deploy, so the service fails to start. The 750-to-755 change was made in commit 791ed0a ('Fix permissions discovered during live deployment').
- **Evidence:** deploy/01-harden-server.sh:163 `chmod 755 /home/deploy`; deploy/configs/sentinel.service:8,10-11 (User=sentinel, WorkingDirectory=/home/deploy/sentinel); git show 791ed0a: '/home/deploy must be 755 (not 750) so sentinel user can traverse to WorkingDirectory'
- **Suggested fix:** Change the Step 9 line to `chmod 755 /home/deploy`. Add one sentence explaining why: the sentinel service user must be able to enter /home/deploy to reach /home/deploy/sentinel.
- **Source:** FINDINGS.json #200 (merged with #357)
- **Also reported (duplicate evidence):**
  - #357 (major): sudo ls -ld /home/deploy shows drwxr-xr-x deploy deploy. id sentinel returns groups=110(sentinel) only. systemctl cat sentinel.service shows User=sentinel and ExecStart=/home/deploy/sentinel/.venv/bin/python.

### F-043 [BLOCKER]

- **Claim:** Step 2 (lines 74-76): 'Create config/secrets directory: mkdir -p /etc/sentinel; chmod 700 /etc/sentinel' (stays root:root).
- **Actual:** The script makes /etc/sentinel root:sentinel with mode 750, so the service can read config.yaml. With root:root 700, the sentinel service user cannot read /etc/sentinel/config.yaml, which is passed via --config in ExecStart. Commit 791ed0a fixed exactly this in the script. Production file modes are config.yaml root:sentinel 640 and sentinel.env root:deploy 640, and the doc mentions neither.
- **Evidence:** deploy/01-harden-server.sh:106-108 (`chown root:sentinel /etc/sentinel`; `chmod 750 /etc/sentinel`); deploy/02-deploy-app.sh:79-80,92-93; deploy/configs/sentinel.service:11; docs/how-to/server-runbook.md troubleshooting row 'Permission denied on startup'; git show 791ed0a
- **Suggested fix:** Replace the Step 2 lines with `chown root:sentinel /etc/sentinel; chmod 750 /etc/sentinel`. Add the file modes: config.yaml root:sentinel 640, and sentinel.env root:deploy 640. Note that sentinel.env is read by systemd (PID 1) through EnvironmentFile, not by the sentinel user.
- **Source:** FINDINGS.json #201 (merged with #356)
- **Also reported (duplicate evidence):**
  - #356 (major): sudo ls -ld /etc/sentinel shows 'drwxr-x--- root sentinel'. config.yaml is -rw-r----- root:sentinel. sentinel.service has User=sentinel and ExecStart ... --config /etc/sentinel/config.yaml.

### F-044 [MAJOR]

- **Claim:** Step 3c/3d (lines 127-174): writing `Port 2222` in /etc/ssh/sshd_config.d/99-sentinel-hardening.conf and running `sshd -t; systemctl restart sshd` moves SSH to 2222.
- **Actual:** On Ubuntu 24.04, SSH is socket-activated through ssh.socket, and the script states that ssh.socket overrides the Port in sshd_config. The script therefore writes /etc/systemd/system/ssh.socket.d/override.conf with ListenStream 0.0.0.0:$SSH_PORT and [::]:$SSH_PORT. It then runs `systemctl daemon-reload` and `systemctl restart ssh.socket`, using `ssh` rather than `sshd` as the fallback. The doc mentions none of this. If someone follows the doc and then runs Step 4 (UFW allows only 2222), they can be locked out. The runbook lists this override as part of the live security stack.
- **Evidence:** deploy/01-harden-server.sh:186-208; docs/how-to/server-runbook.md Security Stack row 'SSH socket | systemd override | /etc/systemd/system/ssh.socket.d/override.conf' and troubleshooting row 'systemctl restart ssh.socket'; commit dc50f73 'Fix SSH hardening: handle Ubuntu 24.04 socket activation'
- **Suggested fix:** Add a step 3c-bis that creates /etc/systemd/system/ssh.socket.d/override.conf (ListenStream= / ListenStream=0.0.0.0:2222 / ListenStream=[::]:2222). Change 3d to `sshd -t && systemctl daemon-reload && systemctl restart ssh.socket`. Also show the fallback `systemctl restart ssh` for systems without socket activation.
- **Source:** FINDINGS.json #202

### F-045 [MAJOR]

- **Claim:** The whole doc is a manual 13-step procedure ('Every step below should be done in your first SSH session'). It never mentions the deploy/ scripts and does not say whether this is how production was built.
- **Actual:** The production server was provisioned by deploy/01-harden-server.sh (then 02-deploy-app.sh and 03-setup-services.sh) on 2026-03-23. Several commits that day are titled as fixes 'discovered during live deployment'. The script differs from the doc in several ways. It copies root's authorized_keys to deploy instead of asking you to paste a key. It runs SSH hardening LAST, keeping a temporary UFW rule for port 22 that it deletes afterwards. It installs more packages (python3, python3-venv, git, sqlite3, gettext-base). It installs fail2ban/sysctl/sshd settings from deploy/configs/*. It logs to /var/log/sentinel-hardening.log. A reader cannot tell which source is authoritative.
- **Evidence:** deploy/01-harden-server.sh:1-20,54,69-79,120-123,211-213; git log 8211636..791ed0a on 2026-03-23 (bd87079 'Fix UFW lockout: keep port 22 open until SSH moves', dc50f73, 791ed0a)
- **Suggested fix:** Add a header note. It should say that production (Ubuntu 24.04, Hetzner) was hardened on 2026-03-23 with `deploy/01-harden-server.sh` (run as root, SSH_PORT defaults to 2222), using the config files in deploy/configs/. It should say this guide is the manual equivalent, and that where the two differ, the script and deploy/configs/* are the source of truth. Then list which steps the script does NOT perform: Step 6's 50unattended-upgrades edits, Step 10's cron job, and Step 11.
- **Source:** FINDINGS.json #203

### F-046 [MAJOR]

- **Claim:** Step 2 (lines 58-61): `adduser deploy` with 'a strong password -- needed for sudo'; `usermod -aG sudo deploy`.
- **Actual:** The script creates deploy with --disabled-password and sets a random 32-byte password that nobody knows. It then grants passwordless sudo through /etc/sudoers.d/deploy ('deploy ALL=(ALL) NOPASSWD:ALL', mode 440, checked with visudo -c), because scripts 02 and 03 and /deploy run sudo non-interactively over SSH. As a result, sudo on the live server never asks for a password. The doc does not mention this privilege grant at all.
- **Evidence:** deploy/01-harden-server.sh:63-65 and 81-85
- **Suggested fix:** Document what was actually set up: deploy has no usable password and has NOPASSWD sudo through /etc/sudoers.d/deploy, which non-interactive deploys need. Say plainly that this means any holder of the deploy SSH key effectively has root.
- **Source:** FINDINGS.json #204

### F-047 [MAJOR]

- **Claim:** Step 5 Fail2ban (lines 235-296) and 'Emergency: Locked Out?' cover only jail.local. They give no IP whitelist.
- **Actual:** The jail.local values in the doc match deploy/configs/fail2ban-jail.local exactly. However, the live server also has /etc/fail2ban/jail.d/whitelist.conf with an `ignoreip` admin whitelist, which the runbook documents (update it when the home IP changes). Project CLAUDE.md warns that SSH as root@ or kossa@ triggers fail2ban bans. The hardening doc never mentions the whitelist file or this ban risk.
- **Evidence:** deploy/configs/fail2ban-jail.local:1-15 (matches doc lines 250-274); docs/how-to/server-runbook.md 'fail2ban — update whitelisted IP' block (`sudo nano /etc/fail2ban/jail.d/whitelist.conf`; `fail2ban-client get sshd ignoreip`) and Security Stack row; CLAUDE.md Critical rules ('root@/kossa@ trigger fail2ban bans')
- **Suggested fix:** Add a subsection to Step 5 about /etc/fail2ban/jail.d/whitelist.conf ([sshd] ignoreip = 127.0.0.1/8 <admin-ip>), followed by `fail2ban-client reload`. Add a line warning that SSH as any user other than deploy counts as a failed attempt and gets banned. Link to the runbook procedure.
- **Source:** FINDINGS.json #205

### F-048 [MAJOR]

- **Claim:** Step 12 (lines 544-546) and checklist row 10 (line 566): `sudo -u sentinel bash` is expected to print 'This account is currently not available.'
- **Actual:** `sudo -u sentinel bash` runs /bin/bash directly as the sentinel user and ignores the account's login shell (/usr/sbin/nologin, set at deploy/01-harden-server.sh:93). It opens a bash shell instead of printing the nologin message, so this check proves nothing. The nologin message only appears when the login shell itself is invoked, for example `sudo su - sentinel` or `sudo -u sentinel -i`.
- **Evidence:** deploy/01-harden-server.sh:93 (`--shell /usr/sbin/nologin`); docs/how-to/security/vps-hardening.md:545,566
- **Suggested fix:** Replace the command with `getent passwd sentinel | cut -d: -f7` (expected: /usr/sbin/nologin) or `sudo su - sentinel` (expected: 'This account is currently not available.') in both Step 12 and checklist row 10.
- **Source:** FINDINGS.json #206

### F-049 [MAJOR]

- **Claim:** Step 0 (lines 18-33) and Post-Hardening Checklist #1 (line 557): the Hetzner Cloud Firewall 'sentinel-fw' allows TCP 2222 only from '<your-admin-ip>/32'. The runbook Security Stack table (server-runbook.md:310-321) implies SSH is not exposed beyond UFW 2222.
- **Actual:** SSH on 2222 is reachable from the whole internet. In the last 24 h sshd logged connections from 122 distinct source IPs. fail2ban shows 376 total failures, 113 total bans and 59 IPs banned right now. UFW allows 2222/tcp from Anywhere (v4 and v6). Either the Cloud Firewall is not applied, or it does not restrict the source to the admin IP. The console itself cannot be checked from the host.
- **Evidence:** sudo journalctl _COMM=sshd --since '24 hours ago' | grep -oE 'from [0-9.]+ port' | sort -u | wc -l returned 122. sudo fail2ban-client status sshd returned 'Total failed: 376', 'Currently banned: 59' and 'Total banned: 113'. sudo ufw status verbose shows '2222/tcp ALLOW IN Anywhere'.
- **Suggested fix:** In the runbook Security Stack, add a 'Provider firewall | Hetzner Cloud Firewall' row stating that SSH 2222 is currently reachable from any IP and that fail2ban + key-only auth are the effective protection. Add a TODO.md item asking the owner to check sentinel-fw in the Hetzner console (applied? source restricted to the admin IP?).
- **Source:** FINDINGS.json #353

### F-050 [MAJOR]

- **Claim:** Step 6 (lines 325-327) sets 'Unattended-Upgrade::Automatic-Reboot "true"' at 04:00 so kernel updates take effect. The runbook Security Stack (server-runbook.md, 'Auto-updates | unattended-upgrades | security patches only') implies patches are applied.
- **Actual:** No uncommented Automatic-Reboot or Remove-Unused-Dependencies line exists in /etc/apt/apt.conf.d/. The host has not rebooted since 2026-03-24 and still runs kernel 6.8.0-106. Kernel 6.8.0-142 is installed. /var/run/reboot-required exists, and reboot-required.pkgs lists libc6, linux-base and the kernels 6.8.0-107 through 6.8.0-137 and later. Security updates are downloaded but have not taken effect for the kernel or libc for 6 months.
- **Evidence:** sudo grep -rn 'Automatic-Reboot\|Remove-Unused' /etc/apt/apt.conf.d/ | grep -v '//' returned nothing. uptime -s returned 2026-03-24 16:43:13. uname -r returned 6.8.0-106-generic. dpkg -l linux-image-* shows 6.8.0-106.106 and 6.8.0-142.142. /var/run/reboot-required is present.
- **Suggested fix:** In the runbook Security Stack, change the Auto-updates row to: 'security + ESM pockets; automatic reboot is NOT enabled, so kernel/libc updates need a manual reboot (pending since 2026-03; check /var/run/reboot-required)'. Add an '[AMENDMENT 2026-10-03]'-style note in hardening Step 6 saying the production host does not use Automatic-Reboot. Log a TODO item asking the owner to schedule a reboot and decide on auto-reboot. A reboot interrupts monitoring, so it is the owner's decision.
- **Source:** FINDINGS.json #354 (merged with #208)
- **Also reported (duplicate evidence):**
  - #208 (minor): deploy/01-harden-server.sh:146-154; docs/how-to/server-runbook.md Security Stack 'Auto-updates | unattended-upgrades | security patches only'

### F-051 [MINOR]

- **Claim:** Doc never mentions the systemd service sandbox or log/journal retention. The area guide asks for unit hardening directives.
- **Actual:** deploy/03-setup-services.sh installs deploy/configs/sentinel.service with a hardening sandbox: NoNewPrivileges, ProtectSystem=strict, ProtectHome=read-only, ReadWritePaths=/var/lib/sentinel /var/log/sentinel, PrivateTmp, PrivateDevices, ProtectKernelTunables/Logs, ProtectControlGroups, ProtectClock, ProtectHostname, an empty CapabilityBoundingSet, RestrictSUIDSGID, LockPersonality, RestrictRealtime, SystemCallArchitectures=native, and RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX. It also checks the result with `systemd-analyze security` (aim under 4.0). It sets journald to SystemMaxUse=500M and MaxRetentionSec=30day, and logrotate to daily with 14 rotations. A future agent who changes the app (for example, a new write path) needs to know about ProtectSystem=strict and ReadWritePaths.
- **Evidence:** deploy/configs/sentinel.service:21-45; deploy/03-setup-services.sh:184-214; deploy/configs/sentinel-logrotate:1-9
- **Suggested fix:** Add a short 'Service sandbox (applied by 03-setup-services.sh)' section. It should list the directives, note that only /var/lib/sentinel and /var/log/sentinel are writable, and give the `sudo systemd-analyze security sentinel.service` check. Alternatively, link to a runbook section that lists them.
- **Source:** FINDINGS.json #207

### F-052 [MINOR]

- **Claim:** Line 10: 'Only then deploy the application (Phase 7)'.
- **Actual:** No current doc defines a 'Phase 7'. This is a leftover from an archived build plan. Deployment is done with deploy/02-deploy-app.sh and deploy/03-setup-services.sh for first install, and with the /deploy skill and the server runbook for updates.
- **Evidence:** grep 'Phase 7' docs (excluding archive) → only docs/how-to/security/vps-hardening.md:10
- **Suggested fix:** Replace '(Phase 7)' with 'run deploy/02-deploy-app.sh then deploy/03-setup-services.sh as deploy; later updates go through /deploy (see docs/how-to/server-runbook.md)'.
- **Source:** FINDINGS.json #210

### F-053 [MINOR]

- **Claim:** Ongoing Maintenance > Weekly (line 576): `sudo journalctl -u sshd --since "7 days ago"`.
- **Actual:** On Ubuntu 24.04 the unit is ssh.service, activated by ssh.socket, which the script and runbook use. `journalctl -u sshd` filters on sshd.service and usually shows no entries, so the weekly review would silently show nothing.
- **Evidence:** deploy/01-harden-server.sh:204-207 (ssh.socket / `systemctl restart ssh`); docs/how-to/server-runbook.md troubleshooting 'systemctl restart ssh.socket'
- **Suggested fix:** Use `sudo journalctl -u ssh --since "7 days ago" | tail -50` (or `sudo grep sshd /var/log/auth.log | tail -50`).
- **Source:** FINDINGS.json #211

### F-054 [MINOR]

- **Claim:** Post-Hardening Checklist row 4 (line 560): `ssh deploy@<ip> -p 22` → 'Connection refused'.
- **Actual:** UFW is set to default deny incoming, which drops packets, and the Hetzner Cloud Firewall allows only 2222. A connection to port 22 therefore times out rather than being refused. The runbook's own troubleshooting row says a blocked port shows as 'SSH connection timed out'. Someone checking this row could wrongly read a timeout as a failure.
- **Evidence:** deploy/01-harden-server.sh:118 (`ufw default deny incoming`), :212 (port 22 rule deleted); docs/how-to/server-runbook.md troubleshooting row 'SSH connection timed out | Port blocked'
- **Suggested fix:** Change the expected result to 'Connection timed out (or refused)'.
- **Source:** FINDINGS.json #212

### F-055 [MINOR]

- **Claim:** Step 7 (lines 377-379) and Security Stack (server-runbook.md 'Kernel | sysctl | /etc/sysctl.d/99-sentinel-hardening.conf'): log_martians = 1 is applied.
- **Actual:** The live file contains net.ipv4.conf.all/default.log_martians = 1, but the running kernel value is 0 for both. No other sysctl.d file sets log_martians, so the cause is unknown. The other checked values (rp_filter, syncookies, redirects, source_route, disable_ipv6, syn backlog/retries, icmp broadcasts) match.
- **Evidence:** sudo sysctl net.ipv4.conf.all.log_martians returned 0. net.ipv4.conf.default.log_martians returned 0. /etc/sysctl.d/99-sentinel-hardening.conf:19-20 sets both to 1. grep over /etc/sysctl.conf, /etc/sysctl.d, /usr/lib/sysctl.d and /run/sysctl.d found only a commented line in sysctl.conf.
- **Suggested fix:** Log as a TODO item: log_martians is configured but not active on the live host (investigate). Doc text needs no change beyond noting the drift if the owner keeps it.
- **Source:** FINDINGS.json #358

### F-056 [MINOR]

- **Claim:** Step 10 (lines 461-484) and Ongoing Maintenance (lines 584, 589): a custom /etc/cron.daily/aide-check writes /var/log/aide-check.log and mails on change, and the AIDE database is updated after every apt upgrade. The runbook Security Stack lists 'File integrity | AIDE | —'.
- **Actual:** /etc/cron.daily/aide-check and /var/log/aide-check.log do not exist. The packaged dailyaidecheck.timer runs daily and writes /var/log/aide/aide.log (~17 MB per day). The baseline /var/lib/aide/aide.db dates from 2026-03-23 and has never been updated, with COPYNEWDB=no. As a result every daily report is dominated by six months of legitimate changes and gives no usable intrusion signal.
- **Evidence:** ls /etc/cron.daily shows dailyaidecheck and no aide-check. systemctl list-timers shows dailyaidecheck.timer, last run 2026-10-03 02:24. /var/lib/aide/aide.db is dated Mar 23 2026, while aide.db.new is dated Oct 3. /var/log/aide/aide.log is 17075967 bytes. /etc/default/aide has COPYNEWDB=no.
- **Suggested fix:** In Step 10, document that production uses the Ubuntu package's dailyaidecheck.timer (log /var/log/aide/aide.log) instead of the custom cron script. Set the runbook Security Stack AIDE config cell to 'dailyaidecheck.timer, /var/lib/aide/aide.db (baseline 2026-03-23)'. Log a TODO item to refresh the AIDE baseline.
- **Source:** FINDINGS.json #359 (merged with #209)
- **Also reported (duplicate evidence):**
  - #209 (minor): deploy/01-harden-server.sh:167-176 (no Step 11 equivalent anywhere in deploy/)

### F-057 [MINOR]

- **Claim:** Step 4, 'What About Other Ports?' (line 223): Sentinel is outbound-only and needs no incoming ports besides SSH.
- **Actual:** Postfix is installed and listens on 0.0.0.0:25 and [::]:25 (inet_interfaces = all). UFW (default deny incoming, only 2222 allowed) blocks it from outside, so it is not exposed. Neither the hardening guide nor the runbook Security Stack mentions Postfix.
- **Evidence:** sudo ss -tlnp shows 'LISTEN 0.0.0.0:25 users:(("master"...))' and '[::]:25'. dpkg -l postfix shows ii 3.8.6-1ubuntu0.1. postconf inet_interfaces returns all. The ufw status allow list contains only 2222/tcp.
- **Suggested fix:** Add a note: 'Postfix (local mail for AIDE/cron) is installed and listens on port 25 on all interfaces; UFW blocks it inbound.' Log a TODO item to consider inet_interfaces = loopback-only.
- **Source:** FINDINGS.json #360

### F-058 [MINOR]

- **Claim:** Step 11 (lines 488-513): /etc/profile.d/ssh-login-notify.sh logs every SSH login.
- **Actual:** The file does not exist on the production host.
- **Evidence:** sudo ls -l /etc/profile.d/ssh-login-notify.sh returned 'No such file or directory'.
- **Suggested fix:** Mark Step 11 as optional and not deployed on the current production host. Alternatively, log a TODO item if the owner wants it.
- **Source:** FINDINGS.json #361

### F-059 [MINOR]

- **Claim:** Step 5 (lines 243-274): fail2ban 'monitors log files', with the sshd jail at 'logpath = /var/log/auth.log'.
- **Actual:** On this host /etc/fail2ban/jail.d/defaults-debian.conf sets backend = systemd and banaction = nftables. The sshd jail reads the systemd journal (_SYSTEMD_UNIT=sshd.service + _COMM=sshd), and the logpath line has no effect.
- **Evidence:** sudo fail2ban-client status sshd shows 'Journal matches: _SYSTEMD_UNIT=sshd.service + _COMM=sshd'. 'fail2ban-client get sshd logpath' returns 'No file is currently monitored'. defaults-debian.conf contains backend = systemd and banaction = nftables.
- **Suggested fix:** Add a note under the jail.local example: 'On Ubuntu 24.04 the Debian default backend = systemd applies, so fail2ban reads the journal; logpath is ignored. Bans are applied via nftables. Overrides in jail.d/*.conf are overridden by jail.local.'
- **Source:** FINDINGS.json #362

## `.claude/skills/deploy/SKILL.md`

### F-060 [MAJOR]

- **Claim:** Step 5 'Full Server Backup' says it creates a backup 'containing all critical data', and the Completion Report lists the contents as 'code.tar.gz, config.yaml, sentinel.db, sentinel_session.session'.
- **Actual:** Production has a second SQLite database: the persistent OpenAI cost ledger at /var/lib/sentinel/model-usage.db (sentinel:sentinel 0600). Step 5 never backs it up. The 2026-09-20 Luna deploy backed it up by hand ('Both SQLite files were backed up'), and it also saved sentinel.service. Because the file is mode 0600, the deploy user can read it only with sudo, so a plain sqlite3 call would fail.
- **Evidence:** config/config.yaml:484 'ledger_path: /var/lib/sentinel/model-usage.db'; commit 6429124 (the live commit) moved the ledger there; docs/reference/luna-deployment-20260920.md:27-30 and :42-43 (ledger owner and mode 0600); docs/how-to/server-runbook.md:68; SKILL.md:149-164 (only sentinel.db is backed up) and :339
- **Suggested fix:** Add a backup item 3b: `sudo sqlite3 /var/lib/sentinel/model-usage.db ".backup '$BACKUP_DIR/model-usage.db'"`. Also add model-usage.db to the Server Reference table and to the Completion Report's backup-contents line. Optionally back up /etc/systemd/system/sentinel.service.d/ as well, without the env files.
- **Source:** FINDINGS.json #230

### F-061 [MAJOR]

- **Claim:** The Server Reference file table (lines 26-37) and Critical Safety Rule 2 ('Never touch /etc/sentinel/sentinel.env') present sentinel.env as the only secrets file.
- **Actual:** The live classifier is OpenAI gpt-5.6-luna. Its key is stored in a separate file, /etc/sentinel/openai.env (root:root 0600). A systemd drop-in, /etc/systemd/system/sentinel.service.d/20-openai.conf, loads that file. The skill names neither one, so an agent has no rule against reading or printing the OpenAI key. It also does not know that the repo's deploy/configs/sentinel.service is not the full live unit.
- **Evidence:** docs/how-to/server-runbook.md:61-64, :182-188; docs/reference/luna-deployment-20260920.md:44-48; deploy/configs/sentinel.service:19 (lists only sentinel.env); SKILL.md:32, :361
- **Suggested fix:** Add rows for /etc/sentinel/openai.env (root:root 600, never read or back up), /etc/systemd/system/sentinel.service.d/20-openai.conf (loads the OpenAI key; deploy does not manage it) and /var/lib/sentinel/model-usage.db. Extend Safety Rule 2 to cover openai.env.
- **Source:** FINDINGS.json #231

### F-062 [MAJOR]

- **Claim:** Step 7b says: 'Scan for ERROR, Exception, Traceback, CRITICAL. If found → ALERT'. 'On Failure (at any verification step)' then says to STOP and report a failure.
- **Actual:** Every cycle logs a known, pre-existing ERROR line: Rzeczpospolita RSS returns HTTP 403 from the VPS. A 403 hits raise_for_status, and the error is logged at line 56. The initial cycle runs right after restart, so this line will appear in the 7b window on every deploy, and the skill will declare the deploy failed. The skill lists no known pre-existing errors to tell apart from regressions.
- **Evidence:** sentinel/fetchers/rss.py:56 (logger.error 'Failed to fetch RSS source %s') and :89 (raise_for_status for 4xx); config/config.yaml:319-322 (Rzeczpospolita enabled); sentinel.py:167-169 (first cycle runs immediately); docs/how-to/server-runbook.md:327; docs/reference/luna-deployment-20260920.md:76-78 (the only error at the Luna deploy was this 403)
- **Suggested fix:** Add a 'Known pre-existing log lines (not deploy failures)' note to 7b. List the Rzeczpospolita RSS HTTP 403 ('Failed to fetch RSS source Rzeczpospolita'). List Twilio HTTP 401 'account ... is not active' too: the account is deliberately unfunded, so this is a known state that clears when the owner recharges it. Tell the agent to compare any ERROR against the pre-restart journal before raising ALERT.
- **Source:** FINDINGS.json #232

### F-063 [MAJOR]

- **Claim:** Step 3: 'To rollback later: `git checkout {tag}` and re-deploy.' On Failure item 4: 're-deploy a previous git tag (`git tag -l 'deploy-*'` to list)'.
- **Actual:** The pipeline cannot deploy an older tag. After `git checkout <tag>`, HEAD is detached and `git branch --show-current` prints an empty string. Step 1c then treats this as 'a branch other than master', so Step 2 runs `git checkout master && git merge --no-edit ""`, which fails. If Step 2 were skipped, Step 3 would tag master HEAD and Step 6b would deploy master, not the old tag. The skill has no real rollback path.
- **Evidence:** SKILL.md:80-83 (branch check), :99-103 (merge of $CURRENT_BRANCH), :114-115 (tags the current HEAD after checkout master), :120, :354; git tag -l 'deploy-*' (20 tags, latest deploy-20260925-143105 = 6429124)
- **Suggested fix:** Replace both rollback sentences with a manual rollback procedure that works. On the server: `git fetch --tags origin && git checkout <deploy-tag>`. Restore /etc/sentinel/config.yaml (and the DB if needed) from /home/deploy/backups/deploy-<ts>/, then `sudo systemctl restart sentinel`. State plainly that /deploy itself deploys only master HEAD.
- **Source:** FINDINGS.json #233

### F-064 [MINOR]

- **Claim:** Frontmatter: 'rebuilds the venv if needed'. Server table: '.venv/ … Rebuilt on server after deploy'. Step 6d is titled 'Rebuild Python dependencies'.
- **Actual:** No rebuild and no condition exist. Step 6d runs `.venv/bin/pip install -r requirements.txt` into the existing venv on every deploy. The venv is never recreated, and packages removed from requirements.txt stay installed.
- **Evidence:** SKILL.md:7-8, :30, :272-276
- **Suggested fix:** Change the wording to 'installs/updates dependencies into the existing server venv (pip install -r requirements.txt, every deploy; the venv is never recreated)'.
- **Source:** FINDINGS.json #234

### F-065 [MINOR]

- **Claim:** Step 6a: 'Values of keys whose name looks like a token, key, secret, password, SID or auth are shown as ***'. The exit-3 STOP message then says: 'Copy these values into config/config.yaml'.
- **Actual:** The regex `token|key|secret|password|sid|auth` matches substrings of the full dotted path. It therefore masks all monitoring.keywords.* and monitoring.exclude_keywords.* lists and the classification *max_tokens values, besides alerts.push.tokens. A server-only keyword edit, the most likely kind of drift (see runbook Ops Debt #4), would appear as `live=*** -> repo=***`. The agent then cannot see the values it is told to copy.
- **Evidence:** SKILL.md:207, :233, :245, :249. Running the regex over config/config.yaml leaves masks monitoring.keywords.{en,pl,uk,ru}.{critical,high}, monitoring.exclude_keywords.{en,pl}, classification.max_tokens, classification.summary_language.repair_max_tokens, classification.incident_memory.extra_output_tokens and alerts.push.tokens
- **Suggested fix:** Document that keyword lists and *_tokens values are also masked. For an UNEXPECTED masked key, the agent should read the value from the Step 5 backup copy (/home/deploy/backups/deploy-<ts>/config.yaml) with sudo. Log a TODO item to narrow the regex to whole key names.
- **Source:** FINDINGS.json #235

### F-066 [MINOR]

- **Claim:** Step 6a: 'Any other failure (e.g. the script or `sudo cat` fails) → STOP and show the output'.
- **Actual:** The script uses `set -uo pipefail` without -e, so failed commands do not stop it. If `sudo cat` fails, LIVE is empty and every key is reported as UNEXPECTED with exit 3. The agent then gets a misleading 'server-only edits' message rather than an 'other failure'. If `git show "$1:config/config.yaml"` fails, NEW is empty and every key is listed as EXPECTED with repo='<missing>'. The check exits 0 and the deploy continues. This was verified locally by running the embedded Python with an empty file.
- **Evidence:** SKILL.md:191 (set -uo pipefail), :197-199, :240, :250. Local simulation: empty NEW → 'UNEXPECTED … none', exit 0; empty LIVE → exit 3
- **Suggested fix:** Correct the bullet: a failed `sudo cat` appears as exit 3 with every key UNEXPECTED, and a failed `git show` silently passes. Log a TODO item to add explicit `|| exit 4` guards after the `sudo cat` and both `git show` lines.
- **Source:** FINDINGS.json #236

### F-067 [MINOR]

- **Claim:** Step 7c (run about 15 s after restart) says: 'Report the health status … health.json may take up to 3 minutes to refresh.' The Completion Report then reads 'Health: {health.json contents or "awaiting first cycle"}'.
- **Actual:** The immediate startup cycle calls pipeline.run_cycle() directly and does not write health.json. Only the scheduled lanes (_run_with_error_handling → _update_health) write it, and the first fast-lane run fires after fast_interval_minutes = 3, plus up to 10 s of jitter. At 7c, and still at 7d (about 45 s), the file is the previous process's snapshot. It exists, so the 'not yet available' fallback never shows. The agent would report stale pre-restart health as the deploy result.
- **Evidence:** sentinel.py:167-169; sentinel/scheduler.py:502-508, :535-539, :596-601; config/config.yaml:658
- **Suggested fix:** Tell the agent to compare `last_cycle_at` in health.json with the restart time. If it is older, report 'pre-restart snapshot; first post-restart write expected about 3 min after restart' and, optionally, re-check after 3-4 minutes.
- **Source:** FINDINGS.json #237

### F-068 [MINOR]

- **Claim:** 6c failure note: 'The service is still running with the old config; no damage done'. 6d failure note: only 'remind the user that a backup exists'.
- **Actual:** By 6d the new code is already on disk from 6b, and the new config from 6c. The old process still runs only from memory. The unit has Restart=always, so any crash or restart after a failed 6d loads the new code and config, possibly without the new dependencies. The skill does not warn about this half-deployed state. The Luna deploy instead installed dependencies before activating the new config.
- **Evidence:** SKILL.md:252-278; deploy/configs/sentinel.service:12 (Restart=always); docs/reference/luna-deployment-20260920.md:53-54
- **Suggested fix:** In 6d's failure branch, state that the server is half-deployed: new code and config on disk, old process in memory, and any restart picks up the new state. Name the restore steps: check out the previous tag, copy the backup config.yaml back and restart.
- **Source:** FINDINGS.json #238

## `.claude/skills/sentinel-audit/SKILL.md`

### F-069 [MAJOR]

- **Claim:** Pipeline Stages step 5 (line 26): 'Classify — Claude Haiku 4.5 assesses keyword-matched articles'. Step 3 (line 217): 'state what Haiku said'. The report template tables (lines 332-338, 352-358) use a 'Haiku' column, and the example on line 402 says 'Haiku: is_military_event=false…'.
- **Actual:** The live classifier is OpenAI gpt-5.6-luna through OpenAIProvider. Classification runs with policy v2 and incident memory: a system prompt plus a JSON user message that carries evaluation_time and remembered_incidents. The Anthropic Haiku path is legacy and used only for rollback. classifications.model_used / provider_used will read gpt-5.6-luna / openai.
- **Evidence:** config/config.yaml:472 'provider: openai', :558 'model: gpt-5.6-luna', :540-541 'incident_memory: enabled: true'; sentinel/classification/classifier.py:164 selects OpenAIProvider when provider=='openai', :178-184 calls provider.request(messages(...)), :204 provider_used='openai'; sentinel/classification/policy.py:136-152 messages()
- **Suggested fix:** Replace 'Claude Haiku 4.5' with 'OpenAI gpt-5.6-luna (provider openai; Anthropic Haiku is legacy/rollback only)' in step 5. Rename the 'Haiku' column and the 'what Haiku said' wording to 'Classifier' or 'Luna'. Add a note that the auditor can read the model from classifications.model_used / provider_used.
- **Source:** FINDINGS.json #240 (merged with #302)
- **Also reported (duplicate evidence):**
  - #302 (major): config/config.yaml:396 gdelt enabled: false, :558, :585, :597, :603; grep -rni whatsapp sentinel/ -> no hits; sentinel/database.py:119-135

### F-070 [MAJOR]

- **Claim:** Pipeline Stages lines 27-28: 'Corroborate — … require 2+ independent sources for phone calls' and 'Alert — Phone call (urgency 9-10 + 2 sources), SMS (7-8), WhatsApp (5-6)'. Line 16 says the system 'alerts via Twilio phone call'. Line 404: 'Should trigger SMS alert at minimum'.
- **Actual:** Live corroboration_required is 1, so one source triggers a phone call today. Tiers 5-8 (high and medium) are push-only (channel: push), and SMS is switched off on purpose. WhatsApp does not exist anywhere in the code or config. Urgency 9-10 places a phone call plus an additive push, with an SMS fallback. The Twilio account is deliberately unfunded, so calls and SMS currently fail with 401 (a known state).
- **Evidence:** config/config.yaml:561 'corroboration_required: 1' (classification), :585/:592/:601 per-tier 'corroboration_required: 1', :597 and :603 'channel: push'; sentinel/classification/corroborator.py:437-441 phone_call when urgency>=9 and source_count>=corroboration_required; sentinel/alerts/state_machine.py:472-508 tiers 5-8 resolve to level.channel; `grep -rni whatsapp sentinel config` returns nothing
- **Suggested fix:** Rewrite stages 6-7 as follows. One source triggers a call today (corroboration_required: 1). Urgency 9-10 gets a phone call plus an additive push (SMS fallback). Urgency 5-8 gets push only (SMS off by owner decision). Urgency 1-4 is log only. Remove WhatsApp. Change line 404 to 'should trigger a push alert at minimum'. Add a TODO.md item asking the owner whether to require 2 sources.
- **Source:** FINDINGS.json #241

### F-071 [MAJOR]

- **Claim:** Database section (line 32): 'Articles present in `articles` but absent from `classifications` = articles filtered out by keywords and NEVER evaluated by the classifier.' Query 1c (lines 132-136) treats every such article as a keyword-filter miss.
- **Actual:** Articles that pass the keyword filter are first written to a classification_queue table. They get a classifications row only after a successful classify and grouping. Articles still pending, or failing because of a provider error, budget limit, empty summary or grouping_failed, stay in the queue with no classification. The pruner also keeps queued articles. Articles from keyword_bypass sources are never keyword-filtered at all. Query 1c therefore mixes real keyword misses with queued or failed classifications. The auditor would wrongly diagnose these as keyword gaps.
- **Evidence:** sentinel/database.py:119-121 classification_queue(article_id, attempts, next_attempt_at, last_error); sentinel/scheduler.py:237-242 enqueue then pending_classifications; :255-272 classification_failed keeps the article queued; sentinel/database.py:446 prune skips queued articles; sentinel/scheduler.py:578-582 health.json classification_status
- **Suggested fix:** Amend line 32 and query 1c to exclude queued articles: add `AND a.id NOT IN (SELECT article_id FROM classification_queue)` and keyword_bypass sources. Add a query 1h: `SELECT q.article_id, q.attempts, q.last_error, a.title, a.source_name FROM classification_queue q JOIN articles a ON a.id=q.article_id`. Report these under a separate 'Pending/failed classification' heading, not as MISSED. Also mention health.json classification_status (pending/failed/degraded).
- **Source:** FINDINGS.json #243

### F-072 [MAJOR]

- **Claim:** Keyword Matching Logic (lines 67-75) lists substring vs word-boundary matching and the CRITICAL/HIGH/EXCLUDE levels only.
- **Actual:** The doc omits three behaviours that matter for diagnosing a miss. (1) keyword_bypass sources go straight to the classifier with no keyword check: Defence24, Defence24 EN and all 4 Telegram channels. (2) For every non-English article, the English exclude list is added to that language's excludes. For PL/UK/RU these English excludes match as substrings, so words like 'film', 'game', 'series', 'review' and 'exercise' can exclude Slavic articles. (3) Articles in a language with no keyword section fall back to the English keyword set. Exclude lists exist only for en and pl.
- **Evidence:** sentinel/processing/keyword_filter.py:21-31 _build_bypass_sources, :103-111 bypass in filter_batch, :43-50 fallback to 'en', :63-67 'if lang != "en": exclude_kws = exclude_kws + exclude_lists.get("en", [])', :183-186 substring match for pl/uk/ru; config/config.yaml:318,:359 (Defence24/Defence24 EN keyword_bypass: true), :447-461 (Telegram keyword_bypass: true), :248-290 exclude_keywords en+pl only
- **Suggested fix:** Add these bullets. 'keyword_bypass sources (see sources.rss[].keyword_bypass and telegram.channels[].keyword_bypass in config) skip the filter, so an unclassified article from them is never a keyword miss.' 'Non-English articles are also checked against the English exclude list, by substring for PL/UK/RU. Check English excludes when diagnosing an excluded Slavic article.' 'An unknown language falls back to the English keywords.'
- **Source:** FINDINGS.json #244

### F-073 [MAJOR]

- **Claim:** Known Issues (lines 93-97): 'PAP RSS returns malformed XML', 'TVN24 RSS returns 403 Forbidden', 'GDELT rate-limits (429) on first cycle after restart'. Step 4 (line 247) says zero-article sources may be a 'known issue (PAP, TVN24)'.
- **Actual:** PAP and TVN24 RSS are disabled in config (enabled: false). PAP is blocked by an Incapsula WAF, and its content now arrives through the Google News query 'site:pap.pl'. GDELT is disabled entirely (sources.gdelt.enabled: false). These sources are not configured-but-failing; they are switched off. The list also misses the current known state: the Twilio account is deliberately unfunded, so since 2026-09-21 every call or SMS attempt logs 'Twilio call/SMS failed … 401 … status 4 is not active'. Such failed attempts create no alert_records row, because send_sms/make_call return None. The error-log grep in Step 1 will surface these lines every audit.
- **Evidence:** config/config.yaml:296 PAP 'enabled: false  # Blocked by Incapsula/Imperva WAF…', :301 TVN24 'enabled: false', :396 gdelt 'enabled: false', :436-437 google_news 'site:pap.pl'; sentinel/alerts/twilio_client.py:60-62 and :93-95 log error and return None (no AlertRecord)
- **Suggested fix:** Replace the Known Issues list with the following. 'PAP and TVN24 RSS are disabled in config (PAP comes via Google News site:pap.pl); GDELT is disabled.' 'Twilio account deliberately unfunded since 2026-09-21: every call/SMS fails with HTTP 401 "status 4 is not active". This is a known state, not a finding. Failed attempts leave no alert_records row, so query 1f shows only push records.' Update the Step 4 wording to match.
- **Source:** FINDINGS.json #245

### F-074 [MAJOR]

- **Claim:** Classification Scale (lines 77-83): a generic 1-10 rubric. Examples: '5-6: airspace violation, border provocation, troop movement near border'; '9-10: … Article 5'. Step 3 asks the auditor to judge urgency against it.
- **Actual:** The live classifier scores against policy v2. Its bands are set in config and its precedence rules are in the system prompt. Examples: an official resident air-raid/shelter order scores 9-10 even without a confirmed impact. A Russian military drone with unresolved danger in Poland scores 7-8, and 5-6 in the other monitored countries. Precautionary scrambles score 5-6. Nuclear activity scores 7-8. Ordinary drills score 1-3. Reactions or diplomacy score 2-4. Unclear location scores 2-3. Auditing against the generic scale will flag correct policy-v2 scores as disagreements and miss real policy violations.
- **Evidence:** config/config.yaml:490-539 classification.policy (version: 2, ranges.*); sentinel/classification/policy.py:27-128 system_prompt() ALERT POLICY rules 1-8
- **Suggested fix:** Replace the generic scale with a pointer. 'Judge urgency against the live policy v2: the bands are in classification.policy.ranges in /etc/sentinel/config.yaml (identical to config/config.yaml) and the precedence rules are in sentinel/classification/policy.py system_prompt().' Optionally summarise the bands in a table.
- **Source:** FINDINGS.json #246

### F-075 [MINOR]

- **Claim:** Database section (lines 34-47) lists the articles, classifications and events schemas. Query 1f selects from alert_records, but that schema is not shown, and no other tables are mentioned.
- **Actual:** classifications now also has facts, summary_processing, provider_used, prompt_version, request_hash, response_id, cached_input_tokens, estimated_cost_usd and incident_memory (the decision new/duplicate/update/escalation/uncertain plus matched_event_id). events has notification_revision. alert_records(id, event_id, alert_type phone_call|sms|sms_update|push, twilio_sid, status, duration_seconds, attempt_number, sent_at, message_body, event_revision) is undocumented, as is the classification_queue table. With incident memory enabled, event grouping follows the classifier's incident_memory decision, not only fuzzy matching. That decision is the main evidence for auditing event fragmentation.
- **Evidence:** sentinel/database.py:52-68, :73-88, :93-104, :119-121, :124-134 (_migrate_schema additions); sentinel/classification/schema.py:14-24 incident_memory; sentinel/classification/corroborator.py:98 _find_memory_match
- **Suggested fix:** Update the schema block to the current columns, add alert_records and classification_queue, and note that classifications.incident_memory / facts explain why an article joined or started an event. Optionally add these columns to query 1b.
- **Source:** FINDINGS.json #247

### F-076 [MINOR]

- **Claim:** Examples, 'MISSED — SHOULD flag' (lines 395-397): Defence24 (PL) drone article — 'The keyword "drony" (HIGH, PL) should match via substring. Investigate: was the article excluded by an EXCLUDE keyword?'
- **Actual:** Defence24 is a keyword_bypass source. Its articles never pass through the keyword filter or the EXCLUDE check, so this example teaches an impossible diagnosis. Also, the PL high list contains 'dron', not 'drony' ('dron' matches 'drony' as a substring).
- **Evidence:** config/config.yaml:313-318 Defence24 'keyword_bypass: true'; config/config.yaml PL high list contains '- dron' (keywords.pl.high); sentinel/processing/keyword_filter.py:103-111
- **Suggested fix:** Change the example to a non-bypass source (e.g. RMF24 or Rzeczpospolita) and the keyword to 'dron'. Or add: 'if the source is keyword_bypass, an unclassified article means a classification-queue failure, not a keyword miss'.
- **Source:** FINDINGS.json #248

### F-077 [MINOR]

- **Claim:** Step 0 (lines 105-112): use the timestamp in data/audit-reports/.last-audit-timestamp as {since}. Steps 2-3 say to review EVERY article.
- **Actual:** The local timestamp file contains 2026-04-12T12:00:00Z, although reports exist for 2026-05-01, 05-22 and 05-23. The update step was not applied, and no audit has run since May. Following Step 0 as written would set the window to the full 30-day article retention (articles are pruned after 30 days) and require reviewing tens of thousands of articles. The doc gives no cap or fallback for a stale timestamp.
- **Evidence:** `cat data/audit-reports/.last-audit-timestamp` → 2026-04-12T12:00:00Z; `ls data/audit-reports` shows audit-2026-05-23.md as the latest; config/config.yaml:663 'article_retention_days: 30'
- **Suggested fix:** Add a rule: 'If the timestamp is older than N days (e.g. 3), ask the user for the window or cap it, and note that data older than article_retention_days (30) has been pruned.'
- **Source:** FINDINGS.json #249

## `.claude/skills/dashboard/SKILL.md`

### F-078 [MAJOR]

- **Claim:** Start step 1 (line 23): `pgrep -f "run-dashboard" || pgrep -f "vite.*dashboard"` detects a running dashboard. Close mode (lines 64, 70) kills and verifies with `pkill -f "run-dashboard"`, `pkill -f "vite.*dashboard"` and the same pgrep.
- **Actual:** These patterns do not detect the real processes, and they do match the agent's own shell. (1) run-dashboard.sh ends with `exec "$PYTHON" -m dashboard`, so no process named run-dashboard survives. (2) The Vite process command line is `node …/dashboard/frontend/node_modules/.bin/vite`, where 'dashboard' comes BEFORE 'vite', so 'vite.*dashboard' never matches. (3) The Bash tool runs each command inside `bash -c '<command text>'`, so pgrep/pkill -f match the wrapper shell that contains the pattern literally. Step 1 then always reports 'already running', and the Close-mode pkill can kill its own shell while Vite keeps running.
- **Evidence:** dashboard/run-dashboard.sh:28 'exec "$PYTHON" -m dashboard "$@"'; test run in this session: an emulated process `node /home/kossa/code/project-sentinel/dashboard/frontend/node_modules/.bin/vite` was matched by `pgrep -af "dashboard.*vite"` but NOT by `pgrep -af "vite.*dashboard"`, and both pgrep calls matched the wrapper `/bin/bash -c … eval '…pgrep -af "vite.*dashboard"…'` (pid 939755)
- **Suggested fix:** Detect by port instead: `ss -ltnp | grep -E ':(5001|5173) '` (or `lsof -i :5001 -i :5173`). Stop by PID, e.g. `fuser -k 5001/tcp 5173/tcp`, or use a pattern that cannot match itself, e.g. `pgrep -f "[p]ython -m dashboard"` and `pgrep -f "dashboard/frontend/node_modules/.bin/[v]ite"`.
- **Source:** FINDINGS.json #250

### F-079 [MAJOR]

- **Claim:** Start mode step 3 (lines 40-44): `cd …/dashboard/frontend && npm run dev &`, with no install step.
- **Actual:** dashboard/frontend/node_modules does not exist in the checkout, so `npm run dev` fails ('vite: not found'). dashboard/CLAUDE.md:20 says 'Install once: npm install', but the skill never checks for it.
- **Evidence:** `ls dashboard/frontend/node_modules/.bin/vite` → No such file or directory; dashboard/frontend/package.json scripts.dev = 'vite'
- **Suggested fix:** Add a step before 3: 'If dashboard/frontend/node_modules is missing, run `npm install` in dashboard/frontend first.'
- **Source:** FINDINGS.json #251

### F-080 [MINOR]

- **Claim:** Frontmatter description (lines 4-6): with no arguments it 'syncs the production database, launches Flask backend + Vite dev server, opens Chrome'; with --close it 'kills all dashboard processes and closes the Chrome tab'.
- **Actual:** The body never opens or closes Chrome. Step 4 only reports the URL, and Close mode only kills processes. Auto-open was removed in commit 52a5f9b ('Remove auto-browser-open from /dashboard skill, show URL instead').
- **Evidence:** .claude/skills/dashboard/SKILL.md:48-53 (Report: URL only), :57-75 (no browser step); `git log -- .claude/skills/dashboard/SKILL.md` → 52a5f9b
- **Suggested fix:** Change the description to '…launches Flask backend + Vite dev server and prints the URL' and '--close kills all dashboard processes'.
- **Source:** FINDINGS.json #252

## `README.md`

### F-081 [MAJOR]

- **Claim:** Line 3: "when a corroborated high-urgency threat is detected, alerts via a Twilio phone call and SMS — with an optional Expo push channel for a companion mobile app."
- **Actual:** Three parts of this sentence are wrong against live behavior. First, a single source triggers a call today, because corroboration_required is 1 on both gates. Second, tiers 5-8 are push-only, with SMS switched off by owner decision, and push is enabled and primary rather than optional. Third, 9-10 gets a call, a confirmation SMS and an additive push. The Twilio account is also deliberately unfunded, so calls and SMS currently fail with 401. This is a known state.
- **Evidence:** config/config.yaml:561, :585 (corroboration_required: 1), :590-603 (channel: push), :650-651 (push enabled); sentinel/alerts/state_machine.py:434-459
- **Suggested fix:** Reword: "For urgency 9–10 it places a Twilio phone call (plus confirmation SMS and an app push); urgency 5–8 goes to the companion mobile app as an Expo push. Today a single source is enough to trigger a call." Optionally link the runbook note about the deliberately unfunded Twilio account.
- **Source:** FINDINGS.json #16 (merged with #15, #299)
- **Also reported (duplicate evidence):**
  - #15 (major): config/config.yaml:472 `provider: openai`, :558 `model: gpt-5.6-luna`; sentinel/classification/openai_provider.py
  - #299 (major): config/config.yaml:472,558,585,597,603,650-651

## `docs/README.md`

### F-082 [MAJOR]

- **Claim:** How-to guides section (lines 16-23) lists six how-to guides and presents itself as the documentation index; line 10 says every new doc goes into one of the four Diataxis folders.
- **Actual:** docs/how-to/model-comparison.md exists and nothing links to it. It is missing from docs/README.md, from CLAUDE.md's Docs list, and from every other doc; the only inbound link is from docs/ideas/model-comparison-plan.md. It is the operating recipe for the evaluation-only model comparison (`python -m sentinel.eval.compare_models`). Its own line 3 still says 'Production still uses Haiku', so a blurb added to the index must not repeat that claim.
- **Evidence:** `find docs -type f` lists docs/how-to/model-comparison.md; `grep -rln 'model-comparison.md' . --exclude-dir=node_modules,.venv,.git` returns only docs/ideas/model-comparison-plan.md and a _temp script; docs/how-to/model-comparison.md:3 says 'Production still uses Haiku.'
- **Suggested fix:** Add this bullet under 'How-to guides': '- [how-to/model-comparison.md](how-to/model-comparison.md) — run the offline, evaluation-only comparison of candidate classifier models (fixtures, validation without a key, paid runs). It sends no alerts and does not change production.'
- **Source:** FINDINGS.json #17

### F-083 [MAJOR]

- **Claim:** Reference section (lines 25-29) lists only config-reference.md, sources.md and cli.md, described as 'Dry, exhaustive lookup material'.
- **Actual:** docs/reference/luna-deployment-20260920.md also lives in reference/ and is not indexed. It is not lookup material. It is a dated deployment record of the 2026-09-20 Luna release: tag deploy-20260925 predecessor deploy-20260920-232235, commit 7048a91, backup path, restart time and rollback procedure. Under Diataxis it is a historical record, not reference. The only inbound link comes from docs/how-to/server-runbook.md:18.
- **Evidence:** docs/reference/luna-deployment-20260920.md:1 '# Luna production deployment — 2026-09-20'; its table lists 'Deployment tag | deploy-20260920-232235'; grep shows the only inbound link at docs/how-to/server-runbook.md:18.
- **Suggested fix:** Add a 'Records (dated, not current truth)' section to docs/README.md that lists reference/luna-deployment-20260920.md with this blurb: '2026-09-20 Luna deployment and rollback record. Production has since moved on (currently tag deploy-20260925-143105). Use the runbook for the current state.' Do not move the file, because the runbook links to its current path. If you prefer to keep it under Reference, label it explicitly as a dated record.
- **Source:** FINDINGS.json #18

### F-084 [MAJOR]

- **Claim:** Line 10 says 'When adding a new doc, decide which of these four needs it serves and place it in the matching folder.' The index has only Tutorials, How-to, Reference, Explanation and Archive sections.
- **Actual:** docs/ideas/ holds 14 files and is not mentioned anywhere in the index. They include plans, eval run records, label reviews, a handoff, and design notes for features that are live in production config. Living docs depend on them: config-reference.md:190 links ideas/polish-summary-guard.md and config-reference.md:239 links ideas/incident-memory-plan.md; api-setup.md:86 links ideas/luna-direct-api-migration-plan.md; model-comparison.md links ideas/model-comparison-labels.md and ideas/model-comparison-v2-plan.md. Several files still state superseded status, for example incident-memory-plan.md:3 'not deployed' and classifier-calibration-roadmap.md 'Current state: 50 human-labeled articles'. An agent that finds them has no index entry telling it whether they are current truth.
- **Evidence:** `find docs/ideas -type f` lists 14 files; `grep -n ideas docs/README.md` returns nothing; docs/reference/config-reference.md:190 and :239, docs/how-to/api-setup.md:86, docs/how-to/model-comparison.md:24 and :122.
- **Suggested fix:** Add an 'Ideas, plans and evaluation records' section to docs/README.md that points to docs/ideas/. State that these are dated working notes and evaluation records: they are append-only, not current truth, and the living docs win on any conflict. Optionally list the files that living docs cite (polish-summary-guard.md, incident-memory-plan.md, luna-direct-api-migration-plan.md, model-comparison-*). Also amend line 10 to name docs/ideas/ as the place for plans and records outside the four Diataxis types.
- **Source:** FINDINGS.json #19

### F-085 [MAJOR]

- **Claim:** Line 18: 'how-to/api-setup.md — set up Anthropic, Twilio, and Telegram accounts and credentials.'
- **Actual:** api-setup.md section 1 is 'Direct OpenAI API (Luna)', and the live config selects provider openai with model gpt-5.6-luna. The guide also covers Expo Push (section 3), GDELT (section 5) and Google News RSS (section 6). It has no Anthropic setup section; Anthropic appears only as a legacy key in the .env template. The blurb points an agent at the legacy rollback provider instead of the live one.
- **Evidence:** docs/how-to/api-setup.md:5 '## 1. Direct OpenAI API (Luna)', :152 '## 3. Expo Push', :259 '## 5. GDELT API', :265 '## 6. Google News RSS'; config/config.yaml:472 'provider: openai', :558 'model: gpt-5.6-luna'.
- **Suggested fix:** Change the blurb to: 'set up the direct OpenAI API (Luna, the live classifier), Twilio, Expo Push and Telegram credentials; GDELT and Google News need no setup. Anthropic is legacy/rollback only.'
- **Source:** FINDINGS.json #20 (merged with #300)
- **Also reported (duplicate evidence):**
  - #300 (minor): docs/how-to/api-setup.md:10 'OpenAI mode does not require an Anthropic key'; sentinel/classification/openai_provider.py:123

### F-086 [MINOR]

- **Claim:** Line 34: 'explanation/pipeline.md — step-by-step data flow from source collection to phone alert.'
- **Actual:** Stage 7 of pipeline.md covers push (channel-routed for tiers 5-8, additive on 9-10), the phone call, SMS, post-acknowledgment behaviour and system health alerts. In live operation tiers 5-8 are push-only. Phone calls and SMS currently fail by design because the Twilio account is unfunded, which is a known state. 'To phone alert' suggests the phone call is the only output.
- **Evidence:** docs/explanation/pipeline.md:156 '## Stage 7: Alerts', :158 '### Push Notification (channel-routed for 5–8, additive on 9–10)', :168 '### Phone Call', :186 '### SMS Alert'.
- **Suggested fix:** Change the blurb to: 'step-by-step data flow from source collection through classification and corroboration to alert delivery (push, phone call, SMS).'
- **Source:** FINDINGS.json #21

### F-087 [MINOR]

- **Claim:** Footer (line 43): 'Two living documents stay at the repository root: SPEC.md ... and TODO.md ...'
- **Actual:** The repo root also holds dated, non-living records that the index never mentions: DECISIONS.md (overnight-run decision log for the redesign Phase 1), MOBILE_APP_START_HERE.md (a 2026-06-01 worktree brief that tells the reader to work on branch mobile-push-app and not touch the main repo; that worktree was removed on 2026-06-03), and review_report_pending.md (a Phase 2 review). There are also mobile/PUSH_APP_SPEC.md and mobile/INBOX_APP_SPEC.md. An agent browsing the root may take MOBILE_APP_START_HERE.md as current instructions.
- **Evidence:** `ls *.md mobile/*.md` lists DECISIONS.md, MOBILE_APP_START_HERE.md, review_report_pending.md, mobile/INBOX_APP_SPEC.md, mobile/PUSH_APP_SPEC.md; MOBILE_APP_START_HERE.md:3 'Worktree branch: mobile-push-app ... Created 2026-06-01'.
- **Suggested fix:** Extend the footer with a sentence like: 'Other root and mobile/ files are dated records, not current truth: DECISIONS.md, review_report_pending.md, MOBILE_APP_START_HERE.md (obsolete worktree brief), and mobile/PUSH_APP_SPEC.md and mobile/INBOX_APP_SPEC.md (completed specs; see explanation/mobile-app.md for current behaviour).'
- **Source:** FINDINGS.json #22

## `TODO.md`

### F-088 [BLOCKER]

- **Claim:** (omission) TODO.md has no item about Telegram channel attribution. sources.md:35-44 and pipeline.md:44 say four channels (@kpszsu, @GeneralStaffZSU, @DeepStateUA, @nexta_live) are monitored, each with its own name, language and priority.
- **Actual:** CODE DEFECT: every Telegram message is stored as 'Ukrainian Air Force' with language uk. The fetcher matches str(message.chat_id), which is numeric, against '@username' channel ids, so the match never succeeds. It then falls back to the first configured channel. The URL is built from that wrong channel, so a NEXTA message gets a URL such as t.me/kpszsu/<nexta message id>. Effects: source_name and language are wrong; the links are fake; URL-hash dedup can drop a real message when ids from different channels collide; and all Telegram channels look like one source to corroboration.
- **Evidence:** sentinel/fetchers/telegram.py:96-106 (match on str(message.chat_id) == '@...', then the 'Fallback: use first channel' branch) and :118-119 (source_url built from channel_config.channel_id). Prod DB, read-only query: SELECT source_name,count(*) FROM articles WHERE source_type='telegram' returns only 'Ukrainian Air Force|4422' (2026-09-03 to 2026-10-03), with zero rows for the other 3 channels. 736 of those rows contain Russian-only letters (ы/э/ъ), e.g. https://t.me/kpszsu/124393 '**🚨Во время беспорядков во французском Кане…'. These are NEXTA posts mislabeled as kpszsu. The message-id range 23793-124393 also spans several channels.
- **Suggested fix:** Log as a TODO item: 'Telegram fetcher mislabels every channel as Ukrainian Air Force (chat_id vs @username match falls back to the first channel). Wrong source_name, language and URL; possible cross-channel URL-hash dedup collisions; Telegram channels never count as independent sources.' Also add a Known Issues row to docs/reference/sources.md that points to this TODO item until the code is fixed.
- **Source:** FINDINGS.json #364

### F-089 [MAJOR]

- **Claim:** (No TODO item exists.) Cyrillic titles normalize to empty title_normalized.
- **Actual:** Two Cyrillic-titled articles from different domains get fuzz.ratio('', '') = 100 >= syndication_similarity_threshold 90. _is_independent_source therefore returns False, and UA/RU sources never count as independent corroboration, which affects source_count and the phone-call gate if corroboration is ever raised above 1. In legacy dedup mode, any Cyrillic title would also collide as a cross-source duplicate. This is a code defect.
- **Evidence:** sentinel/models.py:14; sentinel/classification/corroborator.py:322-332; sentinel/processing/deduplicator.py:42-45; grep -i cyrillic TODO.md -> none
- **Suggested fix:** Log as TODO item: '_normalize_title strips all non-ASCII letters, so Cyrillic titles become empty and every UA/RU pair looks 100% syndicated (corroborator independence) / duplicate (legacy dedup).'
- **Source:** FINDINGS.json #39

### F-090 [MAJOR]

- **Claim:** §5 line 225 says `retry_pending` → "Next cycle attempts again". The `_execute_phone_call` docstring says "Never stops until acknowledged". §9 does not mention this.
- **Actual:** `run_cycle` dispatches only events returned by the corroborator in this cycle. No code reloads `retry_pending` or `call_placed` events from the DB. An unacknowledged critical event is called again only when a new article attaches to it in a later cycle; otherwise retries stop after one round (live max_call_retries 1). This is a code/behavior gap, and TODO.md has no item for it.
- **Evidence:** sentinel/scheduler.py:287-306 (events come only from process_classifications); sentinel/alerts/state_machine.py:550-557, 638-645; grep of TODO.md for retry_pending finds only the 2026-05-30 Galați note (TODO.md:12)
- **Suggested fix:** Log as TODO item: unacknowledged `retry_pending` critical events are retried only when a new article joins the event. No scheduled re-call exists, despite the 'Never stops until acknowledged' docstring. Also add a Known Quirks bullet in architecture.md §9 describing the actual retry trigger.
- **Source:** FINDINGS.json #61 (merged with #111)
- **Also reported (duplicate evidence):**
  - #111 (major): sentinel/scheduler.py:298-306 (dispatch(alertable_events) built only from this cycle's corroborator output); sentinel/database.py:376-384 (pending calls = status IN ('initiated','ringing')); sentinel/alerts/state_machine.py:552-557 (docstring), :637-645 (only sets retry_pending); TODO.md has no item on this (grep 'retry' finds only line 12)

### F-091 [MAJOR]

- **Claim:** TODO.md on master has no item about the OpenAI project's own spend cap. The item that recorded it ('still open: ... raise the OpenAI project's own hard cap in the OpenAI dashboard') exists only in commit 945f5f1 on the unmerged branch eval/model-suite.
- **Actual:** Live app allowance is $30 (config/config.yaml). The OpenAI project hard cap was verified at $10 on 2026-09-20 (luna-direct-api-migration-plan.md:134, luna-deployment-20260920.md:44). No record on master shows it was raised. Measured use is ~$11-17/month (commit 31acd3a). If the provider cap is still $10, OpenAI returns project_spend_limit_exceeded and classification pauses mid-month (openai_provider.py:187-188), with articles left pending. That is a missed-alert risk for urgency 9-10.
- **Evidence:** git branch -a --contains 945f5f1 -> eval/model-suite only; grep -n -i 'hard cap|openai project' TODO.md -> no match; sentinel/classification/openai_provider.py:187-188; git show 31acd3a message
- **Suggested fix:** Log as TODO item: 'Verify in the OpenAI dashboard that the Project Sentinel hard spend limit was raised to at least the $30 app allowance (verified at $10 on 2026-09-20); otherwise classification pauses around mid-to-late October.'
- **Source:** FINDINGS.json #131

### F-092 [MAJOR]

- **Claim:** §1 'Approach: Tiered classification pipeline (Haiku → Sonnet → Opus)' (lines 24-59): 'Keep Haiku as the fast/cheap initial classifier', cost table 'Current (Haiku only) ~$2.57', 'All three tiers use the API (ANTHROPIC_API_KEY)'.
- **Actual:** Haiku is no longer the live classifier. Production classifies through OpenAI gpt-5.6-luna with the versioned clarified-v2 policy prompt, a persistent model-usage ledger and a $30 monthly budget. The Anthropic path is legacy/rollback only. The whole §1 plan, its cost table and the ANTHROPIC_API_KEY note describe a retired path, so an agent that picks it up would build tiers on the wrong provider. The auditability requirement is also partly met: classifications now store provider_used, prompt_version, request_hash, response_id, tokens and cost. There is still no tier/pass column.
- **Evidence:** config/config.yaml: classification.provider: openai, model: gpt-5.6-luna, budget.monthly_usd: 30; sentinel/classification/classifier.py:183-215 (OpenAI branch, provider_used='openai', prompt_version 'clarified-v2:...'); sentinel/database.py:125-126 (provider_used/prompt_version columns); commits 0cdb3cb 'Migrate local classification to direct Luna', dbeaaf9 'Record verified Luna production deployment'.
- **Suggested fix:** Mark §1 'Tiered classification pipeline' and its cost table as superseded by the 2026-09 Luna migration. If model escalation is still wanted, restate it against the live provider (gpt-5.6-luna first pass, the escalation model to be decided) with costs from the model-usage ledger. Drop the ANTHROPIC_API_KEY note. Record that the per-call audit fields already exist and that only a tier/pass column is missing.
- **Source:** FINDINGS.json #214 (merged with #298)
- **Also reported (duplicate evidence):**
  - #298 (major): config/config.yaml:472,558; mobile/app.json:43 `"projectId": "d0e215dd-e23f-4d55-a6b1-a919ea75113d"`; config/config.yaml:650-651 push enabled: true; TODO.md:97

### F-093 [MAJOR]

- **Claim:** §1 tier 3 (line 32): 'Before triggering a phone call (urgency 9+, 2+ corroborating sources), run a single Opus 4.6 verification call.'
- **Actual:** Live behaviour places a phone call on ONE source. The critical tier has corroboration_required: 1, and _determine_action returns 'phone_call' when source_count >= level.corroboration_required.
- **Evidence:** config/config.yaml alerts.urgency_levels.critical.corroboration_required: 1 and classification.corroboration_required: 1; sentinel/alerts/state_machine.py:503-507.
- **Suggested fix:** Replace '2+ corroborating sources' with 'one source triggers a call today (critical corroboration_required: 1)', and link the owner-decision item on 1 vs 2 sources.
- **Source:** FINDINGS.json #215

### F-094 [MAJOR]

- **Claim:** §1.0 Task 3 (line 18): the root-cause fix is to edit 'the classifier prompt's R4 POLAND PRIORITY + bare "NATO state = 9" language' by adding an R0 TARGET-COUNTRY GATE and demoting R4.
- **Actual:** The live prompt no longer contains R4 or 'NATO = 9'. Live classification uses policy.system_prompt (policy v2). It has facts-before-policy fields (facts.attack_countries, protection, status). It defines the 9-10 bands only for monitored countries (PL, LT, LV, EE). It says 'Unknown border side must not be silently assigned to Poland', and it confines affected_countries to monitored countries with a concrete local incident. R4 survives only in the legacy Anthropic SYSTEM_PROMPT, which runs only on rollback. Task 3 as written targets dead text; the live gap is the shelter-order defect (separate finding).
- **Evidence:** sentinel/classification/policy.py:27-127 (system_prompt; rules 1-3; 'Unknown border side must not be silently assigned to Poland'); sentinel/classification/classifier.py:63-65 (R4 only in legacy SYSTEM_PROMPT) and 183-189 (OpenAI path uses policy.messages); commit 8c23a5b 'Resolve operator alert policy and freeze reviewed model benchmark' (2026-09-20).
- **Suggested fix:** Rewrite §1.0 Task 3 to say that policy v2 (clarified-v2, live since the Luna rollout) replaced the R1-R10 prompt and removed R4 and 'NATO = 9'. State that R4 remains only in the legacy rollback SYSTEM_PROMPT. Retarget the task at the remaining live misfire class: non-monitored shelter orders scored 9.
- **Source:** FINDINGS.json #216

### F-095 [MAJOR]

- **Claim:** (omission) TODO.md has no item for Ukraine-only shelter/air-raid orders that are classified urgency 9 with empty affected_countries and then attempt a phone call.
- **Actual:** Policy v2 rule 1 gives official_warning 9-10 only to resident orders 'in a monitored country'. Nothing in code enforces that. No post-classification guard ties urgency >= 9 to a non-empty monitored affected_countries list, and _determine_action ignores countries entirely. Also, _countries_compatible requires a shared concrete country for critical articles, so each such empty-country article spawns its own event and its own call attempt. The orchestrator's prod evidence shows events 03ec67e2 (2026-10-02) and f63c6f6d (2026-10-03).
- **Evidence:** sentinel/classification/policy.py:84-87 (rule 1 'in a monitored country'); sentinel/classification/schema.py (no country/urgency constraint); sentinel/alerts/state_machine.py:472-510 (_determine_action uses only urgency_score and source_count); sentinel/classification/corroborator.py:310-312 (critical requires a concrete country intersection, so an empty list never matches).
- **Suggested fix:** Add item: 'Ukraine-only shelter orders scored urgency 9 with affected_countries [] attempt a phone call (events 03ec67e2 2026-10-02, f63c6f6d 2026-10-03). Decide on an eval-gated policy/prompt fix and/or a code guard (no call when urgency >= 9 but no monitored country is in affected_countries). The owner labels the cases.'
- **Source:** FINDINGS.json #217

### F-096 [MAJOR]

- **Claim:** §1.0 Task 2 (line 17): 'Assess current exposure ... confirm whether any single-source path to a PL/9 call is currently open, and whether raising the phone-tier corroboration_required is warranted'.
- **Actual:** The question is already answered in code: the single-source path is open. The critical tier is corroboration_required: 1, and that tier value alone decides the call (_determine_action). classification.corroboration_required only sets the corroborator's alert_status label and does not gate the call. What remains is an owner decision, and TODO.md does not state it as one.
- **Evidence:** config/config.yaml critical.corroboration_required: 1; sentinel/alerts/state_machine.py:503-507; sentinel/classification/corroborator.py:425-443 (_determine_alert_status uses classification.corroboration_required, a status label only); sentinel/scheduler.py:296 (any non-'pending' status is dispatched).
- **Suggested fix:** Replace Task 2 with an explicit owner-decision item: 'One source triggers a phone call today (alerts.urgency_levels.critical.corroboration_required: 1). Owner to decide whether to require 2 independent sources for the critical tier. The tier value, not classification.corroboration_required, is what gates the call.'
- **Source:** FINDINGS.json #218 (merged with #242)
- **Also reported (duplicate evidence):**
  - #242 (minor): config/config.yaml:561 and :585 'corroboration_required: 1'; grep of TODO.md for 'corroboration' finds no such open question

### F-097 [MAJOR]

- **Claim:** (omission) No item about events stuck in alert_status 'retry_pending' placing stale calls once the Twilio account is recharged.
- **Actual:** Verified in code that this can happen, with one limit: retry is not a background sweep. A retry_pending event is re-dispatched only when a later article attaches to it. That happens through an incident-memory duplicate/update/escalation match within lookback_hours 168 of last_updated_at (confidence >= 0.9 for critical), or through an article replay. process_event then re-runs _execute_phone_call. Nothing ever sets alert_status 'expired', and neither process_event nor _execute_phone_call checks event age. Calls that failed with the 401 created no phone_call alert_record (make_alert_call returns None), so the retry-interval guard has nothing to compare against. As a result, after recharge, a follow-up article on an incident up to about 7 days old (chainable, because each match bumps last_updated_at) would ring the phone for a stale event. Until then, each such match makes another failing call plus confirmation-SMS attempt.
- **Evidence:** sentinel/scheduler.py:294-305 (only events returned this cycle are dispatched); sentinel/classification/corroborator.py:186-200 (replay) and 114-145 (_find_memory_match, lookback check), 398 (retry_pending status preserved); sentinel/alerts/state_machine.py:427-428, 571-585 (retry guard keyed on existing phone_call records), 607-609 (record None -> continue), 645 (retry_pending); grep 'expired' shows no writer; sentinel/alerts/twilio_client.py:60-62 (TwilioRestException -> None).
- **Suggested fix:** Add item: 'Before recharging Twilio, review or expire events in retry_pending/call_placed. A later memory-matched article (within 168h) re-runs _execute_phone_call with no age check, so a stale incident can ring the phone. Consider a max-age or expiry rule for call retries.'
- **Source:** FINDINGS.json #219

### F-098 [MAJOR]

- **Claim:** (omission) TODO.md does not list the urgency-9 event fragmentation that the live config itself calls unfixed.
- **Actual:** The live config comments say the urgency-9 country-gate fragmentation in Corroborator._countries_compatible 'is still unfixed, so one incident can still yield multiple events and therefore multiple calls'. max_call_retries was capped at 1 as a workaround after the 2026-07-30 call storm. Incident memory (2026-09-20) still applies the critical concrete-country gate in _find_memory_match, so differing or empty country labels at urgency >= 9 still split one incident.
- **Evidence:** config/config.yaml alerts.urgency_levels.critical comment and acknowledgment.max_call_retries comment; sentinel/classification/corroborator.py:131-137 and 289-315; commits 4353653, 2cad033 (2026-07-30/31).
- **Suggested fix:** Add item: 'Urgency-9 fragmentation: the critical concrete-country gate (_countries_compatible) splits one incident into several events, each with its own call. max_call_retries: 1 is a stopgap; do not raise it until this is fixed.'
- **Source:** FINDINGS.json #220

### F-099 [MAJOR]

- **Claim:** §3 'Mobile app — replace SMS notifications' (lines 76-93): the problem, an undecided approach ('Native app ... vs PWA?', 'FCM/APNs or ... Expo Push?') and 'SMS stays as a fallback'.
- **Actual:** This is done and decided. A React Native/Expo app with Expo push and an in-app inbox is live (inbox LIVE 2026-06-03). Tiers 5-8 were switched to push-only on 2026-06-04, so SMS is deliberately off for them. SMS survives only as the 9-10 call's confirmation-code SMS. The open questions and the '$50/month SMS' premise no longer apply.
- **Evidence:** mobile/app.json, mobile/package.json (Expo app); config/config.yaml high/medium channel: push, push.enabled: true; commit 7c024a5 'Route SMS-tiers 5-8 to push-only (drop Twilio SMS)' (2026-06-04); TODO.md:97 itself says the inbox app went live 2026-06-03.
- **Suggested fix:** Mark §3 as done: native Expo app with Expo push shipped, and 5-8 is push-only by owner decision since 2026-06-04. Remove the PWA/FCM open questions and 'SMS stays as a fallback'. Keep only §3.1 and the iteration-2 dashboard idea, if still wanted.
- **Source:** FINDINGS.json #222

### F-100 [MAJOR]

- **Claim:** §3.1 item 1 (lines 99-105): 'delete that message from the list without opening it'; likely cause: 'the list delete path (store.remove from MessageListScreen / useMessages) doesn't re-run syncBadge'.
- **Actual:** The list screen has no per-message delete. Single-message delete exists only in MessageDetailScreen, which marks the message read on mount. That delete already calls syncBadge(store.unreadCount()) (added by 5d2d979 on 2026-06-03, before the bug was written up). The likely real cause was found and fixed the next day by commit 1c7697b (2026-06-04): undismissed OS tray copies were re-ingested on cold launch, so deleted messages came back as unread. The item's repro, cause and fix direction do not match the code. Its status should be 'fix committed, on-device verification pending'.
- **Evidence:** mobile/src/screens/MessageListScreen.tsx:41 (no remove in list screen); mobile/src/screens/MessageDetailScreen.tsx:106-134 (markRead on mount; remove then syncBadge); commits 5d2d979 (2026-06-03), 550d0b7 (bug doc), 1c7697b 'Dismiss OS tray copy on ingest so deleted inbox messages stay deleted' (2026-06-04).
- **Suggested fix:** Update §3.1 item 1: the delete path already resyncs the badge (5d2d979), and the probable root cause, tray re-ingest of deleted messages, was fixed in 1c7697b (JS-only). The remaining work is to confirm on the device after the next preview build, then close the item.
- **Source:** FINDINGS.json #223

### F-101 [MAJOR]

- **Claim:** §5.2/§5.3 (lines 168-183) frame classifier measurement as unbuilt: 'regular annotation sessions', 'Build or plan metrics that track classification quality', and the commentary says the annotation system 'hasn't been used to measure accuracy'.
- **Actual:** Material omission: a scored eval harness exists (./run.sh --eval, 100%-pass gate). Human-labeled ground truth exists (50 articles labeled by the owner 2026-05-22; reviewed policy-v2 benchmark frozen 2026-09-20). Model-comparison and holdout sets also exist. §5 does not mention any of these, so an agent could rebuild work that is already done.
- **Evidence:** tests/fixtures/eval_set_human.yaml (header: '50 articles labeled by user on 2026-05-22'), tests/fixtures/benchmark_policy_v2.yaml, model_comparison_v2_holdout.yaml; sentinel/eval/harness.py; docs/how-to/testing.md:16; commits 58b4c55, 8c23a5b.
- **Suggested fix:** In §5.2/§5.3, note the existing eval harness, the human-labeled sets and the frozen policy-v2 benchmark (paths above). Restate the open work as extending them, e.g. adding shelter-order and fragmentation cases, instead of building measurement from scratch.
- **Source:** FINDINGS.json #224

### F-102 [MAJOR]

- **Claim:** Omission: TODO.md does not track the unmerged redesign branches or their owner follow-ups. DECISIONS.md:205 says 'Owner follow-ups (all Low/non-blocking) logged to TODO.md'.
- **Actual:** The Phase-1 follow-ups ('## Phase 1 redesign (Alerting reliability) — owner follow-ups (2026-07-12)') and '### 6.0 Alerting reliability & resilience (from the redesign)' exist only in TODO.md on the redesign branches (commit 145a412), not on master. Master's TODO.md has no item asking the owner whether to rebase, merge or abandon the three redesign branches, which master has now diverged from (Luna, incident memory). The Phase-0 rubric gap ('no urgency band for an attack on a non-monitored NATO state', DECISIONS.md:85) is also not tracked on master.
- **Evidence:** git show 145a412 --stat → TODO.md +12 on branch only; git show redesign-phase2-policy:TODO.md | grep '^### 6.0' → line 204; grep '^#' TODO.md (master) → no 6.0 / Phase 1 redesign sections; grep 'non-monitored NATO|_send_system_sms|sweep_max_age' TODO.md → no hits
- **Suggested fix:** Log as TODO item: 'Redesign branches redesign-phase0-geography / -phase1-alerting / -phase2-policy (2026-07-12) are unmerged and master has diverged (Luna, incident memory, push-only). Owner decision: rebase+merge, cherry-pick parts (e.g. Phase-1 bounded retry / durable failure records), or abandon. Their owner follow-ups live only in the branch TODO.md (§6.0 and "Phase 1 redesign owner follow-ups"). Open rubric gap: no band for an attack on a non-monitored NATO state.'
- **Source:** FINDINGS.json #267

### F-103 [MAJOR]

- **Claim:** No TODO item covers the missing acknowledged-event guard in the live incident-memory grouping path.
- **Actual:** Code/safety question. With incident memory enabled (live), _find_memory_match can attach a new critical article to an already-acknowledged critical event when the model says duplicate/update with confidence >= 0.9. No new call is placed. The legacy path forced a NEW event and call in that case (documented as a life-safety invariant). This may be intended (an 'explicit, validated incident identity may suppress'), but the owner never signed off on weakening the invariant in docs.
- **Evidence:** sentinel/classification/corroborator.py:98-144 vs :178-183; .claude/rules/corroboration.md:31-35 'do not weaken it without explicit sign-off'
- **Suggested fix:** Log as TODO item: "Owner decision: incident-memory path (live) lets a ≥0.9-confidence duplicate/update absorb a critical article into an acknowledged critical event with no new call; the legacy acknowledged_at guard does not apply. Confirm intended or restore the guard."
- **Source:** FINDINGS.json #296

### F-104 [MAJOR]

- **Claim:** TODO.md has no item for the broken out-of-band health alert (the 6.1 'Config & deployment bugs' list covers StartLimit, GDELT and other items, but not check-health.sh).
- **Actual:** deploy/scripts/check-health.sh (deployed copy /home/deploy/check-health.sh) uses the removed legacy venv path /home/deploy/sentinel/venv/bin/python, so it never sends its alert. Its only alert channel is Twilio SMS, which is switched off and unfunded. A stalled service would go unnoticed.
- **Evidence:** deploy/scripts/check-health.sh:9; server 'ls /home/deploy/sentinel/venv' → No such file or directory; TODO.md:203-213 (no matching item)
- **Suggested fix:** Log as TODO item: 'check-health.sh points at removed legacy venv (/home/deploy/sentinel/venv/bin/python), so its stale-health SMS never fires; its only channel is Twilio SMS, which is off and unfunded. Owner to decide on a working out-of-band channel (e.g. push) and the venv path fix.'
- **Source:** FINDINGS.json #323 (merged with #195, #213, #345, #196)
- **Also reported (duplicate evidence):**
  - #195 (minor): deploy/scripts/check-health.sh:9; deploy/02-deploy-app.sh:61-69,102; grep -i 'check-health|venv/bin' TODO.md → no hits
  - #213 (major): deploy/02-deploy-app.sh:61-67,121,134; deploy/scripts/check-health.sh:9,23-31; deploy/configs/sentinel.service:11 (.venv); deploy/02-deploy-app.sh:97-104; sentinel/classification/openai_provider.py:123
  - #345 (major): deploy/scripts/check-health.sh:9, deploy/02-deploy-app.sh:121, server /home/deploy/check-health.sh line 9. Server: /home/deploy/sentinel/venv does not exist.
  - #196 (minor): deploy/scripts/check-health.sh:22-31; sentinel/scheduler.py:459-477,554-557

### F-105 [MAJOR]

- **Claim:** TODO.md has no item for the leftover world-readable credential and session files on the production host.
- **Actual:** /home/deploy/sentinel/.env (0644, live-looking Twilio, Anthropic and Telegram keys) and two Telegram session files (0644) in /home/deploy/sentinel and /home/deploy/sentinel.bak-20260324 are readable by any local user. The backup directory sentinel.bak-20260324 is a full stale March checkout.
- **Evidence:** ssh ls -la outputs above; TODO.md grep for '.env|sentinel.bak|session.session' → no matching open item
- **Suggested fix:** Log as TODO item: 'Production host still has world-readable /home/deploy/sentinel/.env and Telegram session files (app dir + sentinel.bak-20260324); owner to decide removal/permission tightening and whether to rotate the exposed credentials.'
- **Source:** FINDINGS.json #325 (merged with #221)
- **Also reported (duplicate evidence):**
  - #221 (major): deploy/configs/sentinel.service: 'EnvironmentFile=/etc/sentinel/sentinel.env' and WorkingDirectory=/home/deploy/sentinel; grep '\.env' TODO.md -> no hit.

### F-106 [MAJOR]

- **Claim:** No TODO item covers the root console session. The runbook SSH Access section (server-runbook.md:47) says 'Emergency (SSH blocked): Hetzner Cloud web console → server → Console tab → login as root' and gives no instruction to log out.
- **Actual:** A root login session on tty1/seat0 has been active since boot (6 months 10 days). Anyone who reaches the Hetzner web console gets a root shell without a password.
- **Evidence:** loginctl list-sessions shows '2  0 root  seat0 tty1 active yes 6 months 10 days ago'. systemctl list-units --state=running includes user@0.service.
- **Suggested fix:** Log as a TODO item asking the owner to log out of the root console session (tty1). In server-runbook.md:47 add: 'Type exit to log out of the console when done; never leave a root console session open.'
- **Source:** FINDINGS.json #355

### F-107 [MINOR]

- **Claim:** (Config comment defect found while auditing alerts.push.) The live config/config.yaml comment says 'Expo's push API is unauthenticated'.
- **Actual:** Production runs with Expo Enhanced Security and a bearer EXPO_ACCESS_TOKEN, so the comment is stale and could lead someone to drop the token. The config.example.yaml comment 'a tier set to push/both still sends SMS only until a token is added' is wrong for `push`, which sends nothing in that case.
- **Evidence:** config/config.yaml:652-654; config/config.example.yaml push comment block; sentinel/alerts/push_client.py:59-60; sentinel/alerts/state_machine.py:426-427
- **Suggested fix:** Log as TODO item: fix the two misleading config comments, in config.yaml (Expo auth) and config.example.yaml (push tier with push disabled delivers nothing).
- **Source:** FINDINGS.json #116

### F-108 [MINOR]

- **Claim:** (code defect found while auditing docs/reference/cli.md `--test-file`)
- **Actual:** `--test-file` crashes with an uncaught AttributeError traceback when the YAML top level is a list. Every eval fixture in the repo has that shape. The command does not print the clean error that the code gives for a missing file or invalid YAML.
- **Evidence:** sentinel.py:328-343 (FileNotFoundError and YAMLError are handled; `data.get(...)` on a list is not)
- **Suggested fix:** Log as TODO item: "--test-file: reject non-mapping YAML (e.g. eval_set.yaml lists) with a clear error instead of an AttributeError traceback."
- **Source:** FINDINGS.json #120

### F-109 [MINOR]

- **Claim:** (missing item) Running the bot locally with the default config.
- **Actual:** Since config/config.yaml became the production-synced file, `./run.sh` with the default --config cannot start locally. It fails on the unset EXPO_PUSH_TOKEN placeholder, and then on the unwritable /var/log/sentinel and /var/lib/sentinel paths. getting-started.md's `cp config/config.example.yaml config/config.yaml` would overwrite the tracked production file. This conflicts with the CLAUDE.md rule 'Run and test locally by default'.
- **Evidence:** config/config.yaml:484, :656, :662, :667; sentinel/config.py:350-357; sentinel/logging_setup.py:28-30; docs/tutorials/getting-started.md:37
- **Suggested fix:** log as TODO item: "Local runs with the default --config fail (prod paths + ${EXPO_PUSH_TOKEN}); decide on a supported local config path (e.g. a git-ignored config/config.local.yaml) and update getting-started/testing docs accordingly."
- **Source:** FINDINGS.json #156

### F-110 [MINOR]

- **Claim:** (Not mentioned) The PushPanel 'OSTATNI PUSH' section is described in docs as a working on-device receipt surface.
- **Actual:** This is a code defect. The OSTATNI PUSH block in PushPanel is dead UI: no caller passes `lastPush`, and `usePushReceiver` is unused. It always shows 'brak (jeszcze nic nie odebrano)', even after pushes arrive, which can mislead the owner into thinking delivery failed.
- **Evidence:** mobile/src/screens/MessageListScreen.tsx:154; mobile/push/PushPanel.tsx:63-73; mobile/push/usePushReceiver.ts:39 (no call sites)
- **Suggested fix:** Log as a TODO item in the mobile post-launch batch: 'PushPanel OSTATNI PUSH is never fed (usePushReceiver unmounted since the inbox rewrite). Either feed it from the store's newest message or remove the section.'
- **Source:** FINDINGS.json #169

### F-111 [MINOR]

- **Claim:** (Not mentioned) Local development setup for the push token.
- **Actual:** This is a template defect. .env.example has no EXPO_PUSH_TOKEN or EXPO_ACCESS_TOKEN line, but the tracked config/config.yaml requires `${EXPO_PUSH_TOKEN}`. A fresh local checkout that follows .env.example therefore cannot load the config: every ./run.sh mode fails with ConfigError.
- **Evidence:** config/config.yaml alerts.push.tokens `- "${EXPO_PUSH_TOKEN}"`; `grep -n EXPO .env.example` → no output; sentinel/config.py:356-360
- **Suggested fix:** Log as a TODO item: 'Add EXPO_PUSH_TOKEN (and a commented EXPO_ACCESS_TOKEN) to .env.example so a fresh checkout can load config/config.yaml.'
- **Source:** FINDINGS.json #172

### F-112 [MINOR]

- **Claim:** §6.1 item 3 (line 208): 'mobile/app.json — placeholder EAS projectId. Ships as all-zeros ... push channel cannot be provisioned end-to-end ... (Push is off by default, so no runtime impact today.)'
- **Actual:** Resolved. app.json carries a real EAS projectId, and push is enabled and live in production.
- **Evidence:** mobile/app.json:43 "projectId": "d0e215dd-e23f-4d55-a6b1-a919ea75113d"; commit 7181f16 'Link EAS project and add expo-dev-client'; config/config.yaml alerts.push.enabled: true.
- **Suggested fix:** Remove §6.1 item 3, or mark it done (resolved by 7181f16).
- **Source:** FINDINGS.json #225 (merged with #173)
- **Also reported (duplicate evidence):**
  - #173 (minor): mobile/app.json extra.eas.projectId; git log 7181f16; config/config.yaml `push: enabled: true`

### F-113 [MINOR]

- **Claim:** (omission) §2 'Source health analysis' is generic and lists no currently dead RSS feeds.
- **Actual:** Only PAP and TVN24 are visibly disabled in config. The orchestrator's prod log audit reports enabled RSS feeds that fail every cycle. TODO.md does not name them, so the dead feeds keep running unflagged. The feed names cannot be verified from the repo in this no-network run.
- **Evidence:** config/config.yaml sources.rss (PAP enabled: false, TVN24 enabled: false; all others enabled: true); TODO.md:63-72 (no specific feed named).
- **Suggested fix:** Add a §2 sub-item listing each enabled RSS feed that fails every cycle (name, error class, first-seen date, from the server log census), with a disable/replace decision per feed.
- **Source:** FINDINGS.json #227

### F-114 [MINOR]

- **Claim:** §4.1 item 2 (line 120) 'Event deduplication window (our 6-hour corroboration window vs custom)' and §4.3 (line 148) 'Corroboration window (6h default ...)'.
- **Actual:** With incident_memory.enabled: true (live), grouping no longer uses the 6-hour corroboration_window_minutes fuzzy matcher (_find_matching_event). It uses model identity decisions over a 168-hour memory lookback (_find_memory_match).
- **Evidence:** config/config.yaml classification.incident_memory.enabled: true, lookback_hours: 168; sentinel/classification/corroborator.py:83 (memory_enabled -> _find_memory_match), 114-145.
- **Suggested fix:** Change the window wording to say that live grouping uses incident memory (168h lookback, model decision). corroboration_window_minutes (6h) applies only when incident memory is disabled.
- **Source:** FINDINGS.json #228

### F-115 [MINOR]

- **Claim:** 'Commentary: Priority & sequencing (Claude's assessment, 2026-05-24)' (lines 214-230): priority order 5 → 1 → 2 → 3 → 4 → 6; '#1 ... Sonnet/Opus verification. Cost is negligible (+$1.13/mo)'; '#3 — try PWA first, not a native app'; the annotation system 'sitting unused'.
- **Actual:** Its premises are superseded. The classifier is now Luna on OpenAI, the native Expo app shipped instead of a PWA, and human-labeled eval sets exist. A reader could take this ordering as the current plan.
- **Evidence:** config/config.yaml classification.model: gpt-5.6-luna; mobile/ Expo app (inbox live 2026-06-03); tests/fixtures/eval_set_human.yaml.
- **Suggested fix:** Add a dated note above the commentary: '[2026-10-03] Superseded in part: #3 shipped as a native Expo app; the #1 Haiku-tier cost figures predate the Luna migration; human-labeled eval sets now exist. Re-rank before acting on it.'
- **Source:** FINDINGS.json #229

### F-116 [MINOR]

- **Claim:** (No item exists.) dashboard/CLAUDE.md:14 and the dashboard skill describe `--sync` as pulling a fresh copy of the production DB.
- **Actual:** The production DB runs in WAL mode, and sync SCPs only sentinel.db (no -wal file and no sqlite .backup). Writes not yet checkpointed into the main file are missing from the synced copy. The copy can therefore lag the live DB.
- **Evidence:** sentinel/database.py:25 'PRAGMA journal_mode=WAL'; dashboard/config.py:59 REMOTE_DB_PATH='/var/lib/sentinel/sentinel.db'; dashboard/sync.py:56-63 plain `scp` of that one file; `grep -n wal dashboard/sync.py` → no matches
- **Suggested fix:** Log as TODO item: 'Dashboard --sync copies only sentinel.db from a WAL-mode DB; consider `sqlite3 … ".backup"` on the server (read-only) or copying -wal too so the synced copy includes recent writes.'
- **Source:** FINDINGS.json #255

### F-117 [MINOR]

- **Claim:** Omission: dashboard defects found while auditing SPEC.md are not tracked.
- **Actual:** (1) The dashboard ignores classification_queue, so queued or failed articles show as 'Unclassified (filtered out before classification stage)'. (2) Its classifier_input shows the legacy Haiku prompt block, not the Luna JSON payload. (3) The `push` alert_type has no icon or label and is missing from the TS union. (4) The language filter lacks `ru`. The dashboard has had no commits since 2026-05-30.
- **Evidence:** dashboard/ (grep classification_queue → none); dashboard/classifier_input.py vs sentinel/classification/policy.py:177-193; dashboard/frontend/src/types.ts:112; dashboard/frontend/src/components/FilterBar.tsx:51; git log -- dashboard/ → last df4f6ea 2026-05-30
- **Suggested fix:** Log as TODO item (dashboard, low priority): 'Dashboard lags the Luna/incident-memory schema. It should show the classification_queue pending/failed state instead of "filtered out". It should render the Luna policy.messages() payload as classifier input (or label the current block legacy). Add `push` to the AlertRecord.alert_type union and the EventTimeline icon map. Add `ru` to the language filter. Optionally surface provider_used/prompt_version/estimated_cost_usd.'
- **Source:** FINDINGS.json #268 (merged with #254)
- **Also reported (duplicate evidence):**
  - #254 (minor): dashboard/classifier_input.py:3-6; sentinel/classification/policy.py:136-152; dashboard/frontend/src/__tests__/fixtures.ts:29

### F-118 [MINOR]

- **Claim:** The v2 run record ('Post-freeze annotation limitations', lines 156-183) says: 'Before future reuse, correct those annotations in a new version' (35 narrow numeric ranges, 14 unsupported `active` status labels). The holdout review asks for v2h-en-01-c to be rewritten and re-reviewed. TODO.md has no item for either.
- **Actual:** The holdout fixture is unchanged: its sha256 still equals the frozen 47fc04cf…. It keeps 16 exact-9 and 8 exact-10 ranges, and v2h-en-01-c is still disputed. It has been reused since: the runtime replay, sentinel/eval/direct_luna.py:31, tests/test_direct_openai.py:249, and the 2026-09-23 GPT-6 holdout runs (data/eval/gpt6-holdout-r*.json). No TODO tracks the correction, so future exact-urgency or status comparisons on it remain unfair.
- **Evidence:** sha256sum tests/fixtures/model_comparison_v2_holdout.yaml = 47fc04cfebd51da3354f262e7610b407929342dc15326277dc75b273e3dd1b17; range counts {(9,9):16,(10,10):8}; grep TODO.md for holdout/annotation → no item; data/eval/gpt6-holdout-r1..r3-20260923.json
- **Suggested fix:** Log as TODO item: 'Create model_comparison_v2_holdout v2 (new file, keep the frozen one): widen the 35 unsupported narrow urgency ranges, re-review the 14 status labels listed in docs/ideas/model-comparison-v2-run-record.md, rewrite v2h-en-01-c; until then, do not rank models on exact urgency or status with this fixture.'
- **Source:** FINDINGS.json #278

### F-119 [MINOR]

- **Claim:** (Code/config defect found while auditing docs/ideas/model-runtime-comparison-20260920.md.) config/config.yaml:539 comment: '# Local Luna uses the evaluated memory path. Production rollout is separate.'
- **Actual:** config/config.yaml is byte-identical to the production /etc/sentinel/config.yaml. incident_memory.enabled: true has been live since the 2026-09-20 deployment, so the comment wrongly suggests that memory is local-only.
- **Evidence:** config/config.yaml:539-541; git log 0cdb3cb (enabled false→true); tag deploy-20260920-232235; run context: server config identical to repo config
- **Suggested fix:** Log as TODO item: 'Update the stale comment at config/config.yaml:539. Incident memory is live in production since 2026-09-20; the comment implies it is local-only.'
- **Source:** FINDINGS.json #279

### F-120 [MINOR]

- **Claim:** No TODO item covers dead alert config keys.
- **Actual:** Several keys are defined, set in live config and documented as behavior, but no runtime code reads them: alerts.urgency_levels.*.retry_attempts (live critical: 3), .fallback (live critical: sms), and alerts.acknowledgment.cooldown_hours (live 6; config-reference says 'No re-call for same event within this window'). The cooldown helpers named in architecture.md (_is_in_cooldown, _user_already_notified, _last_alert_time) do not exist. Also, config/config.example.yaml still ships max_call_retries: 5, the value that caused the 2026-07-30 call storm (live 1).
- **Evidence:** grep -rn 'retry_attempts\|cooldown_hours' sentinel/ -> only sentinel/config.py:98,100,120; grep '_is_in_cooldown\|_user_already_notified\|_last_alert_time' sentinel/ -> no hits; docs/explanation/architecture.md:328; docs/reference/config-reference.md:294; config/config.example.yaml:649 `max_call_retries: 5`; config/config.yaml:640-647
- **Suggested fix:** Log as TODO item under §6.1: "Dead config: retry_attempts, fallback, cooldown_hours are parsed but never read; config.example.yaml max_call_retries 5 (storm value) vs live 1." Fix the docs that describe them as behavior (config-reference L256-261/L294, architecture L328).
- **Source:** FINDINGS.json #297 (merged with #226)
- **Also reported (duplicate evidence):**
  - #226 (minor): sentinel/config.py:98-100, 120 (only definitions); grep for '.fallback', '.retry_attempts', 'cooldown_hours', 'level.retry_interval_minutes' in sentinel/ and sentinel.py finds no reader; config/config.yaml critical: retry_attempts: 3, fallback: sms; acknowledgment.cooldown_hours: 6.

### F-121 [MINOR]

- **Claim:** (Repo hygiene; no doc covers it.) .gitignore lists .code-refiner-state, -phase1/2/3, -spec-phase4 and -inbox-phase1/2/3.
- **Actual:** Two tool-state directories, .code-refiner-state-redesign-phase0/ and .code-refiner-state-redesign-phase2/, are committed to the public repo (finding registries and diagnostics JSON) and are missing from .gitignore. data/ is gitignored, yet 6 audit reports plus .last-audit-timestamp under data/audit-reports/ are tracked while 6 newer ones are ignored. That makes /sentinel-audit output inconsistently versioned.
- **Evidence:** git ls-files .code-refiner-state-redesign-phase0 -> config.json, diagnostics.json, ...; .gitignore:1-35 (no redesign entries); git ls-files data/audit-reports vs git status --ignored ('!! data/audit-reports/audit-2026-03-25.md' ... '05-23.md')
- **Suggested fix:** Log as TODO item: untrack .code-refiner-state-redesign-phase0/2 and add them to .gitignore. Decide whether data/audit-reports/*.md are versioned (then track them all) or local (then untrack them all).
- **Source:** FINDINGS.json #316

### F-122 [MINOR]

- **Claim:** No TODO item covers the shadowed fail2ban override.
- **Actual:** /etc/fail2ban/jail.d/whitelist.conf sets [sshd] maxretry=5 and bantime=3600 'instead of 3 retries, 24h ban'. That intent never takes effect, because jail.local overrides jail.d/*.conf. Only its [DEFAULT] ignoreip works.
- **Evidence:** whitelist.conf (Mar 24 2026) vs jail.local (Mar 23 2026). The live 'fail2ban-client get sshd maxretry' returns 3 and 'bantime' returns 86400.
- **Suggested fix:** Log as a TODO item asking the owner which sshd ban policy is intended (3 tries / 24 h with escalation, or 5 tries / 1 h). Then move the chosen [sshd] values to a file that actually wins (jail.local or jail.d/*.local).
- **Source:** FINDINGS.json #352

### F-123 [MINOR]

- **Claim:** (omission) The daily summary log line is expected to report the previous day's totals. No doc describes it, and TODO.md has no item about it.
- **Actual:** CODE DEFECT: '=== Daily summary: cycles=1 … ===' always reports cycles=1 and only the first cycle's numbers. Pipeline stats reset at the first cycle of the new UTC day, and _maybe_log_daily_summary reads them only after that reset. The real day has about 576 cycles (~480 fast + ~96 full).
- **Evidence:** sentinel/scheduler.py:101-113 (reset on date change inside record_success) and :605-618 (summary logged at rollover, reading get_daily_summary()). Logs: '2026-10-03 00:01:28 sentinel.scheduler: === Daily summary: cycles=1, articles_processed=221, events_detected=0, alerts_sent=0 ===', and every day 09-26 to 10-03 shows cycles=1. Census: 3506 FAST plus 710 FULL cycle starts in about 7.5 days.
- **Suggested fix:** Log as TODO item: 'Daily summary line reports only the first cycle of the new day (cycles=1): stats are reset before the rollover summary is logged.'
- **Source:** FINDINGS.json #376

## `SPEC.md`

### F-124 [MAJOR]

- **Claim:** Req 1.5a: the `classifier_input` field is 'the reconstructed text that was sent to the classifier' in a 5-line Source/Language/Published/Title/Summary block, and 'This reconstruction matches the format used by sentinel/classification/classifier.py'. Req 3.8 calls it 'the reconstructed text sent to Claude'.
- **Actual:** The live classifier is OpenAI gpt-5.6-luna. On that path classifier.classify() does not use the 5-line USER_PROMPT_TEMPLATE. It calls policy.messages(), which sends a JSON object (evaluation_time, article{title, summary, source_name, source_type, language, published_at}, remembered_incidents) plus a policy-built system prompt. It appends no enrichment caution note. The dashboard's dashboard/classifier_input.py still rebuilds only the legacy Anthropic-path block, so the dashboard shows a reconstruction of the rollback path, not what the live model saw.
- **Evidence:** sentinel/classification/classifier.py:164 (provider selected when classification.provider == 'openai'); classifier.py:178-183 (openai branch calls messages(article, incident_context, cfg.policy)); sentinel/classification/policy.py:177-193 (messages() builds a JSON user payload); classifier.py:299-321 (_build_user_prompt / 5-line template used only on the Anthropic branch); dashboard/classifier_input.py:1-30; dashboard/frontend/src/components/ClassifierView.tsx:4 ('the verbatim text sent to Claude')
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Since the Luna migration (commit 0cdb3cb, 2026-09-20) the live classifier is OpenAI gpt-5.6-luna. It receives a JSON payload built by sentinel/classification/policy.py:messages() (evaluation_time, article fields, remembered_incidents), not this 5-line block. `classifier_input` still reproduces only the legacy Anthropic/Haiku rollback prompt (classifier.py:_build_user_prompt), so it is NOT what the live model saw.' above requirement 1.5a, and a one-line pointer to it above 3.8.
- **Source:** FINDINGS.json #258

### F-125 [MAJOR]

- **Claim:** Pipeline Stage Context: 'No classification row → unclassified (filtered out before classification)'. Req 3.8b: an article with no classification shows 'This article was not classified (filtered out before classification stage)'.
- **Actual:** Keyword-selected articles are now written to a `classification_queue` table first. An article that passed the keyword filter but whose classification is still pending or has failed (OpenAI budget cap, quota, timeout) has no `classifications` row. The dashboard therefore labels it 'Unclassified' and says it was filtered out, which is false. The dashboard code has no reference to classification_queue.
- **Evidence:** sentinel/database.py:119-121 (classification_queue table); sentinel/scheduler.py:236-242 (enqueue after keyword filter, then pending_classifications); scheduler.py:255-259 (classification_failed keeps the article queued); grep 'classification_queue' dashboard/ → no hits; dashboard/frontend/src/components/ClassifierView.tsx:46
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Since the Luna migration, keyword-selected articles wait in `classification_queue` until they are classified. An article with no `classifications` row may be queued or failed (for example, budget exhausted), not filtered out. The dashboard does not read this table yet, so it labels such articles "Unclassified / filtered out". See TODO.md.' above the 'Pipeline Stage Context' section.
- **Source:** FINDINGS.json #259

### F-126 [MAJOR]

- **Claim:** Production Database Schema and Pipeline Stage Context: `classifications.model_used -- "claude-haiku-4-5-20251001"`; stage 5 'Classified — Sent to Claude Haiku'; stage 7 'Alert sent — SMS/call dispatched via Twilio'; the schema lists only the 4 original tables and their original columns.
- **Actual:** The live classifier is gpt-5.6-luna (provider openai); Haiku is the rollback path only. The schema now has more columns. Classifications has facts, summary_processing, provider_used, prompt_version, request_hash, response_id, cached_input_tokens, estimated_cost_usd and incident_memory. Events has notification_revision, alert_records has event_revision, and there is a new classification_queue table. Tiers 5-8 are push-only (Expo), so most new alert records are `push`, not Twilio SMS. Since 2026-09-21 every Twilio call and SMS fails with HTTP 401 because the account is deliberately unfunded (a known state).
- **Evidence:** sentinel/database.py:52-68, 73-87, 93-104, 119-139 (_create_tables + _migrate_schema additions); sentinel/classification/classifier.py:164,203-205 (model_used=cfg.model, provider_used='openai'); sentinel/alerts/state_machine.py:432-435 (per-tier sms/push/both)
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Live classifier = OpenAI gpt-5.6-luna (Haiku = rollback only); `model_used` now holds e.g. "gpt-5.6-luna". The schema below predates incident memory and the Luna migration. See sentinel/database.py:_create_tables/_migrate_schema for the added columns (facts, provider_used, prompt_version, estimated_cost_usd, incident_memory, notification_revision, event_revision) and the classification_queue table. Tiers 5-8 are push-only, so new alert records are mostly `push`. Twilio calls/SMS currently fail by design (account deliberately unfunded since 2026-09-21).' above the 'Production Database Schema' section.
- **Source:** FINDINGS.json #260

### F-127 [MINOR]

- **Claim:** Req 3.9: alert records show 'alert type (SMS/call/WhatsApp icon)'. The note at lines 126-131 says the runtime writes `push` rows and that the dashboard keeps an icon for legacy `whatsapp` rows.
- **Actual:** Push is now the main channel for tiers 5-8, but the dashboard has no push icon or label. The TypeScript type `alert_type` is `"sms" | "phone_call" | "whatsapp"`, so push rows fall back to a bare '•' and the raw string 'push'. Requirement 3.9 never added push.
- **Evidence:** dashboard/frontend/src/types.ts:112; dashboard/frontend/src/components/EventTimeline.tsx:21-31,107-113 (fallback '•'); sentinel/alerts/state_machine.py:412,435 (push records written)
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** `push` is now the main alert_type for tiers 5-8. The dashboard has no push icon or label and no `push` in the `AlertRecord.alert_type` TS union; it renders a generic "•". See TODO.md.' above requirement 3.9.
- **Source:** FINDINGS.json #261

### F-128 [MINOR]

- **Claim:** Status banner (lines 3-8): the event-grouping behaviour of the archived SPEC_ALERT_GROUPING 'is now reflected here and in the living docs under docs/explanation/'.
- **Actual:** SPEC.md does not describe event grouping. It has no per-row `event_id`, no `/events/:id` route or EventDetailPage, no `GET /api/events/<event_id>` endpoint (dashboard/api/events.py) and no EVENT_ID_RETENTION_DAYS. Those are documented only in docs/explanation/architecture.md and dashboard/CLAUDE.md.
- **Evidence:** grep 'event_id|/events|EventDetail|retention' SPEC.md → only line 115 (alert_records FK) and banner; dashboard/api/events.py:20; dashboard/frontend/src/pages/EventDetailPage.tsx; docs/explanation/architecture.md:348
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Correction: event-grouping (per-row `event_id`, `/events/:id` page, `GET /api/events/<event_id>`, `EVENT_ID_RETENTION_DAYS`) is NOT specified in this file. It is documented in docs/explanation/architecture.md and dashboard/CLAUDE.md.' directly below the existing status banner.
- **Source:** FINDINGS.json #262

### F-129 [MINOR]

- **Claim:** articles.language comment `"pl" | "en" | "uk"`; req 2.4 language dropdown 'all/pl/en/uk'.
- **Actual:** An enabled Telegram source (NEXTA Live, language ru) has been in config since 2026-03-26, so `ru` articles can exist. The dashboard language filter offers only pl/en/uk, so ru articles cannot be filtered by language.
- **Evidence:** config/config.yaml:458-462 (NEXTA Live, language: ru; telegram enabled: true at :441); git log -S nexta_live → 9d60198 2026-03-26; dashboard/frontend/src/components/FilterBar.tsx:51
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** `language` can also be `ru` (Telegram NEXTA Live). The FilterBar dropdown lacks it.' above requirement 2.4, and include it in the dashboard TODO item.
- **Source:** FINDINGS.json #263

## `mobile/PUSH_APP_SPEC.md`

### F-130 [MINOR]

- **Claim:** No status banner; the spec reads as pending ('When complete…'). It contains several normative claims. 'Token entry stays manual copy-paste into config.yaml' (Non-Goals, line 31). AD-3 and Technical Context lines 67-71 say the `is_update` dedup-bypass branch of `_maybe_send_push` 'MUST be retained'. Phase 3 (3.4, App.tsx deliverable) says PushPanel shows the last received push via `usePushReceiver` wired in App.tsx. Technical Context says config.yaml omits the push block, and that app.json has the placeholder projectId.
- **Actual:** All three phases were merged and are live since deploy-20260603-114957, with the push-only routing posture deployed 2026-06-04. Several normative points have since drifted. The token is now `${EXPO_PUSH_TOKEN}` from sentinel.env, not a literal in config.yaml (6621a40, 2026-06-04). Since 8864861 (2026-09-20, live) push dedup is per notification revision (`_channel_delivered(..., 'push', event.notification_revision)`), and updates no longer bypass dedup; they push once per new revision. The inbox rewrite (20b74f2) removed `usePushReceiver` from App.tsx, so requirement 3.4's panel is no longer fed. app.json now has a real projectId (7181f16).
- **Evidence:** `git tag --contains 4e9441b` → deploy-20260603-114957; sentinel/alerts/state_machine.py:849-853 (revision dedup), 409-413; tests/test_state_machine.py:1233-1246 (now 'fires for a newer notification revision'); `git log -S EXPO_PUSH_TOKEN -- config/config.yaml` → 6621a40; mobile/src/screens/MessageListScreen.tsx:154
- **Suggested fix:** Add above '## Overview': '> **[AMENDMENT 2026-10-03]** Implemented and live since deploy-20260603-114957; tiers 5-8 run channel: push since 2026-06-04. Superseded points: the token comes from EXPO_PUSH_TOKEN in sentinel.env (config.yaml holds `${EXPO_PUSH_TOKEN}`, never a literal); push dedup is per notification revision since 2026-09-20 (8864861), so there is no is_update bypass; the 3.4 last-push panel is no longer fed after the inbox rewrite (see INBOX_APP_SPEC.md); app.json has a real EAS projectId since 2026-06-02.'
- **Source:** FINDINGS.json #180

## `mobile/INBOX_APP_SPEC.md`

### F-131 [MINOR]

- **Claim:** No status banner; the spec reads as pending ('When complete…'). Requirement 1.4 (lines 239-243) mandates preserving 'the existing record-presence dedup [that] suppresses a re-push when a prior push AlertRecord exists … an is_update=True update still pushes (bypassing the dedup)'.
- **Actual:** All three phases were merged to master and are live since deploy-20260603-114957 (20b74f2 and the follow-up commits are in that tag). The 1.4 dedup contract was later replaced. Since 8864861 (2026-09-20, live in deploy-20260920-232235 and later), `_maybe_send_push` dedups only on a successful push for the current `notification_revision`. Updates no longer bypass dedup, and a failed push stays retryable. The payload contract in Appendix A still matches `_build_push_data` (3500-byte budget, trim order sources → sms_body → summary_pl, PUSH_BODY_SUMMARY_MAX_CHARS = 80).
- **Evidence:** `git tag --contains 20b74f2` → deploy-20260603-114957; sentinel/alerts/state_machine.py:73, 301-371, 849-853; `git log -S 'def _channel_delivered'` → 8864861 2026-09-20
- **Suggested fix:** Add above '## Overview': '> **[AMENDMENT 2026-10-03]** Phases 1-3 implemented and live since deploy-20260603-114957. Requirement 1.4\'s record-presence dedup / is_update bypass was replaced on 2026-09-20 (8864861) by per-notification-revision dedup: one successful push per revision, failed pushes retry. Appendix A payload contract unchanged.'
- **Source:** FINDINGS.json #181

## `docs/tutorials/getting-started.md`

### F-132 [BLOCKER]

- **Claim:** Step 4 'Configure Application': `cp config/config.example.yaml config/config.yaml`; and the table 'Files NOT Committed to Git' lists `config/config.yaml | Your active configuration`.
- **Actual:** config/config.yaml is a TRACKED file and is the production config: /deploy copies it to /etc/sentinel/config.yaml (byte-identical today). It is listed in .gitignore, but that has no effect on a tracked file. Following step 4 overwrites the production config in the working tree with the template (17 RSS feeds instead of 20, GDELT on, push off, 5-8 tiers on `both`, $10 budget, relative paths). A later commit and deploy would ship that to the server.
- **Evidence:** `git ls-files config/` prints config/config.example.yaml and config/config.yaml; .gitignore line 'config/config.yaml'; config/config.yaml:465 session_name /var/lib/sentinel/sentinel_session, :484 ledger_path /var/lib/sentinel/model-usage.db, :662 path /var/lib/sentinel/sentinel.db; commit 6429124 message ('/deploy copies config/config.yaml to /etc/sentinel/config.yaml')
- **Suggested fix:** Replace step 4 with: 'Do not overwrite config/config.yaml. It is tracked and is the production config that /deploy copies to the server. For a local run, use the template directly (`./run.sh --config config/config.example.yaml --once --dry-run`), or copy it to an ignored path such as `data/config.local.yaml` and pass that with `--config`.' Remove `config/config.yaml` from the 'Files NOT Committed' table and add a note that it is tracked and production-matching.
- **Source:** FINDINGS.json #136

### F-133 [MAJOR]

- **Claim:** Header note: 'For obtaining Twilio / Anthropic / Telegram credentials'. Step 3: 'Fill in credentials for Twilio, Anthropic, and Telegram.'
- **Actual:** Both config.example.yaml and the live config select `provider: openai` with `gpt-5.6-luna`. A newcomer must fill in OPENAI_API_KEY from a funded OpenAI API project. With the .env.example placeholder left in place, every classification fails with an auth error and articles stay pending. Classification still runs during a dry run. The Anthropic key is only needed for the legacy rollback.
- **Evidence:** config/config.example.yaml:497 `provider: openai`, :584 `model: gpt-5.6-luna`; sentinel/classification/classifier.py:164; sentinel/classification/openai_provider.py:123-128,186-187; .env.example:9-13
- **Suggested fix:** Replace 'Anthropic' with 'OpenAI (OPENAI_API_KEY, paid API project; see API Setup §1)' in both places. Mention that ANTHROPIC_API_KEY is only for the legacy rollback.
- **Source:** FINDINGS.json #138 (merged with #308)
- **Also reported (duplicate evidence):**
  - #308 (minor): config/config.yaml:472, :597, :603, :650-651; config/config.example.yaml:631,637,669

### F-134 [MAJOR]

- **Claim:** Prerequisites: 'Python 3.10+'.
- **Actual:** The code needs Python 3.11 or newer. 17 modules use `from datetime import UTC`, which was added in 3.11. openai_provider.py uses `asyncio.timeout`, also new in 3.11. pyproject.toml sets ruff `target-version = "py311"`. On 3.10 the import fails before anything runs.
- **Evidence:** sentinel/alerts/twilio_client.py:3 `from datetime import UTC, datetime`; `grep -rln 'from datetime import.*UTC' sentinel/ | wc -l` = 17; sentinel/classification/openai_provider.py:178; pyproject.toml target-version py311; local .venv is Python 3.12.3
- **Suggested fix:** Change the prerequisite to 'Python 3.11+'.
- **Source:** FINDINGS.json #139

### F-135 [MAJOR]

- **Claim:** Steps 3-5 go straight from filling in credentials to `./run.sh --once --dry-run`, with no Telegram step.
- **Actual:** config.example.yaml ships `telegram.enabled: true` with `session_name: sentinel_session`. With no session file, TelegramFetcher.start() calls telethon `client.start()`. In an interactive terminal that call stops the dry run to ask for a phone number and a login code. With the .env.example placeholder api_id it fails, and the error is logged. A newcomer either has to do the one-time authentication from API Setup §4 first, or set `sources.telegram.enabled: false` in their local config.
- **Evidence:** config/config.example.yaml:458 telegram enabled: true, :482 session_name: sentinel_session; sentinel/fetchers/telegram.py:48-53 `await self.client.start()`; sentinel/scheduler.py:189-196 (startup awaits fetcher.start); sentinel.py:115-122 (run_once calls startup)
- **Suggested fix:** Add a step before 'Verify Setup': 'Telegram is enabled in the template. Either run the one-time Telegram authentication in API Setup §4 (it creates sentinel_session.session), or set sources.telegram.enabled: false in your local config. Otherwise the first run stops at a phone-number prompt.'
- **Source:** FINDINGS.json #141

### F-136 [MINOR]

- **Claim:** Step 5/6: `./run.sh --once --dry-run  # single cycle, no alerts sent` / 'dry run: pipeline without alerts'; CLI table: '--dry-run | Don't send Twilio alerts, log only'.
- **Actual:** Dry run suppresses all alert delivery, push included, because AlertDispatcher logs instead of sending. It still runs the paid OpenAI classifier and the quality gate, and it writes to the budget ledger and the database. A newcomer's 'working dry run' therefore needs a funded OpenAI key and spends real model money. The doc does not say so. The `--eval` flag is also missing from the CLI table, although `--help` lists it.
- **Evidence:** sentinel/alerts/dispatcher.py:14,46-47 (dry_run only gates dispatch); sentinel/scheduler.py:157,253,276 (enricher/classifier still run); sentinel/processing/enricher.py:80-97 (OpenAI quality gate); `./run.sh --help` shows `--eval [PATH]`
- **Suggested fix:** Reword `--dry-run` as 'Suppress all alert delivery (Twilio and push), log only. Classification still makes paid OpenAI calls.' Add a sentence under step 5 saying the dry run needs a funded OPENAI_API_KEY and costs a few cents. Add the `--eval [PATH]` row (live API, CI gate).
- **Source:** FINDINGS.json #140

### F-137 [MINOR]

- **Claim:** Step 4 key settings: 'RSS sources -- ~20 feeds preconfigured (...); PAP and TVN24 ship disabled (`enabled: false`)' and 'GDELT is disabled in production'.
- **Actual:** These describe the live config/config.yaml (20 feeds, PAP and TVN24 disabled, GDELT off). The template the tutorial copies has 17 feeds with only PAP disabled. TVN24 is enabled there, and so is GDELT, so a local run from the template polls GDELT.
- **Evidence:** python yaml load: config/config.example.yaml rss=17, disabled=['PAP'], gdelt.enabled=True; config/config.yaml rss=20, disabled=['PAP','TVN24'], gdelt.enabled=False
- **Suggested fix:** Describe the template: '17 feeds; PAP ships disabled; GDELT is enabled in the template but disabled in production (IP throttling).' Optionally add: 'production config/config.yaml has 20 feeds with PAP and TVN24 disabled'.
- **Source:** FINDINGS.json #142

## `docs/how-to/api-setup.md`

### F-138 [BLOCKER]

- **Claim:** 'Complete `.env` Template' (lines 269-289) lists Twilio, ALERT_PHONE_NUMBER, `ANTHROPIC_API_KEY` under '# Anthropic', Telegram and an optional EXPO_ACCESS_TOKEN.
- **Actual:** The template has no OPENAI_API_KEY. That key is mandatory for the live classifier: OpenAIProvider raises 'OPENAI_API_KEY is missing' without it. It presents ANTHROPIC_API_KEY as a normal credential, although that key only serves the legacy rollback. It also omits EXPO_PUSH_TOKEN, which the tracked config.yaml references as `${EXPO_PUSH_TOKEN}`. An unset `${VAR}` raises ConfigError at load. Finally, it omits the optional OPENROUTER_API_KEY. The repo's .env.example already has OPENAI_API_KEY, the Anthropic 'legacy rollback only' comment and OPENROUTER_API_KEY.
- **Evidence:** sentinel/classification/openai_provider.py:123-128; sentinel/config.py:349-358 (_substitute_env_vars raises ConfigError on unset var); config/config.yaml:656 `- "${EXPO_PUSH_TOKEN}"`; .env.example:9-17; sentinel/eval/compare_models.py:541; sentinel/alerts/push_client.py:27
- **Suggested fix:** Rebuild the template from .env.example. Add `OPENAI_API_KEY=` as required (Luna classifier). Relabel ANTHROPIC_API_KEY as 'only for explicit legacy rollback'. Add `OPENROUTER_API_KEY=` as 'optional, offline model comparison only'. Add `EXPO_PUSH_TOKEN=` with a note that it is required whenever the config references `${EXPO_PUSH_TOKEN}` (the tracked config.yaml does), plus EXPO_ACCESS_TOKEN.
- **Source:** FINDINGS.json #137

### F-139 [MAJOR]

- **Claim:** §1, line 7: 'The local configuration selects `classification.provider: openai` and `gpt-5.6-luna`'. Line 87: 'Production deployment, secret installation and restart need separate approval', with a pointer to the migration plan 'for rollout gates'.
- **Actual:** Luna is the LIVE production classifier. It was deployed 2026-09-20 under tag deploy-20260920-232235, and production now runs deploy-20260925-143105 = 6429124. config/config.yaml is the production config, not a local one. The section was last edited 2026-09-20, before deployment, so it reads as if production still runs Haiku and the rollout is pending. It does not link the dated deployment and rollback record.
- **Evidence:** docs/reference/luna-deployment-20260920.md:1-20 (deployed 7048a91, tag deploy-20260920-232235); config/config.yaml:472 provider: openai, :558 model: gpt-5.6-luna; `git log -- docs/how-to/api-setup.md` latest 7048a91 2026-09-20
- **Suggested fix:** Change line 7 to 'Production (config/config.yaml, deployed since 2026-09-20) and the template both select provider: openai with gpt-5.6-luna.' Replace the 'rollout gates' sentence with a link to docs/reference/luna-deployment-20260920.md for the verified deployment and rollback procedure.
- **Source:** FINDINGS.json #143

### F-140 [MAJOR]

- **Claim:** §1 'Budget, failure and rollback', line 57: 'The operator selected **$10/month** on 2026-09-20.'
- **Actual:** The live budget is $30/month, raised on 2026-09-24 in commit 31acd3a. That commit is part of the deployed tag. Its reason: Luna runs 420-580 classifications a day, about $11-17 a month, so $10 would have paused classification around 18 October. The validator bound was also raised to `le=50`. The code default and the template are still $10.
- **Evidence:** config/config.yaml:485 `monthly_usd: 30`; sentinel/config.py:195 `monthly_usd: float = Field(default=10, gt=0, le=50)`; config/config.example.yaml:510 `monthly_usd: 10`; `git show 31acd3a` 'Raise the monthly model budget to $30'
- **Suggested fix:** Replace with: 'Production allowance is $30/month (`classification.budget.monthly_usd`, raised from $10 on 2026-09-24 because Luna costs ~$11-17/month). The code default and config.example.yaml keep $10; the validator accepts at most $50.'
- **Source:** FINDINGS.json #144 (merged with #377)
- **Also reported (duplicate evidence):**
  - #377 (minor): config/config.yaml:485 'monthly_usd: 30'. git log: 31acd3a 'Raise the monthly model budget to $30'. Latest log line: '2026-10-03 12:08:49 sentinel.openai: OpenAI classification: … month_usd=1.2609'. grep -ci budget across the 7-day logs = 0.

### F-141 [MAJOR]

- **Claim:** §1 'Verify without sending alerts': run `.venv/bin/python -m sentinel.eval.direct_luna --live --max-cost-usd 0.25 --output data/eval/luna-direct-validation.jsonl`. Lines 59-61 say to use an absolute ledger path on a server.
- **Actual:** direct_luna defaults to `--config config/config.yaml`. That config now carries the production ledger path /var/lib/sentinel/model-usage.db (commit 6429124). In live mode the ledger is created at that path, so on a workstation the command tries to mkdir /var/lib/sentinel. That directory does not exist locally and needs root, so the live check fails before any request. The offline check is unaffected because it builds no ledger.
- **Evidence:** sentinel/eval/direct_luna.py:173 `--config` default config/config.yaml, :87 Classifier(config); sentinel/classification/openai_provider.py:36-40 (mkdir parent of ledger_path); config/config.yaml:484; `ls -ld /var/lib/sentinel` -> No such file or directory
- **Suggested fix:** Add `--config config/config.example.yaml` (or a local copy with a relative ledger_path) to the live command. Add one sentence saying that config/config.yaml now holds production absolute paths (/var/lib/sentinel/...) and is not runnable locally as-is.
- **Source:** FINDINGS.json #145

### F-142 [MAJOR]

- **Claim:** §2 Twilio, line 96: 'Twilio powers the two primary alert channels: the urgency-9+ phone call and the SMS used for acknowledgments, updates, and the downgrade channel.' The section has no account-state note, and its 'Verify It Works' sends a real SMS.
- **Actual:** By owner decision, SMS is off in production. Tiers 5-8 are `channel: push`, so the only remaining Twilio traffic is the urgency 9-10 call with its confirmation SMS and `fallback: sms`. The Twilio account is also deliberately left unfunded. Since 2026-09-21 every call and SMS fails with HTTP 401 'account ... with status 4 is not active'. This is a known state: calls come back when the owner recharges the account. The doc mentions neither fact, so the verify snippet will fail with 401 and look like a setup error. The snippet also reads os.environ without loading .env, so it raises KeyError unless the variables are exported.
- **Evidence:** config/config.yaml:583-603 (critical action: phone_call, fallback: sms; high/medium channel: push); sentinel/alerts/state_machine.py:436,661,772; run context (Twilio unfunded since 2026-09-21, HTTP 401 status 4)
- **Suggested fix:** Reword line 96: in production Twilio carries only the urgency 9-10 phone call and its confirmation/fallback SMS, and tiers 5-8 are push-only. Add a 'Known state' note: the account is deliberately unfunded, and since 2026-09-21 calls and SMS return HTTP 401 'status 4 is not active' until the owner recharges it. This is not an outage. Link the server runbook's troubleshooting section. In 'Verify It Works', say that it sends a real, billed SMS, that it needs the vars exported (or `./run.sh --test-alert sms`), and that it returns 401 while the account is unfunded.
- **Source:** FINDINGS.json #146

### F-143 [MAJOR]

- **Claim:** §3 Expo Push: it is 'off by default' and the 5-8 tiers 'default to `channel: both`'. Step 2 says to 'Paste each token into `alerts.push.tokens` in `config/config.yaml`'. EXPO_ACCESS_TOKEN is '(Optional)... Leave it unset for basic (unauthenticated) sends.'
- **Actual:** Off-by-default and `both` are the code defaults and the template values. The live config differs: `alerts.push.enabled: true`, token `${EXPO_PUSH_TOKEN}` taken from the env file, and tiers 5-8 set to `channel: push`. config/config.yaml is tracked in a PUBLIC repo, and its own comment says 'NEVER hardcode it here'. Pasting a literal device token into it, as the doc instructs, would leak the token. Project memory also records that production enabled Expo 'Enhanced Security for Push Notifications' after an earlier token leak. If so, production sends need EXPO_ACCESS_TOKEN (robot token in /etc/sentinel/sentinel.env), and unauthenticated sends are rejected. The orchestrator did not verify this: it comes from project memory, not from the code.
- **Evidence:** config/config.yaml:651-656 (enabled: true; comment 'Real token lives in /etc/sentinel/sentinel.env (EXPO_PUSH_TOKEN)... NEVER hardcode it here — this is a PUBLIC repo'); config/config.yaml:597,603 `channel: push`; sentinel/config.py:105,154; sentinel/alerts/push_client.py:16-21,27; memory project_prod_config_and_routing.md ('Enhanced Security for Push Notifications' + robot EXPO_ACCESS_TOKEN)
- **Suggested fix:** Separate defaults from live. Add a line: 'Production: push enabled, tiers 5-8 channel: push (no SMS), token via `${EXPO_PUSH_TOKEN}` from /etc/sentinel/sentinel.env, EXPO_ACCESS_TOKEN required because Enhanced Push Security is on.' Change step 2 so it never writes a literal token into the tracked config/config.yaml: put `"${EXPO_PUSH_TOKEN}"` in the list and set EXPO_PUSH_TOKEN in .env, or use a literal only in an untracked local config.
- **Source:** FINDINGS.json #147 (merged with #309)
- **Also reported (duplicate evidence):**
  - #309 (minor): config/config.yaml:597, :603, :650-655

### F-144 [MINOR]

- **Claim:** The guide says it 'covers setting up all external service accounts needed by Project Sentinel' (line 3). Its sections are OpenAI, Twilio, Expo, Telegram, GDELT and Google News.
- **Actual:** There is no OpenRouter entry. .env.example declares OPENROUTER_API_KEY (offline model comparison only, with a separate key and a credit limit), and sentinel/eval/compare_models.py requires it for live comparison runs. The setup is documented in docs/how-to/model-comparison.md, but api-setup neither mentions nor links it.
- **Evidence:** .env.example:15-17; sentinel/eval/compare_models.py:541-543; docs/how-to/model-comparison.md:51
- **Suggested fix:** Add a short '7. OpenRouter (optional, evals only)' section. It should say: OPENROUTER_API_KEY is used only by `sentinel.eval.compare_models`, never by production alerting; use a separate key with a credit limit; details are in docs/how-to/model-comparison.md.
- **Source:** FINDINGS.json #148

## `docs/how-to/testing.md`

### F-145 [MAJOR]

- **Claim:** Line 14 (Test headline: "Classifies a single headline via Claude Haiku") and line 103 (dry run: "AI classification via Claude Haiku (API costs apply)").
- **Actual:** Classifier() uses the configured provider. With the live config that is OpenAI gpt-5.6-luna. Each call needs OPENAI_API_KEY, reserves and settles cost in the persistent usage ledger (classification.budget.ledger_path), and counts against the monthly_usd cap. It may also make a second Polish-summary repair call. In a dry-run or --once cycle, the enricher also makes paid OpenAI 'enrichment_quality' vagueness calls on the same ledger. The dry-run list omits that enrichment step.
- **Evidence:** sentinel/classification/classifier.py:164-165 and :178-191 (ensure_polish repair call); sentinel/classification/openai_provider.py:131-136 (missing key error), :167 ledger.reserve; sentinel/processing/enricher.py:80-97 and :268-272; config/config.yaml:472, :484-485, :584
- **Suggested fix:** Replace "via Claude Haiku" with "via the configured provider (live: OpenAI gpt-5.6-luna; needs OPENAI_API_KEY; cost is recorded in the usage ledger and counts toward the monthly cap)". In Dry-Run Behavior, replace the Haiku bullet with "Article enrichment (OpenAI vagueness check + body fetch) and AI classification via the configured provider (live: gpt-5.6-luna); API costs apply and are recorded in the usage ledger."
- **Source:** FINDINGS.json #154 (merged with #306)
- **Also reported (duplicate evidence):**
  - #306 (minor): sentinel/classification/classifier.py:164-205; config/config.yaml:472,558

### F-146 [MAJOR]

- **Claim:** Lines 7-21: all Quick Reference commands are given as bare `./run.sh ...` invocations that use the default config/config.yaml. Line 21 says --health prints `data/health.json`, and line 20 says --diagnostic writes `data/diagnostic.html`.
- **Actual:** config/config.yaml is the production file. It uses server-absolute paths and an env placeholder. Locally, load_config fails with "Environment variable 'EXPO_PUSH_TOKEN' is not set" because .env has no such key. Even with that variable set, setup_logging would try to create /var/log/sentinel and the classifier ledger /var/lib/sentinel, and neither is writable locally. health.json and diagnostic.html are written next to database.path, which is /var/lib/sentinel/ with this config. config/config.example.yaml uses local paths (data/sentinel.db, logs/sentinel.log, data/model-usage.db) and has no ${VAR} placeholders.
- **Evidence:** config/config.yaml:484 ledger_path /var/lib/sentinel/model-usage.db, :656 `"${EXPO_PUSH_TOKEN}"`, :662 database path /var/lib/sentinel/sentinel.db, :667 log file /var/log/sentinel/sentinel.log; sentinel/config.py:350-357 raises ConfigError for an unset var; sentinel/logging_setup.py:28-30 os.makedirs(log_dir); sentinel.py:92 and :139-142 derive paths from database.path; local python -c load_config('config/config.yaml') raised the EXPO_PUSH_TOKEN ConfigError; /var/lib and /var/log are not writable; config/config.example.yaml:509, :687, :696
- **Suggested fix:** Add a note above the table: "config/config.yaml is the production config (server paths under /var/lib/sentinel and /var/log/sentinel, ${EXPO_PUSH_TOKEN}). For local runs, pass a local config, e.g. `./run.sh --config config/config.example.yaml --dry-run --once` (or a private copy of it). health.json and diagnostic.html are written in the directory of database.path (data/ with the example config)."
- **Source:** FINDINGS.json #155

### F-147 [MAJOR]

- **Claim:** Line 75: "The bundled fixtures are YAML files with a top-level `headlines:` list (each entry may carry an optional `expected:` map of `is_military_event`, `urgency_min/max`, `event_type`, `affected_countries`, `aggressor`). Both feed the classifier through `--test-file` ... and `--eval`."
- **Actual:** Neither eval_set.yaml nor eval_set_human.yaml has a `headlines:` key. Both are flat top-level lists of cases with id, headline, summary, source, language and failure_mode. The harness also accepts a dict with `cases:`. In `expected`, the fields is_military_event, urgency_min, urgency_max and expected_action are required. Optional fields are affected_countries, affected_countries_must_not_contain, aggressor, aggressor_any_of, and event_type or event_type_any_of. --test-file only reads `data.get("headlines")`, so feeding it these fixtures crashes with AttributeError, because the data is a list. --test-file also compares each expected key with getattr(result, key), so keys such as urgency_min/urgency_max always show up as mismatches. A case passes --eval only when every applicable check passes, including action_match. The harness derives action_match itself: urgency >=9 with a monitored country gives phone_call, >=5 gives sms, anything else is log_only. Errors count as failures.
- **Evidence:** sentinel/eval/harness.py:95-118 (list or `cases:` layouts), :121-168 (required expected keys), :183-216 (checks, action_match), :34-44 (_action_for_urgency); sentinel.py:338 `headlines = data.get("headlines", [])`, :365-369 getattr comparison; tests/fixtures/eval_set.yaml:24-48 (flat `- id:` list); no `headlines:` key in any tests/fixtures/*.yaml
- **Suggested fix:** Rewrite the paragraph. Say that eval sets are flat lists (or `cases:` dicts) of {id, headline, summary, source, language, expected:{is_military_event, urgency_min, urgency_max, expected_action, optional affected_countries / affected_countries_must_not_contain / aggressor / aggressor_any_of / event_type / event_type_any_of}, failure_mode}, consumed only by --eval. Say that --test-file takes a separate `headlines:` list (strings or {text|headline, expected}) and compares expected keys by exact attribute equality. State the pass rule: all applicable checks pass, including the derived action.
- **Source:** FINDINGS.json #157

### F-148 [MAJOR]

- **Claim:** Line 79: eval_set.yaml "Covers critical (9-10), high (7-8), medium (5-6), low/not-military (1-4), and edge cases."
- **Actual:** eval_set.yaml has 44 audit-derived cases (audits 2026-03-24 to 2026-05-01). It has no critical case: no expected_action is phone_call (29 log_only, 15 sms), and the highest urgency_max is 8. eval_set_human.yaml has 50 user-labelled cases (2026-05-22), 6 of them phone_call.
- **Evidence:** tests/fixtures/eval_set.yaml:1-4 header; python count: eval_set.yaml expected_action Counter({'log_only': 29, 'sms': 15}), urgency ranges max (8,8); eval_set_human.yaml Counter({'log_only': 28, 'sms': 16, 'phone_call': 6}); eval_set_human.yaml:1-3 header
- **Suggested fix:** Change the row to: "Default eval set (testing.eval_set_file): 44 cases extracted from the 2026-03-24..05-01 audit reports, tagged by failure_mode; no phone_call/9-10 cases (29 log_only, 15 sms)." Change the eval_set_human row to: "50 production articles blind-labelled by the user on 2026-05-22 (28 log_only, 16 sms, 6 phone_call); urgency range = human score ±1."
- **Source:** FINDINGS.json #158

### F-149 [MAJOR]

- **Claim:** Lines 40-46 and 61-69: the per-phase test commands and the 'Async classifier, alert-path & CLI-bridge tests' section describe the suite. The classifier tests are described only as patching anthropic.AsyncAnthropic. The doc says nothing about tests/conftest.py.
- **Actual:** The suite has 583 tests in 37 files. Fifteen files are in none of the listed groups: test_cached_runtime, test_clarified_policy, test_classification_queue, test_direct_openai (34 tests on the live OpenAI path: no retry, total timeout, budget ledger, missing key, strict schema, reasoning-off), test_enricher, test_incident_alerts, test_incident_memory, test_incident_storage, test_model_comparison, test_openrouter_eval_client, test_push_client, test_separate_metrics, test_summary_language, test_utils_datetime and test_vagueness_check. conftest's `config` fixture uses the code-default legacy provider (anthropic, claude-haiku-4-5-20251001). The `direct_config` fixture switches to provider openai / gpt-5.6-luna with the v2 policy and a tmp_path ledger. Live-path tests mock HTTP through an httpx handler on openai.AsyncOpenAI with a placeholder OPENAI_API_KEY. test_classifier.py covers only the legacy Anthropic path.
- **Evidence:** `.venv/bin/pytest tests/ -q --co` -> "583 tests collected"; per-file counts from collection; tests/conftest.py:62-63 (haiku model, no provider), :226-235 (direct_config); tests/test_direct_openai.py:68-80 (classifier_with_http), :151 test_api_errors_are_safe_no_retry, :170 test_total_timeout; sentinel/config.py:232 provider default "anthropic"
- **Suggested fix:** Add groups for the missing files: live provider (test_direct_openai, test_summary_language, test_classification_queue), incident memory (test_incident_memory, test_incident_storage, test_incident_alerts), enrichment (test_enricher, test_vagueness_check), push (test_push_client), eval tooling (test_model_comparison, test_openrouter_eval_client, test_cached_runtime, test_clarified_policy, test_separate_metrics) and utils (test_utils_datetime). Add a 'Mocking' paragraph: `config` = legacy Anthropic defaults, `direct_config` = live OpenAI/Luna settings with tmp ledger, and OpenAI HTTP stubbed via httpx handler. Retitle the classifier bullet as 'legacy Anthropic path'. Add the total count (583 at 282947f) or tell readers to run `pytest --co -q | tail -1`.
- **Source:** FINDINGS.json #160

### F-150 [MINOR]

- **Claim:** Lines 77-80: the Fixture Files table lists only eval_set.yaml and eval_set_human.yaml.
- **Actual:** tests/fixtures has 9 files. The table omits benchmark_policy_v2.yaml (resolved v2 policy used by runtime tests and compare_models), incident_memory_eval.yaml (sentinel.eval.incident_memory smoke set), luna_direct_fresh.yaml (sentinel.eval.direct_luna), model_comparison_first50.yaml, model_comparison_v2_development.yaml, model_comparison_v2_holdout.yaml (sentinel.eval.compare_models) and polish_summary_guard_fresh.yaml (summary-language guard checks). benchmark_policy_v2.yaml is loaded by the shared direct_config test fixture.
- **Evidence:** `ls tests/fixtures`; tests/conftest.py:232 reads tests/fixtures/benchmark_policy_v2.yaml; sentinel/eval/compare_models.py:29 DEFAULT_DATASET
- **Suggested fix:** Add one row per missing fixture with its consumer (module or test). Link docs/how-to/model-comparison.md for the model_comparison_* and benchmark_policy_v2 files.
- **Source:** FINDINGS.json #159

### F-151 [MINOR]

- **Claim:** Lines 31-35: "# Skip integration tests (no network/API calls) ... -m \"not integration\"" and "# Integration tests only ... -m integration". Line 57 says the `integration` marker covers tests requiring network/API access.
- **Actual:** No test carries @pytest.mark.integration, and no file sets pytestmark. `-m integration` selects 0 tests (583 deselected), and `-m "not integration"` selects all 583. tests/test_integration.py is a mocked pipeline test and is not marked.
- **Evidence:** `grep -rn "mark.integration\|pytestmark" tests/` -> no matches; `.venv/bin/pytest tests/ -q --co -m integration` -> "no tests collected (583 deselected)"
- **Suggested fix:** Say that the `integration` marker is registered in pyproject.toml but currently unused. The whole suite runs offline with mocks, and `-m integration` selects nothing. Drop the two marker commands or label them as reserved.
- **Source:** FINDINGS.json #161

### F-152 [MINOR]

- **Claim:** Line 57: "an unmarked `async def test_...` is silently skipped."
- **Actual:** The venv has pytest 9.0.2 and pytest-asyncio 1.3.0. Under them, an unmarked async test fails with "async def functions are not natively supported". It is not silently skipped. The convention that async tests must be marked is still true: every async test in the listed files carries @pytest.mark.asyncio.
- **Evidence:** `.venv/bin/pytest --version` -> pytest 9.0.2; pip show pytest-asyncio -> 1.3.0; a scratch test `async def test_x()` without the marker -> "FAILED ... async def functions are not natively supported"
- **Suggested fix:** Replace "is silently skipped" with "fails with 'async def functions are not natively supported'".
- **Source:** FINDINGS.json #162

### F-153 [MINOR]

- **Claim:** Lines 17-18 and 13: --test-alert phone_call/sms "Fires real Twilio phone call/SMS ... Real Twilio charge". --once side effects: "Real Twilio calls/SMS if event triggers".
- **Actual:** The owner deliberately left the Twilio account unfunded. Since 2026-09-21 every Twilio call and SMS returns HTTP 401 "account ... with status 4 is not active". This is a known state, so --test-alert phone_call/sms currently fail with that 401 and do not charge. SMS is switched off on purpose: tiers 5-8 are push-only, so --once sends real Expo pushes, which the side-effects column does not mention. --test-alert also inserts a synthetic article and event into the configured database, which the side-effects column omits.
- **Evidence:** Run context owner decisions (2026-10-03); sentinel.py:427-445 (db.insert_article / db.insert_event in _run_test_alert), :473-476; sentinel/alerts/state_machine.py:507-508 (5-8 return level.channel)
- **Suggested fix:** Add a note under the table: "Known state: the Twilio account is intentionally unfunded, so phone_call/sms test alerts currently return HTTP 401 'status 4 is not active' until the owner recharges it (see server-runbook troubleshooting). Tiers 5-8 are push-only, so --once sends real pushes. --test-alert writes a synthetic [TEST] article and event to the configured database."
- **Source:** FINDINGS.json #163

### F-154 [MINOR]

- **Claim:** Line 66: "the ~20 alert-state-machine tests are async". Line 68: run_cycle awaiting the classifier is "verified under -W error::RuntimeWarning" in test_cli_bridges.py.
- **Actual:** test_state_machine.py has 39 async tests (61 collected). test_cli_bridges.py has no warnings filter. The un-awaited-coroutine RuntimeWarning-as-error check is in tests/test_scheduler.py (warnings.simplefilter("error", RuntimeWarning)).
- **Evidence:** grep -c 'async def test' tests/test_state_machine.py -> 39; `grep -rn RuntimeWarning tests/` -> only tests/test_scheduler.py:349,365
- **Suggested fix:** Change "~20" to "39". Move the RuntimeWarning remark to the test_scheduler.py bullet (test_run_cycle_awaits_dispatch_and_check_pending).
- **Source:** FINDINGS.json #164

### F-155 [MINOR]

- **Claim:** Lines 51 and 184 cite "SPEC_ALERT_GROUPING.md Phase 3" and its Manual Verification checklist as if the file were at the repo root. The frontend table (lines 149-170) is presented as the list of covered test files.
- **Actual:** SPEC_ALERT_GROUPING.md now lives at docs/archive/SPEC_ALERT_GROUPING.md; there is no root copy. The frontend table omits two existing test files: src/__tests__/EventDetailPage.test.tsx and src/__tests__/datetime.test.ts.
- **Evidence:** `ls SPEC_ALERT_GROUPING.md` -> No such file; `ls docs/archive/` -> SPEC_ALERT_GROUPING.md; `ls dashboard/frontend/src/__tests__/`
- **Suggested fix:** Link docs/archive/SPEC_ALERT_GROUPING.md in both places. Add rows for EventDetailPage.test.tsx and datetime.test.ts to the frontend table, or point to dashboard/CLAUDE.md as the owner of the dashboard test list.
- **Source:** FINDINGS.json #165

## `docs/how-to/mobile-push-setup.md`

### F-156 [BLOCKER]

- **Claim:** Step 4 (lines 62-76) and Prerequisites (lines 22-24): paste the literal token `"ExponentPushToken[...]"` into `alerts.push.tokens` in `config/config.yaml` locally, or hand-edit `/etc/sentinel/config.yaml` on the server. It also says that with push disabled the backend no-ops and this is 'the shipped, behavior-preserving default — SMS only'.
- **Actual:** The tracked config/config.yaml already has `alerts.push.enabled: true` and `tokens: ["${EXPO_PUSH_TOKEN}"]`, with a comment saying the real token lives in /etc/sentinel/sentinel.env and must never be hardcoded because the repo is public. config.py:350-366 resolves the value from the environment and raises ConfigError when the variable is missing. On the server, /deploy step 6c copies the repo config over /etc/sentinel/config.yaml, and step 6a stops the deploy when it finds a server-only edit, so hand-editing the server file is the wrong procedure. The 'SMS only' claim is also false for the live routing: high and medium use `channel: push`, so with push disabled tiers 5-8 would deliver nothing at all (state_machine.py:435-436 sets send_sms=False for the 'push' action).
- **Evidence:** config/config.yaml alerts.push block (`enabled: true`, `- "${EXPO_PUSH_TOKEN}"`, comment 'NEVER hardcode it here — this is a PUBLIC repo'); sentinel/config.py:350-366; .claude/skills/deploy/SKILL.md:180-249 (6a), 262-268 (6c); sentinel/alerts/state_machine.py:435-436
- **Suggested fix:** Rewrite Step 4 as follows. The token goes into the environment variable EXPO_PUSH_TOKEN: in the local `.env` for local runs, and in `/etc/sentinel/sentinel.env` on the server (owner only). The tracked config.yaml already references `${EXPO_PUSH_TOKEN}` with `enabled: true`. Never paste a literal token into config.yaml, because the repo is public. Never hand-edit /etc/sentinel/config.yaml: config changes go through config/config.yaml, a commit and /deploy (6a/6c). Replace the 'SMS only' sentence with: 'With push disabled or no token, tiers set to channel: push deliver nothing.'
- **Source:** FINDINGS.json #166 (merged with #371)
- **Also reported (duplicate evidence):**
  - #371 (major): config/config.yaml:650-656 (comment: 'Real token lives in /etc/sentinel/sentinel.env (EXPO_PUSH_TOKEN) … NEVER hardcode it here — this is a PUBLIC repo'). grep EXPO_PUSH_TOKEN docs/how-to/mobile-push-setup.md returns no match. Live log: '2026-10-03 10:04:55 [INFO] sentinel.alerts.push_client: Push sent for event 7ebfbda1-… to 1 token(s), ticket=…'. sentinel/alerts/push_client.py:68/78/86 (error lines 'Expo push failed for event', 'no tickets accepted').

### F-157 [MAJOR]

- **Claim:** Step 1 (lines 28-43): 'mobile/app.json ships a placeholder extra.eas.projectId (00000000-0000-0000-0000-000000000000)' and tells the owner to run `npx eas init` to replace it.
- **Actual:** app.json already carries a real EAS projectId and `owner: beepbeepjeep`. They were linked on 2026-06-02 in commit 7181f16 ('Link EAS project and add expo-dev-client for iOS development builds'), and the push path has been live since deploy-20260603-114957. Running `eas init` again is unnecessary and could re-link the project.
- **Evidence:** mobile/app.json `"projectId": "d0e215dd-e23f-4d55-a6b1-a919ea75113d"`, `"owner": "beepbeepjeep"`; `git log -S d0e215dd -- mobile/app.json` → 7181f16 2026-06-02
- **Suggested fix:** Mark Step 1 as already done. Say that app.json is linked to EAS project d0e215dd… under the Expo account beepbeepjeep since 2026-06-02. Keep the eas login/init instructions only as 'if re-provisioning from scratch'.
- **Source:** FINDINGS.json #167

### F-158 [MAJOR]

- **Claim:** Step 7.2 (lines 107-120): 'Opening the PushPanel shows the same push under OSTATNI PUSH (title + body) — the in-app surface fed by the received-notification listener'. The foreground/background note says a foreground push 'shows in the panel immediately'.
- **Actual:** The OSTATNI PUSH section can never show a push. PushPanel only renders a push when it receives a `lastPush` prop and otherwise shows 'brak (jeszcze nic nie odebrano)'. Its only mount point passes no `lastPush`, and `usePushReceiver` is no longer called anywhere: the inbox rewrite removed it from App.tsx in 20b74f2 on 2026-06-02. So check 7.2 always fails, even when delivery works. The real in-app confirmation is now the inbox list (foreground capture and tray sweep).
- **Evidence:** mobile/src/screens/MessageListScreen.tsx:154 `<PushPanel onClose={() => setSettingsOpen(false)} />`; mobile/push/PushPanel.tsx:28,64-72 (`lastPush = null` default → 'brak'); `grep -rn usePushReceiver mobile` → only the definition (usePushReceiver.ts:39) and a type import (PushPanel.tsx:13); docs/explanation/mobile-app.md:124 already says it is 'no longer mounted'
- **Suggested fix:** Replace check 7.2 and the foreground/background note with: 'the push appears as a new tile at the top of the inbox list (foreground capture), or after the app is reopened (tray sweep); tapping the banner opens its Detail screen.' Link mobile-inbox-verification.md MA-1/MA-3. Drop the OSTATNI PUSH wording, or mark that panel section as inert.
- **Source:** FINDINGS.json #168

### F-159 [MAJOR]

- **Claim:** Step 3 (line 58): 'In the running app, tap **PUSH** to open the PushPanel.'
- **Actual:** There is no PUSH button. Since the inbox rewrite the app opens to the message list, and the PushPanel opens as a modal from the ⚙ (Settings) button in the list header. The panel's own title is 'POWIADOMIENIA PUSH'.
- **Evidence:** mobile/App.tsx (Stack with List/Detail only); mobile/src/screens/MessageListScreen.tsx:126-129 (`setSettingsOpen(true)`, label '⚙'), 150-155 (Modal → PushPanel); mobile/push/PushPanel.tsx:60
- **Suggested fix:** Change Step 3 to: 'On the inbox screen, tap ⚙ (top-right of the header) to open the push panel (POWIADOMIENIA PUSH); tap KOPIUJ TOKEN.'
- **Source:** FINDINGS.json #170

### F-160 [MAJOR]

- **Claim:** Step 6 (lines 96-103): run `./run.sh --test-alert push` locally; it sends a real Expo push to every token. The doc does not mention which credentials the local run needs.
- **Actual:** The local run needs two credentials that the doc never mentions. First, the tracked config references `${EXPO_PUSH_TOKEN}`, and load_config raises ConfigError when that variable is unset. The local .env has no EXPO_PUSH_TOKEN entry, and .env.example has no Expo entries at all, so every local ./run.sh command fails at config load until it is added (verified with a load_config call: "ConfigError Environment variable 'EXPO_PUSH_TOKEN' is not set"). Second, ExpoPushClient sends EXPO_ACCESS_TOKEN as a bearer token when set (push_client.py:27,60-61). The owner recorded on 2026-06-04 that Enhanced Push Security is enabled on the EAS project, which rejects unauthenticated sends, so the local .env also needs EXPO_ACCESS_TOKEN. That last point comes from the owner's project memory and cannot be verified from the repo.
- **Evidence:** sentinel/config.py:356-360; `.venv/bin/python -c 'load_config("config/config.yaml")'` → ConfigError EXPO_PUSH_TOKEN not set; `grep -c ^EXPO_PUSH_TOKEN= .env` → 0; `grep EXPO .env.example` → no match; sentinel/alerts/push_client.py:17-21,27,60-61
- **Suggested fix:** Add a prerequisite before Step 6: the local `.env` must define EXPO_PUSH_TOKEN (the device token) and EXPO_ACCESS_TOKEN (the robot access token, which is required while Enhanced Push Security is on), or any ./run.sh command fails at config load. Link api-setup.md for EXPO_ACCESS_TOKEN.
- **Source:** FINDINGS.json #171

### F-161 [MINOR]

- **Claim:** Notes (lines 130-131): 'This procedure exercises Phase 1 backend routing. Run it only after the per-tier channel routing is in place and push is enabled per the steps above.' Step 5 presents `both` as the choice to make; the doc does not mention the live per-tier values.
- **Actual:** `--test-alert push` does not exercise the per-tier routing: it calls `_maybe_send_push` directly on a synthetic urgency-10 event and bypasses `process_event` and `_determine_action`. Per-tier routing has been live since deploy-20260603-114957 (4e9441b). The live config already sets both `high.channel` and `medium.channel` to `push`, by the owner's decision that tiers 5-8 are push-only. Step 5 should state that, not leave it as an open choice.
- **Evidence:** sentinel.py:466-484 ('Bypass state machine routing — call the requested method directly'); `git tag --contains 4e9441b` → deploy-20260603-114957; config/config.yaml high/medium `channel: push`
- **Suggested fix:** Reword the note: '--test-alert push sends one push straight through ExpoPushClient; it does not test tier routing.' In Step 5, say that production runs `channel: push` on high and medium (SMS is switched off on purpose) and that changes go through config/config.yaml + /deploy.
- **Source:** FINDINGS.json #174

### F-162 [MINOR]

- **Claim:** Notes (lines 126-129): 'For the urgency 9–10 path the Twilio voice call remains the primary wake-up; the push is additive'. The doc does not mention the current Twilio state.
- **Actual:** The doc omits the current Twilio state. By the owner's decision the Twilio account is left unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 ('account … with status 4 is not active'). Until the account is recharged, the additive push is the only 9–10 delivery that actually reaches the phone. Calls stay configured and return once the account is recharged.
- **Evidence:** Orchestrator-verified run context (Twilio 401 since 2026-09-21, known state); sentinel/alerts/state_machine.py:435,452-456 (push sent before the call attempt)
- **Suggested fix:** Add one sentence to the caveat: 'Known state: while the Twilio account is unfunded (since 2026-09-21, HTTP 401), calls and SMS fail and the push is the only delivery that reaches the phone; calls return when the owner recharges the account. See server-runbook troubleshooting.'
- **Source:** FINDINGS.json #175

## `docs/how-to/mobile-inbox-verification.md`

### F-163 [MAJOR]

- **Claim:** 'Before you start' step 2 (lines 148-150): '…copy the Expo push token, and paste it into the server `config/config.yaml` push tokens list.'
- **Actual:** The token is never pasted into config.yaml. The tracked config/config.yaml (byte-identical to the live /etc/sentinel/config.yaml) lists `"${EXPO_PUSH_TOKEN}"`, and the real value lives in /etc/sentinel/sentinel.env on the server and in `.env` locally. The repo is public, so a literal token in config.yaml would leak. 'Server config/config.yaml' is also a mix-up: the server reads /etc/sentinel/config.yaml, which /deploy overwrites from the repo.
- **Evidence:** config/config.yaml alerts.push block and comment; sentinel/config.py:350-366; .claude/skills/deploy/SKILL.md:262-268
- **Suggested fix:** Replace with: 'set EXPO_PUSH_TOKEN to this token in the local `.env` (and, owner only, in /etc/sentinel/sentinel.env on the server); config.yaml already references ${EXPO_PUSH_TOKEN} — never paste the token into config.yaml (public repo).'
- **Source:** FINDINGS.json #176

### F-164 [MINOR]

- **Claim:** 'Before you start' step 3 (lines 151-152): fire test alerts with `./run.sh --test-alert push`, `./run.sh --test-alert sms`, or `./run.sh --test-alert` (the 9–10 call). The doc does not mention prerequisites or the Twilio state.
- **Actual:** Two things are missing. First, while the Twilio account is deliberately unfunded (since 2026-09-21), `--test-alert sms` and `--test-alert` (call) fail with HTTP 401 ('account … status 4 is not active'); this is a known state and not a defect. Only `--test-alert push` works today, and every MA item only needs push. Second, any local ./run.sh fails at config load unless `.env` defines EXPO_PUSH_TOKEN, and per the owner's recorded setup EXPO_ACCESS_TOKEN is also needed while Enhanced Push Security is on.
- **Evidence:** sentinel.py:472-484; sentinel/config.py:356-360 (ConfigError reproduced via load_config); sentinel/alerts/push_client.py:27,60-61; run context (Twilio 401 known state)
- **Suggested fix:** Add the following. 'Use `--test-alert push` for all MA checks. Known state: while the Twilio account is unfunded, the sms and call variants return HTTP 401 until the owner recharges the account. The local .env must define EXPO_PUSH_TOKEN (and EXPO_ACCESS_TOKEN).'
- **Source:** FINDINGS.json #177

### F-165 [MINOR]

- **Claim:** Intro and 'Before you start' step 1 (lines 138-140, 147): the checks need 'a fresh dev build'; 'rebuild with `eas build` / a local dev build'.
- **Actual:** The phone in production use runs a standalone `preview` build. TODO.md:97 says the inbox went live 2026-06-03 with a 'standalone `preview` build on the iPhone' and that seeing a fix needs `eas build --profile preview --platform ios` plus a reinstall. eas.json defines both `development` (developmentClient) and `preview` (internal) profiles. The doc names neither profile, so an agent would build the dev-client variant, which needs a Metro server, rather than the build the owner actually uses.
- **Evidence:** mobile/eas.json build.development / build.preview; TODO.md:97
- **Suggested fix:** Name the profile explicitly: 'Install a fresh build with the native deps: `npx eas build --profile preview --platform ios` (the standalone build the owner uses), or `--profile development` for a dev-client build that needs Metro.'
- **Source:** FINDINGS.json #178

## `docs/how-to/model-comparison.md`

### F-166 [BLOCKER]

- **Claim:** Line 3: "This is an evaluation-only workflow. Production still uses Haiku."
- **Actual:** Production classifies with provider openai, model gpt-5.6-luna, through the direct OpenAI Responses API. The Anthropic Haiku path is legacy and kept only for rollback. The OpenRouter comparison described in this doc ended with Luna being adopted (deployed 2026-09-20, live at deploy tag deploy-20260925-143105).
- **Evidence:** config/config.yaml:472 `provider: openai`, :584 `model: gpt-5.6-luna`; sentinel/classification/classifier.py:164 picks OpenAIProvider when provider == "openai"; docs/reference/luna-deployment-20260920.md:1 "Luna production deployment — 2026-09-20"
- **Suggested fix:** Replace the sentence with: "This is an evaluation-only workflow. Production now runs gpt-5.6-luna through the direct OpenAI API (see docs/reference/luna-deployment-20260920.md); Claude Haiku is legacy and kept only for rollback." Keep the next sentence about not constructing Twilio/Expo clients.
- **Source:** FINDINGS.json #149 (merged with #301)
- **Also reported (duplicate evidence):**
  - #301 (major): config/config.yaml:472 provider: openai, :558 model: gpt-5.6-luna

### F-167 [MAJOR]

- **Claim:** Line 123, Version 2 section: "Production still uses its existing prompt, model, memory settings and alert policy."
- **Actual:** Production has adopted the version-2 contract. The runtime classifier builds its requests with sentinel.classification.policy.messages() and labels them prompt_version "clarified-v2:...". The production config carries the same v2 policy ranges as benchmark_policy_v2.yaml, with incident memory enabled. The eval module itself says "runtime owns the unchanged v2 contract".
- **Evidence:** sentinel/classification/classifier.py:14 imports `messages, prompt_hash` from sentinel.classification.policy, :180-185 and :205 `prompt_version="clarified-v2:"...`; sentinel/eval/clarified_policy.py:1 docstring and :7 re-exports from sentinel.classification.policy; config/config.yaml:490-537 `policy: version: 2 ...`, :539-541 `incident_memory: enabled: true`
- **Suggested fix:** Replace the sentence with: "Since the 2026-09-20 Luna deployment, production uses the same clarified version-2 prompt and policy (sentinel/classification/policy.py) with gpt-5.6-luna and incident memory enabled. The benchmark modules import that runtime contract, so a prompt change here is a production change."
- **Source:** FINDINGS.json #150

### F-168 [MAJOR]

- **Claim:** Line 195: "The ongoing production target is separately **$20/month**."
- **Actual:** The live monthly model budget is $30. UsageLedger.reserve() enforces it as a hard cap: classification pauses when the month's ledger total plus the next reservation would go over monthly_usd. It was raised in commit 31acd3a, which is included in the deployed commit 6429124.
- **Evidence:** config/config.yaml:485 `monthly_usd: 30`; sentinel/classification/openai_provider.py:63-67 raises BudgetExceeded when total + amount > monthly_usd; `git log` shows 31acd3a "Raise the monthly model budget to $30" before 6429124
- **Suggested fix:** Change to: "Production has a separate $30/month cap (classification.budget.monthly_usd), enforced by the persistent usage ledger in sentinel/classification/openai_provider.py. This test neither uses nor proves that limit."
- **Source:** FINDINGS.json #151

### F-169 [MAJOR]

- **Claim:** Lines 212-217: the replay example `.venv/bin/python -m sentinel.eval.cached_runtime --report data/eval/v2-runtime-development-20260920-luna.json --dataset ... --output ...` is presented as the way to recheck a finished report.
- **Actual:** With the default --config config/config.yaml, this command now fails in preflight. cached_runtime requires make_config(config).classification to equal the report's saved classification_config. The tracked config has since gained provider, api_base_url, budget, policy, summary_language, retry_* and timeout settings, and changed model and max_tokens. The alert levels still match. The tool stops with "Current make_config classification settings differ from the source report".
- **Evidence:** sentinel/eval/cached_runtime.py:204-209; offline python -c comparison of compare_models.make_config('config/config.yaml').classification against the report's classification_config showed these keys differ: reasoning_effort, provider, api_base_url, budget, summary_language, retry_delay_seconds, policy, timeout_seconds, retry_batch_size, model, max_tokens
- **Suggested fix:** Add a note under the replay command: "The replay compares the current --config classification settings with those saved in the report. Since the Luna deployment changed config/config.yaml, pass --config with the config file used for the original run (for example extract it with `git show <commit>:config/config.yaml` into a scratch file). Otherwise the replay stops with 'classification settings differ'."
- **Source:** FINDINGS.json #152

### F-170 [MINOR]

- **Claim:** Line 5: "Read-only production sampling is a separate, explicit preparation command." The command is never named. The doc also never states how the comparison ended.
- **Actual:** The sampling command is `python -m sentinel.eval.export_candidates --from-production [--output]`. The run results and the adoption decision are recorded in docs/ideas/model-comparison-v2-run-record.md, docs/ideas/model-runtime-comparison-20260920.md, docs/ideas/luna-direct-api-validation-20260920.md and docs/reference/luna-deployment-20260920.md. None of them is linked from this doc. The direct-API follow-up runner (sentinel.eval.direct_luna, fixtures luna_direct_fresh.yaml and polish_summary_guard_fresh.yaml) is not mentioned either.
- **Evidence:** `python -m sentinel.eval.export_candidates --help` prints "--from-production [--output OUTPUT]"; `python -m sentinel.eval.direct_luna --help`; ls docs/ideas docs/reference
- **Suggested fix:** Name the command: "`.venv/bin/python -m sentinel.eval.export_candidates --from-production` (read-only)." Add a short "Outcome" section that links the run record, the runtime comparison, the direct-API validation and the Luna deployment record, and says the direct-API checks use sentinel.eval.direct_luna.
- **Source:** FINDINGS.json #153

## `docs/explanation/architecture.md`

### F-171 [BLOCKER]

- **Claim:** §3 Stage 4.5/5/6 (lines 137-162) describe the live flow as batch enrich -> Classifier.classify_batch -> Corroborator over the whole batch, with refs scheduler.py:239/245/262 and 'On exception: logs error, returns []'.
- **Actual:** Live config has classification.incident_memory.enabled: true, so run_cycle takes a per-article path: for each pending article it calls enricher.enrich_batch([article]) -> IncidentMemory.candidates() -> Classifier.classify(article, incident_context=...) -> IncidentMemory.validate() -> Corroborator.process_classifications([result]) inside its own DB transaction, then classification_complete. classify_batch is only used when incident memory is off. A failure calls db.classification_failed(retry_delay_seconds) and the article stays in classification_queue for retry; it is not dropped. Dedup, keyword filter and enqueue run in one transaction, and the cycle classifies db.pending_classifications(retry_batch_size), not just this cycle's articles. The cited line numbers are stale.
- **Evidence:** sentinel/scheduler.py:236-297 (per-article loop 248-274, legacy branch 275-285, dispatch 306); config/config.yaml incident_memory.enabled: true; sentinel/database.py:119,160-188 (classification_queue)
- **Suggested fix:** Rewrite Stages 4-6 to describe the live incident-memory path first: the classification_queue (enqueue, pending_classifications, retry_delay_seconds, retry_batch_size) and the per-article enrich, candidates, classify, validate and corroborate loop with per-article failure-to-retry. Mark the batch classify_batch path as the legacy path used when incident_memory.enabled is false. Update the line refs to scheduler.py:253/255/277/306.
- **Source:** FINDINGS.json #24

### F-172 [BLOCKER]

- **Claim:** Stage 5 (lines 146-153): 'Calls Claude Haiku 4.5 (claude-haiku-4-5-20251001) via anthropic.AsyncAnthropic ... Per-article json.JSONDecodeError / anthropic.APIError are logged'.
- **Actual:** The live provider is OpenAI: classification.provider: openai, model gpt-5.6-luna. Classifier.classify calls OpenAIProvider.request with the policy.messages() prompt and the strict CLASSIFICATION_SCHEMA through the Responses API, then runs summary_language.ensure_polish. Failures raise ClassificationError, including BudgetExceeded from the persistent UsageLedger. The Anthropic Haiku path runs only when provider == 'anthropic', which is the Pydantic default. It is legacy/rollback.
- **Evidence:** sentinel/classification/classifier.py:164-212; sentinel/classification/openai_provider.py:121-237; config/config.yaml classification.provider: openai, model: gpt-5.6-luna; sentinel/config.py:232
- **Suggested fix:** Describe the live call as OpenAI gpt-5.6-luna via OpenAIProvider (strict JSON schema, monthly budget ledger, Polish-summary guard, ClassificationError leaves the article pending). Move the Haiku/AsyncAnthropic text to a 'legacy/rollback (provider: anthropic)' note.
- **Source:** FINDINGS.json #25 (merged with #26, #305)
- **Also reported (duplicate evidence):**
  - #26 (major): sentinel/classification/classifier.py:1,159-165,173
  - #305 (major): sentinel/classification/classifier.py:164-165, :204 provider_used='openai'; config/config.yaml:650-655; grep '_is_in_cooldown\|_user_already_notified\|_last_alert_time' sentinel/ -> no hits

### F-173 [BLOCKER]

- **Claim:** §6 Key Config Keys, line 260: `alerts.push.tokens` ... "(live `config.yaml` omits the whole block → push off)"; line 259 also lists only the code default `false` for `alerts.push.enabled`.
- **Actual:** Live config has push switched ON with one token: `alerts.push.enabled: true`, `tokens: ["${EXPO_PUSH_TOKEN}"]` (token substituted from /etc/sentinel/sentinel.env). Push is the only working delivery channel for tiers 5-8 today and is additive on 9-10.
- **Evidence:** config/config.yaml:650-656 (`push:` / `enabled: true` / `tokens: - "${EXPO_PUSH_TOKEN}"`); sentinel/config.py:153-155 (code default enabled=False, tokens=[])
- **Suggested fix:** Replace the parenthetical with: "Code default `false` / `[]`; live `config/config.yaml` sets `enabled: true` with one token `${EXPO_PUSH_TOKEN}` (real value in /etc/sentinel/sentinel.env). Push is live." Add the live value to the `alerts.push.enabled` row as well.
- **Source:** FINDINGS.json #45 (merged with #28, #349)
- **Also reported (duplicate evidence):**
  - #28 (major): config/config.yaml:650-656 (push block), alerts.urgency_levels.high/medium channel: push; sentinel/config.py:153-155
  - #349 (minor): config/config.yaml:472, 558, 396, 650-656. sentinel/config.py:28 (enabled: bool = True), 232, 266. Live model-usage.db rows for 2026-10 are all gpt-5.6-luna.

### F-174 [MAJOR]

- **Claim:** §1 Module Map (lines 9-34) lists the modules of the sentinel package.
- **Actual:** The table omits live runtime modules. It is missing sentinel/classification/openai_provider.py (OpenAIProvider, UsageLedger with the model_usage table at classification.budget.ledger_path = /var/lib/sentinel/model-usage.db, StructuredReply, ClassificationError, BudgetExceeded). It is missing policy.py (system_prompt, messages, prompt_hash, FACT_SCHEMA; the v2 clarified policy), schema.py (RESPONSE_SCHEMA, CLASSIFICATION_SCHEMA) and summary_language.py (ensure_polish, is_polish, GUARD_VERSION; a lingua-based Polish gate plus a translation repair call). It is missing incident_memory.py (IncidentMemory.candidates/validate, MEMORY_INSTRUCTIONS) and the offline/opt-in eval package sentinel/eval/ (harness.py for ./run.sh --eval, compare_models.py, openrouter_client.py, cached_runtime.py, direct_luna.py, separate_metrics.py, export_candidates.py, rescore_dimensions.py, reference_history.py, clarified_policy.py, incident_memory.py). It also omits sentinel/processing/__init__.py:process_articles.
- **Evidence:** find sentinel -name '*.py' (46 files); sentinel/scheduler.py:23,160 (IncidentMemory wired into pipeline); sentinel/classification/classifier.py:12-16 imports
- **Suggested fix:** Add rows for openai_provider.py, policy.py, schema.py, summary_language.py and incident_memory.py with their main classes and functions. Add one row for sentinel/eval/ ('offline/opt-in evaluation tooling; not imported by the runtime; harness.py backs ./run.sh --eval').
- **Source:** FINDINGS.json #27

### F-175 [MAJOR]

- **Claim:** §5 'Channel routing & additive push dispatch' (line 221): push is a no-op when disabled '(the shipped default, where a both/push tier still sends SMS only)'; 'after the cooldown / acknowledged / pending-call / dedup gates'; 'the initial push is deduped on the presence of a prior push record'; 'SMS re-alert suppression (_user_already_notified)'; '_USER_NOTIFIED_ALERT_TYPES (sms, whatsapp, phone_call)'; acknowledged updates use 'the is_update dedup-bypass, so each escalation pushes'.
- **Actual:** _user_already_notified and _USER_NOTIFIED_ALERT_TYPES no longer exist. Dedup is now per channel and per notification revision: _channel_delivered() treats a channel as done only when an AlertRecord of that type has status in ('sent','delivered','acknowledged') and event_revision == event.notification_revision. A failed attempt therefore stays retryable. A 'push' tier sets send_sms=False, so with push disabled it sends nothing, not SMS. No cooldown gate exists in process_event. Acknowledged-event updates are sent only when _has_new_delivered_revision() is true, which happens when the revision was bumped by an incident-memory escalation.
- **Evidence:** sentinel/alerts/state_machine.py:391-459 (send_push/send_sms 435-436), 514-544 (_channel_delivered, _has_new_delivered_revision), 833-866 (_maybe_send_push); grep for _user_already_notified/_USER_NOTIFIED returns nothing
- **Suggested fix:** Rewrite the paragraph around notification_revision and _channel_delivered with successful statuses. State that a push-only tier with push disabled delivers nothing. Remove the cooldown, _user_already_notified and _USER_NOTIFIED_ALERT_TYPES references. State that acknowledged events re-notify only on a new notification_revision (escalation).
- **Source:** FINDINGS.json #29

### F-176 [MAJOR]

- **Claim:** §5 post-alert transitions (lines 224-227): 'Further source additions trigger _send_update_sms()'; 'Cooldown: acknowledgment.cooldown_hours (default: 6) after acknowledged_at. No further calls or initial SMSes during cooldown.'; 'Pending call guard: if any AlertRecord has status in (initiated, ringing)'.
- **Actual:** No code reads cooldown_hours; it is defined only in config. For an acknowledged event, process_event returns early and sends an update SMS and push only when notification_revision advanced. Source additions alone do nothing. The pending-call guard checks only alert_type == 'phone_call' records with status initiated/ringing.
- **Evidence:** grep -rn cooldown sentinel/ -> only sentinel/config.py:120 plus comments; sentinel/alerts/state_machine.py:403-420
- **Suggested fix:** Say that cooldown_hours is a dead field (no cooldown is enforced). Say that acknowledged events get update SMS and push only on a new notification_revision (incident-memory escalation). Narrow the pending-call guard to phone_call records.
- **Source:** FINDINGS.json #30 (merged with #47)
- **Also reported (duplicate evidence):**
  - #47 (major): grep for cooldown_hours over sentinel/ and sentinel.py finds only sentinel/config.py:120; sentinel/alerts/state_machine.py:403-414; git log -S _is_in_cooldown → 8864861 (ancestor of deployed 6429124)

### F-177 [MAJOR]

- **Claim:** §2 ClassificationResult table (lines 58-75): lists 13 fields, 'Produced by: Classifier.classify_batch()', is_military_event 'Core yes/no from Haiku', model_used 'Haiku model ID'.
- **Actual:** The dataclass has 10 more fields: incident_memory (dict), facts (dict: attack_countries, protection, status, evidence), summary_processing (dict from ensure_polish), provider_used ('openai'|'anthropic'|'legacy'), prompt_version, request_hash, response_id, cached_input_tokens, estimated_cost_usd, and id (UUID4 PK). Live results come from Classifier.classify(), called per article, and pass through IncidentMemory.validate before the Corroborator. model_used is cfg.model, which is gpt-5.6-luna live.
- **Evidence:** sentinel/models.py:124-148; sentinel/classification/classifier.py:197-212; sentinel/scheduler.py:255-262
- **Suggested fix:** Add the 10 missing fields with types and defaults. Change 'Produced by' to 'Classifier.classify() (live, per article; classify_batch in legacy non-memory mode); validated by IncidentMemory.validate()'. Replace the 'Haiku' wording with 'model (live gpt-5.6-luna)'.
- **Source:** FINDINGS.json #31

### F-178 [MAJOR]

- **Claim:** §2 Event table (lines 77-93): fields end at acknowledged_at; urgency_score 'Max urgency across corroborating articles'; summary_pl 'Polish summary'; first_seen_at 'Earliest article in group'; last_updated_at 'Latest article in group'.
- **Actual:** The field notification_revision (int, default 1) is missing. It is incremented on incident-memory escalation and drives all delivery dedup. With incident memory enabled (live), urgency_score is raised and summary_pl replaced only on an 'escalation' decision; otherwise both stay from the first article. first_seen_at is the first ClassificationResult.classified_at. last_updated_at is datetime.now(UTC) at each update, a processing time and not an article time.
- **Evidence:** sentinel/models.py:210-224; sentinel/classification/corroborator.py:341-352,375-382
- **Suggested fix:** Add notification_revision. Correct the semantics of urgency_score and summary_pl for memory mode, and of first_seen_at and last_updated_at (classification time and processing time).
- **Source:** FINDINGS.json #33

### F-179 [MAJOR]

- **Claim:** §2 AlertRecord table (lines 95-107): 'Consumed by: AlertStateMachine.check_pending_calls()'; status lists Twilio call values plus acknowledged; 'Database.get_pending_call_records() (database.py:221) filters status IN (initiated, ringing)'.
- **Actual:** The field event_revision (int, default 1) is missing. It is set by _record_alert and is the key of delivery dedup. SMS and push records are written with status 'sent' (twilio_client.py:102, push_client.py:99). 'sent', 'delivered' and 'acknowledged' are the _SUCCESSFUL_DELIVERY_STATUSES that process_event reads through _channel_delivered. get_pending_call_records is at database.py:376 and also filters alert_type = 'phone_call'.
- **Evidence:** sentinel/models.py:266-277; sentinel/alerts/state_machine.py:516,868-877; sentinel/database.py:376-384
- **Suggested fix:** Add event_revision. Add 'sent' (SMS/push) to the status list. Extend 'Consumed by' to process_event/_channel_delivered. Fix the ref to database.py:376 and add the alert_type='phone_call' filter.
- **Source:** FINDINGS.json #35

### F-180 [MAJOR]

- **Claim:** §3 Stage 3 (lines 123-129): exact URL-hash match, then fuzzy rapidfuzz title match against recent DB articles (85/95 thresholds).
- **Actual:** When incident_memory.enabled is true (live), Deduplicator._check_duplicate returns after the URL-hash check and skips fuzzy title dedup entirely. Same-headline articles from other URLs are kept for incident comparison.
- **Evidence:** sentinel/processing/deduplicator.py:31-35; config/config.yaml incident_memory.enabled: true
- **Suggested fix:** Add: 'Fuzzy title dedup runs only when classification.incident_memory.enabled is false; live (enabled) uses URL-hash dedup only, and duplicate suppression happens in incident memory after classification.'
- **Source:** FINDINGS.json #36

### F-181 [MAJOR]

- **Claim:** §3 Stage 6 (lines 156-162): groups military classifications by event_type + affected_countries within the corroboration window plus summary similarity; 'Sets Event.alert_status = pending if source_count < corroboration_required.'
- **Actual:** In live memory mode, matching uses _find_memory_match. A match needs a validated model decision of duplicate, update or escalation, confidence >= min_confidence 0.85 (0.9 for critical), a matched_event_id among the candidate_ids, country compatibility and age within lookback_hours 168. The window and summary-similarity logic is the legacy _find_matching_event. Events are created only for is_military_event with urgency >= 5 (_MIN_EVENT_URGENCY). _determine_alert_status returns 'sms', not 'pending', for urgency >= 9 below corroboration_required, and never returns 'pending' for urgency >= 5.
- **Evidence:** sentinel/classification/corroborator.py:28,72-83,98-144,425-445; config/config.yaml incident_memory min_confidence 0.85, critical_min_confidence 0.9, lookback_hours 168
- **Suggested fix:** Describe the memory-mode matching first and label the window and summary matching as legacy. Add the urgency >= 5 military gate. Replace the 'pending' sentence with: under-corroborated critical -> provisional 'sms'; 'pending' only for urgency < 5, which never creates an event.
- **Source:** FINDINGS.json #37

### F-182 [MAJOR]

- **Claim:** §6 line 249: `alerts.urgency_levels.{high,medium}.channel` default `both`, with no live value stated (the rest of the table states live values).
- **Actual:** Live config routes both SMS tiers to push only (`channel: push` for high and medium). This is a deliberate owner decision: SMS is switched off, tiers 5-8 are push-only.
- **Evidence:** config/config.yaml:597 and :603 (`channel: push`); sentinel/config.py:105 (code default "both")
- **Suggested fix:** Append to the row: "Live: `push` for both `high` and `medium` (owner decision: SMS is off, tiers 5-8 are push-only)."
- **Source:** FINDINGS.json #46

### F-183 [MAJOR]

- **Claim:** §6 line 235: `classification.corroboration_required` = "Min independent sources before a phone call fires (the corroborator's `phone_call` gate)"; line 248: `alerts.urgency_levels.<name>.corroboration_required` = "Per-level override for corroboration gate on phone calls".
- **Actual:** The call decision comes only from `AlertStateMachine._determine_action`, which uses `alerts.urgency_levels.critical.corroboration_required` (code default 1, live 1). `classification.corroboration_required` only sets the provisional `Event.alert_status` label in the corroborator. An urgency-9 event below it still gets `sms` (≠ pending), so it is dispatched anyway and cannot block a call. Today one source triggers a call.
- **Evidence:** sentinel/alerts/state_machine.py:500-506; sentinel/classification/corroborator.py:437-445; sentinel/scheduler.py:301; config/config.yaml:577-585 (critical corroboration_required: 1); config/config.yaml:561 (classification corroboration_required: 1)
- **Suggested fix:** Reword line 235: "Only sets the provisional `Event.alert_status` label; does not gate the call." Reword line 248: "`critical.corroboration_required` is the actual phone-call gate; live 1, so one source triggers a call today." Add a TODO.md item asking the owner whether to require 2 sources (existing TODO.md:17 is related).
- **Source:** FINDINGS.json #48 (merged with #41)
- **Also reported (duplicate evidence):**
  - #41 (minor): config/config.yaml:585 (critical corroboration_required: 1), :561; sentinel/alerts/state_machine.py:478

### F-184 [MAJOR]

- **Claim:** §6 line 241: `classification.model` | default `claude-haiku-4-5-20251001` | "Anthropic model for classification". The table has no `classification.provider` row.
- **Actual:** `classification.provider` selects the backend: code default `anthropic`, live `openai`. Live model is `gpt-5.6-luna` through `OpenAIProvider`. The Anthropic Haiku path is legacy and kept only for rollback. The config validator requires a `gpt-` model and a version-2 `classification.policy` when provider is openai.
- **Evidence:** config/config.yaml:472 (`provider: openai`), :558 (`model: gpt-5.6-luna`); sentinel/config.py:232, 242-263, 266; sentinel/classification/classifier.py:164-165
- **Suggested fix:** Add a `classification.provider` row: `anthropic|openai`, code default `anthropic`, live `openai`. Change the model row to "Model ID for the selected provider; code default Haiku (legacy/rollback), live `gpt-5.6-luna`."
- **Source:** FINDINGS.json #49

### F-185 [MAJOR]

- **Claim:** §6 Key Config Keys table (lines 233-261) lists the keys that change runtime behavior.
- **Actual:** Several live-critical keys are missing. (1) `alerts.acknowledgment.max_call_retries`: code default 3, live 1; caps calls per round. (2) `classification.incident_memory.enabled`: default false, live true; switches grouping to the LLM incident-identity path and per-article classification. (3) `classification.budget.*`: `ledger_path` live /var/lib/sentinel/model-usage.db, `monthly_usd` live 30 (code default 10, max 50), and per-million prices. (4) `classification.retry_delay_seconds` (300) and `retry_batch_size` (100), which drive the classification queue.
- **Evidence:** config/config.yaml:647, :540-541, :484-489, :476-477; sentinel/config.py:118, 173, 193-199, 238-239; sentinel/scheduler.py:242, 248, 258-259; sentinel/alerts/state_machine.py:576
- **Suggested fix:** Add rows for `alerts.acknowledgment.max_call_retries` (default 3, live 1), `classification.incident_memory.enabled` (default false, live true), `classification.budget.monthly_usd` / `ledger_path` (default 10 / data/model-usage.db; live 30 / /var/lib/sentinel/model-usage.db), and `classification.retry_delay_seconds` / `retry_batch_size` (300 / 100).
- **Source:** FINDINGS.json #50

### F-186 [MAJOR]

- **Claim:** §6.5 Corroboration & Event Grouping (lines 265-278): a new classification merges into an event only when all five `_find_matching_event` conditions hold (type compatibility, country, critical-acknowledged guard, sliding window, summary similarity). §6 rows 236-239 call the window, max-age and summary-similarity values "live".
- **Actual:** Live config has `incident_memory.enabled: true`, so live grouping uses `_find_memory_match`, not `_find_matching_event`. The classifier receives remembered incidents and returns a decision (duplicate/update/escalation). A merge requires that decision, a matched_event_id among the candidate_ids, confidence ≥ `min_confidence` 0.85 (≥ `critical_min_confidence` 0.9 at urgency ≥ 9), country compatibility, and age ≤ `lookback_hours` 168. Only an `escalation` raises urgency, replaces the summary and increments `notification_revision`. An article already attached to an event is treated as a replay. The fuzzy window, summary-similarity and acknowledged-event guards are not applied on the live path; they only run when memory is disabled.
- **Evidence:** config/config.yaml:540-541; sentinel/classification/corroborator.py:49-82 (memory branch + replay), 98-145 (_find_memory_match), 374-380 (escalation/revision); sentinel/scheduler.py:248-273
- **Suggested fix:** Add a paragraph at the top of §6.5: "Live path (incident_memory.enabled: true): `_find_memory_match` ..." with the conditions above. Relabel the existing five-condition list as "legacy fuzzy path (incident_memory disabled)". In §6 rows 236-239, note that these keys apply only to the legacy path.
- **Source:** FINDINGS.json #51

### F-187 [MAJOR]

- **Claim:** §9 line 327: "Classifier daily token cost logged with hardcoded prices `$0.80/M input, $4.00/M output` at UTC date rollover (`classifier.py:246-248`); not configurable."
- **Actual:** The hardcoded estimate now applies only to the legacy Anthropic path (classifier.py:398-400). On the live OpenAI path, the daily log only reports token counts and points to the ledger. Costs are computed from configurable `classification.budget` prices. A persistent `UsageLedger` reserves a worst-case cost before every request and enforces `monthly_usd` (live $30) with BEGIN IMMEDIATE. `BudgetExceeded` leaves articles pending in classification_queue (retried after retry_delay_seconds) and marks health degraded. Per-row cost is stored in classifications.estimated_cost_usd.
- **Evidence:** sentinel/classification/classifier.py:389-400; sentinel/classification/openai_provider.py:29-90, 166-175, 211; config/config.yaml:484-489; sentinel/scheduler.py:256-260, 578-581
- **Suggested fix:** Replace the bullet with: the hardcoded $0.80/$4.00 estimate is legacy-Anthropic only (classifier.py:398-400). Live cost control is the `classification.budget` ledger, described as above.
- **Source:** FINDINGS.json #56

### F-188 [MAJOR]

- **Claim:** §9 line 328 (async note): "`Classifier` uses `anthropic.AsyncAnthropic`... `run_cycle` awaits `classify_batch`... preserves the Anthropic rate-limit profile". It says every Twilio HTTP touch point is offloaded with `asyncio.to_thread`, and that "Six pure helpers (`_determine_action`, `_is_in_cooldown`, `_user_already_notified`, `_is_acknowledged`, `_last_alert_time`, `_update_alert_record`) stay synchronous."
- **Actual:** (1) Live provider is `openai.AsyncOpenAI` via `OpenAIProvider` (max_retries=0, asyncio.timeout). With incident memory enabled (live), `run_cycle` calls `enricher.enrich_batch([article])` and `classifier.classify` once per article and groups each result in its own transaction. `classify_batch` runs only when memory is disabled. (2) `_is_in_cooldown`, `_user_already_notified` and `_last_alert_time` no longer exist. The current sync helpers are `_determine_action`, `_channel_delivered`, `_has_new_delivered_revision`, `_is_acknowledged`, `_record_alert` and `_update_alert_record`. (3) Not every Twilio touch is offloaded: `SentinelPipeline._send_system_sms` calls `twilio_client.send_sms` synchronously on the event loop. (4) `ExpoPushClient.send_push` is also offloaded via `asyncio.to_thread`. (5) `_run_test_alert` also drives `_maybe_send_push`.
- **Evidence:** sentinel/classification/classifier.py:164-165; sentinel/classification/openai_provider.py:131-136, 177-179; sentinel/scheduler.py:248-277, 471-477; sentinel/alerts/state_machine.py:472, 518-548, 857-863, 868-886; sentinel.py:484
- **Suggested fix:** Rewrite the classifier half for the OpenAI provider and the per-article memory loop; mention AsyncAnthropic only as the legacy path. Replace the helper list with the current six sync helpers. Add that `_send_system_sms` is the one synchronous Twilio call on the loop, and add `send_push` to the to_thread list.
- **Source:** FINDINGS.json #57

### F-189 [MAJOR]

- **Claim:** §9 Known Quirks (lines 317-334) describes system-health SMS (fetcher failure at 10, pipeline failure at 3). It does not mention the Twilio account state.
- **Actual:** All Twilio traffic is affected: calls, confirmation SMS, SMS and system-health SMS. The account is deliberately left unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 ('account ... with status 4 is not active'); this is a known state, not an outage. `send_sms` and `make_alert_call` return None. The two system-health notifications go only through Twilio and have no push fallback, so they do not reach the operator today. Calls stay configured and return when the owner recharges the account.
- **Evidence:** sentinel/scheduler.py:459-460, 471-477, 553-554; sentinel/alerts/twilio_client.py:54-62, 87-95; orchestrator run context (owner decision, Twilio unfunded since 2026-09-21)
- **Suggested fix:** Add a Known Quirks bullet: "Known state (owner decision): the Twilio account is unfunded, so all calls and SMS currently fail with 401 and return None. Phone calls stay configured and return when the account is recharged. System-health SMS are Twilio-only, with no push fallback, so they are not delivered today." Link the runbook troubleshooting section.
- **Source:** FINDINGS.json #60 (merged with #40)
- **Also reported (duplicate evidence):**
  - #40 (major): sentinel/scheduler.py:448-480,550-554; sentinel/alerts/state_machine.py:435-455

### F-190 [MAJOR]

- **Claim:** §10.1 line 351: `dashboard/classifier_input.py` "Reconstructs the exact prompt the production classifier sent to Claude Haiku (kept in lockstep via drift-guard test)".
- **Actual:** The module reproduces only the legacy Anthropic `_build_user_prompt` 5-line text block. The live OpenAI path sends a different payload: `policy.messages()` with a policy-derived system prompt and a JSON user message that includes evaluation_time and remembered_incidents. For Luna-classified rows (since 2026-09-20), the dashboard shows an input the live model never saw. This is a dashboard defect.
- **Evidence:** dashboard/classifier_input.py:1-30; sentinel/classification/policy.py:137-153; sentinel/classification/classifier.py:178-184
- **Suggested fix:** Change the row to: "Reconstructs the legacy Anthropic/Haiku user-prompt block; does not match the live OpenAI (Luna) JSON payload with remembered incidents." Log as TODO item: update classifier_input.py to render the OpenAI `policy.messages()` payload for provider_used='openai' rows.
- **Source:** FINDINGS.json #62

### F-191 [MAJOR]

- **Claim:** §7 Database Schema (lines 284-291) lists four tables: articles, classifications, events and alert_records. Indexes for events are 'alert_status, first_seen_at'. Retention for classifications and alert_records is 'Cascades with article/event cleanup'.
- **Actual:** The live DB has five tables. classification_queue (article_id PK/FK, attempts, next_attempt_at, last_error) is missing from the doc. Also missing: the index idx_events_last_updated on events(last_updated_at), and the additive migration columns. These are classifications.facts, summary_processing, provider_used, prompt_version, request_hash, response_id, cached_input_tokens, estimated_cost_usd, incident_memory; events.notification_revision; alert_records.event_revision. Retention is done by explicit DELETEs, not FK cascades, and articles still in classification_queue are exempt from purging. The separate ledger DB (budget.ledger_path, live /var/lib/sentinel/model-usage.db, table model_usage) is not mentioned.
- **Evidence:** Live: sqlite3 -readonly sentinel.db '.tables' returns alert_records, classification_queue, articles, classifications, events; .schema shows idx_events_last_updated and the added columns. sentinel/database.py:91, 119-138, 427-465. Live model-usage.db .schema matches sentinel/classification/openai_provider.py:42-47.
- **Suggested fix:** Add a classification_queue row (article_id PK/FK, attempts, next_attempt_at, last_error; deleted on completion). Add idx_events_last_updated. Add a line listing the migration columns from _migrate_schema. Reword retention to 'explicit DELETE in cleanup_old_records; queued articles are exempt'. Add a short note on model-usage.db (table model_usage, path from classification.budget.ledger_path, production /var/lib/sentinel/model-usage.db, mode 600).
- **Source:** FINDINGS.json #347 (merged with #53)
- **Also reported (duplicate evidence):**
  - #53 (major): sentinel/database.py:67, 81, 86, 91, 99-103, 110-144, 146-158, 427-464; sentinel/classification/openai_provider.py:36-47

### F-192 [MAJOR]

- **Claim:** §2 Event.alert_status (line 92): 'Values written by code: pending, call_placed, retry_pending, sms_sent, acknowledged, dry_run ... Corroborator._determine_alert_status sets a provisional value (phone_call/sms/pending) but AlertStateMachine overwrites it with the values above.'
- **Actual:** In production the provisional values persist. The state machine updates alert_status only on the call and SMS paths, and the push-only 5-8 tiers never reach the SMS path. So 665 events keep alert_status='sms' (the latest from today), 16 keep 'phone_call', and only 4 have 'sms_sent' (the latest on 2026-07-30). A query for 'sms_sent' would miss all current 5-8 alerts.
- **Evidence:** Live: SELECT alert_status,COUNT(*) FROM events GROUP BY alert_status returned phone_call|16, retry_pending|96, sms|665, sms_sent|4. sentinel/alerts/state_machine.py:780 (sms_sent is set only after a Twilio SMS record); the push path at lines 850-866 does not update alert_status.
- **Suggested fix:** Change the note to say that for push-only tiers, and whenever no Twilio SMS succeeds, the corroborator's provisional value (sms or phone_call) stays stored. Say that most current production rows carry 'sms', and add 'sms' and 'phone_call' to the list of values found in the DB.
- **Source:** FINDINGS.json #348 (merged with #34)
- **Also reported (duplicate evidence):**
  - #34 (major): sentinel/alerts/state_machine.py:435-459,780; sentinel/classification/corroborator.py:398-401; sentinel/database.py:292

### F-193 [MINOR]

- **Claim:** ClassificationResult.event_type (line 65) is an enum: invasion | airstrike | ... | drone_attack | other.
- **Actual:** In the live OpenAI path, event_type is an unconstrained string in the strict schema ({"type": "string"}). The enum exists only in the legacy Anthropic USER_PROMPT_TEMPLATE, and that list also includes 'none'.
- **Evidence:** sentinel/classification/schema.py:7; sentinel/classification/classifier.py:126-127
- **Suggested fix:** Note that event_type is a free string in the live schema. Say that the listed values (plus 'none') are the legacy prompt's vocabulary used by EVENT_COMPATIBILITY grouping.
- **Source:** FINDINGS.json #32

### F-194 [MINOR]

- **Claim:** §2 Article.title_normalized (line 56): 'NFKD + strip diacritics + lowercase + collapse whitespace; used for fuzzy dedup'.
- **Actual:** _normalize_title also deletes every character outside [a-zA-Z0-9\s]. All-Cyrillic (UA/RU) titles normalize to '' or to digits only. Verified: 'Российские дроны атаковали Польшу' -> ''. The field is also used by Corroborator._is_independent_source for the syndication check, not only for dedup.
- **Evidence:** sentinel/models.py:11-15; python -c test: _normalize_title(cyrillic) == '' and fuzz.ratio('', '') == 100.0; sentinel/classification/corroborator.py:322
- **Suggested fix:** State that non-ASCII letters are removed (Cyrillic titles become empty). Say the field is used for legacy fuzzy dedup and for the corroborator's syndication/independence check.
- **Source:** FINDINGS.json #38

### F-195 [MINOR]

- **Claim:** §4 (line 196): 'Health written to data/health.json after each cycle via SentinelScheduler._update_health()'.
- **Actual:** The path is os.path.dirname(config.database.path)/health.json, which is /var/lib/sentinel/health.json in production. data/health.json is only the code-default location. Health is also marked unhealthy when db.classification_health() reports a degraded classification queue.
- **Evidence:** sentinel/scheduler.py:578-596; config/config.yaml database.path: /var/lib/sentinel/sentinel.db
- **Suggested fix:** Say: 'written next to the database (<dirname(database.path)>/health.json; prod /var/lib/sentinel/health.json); includes classification_status and goes unhealthy when the classification queue is degraded.'
- **Source:** FINDINGS.json #42 (merged with #350, #54)
- **Also reported (duplicate evidence):**
  - #350 (minor): sentinel/scheduler.py:595 and sentinel.py:92 (os.path.dirname(config.database.path)). Server: sudo cat /var/lib/sentinel/health.json.
  - #54 (minor): sentinel.py:92; sentinel.py:140-142; sentinel/scheduler.py:578-581, 596; config/config.yaml:662 (path: /var/lib/sentinel/sentinel.db)

### F-196 [MINOR]

- **Claim:** §1 twilio_client row (line 33): 'make_alert_call(phone, message_pl, event_id) (twilio_client.py:43)'.
- **Actual:** make_alert_call is defined at twilio_client.py:27. send_sms is at :78 and get_call_status at :111.
- **Evidence:** sentinel/alerts/twilio_client.py:27,78,111
- **Suggested fix:** Change the anchor to twilio_client.py:27.
- **Source:** FINDINGS.json #43

### F-197 [MINOR]

- **Claim:** §1 run.sh row (line 12): 'Activates .venv, forwards all args to sentinel.py'.
- **Actual:** run.sh does not activate the venv. It execs .venv/bin/python directly. If the venv is missing, it creates it and runs pip install -r requirements.txt first.
- **Evidence:** run.sh:12-23
- **Suggested fix:** Change to: 'Runs sentinel.py with .venv/bin/python (creates the venv and installs requirements if missing), forwarding all args.'
- **Source:** FINDINGS.json #44

### F-198 [MINOR]

- **Claim:** §6.5 line 278: an article is an independent source if it has a different domain and a title below the syndication threshold.
- **Actual:** Google News articles keep the news.google.com redirect link as `source_url`. `_extract_domain` therefore returns the same domain for every Google News article, so two Google News articles from different publishers never count as independent of each other.
- **Evidence:** sentinel/fetchers/google_news.py:140-162 (link used as-is); sentinel/classification/corroborator.py:447-458 (_extract_domain), 319-325 (same-domain → not independent)
- **Suggested fix:** Add one sentence: "Because Google News links are stored as news.google.com redirects, Google-News-vs-Google-News pairs are never independent (same domain)."
- **Source:** FINDINGS.json #52

### F-199 [MINOR]

- **Claim:** §8 line 301: `--dry-run` = "no Twilio calls/SMS"; line 305: `--diagnostic` "skips alert dispatch"; line 309: `--test-alert` bypasses fetch/classify.
- **Actual:** Dry run skips all event alerts, push included, because the dispatcher only logs. It still does three things: (1) it makes live paid classifier calls; (2) it runs `check_pending_calls`; (3) it can send Twilio system-health SMS (`_send_system_sms` ignores dry_run). `--diagnostic` also classifies with the live model and writes to the DB. `--test-alert` inserts a synthetic article and event into the configured database and also supports push via `_maybe_send_push`.
- **Evidence:** sentinel/alerts/dispatcher.py:45-48; sentinel/scheduler.py:304-309, 459-460, 471-477, 553-554; sentinel.py:254-257, 428-438, 476-484
- **Suggested fix:** Change the rows to: "--dry-run: no event alerts (SMS, call or push); classification still calls the paid model; system-health SMS are not suppressed." and "--diagnostic: ... still makes paid classifier calls and writes to the DB." Note that --test-alert writes a synthetic article and event into database.path.
- **Source:** FINDINGS.json #55

### F-200 [MINOR]

- **Claim:** §9 line 331: "`keyword_bypass` sources skip Stage 4 entirely. All their articles consume Haiku API quota."
- **Actual:** Live classification is OpenAI `gpt-5.6-luna`. Bypass articles consume the OpenAI budget tracked in the model-usage ledger (monthly cap $30).
- **Evidence:** config/config.yaml:472, 558, 485; sentinel/classification/openai_provider.py:175
- **Suggested fix:** Change to: "All their articles are classified by the live model (gpt-5.6-luna) and count against `classification.budget.monthly_usd`."
- **Source:** FINDINGS.json #58

### F-201 [MINOR]

- **Claim:** §9 line refs: line 322 `state_machine.py:368`, `state_machine.py:391` (confirmation code); line 323 `gdelt.py:178`; line 332 `scheduler.py:464`; line 333 `scheduler.py:420`; line 334 `scheduler.py:515`.
- **Actual:** The behaviors still hold, but the line numbers are stale. The confirmation code is set at state_machine.py:667 and the SMS SID at :677. GDELT `summary=""` is at gdelt.py:190. Fast-lane jitter is at scheduler.py:504. The fetcher SMS check `failures == 10` is at scheduler.py:459. The pipeline failure SMS `failures == 3` is at scheduler.py:553.
- **Evidence:** sentinel/alerts/state_machine.py:667, 677; sentinel/fetchers/gdelt.py:190; sentinel/scheduler.py:504, 459, 553
- **Suggested fix:** Update the references to state_machine.py:667/677, gdelt.py:190, scheduler.py:504, scheduler.py:459 and scheduler.py:553, or cite function names instead of line numbers.
- **Source:** FINDINGS.json #59

### F-202 [MINOR]

- **Claim:** §10.2 line 392 says enum-like unions in `types.ts` are widened with `| string`. Line 419 says EventTimeline shows "emoji icons for phone/SMS/WhatsApp".
- **Actual:** `AlertRecord.alert_type` in types.ts is `"sms" | "phone_call" | "whatsapp"`, not widened, and it has no `push`. Push is the dominant live alert type (tiers 5-8 are push-only). EventTimeline has no push icon or label, so push records fall back to "•" and the raw string "push".
- **Evidence:** dashboard/frontend/src/types.ts:112; dashboard/frontend/src/components/EventTimeline.tsx:21-30, 107-113
- **Suggested fix:** Note in the line 392 and 419 rows that `alert_type` is not widened and has no `push` variant, and that push records render with the generic "•" fallback. Optionally log a TODO to add a push icon.
- **Source:** FINDINGS.json #63

## `docs/explanation/pipeline.md`

### F-203 [BLOCKER]

- **Claim:** Stage 5 (line 93): "Every article that reaches this stage is sent individually to Claude Haiku 4.5 for classification." The section then describes the legacy prompt: a fixed event_type enum, aggressor RU/BY/unknown/none, an urgency table, "Events in Ukraine max out at urgency 4", and "special military operation" framing treated as an attack (lines 95-119). The classifier is cited as `sentinel/classifier.py`.
- **Actual:** Production classifies through OpenAI `gpt-5.6-luna` using the Responses API. It sends a strict JSON schema with reasoning effort 'none' and the versioned policy-v2 prompt from `sentinel/classification/policy.py`. The Anthropic Haiku branch is legacy and used only for rollback. The live prompt sets bands from `classification.policy.ranges`. Official resident air-raid, shelter or evacuation orders score 9-10 even when no attack is confirmed. Ukraine-only combat scores 1-3, capability escalation scores 5-6, and a near-border strike under `awareness` scores 5-6. The legacy cap of urgency 4 for Ukraine does not apply. The live schema has `event_type` and `aggressor` as free strings with no enum. The model also returns `facts` (attack_countries/protection/status/evidence), `incident_memory` and `is_new_event`. The v2 prompt has no 'special military operation' rule. The file path is `sentinel/classification/classifier.py`.
- **Evidence:** config/config.yaml:472 `provider: openai`, :558 `model: gpt-5.6-luna`, :474 `reasoning_effort: none`, :490-538 policy v2 ranges; sentinel/classification/classifier.py:164,178-205 (OpenAI path, provider_used="openai"); sentinel/classification/openai_provider.py:151-159 (responses.create, json_schema strict); sentinel/classification/schema.py:5-33 (event_type/aggressor plain strings, facts + incident_memory required); sentinel/classification/policy.py:111-143 (bands); sentinel/config.py:232,266 (code defaults anthropic / claude-haiku-4-5-20251001 = legacy)
- **Suggested fix:** Rewrite Stage 5 to describe the live path. Each article goes individually to OpenAI `gpt-5.6-luna` (`classification.provider: openai`, `sentinel/classification/openai_provider.py`) with the policy-v2 prompt (`sentinel/classification/policy.py`) and the strict schema (`schema.py`). Name the band rules from `classification.policy.ranges` in live config, including that official shelter orders score 9-10 and Ukraine-only events score 1-3, or 5-6 for capability escalation or a near-border strike. List the extra output fields (`facts`, `incident_memory`, `is_new_event`). Mark the Haiku prompt and enum list as the legacy/rollback path only. Fix the path to `sentinel/classification/classifier.py`.
- **Source:** FINDINGS.json #64 (merged with #303)
- **Also reported (duplicate evidence):**
  - #303 (major): config/config.yaml:558, :585, :597, :603, :647 `max_call_retries: 1`, :650-655 push enabled

### F-204 [BLOCKER]

- **Claim:** Stage 7 Push section (line 166): push is off by default and "the live production config omits the block, so push is currently disabled". It adds: "While push is off, a `both`/`push` tier still sends SMS only, so the deployed behavior is unchanged." Lines 146-147 and 162 give tiers 5-8 the channel `default both` and never state the live value.
- **Actual:** Live config enables push with a token and routes both SMS tiers (high 7-8 and medium 5-6) to `channel: push`. Tiers 5-8 are therefore push-only in production, and the owner switched SMS off for them on purpose. The code also contradicts the doc for the disabled case. For a `push` tier `send_sms` is False, and `_maybe_send_push` returns early when push is disabled. A `push` tier with push disabled therefore sends nothing at all, not SMS. Only a `both` tier falls back to SMS-only.
- **Evidence:** config/config.yaml:650-652 `push: enabled: true, tokens: ["${EXPO_PUSH_TOKEN}"]`; config/config.yaml:597 and :603 `channel: push` (high, medium); sentinel/alerts/state_machine.py:435-436 (`send_push = action in ("push","both","phone_call")`, `send_sms = action in ("sms","both")`), :849-851 (push no-op when disabled)
- **Suggested fix:** State that push is enabled in production (`alerts.push.enabled: true`, token from `${EXPO_PUSH_TOKEN}`). State that live `high.channel` and `medium.channel` are both `push`, so urgency 5-8 is push-only with no Twilio SMS, by owner decision. Keep `both` as the code default only. Correct the disabled-push sentence: with push off, a `both` tier sends SMS only and a `push` tier sends nothing.
- **Source:** FINDINGS.json #65 (merged with #369)
- **Also reported (duplicate evidence):**
  - #369 (major): config/config.yaml:650-656 (push.enabled: true, tokens ${EXPO_PUSH_TOKEN}), :597 and :603 (channel: push), and max_call_retries: 1 (line ~647); config/config.yaml:472 provider: openai, :558 model: gpt-5.6-luna. Logs: 159x 'sentinel.alerts.push_client: Push sent for event … to 1 token(s), ticket=…' in 7 days. Prod DB alert_records for the last 7 days: 'push|sent|159' only. 'Event 4fc335a6: 1 calls this round, no SMS confirmation, retry in 5 min'. 4449x 'OpenAI classification' lines and 0 lines mentioning haiku/anthropic.

### F-205 [BLOCKER]

- **Claim:** Stage 6 (lines 125-138) says Events are matched by four conditions: event-type compatibility, country compatibility, a sliding 360-minute window with a 2880-minute max age, and summary similarity >= 50 by token_set_ratio. It also describes a guard that keeps critical articles out of acknowledged Events. Line 119 says gating uses urgency + source_count only, and line 152 says urgency escalates as articles arrive.
- **Actual:** Production has `classification.incident_memory.enabled: true`, so the corroborator calls `_find_memory_match` instead of `_find_matching_event`. Grouping follows the model's own incident decision (new/duplicate/update/escalation/uncertain), made against up to 5 candidate incidents. `IncidentMemory.candidates` builds that list from the newest event in a 168h, 100-event pool plus the best fuzzy WRatio matches. `IncidentMemory.validate` accepts a match only when the ID is among the candidates and confidence is >= 0.85, or >= 0.9 at phone-call urgency. It forces `new` when explicit dates or weekdays conflict. Country compatibility and the 168h lookback still apply. The event-type, 360-min window, 2880-min max-age, summary-similarity and acknowledged-event guards are not used in production. In memory mode an existing event's urgency rises only on an `escalation` decision. Escalation also increments `notification_revision` and replaces `summary_pl`. A first critical report on a non-critical incident is forced to `escalation`. An article already linked to an event is replayed as a duplicate.
- **Evidence:** config/config.yaml:540-557 (incident_memory enabled, lookback_hours 168, candidate_pool_size 100, max_candidates 5, min_confidence 0.85, critical_min_confidence 0.9); sentinel/classification/corroborator.py:49-70 (replay guard), :82-83 (memory vs legacy matcher), :98-144 (_find_memory_match), :146-214 (legacy matcher incl. ack guard :182), :375-381 (urgency/revision only on escalation); sentinel/classification/incident_memory.py:157-187, :215-277; sentinel/scheduler.py:248-273
- **Suggested fix:** Rewrite the Event-matching part of Stage 6 around incident memory, which is live in production. Cover candidate retrieval, the model's incident decision, the validation thresholds and the date/weekday conflict guard. Cover the country and lookback safety guards, escalation as the only way urgency or `notification_revision` rises, and the forced escalation on a first critical report. Move the four-condition fuzzy matcher and the acknowledged-event critical guard into a clearly labelled 'legacy path (incident_memory.enabled: false)' subsection. Note that incident-memory confidence is threshold-gated even though classification confidence is not.
- **Source:** FINDINGS.json #66 (merged with #304)
- **Also reported (duplicate evidence):**
  - #304 (major): config/config.yaml:540-549; sentinel/scheduler.py:248-262; sentinel/classification/corroborator.py:82-83, :98-144, :375-380; grep -ci incident.memory docs/explanation/*.md -> 0

### F-206 [MAJOR]

- **Claim:** Stage 6 intro (line 125): "A single article, however alarming, is not enough to trigger a phone call... requires corroboration from independent sources". Stage 7 heading (line 168) reads "Phone Call (Urgency 9–10 with Independent Corroboration)", and line 170 says a call "requires... at least one independent confirming source". The table row at line 144 cites `classification.corroboration_required = 1` as the state-machine reference.
- **Actual:** In production one source triggers a phone call. The state machine's `_determine_action` reads `alerts.urgency_levels.critical.corroboration_required`, which is 1 live, and it does not read `classification.corroboration_required`. Every event has source_count >= 1, so the 9-10 'sms fallback' row cannot be reached under live config. The corroborator's `_determine_alert_status` separately reads `classification.corroboration_required`, which is 1 live with a code default of 2. The 'two parallel paths' therefore read two different keys. TODO.md:17 already asks whether raising the phone-tier `corroboration_required` is warranted.
- **Evidence:** config/config.yaml:585 (critical corroboration_required: 1), :561 (classification.corroboration_required: 1); sentinel/alerts/state_machine.py:500-506; sentinel/classification/corroborator.py:437-440; sentinel/config.py:97 (UrgencyLevel default 1), :269 (classification default 2); TODO.md:17
- **Suggested fix:** Describe current behaviour: today one source at urgency 9-10 triggers a phone call. Retitle the Stage 7 heading so it no longer says 'with Independent Corroboration'. Cite `alerts.urgency_levels.critical.corroboration_required` (live 1, code default 1) for the state-machine row. Cite `classification.corroboration_required` (live 1, code default 2) for the corroborator's alert_status. Note that the 9-10 SMS-fallback row is unreachable at the value 1. Add a TODO.md item, or extend the existing TODO.md:17 item, asking the owner whether to require 2 sources.
- **Source:** FINDINGS.json #67 (merged with #368)
- **Also reported (duplicate evidence):**
  - #368 (major): Log census of 'action=phone_call' lines: 2026-09-29 'u9 s1 phone_call', 2026-09-30 'u9 s1', 2026-10-01 'u9 s1', 2026-10-02 2x 'u9 s1', 2026-10-03 'u9 s1' (from 'sentinel.alerts.state_machine: Event …: urgency=9, sources=1, action=phone_call').

### F-207 [MAJOR]

- **Claim:** Stage 3 (lines 58-66): "Three deduplication checks are applied in sequence", including (3) fuzzy title matching over the past 60 minutes at 95% cross-source and 85% same-source.
- **Actual:** With incident memory enabled, as in production, `_check_duplicate` returns after the exact-URL check. Fuzzy title dedup is skipped on purpose, so near-identical headlines from different URLs reach classification. There the incident-memory decision handles them. Only the batch-internal URL check and the DB URL-hash check run in production.
- **Evidence:** sentinel/processing/deduplicator.py:26-35 (`if self.config.classification.incident_memory.enabled: return None` before Strategy 2); config/config.yaml:541 (incident_memory.enabled: true)
- **Suggested fix:** State that the fuzzy-title check (step 3) runs only when `classification.incident_memory.enabled` is false. Also state that in production, with memory on, only the two URL checks run and near-duplicate headlines are resolved after classification by incident memory.
- **Source:** FINDINGS.json #68

### F-208 [MAJOR]

- **Claim:** The pipeline is described as articles flowing straight from the keyword filter through enrichment into classification. Lines 89 and 83 say failed articles are simply dropped or skipped, and the doc has no retry or budget step.
- **Actual:** Articles that pass the keyword filter are inserted into the `classification_queue` table in the same transaction as dedup. Each cycle then classifies `db.pending_classifications(retry_batch_size)`: up to 100 queued articles, oldest first, including retries from earlier cycles. When classification or grouping fails, `classification_failed` reschedules the article after `retry_delay_seconds` (300). The article is removed from the queue only after grouping succeeds. Every OpenAI request first reserves a cost bound against a persistent monthly ledger, `classification.budget.ledger_path`, at /var/lib/sentinel/model-usage.db live. The cap is `monthly_usd` (live 30, code default 10). When the cap would be exceeded, `BudgetExceeded` is raised and the article stays pending. Classification, the enrichment LLM gate and the summary-translation call are all budgeted. Any queued article with attempts > 0 marks `health.json` `classification_status.degraded` and sets `is_healthy` false.
- **Evidence:** sentinel/scheduler.py:236-243, :256-273, :287-298, :578-581; sentinel/database.py:119-121 (classification_queue), :160-190; sentinel/classification/openai_provider.py:56-73, :166-175; config/config.yaml:476-489; sentinel/config.py:195 (monthly_usd default 10)
- **Suggested fix:** Add a short 'Classification queue and budget' stage between keyword filtering and classification. Describe the enqueue step, the batch of `retry_batch_size` (100) per cycle, the retry after `retry_delay_seconds` (300), and removal from the queue only after successful grouping. Describe the monthly ledger cap (`classification.budget.monthly_usd`, live 30): articles stay pending when it is reached and health reports degraded.
- **Source:** FINDINGS.json #69

### F-209 [MAJOR]

- **Claim:** Stage 5, 'Polish summary' (line 117): "One to two sentences summarizing the event in Polish. This text is used verbatim in the phone call and SMS alert."
- **Actual:** On the live OpenAI path the model's `summary_pl` passes through the Polish-summary guard, `ensure_polish` in `sentinel/classification/summary_language.py`. The guard rejects any Cyrillic text and any text the lingua detector does not identify as Polish. The detector is restricted to `summary_language.detector_languages`. Rejected text goes to one budgeted translation repair call (`repair_max_tokens` 512, `repair_timeout_seconds` 10). If the repair also fails, the alert carries the fixed `fallback_pl` text 'Polskie podsumowanie jest chwilowo niedostępne...'. The danger score and incident decision are kept unchanged. An empty summary raises `ClassificationError`, so the article stays pending. The guard's metadata is stored in `classifications.summary_processing`.
- **Evidence:** sentinel/classification/summary_language.py:45-93; sentinel/classification/classifier.py:187-192 (empty summary raises; ensure_polish); config/config.yaml:478-482
- **Suggested fix:** Add a paragraph on the Polish-summary guard: the Cyrillic check, lingua detection, one translation repair, and the configured `fallback_pl` text that can appear in calls and pushes. Note that an empty summary keeps the article pending.
- **Source:** FINDINGS.json #70

### F-210 [MAJOR]

- **Claim:** Post-Acknowledgment Behavior (line 194): "a 6-hour cooldown applies to that Event. No further calls or initial SMSes are sent... If new confirming sources arrive within those 6 hours, a brief SMS update is sent." Line 164 says acknowledged-event updates send the update SMS and an additive push via "the `is_update` dedup-bypass". Line 166 says the initial push is deduplicated against any prior `push` record.
- **Actual:** No time-based cooldown exists. `alerts.acknowledgment.cooldown_hours` is read nowhere in `sentinel/`. An acknowledged event never gets another call, at any time. Updates are revision-aware, from commit 8864861, which is deployed. An update is sent only when `event.notification_revision` has advanced past a previously delivered revision. Only an incident-memory `escalation` advances the revision, and the comment says cooldown intentionally does not apply to a new revision. New sources alone do not trigger an update. SMS and push are each deduplicated per channel. A channel counts as delivered only when a record has a successful status (sent/delivered/acknowledged) for the same `event_revision`. A failed attempt therefore stays retryable, and the `is_update` dedup bypass no longer exists.
- **Evidence:** sentinel/alerts/state_machine.py:403-414, :438-453, :515-544, :849-853; grep: `cooldown_hours` appears only at sentinel/config.py:120 and config/config.yaml:649; sentinel/classification/corroborator.py:379-381; git: 8864861 is an ancestor of deployed 6429124
- **Suggested fix:** Replace the cooldown paragraph. State that acknowledgement stops calls permanently for that Event. State that an update SMS and an update push are sent once per new `notification_revision`, and only an incident-memory escalation creates one. State that each channel is deduplicated by a successful record for that revision, so failed sends retry. Remove the 6-hour cooldown and the `is_update` dedup-bypass wording. Log a TODO item that `alerts.acknowledgment.cooldown_hours` is an unused config key.
- **Source:** FINDINGS.json #71

### F-211 [MAJOR]

- **Claim:** Phone Call step 5 (line 180): "Attempts per round: `alerts.max_call_retries` from config — live value `5`, code default `3`." Step 1 (line 172) quotes the confirmation SMS as "Telefon będzie dzwonił dopóki nie potwierdzisz."
- **Actual:** The key is `alerts.acknowledgment.max_call_retries`. Its live value is 1; it was reduced from 5 after the 2026-07-30 call storm, per the config comment. The code default is 3. The confirmation SMS is sent without diacritics: "Odpowiedz kodem aby potwierdzic odbior alertu: NNNNNN" followed by "Telefon bedzie dzwonil dopoki nie potwierdzisz."
- **Evidence:** config/config.yaml:640-647 (`max_call_retries: 1` under acknowledgment, with storm comment); sentinel/config.py:118; sentinel/alerts/state_machine.py:576, :669-674
- **Suggested fix:** Change the step to `alerts.acknowledgment.max_call_retries` with live value 1 (code default 3), and add a pointer to the 2026-07-30 rationale. Quote the confirmation SMS as sent, without diacritics.
- **Source:** FINDINGS.json #72

### F-212 [MAJOR]

- **Claim:** 'SMS Alert (Urgency 7–8)' section (lines 186-190) describes the SMS sent for urgency 7-8.
- **Actual:** In production, urgency 7-8 and 5-6 send no SMS, because both tiers are `channel: push` by owner decision. The SMS-format body built by `_format_sms_message` is still used in four places. It is the post-acknowledgement follow-up SMS, the `data.sms_body` field inside every push payload, any tier set to `sms` or `both`, and the 9-10 fallback. The format applies to 5-8, not only 7-8. `twilio_client.send_sms` also hard-truncates any body over 1600 characters.
- **Evidence:** config/config.yaml:597,603; sentinel/alerts/state_machine.py:155-189, :314 (sms_body in push data), :812-822 (follow-up), :435-458; sentinel/alerts/twilio_client.py:84-85
- **Suggested fix:** Retitle the section 'SMS body format'. State that tiers 5-8 are push-only in production, so this body is not sent as an SMS for them. State that it is used for the post-acknowledgement follow-up SMS, inside push `data.sms_body`, and for any tier set to `sms` or `both`.
- **Source:** FINDINGS.json #73

### F-213 [MINOR]

- **Claim:** Stage 7 (lines 168-184) and System Health Alerts (lines 196-204) describe calls, the confirmation SMS and the operator health SMS as working delivery channels.
- **Actual:** Known state, not a defect: the owner has deliberately left the Twilio account unfunded. Since 2026-09-21 every Twilio call and SMS fails with HTTP 401 ('account ... with status 4 is not active'). `make_alert_call` and `send_sms` therefore return None. The phone-call path still runs every cycle, and the health SMSes in `_send_system_sms` do not arrive. Phone calls stay configured and return when the owner recharges the account. Push is the only channel that delivers today.
- **Evidence:** Run context (owner decision); sentinel/alerts/twilio_client.py:60-62, :93-95 (TwilioRestException -> None); sentinel/scheduler.py:471-477
- **Suggested fix:** Add a one-line note in Stage 7 that links to the server runbook's troubleshooting entry. The note should say that the Twilio account is intentionally unfunded, so calls and SMS currently fail with HTTP 401 until the owner recharges it, and Expo push is the channel that delivers today. Frame it as a known state, not an outage.
- **Source:** FINDINGS.json #74

### F-214 [MINOR]

- **Claim:** Stage 4 (line 83): keyword lists cover "English (20 critical, 38+ high, 24 exclude), Polish (17 critical, 31 high, 15 exclude), Ukrainian (9 critical, 19 high), and Russian (9 critical, 19 high)".
- **Actual:** Live config has EN 29 critical, 57 high and 24 exclude, and PL 23 critical, 48 high and 16 exclude. UK (9/19) and RU (9/19) are correct. The doc also omits two behaviours. Non-English articles are checked against their own exclude list plus the English one. Articles in a language with no keyword set fall back to the English set.
- **Evidence:** python yaml count of config/config.yaml: {'en': (29, 57, 24), 'pl': (23, 48, 16), 'uk': (9, 19, 0), 'ru': (9, 19, 0)}; sentinel/processing/keyword_filter.py:42-49, :65-69
- **Suggested fix:** Update the counts to EN 29/57/24, PL 23/48/16, UK 9/19, RU 9/19, or drop exact counts and point to `monitoring.keywords` in config/config.yaml. Mention the English exclude list and the English fallback set.
- **Source:** FINDINGS.json #75

### F-215 [MINOR]

- **Claim:** Google News (line 32): "Note: `config/config.example.yaml` ships with 15 queries — the live count (16) is authoritative."
- **Actual:** config/config.example.yaml now also has 16 queries, so the two files no longer differ.
- **Evidence:** python yaml count: config/config.example.yaml google_news queries = 16; config/config.yaml = 16
- **Suggested fix:** Delete the example-vs-live note, or say both ship 16 queries.
- **Source:** FINDINGS.json #76

### F-216 [MINOR]

- **Claim:** Line references: jitter `sentinel/scheduler.py:464` (line 15); enrichment "awaited at `scheduler.py:239`" (line 89); health SMS `scheduler.py:420` and `scheduler.py:515` (lines 201-202); GDELT `summary = ""` at `sentinel/fetchers/gdelt.py:178` (line 38). Health table rows `failures == 5` → WARNING and `failures == 10` → ERROR log + SMS.
- **Actual:** The lines have moved. Fast-lane jitter is at scheduler.py:504. Enrichment is at :253 (memory path, per article) and :276 (legacy path). The ==10 SMS is at :459 and the ==3 SMS at :553. GDELT `summary=""` is at gdelt.py:190. The WARNING log fires on every failure from 5 to 9, and the ERROR log on every failure from 10 up. Only the SMS is one-shot at exactly 10.
- **Evidence:** sentinel/scheduler.py:452-469, :504, :553; sentinel/fetchers/gdelt.py:190
- **Suggested fix:** Update the line numbers, or replace them with function names (`SentinelScheduler.start`, `SentinelPipeline.run_cycle`, `_check_fetcher_health`, `_check_pipeline_health`). Change the table to `failures >= 5` → WARNING, `failures >= 10` → ERROR, and SMS only at `== 10`.
- **Source:** FINDINGS.json #77

### F-217 [MINOR]

- **Claim:** Stage 4.5 (line 89): a "cheap LLM gate" flags vague titles, and the fetched body is "merged in". GDELT section (line 38): "Language detection is performed later in the pipeline."
- **Actual:** In production the LLM gate is an OpenAI request (`purpose="enrichment_quality"`, max 256 tokens) that counts against the model budget; the Anthropic `_check_vagueness_llm` is legacy. In memory mode enrichment runs per article inside the classification loop. If enrichment raises, for example on budget exhaustion, the article is rescheduled for retry. A fetched body replaces `article.summary`; it is not merged with it. No article-language detection exists anywhere in the pipeline. GDELT language comes from the API's `language` field, mapped by `GDELT_LANGUAGE_MAP` with a default of 'en'.
- **Evidence:** sentinel/processing/enricher.py:80-98, :265-273, :289-292 (`article.summary = body`); sentinel/scheduler.py:251-261; sentinel/fetchers/gdelt.py:179-183
- **Suggested fix:** State that the vagueness gate is a budgeted OpenAI call. State that the fetched body (og:description, or text capped at 500 characters) replaces the summary. Note that an enrichment failure leaves the article queued for retry. Replace 'Language detection is performed later' with 'language comes from GDELT's own language field'.
- **Source:** FINDINGS.json #78

### F-218 [MINOR]

- **Claim:** Storage (lines 210-217): "a SQLite database with four tables". The health snapshot is written to `data/health.json` and "shows the last cycle's outcome, source counts, and any errors".
- **Actual:** The DB has a fifth table, `classification_queue`, which holds pending and retrying articles. Articles still in the queue are exempt from 30-day cleanup. Model spend lives in a separate SQLite ledger, `model_usage`, at `classification.budget.ledger_path` (/var/lib/sentinel/model-usage.db live). health.json is written next to the database (`dirname(database.path)`), which is /var/lib/sentinel/health.json in production; `data/health.json` holds only for a local relative path. It contains per-fetcher booleans, not source counts, plus `classification_status` {pending, failed, degraded}. Each `alert_records` row also carries `event_revision`, and each event carries `notification_revision`.
- **Evidence:** sentinel/database.py:119-121, :103, :427-445; sentinel/scheduler.py:572-596; sentinel.py:92; config/config.yaml:662 (database.path /var/lib/sentinel/sentinel.db), :484
- **Suggested fix:** Make the list five tables (add `classification_queue`) and mention the separate model-usage ledger. Give the health path as `<dir of database.path>/health.json` (/var/lib/sentinel/health.json in production). List its fields, including `classification_status`.
- **Source:** FINDINGS.json #79

## `docs/explanation/mobile-app.md`

### F-219 [BLOCKER]

- **Claim:** Lines 64-68: 'The channel is **off by default**: the config block `alerts.push` has `enabled: false` and an empty `tokens: []` list, and the live `config/config.yaml` omits the block entirely — so until push is enabled, a `both`/`push` tier still sends SMS only and the deployed behavior is unchanged.' Line 13 also presents `both` as the operative setting without saying what production uses.
- **Actual:** The live config/config.yaml (byte-identical to /etc/sentinel/config.yaml) HAS an `alerts.push` block with `enabled: true` and `tokens: ["${EXPO_PUSH_TOKEN}"]`, and both SMS tiers are `channel: push`. Tiers 5-8 are push-only in production; there is no Twilio SMS for them. `enabled: false` / `tokens: []` is only the code default (sentinel/config.py) and the template (config/config.example.yaml).
- **Evidence:** config/config.yaml:597 `channel: push` (high), :603 `channel: push` (medium), :650-656 `push: enabled: true ... tokens: - "${EXPO_PUSH_TOKEN}"`; config/config.example.yaml:631,637 `channel: both`, :668-670 `enabled: false, tokens: []`; sentinel/config.py:153-155 PushConfig defaults; tests/test_config.py:378-384 asserts config.yaml is 'production push-only'.
- **Suggested fix:** Replace the paragraph with three facts kept apart: (1) code default (sentinel/config.py) and template (config/config.example.yaml) = push disabled, `tokens: []`, tiers `channel: both`; (2) live production (config/config.yaml) = push enabled, token supplied as `${EXPO_PUSH_TOKEN}`, tiers 5-8 `channel: push`, so tiers 5-8 are push-only by owner decision (SMS deliberately off); (3) the 9-10 tier keeps its call plus the additive push. Delete 'the deployed behavior is unchanged'.
- **Source:** FINDINGS.json #80 (merged with #310)
- **Also reported (duplicate evidence):**
  - #310 (major): config/config.yaml:650-655, :597, :603

### F-220 [BLOCKER]

- **Claim:** Lines 22-24 ('copy it and paste it into the server's `alerts.push.tokens` config list'), the diagram at line 76 (`config/config.yaml  alerts.push.tokens: ["ExponentPushToken[…]"]`), and line 226 ('copy the token shown in the panel') tell the reader to paste the literal device token into config/config.yaml.
- **Actual:** The repo is public. Production keeps the device token in /etc/sentinel/sentinel.env as EXPO_PUSH_TOKEN, and config.yaml only references `${EXPO_PUSH_TOKEN}`, resolved at load by config.py `_substitute_env_vars`. config.yaml says explicitly to NEVER hardcode the token there, and a test enforces the placeholder. Following the doc would commit a device token to a public repo and break the test.
- **Evidence:** config/config.yaml:652-656 comment 'Real token lives in /etc/sentinel/sentinel.env (EXPO_PUSH_TOKEN) ... NEVER hardcode it here — this is a PUBLIC repo'; tests/test_config.py:384 `assert main_push["tokens"] == ["${EXPO_PUSH_TOKEN}"]  # placeholder, not a raw token`.
- **Suggested fix:** Change the purpose list, diagram and 'Running it' text to: copy the token from the app panel, then set it as `EXPO_PUSH_TOKEN` in the server env file (/etc/sentinel/sentinel.env; this is a server write that needs the owner's permission). config/config.yaml keeps only the `"${EXPO_PUSH_TOKEN}"` placeholder. Never put a literal `ExponentPushToken[...]` in a tracked file. Update the diagram node to `sentinel.env EXPO_PUSH_TOKEN → config.yaml alerts.push.tokens: ["${EXPO_PUSH_TOKEN}"]`.
- **Source:** FINDINGS.json #81

### F-221 [MAJOR]

- **Claim:** Lines 201-205: 'The committed `app.json` ships a placeholder (`00000000-0000-0000-0000-000000000000`); a real EAS project id is required before token minting works.' Lines 284-287 add a 'Bug noticed while documenting' note that `getExpoPushTokenAsync` 'will fail until a real EAS project id is wired in'.
- **Actual:** app.json holds a real EAS projectId and an owner, wired in on 2026-06-02 (commit 7181f16, before this doc's last rewrite on 2026-06-03). Token minting works, and the push path has been live since 2026-06-03. The bug note is false, and so is TODO.md item 3, which repeats it.
- **Evidence:** mobile/app.json `"extra": {"eas": {"projectId": "d0e215dd-e23f-4d55-a6b1-a919ea75113d"}}, "owner": "beepbeepjeep"`; git log mobile/app.json: 7181f16 2026-06-02 'Link EAS project and add expo-dev-client for iOS development builds'; TODO.md:208 still lists the placeholder bug; TODO.md:97 'went live in production 2026-06-03'.
- **Suggested fix:** Rewrite the Configuration note: app.json carries the linked EAS projectId (extra.eas.projectId) and Expo owner `beepbeepjeep`, and registerForPush.ts reads the id from there rather than hardcoding it. Delete the trailing 'Bug noticed while documenting' block. Also remove or close TODO.md:208 item 3 as resolved by 7181f16.
- **Source:** FINDINGS.json #82

### F-222 [MAJOR]

- **Claim:** Lines 260-263 (Known limitations): 'On-device verification (MA-1…MA-7) is pending.' Lines 99-101 and 222-224 say the app must run as 'a fresh dev build'. The page never says the inbox has shipped or is live.
- **Actual:** The inbox went live in production on 2026-06-03. The iPhone runs a standalone `preview` build (internal distribution), server push is enabled, and MA-1…MA-7 were validated on-device that day. JS changes reach the phone only through a new `eas build --profile preview --platform ios` and a reinstall. A dev build with Metro is the development path, not what runs in production.
- **Evidence:** TODO.md:97 'The in-app SMS-equivalent message inbox shipped and went **live in production 2026-06-03** (server push enabled; standalone `preview` build on the iPhone)... needs a fresh `eas build --profile preview --platform ios`'; mobile/eas.json `preview: {distribution: internal}`; owner memory project_inbox_app_spec.md: 'on-device MA-1..MA-7 ALL VALIDATED' 2026-06-03.
- **Suggested fix:** Add a Status line near the top: 'Shipped and live since 2026-06-03 (standalone EAS `preview` build on the owner's iPhone; server push enabled).' Change the Known-limitations bullet to say MA-1…MA-7 were validated on-device on 2026-06-03 and must be re-run after each rebuild. In 'Running it', split the dev-build/Metro workflow from the shipped path: a JS fix reaches the phone only after `eas build --profile preview --platform ios` and a reinstall, so batch fixes as TODO.md 3.1 describes.
- **Source:** FINDINGS.json #83

### F-223 [MAJOR]

- **Claim:** Lines 30-31, 54-55, 157-158 and 258-259 say 'the Twilio phone call remains the primary 9–10 wake-up' / 'the guaranteed wake-up'. Lines 251-252 say acknowledgment is the 6-digit confirmation-SMS reply flow. The page presents push as supplementary only.
- **Actual:** The code still places the call and sends the confirmation SMS. But the owner has deliberately left the Twilio account unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 ('account ... with status 4 is not active'). This is a known state, not a defect. Today the Expo push, sent before the call is attempted, is the only channel that actually reaches the phone, also for urgency 9-10. The doc does not tell the reader this.
- **Evidence:** sentinel/alerts/state_machine.py:452-456 (push sent via `_maybe_send_push` before `_execute_phone_call`); :580-581 confirmation SMS inside the call path; orchestrator-verified owner decision (Twilio unfunded since 2026-09-21, HTTP 401).
- **Suggested fix:** Add a short 'Current known state' note: the Twilio account is deliberately left unfunded, so since 2026-09-21 calls and SMS (including the 6-digit confirmation SMS) fail with HTTP 401. That is a known state, not an outage. Calls stay configured and return when the owner recharges the account. Until then the additive push is the only alert that reaches the phone, and it does not bypass silent mode/DND without Critical Alerts. Keep 'the call is the designed primary wake-up' as design intent and link to the runbook troubleshooting entry.
- **Source:** FINDINGS.json #84

### F-224 [MAJOR]

- **Claim:** The page explains the push channel and the token flow but never mentions EXPO_ACCESS_TOKEN or Expo 'Enhanced Security for Push Notifications'. AD-1 frames the posture as 'no server ingress opened — same posture as the token paste flow'.
- **Actual:** push_client.py sends `Authorization: Bearer $EXPO_ACCESS_TOKEN` when that env var is set. In production, Enhanced Security for Push Notifications is turned on for the EAS project, with a robot access token in sentinel.env. This neutralised a device token that leaked into public git history. A send carrying only the device token returns UNAUTHORIZED, so in production EXPO_ACCESS_TOKEN is effectively required, not optional.
- **Evidence:** sentinel/alerts/push_client.py:18-21 (docstring on optional EXPO_ACCESS_TOKEN / Enhanced Security), :27 `os.environ.get("EXPO_ACCESS_TOKEN", "")`, :60-61 Bearer header; owner memory project_prod_config_and_routing.md 'Security (resolved 2026-06-04)'.
- **Suggested fix:** Add a bullet under 'How it relates to the push channel': the EAS project has Enhanced Security for Push Notifications enabled, so every send must carry the robot access token `EXPO_ACCESS_TOKEN` (from /etc/sentinel/sentinel.env; push_client.py sends it as a Bearer header). Without it Expo rejects the push. If the robot token leaks, rotate it in the Expo dashboard and update sentinel.env; the device token itself is not the secret. Link api-setup.md for the setup.
- **Source:** FINDINGS.json #85

### F-225 [MAJOR]

- **Claim:** AD-3 and the App.tsx/capture rows (lines 113, 118, 150-158) describe capture as foreground listener + tap handler + tray-sweep on foreground. Nothing is said about what happens to the OS notification afterwards.
- **Actual:** Since commit 1c7697b (2026-06-04, after this doc was written), each capture path (foreground listener, tray sweep, tap routing) calls `dismissFromTray()` after a successful ingest. This removes the notification from the iOS Notification Center once it is stored. The reason is that the store keeps no deletion tombstone, so an undismissed tray copy would bring a deleted message back on the next sweep.
- **Evidence:** mobile/src/notifications/capture.ts:20-24 and :42-51 (`dismissFromTray`), :64 and :102 calls; mobile/src/notifications/useNotificationRouting.ts:197; git log: 1c7697b 2026-06-04 'Dismiss OS tray copy on ingest so deleted inbox messages stay deleted'.
- **Suggested fix:** Add to AD-3/AD-4 (and the capture.ts table row): after a successful ingest every capture path dismisses the OS notification from the tray (`dismissFromTray`), so alerts disappear from Notification Center once they are in the inbox. The store has no deletion tombstone, so a tray copy left behind would re-ingest a deleted message.
- **Source:** FINDINGS.json #86

### F-226 [MINOR]

- **Claim:** Lines 59-62: the fat payload carries 'the alert's structured fields ... plus the original SMS body ... inside the notification's `data`'. No size limits or trim behaviour are mentioned.
- **Actual:** The server caps `data` at 3500 UTF-8 bytes (PUSH_DATA_MAX_BYTES). It trims in a fixed order: trailing sources first, then `sms_body`, then `summary_pl`. The visible push `body` carries at most 80 summary characters (PUSH_BODY_SUMMARY_MAX_CHARS). `data` also carries `message_id` (a fresh uuid per send), `event_id`, `kind` (event/update) and `event_type_pl`. Expo sends with `priority: high`, `sound: default` and `_contentAvailable: true` (the best-effort background wake behind AD-3). As a result, the Detail screen can show fewer sources than the SMS for a large event.
- **Evidence:** sentinel/alerts/state_machine.py:49-55 PUSH_DATA_MAX_BYTES=3500, :57-70 PUSH_BODY_SUMMARY_MAX_CHARS, :301-372 `_build_push_data` (fields + trim order); sentinel/alerts/push_client.py:46-55 payload keys.
- **Suggested fix:** Add 2-3 sentences after the fat-payload paragraph. Name the builder (`_build_push_data` in sentinel/alerts/state_machine.py) and the full field list (incl. message_id, kind, event_type_pl). State the 3500-byte `data` budget with its trim order (sources → sms_body → summary_pl) and the 80-char cap on the visible body. Note `_contentAvailable: true` in push_client.py as the AD-3 background-wake hint.
- **Source:** FINDINGS.json #87

### F-227 [MINOR]

- **Claim:** Line 230: 'Building requires Expo CLI `>= 16.0.0`'. Lines 92-98 list the stack dependencies.
- **Actual:** `cli.version` in eas.json constrains the EAS CLI (eas-cli), not the Expo CLI. eas.json also sets `appVersionSource: remote`. The dependency list leaves out `expo-dev-client`, which makes `npm start` target a dev build rather than Expo Go. The doc also omits `mobile/.npmrc` (`legacy-peer-deps=true`, needed for a clean `npm install` with RNTL 13 on React 19.1) and the `npm run typecheck` (tsc) gate that the verification runbook names as an automated gate.
- **Evidence:** mobile/eas.json `"cli": {"version": ">= 16.0.0", "appVersionSource": "remote"}`; mobile/package.json dependencies `"expo-dev-client": "~6.0.21"`, scripts `"typecheck": "tsc --noEmit"`; mobile/.npmrc `legacy-peer-deps=true`; docs/how-to/mobile-inbox-verification.md:4 'automated gates are JS-only (Jest + `tsc`)'.
- **Suggested fix:** Change 'Expo CLI `>= 16.0.0`' to 'EAS CLI (`eas-cli`) `>= 16.0.0`; app versions are managed remotely (`appVersionSource: remote`)'. Add `expo-dev-client` to the stack list. Under Tests add `npm run typecheck` beside `npm test`. Note that `mobile/.npmrc` sets `legacy-peer-deps=true` so `npm install` resolves the SDK-54-pinned tree.
- **Source:** FINDINGS.json #88

## `docs/reference/config-reference.md`

### F-228 [BLOCKER]

- **Claim:** Lines 133-139 (classification table) present `corroboration_window_minutes`, `corroboration_max_age_minutes`, `summary_similarity_metric` and `summary_similarity_threshold` as active settings, e.g. 'Live & default `360` (6h)' and 'Tune in config without a code deploy'. The 'Legacy event-grouping notes' (l.141) and l.198 call them legacy only in passing.
- **Actual:** Live config has `incident_memory.enabled: true`. In that mode the Corroborator calls `_find_memory_match`, not `_find_matching_event`, so these four keys are never read in production. The memory path has no max-age cap. A validated match can attach to any event whose `last_updated_at` is within `incident_memory.lookback_hours` (168h). The acknowledged-event critical guard (l.144) is also legacy-only. In memory mode the deduplicator returns before fuzzy title dedup, so the `processing.dedup.*` title thresholds are inert too. The keys that still act in production are `syndication_similarity_threshold` (`_is_independent_source`) and `corroboration_required`.
- **Evidence:** sentinel/classification/corroborator.py:82-83 (`matching_event = self._find_memory_match(result) if memory_enabled else self._find_matching_event(result)`); corroborator.py:148-151 (the four keys are read only inside `_find_matching_event`); corroborator.py:135 (memory age check uses lookback_hours on last_updated_at); sentinel/processing/deduplicator.py:34-35; config/config.yaml:541 (`enabled: true`); `git show 6429124:config/config.yaml` line 541 `enabled: true`
- **Suggested fix:** Add a sentence above the table: 'Production runs the incident-memory path (`incident_memory.enabled: true`). In that mode corroboration_window_minutes, corroboration_max_age_minutes, summary_similarity_metric and summary_similarity_threshold are not read; only syndication_similarity_threshold and corroboration_required still act.' Mark those four rows 'legacy path only (inert in production)'. Replace each 'Live & default' with 'default'. In the incident_memory section, state that memory matching has no max-age cap and is bounded only by lookback_hours since last activity. State that processing.dedup fuzzy thresholds are skipped while memory is enabled.
- **Source:** FINDINGS.json #90

### F-229 [BLOCKER]

- **Claim:** alerts.push section (line 315): 'The live config/config.yaml omits this block entirely, so push is OFF by default ... the deployed behavior is unchanged'; table rows line 319 `enabled` live value '(omitted → false)' and line 320 `tokens` live value '(omitted → [])'.
- **Actual:** The live config has the push block with enabled: true and tokens: ["${EXPO_PUSH_TOKEN}"]. Push is ON in production (also in the deployed commit 6429124). Only config/config.example.yaml ships it disabled.
- **Evidence:** config/config.yaml:650-656 (`push:` / `enabled: true` / `tokens: - "${EXPO_PUSH_TOKEN}"`); `git show 6429124:config/config.yaml` lines 650-656 identical; sentinel/config.py:153-155 (PushConfig default enabled=False); config/config.example.yaml push block `enabled: false`, `tokens: []`
- **Suggested fix:** Rewrite the paragraph: push is enabled in production (live `enabled: true`, `tokens: ["${EXPO_PUSH_TOKEN}"]`, token resolved from /etc/sentinel/sentinel.env). Set the live-value column to `true` and `["${EXPO_PUSH_TOKEN}"]`. Keep the separate note that the Pydantic default is `false`/`[]` and that config.example.yaml ships it disabled.
- **Source:** FINDINGS.json #103 (merged with #335)
- **Also reported (duplicate evidence):**
  - #335 (major): config/config.yaml:650-656. Live DB: 'push|sent|791|2026-10-03T10:14:07' from alert_records grouped by alert_type and status.

### F-230 [MAJOR]

- **Claim:** l.233-234: 'The model budget target is **USD 20/month total**, including future content verification. This configuration does not enforce a billing cap.'
- **Actual:** `classification.budget.monthly_usd` is enforced. `UsageLedger.reserve` raises `BudgetExceeded` once the month's reservations would exceed the cap, which pauses classification. Production sets the cap to 30 (commit 31acd3a, 'Raise the monthly model budget to $30'). The same doc says '(maximum configurable 50; production sets 30)' at l.157, so the two passages contradict each other.
- **Evidence:** sentinel/classification/openai_provider.py:64-68 (`if self.total(month) + amount > self.config.monthly_usd: raise BudgetExceeded`); config/config.yaml:485 (`monthly_usd: 30`); sentinel/config.py:195 (`le=50`); git show 31acd3a
- **Suggested fix:** Replace l.233-234 with: 'Incident-memory context is billed in the same request and counts against `classification.budget.monthly_usd` (live 30 USD/month, hard-enforced by the usage ledger: when it is reached, classification pauses and articles stay pending).' Delete the 'USD 20/month' and 'does not enforce a billing cap' claims.
- **Source:** FINDINGS.json #92 (merged with #339)
- **Also reported (duplicate evidence):**
  - #339 (major): config/config.yaml:485. git log: 31acd3a 'Raise the monthly model budget to $30'. Live model-usage.db: SUM(charged_usd) per month and purpose gives 2026-09 classification 5.3034, enrichment_quality 0.2746, summary_translation 0.0303; 2026-10 values 1.1727, 0.0779, 0.0071.

### F-231 [MAJOR]

- **Claim:** §`monitoring` l.101: 'Consumed by: `sentinel/scheduler.py`, `sentinel/classification/classifier.py`'. l.105-106: `target_countries` are the 'Countries monitored for attack' and `aggressor_countries` are 'Potential aggressors injected into classification prompt context'.
- **Actual:** Neither the classifier nor the scheduler reads `monitoring.*`. `keywords` and `exclude_keywords` are read only by `sentinel/processing/keyword_filter.py`. `target_countries` is read only by the GDELT fetcher, which is disabled in production, as a `sourcecountry:` filter. No code reads `aggressor_countries`. The countries in the classifier prompt come from `classification.policy.monitored_countries` (OpenAI path) or are hardcoded in `SYSTEM_PROMPT` (legacy Anthropic path). Editing `monitoring.target_countries` therefore does not change what the classifier monitors.
- **Evidence:** `grep -rn 'aggressor_countries\|target_countries\|monitoring\.' sentinel` → only sentinel/fetchers/gdelt.py:79 and sentinel/processing/keyword_filter.py:39,65,133,155; sentinel/classification/policy.py:29 (`countries = ", ".join(policy["monitored_countries"])`); sentinel/classification/classifier.py:20-23 (hardcoded PL/LT/LV/EE, Russia/Belarus)
- **Suggested fix:** Change 'Consumed by' to `sentinel/processing/keyword_filter.py` (keywords, exclude_keywords) and `sentinel/fetchers/gdelt.py` (target_countries, as the GDELT sourcecountry filter). Describe `aggressor_countries` as 'currently unused by code'. Add: 'The countries the classifier monitors are set by classification.policy.monitored_countries (live PL, LT, LV, EE), not by monitoring.target_countries.'
- **Source:** FINDINGS.json #93

### F-232 [MAJOR]

- **Claim:** §`sources.rss` l.42: `priority` — '1=fast lane + highest corroboration weight; 2–3=slow lane only'. §`sources.telegram` l.86 and l.88-95 document a per-channel `priority` (default 1) and list live priorities 1/1/1/2.
- **Actual:** Priority only selects the lane for RSS: the fast lane fetches `priority <= 1`. No code gives priority any corroboration weight. Independence is judged by domain and title similarity only, and `source_count` increments by 1 per independent source. `TelegramChannel.priority` is read nowhere. Telegram always runs in the fast lane, so DeepState's priority 2 has no effect.
- **Evidence:** sentinel/fetchers/rss.py:38 (`s.priority <= max_priority`); sentinel/scheduler.py:417 (`_FAST_LANE_FETCHERS = frozenset({"telegram", "google_news"})`) and :435-436; `grep -rn priority sentinel` shows no other consumer; sentinel/classification/corroborator.py:285-330 (`_is_independent_source`, no weighting) and :393-394 (`source_count += 1`)
- **Suggested fix:** Change the RSS `priority` description to '1 = polled in both the fast (3 min) and slow lanes; ≥2 = slow lane only. No effect on corroboration.' Add to the Telegram section: '`priority` is accepted but currently unused; all Telegram channels are drained in the fast lane.'
- **Source:** FINDINGS.json #94

### F-233 [MAJOR]

- **Claim:** §Required Environment Variables l.15-26 lists OPENAI/ANTHROPIC/TWILIO/ALERT_PHONE_NUMBER/TELEGRAM vars. Twilio vars are 'Used by Alert dispatcher (`sentinel/alerts/dispatcher.py`)'. TELEGRAM vars are 'yes if telegram enabled'.
- **Actual:** (1) The live config references `${EXPO_PUSH_TOKEN}` in `alerts.push.tokens`. `_substitute_env_vars` raises ConfigError for any unset referenced variable, so the config fails to load without it, and the table omits it. (2) `EXPO_ACCESS_TOKEN` is read by `push_client.py` and sent as a bearer token. Production uses Enhanced Push Security, so pushes need it; it is also missing. (3) The Twilio credentials are read in `sentinel/alerts/twilio_client.py`, not dispatcher.py. (4) The TELEGRAM_* vars are required whenever the YAML contains `${TELEGRAM_...}`, whatever the value of `enabled`, because substitution runs before validation.
- **Evidence:** config/config.yaml:656 (`- "${EXPO_PUSH_TOKEN}"`); sentinel/config.py:350-362 (raise ConfigError on unset var), :394-397 (substitution before model validation); sentinel/alerts/push_client.py:27 (`EXPO_ACCESS_TOKEN`); sentinel/alerts/twilio_client.py:21-23
- **Suggested fix:** Add rows: `EXPO_PUSH_TOKEN`, used by alerts.push.tokens and required whenever the YAML references it (it is referenced live). `EXPO_ACCESS_TOKEN`, used by sentinel/alerts/push_client.py and required in production because Enhanced Push Security is on. Change the Twilio 'Used by' cell to `sentinel/alerts/twilio_client.py`. Reword the TELEGRAM rows to 'required whenever referenced as ${...} in the YAML (substitution happens before the enabled check)'.
- **Source:** FINDINGS.json #95 (merged with #340)
- **Also reported (duplicate evidence):**
  - #340 (major): config/config.yaml:656. sentinel/config.py:350-360 (missing var raises ConfigError). Server: sudo sed 's/=.*//' /etc/sentinel/sentinel.env lists TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, TWILIO_WHATSAPP_NUMBER, ALERT_PHONE_NUMBER, ANTHROPIC_API_KEY, TELEGRAM_API_ID, TELEGRAM_API_HASH, EXPO_PUSH_TOKEN, EXPO_ACCESS_TOKEN.

### F-234 [MAJOR]

- **Claim:** §`classification` l.146-161 and l.179-212 list defaults only. `policy` is described as '`{}` | Complete approved v2 policy required in OpenAI mode; the example config contains the resolved choices/ranges'. No sub-keys are documented.
- **Actual:** `ClassificationConfig._validate_direct_policy` (OpenAI mode) requires `policy.version == 2` and a non-empty `policy.monitored_countries`. It requires every `policy.ranges.*` value to be an int pair `[lo, hi]` with 1 ≤ lo ≤ hi ≤ 10. `system_prompt()` must also build, which needs `near_border_strike` ∈ {awareness, log_only, critical} and `neutralised_drone` ∈ {current_danger, original_severity}. It also needs the 14 named range bands: active_attack, official_warning, precaution, nuclear_activity, direct_hostile_threat, routine, reaction, resolved, unclear_location, russian_drone_unresolved_poland, russian_drone_unresolved_other, civilian_or_unknown_ground_drone, capability_escalation. The same validator rejects an OpenAI model ID that does not start with `gpt-`. These keys set the urgency bands the live classifier assigns, so they are among the most consequential tunables. Live values: near_border_strike awareness, neutralised_drone original_severity, monitored_countries PL/LT/LV/EE.
- **Evidence:** sentinel/config.py:242-263; sentinel/classification/policy.py:27-43 and band() uses throughout; config/config.yaml:490-538
- **Suggested fix:** Add a `classification.policy` subsection. It should have a table of version, monitored_countries, near_border_strike (allowed values), neutralised_drone (allowed values) and ranges (named bands with live [lo, hi] values). Add the validation rules and the requirement that the `model` ID starts with `gpt-` when provider is openai.
- **Source:** FINDINGS.json #96

### F-235 [MAJOR]

- **Claim:** Urgency-level table lines 259-260: `high` and `medium` have `channel` = `both`. Line 283 'Behavior-preserving default': the shipped default (`channel: both` with push disabled) sends SMS only, identical to historical behavior.
- **Actual:** Live config sets `channel: push` on both high and medium, and push is enabled, so tiers 5-8 are push-only with no Twilio SMS (owner decision). `both` is only the Pydantic default and the config.example.yaml value. The doc never states the live routing.
- **Evidence:** config/config.yaml:597 (`channel: push` under high), :603 (`channel: push` under medium), :651 (`enabled: true`); config/config.example.yaml high/medium `channel: both`; sentinel/config.py:105 (`channel: str = "both"`)
- **Suggested fix:** Change the table's high/medium channel to `push` (live). Add a sentence: 'Live: tiers 5-8 are push-only on purpose (no Twilio SMS); `both` is the Pydantic default and the config.example.yaml value.' Reword line 283 so the 'SMS only' behaviour is attributed to the template/default, not to production.
- **Source:** FINDINGS.json #104 (merged with #336)
- **Also reported (duplicate evidence):**
  - #336 (major): config/config.yaml:597 and 603 have 'channel: push'. config/config.example.yaml:631 and 637 have 'channel: both'. sentinel/config.py:105 has channel default 'both'.

### F-236 [MAJOR]

- **Claim:** Line 315: 'with push off, a both/push tier still sends SMS only'.
- **Actual:** This holds only for `both`. A tier with `channel: push` while push is disabled or has no tokens sends nothing at all. The state machine sets send_sms only for actions 'sms'/'both'. The push client then no-ops, so a 5-8 alert is silently dropped. The config.example.yaml comment repeats the same wrong claim.
- **Evidence:** sentinel/alerts/state_machine.py:426-427 (`send_push = action in ("push","both","phone_call")`, `send_sms = action in ("sms","both")`); :442-447 (no SMS branch for 'push'); :833-835 (`_maybe_send_push` returns when disabled/no tokens); config/config.example.yaml push comment 'a tier set to push/both still sends SMS only until a token is added'
- **Suggested fix:** State: 'With push disabled or no tokens, a `both` tier sends SMS only, but a `push` tier sends nothing (the alert is dropped silently).' Also add a TODO.md item to correct the misleading comment in config/config.example.yaml (log as TODO item).
- **Source:** FINDINGS.json #105

### F-237 [MAJOR]

- **Claim:** alerts.acknowledgment table line 292: `max_call_retries` live value `5`.
- **Actual:** The live value is 1, capped after the 2026-07-30 call storm. That storm came from fragmented events times 5 calls each. 5 is only the config.example.yaml value; the Pydantic default is 3. The doc also omits that this is calls per round (per dispatch), not a lifetime total.
- **Evidence:** config/config.yaml:647 (`max_call_retries: 1` with storm comment at :640-646); `git show 6429124:config/config.yaml` line 647 same; config/config.example.yaml acknowledgment `max_call_retries: 5`; sentinel/alerts/state_machine.py:576-579 (`max_per_round = ...max_call_retries`, loop `for attempt in range(1, max_per_round + 1)`)
- **Suggested fix:** Set the live value to `1`. Add: 'calls placed per round; capped at 1 since 2026-07-30 because event fragmentation multiplied calls; config.example.yaml still shows 5'.
- **Source:** FINDINGS.json #106 (merged with #337)
- **Also reported (duplicate evidence):**
  - #337 (major): config/config.yaml:647 has 'max_call_retries: 1'. config/config.example.yaml:649 has 'max_call_retries: 5'. sentinel/config.py:118 has the default 3.

### F-238 [MAJOR]

- **Claim:** Line 294: `cooldown_hours` — 'No re-call for same event within this window'. Line 252: `alerts.language` — 'Alert language code'. Table line 258: critical `retry_attempts` 3, `retry_interval_minutes` 5, `fallback` `sms` (presented as working settings).
- **Actual:** No code reads any of these fields: acknowledgment.cooldown_hours, alerts.language, and the per-level UrgencyLevel retry_attempts, retry_interval_minutes and fallback. Call spacing comes only from acknowledgment.retry_interval_minutes. When a 9-10 event has fewer sources than corroboration_required, a hard-coded 'sms' action applies instead of `fallback`; that path sends SMS only, with no push and no channel lookup. TTS language is hard-coded to pl-PL. The doc marks only call_duration_threshold_seconds as dead.
- **Evidence:** grep over sentinel/ and sentinel.py finds no reads of `cooldown_hours`, `retry_attempts`, `.fallback`, or `alerts.language` (only definitions at sentinel/config.py:98-100,120,160); state_machine.py:502-506 (hard-coded `return "sms"`); state_machine.py:566 (call spacing uses acknowledgment.retry_interval_minutes); twilio_client.py:40-48 (`language="pl-PL"` hard-coded)
- **Suggested fix:** Mark `cooldown_hours`, `alerts.language`, and the per-level `retry_attempts` / `retry_interval_minutes` / `fallback` as 'defined but not read (no effect)', as already done for call_duration_threshold_seconds. Note that the below-threshold 9-10 path uses a hard-coded SMS-only action. Log the dead fields as a TODO item.
- **Source:** FINDINGS.json #107 (merged with #311)
- **Also reported (duplicate evidence):**
  - #311 (major): config/config.yaml:647, :597, :603, :650-655, :485 monthly_usd: 30; grep cooldown_hours/retry_attempts sentinel/ -> only sentinel/config.py:98,120

### F-239 [MAJOR]

- **Claim:** Line 309: `sms_update` template is the 'SMS for new sources corroborating an acknowledged event'. Line 315: push fires 'on acknowledged-event updates'.
- **Actual:** An update SMS or push for an acknowledged event is sent only when the event's notification_revision went up. Only an incident-memory 'escalation' decision raises it; new sources and source-count changes do not. With incident_memory disabled, no update is ever sent.
- **Evidence:** sentinel/classification/corroborator.py:375-381 (`escalation = memory_enabled and ... == "escalation"`; `if escalation: event.notification_revision += 1`); sentinel/alerts/state_machine.py:403-413 (comment 'source-count and timestamp changes therefore cannot manufacture an update'; `_has_new_delivered_revision`)
- **Suggested fix:** Reword: 'SMS (and additive push) sent for an already-acknowledged event when incident memory classifies a new article as an escalation (notification_revision increments); new corroborating sources alone do not trigger it.'
- **Source:** FINDINGS.json #108

### F-240 [MAJOR]

- **Claim:** Line 322: 'Optional env var: EXPO_ACCESS_TOKEN ... Not required for basic sends.'
- **Actual:** The production Expo project has 'Enhanced Security for Push Notifications' turned on. A robot access token (EXPO_ACCESS_TOKEN in sentinel.env) was added to neutralise a device token leaked in the public git history. With Enhanced Security on, a send without the bearer token returns UNAUTHORIZED. So production push depends on this variable. The code itself treats it as optional.
- **Evidence:** sentinel/alerts/push_client.py:19-21,27,59-60 (token optional; forwarded only when set); operator record ~/.claude/projects/-home-kossa-code-project-sentinel/memory/project_prod_config_and_routing.md ('NEUTRALIZED by enabling Enhanced Security ... robot access token (EXPO_ACCESS_TOKEN in sentinel.env) ... a raw send with only the leaked device token returns UNAUTHORIZED'). Server state not re-checked (read-only run).
- **Suggested fix:** Say: 'Optional in code, but required in production. The Expo project has Enhanced Security enabled, so sends without EXPO_ACCESS_TOKEN are rejected; if the robot token leaks, rotate it in the Expo dashboard and update sentinel.env.'
- **Source:** FINDINGS.json #109

### F-241 [MAJOR]

- **Claim:** Config Loading table line 8: '${VAR_NAME} — expanded at load time; missing var raises ConfigError' (the only statement of the substitution rules).
- **Actual:** Material omissions. (1) Substitution walks every string in the whole YAML unconditionally, so a ${VAR} in a disabled section still has to be set. (2) There is no default syntax: ${A:-b} looks up a variable literally named 'A:-b'. (3) The live config therefore needs ALERT_PHONE_NUMBER, TELEGRAM_API_ID, TELEGRAM_API_HASH and EXPO_PUSH_TOKEN at load. EXPO_PUSH_TOKEN appears nowhere in the doc's env-var guidance. (4) .env is loaded only if python-dotenv is importable, and it does not override variables already set. (5) In production the variables come from /etc/sentinel/sentinel.env, the systemd EnvironmentFile.
- **Evidence:** sentinel/config.py:347-372 (`_ENV_VAR_PATTERN = r"\$\{([^}]+)\}"`, recursive over dict/list, raises ConfigError on missing), :375-381 (`load_dotenv()` in try/except ImportError); config/config.yaml:463-464,574,656 (TELEGRAM_API_ID, TELEGRAM_API_HASH, ALERT_PHONE_NUMBER, EXPO_PUSH_TOKEN); config/config.example.yaml push comment 'every "${VAR}" here must resolve at load'
- **Suggested fix:** Add a short 'Env-var substitution rules' note. It should say that every ${VAR} anywhere in the file must resolve, even in disabled sections, and that there is no default syntax. List the four variables the live config needs (incl. EXPO_PUSH_TOKEN). Note that .env is loaded via python-dotenv without overriding existing env vars, and that production reads /etc/sentinel/sentinel.env.
- **Source:** FINDINGS.json #110

### F-242 [MAJOR]

- **Claim:** classification.incident_memory, lines 196-198: 'It is enabled in the local/example Luna configuration after the no-send runtime evaluation ... Production rollout is a separate permission boundary.' The classification table header at line 128 is labeled 'Local branch value'.
- **Actual:** Incident memory is ON in production. The live config has incident_memory.enabled: true. Every live Luna classification from the last 14 days carries a non-empty incident_memory payload: 6985 openai rows, all non-'{}'. The values in the 'Local branch value' column are the live production values.
- **Evidence:** config/config.yaml:540-541. Live query on classifications (last 14 days) grouped by incident_memory='{}' returned 0|6985 and 1|197; the 197 rows are pre-deploy legacy Haiku rows. docs/reference/luna-deployment-20260920.md:38 records that memory was enabled at deploy.
- **Suggested fix:** Replace the rollout sentence with: 'Production runs with incident memory enabled since the 2026-09-20 Luna deployment; the Pydantic default stays false for old configurations.' Rename the column to 'Live value'.
- **Source:** FINDINGS.json #338 (merged with #91)
- **Also reported (duplicate evidence):**
  - #91 (major): config/config.yaml:540-542 (`incident_memory:` / `enabled: true`); git show 6429124:config/config.yaml:540-541; docs/reference/luna-deployment-20260920.md:38 ('incident-memory path was enabled with the approved configuration'); config/config.yaml:539 comment

### F-243 [MINOR]

- **Claim:** The classification, summary_language and incident_memory tables (l.128-139, 148-161, 179-184, 201-212) give types and defaults but no validation constraints.
- **Actual:** config.py enforces bounds that make config load fail when violated. max_tokens is 128–4096. timeout_seconds is >0 and ≤120. retry_delay_seconds is ≥1. retry_batch_size is 1–1000. Budget rates must be >0 (cached ≥0) and cache_write_multiplier ≥1. repair_max_tokens is 128–1024; repair_timeout_seconds is >0 and ≤30. fallback_pl is 20–500 chars. detector_languages must have no duplicates and must be lingua ISO-639-1 codes. Incident memory bounds: lookback_hours 1–2160, candidate_pool_size 1–1000, max_candidates 1–20, evidence_per_event 1–5, max_text_chars 100–2000, min_confidence and critical_min_confidence 0.5–1.0, extra_output_tokens 128–1024. Cross-field rules: max_candidates ≤ candidate_pool_size, and critical_min_confidence ≥ min_confidence. Only monthly_usd ≤ 50 and the metric allow-list are documented.
- **Evidence:** sentinel/config.py:174-190, 195-199, 206-227, 235-239, 267
- **Suggested fix:** Add a 'Constraint' column (or a line under each table) listing these bounds and the two cross-field rules for incident_memory.
- **Source:** FINDINGS.json #97

### F-244 [MINOR]

- **Claim:** Classification table header l.128 labels the value column 'Local branch value'. The 'Direct provider, budget and recovery' and incident_memory tables (l.148, l.201) show only defaults.
- **Actual:** Those values come from config/config.yaml, which is byte-identical to the production /etc/sentinel/config.yaml, so they are the live production values, not a local branch. The later tables never give the differing live values: `budget.ledger_path` live is `/var/lib/sentinel/model-usage.db` (default `data/model-usage.db`), and `incident_memory.enabled` live is `true` (default `false`). The template config/config.example.yaml differs: monthly_usd 10, ledger_path data/model-usage.db.
- **Evidence:** docs/reference/config-reference.md:128; config/config.yaml:484-485,541; config/config.example.yaml:509-510
- **Suggested fix:** Rename the column to 'Live value (config/config.yaml)'. Add a 'Live value' column to the direct-provider/budget and incident_memory tables, at least for ledger_path (/var/lib/sentinel/model-usage.db), monthly_usd (30) and enabled (true). Where the template differs, note it (example: monthly_usd 10).
- **Source:** FINDINGS.json #98

### F-245 [MINOR]

- **Claim:** l.134 `corroboration_required` (top-level): '... this top-level key feeds the corroborator's alertable check.'
- **Actual:** The top-level key only switches the stored `alert_status` label between 'phone_call' and 'sms' for urgency ≥ 9 events. Both labels pass the scheduler's alertable filter (`alert_status != "pending"`), which depends only on urgency ≥ 5. The top-level key therefore never decides whether or how an alert is sent. The per-level `alerts.urgency_levels.critical.corroboration_required` (live 1) in `_determine_action` is the only gate: one source triggers a call today.
- **Evidence:** sentinel/classification/corroborator.py:437-444; sentinel/scheduler.py:301; sentinel/alerts/state_machine.py:502-506; config/config.yaml:585
- **Suggested fix:** Reword to: 'Only sets the stored alert_status label (phone_call vs sms) for urgency ≥ 9; it does not affect dispatch. The call gate is alerts.urgency_levels.critical.corroboration_required (live 1, so one source triggers a phone call today).'
- **Source:** FINDINGS.json #99

### F-246 [MINOR]

- **Claim:** Keyword matching rules l.112-118: 'PL/UK/RU: substring matching (handles inflection); EN: word-boundary preferred'. 'Live `exclude_keywords` languages: `en`, `pl`.'
- **Actual:** Several behaviours are missing or wrong. (1) English `exclude_keywords` are applied to every non-English article in addition to that language's own list. For pl/uk/ru the English excludes match as substrings, so uk/ru articles do have exclusions: the EN list. (2) Articles in a language with no keyword set fall back to the `en` keywords. (3) Word-boundary matching is always used for EN and any non-Slavic language; it is not merely 'preferred'. (4) Articles from `keyword_bypass` sources skip the filter entirely. Telegram bypass applies only while telegram is enabled.
- **Evidence:** sentinel/processing/keyword_filter.py:42-49 (fallback to en), :66-69 (English excludes appended for non-en), :186-194 (substring for pl/uk/ru, \b regex otherwise), :21-31 and :104-111 (bypass)
- **Suggested fix:** Add these rules to the list: the English exclude list also applies to non-English articles (as substrings for pl/uk/ru); unknown languages use the `en` keyword set; non-Slavic languages always use word-boundary matching; keyword_bypass sources skip the filter.
- **Source:** FINDINGS.json #100

### F-247 [MINOR]

- **Claim:** §`sources.gdelt` l.59: themes are 'OR-combined with the target-country `sourcecountry:` filter to build the query.'
- **Actual:** The themes are OR-ed with each other, and that group is ANDed (space-joined) with a separate OR group of `sourcecountry:` FIPS codes. `sourcecountry` filters by the publishing outlet's country, not by the attacked country.
- **Evidence:** sentinel/fetchers/gdelt.py:67-85 (`parts.append(f"({theme_query})")`, `parts.append(f"({country_query})")`, `return " ".join(parts)`)
- **Suggested fix:** Reword to: '(theme:A OR theme:B ...) AND (sourcecountry:<FIPS of each monitoring.target_countries code>), where sourcecountry is the publishing outlet's country.'
- **Source:** FINDINGS.json #101

### F-248 [MINOR]

- **Claim:** l.154-155: `retry_delay_seconds` is the 'Delay before reattempting queued failed work'; `retry_batch_size` is the 'Maximum pending articles processed per cycle, oldest arrival first.'
- **Actual:** The doc leaves out that there is no maximum attempt count. A failed article (provider error, budget exhaustion, grouping failure) stays in `classification_queue` and is retried every `retry_delay_seconds` indefinitely. Health reports `degraded` while any queued row has attempts > 0. The batch limit applies to both lanes (fast and slow cycles).
- **Evidence:** sentinel/database.py:167-190 (no attempts cap; degraded = failed > 0); sentinel/scheduler.py:242, 257-260, 270-272, 296-298
- **Suggested fix:** Add: 'Failed articles are retried indefinitely (no attempt cap); every cycle in either lane picks up to retry_batch_size due items, oldest fetched_at first; any row with a failed attempt marks health as degraded.'
- **Source:** FINDINGS.json #102

### F-249 [MINOR]

- **Claim:** Line 389: '`dry_run` runs the complete classification pipeline — only the Twilio dispatch step is skipped. Safe for development and continuous testing.' Line 382: 'Consumed by: sentinel/scheduler.py, sentinel/alerts/'.
- **Actual:** (1) dry_run skips the whole state-machine dispatch, so Expo push is suppressed too, not just Twilio. (2) The corroborator writes alert_status='dry_run' on events. (3) check_pending_calls still polls Twilio for call status. (4) Classification still makes paid model calls (OpenAI gpt-5.6-luna), so it is not free to run continuously. dry_run is read by alerts/dispatcher.py, classification/corroborator.py and sentinel.py, not scheduler.py. eval_set_file is read only by sentinel.py.
- **Evidence:** sentinel/alerts/dispatcher.py:14,45-48 (skips process_event entirely); sentinel/classification/corroborator.py:37,434-435 (returns 'dry_run' status); sentinel/scheduler.py:304-308 (check_pending_calls runs regardless); sentinel.py:204-205,245; no `testing.` read in sentinel/scheduler.py
- **Suggested fix:** Reword: 'suppresses all alert delivery (Twilio call/SMS and Expo push) and marks events alert_status=dry_run; fetching and classification still run and still spend model API money.' Fix 'Consumed by' to sentinel/alerts/dispatcher.py, sentinel/classification/corroborator.py, sentinel.py.
- **Source:** FINDINGS.json #112

### F-250 [MINOR]

- **Claim:** Line 315: push is dispatched 'after the cooldown/dedup/suppression gates' ... 'push is not in the user-notified-alert-types set' ... 'bounded only by its own dedup on a prior push record'. Line 280: 'The urgency 9–10 path always places the call + confirmation/stop SMS'.
- **Actual:** process_event has no cooldown gate and no 'user-notified-alert-types' set. Dedup is per channel and per notification revision: a channel counts as done only after a successful ('sent'/'delivered'/'acknowledged') record for the current notification_revision, so failed pushes retry. The gates are the acknowledged check and the pending-call check. No 'stop SMS' exists. The 9-10 path sends a confirmation-code SMS before the calls and a follow-up SMS after acknowledgment. It places a call only when source_count >= corroboration_required; live is 1, so one source triggers a call today.
- **Evidence:** sentinel/alerts/state_machine.py:400-419 (ack and pending-call gates), :429-447 (per-channel suppression), :513-529 (`_channel_delivered` by revision and successful status), :585 (confirmation SMS), :650-652 (follow-up SMS after ack), :502-506 (corroboration check); config/config.yaml:585 (`corroboration_required: 1` on critical)
- **Suggested fix:** Replace the stale gate wording with: 'after the acknowledged and pending-call gates; each channel is suppressed only by its own successful delivery of the current notification_revision.' Change 'confirmation/stop SMS' to 'confirmation-code SMS (and a follow-up SMS after acknowledgment)'. Add: 'live corroboration_required is 1, so one source triggers a call today.'
- **Source:** FINDINGS.json #113

### F-251 [MINOR]

- **Claim:** Line 334: `jitter_seconds` — 'Random ±offset applied to each scheduled run'.
- **Actual:** APScheduler 3.11 jitter only delays a run, by a random 0..jitter seconds; it never fires early. The fast lane caps jitter at 10 s (min(jitter, 10)), so only the slow lane uses the full 30 s.
- **Evidence:** sentinel/scheduler.py:504 (`IntervalTrigger(minutes=fast_interval, jitter=min(jitter, 10))`), :514 (slow lane `jitter=jitter`); apscheduler.triggers.base.BaseTrigger._apply_jitter → `random.uniform(0, jitter)` (installed 3.11.2)
- **Suggested fix:** Change to: 'Random delay of 0..N seconds added to each run; the fast lane caps it at 10 s, the slow lane uses the full value.'
- **Source:** FINDINGS.json #114

### F-252 [MINOR]

- **Claim:** Acknowledgment table lines 295-297: `call_poll_timeout_seconds`, `call_poll_interval_seconds` and `call_retry_pause_seconds` are listed with live values 90 / 5 / 10. Intro line 287 says inbound SMS is polled 'after each call attempt'.
- **Actual:** The live config omits all three keys, so production runs on the Pydantic defaults. Only config.example.yaml sets them. The reply is checked before each call, during the call's wait loop, after the call, and once more after the round.
- **Evidence:** config/config.yaml:639-650 (acknowledgment block has only call_duration_threshold_seconds, max_call_retries, retry_interval_minutes, cooldown_hours); config/config.example.yaml acknowledgment sets 90/5/10; sentinel/config.py:121-123; state_machine.py:589-590, 754-756, 609-611, 632-634
- **Suggested fix:** Show the live value as '(omitted → 90)', '(omitted → 5)' and '(omitted → 10)', matching the push/testing rows. Say the reply is polled before, during and after each call attempt.
- **Source:** FINDINGS.json #115

## `docs/reference/cli.md`

### F-253 [MAJOR]

- **Claim:** Flag table, `--test-headline` row (line 19): "Hits the live Anthropic API."
- **Actual:** The classifier uses whichever provider the config names. The live config sets `classification.provider: openai`, so `--test-headline` (and `--test-file`, `--eval`) call OpenAI gpt-5.6-luna through OpenAIProvider and record the spend in the budget ledger. The Anthropic client is created only when the provider is not `openai`, which makes it the legacy/rollback path.
- **Evidence:** sentinel/classification/classifier.py:164-165 (`OpenAIProvider(...) if config.classification.provider == "openai" else None`; Anthropic only as fallback); config/config.yaml:471-472 (`provider: openai`); config/config.example.yaml resolves to provider openai, model gpt-5.6-luna (checked via load_config)
- **Suggested fix:** Replace "Hits the live Anthropic API" with "Makes a live, paid call to the configured classifier provider (today OpenAI gpt-5.6-luna; Anthropic Haiku only when `classification.provider` is not `openai`); the cost is recorded in `classification.budget.ledger_path`." Give `--test-file` and `--eval` the same wording.
- **Source:** FINDINGS.json #117 (merged with #307)
- **Also reported (duplicate evidence):**
  - #307 (minor): sentinel/classification/classifier.py:164; config/config.yaml:472

### F-254 [MAJOR]

- **Claim:** `--config` default `config/config.yaml` (line 21), and the Examples block (lines 36-46) presented as working local commands, such as `./run.sh --once --dry-run`.
- **Actual:** `config/config.yaml` is the production config, byte-identical to /etc/sentinel/config.yaml. It uses absolute server paths: database `/var/lib/sentinel/sentinel.db`, log file `/var/log/sentinel/sentinel.log`, budget ledger `/var/lib/sentinel/model-usage.db`, Telegram session `/var/lib/sentinel/sentinel_session`. It also references `${EXPO_PUSH_TOKEN}`, which the local .env does not define. Locally, every `./run.sh` command with the default `--config` therefore exits 1 with `ConfigError: Environment variable 'EXPO_PUSH_TOKEN' is not set`. With that variable set, setup_logging would still try to create `/var/log/sentinel`, which is root-owned. The local-safe config is `config/config.example.yaml`, which uses relative `data/` and `logs/` paths and has push disabled. The systemd unit passes `--config /etc/sentinel/config.yaml` explicitly.
- **Evidence:** config/config.yaml:656 (`"${EXPO_PUSH_TOKEN}"`), :662 (`path: /var/lib/sentinel/sentinel.db`), :667 (`file: /var/log/sentinel/sentinel.log`), :484 (ledger_path /var/lib/sentinel/model-usage.db); `.venv/bin/python -c "load_config('config/config.yaml')"` -> `ConfigError: Environment variable 'EXPO_PUSH_TOKEN' is not set`; local .env key list has no EXPO_PUSH_TOKEN; sentinel/logging_setup.py:28-30 (makedirs of the log dir); /var/lib owned by root 755; load_config('config/config.example.yaml') -> data/sentinel.db, logs/sentinel.log, data/model-usage.db; deploy/configs/sentinel.service:11
- **Suggested fix:** Add a note under the flag table. It should say that the default `config/config.yaml` is the production copy with absolute server paths and `${EXPO_PUSH_TOKEN}`, and that the server unit uses `--config /etc/sentinel/config.yaml`. It should say that local runs must pass `--config config/config.example.yaml` or a local copy with relative paths. Update the local examples to include `--config config/config.example.yaml`.
- **Source:** FINDINGS.json #118

### F-255 [MAJOR]

- **Claim:** Example (line 39): `./run.sh --test-file tests/fixtures/eval_set.yaml`. Line 20 says --test-file loads "a YAML file with a `headlines:` list".
- **Actual:** `tests/fixtures/eval_set.yaml` is a top-level YAML list of 44 cases, each keyed `headline:`. It is not a mapping with a `headlines:` key. `_run_test_file` calls `data.get("headlines", [])`, which raises an unhandled AttributeError on a list. The documented example therefore crashes with a traceback. No fixture under tests/ has a `headlines:` key, so the repo contains no ready-made input for `--test-file`.
- **Evidence:** sentinel.py:340 (`headlines = data.get("headlines", [])`); yaml.safe_load('tests/fixtures/eval_set.yaml') -> <class 'list'> of 44 entries; `grep -rln "headlines:" tests/` returned nothing
- **Suggested fix:** Replace the example with an inline-documented file shape, for example `headlines:` followed by `- text: "..."` and an optional `expected: {urgency_score: 9}`, and point to a user-created file. State that eval-set fixtures (`eval_set*.yaml`) go to `--eval`, not `--test-file`.
- **Source:** FINDINGS.json #119

### F-256 [MAJOR]

- **Claim:** `--dry-run` row (line 18): "suppress **all** Twilio calls/SMS (sets `testing.dry_run = True`). Safe for development."
- **Actual:** Dry-run only skips `AlertDispatcher.dispatch`, which suppresses event calls, SMS and push alike. Everything else still runs. Each article is still classified with live, paid calls to the configured classifier (OpenAI Luna), and the cost is charged to the budget ledger. Articles, the classification queue, classifications and events are still written to the configured DB. In continuous mode, system-health SMS are not gated by dry_run: one fires at 10 consecutive fetcher failures and one at 3 consecutive pipeline failures, both through TwilioClient.send_sms. So "all" and "Safe" overstate the flag.
- **Evidence:** sentinel/alerts/dispatcher.py:14,45-48 (dry_run only skips process_event); sentinel/scheduler.py:229-243 (dedup/enqueue/classify run regardless); sentinel/scheduler.py:458-477 and :551-554 (`_send_system_sms` with no dry_run check); sentinel/alerts/twilio_client.py has no dry_run reference
- **Suggested fix:** Reword the row as follows: "Runs the full pipeline but skips alert dispatch (no calls, SMS or push for events). It still makes live, paid classifier calls and writes articles and events to the configured DB. In continuous mode, system-health SMS (fetcher or pipeline failure) are not suppressed." Remove "Safe for development".
- **Source:** FINDINGS.json #121

### F-257 [MAJOR]

- **Claim:** `--test-alert` row (line 26) and the note on line 31 describe a synthetic event fired via Twilio or Expo, with no side effects or current-state caveats.
- **Actual:** (1) `--test-alert` forces `dry_run = False`. It then persists a synthetic "[TEST]" article and event, plus the alert records, into the configured DB. Run on the server, these land in the production DB. (2) `main()` exits 0 unconditionally after `_run_test_alert`, even when the call or SMS fails. (3) Known state: the Twilio account is deliberately unfunded, so since 2026-09-21 `phone_call` and `sms` test alerts fail with HTTP 401 ("account ... with status 4 is not active"). Calls stay configured and return when the owner recharges the account. (4) `--test-alert sms` sends an SMS directly, although live tiers 5-8 are push-only on purpose.
- **Evidence:** sentinel.py:425 (`config.testing.dry_run = False`), :439 (`db.insert_article(article)`), :462 (`db.insert_event(event)`), :231-232 (`_run_test_alert(...)` then `sys.exit(0)`); sentinel/alerts/state_machine.py:772-780 (`_execute_sms` sends directly and records it); orchestrator-verified owner decisions on Twilio and SMS
- **Suggested fix:** Add to the `--test-alert` row or note: it writes a synthetic [TEST] article and event (and alert records) into the configured DB, which is the production DB when run on the server; it always exits 0, so check the output and logs. Add the known-state note: "Twilio is deliberately unfunded since 2026-09-21; `phone_call`/`sms` currently fail with HTTP 401 until the owner recharges. This is expected, not a defect." Add that `sms` bypasses tier routing even though live tiers 5-8 are push-only.
- **Source:** FINDINGS.json #122

### F-258 [MAJOR]

- **Claim:** Lines 3-8: "Two command-line entry points exist" (sentinel.py and dashboard/cli.py).
- **Actual:** The repo has more runnable entry points. There are six `python -m sentinel.eval.*` modules with their own argparse CLIs: compare_models, rescore_dimensions, cached_runtime, direct_luna, incident_memory and export_candidates. There is also the root script `test_e2e_live.py`, which makes a REAL phone call; its docstring still says "Claude Haiku API call". compare_models, rescore_dimensions and cached_runtime are documented in docs/how-to/model-comparison.md, and direct_luna in docs/how-to/api-setup.md. export_candidates and incident_memory are documented nowhere. export_candidates SSHes to production as deploy@ and runs a read-only `sudo sqlite3` query. incident_memory makes paid classifier calls with `--live`.
- **Evidence:** sentinel/eval/compare_models.py:602-621, rescore_dimensions.py:34-56, cached_runtime.py:304-313, direct_luna.py:171-182 (`--live`, `--max-cost-usd`), incident_memory.py:104-113 (`--live`, `--fixtures`, `--config`, `--case`), export_candidates.py:11-35 (`--from-production` required; ssh -p 2222 deploy@178.104.76.254 'sudo sqlite3 -readonly ...'); test_e2e_live.py:1-19 ("WARNING: This will make a REAL phone call"); grep over *.md: export_candidates and eval.incident_memory have no hits
- **Suggested fix:** Replace "Two command-line entry points exist" with a short list. Keep the two main ones and add a section "Other entry points" with one row each for the six `python -m sentinel.eval.*` modules: purpose, whether it is offline by default or needs `--live`/paid calls or prod SSH, and a link to model-comparison.md or api-setup.md where they are covered. Add `test_e2e_live.py` with a warning that it places a real phone call.
- **Source:** FINDINGS.json #123

### F-259 [MINOR]

- **Claim:** `--health` row (line 24): prints health.json; reports "No health data found" if the pipeline hasn't run.
- **Actual:** health.json is written only by the scheduled lane jobs in continuous mode (`_run_with_error_handling` -> `_update_health`). `--once`, `--diagnostic` and the immediate first cycle of continuous mode do not write it. After those, `--health` still reports "No health data found" even though the pipeline ran. The file sits in the DB's directory, which is `/var/lib/sentinel/health.json` with the default config.
- **Evidence:** sentinel/scheduler.py:536-547 (only call sites of `_update_health`), :596 (path = dirname(database.path)/health.json); sentinel.py:115-124 and :152-169 (run_once and the first continuous cycle call `pipeline.run_cycle()` directly)
- **Suggested fix:** Change the row to: "Prints health.json from the DB's directory (/var/lib/sentinel/health.json with the production config). The file is written only by scheduled cycles of continuous mode, not by `--once`, `--diagnostic` or the first immediate cycle."
- **Source:** FINDINGS.json #124

### F-260 [MINOR]

- **Claim:** `--diagnostic` row (line 25) and example (line 40): writes the report to `data/diagnostic.html`.
- **Actual:** The report goes to `<dirname(database.path)>/diagnostic.html`. With the default `config/config.yaml` that is `/var/lib/sentinel/diagnostic.html`. It is `data/diagnostic.html` only with a relative-path config such as config.example.yaml. `--diagnostic` also still makes live, paid classifier calls; only alerts are suppressed.
- **Evidence:** sentinel.py:139-143 (`os.path.join(os.path.dirname(config.database.path) or "data", "diagnostic.html")`); config/config.yaml:662
- **Suggested fix:** Say "writes diagnostic.html next to the DB: data/diagnostic.html with config.example.yaml, /var/lib/sentinel/diagnostic.html with the production config". Add that classification calls are live and paid.
- **Source:** FINDINGS.json #125

### F-261 [MINOR]

- **Claim:** The only exit-code statement is for `--eval` (line 27). Nothing says what happens when several mode flags are combined.
- **Actual:** `main()` checks modes in a fixed order and runs only the first match: --test-alert, then --test-headline, --test-file, --eval, --health, --diagnostic, --once, then continuous. Exit 1 occurs on a config load error, a `--test-headline` classification failure, `--test-file` file-not-found, invalid YAML or no headlines, and an `--eval` set file not found. `--test-alert` always exits 0.
- **Evidence:** sentinel.py:189-199 (config errors -> exit 1), :230-263 (precedence chain and exits), :311-313, :328-343, :386-388
- **Suggested fix:** Add a short "Mode precedence and exit codes" paragraph that lists the order above and the exit-1 cases. State that `--test-alert` returns 0 even on delivery failure.
- **Source:** FINDINGS.json #126

## `docs/reference/sources.md`

### F-262 [MAJOR]

- **Claim:** RSS Sources table (lines 13-31) lists 17 feeds, with the note 'Do not add sources not present in config — this doc tracks config state'.
- **Actual:** The live config has 20 RSS entries (18 enabled). Three enabled feeds are missing from the doc: Ukrainska Pravda EN (priority 1, fast lane), Kyiv Independent (priority 1, fast lane) and France 24 Europe (priority 3). All three fetch successfully in production.
- **Evidence:** config/config.yaml:365-379 (Ukrainska Pravda EN https://www.pravda.com.ua/eng/rss/view_news/ p1; Kyiv Independent https://kyivindependent.com/feed/rss/ p1; France 24 Europe https://www.france24.com/en/europe/rss p3). Startup log: 'Config loaded: 18 RSS sources, 16 Google News queries, GDELT disabled, Telegram enabled'. 7-day fetch-OK lines: Kyiv Independent 4216, Ukrainska Pravda EN 2161, France 24 Europe 710. DB articles: 155, 377 and 46 respectively.
- **Suggested fix:** Add the three rows to the RSS table with URL, language, priority and enabled=true, so the doc matches config/config.yaml.
- **Source:** FINDINGS.json #372 (merged with #127)
- **Also reported (duplicate evidence):**
  - #127 (major): config/config.yaml sources.rss entries 'Ukrainska Pravda EN', 'Kyiv Independent', 'France 24 Europe'; `git log -S"Kyiv Independent" -- config/config.yaml` -> 9d60198 2026-03-26 (same for France 24 and pravda.com.ua/eng)

### F-263 [MINOR]

- **Claim:** Telegram (line 37): "Polled on fast lane (every 3 min)". Google News (lines 50-69): "Polled on fast lane", with every query marked Lane = fast.
- **Actual:** Telegram is not polled. A persistent telethon client buffers NewMessage events in real time, and every pipeline cycle drains the buffer, both the fast lane (3 min) and the slow lane (15 min). Google News and Telegram also run in the slow lane, because the slow lane is a superset and excludes only GDELT. The Telegram channel `priority` field exists in config but no code uses it; only RSS priority gates the fast lane.
- **Evidence:** sentinel/fetchers/telegram.py:10-17, 58-62, 71-78 (listener plus buffer drain); sentinel/scheduler.py:416-438 (`_SLOW_LANE_FETCHERS = {"gdelt"}`; the full lane fetches everything); sentinel/fetchers/rss.py:38 is the only `.priority` use outside eval/; sentinel/config.py:43-48 (TelegramChannel.priority)
- **Suggested fix:** Telegram: "Persistent listener (telethon) buffers messages in real time; every pipeline cycle (fast 3 min and slow 15 min) drains the buffer. The `priority` field is not used." Google News: "Fetched every fast-lane cycle (3 min) and again in each slow-lane cycle."
- **Source:** FINDINGS.json #128

### F-264 [MINOR]

- **Claim:** Rzeczpospolita row (line 20) shows enabled with no note. The Known Issues table (lines 93-97) lists only PAP, TVN24 and GDELT.
- **Actual:** Rzeczpospolita returns 403 on every slow-lane cycle: 710 of 710 cycles in 7 days, with zero successful fetches. The runbook's Known Issues already records it, but sources.md does not.
- **Evidence:** 7-day census: 710x '[ERROR] sentinel.fetcher.rss: Failed to fetch RSS source Rzeczpospolita: Client error '403 Forbidden' for url 'https://www.rp.pl/rss_main''. 'RSS source Rzeczpospolita: fetched' = 0. '[FULL]' cycles = 710. docs/how-to/server-runbook.md:327 records the issue.
- **Suggested fix:** Add 'Returns 403 from the VPS on every cycle (confirmed 2026-09-20 and 2026-10-03); config kept' to the Rzeczpospolita row's Notes and to the Known Issues table.
- **Source:** FINDINGS.json #373

## `docs/reference/luna-deployment-20260920.md`

### F-265 [MAJOR]

- **Claim:** Migration-specific configuration, lines 41-44: "The application allowance is $10/month ... The OpenAI project also has the separately verified $10 enforced monthly cap."
- **Actual:** The live application allowance is $30/month. Commit 31acd3a (2026-09-24) raised config/config.yaml classification.budget.monthly_usd from 10 to 30 and the validator bound from 20 to 50. That commit is live through deploy-20260925-143105 (6429124). The code default (sentinel/config.py:195) and config/config.example.yaml:510 still say 10. No document on master records whether the OpenAI project's own $10 hard cap was raised. Commit 31acd3a estimates real use at ~$11-17/month, which is above a $10 provider cap.
- **Evidence:** config/config.yaml (classification.budget.monthly_usd: 30); git diff 7048a91 6429124 -- config/config.yaml shows '-    monthly_usd: 10' / '+    monthly_usd: 30'; sentinel/config.py:195 default=10, le=50; git show 31acd3a commit message ('~$11-17 a month by the ledger, so the $10 cap would pause classification around 18 October')
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Since deploy-20260925-143105 (commit 6429124) the live application allowance is $30/month (commit 31acd3a). The code default and config.example.yaml remain $10. The $10 OpenAI project hard cap below is the 2026-09-20 setting; no record shows it was raised. If it is still $10, OpenAI rejects requests with project_spend_limit_exceeded once $10 is spent, and classification pauses (openai_provider.py:187-188) even though the app allowance is $30.' above section 'Migration-specific configuration'.
- **Source:** FINDINGS.json #129 (merged with #333)
- **Also reported (duplicate evidence):**
  - #333 (minor): ssh: git log -1 → 6429124 (tag deploy-20260925-143105); sudo grep /etc/sentinel/config.yaml → '485: monthly_usd: 30'; git log shows 31acd3a 'Raise the monthly model budget to $30' before 6429124; systemctl show DropInPaths=/etc/systemd/system/sentinel.service.d/20-openai.conf

### F-266 [MAJOR]

- **Claim:** Lines 85-91, 'Rollback plan': "Stop the service, select the previous code commit/tag, restore the backed-up live config ..., remove only the newly added 20-openai.conf drop-in". Lines 52-53: "Unlike the old generic skill's wholesale config copy, this deployment merged only reviewed classifier fields". The runbook (server-runbook.md:16-18) links this record as the current deployment record.
- **Actual:** Production no longer runs the release in this record. Two later deploys followed on 2026-09-25: deploy-20260925-141910 (314f1c2) and deploy-20260925-143105 (6429124, live). Today 'the previous code commit/tag' is deploy-20260925-141910, which also runs Luna. So the rollback steps as written would not return to the Anthropic code (2cad033). The current /deploy skill copies config/config.yaml wholesale to /etc/sentinel/config.yaml (SKILL.md step 6c, line 265). The new step 6a drift check now stops a deploy when the live config was edited by hand. A hand-restored backup config would therefore block the next /deploy. The record omits the 2026-09-25 incident: the wholesale sync replaced the server-only absolute ledger_path with the relative data/model-usage.db, and the service stopped for about 10 minutes. Commit 6429124 fixed this. The deploy skill prunes backups to the 10 newest (SKILL.md:288-291), so /home/deploy/backups/deploy-20260920-232235/ is not guaranteed to exist. Current code also supports a config-only rollback (provider: anthropic), as described in docs/how-to/api-setup.md:83-87.
- **Evidence:** git rev-list -n1 deploy-20260925-141910 = 314f1c2, deploy-20260925-143105 = 6429124; .claude/skills/deploy/SKILL.md:180-186 (6a drift check, mentions the 2026-09-25 ledger_path stop), :262-268 (6c wholesale copy), :288-291 (keep last 10); git show 6429124 message ('stopped the service for ~10 minutes (restored from backup)'); sentinel/config.py:232 provider Literal['anthropic','openai']
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** This record describes the 2026-09-20 release only. Production now runs deploy-20260925-143105 (6429124), after deploy-20260925-141910 (314f1c2). On 2026-09-25 the /deploy config sync overwrote the server-only ledger_path and stopped the service for ~10 minutes; 6429124 fixed the path, and /deploy step 6a now stops on server-only config edits. /deploy copies config/config.yaml wholesale (step 6c), so a rollback config must be committed to the repo, not restored by hand. To return to Anthropic, use the config-only rollback in docs/how-to/api-setup.md (provider: anthropic, legacy Haiku model) or the pre-Luna commit 2cad033 explicitly, not "the previous tag". The 20260920 backup directory may have been pruned (keep-10 rule).' above section 'Rollback plan — only on explicit instruction'.
- **Source:** FINDINGS.json #130

## `docs/ideas/HANDOFF-fix-vague-inputs.md`

### F-267 [BLOCKER]

- **Claim:** Opening lines and 'What Needs to Happen': 'Paste this into a fresh Claude Code session'. It says the system 'uses Claude Haiku 4.5 as the classifier' and that the vague-input problem is 'unsolved'. It tells the agent to analyse, quantify (by querying the production DB) and 'Implement the chosen approach'. 'What NOT to Change' protects 'The 10 calibration rules in the classifier prompt'.
- **Actual:** The problem was solved about 8 hours after this handoff was written. Commit 9db4916 (2026-05-22 12:30) 'Add dual-gate content enrichment to fix classifier false positives from vague inputs' added sentinel/processing/enricher.py (heuristic summary≈title gate plus an LLM vagueness gate, then an article-body fetch). sentinel/scheduler.py:157/253/276 runs it on every cycle. The live classifier is gpt-5.6-luna through sentinel/classification/openai_provider.py, using the v2 policy prompt from sentinel/classification/policy.py. The '10 calibration rules' (SYSTEM_PROMPT in classifier.py) are only used on the legacy Anthropic rollback path. Also, GDELT (listed as a live source type) is disabled (config/config.yaml:396 enabled: false). An agent who pastes this prompt would re-implement shipped work against a classifier and prompt that are no longer live.
- **Evidence:** git log: 699b87f 2026-05-22 04:33 (handoff added) then 9db4916 2026-05-22 12:30 (enricher); sentinel/processing/enricher.py:1-6; sentinel/scheduler.py:36,157,253,276; config/config.yaml:472 provider: openai, :555 model: gpt-5.6-luna; sentinel/classification/classifier.py:178-186 (openai path uses policy.messages), :243-246 (SYSTEM_PROMPT only on anthropic path)
- **Suggested fix:** Move the file to docs/archive/ and add a row to docs/archive/README.md: completed handoff, now covered by sentinel/processing/enricher.py and docs/explanation/pipeline.md. Add this banner at the top: '> **[AMENDMENT 2026-10-03]** Do not paste this prompt. The vague-input problem was addressed the same day by dual-gate content enrichment (commit 9db4916, sentinel/processing/enricher.py, run from sentinel/scheduler.py). Production now classifies with gpt-5.6-luna (sentinel/classification/openai_provider.py) using the v2 policy prompt in sentinel/classification/policy.py. Haiku and the classifier.py SYSTEM_PROMPT rules are the legacy rollback path only. GDELT is disabled.'
- **Source:** FINDINGS.json #269

### F-268 [MINOR]

- **Claim:** 'Key files' lists `sentinel/fetcher/` (rss.py, google_news.py, telegram.py, gdelt.py) and `sentinel/pipeline.py — orchestration, filtering, dedup`. The Key Files table lists `sentinel/fetcher/*.py` and `sentinel/pipeline.py`.
- **Actual:** No `sentinel/fetcher/` directory or `sentinel/pipeline.py` has ever existed, not even at the commit that added this doc. The fetchers live in `sentinel/fetchers/`. Orchestration lives in `sentinel/scheduler.py`, with filtering and dedup in `sentinel/processing/` (keyword_filter.py, deduplicator.py, normalizer.py, enricher.py).
- **Evidence:** ls sentinel/ → no pipeline.py, fetchers/ exists; git log --all -- sentinel/pipeline.py sentinel/fetcher/rss.py → empty; git ls-tree 699b87f shows sentinel/fetchers/*.py and sentinel/scheduler.py
- **Suggested fix:** Fold this into the single archive banner above: 'Paths in this handoff are wrong: fetchers are in sentinel/fetchers/, orchestration is in sentinel/scheduler.py, and filtering/dedup/enrichment are in sentinel/processing/.'
- **Source:** FINDINGS.json #270

## `docs/ideas/classifier-calibration-roadmap.md`

### F-269 [MAJOR]

- **Claim:** Line 5: '**Current state:** 50 human-labeled articles, 10 calibration rules in system prompt, action-tier accuracy at 98%.' Step 4 says to add few-shot examples 'to the system prompt'. Lines 62, 111 and 149 reason about cost and prompt size for 'Haiku'. Lines 158-167 prescribe a `labeled_data/dev_set.yaml` / `holdout_set.yaml` layout.
- **Actual:** The 'current state' is stale (doc undated; written 2026-05-22). Production classifies with gpt-5.6-luna using the frozen v2 policy prompt built by sentinel/classification/policy.py from config classification.policy. That prompt's hash aa4d4ca8… equals the frozen benchmark prompt hash, and the module header says 'Keep frozen v2 messages stable'. The '10 calibration rules' are the legacy classifier.py SYSTEM_PROMPT, used only on the Anthropic rollback path. Adding few-shot examples there would change nothing in production, and editing policy.py would break the frozen v2 contract. The dev/holdout split was realised differently: tests/fixtures/model_comparison_v2_development.yaml (36 cases) and model_comparison_v2_holdout.yaml (64 synthetic cases). No labeled_data/ directory exists. The roadmap's source-type diversity step lists GDELT, which is disabled.
- **Evidence:** config/config.yaml:472,489-490,555; sentinel/classification/policy.py:1,156-157; python: prompt_hash(config.classification.policy) == aa4d4ca8853bc1cc0852241bec01faeec065cbe163c1448c7828ba56a33f5115; sentinel/classification/classifier.py:178-186 vs 243-246; git log 699b87f 2026-05-22; config/config.yaml:396
- **Suggested fix:** Add above 'Next Steps': '> **[AMENDMENT 2026-10-03]** The "current state" line describes the May 2026 Haiku prompt. Production now runs gpt-5.6-luna with the frozen v2 policy prompt (sentinel/classification/policy.py, parameters in config classification.policy). The 10 rules in classifier.py SYSTEM_PROMPT are the legacy rollback path only. The dev/holdout split now exists as tests/fixtures/model_comparison_v2_development.yaml and model_comparison_v2_holdout.yaml; see docs/ideas/model-comparison-v2-run-record.md. Changing the v2 prompt changes its frozen hash and needs a fresh evaluation.' Also consider moving the file to docs/archive/, because it is a superseded plan.
- **Source:** FINDINGS.json #271

## `docs/ideas/incident-memory-plan.md`

### F-270 [MAJOR]

- **Claim:** Line 3: "Status: implemented on `fix/incident-memory`, opt-in and not deployed ... Production deployment requires operator approval." Lines 117-119: "The retained Haiku setup has not demonstrated the USD 20/month target. Keep memory disabled until ..." Lines 22 and 80 describe memory as part of 'the existing Haiku classification request'.
- **Actual:** Incident memory is merged to master (8864861) and live in production. It shipped with deploy-20260920-232235 (7048a91), and 8864861 is an ancestor of the deployed 6429124. The live config/config.yaml sets classification.incident_memory.enabled: true; the code default (sentinel/config.py:154) is False. Memory now runs inside the OpenAI gpt-5.6-luna request through the policy prompt (sentinel/classification/policy.py:53, 119-148), not Haiku. The model ceiling is a $30/month app allowance, not USD 20. luna-deployment-20260920.md:37-38 records that memory was enabled with the approved configuration.
- **Evidence:** git merge-base --is-ancestor 8864861 6429124 -> true; config/config.yaml (incident_memory: enabled: true, lookback_hours 168, min_confidence 0.85, critical_min_confidence 0.9); sentinel/config.py:154 enabled: bool = False; sentinel/scheduler.py:160
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Superseded status: incident memory was merged to master (8864861) and enabled in production on 2026-09-20 with the Luna deployment (deploy-20260920-232235). It is still live in deploy-20260925-143105. It now runs inside the direct OpenAI gpt-5.6-luna classification request, not Haiku. The Haiku cost projections and the USD 20 ceiling below are historical; the live app allowance is $30/month. The code default stays enabled: false; config/config.yaml enables it.' above the 'Status:' line.
- **Source:** FINDINGS.json #132

## `docs/ideas/luna-direct-api-migration-plan.md`

### F-271 [MAJOR]

- **Claim:** Header, lines 3-5: "Production deployment requires separate permission." Budget, line 52: "The operator's maximum model objective is $20/month". 'Operator budget update', lines 122-124: "selected a **$10 monthly limit** ... as the active allowance ... Local/example YAML and the code default now use $10." Line 134: "$10/month enforced hard spend limit".
- **Actual:** The plan is implemented and deployed. The doc records this only at the bottom (lines 171-176), not up front. The active application allowance is now $30/month in config/config.yaml (commit 31acd3a, live since deploy-20260925-143105). The code default and config.example.yaml remain $10. No record shows whether the OpenAI project hard cap is still $10. The deployment record linked at the end is itself superseded by two 2026-09-25 deploys.
- **Evidence:** config/config.yaml classification.budget.monthly_usd: 30; config/config.example.yaml:510 monthly_usd: 10; sentinel/config.py:195 default=10; git tag deploy-20260925-143105 -> 6429124
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Status: implemented and deployed (deploy-20260920-232235). Production now runs deploy-20260925-143105 (6429124). The active application allowance is $30/month in config/config.yaml (commit 31acd3a); the code default and config.example.yaml stay at $10. The OpenAI project hard cap was $10 on 2026-09-20 and is not recorded as raised. The $20 and $10 figures below are historical.' above section 'Evidence and scope'.
- **Source:** FINDINGS.json #133

## `docs/ideas/luna-direct-api-validation-20260920.md`

### F-272 [MINOR]

- **Claim:** Line 54: "The remaining rollout issue is Polish-output reliability." Lines 55-58 say a safeguard must be designed before rollout. The doc has no forward link to the fix.
- **Actual:** The Polish-language defect was addressed by the Polish summary guard (docs/ideas/polish-summary-guard.md; sentinel/classification/summary_language.py). The guard and Luna were deployed on 2026-09-20 (deploy-20260920-232235) and remain live. A reader of this record alone would take the rollout as still blocked.
- **Evidence:** git log: aed7ed8 (this record) -> 7048a91 'Guard Polish alert summaries with bounded translation and safe fallback' -> deploy-20260920-232235; git merge-base --is-ancestor 7048a91 6429124 -> true
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** The Polish-output issue below was addressed by the Polish summary guard (polish-summary-guard.md, commit 7048a91). Luna with the guard was deployed on 2026-09-20 (see docs/reference/luna-deployment-20260920.md) and is live today.' above section 'Reproduced Polish-language defect'.
- **Source:** FINDINGS.json #135

## `docs/ideas/model-comparison-labels.md`

### F-273 [MINOR]

- **Claim:** The labels are presented as the first-round annotations, for example 'mc-scramble-pl-01 … 9–10; PL; initial; critical=true' under 'The current shelter/air-alert calibration rule' and 'Current safety plumbing treats…'. The doc does not say these labels encode the legacy pre-v2 prompt policy.
- **Actual:** The first50 labels follow the legacy Haiku-era prompt. The live v2 policy relabels several of the same articles in tests/fixtures/model_comparison_v2_development.yaml. For example, mc-scramble-pl-01 is 2–3, silent, not critical; mc-scramble-pl-02 is initial; mc-scramble-pl-06 is update; and several Rusinowo reports are 1–4. sentinel/eval/compare_models.py still defaults to this first50 dataset (DEFAULT_DATASET) with the legacy prompt unless --policy-file is given. A reader could score the live v2 classifier against outdated expectations.
- **Evidence:** tests/fixtures/model_comparison_first50.yaml vs tests/fixtures/model_comparison_v2_development.yaml (dump: mc-scramble-pl-01 2 3 silent False); sentinel/eval/compare_models.py:29,613
- **Suggested fix:** Add above 'Label interpretation': '> **[AMENDMENT 2026-10-03]** These first-round labels encode the legacy (pre-v2) prompt policy. Production now uses policy v2. For the live policy use tests/fixtures/model_comparison_v2_development.yaml (see model-comparison-v2-label-review.md), which changes several labels here, e.g. mc-scramble-pl-01 and the Rusinowo follow-ups.'
- **Source:** FINDINGS.json #276

## `docs/ideas/model-comparison-plan.md`

### F-274 [MINOR]

- **Claim:** 'Prepared status' (lines 64-76): 'Prepared on 2026-09-20… no release evaluation is approved yet… No paid inference was run during preparation.' The doc gives no execution outcome or successor.
- **Actual:** The first round was later executed on the 34 development cases with all four models (data/eval/model-comparison-development-20260920.json, started 2026-09-20T15:19Z). Its review (data/eval/model-comparison-review-20260920.md, gitignored) found prompt-policy contradictions that led to the v2 plan. The outcome of the effort was Luna in production. A reader sees only 'prepared' and has no pointer to the v2 plan or the outcome. Because the review file is gitignored, the first-round result is recorded in no tracked doc.
- **Evidence:** data/eval/model-comparison-development-20260920.json (models: 4, started_at 2026-09-20T15:19:19Z); data/eval/model-comparison-review-20260920.md:1-5 ('uses the 34 development cases only'); git check-ignore → ignored; commit 31f0298 'Separate model understanding from runtime behaviour in evaluation'
- **Suggested fix:** Add above 'Prepared status': '> **[AMENDMENT 2026-10-03]** Executed 2026-09-20 on the development split only. Its review (data/eval/model-comparison-review-20260920.md, local and untracked) found legacy-prompt contradictions and was superseded by docs/ideas/model-comparison-v2-plan.md. The effort ended with Luna in production (docs/reference/luna-deployment-20260920.md).' Consider moving this completed plan to docs/archive/.
- **Source:** FINDINGS.json #275

## `docs/ideas/model-comparison-v2-holdout-notes.md`

### F-275 [MINOR]

- **Claim:** 'Policy ambiguity flags' (lines 43-46): the near-border strike and neutralised-drone scoring choices are each called an 'unresolved scoring choice'.
- **Actual:** The operator resolved both choices on 2026-09-20 (tests/fixtures/benchmark_policy_v2.yaml status: resolved). They are live in config classification.policy as near_border_strike: awareness and neutralised_drone: original_severity. The fixture still excludes such cases, as the holdout review states, but calling the choices 'unresolved' is now false.
- **Evidence:** tests/fixtures/benchmark_policy_v2.yaml (status: resolved, operator_decisions.confirmed_at 2026-09-20); config/config.yaml:494-495; docs/ideas/model-comparison-v2-holdout-review.md:68
- **Suggested fix:** Add above 'Policy ambiguity flags': '> **[AMENDMENT 2026-10-03]** Both choices were resolved on 2026-09-20 (awareness 5–6; original severity 7–8). See model-comparison-v2-plan.md and config classification.policy. This fixture still contains no case that tests either choice.'
- **Source:** FINDINGS.json #277

## `docs/ideas/model-comparison-v2-plan.md`

### F-276 [MAJOR]

- **Claim:** Line 3: 'Scope: evaluation only… Do not modify the production classifier, runtime configuration or alert routing.' Implementation item 1: 'evaluation-only policy/prompt bundle… never silently mix it with the legacy classification prompt.' Lines 64-66: 'Deployment, runtime prompt replacement, article-body extraction and model migration remain separate decisions after this benchmark.' The doc ends at 'Preparation status' and gives no outcome.
- **Actual:** The bundle this plan defines as evaluation-only is now the production prompt. On 2026-09-20 commit 0cdb3cb moved the prompt into sentinel/classification/policy.py (sentinel/eval/clarified_policy.py now only re-exports it). The deployment tag deploy-20260920-232235 (7048a91) put it live with gpt-5.6-luna. Live config classification.policy (version 2, near_border_strike: awareness, neutralised_drone: original_severity) yields exactly the frozen prompt hash aa4d4ca8…. A reader who trusts the 'evaluation only' scope could treat edits to policy.py or classification.policy as harmless to production.
- **Evidence:** sentinel/eval/clarified_policy.py:1,7; sentinel/classification/policy.py:1; config/config.yaml:489-499; python prompt_hash(config policy) == aa4d4ca8…; git tag deploy-20260920-232235; docs/reference/luna-deployment-20260920.md 'Release and backup' table
- **Suggested fix:** Add above 'Policy decisions': '> **[AMENDMENT 2026-10-03]** Outcome: this v2 policy prompt went to production on 2026-09-20 (tag deploy-20260920-232235) with gpt-5.6-luna. It now lives in sentinel/classification/policy.py and is parameterised by config classification.policy, whose prompt hash equals the frozen aa4d4ca8…. It is no longer evaluation-only, so any change to it changes live classification. See docs/reference/luna-deployment-20260920.md.' Also consider moving this completed plan to docs/archive/.
- **Source:** FINDINGS.json #272

## `docs/ideas/model-comparison-v2-run-record.md`

### F-277 [MAJOR]

- **Claim:** Line 126: 'Luna is the strongest candidate for the next integration/shadow test, not an approved production replacement.' Lines 220-225 ('Next step'): 'Do not deploy a model change…'. Lines 29-34 list Luna via OpenRouter, pinned provider `openai`. Cost section (lines 198-218): Luna estimate $4.39/month from 5,917 classifications/month, with 'substantial headroom beneath $20'.
- **Actual:** Luna was deployed to production on 2026-09-20 (tag deploy-20260920-232235) through the direct OpenAI API (config classification.api_base_url https://api.openai.com/v1), not OpenRouter. Incident memory was enabled. Haiku is now the rollback path only. Measured production volume and cost differ materially from the estimate. Commit 31acd3a records 420-580 classifications/day and about $11-17/month by the ledger, so the monthly cap was raised to $30 (config classification.budget.monthly_usd: 30). A reader could conclude that Luna is not live or could size budgets from the $4.39 figure.
- **Evidence:** git tag deploy-20260920-232235 / docs/reference/luna-deployment-20260920.md; config/config.yaml:472-473,485,540,555; git show 31acd3a message 'Luna runs 420-580 classifications a day, ~$11-17 a month by the ledger'
- **Suggested fix:** Add above 'Held-out results and recommendation': '> **[AMENDMENT 2026-10-03]** Outcome: Luna (gpt-5.6-luna) became the production classifier on 2026-09-20 via the direct OpenAI API, not OpenRouter, with incident memory enabled. See docs/reference/luna-deployment-20260920.md. Haiku is now the rollback path only. The $4.39/month estimate below was too low: production runs about 420-580 classifications/day, about $11-17/month by the ledger, and the cap is $30 (config classification.budget.monthly_usd).'
- **Source:** FINDINGS.json #273

## `docs/ideas/model-runtime-comparison-20260920.md`

### F-278 [MAJOR]

- **Claim:** Line 15: 'The memory feature is enabled only in the local evaluation configuration.' Lines 194-197 (Recommendation): '…investigate the inconsistent awareness classification and test fresh news plus repeated identical inputs before switching production.' Line 56: 'No production files, settings, model choice or server state are changed.'
- **Actual:** Production was switched the same day. Commit 0cdb3cb set incident_memory.enabled: true (it was false at 7acd20a, the commit of this report). Tag deploy-20260920-232235 deployed direct Luna. The same confidence gates (min_confidence 0.85, critical_min_confidence 0.9) and corroboration_required 1 that this replay used are the live values. The replay's Luna gate results therefore describe the live configuration, which this record does not say. A reader would think memory is still eval-only and that the production switch is still pending.
- **Evidence:** git show 7acd20a:config/config.yaml:475 'enabled: false'; config/config.yaml:540-548 (enabled: true, 0.85/0.9); data/eval/v2-runtime-holdout-20260920-luna-corrected.json classification_config.incident_memory + alert_levels.critical.corroboration_required=1; git log 0cdb3cb, tag deploy-20260920-232235
- **Suggested fix:** Add above 'Cost, checks and recommendation': '> **[AMENDMENT 2026-10-03]** Outcome: production switched to direct Luna with incident memory enabled on 2026-09-20 (tag deploy-20260920-232235; see docs/reference/luna-deployment-20260920.md and docs/ideas/luna-direct-api-validation-20260920.md for the follow-up repeated-input checks). The memory gates tested here (0.85 / critical 0.9) and corroboration_required 1 are the live values. DeepSeek was not adopted, and there is no automatic fallback.'
- **Source:** FINDINGS.json #274

## `docs/ideas/polish-summary-guard.md`

### F-279 [MINOR]

- **Claim:** Lines 37-38: "Production deployment still needs separate permission." Section 'Deployment preparation only' (lines 83-94): the server checkout was `2cad033`. Lines 18-19: "Repair uses the same monthly ledger and remaining test allowance". The doc has no status line up front.
- **Actual:** The guard (GUARD_VERSION 'polish-summary-v1', sentinel/classification/summary_language.py:18) shipped in 7048a91, deployed as deploy-20260920-232235. It is still live in 6429124. In production, repair calls count only against the $30/month application ledger. The explicit test spending cap (openai_provider.py:173) applies only to the paid test runs.
- **Evidence:** git merge-base --is-ancestor 7048a91 6429124 -> true; sentinel/classification/summary_language.py:18,58-93; sentinel/database.py:124 (summary_processing column); config/config.yaml classification.summary_language and budget.monthly_usd: 30
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Status: deployed to production on 2026-09-20 (deploy-20260920-232235, commit 7048a91) and still live in deploy-20260925-143105. In production, repair requests count against the monthly application allowance ($30), not a test allowance. The deployment-permission and server-checkout statements below are historical.' above the first paragraph.
- **Source:** FINDINGS.json #134

## `docs/archive/HANDOFF_audit-findings-2026-05-23.md`

### F-280 [MINOR]

- **Claim:** Line 68 (Issue #1 'Fix'): 'Edit **two locations**: `config/config.yaml` (local, if used) AND the production config at `/etc/sentinel/config.yaml` on the VPS (see [docs/server-runbook.md]...)'. Line 3 also says 'Status: Open. None of the items below are addressed in code yet.'
- **Actual:** The top-of-file HISTORIC banner exists. But an agent that greps '/etc/sentinel/config.yaml' lands on line 68, which tells it to hand-edit the live server config. Today the routine is to edit and commit the tracked config/config.yaml and let /deploy step 6c sync it. /deploy step 6a now stops the deploy when the server has its own edits, so a hand-edit like this creates exactly the drift that 6a blocks. The same handoff contradicts itself at line 288 ('do NOT modify server files manually'). The link docs/server-runbook.md is broken; the file is now docs/how-to/server-runbook.md.
- **Evidence:** docs/archive/HANDOFF_audit-findings-2026-05-23.md:68 versus :288. In .claude/skills/deploy/SKILL.md, :180-185 is 6a ('Config drift check... a server-only edit that the config sync (6c)...') and :262-268 is 6c ('copies the repo config ... to the live path').
- **Suggested fix:** Add above the '### Fix' heading of Issue #1 (just before line 68): '> **[AMENDMENT 2026-10-03]** Do not hand-edit `/etc/sentinel/config.yaml`. Today config changes are made in the tracked `config/config.yaml`, committed, and synced by `/deploy` step 6c. Step 6a stops the deploy when the server has its own edits. The runbook is now docs/how-to/server-runbook.md.'
- **Source:** FINDINGS.json #284

### F-281 [MINOR]

- **Claim:** Links at L6, L155, L224, L273 `data/audit-reports/audit-2026-05-23.md`, L68 `docs/server-runbook.md`, L285 `CLAUDE.md`
- **Actual:** These links were written relative to the repo root. After the move to docs/archive/ (df4f6ea) they resolve to nonexistent paths. The audit report itself exists at the repo-root path but is gitignored (not tracked), and the runbook moved to docs/how-to/server-runbook.md.
- **Evidence:** test -e docs/archive/data/audit-reports/audit-2026-05-23.md -> missing; git status --ignored -> '!! data/audit-reports/audit-2026-05-23.md'; docs/how-to/server-runbook.md exists
- **Suggested fix:** Add '> **[AMENDMENT 2026-10-03]** Links in this archived handoff are relative to the repo root: the audit report is the untracked local file data/audit-reports/audit-2026-05-23.md, the runbook is now docs/how-to/server-runbook.md, CLAUDE.md is ../../CLAUDE.md.' above the title.
- **Source:** FINDINGS.json #315

## `docs/archive/README.md`

### F-282 [MINOR]

- **Claim:** Table row for HANDOFF_audit-findings-2026-05-23.md (line 22): 'Tracked/resolved in ../../TODO.md'.
- **Actual:** TODO.md does not track the nuclear-keyword gap; a search for 'nuclear' in TODO.md returns no matches. The gap was resolved in config: config/config.yaml now contains 'nuclear strike', 'nuclear drill(s)', 'nuclear forces' and a nuclear_activity entry. A reader who follows the pointer to TODO.md finds nothing.
- **Evidence:** `grep -n -i nuclear TODO.md` returns nothing; config/config.yaml:37, :41-42, :92 and :509 contain nuclear vocabulary.
- **Suggested fix:** Add above the 'What's in here' table: '> **[AMENDMENT 2026-10-03]** The 2026-05-23 audit's nuclear-keyword gap (Issue #1) is resolved in config/config.yaml (monitoring keywords include nuclear strike/drill/forces); it is not tracked in TODO.md.'
- **Source:** FINDINGS.json #23

## `docs/archive/prompts/corroboration-removal.md`

### F-283 [MINOR]

- **Claim:** Lines 1-3: '# Corroboration Removal — Agent Directive. You are making a config-only change... reducing the corroboration threshold for phone call alerts from 2 independent sources to 1... Follow each step in order.' There is no historic banner.
- **Actual:** The change was already applied and is the live state: config/config.yaml has corroboration_required: 1 under classification and under the critical tier. If an agent re-runs the directive, it does nothing or fails, and it may make a stray commit. The file has no marker that says it was completed, and the README says so only at folder level. An agent that greps 'corroboration_required' lands here first and reads an imperative directive as pending work. The code default for the critical tier is still 2 (sentinel/config.py:269). The file's '~line' anchors are stale (the live keys are at config/config.yaml:561 and :585, not ~391/~400).
- **Evidence:** docs/archive/prompts/corroboration-removal.md:1-3 (no banner), :37 and :46 (stale line anchors). config/config.yaml:561 and :585 both have corroboration_required: 1. sentinel/config.py:97 defaults to 1 and :269 to 2. git log shows c238c15 'Add optimized agent prompt for corroboration removal'.
- **Suggested fix:** Add a dated banner as line 1: '> **[AMENDMENT 2026-10-03]** HISTORIC — this directive was carried out. Live config/config.yaml already has corroboration_required: 1 (classification and the critical tier), so one source triggers a phone call today. Do NOT re-run it. Whether to require 2 sources again is an open owner question in TODO.md.'
- **Source:** FINDINGS.json #283

## `docs/archive/prompts/implement-audit-remediation.md`

### F-284 [MAJOR]

- **Claim:** Line 1-3: '# Sentinel Audit Remediation — Agent Directive / You are implementing fixes to Project Sentinel... Follow each step in order.' There is no historic banner. Lines 183-200 tell the agent to run seven `./run.sh --test-headline "..."` commands, and lines 31-85 tell it to edit SYSTEM_PROMPT in sentinel/classification/classifier.py and to commit.
- **Actual:** This is a completed 2026-05 directive. An agent that reaches this file by grep (for example on 'SYSTEM_PROMPT', 'poderwał' or 'Agent Directive') sees no historic marker, because only docs/archive/README.md marks the prompts/ folder as historic. If the agent acts on it, it re-edits a classifier prompt that has since changed. It also makes live model calls through --test-headline, which spends API money (the live classifier is now openai gpt-5.6-luna, not the Haiku the prompt names on line 8).
- **Evidence:** docs/archive/prompts/implement-audit-remediation.md:1-3 (no banner), :186-199 (--test-headline calls), :8 ('Claude Haiku 4.5 classifies'). The SYSTEM_PROMPT the directive targets still exists at sentinel/classification/classifier.py:20. Compare the HANDOFF/SPEC files in the same folder, which each carry the '> ⚠️ **HISTORIC — archived 2026-05-30.**' banner on line 1.
- **Suggested fix:** Add a dated banner as line 1: '> **[AMENDMENT 2026-10-03]** HISTORIC — completed directive (applied 2026-05, commit 7651e3f era). Do NOT execute: the classifier prompt and keyword lists have since changed, the live classifier is OpenAI gpt-5.6-luna, and the `./run.sh --test-headline` steps make paid live model calls. See docs/archive/README.md.'
- **Source:** FINDINGS.json #280

## `docs/archive/prompts/phase-1-orchestrator.md`

### F-285 [MAJOR]

- **Claim:** Lines 5-10 and 24-99: 'You are an orchestrator agent... Working directory: /home/kossa/code/project-sentinel'. It tells the agent to create the package structure, spawn Opus agents with `mode: "auto"` that write sentinel/models.py, sentinel/config.py, sentinel/database.py, sentinel.py and tests, run `python sentinel.py --config config/config.example.yaml --dry-run --once`, and commit 'Implement Phase 1'. There is no historic banner.
- **Actual:** All of these files already exist and have evolved far past Phase 1. If an agent acts on the directive, it overwrites shipped code without permission prompts. The `--once` step runs a real fetch-and-classify cycle, because dry_run only suppresses alerts (sentinel.py:204-205). That cycle makes paid model calls. The prompt also reads files that no longer exist at those paths: docs/phase-1-infrastructure.md, docs/architecture.md (now docs/explanation/architecture.md) and prompts/phase-1-agent-*.md (now under docs/archive/prompts/). The sibling files phase-1-agent-1/2/3 also have no banner.
- **Evidence:** docs/archive/prompts/phase-1-orchestrator.md:1-10 (no banner), :70 (--dry-run --once), :99 (commit), :110 ('mode: "auto"'). `ls` shows sentinel.py, sentinel/models.py, sentinel/config.py and sentinel/database.py all exist. sentinel.py:47 defines --once, and :204-205 shows that dry_run only sets config.testing.dry_run. `head -3 docs/archive/prompts/phase-1-agent-*.md` shows no banner on any of them.
- **Suggested fix:** Add a dated banner as line 1 of phase-1-orchestrator.md, and the same banner to phase-1-agent-1-models-config.md, phase-1-agent-2-database-cli.md and phase-1-agent-3-tests.md: '> **[AMENDMENT 2026-10-03]** HISTORIC — original Phase 1 bootstrap prompt, completed long ago. Do NOT execute: every file it creates already exists, so running it would overwrite shipped code, and its `--once` step makes paid live model calls. See docs/archive/README.md.'
- **Source:** FINDINGS.json #281

## `docs/archive/prompts/sentinel-audit.md`

### F-286 [MAJOR]

- **Claim:** Lines 1-11: '# Sentinel Daily Audit — Skill Prompt... Your job: pull the latest data from the production server'. Lines 99-103 and 227-231 read and overwrite `data/audit-reports/.last-audit-timestamp`. Lines 21-22 say 'require 2+ independent sources for phone calls' and 'Phone call (urgency 9-10 + 2 sources), SMS (7-8), WhatsApp (5-6)'. Lines 20 and 62 say the classifier is Haiku 4.5. There is no historic banner.
- **Actual:** This is a superseded draft of the living skill .claude/skills/sentinel-audit/SKILL.md. Both versions read and write the same .last-audit-timestamp file. If an agent runs this stale draft, it advances that timestamp, and the next run of the living skill silently skips that window of articles. The draft also teaches facts that are wrong today. One source triggers a call, because critical corroboration_required is 1 (config/config.yaml:585). Tiers 5-8 are push-only; there is no WhatsApp tier. The live classifier is OpenAI gpt-5.6-luna. Its SSH recipe uses deploy@ and read-only commands, so that part is safe.
- **Evidence:** docs/archive/prompts/sentinel-audit.md:1 (no banner), :21-22, :102, :230. The living skill uses the same file at .claude/skills/sentinel-audit/SKILL.md:108 and :264. config/config.yaml:561 and :585 both have corroboration_required: 1.
- **Suggested fix:** Add a dated banner as line 1: '> **[AMENDMENT 2026-10-03]** HISTORIC — superseded draft. The living audit is the `/sentinel-audit` skill (.claude/skills/sentinel-audit/SKILL.md). Do NOT run this draft: it writes the same `.last-audit-timestamp` file and would make the living skill skip a window. Its pipeline facts are stale. Today one source triggers a phone call, tiers 5-8 are push-only (no WhatsApp), and the live classifier is OpenAI gpt-5.6-luna.'
- **Source:** FINDINGS.json #282

## `DECISIONS.md`

### F-287 [MAJOR]

- **Claim:** Forward-looking status lines read as current: line 96 'NOT merged to master / NOT deployed — that is the owner's step'; line 205 same for Phase 1; lines 256-259 'OWNER FOLLOW-UP (do at merge)… They MUST be updated in the same change that merges this branch to master'; line 290 'PAUSED per owner instruction: runner stopped after Phase 2; Phases 3-4 await his go.'
- **Actual:** As of 2026-10-03 none of redesign-phase0-geography (e4f9e54), redesign-phase1-alerting (145a412) or redesign-phase2-policy (8c441e7) is merged into master or the deployed tag (6429124). None has had a commit since 2026-07-12, and Phases 3-4 never started. Master has since diverged a lot: the Luna/OpenAI migration, incident memory, the clarified-v2 policy in a different sentinel/classification/policy.py, push-only tiers 5-8, calls muted 2026-07-30 and restored 2026-07-31, and a deliberately unfunded Twilio account since 2026-09-21. The branches' AlertPolicy/GeoWeighter (sentinel/alerts/policy.py, geo_weighter.py) do not exist on master, and corroboration is still live there with corroboration_required: 1. A reader may conclude a merge is pending and imminent, and that the 'update CLAUDE.md at merge' instruction applies to master.
- **Evidence:** git merge-base --is-ancestor <branch> master → NOT-MERGED for all three; git log -1 on each branch → 2026-07-11/12; ls sentinel/alerts/policy.py sentinel/classification/geo_weighter.py → absent; config/config.yaml:561,585 corroboration_required: 1; git log 0cdb3cb (2026-09-20 Luna), 2cad033 (2026-07-31 restore calls)
- **Suggested fix:** Add at the top of the file: '> **[AMENDMENT 2026-10-03]** Status: redesign Phases 0-2 remain UNMERGED on branches redesign-phase0-geography / redesign-phase1-alerting / redesign-phase2-policy (last commits 2026-07-11/12). Phases 3-4 were never started. Master has since diverged: the Luna/OpenAI classifier (docs/reference/luna-deployment-20260920.md), incident memory, push-only tiers 5-8, calls restored 2026-07-31 (config/config.yaml comment) and the deliberately unfunded Twilio account since 2026-09-21. Corroboration is still live on master with corroboration_required: 1. The "do at merge" follow-ups below apply only if those branches are ever rebased and merged. This file logs only the redesign run; later owner decisions are not recorded here.'
- **Source:** FINDINGS.json #264

### F-288 [MINOR]

- **Claim:** Line 71: '[Phase 0] Gitignored `DECISIONS.md` and the new state dir — DECISIONS.md is a local review artifact and keeping it untracked…'; lines 220/228: the phase-2 state dir 'added to .gitignore'.
- **Actual:** DECISIONS.md is tracked on master, committed in 5b07d2a ('Back up work-in-progress', 2026-08-28). That commit also tracked .code-refiner-state-redesign-phase0/ and .code-refiner-state-redesign-phase2/. Neither DECISIONS.md nor the redesign-phase* state dirs are in master's .gitignore, which lists .code-refiner-state-phase2/ but not -redesign-phase2/.
- **Evidence:** git ls-files DECISIONS.md → tracked; git show 5b07d2a --stat; git check-ignore DECISIONS.md → not ignored; .gitignore:11-32
- **Suggested fix:** Fold into the top amendment banner: 'DECISIONS.md and the .code-refiner-state-redesign-phase0/-phase2 dirs were committed to master in 5b07d2a (2026-08-28) and are tracked, despite the Phase-0 line saying they are gitignored.'
- **Source:** FINDINGS.json #265

## `MOBILE_APP_START_HERE.md`

### F-289 [MAJOR]

- **Claim:** The whole file is a June handoff. It says: 'Worktree branch: `mobile-push-app` (base: master @ df4f6ea). Created 2026-06-01'. It says the main repo 'lives at /home/kossa/code/project-sentinel on branch docs-overhaul. Don't touch it'. It calls `ExpoPushClient` 'currently a no-op (Expo projectId not provisioned + push disabled)' and plans to 'add a token-registration route'. It warns that 'This worktree has no Python .venv'.
- **Actual:** The file is obsolete on every point. No `mobile-push-app` branch exists locally or on origin. The mobile worktree is gone: `git worktree list` shows only project-sentinel (master), project-sentinel-buildtree and sentinel-mobile (detached HEAD at dbeaaf9). The work was merged to master and is live since deploy-20260603-114957. Push is enabled with a provisioned projectId. The token-registration route was explicitly made a Non-Goal (PUSH_APP_SPEC Appendix A). The main checkout is on master, not docs-overhaul. As a tracked file at the repo root it would mislead an agent into treating the repo as a do-not-touch worktree.
- **Evidence:** `git branch -a` (no *mobile* branch); `git worktree list`; `git tag --contains 20b74f2` → deploy-20260603-114957; mobile/app.json projectId; config/config.yaml `push: enabled: true`; mobile/PUSH_APP_SPEC.md:31-34
- **Suggested fix:** Move the file to docs/archive/MOBILE_APP_START_HERE.md (do not delete it). Add at the top: '> **[ARCHIVED 2026-10-03]** Historical June 2026 handoff. The mobile-push-app branch and worktree no longer exist; push and inbox were merged to master and live since 2026-06-03. Current docs: docs/explanation/mobile-app.md, docs/how-to/mobile-push-setup.md.' Add an entry to docs/archive/README.md.
- **Source:** FINDINGS.json #179 (merged with #314)
- **Also reported (duplicate evidence):**
  - #314 (major): git log -- MOBILE_APP_START_HERE.md -> 444889b; mobile/app.json:43 real projectId; config/config.yaml:650-651; TODO.md:97 'live in production 2026-06-03'; grep -rn MOBILE_APP_START_HERE *.md -> no references

## `review_report_pending.md`

### F-290 [MAJOR]

- **Claim:** The whole file is a 'Phase 2 Review — Single AlertPolicy + GeoWeighter' with 'Verdict: PASS'. It states that corroboration was removed, '606 tests pass', and cites code at sentinel/alerts/policy.py:184, sentinel/classification/geo_weighter.py, sentinel/eval/harness.py:34 and corroborator.py:240/432 line numbers. Finding 1 says CLAUDE.md:21's corroboration rule is stale.
- **Actual:** This is a transient /workflow-code-refiner artifact from 2026-07-12 15:01 about the unmerged branch redesign-phase2-policy. It is gitignored and untracked. It is not pending anything: the night-watch closed Phase 2 later the same day (DECISIONS.md:276-290). Against master and production it is wrong. sentinel/alerts/policy.py and geo_weighter.py do not exist; sentinel/classification/policy.py is an unrelated Luna prompt module. Corroboration is still live (corroboration_required: 1). Master collects 583 tests, not 606, and CLAUDE.md's corroboration bullet describes master, not the branch. A reader at the repo root could take its 'corroboration deleted / PASS' as the current state.
- **Evidence:** .gitignore:14 (review_report_pending.md); ls -la → Jul 12 15:01; ls sentinel/alerts/policy.py sentinel/classification/geo_weighter.py → absent on master; .venv/bin/pytest --co -q → 583 tests collected; config/config.yaml:561; DECISIONS.md:276-290
- **Suggested fix:** Add at the top: '> **[AMENDMENT 2026-10-03]** HISTORICAL, not pending. This is the 2026-07-12 blind review of the UNMERGED branch redesign-phase2-policy (8c441e7). It does not describe master or production: AlertPolicy/GeoWeighter do not exist on master, and corroboration is still live there with corroboration_required: 1. Phase 2 was closed the same day (DECISIONS.md "Phase 2 — CLOSED").' Then recommend that the owner move it next to DECISIONS.md under docs/archive/ (or delete it, since it is untracked).
- **Source:** FINDINGS.json #266

