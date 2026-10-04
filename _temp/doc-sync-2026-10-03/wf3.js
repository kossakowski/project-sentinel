export const meta = {
  name: 'doc-sync-edit',
  description: 'Apply the audited findings + standards report to the documentation set (file-partitioned editors + consistency pass)',
  phases: [
    { title: 'Edit', detail: 'file-partitioned editors (no file has two authors)' },
    { title: 'Consistency', detail: 'cross-file contradiction check, size limits, path existence, secret scan' },
  ],
}

// ---------------------------------------------------------------------------
// CONFIG — overridable via `args` (object or JSON string); tokens (double-underscore placeholders) stamped
// by the orchestrator.
// ---------------------------------------------------------------------------
const raw = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const REPO = raw.repo || '/home/kossa/code/project-sentinel'
const OUT = raw.outDir || '/home/kossa/code/project-sentinel/_temp/doc-sync-2026-10-03'
const AGENT_MODEL = raw.agentModel || 'opus'
const MAX_EDITORS = raw.maxEditors || 16                       // interview question (d); includes the consistency agent
const FINDINGS_COUNT = raw.findingsCount || '290 findings, F-001..F-290 (24 blocker, 150 major, 116 minor)' // e.g. '139 findings, F-001..F-139'
const STANDARDS_FILE = raw.standardsFile || 'NONE' // repo-relative path of the binding standard, or 'NONE'
const SIZE_RULES = raw.sizeRules || 'always-loaded files (root CLAUDE.md, dashboard/CLAUDE.md, .claude/rules/*.md) at most 200 lines each, root CLAUDE.md should stay near 80 lines; every SKILL.md under 500 lines; other docs have no hard ceiling but must not bloat.'           // one paragraph: the binding size budgets per file class
const PROJECT_DESC = raw.projectDesc || 'small production Python life-safety alert bot (media monitoring, LLM classification, Twilio call + Expo push) on one VPS, plus an Expo mobile app and a local-only dashboard; solo non-technical operator; docs follow Diataxis and are read and maintained mostly by AI agents'

async function runAgent(prompt, opts) {
  let r = null
  for (let i = 0; i < 2 && r === null; i++) r = await agent(prompt, opts)
  return r
}

const COMMON = `You are a documentation editor in an automated doc-sync pipeline for ${REPO} (${PROJECT_DESC}).

INPUTS — read these first:
1. ${OUT}/FINDINGS.md — the audited discrepancy register (${FINDINGS_COUNT}, grouped by docFile, each with claim/actual/evidence/severity/suggestedFix). Address ONLY the findings whose docFile is in YOUR file set below.
2. ${OUT}/STANDARDS-REPORT.md — Section 5 is a binding imperative checklist for you; sections 2-3 explain amended standards. (If the file does not exist, this run skipped standards research — follow the project standard alone.)
3. ${STANDARDS_FILE === 'NONE' ? '(no binding standards file in this repo — STANDARDS-REPORT.md Section 5 governs)' : `${REPO}/${STANDARDS_FILE} — the current binding doc standard.`}

METHOD:
- For each finding on your files: quickly re-verify the 'actual' against the code/repo (cheap check — grep/read the cited evidence); then apply the suggestedFix or a better formulation. Findings are evidence-backed but not infallible — if a finding is wrong, SKIP it and say why.
- Fix ALL blocker and major findings on your files. Fix minors too unless a minor fix would bloat the file; then skip with reason.
- Respect the file's existing voice, density and structure; edit surgically, do not rewrite wholesale (exception: where a finding says content is fundamentally outdated).
- Size budgets: ${SIZE_RULES} After editing run wc -l -c on every file you touched and trim if over.
- NEVER write a secret value into any doc — credential PATHS and variable NAMES only.
- Never edit any file outside YOUR file set. Do not run git commit. Do not touch production.
- Frequently-changing facts (counts, point-in-time stats) belong to their source of truth — prefer a pointer over restating.
- SPEC-class files (normative specs) are APPEND-ONLY: you may ONLY add dated amendment banners ('> **[AMENDMENT YYYY-MM-DD]** <what changed, live name/behavior, one line why>') directly above the affected section — never rewrite, delete or restyle existing normative text.
- Dated sequence logs / history sections are append-only: fix only forward-looking false claims, never rewrite the historical record.

RETURN (raw data for the pipeline, no prose for a human): first a section 'DEVIATIONS' listing every deliberate skip, UNVERIFIABLE item and accepted limitation with its reason; then per finding ID → fixed | adjusted (how) | skipped (why); then wc -l -c of each touched file.`

// ---------------------------------------------------------------------------
// STAMP: EDITORS — authored by the orchestrator from FINDINGS.md's docFile
// groups. HARD RULE: the file sets MUST be disjoint (no file has two authors);
// the guard below enforces it. `files` = comma-separated repo-relative paths;
// `extra` = per-editor guidance: the known blockers on those files, their
// current wc -l -c headroom, and any special regime (append-only, banners).
//   { label: 'edit:CLAUDE.md', files: 'CLAUDE.md', extra: 'Always-loaded orientation file — dual limit is HARD; currently N lines / M KB, prefer replacing stale text over adding.' },
// ---------------------------------------------------------------------------
const CTX = "\n\nRUN CONTEXT AND OWNER DECISIONS (binding; they override FINDINGS.md and STANDARDS-REPORT.md where they conflict):\n- FINDINGS.md is large (2600 lines). Do not read it whole: run grep -n '^## ' on it, then read only the sections of YOUR files (each section heading is the docFile path in backticks). Findings that sit under another file's section but name one of your files in their suggestedFix are yours too only for the part touching your file.\n- Repo HEAD (master) = 282947f. PRODUCTION runs tag deploy-20260925-143105 = commit 6429124; the only difference is .claude/skills/deploy/SKILL.md (step 6a). Never call something live merely because it is at HEAD. /etc/sentinel/config.yaml on the server is byte-identical to config/config.yaml, so config/config.yaml holds the live values; config/config.example.yaml is the template; sentinel/config.py holds code defaults. Keep the three apart in wording.\n- Live classifier: OpenAI gpt-5.6-luna via sentinel/classification/openai_provider.py. Claude Haiku is the legacy / rollback path only.\n- SMS is switched off on purpose: tiers 5-8 are push-only. The Twilio account is deliberately unfunded, so every Twilio call and SMS fails with HTTP 401 (account not active) since 2026-09-21. Describe this neutrally as a KNOWN STATE the owner chose (calls return when the owner recharges the account) — never as an outage, bug or emergency. Phone calls stay configured.\n- Corroboration: the live critical tier has corroboration_required: 1, so one source triggers a phone call today. Docs describe that as current behavior; the open owner decision (require 2?) lives as a TODO.md item only.\n- DOCS ONLY. Never edit code, config, tests, scripts, settings.json, hooks, .gitignore, or anything on the server. Code or server defects are documented truthfully where the doc would otherwise mislead, with a pointer to TODO.md; only the TODO.md editor adds TODO items (the findings already filed them under TODO.md), so do not edit TODO.md unless it is in your file set — refer to the item by topic, not by a number you cannot know.\n- No new doc areas in this run: do NOT create docs/incidents/ or docs/decisions/, do not move or rename files (the single exception is stated in the guidance of the editor that owns it). Standards-report items that need new areas, hooks, settings or GitHub features are out of scope.\n- Adopt from STANDARDS-REPORT Section 5: directives 1-5, 7-10, 12-18. For directive 9: add or update a line 'Last verified: 2026-10-03 (deployed commit 6429124)' directly under the H1 of a LIVING doc only when you really re-checked its content in this session; never on append-only records, specs, ideas, archive files or skills. For directive 18: add a short table of contents to a living doc over 100 lines if it lacks one.\n- APPEND-ONLY classes (SPEC.md, DECISIONS.md, mobile/*_SPEC.md, docs/ideas/*, docs/archive/*, docs/reference/luna-deployment-20260920.md, review_report_pending.md): the only allowed change is ADDING lines of the form '> **[AMENDMENT 2026-10-03]** ...' (at the top of the file or directly above the affected section). No pre-existing line may be modified or deleted.\n- Write for a non-technical owner and for AI agents: full simple sentences, concrete, no hype. Never write a secret value, token, phone number or account SID.\n- Do not run the bot or anything that sends alerts or calls a paid API (no ./run.sh --once, --test-alert, --test-headline, --eval). Read-only verification only. Do not touch production (no ssh)."

const editors = [
  { label: "edit:orientation", files: "CLAUDE.md, .claude/rules/corroboration.md, README.md, dashboard/CLAUDE.md, mobile/AGENTS.md", extra: "Always-loaded orientation files. CLAUDE.md is 51 lines / 4477 B: keep it near 80 lines at most, replace stale text instead of adding, point to config/config.yaml and docs/reference/config-reference.md instead of restating model names, thresholds or source state. Blockers: F-001 (corroboration rule false: one source triggers a call today), F-002 (classifier is Luna, not Haiku), F-014 (the acknowledged-event critical guard in corroboration.md only exists on the legacy path; rewrite to the real live mechanism and keep the life-safety warning). Keep emphasis (bold NEVER, warning icon) only on the two life-safety lines: no production writes without permission; never miss urgency 9-10. corroboration.md must keep valid paths: frontmatter and no other frontmatter field. The owner approved editing these instruction files in this run." },
  { label: "edit:runbook", files: "docs/how-to/server-runbook.md", extra: "330 lines, 19 findings incl. blockers F-023 (the detached-HEAD fix would deploy undeployed master: detached HEAD on a deploy tag is the intended state) and the push-disabled claim. Majors: watchdog check-health.sh inert (F-030), Twilio 401 known state missing from troubleshooting (add a symptom row worded as known state), current deployment line, budget 30 USD, deploy step 6a stop-on-server-only-config-edits and renumbered 6b-6f (match .claude/skills/deploy/SKILL.md wording), stray .env hazard. Put the symptom about undeliverable urgency 9-10 alerts first in troubleshooting. Add a table of contents. Label each command read-only or state-changing where the finding asks." },
  { label: "edit:hardening", files: "docs/how-to/security/vps-hardening.md, docs/how-to/security/README.md", extra: "602 lines, 18 findings incl. 2 blockers. Fix against deploy/*.sh, deploy/configs/* and the prod-auditor evidence quoted in the findings. Make clear whether the doc is a record of what was done or a repeatable procedure. Add a table of contents if missing." },
  { label: "edit:skills", files: ".claude/skills/deploy/SKILL.md, .claude/skills/sentinel-audit/SKILL.md, .claude/skills/dashboard/SKILL.md", extra: "Project skills (364 / 404 / 75 lines; each must stay under 500). The owner approved editing them in this run. Never change the frontmatter name; change a frontmatter description only if a finding proves it factually false. Deploy skill: fix only what findings prove wrong, keep step numbering 6a-6f stable because the runbook editor mirrors it. sentinel-audit: Haiku vs Luna, SMS vs push-only, paths, tables and columns. No Last-verified line in skills." },
  { label: "edit:TODO", files: "TODO.md", extra: "242 lines, 36 findings (1 blocker F-088 Telegram mislabel defect). You are the ONLY editor allowed to add TODO items; other editors point here by topic. Close or re-word items that are done or built on the retired Haiku classifier (do not delete history: mark done with date, or move obsolete plans under a clearly labelled superseded heading). Add every code/server defect and owner decision the findings file under TODO.md, grouped under one new top section for life-safety items first: F-014 sign-off on the changed critical-guard invariant, F-088, F-091 OpenAI project hard cap vs 30 USD allowance, F-030 no working out-of-band watchdog, F-095 Ukraine-only shelter orders scoring 9, F-097 stale retry_pending calls after a Twilio recharge, corroboration_required 1 vs 2 decision, stray server .env. Also scan ALL other sections of FINDINGS.md for suggestedFix text that says to log or add a TODO item (grep -n -i \"todo\" FINDINGS.md) and make sure each such item exists exactly once. Use stable, greppable item titles so other docs can point to them by topic. Keep each item to a few lines: what, evidence pointer (file:line), why it matters." },
  { label: "edit:index+records", files: "docs/README.md, docs/archive/README.md, docs/archive/HANDOFF_audit-findings-2026-05-23.md, docs/archive/prompts/corroboration-removal.md, docs/archive/prompts/implement-audit-remediation.md, docs/archive/prompts/phase-1-orchestrator.md, docs/archive/prompts/sentinel-audit.md, MOBILE_APP_START_HERE.md, docs/archive/MOBILE_APP_START_HERE.md, review_report_pending.md, DECISIONS.md, SPEC.md, mobile/PUSH_APP_SPEC.md, mobile/INBOX_APP_SPEC.md", extra: "docs/README.md is a living index: index every area incl. docs/ideas/ (working notes and plans, NOT current truth), the dated Luna deployment record, how-to/model-comparison.md; fix blurbs. THE ONE ALLOWED MOVE: archive the obsolete June handoff with git mv MOBILE_APP_START_HERE.md docs/archive/MOBILE_APP_START_HERE.md, add a dated AMENDMENT banner at its top saying it is historic and where current truth lives, list it in docs/archive/README.md, and grep the repo docs for links to the old path (report any hit in a file you do not own in your DEVIATIONS section for the consistency agent). All other files in your set except docs/README.md and docs/archive/README.md are APPEND-ONLY: banners only. SPEC.md banners go directly above the affected section. DECISIONS.md: add at most a short dated banner block for forward-looking claims the findings prove stale; do not invent decision records." },
  { label: "edit:setup", files: "docs/tutorials/getting-started.md, docs/how-to/api-setup.md", extra: "Blockers: F-132 (the cp config.example.yaml config/config.yaml step overwrites the TRACKED production config that /deploy ships — rewrite the local-setup path so a newcomer never clobbers it; verify how the repo really expects local config, e.g. --config flag in sentinel.py / run.sh, before writing) and the api-setup .env template lacking OPENAI_API_KEY / OPENROUTER_API_KEY. Align every env var with .env.example and the code. Budget numbers: point to config, state live 30 USD only once." },
  { label: "edit:testing+comparison", files: "docs/how-to/testing.md, docs/how-to/model-comparison.md", extra: "16 findings incl. 1 blocker in model-comparison.md (production still uses Haiku claim). Update mocking description, fixture table, test file groups; never state a test count (volatile) — give the command instead." },
  { label: "edit:mobile", files: "docs/explanation/mobile-app.md, docs/how-to/mobile-push-setup.md, docs/how-to/mobile-inbox-verification.md", extra: "19 findings incl. blockers: F-156 (doc tells the reader to paste the literal Expo push token into the tracked config of a PUBLIC repo or to hand-edit the server config; the real mechanism is the ${EXPO_PUSH_TOKEN} placeholder resolved from the server env file, shipped by /deploy) and the push routing claims in mobile-app.md (tiers 5-8 are push-only live; urgency 9-10 sends an additive push). State that EXPO_PUBLIC_* values are public by design if the docs mention them." },
  { label: "edit:architecture", files: "docs/explanation/architecture.md", extra: "462 lines, 32 findings incl. 3 blockers. This doc is fundamentally outdated in its classifier, cost, error-handling and schema parts: rewrite those sections against the code (sentinel/classification/*.py, sentinel/database.py, sentinel/models.py, sentinel/alerts/*.py, sentinel/scheduler.py), keep sections that are still right. Add the missing modules, the classification_queue table and the migration-added columns, incident memory, summary guard, budget ledger, revision-aware notifications. Mirror code structure, neutral voice, no hardcoded prices or line numbers that will drift. Add a table of contents." },
  { label: "edit:pipeline", files: "docs/explanation/pipeline.md", extra: "217 lines, 16 findings incl. 3 blockers. Walk sentinel/scheduler.py stage by stage and make the doc match: provider and model by pointer to config, retry queue, budget gating, incident-memory matching (incl. the F-014 fact: in live memory mode a same-incident critical repeat merges into an acknowledged event without a new call), Polish summary guard, tier routing (5-8 push-only live), one-source call today, revision-aware notifications. Add a table of contents." },
  { label: "edit:config-reference", files: "docs/reference/config-reference.md", extra: "397 lines, 25 findings incl. 2 blockers. Reference mirrors sentinel/config.py 1:1: for each key give code default, template value where it differs, and the live value only where the doc already has such a column — and then it must equal config/config.yaml (max_call_retries live 1, push enabled live, channel push on high and medium, monthly budget 30, incident memory enabled live). Remove statements that the live config omits the push block. Neutral voice, no instructions. Add a table of contents." },
  { label: "edit:cli+sources+luna", files: "docs/reference/cli.md, docs/reference/sources.md, docs/reference/luna-deployment-20260920.md", extra: "cli.md (9 findings) vs build_parser() in sentinel.py; point to docs/how-to/model-comparison.md for the python -m sentinel.eval.* entry points. sources.md: add a Known issues note that every Telegram message is currently stored under the first configured channel name (F-088, code defect, pointer to TODO.md) and fix the 3 findings. luna-deployment-20260920.md is an APPEND-ONLY dated record: banners only (budget since raised to 30 USD on 2026-09-24; repo config and server config are now the same file)." },
  { label: "edit:ideas", files: "docs/ideas/HANDOFF-fix-vague-inputs.md, docs/ideas/classifier-calibration-roadmap.md, docs/ideas/incident-memory-plan.md, docs/ideas/luna-direct-api-migration-plan.md, docs/ideas/luna-direct-api-validation-20260920.md, docs/ideas/model-comparison-labels.md, docs/ideas/model-comparison-plan.md, docs/ideas/model-comparison-v2-holdout-notes.md, docs/ideas/model-comparison-v2-plan.md, docs/ideas/model-comparison-v2-run-record.md, docs/ideas/model-runtime-comparison-20260920.md, docs/ideas/polish-summary-guard.md", extra: "All APPEND-ONLY: one dated AMENDMENT banner per file at the top (status today + pointer to the living doc), nothing else. Blocker in HANDOFF-fix-vague-inputs.md: read the finding and word the banner so an agent that finds the file by grep will not act on its stale instruction. Verify each status claim against git log / code / config before writing it." }
]

if (editors.length + 1 > MAX_EDITORS) {
  throw new Error(`${editors.length} editors + consistency agent exceeds MAX_EDITORS=${MAX_EDITORS} — merge file sets`)
}
{
  const owned = new Map()
  for (const e of editors) for (const f of e.files.split(',').map(s => s.trim()).filter(Boolean)) {
    if (owned.has(f)) throw new Error(`file partition violated: '${f}' owned by both '${owned.get(f)}' and '${e.label}'`)
    owned.set(f, e.label)
  }
}

phase('Edit')
const editResults = await parallel(editors.map(e => () => runAgent(`${COMMON}

YOUR FILE SET (you own these files exclusively): ${e.files}

SPECIFIC GUIDANCE: ${e.extra}${CTX}`, { label: e.label, phase: 'Edit', model: AGENT_MODEL, effort: 'high' })))

const failedEditors = editors.filter((e, i) => editResults[i] === null).map(e => e.label)
if (failedEditors.length) log(`WARNING: editors failed after retry: ${failedEditors.join(', ')}`)

phase('Consistency')
const editDigest = editors.map((e, i) => `### ${e.label} (${e.files})\n${editResults[i] === null ? 'EDITOR FAILED — its findings are UNADDRESSED' : editResults[i]}`).join('\n\n')

const consistency = await runAgent(`You are the final consistency agent of a doc-sync pipeline for ${REPO}. ${editors.length} editors just modified the documentation set per ${OUT}/FINDINGS.md and ${OUT}/STANDARDS-REPORT.md. ${CTX}

You may edit ANY documentation file to fix what you find, within the rules above (docs only — never source code, schema files, package manifests; never git commit; never touch production).

EDITOR REPORTS:
${editDigest}

CHECKS (run all, fix directly where possible):
1. Cross-file contradictions: when a fact changed, ALL files stating the old fact must be aligned in one pass. From the editor reports above, list every fact the editors changed (renamed things, corrected counts, corrected statuses, brand/URL changes, env-var names) and grep the whole doc set for each old formulation; align any file still stating the old fact.
2. Size limits: ${SIZE_RULES} Run wc -l -c on every gated file; trim overages yourself (prefer deleting redundancy over compressing prose into unreadability).
3. Referenced-path existence: extract every repo path referenced in the always-loaded docs (CLAUDE.md, .claude/rules/*.md if present) and test -e each; fix or remove dead references.
4. Secret scan: run git diff on the repo and scan the ADDED lines for anything looking like a secret (long hex/base64 runs, key=value with 20+ char opaque values, Bearer tokens, webhook URLs with tokens). If found, redact to a path/name reference immediately and flag it loudly in your report.
5. Unaddressed findings: FINDINGS.md entries marked skipped without a valid reason, or belonging to failed editors — fix the blockers/majors among them yourself.
6. Rules frontmatter: if the repo uses .claude/rules/*.md with paths: frontmatter, every rules file must still carry valid frontmatter after the edits (head -8 each).

RETURN (raw): per check → pass/fixed(what)/fail(why); list of extra edits you made (file + one line); final wc -l -c table; any residual problem you could not fix.`, { label: 'consistency-pass', phase: 'Consistency', model: AGENT_MODEL, effort: 'high' })

return { consistency, failedEditors }
