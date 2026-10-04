export const meta = {
  name: 'doc-truth-audit',
  description: 'Audit every documentation claim against the actual code and (optionally) the live production state (read-only) → FINDINGS.md',
  phases: [
    { title: 'Audit', detail: 'code-truth + prod-truth read-only auditors (file-scoped)' },
    { title: 'Merge', detail: 'dedup + rank → FINDINGS.md + FINDINGS.json' },
  ],
}

// ---------------------------------------------------------------------------
// CONFIG — overridable via `args` (object or JSON string); tokens (double-underscore placeholders) stamped
// by the orchestrator. Date.now() unavailable — date must be passed in.
// ---------------------------------------------------------------------------
const raw = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const REPO = raw.repo || '/home/kossa/code/project-sentinel'
const OUT = raw.outDir || '/home/kossa/code/project-sentinel/_temp/doc-sync-2026-10-03'
const TODAY = raw.date || '2026-10-03'
const AGENT_MODEL = raw.agentModel || 'opus'
const MAX_AUDITORS = raw.maxAuditors || 30   // interview question (d) may lower/raise this via args

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['docFile', 'claim', 'actual', 'evidence', 'severity', 'suggestedFix'],
        properties: {
          docFile: { type: 'string', description: 'repo-relative path of the documentation file the finding is about' },
          claim: { type: 'string', description: 'what the doc states (or omits), quoted or tightly paraphrased, with an anchor (section/line)' },
          actual: { type: 'string', description: 'what the code / prod actually shows' },
          evidence: { type: 'string', description: 'file:line, command run + key output line, or API response fragment (NEVER a secret value)' },
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'], description: 'blocker = would cause an agent to act wrongly; major = materially wrong or missing; minor = cosmetic/stale detail' },
          suggestedFix: { type: 'string', description: 'concrete edit suggestion for the doc' },
        },
      },
    },
  },
}

async function runAgent(prompt, opts) {
  let r = null
  for (let i = 0; i < 2 && r === null; i++) r = await agent(prompt, opts)
  return r
}

const CODE_COMMON = `You are a documentation-accuracy auditor for the repo ${REPO}. Read your target doc file COMPLETELY, then verify EVERY factual claim in it against the actual code: every referenced path exists, every function/getter/table/job name matches, described behavior matches the implementation (read the source), counts are correct, status claims ('LIVE', 'shipped', 'not built', dates) match reality (use git log when helpful). ALSO report material OMISSIONS: things the code does in this doc's area that a future agent would need but the doc doesn't say. Do NOT edit any file. Do NOT touch production or any network service. Report ONLY discrepancies/omissions via the structured output schema (empty findings array if the doc is fully accurate). Do not report stylistic preferences — factual accuracy and material omissions only.

RUN CONTEXT (verified by the orchestrator on 2026-10-03 — treat as true, do not re-litigate):
- Repo HEAD (master) = 282947f. PRODUCTION runs tag deploy-20260925-143105 = commit 6429124. The only difference between them is .claude/skills/deploy/SKILL.md (new step 6a, config drift check). A commit being at HEAD does not make it live; check against the deployed commit before calling anything live.
- The server file /etc/sentinel/config.yaml is byte-identical to the repo file config/config.yaml. So config/config.yaml = the live production values; config/config.example.yaml = the template; sentinel/config.py = code defaults. Docs must keep these three apart.
- Live classifier: provider openai, model gpt-5.6-luna (sentinel/classification/openai_provider.py). The Anthropic Claude Haiku path is legacy / rollback only. Many docs still say Haiku — verify each mention.
- Owner decisions: (1) SMS is switched off on purpose; urgency tiers 5-8 are push-only. (2) The Twilio account is deliberately left unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 'account ... with status 4 is not active'. This is a KNOWN STATE, not a bug: phone calls stay configured and return when the owner recharges the account. Docs should describe it as a known state (runbook troubleshooting), never as an outage or defect. (3) The live critical tier has corroboration_required: 1, so ONE source triggers a phone call today. Docs that claim an independent second source is required are wrong against live behavior: the suggestedFix is 'describe that one source triggers a call today' plus a TODO.md item asking the owner whether to require 2. Never suggest changing the config.
- This is a DOCS-ONLY run. If you discover a code or server defect, report it as a finding against TODO.md with suggestedFix 'log as TODO item' (never suggest a code change as the fix of a doc finding).
- APPEND-ONLY classes: SPEC.md, DECISIONS.md, mobile/PUSH_APP_SPEC.md, mobile/INBOX_APP_SPEC.md, everything in docs/ideas/ and docs/archive/, dated records such as docs/reference/luna-deployment-20260920.md, review_report_pending.md. For these the only allowed fix is a dated banner, so word the suggestedFix as: add '> **[AMENDMENT 2026-10-03]** ...' above section X. Do not report historical narrative that was true when written unless a reader would take it as current truth.
- SAFETY: never run the bot or anything that sends alerts or spends API money: no ./run.sh --once, --test-alert, --test-headline, --eval, no live model calls. Allowed: reading files, git log/show, grep, .venv/bin/pytest --co (collection only), ./run.sh --help, python -c imports.
- Put exact evidence in every finding (file:line). Quality over speed: read the source, do not guess.`

// PROD_COMMON is only used when the interview chose code+prod scope. The
// orchestrator stamps the access recipe (ssh wrapper / credential file paths /
// runbook sections) discovered during reconnaissance. If scope is code-only,
// leave PROD_TASKS empty — PROD_COMMON is then never used.
const PROD_COMMON = `You are a production-truth auditor for the repo ${REPO}. You have READ-ONLY authorization for the production system and external service APIs. HARD RULES: (1) read-only — for HTTP use GET only, for the DB use SELECT only, never restart/edit/PATCH/POST/DELETE anything, never write any file on the production host; (2) never print secret VALUES — print variable NAMES, file paths, lengths, or masked fragments only; (3) keep remote commands short and non-interactive.
ACCESS RECIPE:
ssh -p 2222 -o ConnectTimeout=15 deploy@178.104.76.254 '<command>' — runs <command> on the production VPS as user deploy (key login, passwordless sudo). NEVER use root@ or kossa@ (fail2ban bans the IP). If an ssh connection fails twice, stop and report UNVERIFIABLE; do not hammer the host. Batch several read commands into one ssh call where practical.
Paths: app code /home/deploy/sentinel (git checkout), live config /etc/sentinel/config.yaml, env files /etc/sentinel/*.env, state /var/lib/sentinel (sentinel.db, model-usage.db, health.json), logs /var/log/sentinel, backups /home/deploy/backups, systemd unit sentinel.service.
sudo is allowed ONLY to read: sudo cat / ls / stat / tail / grep / journalctl / systemctl status|show|cat|is-active|list-timers / sqlite3 -readonly ... 'SELECT ...' / crontab -l / ufw status / fail2ban-client status / sshd -T. Forbidden: any restart/stop/start/reload/enable, any editor, git pull/checkout/fetch, pip, rm/mv/cp/tee/redirects on the host, sqlite3 without -readonly, running the bot or its CLI flags.
Secrets: for env files print KEY NAMES only (sudo sed 's/=.*//' file). Never cat a credential, token, key or session file. Mask phone numbers, tokens and account SIDs in your output.
The main doc is docs/how-to/server-runbook.md; read the sections named in your task first.
First read the relevant runbook sections named in your task so you know exactly what the docs CLAIM, then verify each claim against live state. If something is genuinely unverifiable with your access, report it as a finding with severity minor, actual='UNVERIFIABLE: <why>'. Report via the structured schema; findings must reference the doc file whose claim you checked. Empty findings array if everything matches.

RUN CONTEXT (verified by the orchestrator on 2026-10-03 — treat as true, do not re-litigate):
- Repo HEAD (master) = 282947f. PRODUCTION runs tag deploy-20260925-143105 = commit 6429124. The only difference between them is .claude/skills/deploy/SKILL.md (new step 6a, config drift check). A commit being at HEAD does not make it live; check against the deployed commit before calling anything live.
- The server file /etc/sentinel/config.yaml is byte-identical to the repo file config/config.yaml. So config/config.yaml = the live production values; config/config.example.yaml = the template; sentinel/config.py = code defaults. Docs must keep these three apart.
- Live classifier: provider openai, model gpt-5.6-luna (sentinel/classification/openai_provider.py). The Anthropic Claude Haiku path is legacy / rollback only. Many docs still say Haiku — verify each mention.
- Owner decisions: (1) SMS is switched off on purpose; urgency tiers 5-8 are push-only. (2) The Twilio account is deliberately left unfunded, so since 2026-09-21 every Twilio call and SMS fails with HTTP 401 'account ... with status 4 is not active'. This is a KNOWN STATE, not a bug: phone calls stay configured and return when the owner recharges the account. Docs should describe it as a known state (runbook troubleshooting), never as an outage or defect. (3) The live critical tier has corroboration_required: 1, so ONE source triggers a phone call today. Docs that claim an independent second source is required are wrong against live behavior: the suggestedFix is 'describe that one source triggers a call today' plus a TODO.md item asking the owner whether to require 2. Never suggest changing the config.
- This is a DOCS-ONLY run. If you discover a code or server defect, report it as a finding against TODO.md with suggestedFix 'log as TODO item' (never suggest a code change as the fix of a doc finding).
- APPEND-ONLY classes: SPEC.md, DECISIONS.md, mobile/PUSH_APP_SPEC.md, mobile/INBOX_APP_SPEC.md, everything in docs/ideas/ and docs/archive/, dated records such as docs/reference/luna-deployment-20260920.md, review_report_pending.md. For these the only allowed fix is a dated banner, so word the suggestedFix as: add '> **[AMENDMENT 2026-10-03]** ...' above section X. Do not report historical narrative that was true when written unless a reader would take it as current truth.
- SAFETY: never run the bot or anything that sends alerts or spends API money: no ./run.sh --once, --test-alert, --test-headline, --eval, no live model calls. Allowed: reading files, git log/show, grep, .venv/bin/pytest --co (collection only), ./run.sh --help, python -c imports.
- Put exact evidence in every finding (file:line). Quality over speed: read the source, do not guess.`

// ---------------------------------------------------------------------------
// STAMP: CODE_TASKS — one entry per doc file (or tight group). Authored by the
// orchestrator from the repo's doc inventory. Each hint tells the auditor what
// the doc covers and which source dirs/files to verify against, plus any known
// suspicions worth checking.
//   { label: 'doc:CLAUDE.md', doc: 'CLAUDE.md', hint: 'The orientation file. Verify: commands table vs package.json scripts; every status bullet; every referenced path; rules routing table vs .claude/rules/ contents.' },
// Special duties worth assigning to one auditor each (proven pattern):
//   - size self-check: wc -l -c on every always-loaded doc vs the binding limits, paths: frontmatter presence (head -5)
//   - TODO auditor: verify OPEN items are genuinely open (vs code/git log); do not audit historical narrative
//   - spec-banner hunters: read banners/status of each SPEC*.md, spot-check top load-bearing normative claims vs code — hunting drift that deserves a DATED AMENDMENT BANNER (specs are never rewritten)
// ---------------------------------------------------------------------------
const CODE_TASKS = [
  { label: "doc:CLAUDE.md+rules+README", doc: "CLAUDE.md, .claude/rules/corroboration.md, README.md", hint: "Audit these THREE files (report each finding with its own docFile). CLAUDE.md is the always-loaded orientation file: verify every critical rule, every quick-reference flag vs the argparse parser in sentinel.py, stack line (lanes, intervals, GDELT) vs config/config.yaml and sentinel/scheduler.py, classification model line, every linked doc path exists. corroboration.md: verify every number and function name vs sentinel/classification/corroborator.py, sentinel/alerts/state_machine.py and config; check whether incident memory (sentinel/classification/incident_memory.py) and revision-aware notifications change what the rule says; check its paths: frontmatter. README.md: every claim." },
  { label: "doc:docs-index", doc: "docs/README.md, docs/archive/README.md, docs/how-to/security/README.md", hint: "Index files. Verify every link resolves (test -e), every file under docs/ (ls -R docs) is reachable from an index or deliberately archived, blurbs describe what the target file actually contains today, Diataxis placement is right (e.g. is docs/reference/luna-deployment-20260920.md a reference or a dated record; is docs/ideas/ indexed)." },
  { label: "doc:architecture-A", doc: "docs/explanation/architecture.md", hint: "Audit ONLY the first half of the file (from the top through the end of the data-model / dataclass sections — roughly lines 1-230; another auditor owns the rest). Verify the module table against the real tree (find sentinel -name \"*.py\"), every dataclass/field against sentinel/models.py and sentinel/classification/schema.py, classifier description vs sentinel/classification/classifier.py and openai_provider.py, and report missing modules (openai_provider, policy, schema, summary_language, incident_memory, sentinel/eval/*)." },
  { label: "doc:architecture-B", doc: "docs/explanation/architecture.md", hint: "Audit ONLY the second half of the file (roughly line 231 to the end; another auditor owns the first half): alert state machine, channel routing, scheduler lanes, DB schema tables/columns/indexes vs sentinel/database.py (include classification_queue and every migration-added column), cost/budget notes vs the classification.budget ledger, error handling, async notes, known limitations. Read sentinel/alerts/*.py, sentinel/scheduler.py, sentinel/database.py fully." },
  { label: "doc:pipeline", doc: "docs/explanation/pipeline.md", hint: "Walk the real pipeline in sentinel/scheduler.py stage by stage (fetch, normalize, dedup, keyword filter, classify, corroborate, alert) and compare with the doc. Check: classifier provider/model, retry queue (classification_queue), budget gating, incident-memory candidates, Polish summary guard (sentinel/classification/summary_language.py), revision-aware notifications (commit 8864861), tier routing and message bodies vs sentinel/alerts/state_machine.py, twilio_client.py, push_client.py and config/config.yaml." },
  { label: "doc:mobile-explanation", doc: "docs/explanation/mobile-app.md, mobile/CLAUDE.md, mobile/AGENTS.md", hint: "Verify against mobile/ (app.json, package.json, src tree, tests) and the server side sentinel/alerts/push_client.py + alerts.push config. Check every referenced path, script name, dependency, push payload field, inbox behavior, live push routing (tiers 5-8 push-only, additive push on 9-10), Enhanced Push Security / EXPO_ACCESS_TOKEN if the code uses it." },
  { label: "doc:config-reference-A", doc: "docs/reference/config-reference.md", hint: "Audit ONLY the first half (top through the classification section, roughly lines 1-240; another auditor owns the rest). For every documented key: exists in sentinel/config.py (Pydantic model), default correct, constraint correct, live value (config/config.yaml) and template value (config/config.example.yaml) correctly labelled. Then the reverse: every key in config.py for these sections that the doc omits. Cover sources, keywords/monitoring, processing, classification incl. provider, model, reasoning effort, policy, summary_language, budget, incident_memory, retry/queue settings." },
  { label: "doc:config-reference-B", doc: "docs/reference/config-reference.md", hint: "Audit ONLY the second half (from the alerts section to the end, roughly line 240 onward; another auditor owns the first half): alerts.urgency_levels (channel, action, corroboration_required, retry fields), acknowledgment (max_call_retries live 1), push block (live enabled), scheduler, database, logging, testing/eval, env-var substitution rules. Same method: doc vs sentinel/config.py vs config/config.yaml vs config/config.example.yaml, both directions." },
  { label: "doc:cli+sources", doc: "docs/reference/cli.md, docs/reference/sources.md", hint: "cli.md: every flag, default, choice and exit code vs build_parser() in sentinel.py and run.sh; python -m sentinel.eval.* entry points (are they documented anywhere, should cli.md point to them). sources.md: every source row (name, URL, language, priority, lane, enabled, keyword_bypass) vs config/config.yaml and the fetchers in sentinel/fetchers/; Telegram channels; Google News queries; GDELT state." },
  { label: "doc:luna-records", doc: "docs/reference/luna-deployment-20260920.md, docs/ideas/luna-direct-api-migration-plan.md, docs/ideas/luna-direct-api-validation-20260920.md, docs/ideas/polish-summary-guard.md, docs/ideas/incident-memory-plan.md", hint: "Dated records and plans (append-only class). For each: is its status (plan / implemented / deployed / superseded) stated up front and true today (git log, code, config)? Which statements would a reader wrongly take as current (budget 10 vs live 30 USD, rollout pending vs live, rollback procedure still valid vs the systemd drop-in and env files named in docs/how-to/server-runbook.md)? Suggest dated banners only." },
  { label: "doc:setup", doc: "docs/how-to/api-setup.md, docs/tutorials/getting-started.md", hint: "Verify every env var vs .env.example and what the code actually reads (grep -rn \"environ\\|getenv\" sentinel/ and ${VAR} in config/*.yaml), the complete .env template, every setup command vs run.sh / requirements.txt / pyproject.toml, account steps (OpenAI, Twilio, Telegram, Expo, OpenRouter for evals), budget numbers, and that a newcomer following getting-started ends with a working dry run." },
  { label: "doc:testing+model-comparison", doc: "docs/how-to/testing.md, docs/how-to/model-comparison.md", hint: "testing.md: every command, test file grouping, fixture table vs ls tests tests/fixtures, mocking description vs tests/conftest.py and the provider tests, eval harness default path and pass criteria vs sentinel.py and sentinel/eval/harness.py; run .venv/bin/pytest tests/ -q --co | tail -3 for the count. model-comparison.md: every module, flag, fixture, number and status claim vs sentinel/eval/*.py (use python -m sentinel.eval.<mod> --help only), and whether it still says production uses Haiku." },
  { label: "doc:mobile-howto+specs", doc: "docs/how-to/mobile-push-setup.md, docs/how-to/mobile-inbox-verification.md, MOBILE_APP_START_HERE.md, mobile/PUSH_APP_SPEC.md, mobile/INBOX_APP_SPEC.md", hint: "How-to files: verify commands, paths, config keys, build steps vs mobile/ and alerts.push config. MOBILE_APP_START_HERE.md is a June handoff naming a worktree and branches: check with git branch -a and git worktree list whether it is obsolete (suggest archiving to docs/archive/ with a banner, not deletion). The two SPEC files are append-only: read status banners, spot-check the top load-bearing normative claims vs code, and report only drift that deserves a dated amendment banner (e.g. spec says phase pending but it is merged and live)." },
  { label: "doc:runbook-code-side", doc: "docs/how-to/server-runbook.md", hint: "Code-side audit only (prod auditors check the live host). Compare the deploy procedure with .claude/skills/deploy/SKILL.md step by step (incl. the new step 6a stop-on-server-only-config-edits and renumbered 6b-6f; note 6a exists at HEAD but check what is deployed is irrelevant here since the skill runs locally), systemd unit and drop-ins vs deploy/configs and deploy/*.sh, cron/backup/health scripts vs deploy/scripts, log rotation vs config logging section, config section (push off / block omitted claims vs live config), Luna rollout section, troubleshooting table (is the Twilio 401 unfunded-account known state covered; is live-config-behind-repo row still right), Known Server Hazards." },
  { label: "doc:vps-hardening", doc: "docs/how-to/security/vps-hardening.md", hint: "Code-side audit: every step and config snippet vs deploy/01-harden-server.sh, deploy/02-deploy-app.sh, deploy/03-setup-services.sh and deploy/configs/*. Check ports, users, fail2ban jail values, ufw rules, unit hardening directives, paths, and whether the doc is a record of what was done or a procedure (and labelled as such)." },
  { label: "doc:TODO", doc: "TODO.md", hint: "TODO auditor. For EVERY open item: is it genuinely still open (check code, config, git log)? For items marked done: really done? Flag sections built on the retired Haiku classifier (model-escalation plan, cost tables). Do not audit historical narrative. Also report as findings against TODO.md (suggestedFix: add item) these known unlogged defects if not already listed: Ukraine-only shelter orders with empty affected_countries classified urgency 9 and attempting a call (events 03ec67e2 on 2026-10-02 and f63c6f6d on 2026-10-03); stray world-readable /home/deploy/sentinel/.env on the server; owner decision pending on corroboration_required 1 vs 2 for the critical tier; events stuck in retry_pending may place stale calls once Twilio is recharged (verify in sentinel/alerts/state_machine.py and sentinel/scheduler.py whether that can actually happen before asserting it); dead RSS feeds." },
  { label: "doc:deploy-skill", doc: ".claude/skills/deploy/SKILL.md", hint: "Verify every step, command, path, tag format, backup target, service name, venv rebuild condition, config sync logic (6a-6f) and verification step against deploy/, the runbook, sentinel.service and the real git history of deploy tags (git tag). Internal consistency of step numbering and cross-references. Check it agrees with docs/how-to/server-runbook.md." },
  { label: "doc:audit+dashboard-skills", doc: ".claude/skills/sentinel-audit/SKILL.md, .claude/skills/dashboard/SKILL.md, dashboard/CLAUDE.md", hint: "sentinel-audit skill: every path, command, DB table/column, log location, classifier/model assumption (Haiku vs Luna), alert channel assumption (SMS vs push-only), ssh recipe vs current reality. dashboard skill + dashboard/CLAUDE.md: commands, ports, paths, stack vs dashboard/ (package.json, backend entry, frontend), and the claim that the dashboard is local-only and not part of the runtime." },
  { label: "doc:SPEC+DECISIONS", doc: "SPEC.md, DECISIONS.md, review_report_pending.md", hint: "Append-only class. SPEC.md is the living dashboard spec: read its status banners, spot-check the top ~15 load-bearing normative claims vs dashboard/ code, report only drift that deserves a dated amendment banner. DECISIONS.md: check forward-looking claims (e.g. lines about branch redesign-phase2-policy making CLAUDE.md stale; does that branch exist, is it merged — git branch -a, git log) and whether newer decisions (Luna migration, push-only tiers, Twilio unfunded, call restore) are absent and should be appended. review_report_pending.md: what is it, is it still pending, should it be archived." },
  { label: "doc:ideas-model-comparison", doc: "docs/ideas/model-comparison-plan.md, docs/ideas/model-comparison-labels.md, docs/ideas/model-comparison-v2-plan.md, docs/ideas/model-comparison-v2-run-record.md, docs/ideas/model-comparison-v2-label-review.md, docs/ideas/model-comparison-v2-holdout-notes.md, docs/ideas/model-comparison-v2-holdout-review.md, docs/ideas/model-comparison-v2-development-independent-review.md, docs/ideas/model-runtime-comparison-20260920.md, docs/ideas/classifier-calibration-roadmap.md, docs/ideas/HANDOFF-fix-vague-inputs.md", hint: "Append-only records and plans. For each file: one check of status-up-front (plan / executed / superseded / outcome) vs reality (git log, sentinel/eval, tests/fixtures, live config), referenced paths exist, and whether a reader would wrongly take a stale statement as current (e.g. production uses Haiku, Luna not adopted, rollout pending). Suggest one dated banner per file at most, only where it prevents a wrong action. Also flag files that belong in docs/archive/." },
  { label: "doc:archive", doc: "docs/archive/HANDOFF_audit-findings-2026-05-23.md, docs/archive/SPEC_ALERT_GROUPING.md, docs/archive/SPEC_ASYNC_REFACTOR.md, docs/archive/prompts/corroboration-removal.md, docs/archive/prompts/implement-audit-remediation.md, docs/archive/prompts/sentinel-audit.md, docs/archive/prompts/phase-1-orchestrator.md", hint: "Archived material. Light audit: is each file clearly marked historic at the top (or covered by docs/archive/README.md), and does any of them contain an instruction that an agent finding it by grep could act on harmfully today (e.g. a prompt telling it to remove corroboration, edit production, or a stale ssh recipe with root@)? Report only those; suggest a dated banner." },
  { label: "special:size+crossdoc", doc: "CLAUDE.md", hint: "SPECIAL DUTY, not a normal file audit; report each finding against the file it concerns. (1) Size self-check: wc -l -c on CLAUDE.md, .claude/rules/*.md, dashboard/CLAUDE.md, mobile/CLAUDE.md, mobile/AGENTS.md, scripts and every SKILL.md; flag always-loaded files over 200 lines and check rules frontmatter (head -8). (2) Cross-document sweep over ALL tracked *.md (git ls-files \"*.md\"): grep for every stale formulation and list each hit file:line as a finding unless it sits in an append-only historic file: Haiku / claude-haiku / Anthropic as the live classifier; ANTHROPIC_API_KEY as required; push off / block omitted; channel both as live; max_call_retries 5; budget 10 or 20 USD as live; deployed tag or commit older than deploy-20260925-143105 / 6429124 presented as current; SMS presented as a live channel; corroboration needs 2 sources; worktree project-sentinel-mobile; old project names twilio-playground / sentinel paths; venv/ instead of .venv/. (3) Dead relative links across all tracked markdown (resolve each [text](path) and test -e). (4) Untracked or stray doc-like files in the repo root or data/ that docs reference or that should be gitignored (git status --ignored -s | head -40)." }
]

// ---------------------------------------------------------------------------
// STAMP: PROD_TASKS — one entry per "service card" built from the project's
// runbook during reconnaissance (see references/prod-task-patterns.md for the
// proven msigalert card set: vps-core, db-schema, error-tracking, uptime,
// analytics, backup, email, dns/alerting). Empty array when scope = code-only.
//   { label: 'prod:vps-core', prompt: `${PROD_COMMON}\n\nTARGET: ...numbered read-only checks, each mapping a doc claim to a command...` },
// ---------------------------------------------------------------------------
const PROD_TASKS = [
  { label: "prod:host-core", prompt: `${PROD_COMMON}

TARGET: the live host vs docs/how-to/server-runbook.md (read it fully first) and docs/reference/luna-deployment-20260920.md.
1. Deployed code: git -C /home/deploy/sentinel log -1 --format='%h %d %s' and git -C /home/deploy/sentinel status --short | head — vs the runbook's Current deployment line and the directory-layout section (every listed path: ls -la each).
2. systemd: systemctl cat sentinel.service (unit + drop-ins), systemctl show sentinel -p User,ExecStart,EnvironmentFiles,Restart,NRestarts,ActiveEnterTimestamp — vs every claim about the unit, drop-in names, hardening directives, StartLimit placement.
3. Env files: sudo ls -la /etc/sentinel and KEY NAMES ONLY of each *.env — vs the documented variables, owners and modes. Check the stray /home/deploy/sentinel/.env (ls -la only, names only) vs the Known Server Hazards section.
4. Cron and scripts: crontab -l, sudo crontab -l, ls -la /home/deploy/*.sh, read the health and backup scripts (they hold no secrets; if a line looks like a secret, mask it) — vs documented schedules, retention, alerting.
5. Backups: ls -la /home/deploy/backups | tail -20 and count — vs documented retention (the runbook says 7-day).
6. Logs: ls -la /var/log/sentinel, logrotate config (sudo cat /etc/logrotate.d/sentinel if present) — vs the log rotation table.
7. Python/venv: ls /home/deploy/sentinel | head -40, the venv path used by ExecStart, python version — vs docs.` },
  { label: "prod:config+db", prompt: `${PROD_COMMON}

TARGET: live config and database vs docs/reference/config-reference.md (every statement labelled live / production / deployed), docs/explanation/architecture.md (schema section) and docs/how-to/server-runbook.md (config + database sections). Read those sections first.
1. Confirm identity of live config: sudo sha256sum /etc/sentinel/config.yaml on the host vs sha256sum config/config.yaml locally. Then for each doc statement about a LIVE value, check it in the file (never print resolved secrets; the file uses $ {ENV} placeholders).
2. Live schema: sudo sqlite3 -readonly /var/lib/sentinel/sentinel.db '.tables' and '.schema' — compare tables, columns and indexes with the architecture.md schema section and with sentinel/database.py; report doc omissions.
3. Ledger: sudo ls -la /var/lib/sentinel; sudo sqlite3 -readonly /var/lib/sentinel/model-usage.db '.schema' and one aggregate SELECT of month-to-date cost — vs documented ledger path, budget and behavior at the cap.
4. health.json: sudo cat /var/lib/sentinel/health.json (no secrets expected; mask if any) — vs documented fields and the --health description.
5. Sanity of runbook SQL examples: do the documented example queries reference columns that exist (do not run heavy queries; LIMIT everything).
6. Alert reality, last 14 days: SELECT alert type/status counts from the alert records table (introspect the name first) — vs docs claims about which channels fire (push-only tiers, call attempts failing = known unfunded-Twilio state).` },
  { label: "prod:hardening", prompt: `${PROD_COMMON}

TARGET: live host security posture vs docs/how-to/security/vps-hardening.md and the access section of docs/how-to/server-runbook.md (read both first).
1. sshd: sudo sshd -T | grep -iE 'port|permitrootlogin|passwordauthentication|allowusers|maxauthtries|pubkeyauthentication' — vs documented settings.
2. Firewall: sudo ufw status verbose — vs documented rules (2222 open, 22 closed).
3. fail2ban: sudo fail2ban-client status and sudo fail2ban-client status sshd (jail values: maxretry, findtime, bantime via sudo fail2ban-client get sshd maxretry etc.) — vs the documented 5 failures / 10 min / 1 hour. Do not unban or change anything.
4. Updates and misc: systemctl is-enabled unattended-upgrades, any documented sysctl / swap / timezone / NTP claims (timedatectl, swapon --show).
5. Users and permissions: id deploy, id sentinel, sudo ls -ld /etc/sentinel /var/lib/sentinel /var/log/sentinel /home/deploy/sentinel — vs documented owners and modes.
6. Listening ports: sudo ss -tlnp | head -20 — vs anything the docs claim is or is not exposed.
If a tool is not installed or a check is impossible, report UNVERIFIABLE (minor).` },
  { label: "prod:logs+known-issues", prompt: `${PROD_COMMON}

TARGET: what the live logs show vs the troubleshooting table, Known Issues and Known Server Hazards sections of docs/how-to/server-runbook.md, plus docs/reference/sources.md (dead or blocked feeds) and docs/explanation/pipeline.md (log lines it quotes). Read those first.
1. Error census, last 7 days: sudo zgrep -h -E '\[(ERROR|WARNING)\]' /var/log/sentinel/sentinel.log* | sed -E 's/^[0-9-]+ [0-9:,]+ //' | cut -c1-110 | sort | uniq -c | sort -rn | head -40 (mask SIDs / tokens / phone numbers in what you report). For each recurring error class: is it covered by the troubleshooting / known-issues docs? Missing classes are findings (the Twilio 401 class is the known unfunded-account state: the finding is only that the runbook lacks a row for it).
2. Dead feeds: which sources fail every cycle (403 / 404 / timeouts) vs what sources.md and the runbook say about them.
3. Classifier evidence: lines from sentinel.openai / classifier loggers — provider, model, month-to-date cost, queue retries, budget warnings, Polish-summary guard warnings — vs what docs say these look like.
4. Cycle cadence: timestamps of fast and slow lane cycles over one hour vs documented 3 min / 15 min.
5. journalctl -u sentinel --since '7 days ago' | grep -ciE 'start|stopp|fail' and the last 20 unit-level lines — restarts vs docs claims.
6. Push evidence: push_client lines (tickets, receipts, errors) vs docs/how-to/mobile-push-setup.md verification steps.` }
]

if (CODE_TASKS.length + PROD_TASKS.length > MAX_AUDITORS) {
  throw new Error(`auditor count ${CODE_TASKS.length + PROD_TASKS.length} exceeds MAX_AUDITORS=${MAX_AUDITORS} — repartition the task lists`)
}
log(`${CODE_TASKS.length} code auditors + ${PROD_TASKS.length} prod auditors (cap ${MAX_AUDITORS})`)

phase('Audit')
const tasks = []
for (const t of CODE_TASKS) {
  tasks.push(() => runAgent(`${CODE_COMMON}

TARGET DOC: ${REPO}/${t.doc}
AREA GUIDE: ${t.hint}`, { label: t.label, phase: 'Audit', schema: FINDINGS_SCHEMA, model: AGENT_MODEL, effort: 'high' }))
}
for (const t of PROD_TASKS) {
  tasks.push(() => runAgent(t.prompt, { label: t.label, phase: 'Audit', schema: FINDINGS_SCHEMA, model: AGENT_MODEL, effort: 'high' }))
}
const results = await parallel(tasks)
const dropped = results.filter(r => r === null).length
if (dropped > 0) log(`WARNING: ${dropped} auditor(s) returned null after retry — coverage incomplete, will be listed in FINDINGS.md`)
const all = results.filter(Boolean).flatMap(r => r.findings)

// exact-duplicate dedup before the merge agent
const seen = new Set()
const deduped = []
for (const f of all) {
  const k = (f.docFile + '||' + f.claim).toLowerCase()
  if (!seen.has(k)) { seen.add(k); deduped.push(f) }
}
log(`${all.length} raw findings → ${deduped.length} after exact dedup`)

phase('Merge')
const auditorLabels = [...CODE_TASKS.map(t => t.label), ...PROD_TASKS.map(t => t.label)]
const merge = await runAgent(`You are the merge agent of a documentation-truth audit for ${REPO}. Below is the FULL JSON array of deduplicated findings from ${auditorLabels.length} auditors (${dropped} auditor(s) failed and are listed after the JSON).

FINDINGS JSON:
${JSON.stringify(deduped, null, 1)}

FAILED AUDITORS (coverage gaps to note in the report): ${dropped === 0 ? 'none' : 'count=' + dropped}

TASKS (use the Write tool; directory ${OUT} exists):
1. Write ${OUT}/FINDINGS.json — the raw JSON array verbatim.
2. Write ${OUT}/FINDINGS.md — the authored register: near-duplicate merge (same underlying discrepancy reported by two auditors → one entry, keep the better evidence), then group by docFile, order groups: always-loaded orientation docs first (CLAUDE.md, .claude/rules/*), then runbooks, then README/TODO, then the standards file, then SPEC-*. Within a group order blocker→major→minor. Each entry: severity tag, claim, actual, evidence, suggestedFix. Start the file with a summary table (docFile × counts per severity) and a 'Coverage gaps' note (failed auditors, UNVERIFIABLE items). Assign each finding a stable ID like F-001 in file order.
RETURN: raw summary — total findings after your merge, counts per severity, per docFile counts, and the 10 most consequential findings (ID + one line each). No prose for a human.`, { label: 'merge:findings', phase: 'Merge', model: AGENT_MODEL, effort: 'high' })

return { summary: merge, rawCount: all.length, dedupedCount: deduped.length, droppedAuditors: dropped }
