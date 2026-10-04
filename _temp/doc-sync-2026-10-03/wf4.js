export const meta = {
  name: 'doc-sync-review-loop',
  description: 'Fresh blind reviewer → resolver → executor loop on the doc-sync diff, until zero blocking findings (capped iterations)',
  phases: [
    { title: 'Review', detail: 'fresh blind reviewer per iteration' },
    { title: 'Resolve', detail: 'fresh resolver adjudicates' },
    { title: 'Fix', detail: 'executor fixes blocking findings' },
  ],
}

// ---------------------------------------------------------------------------
// CONFIG — overridable via `args` (object or JSON string); tokens (double-underscore placeholders) stamped
// by the orchestrator. REVIEW_MODEL should sit one tier ABOVE the bulk agent
// model — adjudication quality is this loop's brake.
// ---------------------------------------------------------------------------
const raw = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const REPO = raw.repo || '/home/kossa/code/project-sentinel'
const OUT = raw.outDir || '/home/kossa/code/project-sentinel/_temp/doc-sync-2026-10-03'
const TODAY = raw.date || '2026-10-03'
const REVIEW_MODEL = raw.reviewModel || 'fable'
const MAX_ITER = raw.maxIterations || 2                        // interview question (d)
const PROJECT_DESC = raw.projectDesc || 'small production Python life-safety alert bot (media monitoring, LLM classification, Twilio call + Expo push) on one VPS, plus an Expo mobile app and a local-only dashboard; solo non-technical operator; docs follow Diataxis and are read and maintained mostly by AI agents'
const DOC_SCOPE = raw.docScope || '52 markdown files: CLAUDE.md, .claude/rules, 3 project skills, README, TODO, all of docs/ (living docs edited; ideas, archive and dated records banner-only), SPEC.md, DECISIONS.md, mobile specs'              // one line listing the doc files/classes the diff touches
const FINDINGS_COUNT = raw.findingsCount || '290 findings F-001..F-290; the file is 2600 lines, so grep its section headings and read selectively'
const STANDARDS_FILE = raw.standardsFile || 'NONE' // repo-relative path or 'NONE'
const SIZE_GATES = raw.sizeGates || 'root CLAUDE.md, dashboard/CLAUDE.md and every .claude/rules/*.md at most 200 lines each; every .claude/skills/*/SKILL.md under 500 lines'           // exact wc-verifiable gates, e.g. 'CLAUDE.md ≤200 lines AND ≤12288 bytes; ...' or 'none'
const PROD_CHECK_LINE = raw.prodCheckLine || "ssh -p 2222 -o ConnectTimeout=15 deploy@178.104.76.254 '<read command>' (never root@ or kossa@; sudo only for cat/ls/stat/grep/journalctl/systemctl status|show|cat/sqlite3 -readonly SELECT; env files: key names only; at most a handful of calls)"                // optional: one line telling the reviewer how to run read-only prod checks; '' if scope is code-only

// KNOWN ACCEPTED DEVIATIONS — stamped by the orchestrator AFTER WF3 from the
// editor/consistency reports: deliberate skips, accepted overages, items
// annotated UNVERIFIABLE. Findings that merely restate these get rejected by
// the resolver instead of looping forever.
const known = `KNOWN ACCEPTED DEVIATIONS (from the edit pass — findings that merely restate these should be rejected):
- The full list of deliberate skips, UNVERIFIABLE items and accepted limitations reported by the editors is in the file /home/kossa/code/project-sentinel/_temp/doc-sync-2026-10-03/KNOWN-DEVIATIONS.md — read it before adjudicating.
- Owner decisions that are binding and not defects: SMS is off on purpose (tiers 5-8 push-only); the Twilio account is deliberately unfunded (HTTP 401 since 2026-09-21) and docs describe it as a known state; docs state that one source triggers a phone call today and the 1-vs-2 decision lives in TODO.md; code and server defects are only logged in TODO.md (docs-only run); no docs/incidents or docs/decisions areas, no hooks or settings changes in this run.
- Production runs commit 6429124 (tag deploy-20260925-143105); HEAD 282947f differs only in .claude/skills/deploy/SKILL.md. config/config.yaml equals the live server config.
- Append-only classes (SPEC.md, DECISIONS.md, mobile/*_SPEC.md, docs/ideas/*, docs/archive/* incl. the moved MOBILE_APP_START_HERE.md, docs/reference/luna-deployment-20260920.md, review_report_pending.md) carry only added AMENDMENT 2026-10-03 banners; the rename of MOBILE_APP_START_HERE.md into docs/archive/ is intended. docs/README.md and docs/archive/README.md index edits are intended (archive README: banner plus one added row).
- Last verified lines exist only on living docs the editor actually re-checked; their absence elsewhere is deliberate.`

const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['file', 'issue', 'evidence', 'severity', 'suggestedFix'],
        properties: {
          file: { type: 'string' },
          issue: { type: 'string' },
          evidence: { type: 'string', description: 'file:line or command output fragment proving the issue; never a secret value' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          suggestedFix: { type: 'string' },
        },
      },
    },
  },
}

const RESOLVE_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['index', 'verdict', 'reason'],
        properties: {
          index: { type: 'integer', description: '0-based index into the reviewer findings array' },
          verdict: { type: 'string', enum: ['blocking', 'non_blocking', 'reject'] },
          reason: { type: 'string' },
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

// BLIND-REVIEW INVARIANT: this prompt must never mention the iteration number,
// previous findings, or the fix history — each reviewer sees only the diff.
const REVIEWER_PROMPT = `You are an independent, fresh documentation reviewer for the repo ${REPO} (${PROJECT_DESC}). A documentation-sync pass has produced UNCOMMITTED working-tree changes across the doc set (${DOC_SCOPE}).

CONTEXT INPUTS:
- Run: git -C ${REPO} diff HEAD --stat, then git -C ${REPO} diff HEAD -- <file> per file or group (the diff is about 3500 changed lines across 52 files; one rename is staged, so always diff against HEAD). Review ALL of it, the always-loaded files, runbook, skills, TODO.md and explanation/reference docs most carefully.
- Never run the bot or anything that sends alerts or spends API money (no ./run.sh --once / --test-alert / --test-headline / --eval / --diagnostic). Never edit any file.
- ${OUT}/FINDINGS.md — the audited discrepancy register the edits were meant to fix (${FINDINGS_COUNT}, with evidence)
- ${OUT}/STANDARDS-REPORT.md — the doc standards the edits must comply with (Section 5 = binding checklist; skip if the file does not exist)
${STANDARDS_FILE === 'NONE' ? '' : `- ${REPO}/${STANDARDS_FILE} — the repo's binding doc standard (as possibly amended in this diff)`}

REVIEW FOR (in priority order):
1. FACTUAL ERRORS INTRODUCED: any changed/added doc statement that contradicts the actual code — spot-check the riskiest claims by reading the cited source files (function/getter/table/env names, counts, paths, behavior). Pay special attention to statements the diff ADDED.
2. FINDINGS REGRESSIONS: blocker/major findings from FINDINGS.md whose fix is missing, wrong, or reintroduced elsewhere (cross-file contradictions: a fact fixed in one file but still stated old-style in another — grep the whole doc set for the old fact).
3. STANDARDS VIOLATIONS: size gates (${SIZE_GATES} — verify with wc -l -c), missing/broken frontmatter in rules files (if the repo uses them), secret VALUES anywhere in the diff (long opaque strings, tokens, webhook URLs — scan added lines), dead file references in changed lines (test -e them).
4. SPEC INTEGRITY: in normative SPEC-class files the diff must be PURE ADDITIONS of dated amendment banners ("> **[AMENDMENT ${TODAY}]** ...") — any modified or deleted pre-existing normative line is critical.
5. Broken markdown, broken tables, garbled language, wrong dates.
${PROD_CHECK_LINE ? `Optional read-only prod check if a claim can only be verified live: ${PROD_CHECK_LINE} — GET/SELECT only, never modify anything.` : 'Do NOT touch production or any network service.'}

SEVERITY: critical = would mislead an agent into a harmful action, factual claim contradicting code, secret in diff, normative spec text modified; high = materially wrong or a standards-gate failure; medium = real but low-stakes inaccuracy or inconsistency; low = cosmetic.
Do NOT report: stylistic taste, pre-existing problems in UNCHANGED lines (unless a changed line contradicts them), or the known accepted deviations you may find documented in the diff itself.
Report via the structured schema; empty findings array if the diff is clean. Verify before reporting — every finding must carry concrete evidence you checked yourself.`

const FOCUS = [
  'CLAUDE.md, .claude/rules/corroboration.md, README.md, dashboard/CLAUDE.md, mobile/AGENTS.md, TODO.md, docs/README.md, and every append-only file (SPEC.md, DECISIONS.md, review_report_pending.md, mobile/*_SPEC.md, docs/ideas/*, docs/archive/*, docs/reference/luna-deployment-20260920.md) for banner-only integrity',
  'docs/how-to/server-runbook.md, docs/how-to/security/vps-hardening.md, docs/how-to/security/README.md, .claude/skills/deploy/SKILL.md, .claude/skills/sentinel-audit/SKILL.md, .claude/skills/dashboard/SKILL.md',
  'docs/explanation/architecture.md, docs/explanation/pipeline.md, docs/reference/config-reference.md (verify against sentinel/ code and config/config.yaml)',
  'docs/reference/cli.md, docs/reference/sources.md, docs/tutorials/getting-started.md, docs/how-to/api-setup.md, docs/how-to/testing.md, docs/how-to/model-comparison.md, docs/explanation/mobile-app.md, docs/how-to/mobile-push-setup.md, docs/how-to/mobile-inbox-verification.md',
]

let iteration = 0
let lastReview = null
let history = []
let carriedNonBlocking = []

while (iteration < MAX_ITER) {
  iteration++

  phase('Review')
  const parts = await parallel(FOCUS.map((f, i) => () => runAgent(REVIEWER_PROMPT + '\n\nYOUR SHARE OF THE DIFF (other fresh reviewers cover the rest; review these files in full depth, and report cross-file contradictions you notice against any other file): ' + f, { label: `review#${iteration}.${i + 1}`, phase: 'Review', schema: REVIEW_SCHEMA, model: REVIEW_MODEL, effort: 'high' })))
  const failedParts = parts.filter(p => p === null).length
  const review = failedParts === parts.length ? null : { findings: parts.filter(Boolean).flatMap(p => p.findings) }
  if (failedParts) log(`iteration ${iteration}: ${failedParts} reviewer share(s) failed after retry — coverage gap`)
  if (review === null) { history.push({ iteration, error: 'reviewer failed after retry' }); break }
  lastReview = review
  log(`iteration ${iteration}: reviewer returned ${review.findings.length} findings`)

  if (review.findings.length === 0) {
    history.push({ iteration, reviewerFindings: 0, blocking: 0 })
    return { verdict: 'green', iterations: iteration, history, note: 'reviewer returned zero findings' }
  }

  phase('Resolve')
  const resolve = await runAgent(`You are the independent resolver in a documentation review loop for ${REPO}. A blind reviewer examined the uncommitted doc-sync diff (run git -C ${REPO} diff HEAD yourself as needed; never edit files, never run the bot or paid API calls) and returned the findings below. Adjudicate EACH finding by index:
- blocking: real, and severity critical/high/medium — must be fixed before commit. Verify the finding yourself against the repo (read the files, run wc, grep) before confirming.
- non_blocking: real but low-stakes (low severity, cosmetic) — record, do not block.
- reject: wrong, unverifiable, out of scope (pre-existing in unchanged lines, stylistic taste), or restates a known accepted deviation.

${known}

REVIEWER FINDINGS (JSON):
${JSON.stringify(review.findings, null, 1)}

Return a verdict for every index via the schema.`, { label: `resolve#${iteration}`, phase: 'Resolve', schema: RESOLVE_SCHEMA, model: REVIEW_MODEL, effort: 'high' })
  if (resolve === null) { history.push({ iteration, error: 'resolver failed after retry' }); break }

  const blocking = resolve.verdicts
    .filter(v => v.verdict === 'blocking')
    .map(v => ({ ...review.findings[v.index], resolverReason: v.reason }))
    .filter(f => f && f.file)
  history.push({ iteration, reviewerFindings: review.findings.length, blocking: blocking.length, verdicts: resolve.verdicts })
  log(`iteration ${iteration}: resolver confirmed ${blocking.length} blocking of ${review.findings.length}`)

  if (blocking.length === 0) {
    return { verdict: 'green', iterations: iteration, history, nonBlocking: resolve.verdicts.filter(v => v.verdict === 'non_blocking').map(v => ({ ...review.findings[v.index], resolverReason: v.reason })) }
  }

  const nonBlockingList = resolve.verdicts.filter(v => v.verdict === 'non_blocking').map(v => ({ ...review.findings[v.index], resolverReason: v.reason }))
  if (iteration >= MAX_ITER) {
    return { verdict: 'orchestrator-fix', iterations: iteration, history, blocking, nonBlocking: nonBlockingList, note: 'cap reached: orchestrator applies the remaining blocking findings inline (owner instruction), no further review round' }
  }
  carriedNonBlocking.push(...nonBlockingList)

  phase('Fix')
  const fix = await runAgent(`You are a documentation fix executor for ${REPO}. An adjudicated review of the uncommitted doc-sync diff produced the BLOCKING findings below. Fix each one surgically in the working tree.

Also fix the non-blocking findings listed at the end where the fix is cheap and safe. Use git diff HEAD (one rename is staged). Never run the bot or paid API calls.

RULES: docs only (*.md) — never source code, schema files, package manifests; never git commit; never touch production. Normative SPEC-class files: amendment banners may be edited/added but pre-existing normative text must stay untouched. Keep size gates: ${SIZE_GATES} (wc -l -c after editing). Never write a secret value. If a fix requires changing a fact, verify the fact against the code first. Cross-file rule: if you change a fact, grep the whole doc set and align every file stating it.

BLOCKING FINDINGS (JSON):
${JSON.stringify(blocking, null, 1)}

NON-BLOCKING FINDINGS (fix if cheap):
${JSON.stringify(nonBlockingList, null, 1)}

RETURN (raw): per finding → what you changed (file:line), plus wc -l -c of each touched gated file.`, { label: `fix#${iteration}`, phase: 'Fix', model: 'opus', effort: 'high' })
  if (fix === null) { history.push({ iteration, error: 'executor failed after retry' }); break }
}

return { verdict: 'escalate', iterations: iteration, history, lastReviewFindings: lastReview ? lastReview.findings : null, note: 'loop ended without a green pass — cap reached or an agent failed; main agent must decide' }
