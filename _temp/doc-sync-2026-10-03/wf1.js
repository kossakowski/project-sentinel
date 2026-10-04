export const meta = {
  name: 'doc-standards-research',
  description: 'Establish current CLAUDE.md + project-doc standards (official Anthropic + community + project-type) and diff them against the project standards file',
  phases: [
    { title: 'Research', detail: '3 parallel researchers: official Anthropic docs, community practice, project-type doc standards' },
    { title: 'Synthesize', detail: 'diff vs the project standards file → STANDARDS-REPORT.md' },
  ],
}

// ---------------------------------------------------------------------------
// CONFIG — every value can arrive via `args` (object or JSON string); the
// tokens (double-underscore placeholders) are stamped by the orchestrator before launch. Date.now() is
// unavailable inside workflows, so the date MUST be passed in.
// ---------------------------------------------------------------------------
const raw = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const REPO = raw.repo || '/home/kossa/code/project-sentinel'                         // absolute repo path
const OUT = raw.outDir || '/home/kossa/code/project-sentinel/_temp/doc-sync-2026-10-03'                         // absolute output dir (must already exist)
const TODAY = raw.date || '2026-10-03'                        // YYYY-MM-DD
const AGENT_MODEL = raw.agentModel || 'sonnet'     // model for workflow agents (mode-dependent)
const PROJECT_DESC = raw.projectDesc || 'small production Python life-safety alert bot (media monitoring, LLM classification, Twilio call + Expo push) on one VPS, plus an Expo mobile app and a local-only dashboard; solo non-technical operator; docs follow Diataxis (docs/) with CLAUDE.md + .claude/rules + project skills, and are read and maintained mostly by AI agents'  // one line: project type, scale, who reads the docs
const STANDARDS_FILE = raw.standardsFile || 'NONE' // repo-relative path of the binding doc standard, or 'NONE'
const SIZE_LIMITS = raw.sizeLimits || 'none documented (generic budget: always-loaded files at most 200 lines)'     // one line: current binding size limits, or 'none documented'

// WF1 budget: 3 researchers + 1 synthesizer = 4 agents (limit for this stage: 5).

async function runAgent(prompt, opts) {
  let r = null
  for (let i = 0; i < 2 && r === null; i++) r = await agent(prompt, opts)
  return r
}

const COMMON = `You are a research agent inside an automated pipeline. Your final text IS raw data consumed by a synthesizer agent — no greetings, no prose for a human. Return a structured bullet digest. Every claim must carry its source URL. Today is ${TODAY}; prefer the most current sources. Do not read or modify any file in ${REPO} except where explicitly told.`

phase('Research')
const [official, community, domain] = await parallel([
  () => runAgent(`${COMMON}

TASK: Extract Anthropic's OFFICIAL current guidance on writing CLAUDE.md / memory files and .claude/rules for Claude Code projects.
Sources to fetch (WebFetch) and search (WebSearch) for newer versions:
- https://code.claude.com/docs/en/memory (memory hierarchy, CLAUDE.md, imports; check docs.anthropic.com mirror too)
- https://www.anthropic.com/engineering/claude-code-best-practices (engineering blog)
- Any official docs on settings, path-scoped rules files, @imports, slash commands vs rules, output styles.
Extract concrete standards: recommended content of CLAUDE.md (what to include/exclude), size guidance, structure, memory hierarchy (user/project/local), @path import semantics, .claude/rules usage and paths: frontmatter if documented, maintenance cadence, anti-patterns Anthropic warns about.
RETURN: '## OFFICIAL STANDARDS' — bullets, each: standard → why → source URL. Mark items where official docs are silent as 'NOT COVERED OFFICIALLY'.`, { label: 'research:official', phase: 'Research', model: AGENT_MODEL }),

  () => runAgent(`${COMMON}

TASK: Extract COMMUNITY best practices (current year and the previous one) for CLAUDE.md and Claude Code project documentation.
Search (WebSearch + WebFetch): awesome-claude-code on GitHub, well-known blog posts on CLAUDE.md structure, HN threads, r/ClaudeAI, examples from mature OSS repos that ship CLAUDE.md + .claude/rules (search GitHub). Look for: size limits people converge on, path-scoped rule files, keeping CLAUDE.md orientation-only vs encyclopedic, links-not-duplication, how teams prevent doc drift, what over-instruction does to strong models, patterns for runbooks/specs referenced from CLAUDE.md.
RETURN: '## COMMUNITY PRACTICES' — bullets, each: practice → who/where uses it → source URL. Separate section '## CONTESTED' for practices the community disagrees on.`, { label: 'research:community', phase: 'Research', model: AGENT_MODEL }),

  () => runAgent(`${COMMON}

TASK: Extract documentation standards for projects of THIS type: ${PROJECT_DESC}
Research (WebSearch/WebFetch) the doc genres this project type actually uses — e.g. ops runbook best practices (Google SRE workbook playbook guidance, runbook patterns), ADR / append-only decision logs, spec governance (normative specs amended with dated banners), documenting credentials safely (paths/pointers, never values — vault-pointer pattern), doc-drift prevention (docs-as-code, review gates), and any emerging guidance on writing docs FOR AI agents as the primary reader (agent-readable runbooks). Pick the genres that match the project description above; skip genres the project does not have.
RETURN: '## PROJECT-TYPE DOC STANDARDS' — bullets, each: standard → rationale → source URL.`, { label: 'research:project-type', phase: 'Research', model: AGENT_MODEL }),
])

phase('Synthesize')
const digests = [official, community, domain].filter(Boolean).join('\n\n---\n\n')
const standardsInput = STANDARDS_FILE === 'NONE'
  ? `INPUT B — the repo has NO binding doc-standards file yet. Skim ${REPO}/CLAUDE.md (if present) and list the doc files the orchestrator flagged, to understand current practice. Your report will BECOME the seed of the project's first standards file, so section 2 (Change) may be empty and section 3 (Add) will carry most content.`
  : `INPUT B — the repo's CURRENT binding standard: read ${REPO}/${STANDARDS_FILE} in full. Also skim ${REPO}/CLAUDE.md and list the filenames in ${REPO}/.claude/rules/ (if present) to understand current practice (do NOT audit their content — another pipeline does that). Current binding size limits: ${SIZE_LIMITS}.`

const report = await runAgent(`You are the synthesis agent of a documentation-standards pipeline for the repo ${REPO} (${PROJECT_DESC}).

INPUT A — three research digests (official Anthropic / community / project-type standards):

${digests}

${standardsInput}

TASK: Write the file ${OUT}/STANDARDS-REPORT.md (use the Write tool; the directory exists). Structure:
# Standards report — doc-sync ${TODAY}
## 1. Confirmed — current standard already aligns (bullet: current rule → confirming source)
## 2. Change — amend the current standard (bullet: current rule → proposed change → why → source)
## 3. Add — standards missing from the project standard worth adopting (bullet: proposed rule → why → source)
## 4. Rejected — official/community advice we deliberately do NOT adopt for this repo (bullet: advice → why rejected here)
## 5. Directives for doc-editing agents — a short, imperative checklist that downstream agents editing the doc set must follow (synthesis of 1-3; keep any existing binding size limits unless research justified changing them: ${SIZE_LIMITS}).
Keep it ≤180 lines, actionable, each recommendation traceable to a source. This report is consumed by other agents, not a human.
RETURN: a 15-line summary of the report's key changes/additions + confirmation the file was written (path + line count).`, { label: 'synthesize:standards-report', phase: 'Synthesize', model: 'opus', effort: 'high' })

return { report }
