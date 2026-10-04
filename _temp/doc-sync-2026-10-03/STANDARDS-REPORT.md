# Standards report — doc-sync 2026-10-03

Scope: `CLAUDE.md` (51 lines), `dashboard/CLAUDE.md` (52), `.claude/rules/corroboration.md` (path-scoped),
`.claude/skills/{deploy,sentinel-audit,dashboard}/SKILL.md` (364/404/75), `docs/` (Diataxis + `archive/` + `ideas/`),
`SPEC.md` (830, living), `TODO.md`. No `.claude/settings.json` exists, so there are no hooks and no `permissions.deny`.
Source keys: [MEM] code.claude.com/docs/en/memory · [BP] code.claude.com/docs/en/best-practices ·
[FO] code.claude.com/docs/en/features-overview · [LC] code.claude.com/docs/en/large-codebases ·
[BLOG] claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more · [SKBP] platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices ·
[CTX] anthropic.com/engineering/effective-context-engineering-for-ai-agents · [DTX] diataxis.fr ·
[SRE-OC] sre.google/workbook/on-call · [SRE-PM] sre.google/sre-book/postmortem-culture · [SRE-DI] sre.google/sre-book/data-integrity ·
[ADR] cognitect.com/blog/2011/11/15/documenting-architecture-decisions · [PEP1] peps.python.org/pep-0001 ·
[OWASP] cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html · [12F] 12factor.net/config ·
[RB2] oneuptime.com/blog/post/2026-08-06-on-call-runbook-game-day-validation (secondary) · [ETH] arxiv.org/abs/2602.11988.

## 1. Confirmed — current standard already aligns

- Root `CLAUDE.md` is 51 lines, well under the 200-line target → [MEM] "target under 200 lines"; community range 58–82 lines in Anthropic repos.
- "Docs: link, don't restate" plus a docs index of one-line pointers → [CTX] progressive disclosure; [BP] "detailed API docs: link instead"; [MEM] contradictions make Claude "pick one arbitrarily".
- `corroboration.md` uses `paths:` frontmatter and says "do not restate numeric values" → [MEM] path-specific rules; [BLOG] "if a rule only applies to `src/api/**`, scope it with `paths:`".
- `dashboard/CLAUDE.md` is a nested file that loads lazily, used for a separate subsystem → [MEM] subdirectory files load on demand; [LC] per-directory file for a self-contained area.
- `docs/` follows Diataxis with four typed folders and an index → [DTX] keep the four types separate.
- `docs/archive/README.md` marks historic specs as "NOT current truth" and maps each to its living equivalent → [ADR] superseded records stay in place, marked, with a link; [PEP1] resolved specs are historical.
- `SPEC.md` carries "Status: living" and "Last reviewed: 2026-05-30" → [PEP1] status lifecycle; abseil.io/resources/swe-book/html/ch10.html freshness date.
- CLAUDE.md lists commands Claude cannot guess (`./run.sh` flags, `.venv/bin/pytest`) and a real gotcha (rename history, venv rebuild) → [BP] include list.
- Server facts live in one runbook that CLAUDE.md points to ("read first") → [CTX] just-in-time loading; [SKBP] one level of references.
- Multi-step procedures (deploy, audit) live in skills, both under 500 lines → [FO] skills for procedures; [SKBP] SKILL.md under 500 lines.
- Secrets are referenced by env-var name, and the repo is public with secrets in `${ENV}`/`sentinel.env` → [OWASP] store metadata, not values; [12F] config in env.

## 2. Change — amend the current standard

- CLAUDE.md "Classification model: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)" → replace with a pointer: "The live provider and model are set in `config/config.yaml` (`classification.*`); see the config reference." → This line is now FALSE: `config/config.yaml` sets `provider: openai`, `model: gpt-5.6-luna`, and the runbook says production runs Luna. `docs/explanation/architecture.md` lines 29/64/73 repeat the stale Haiku claim. Frequently changing facts in CLAUDE.md are exactly what drifts → [BP] exclude "information that changes frequently"; aicodex npm→bun drift case [blog].
- CLAUDE.md "Stack: … GDELT is currently disabled" → drop the state clause or point to `config/config.yaml` / `docs/reference/sources.md`. → Source on/off state is config, not a standing fact → [BP] exclude frequently changing info; [SKBP] avoid time-sensitive text.
- CLAUDE.md "⚠️ Critical rules (always honor)" block with bold NEVER lines → keep the block, but cap emphasis at the two life-safety lines (no prod writes without permission; never miss urgency 9–10). Remove bold or caps from the others. → "If you emphasize many lines, none of them stands out"; newer models overtrigger on aggressive language → [BP]; platform prompting guide (Opus 4.5+, Fable 5).
- CLAUDE.md prose prohibition "NEVER modify production server files" and "SSH only as deploy@" → keep the line, and PROPOSE to the user (do not apply) a `PreToolUse` hook or `permissions.deny` entry that blocks `ssh … root@`/`kossa@` and server-write commands without approval. → CLAUDE.md "is a request, not a guarantee" → [FO]; [BLOG] hard constraints go in hooks or settings. User rule: config changes are proposals first.
- `docs/README.md` "When adding a new doc, decide which of these four needs it serves" → extend it to name the non-Diataxis areas explicitly: `archive/` (historic), `ideas/` (working notes and plans, NOT current truth), and the new record areas from section 3. Index every area. → `docs/ideas/` (15 files) and `docs/reference/luna-deployment-20260920.md` (a dated record filed under reference) are unindexed or mis-typed, so agents cannot tell plan from fact → [DTX] reference "describes and nothing else"; abseil ch10 "orphan docs get marked obsolete or deleted".

## 3. Add — standards missing from the project standard worth adopting

Instruction files (CLAUDE.md, rules, skills)
- Each line of an always-loaded file passes "Would removing this cause Claude to make mistakes?"; if not, cut it or move it to a linked doc. → Bloat makes Claude ignore real rules → [BP]; [ETH] generic overviews add cost without benefit.
- Always-loaded files hold only always-true facts and "always do X" rules. A procedure of 30+ lines goes to a skill, area-specific constraints go to a `paths:` rule, and "every time X / never X" enforcement goes to a hook. → [FO]; [BLOG] three CLAUDE.md misuses.
- Rules frontmatter: only `paths:` is read. Any other field is ignored, and a YAML parse error makes the rule load unconditionally. → [MEM] rules frontmatter reference.
- Do not use `@path` imports to "save context"; they load eagerly. Use plain-text path pointers for on-demand docs. → [MEM] imports "don't reduce its context cost".
- Put maintainer-only notes (rationale for a rule, edit history) in block-level `<!-- -->` comments in CLAUDE.md. → Stripped before injection, so they cost no context → [MEM].
- When adding any instruction, search all instruction files (both CLAUDE.md files, `.claude/rules/`, skills, and the user-level `~/.claude/rules/`) for the same topic and resolve conflicts in the same edit. → Conflicts resolve arbitrarily; user and project rules do not override each other → [MEM] user-level rules.
- After an instruction-file edit, or after a major model switch, run `/doctor prompt-audit` and apply only the findings the user confirms. → It detects stale-model workarounds, dead references and contradictions, and changes nothing by itself → [MEM] audit; [LC] revisit after model releases.
- Add instructions from observed failures (a repeated mistake, a retyped correction), not from imagined needs. → [MEM] when to add; [SKBP] evaluation-driven development.
- A doc a skill reads must be one hop from SKILL.md. A doc over 100 lines needs a table of contents at its top. → Nested references get read partially with `head` → [SKBP]. Today `architecture.md` (462), `config-reference.md` (397), `server-runbook.md` (330) and `vps-hardening.md` (602) qualify.

Docs-as-code and drift
- A doc change ships in the same commit as the code or config change it describes. A commit that changes a config key, CLI flag, source, model or alert channel updates `config-reference.md`, `cli.md`, `sources.md` or the relevant explanation doc in that commit. → Primary drift control → abseil ch10; unabyss/aicodex event-driven updates [blog].
- Reference docs (`docs/reference/*`) mirror the machinery 1:1 (config keys, CLI flags, sources) in neutral voice with no instructions. → They can then be audited against code mechanically → [DTX] reference.
- Every living doc outside `archive/` carries a header line `Last verified: YYYY-MM-DD (against <commit or config>)`. Update it only when the content was actually checked. → Measurable staleness signal → abseil ch10; [RB2].
- Current behavior goes in the main text. Superseded behavior goes in a labeled "Old behavior" section or in `archive/`, never as inline "as of <date>" branches. → [SKBP] avoid time-sensitive information.

Ops runbook (life-safety)
- Organize troubleshooting by symptom first, cause second. The top symptom is "an urgency 9–10 alert cannot be delivered" (call, SMS or push path down). → [SRE] monitoring-distributed-systems.
- Each symptom entry starts with fixed fields: trigger or symptom; impact and urgency; safe actions (read-only, allowed without asking); dangerous actions (need explicit user approval); signal that the fix worked (a runnable command and its expected output); what to try next (Twilio console, second phone, rollback); last validated date. → [SRE-OC] every alert gets a playbook with severity, debugging and mitigation; [RB2] field list, adapted for a solo operator.
- Write fragile steps (deploy, rollback, DB restore, Telegram-session restore, secret rotation) as exact commands with "add no flags", each ending in a verification command. → [SKBP] match specificity to fragility; [BP] give the agent a runnable check.
- Document and periodically perform a restore drill for the SQLite DB, the Telegram session and config, and record its date in the runbook. → "You only know that you can recover … if you actually do so" → [SRE-DI].
- Validate a changed runbook with a fresh-context agent that follows only the written text (read-only steps only) and reports gaps. → Game-day validation → [RB2]; agent-as-stranger is an inference.

Records (incidents, decisions, specs)
- Add `docs/incidents/YYYY-MM-DD-<slug>.md`: blameless postmortems with impact, timeline, mitigation, root cause, and follow-ups linked to `TODO.md`. Backfill the 2026-07-30 Kh-101 call storm. → [SRE-PM]; incident history currently lives only in machine-local auto memory, which the repo and other machines cannot see → [MEM] auto memory is machine-local.
- Add `docs/decisions/NNNN-<slug>.md` (Nygard ADR): title, status (proposed/accepted/superseded/rejected), context, decision ("We will …"), consequences including negative ones. Numbers are monotonic and never reused, and the files are append-only; a reversal adds a new ADR and marks the old one superseded with a link. Seed candidates: no DTMF confirmation, no quiet hours, UTC storage with local rendering, Luna adoption and the GPT-6 rejection, 5–8 tiers push-only routing. → [ADR]; adr.github.io.
- Move dated run or deployment records (e.g. `reference/luna-deployment-20260920.md`, `ideas/*-run-record.md`) to `docs/decisions/` or `docs/incidents/`, or link them from an ADR. → They are records, not reference → [DTX].
- Normative specs use a status header (Draft / Accepted / Final / Superseded / Withdrawn). When implementation diverges, append a dated amendment entry (newest first) instead of silently rewriting the text. Use RFC 2119 keywords only in capitals. → [PEP1]; keepachangelog.com/en/1.1.0; rfc-editor.org/rfc/rfc8174.

Secrets (public repo)
- Docs name each secret by key name and location only, never by value or a partial value. For each one, record its purpose, its consumer (service or file) and its rotation steps. Include a how-to for rotating each credential without any values. → [OWASP]; [12F] "could the codebase be open-sourced at any moment"; a leaked Expo device-token incident already happened.
- `mobile/` docs state that every `EXPO_PUBLIC_*` value and anything bundled in the app is public by design. → docs.expo.dev/eas/environment-variables.
- PROPOSE to the user (do not enable unasked) GitHub secret scanning with push protection. → docs.github.com …/about-push-protection.

## 4. Rejected — official/community advice we deliberately do NOT adopt for this repo

- AGENTS.md or an `@AGENTS.md` import → Only Claude Code works in this repo, so interoperability adds a file with no reader.
- Tightening CLAUDE.md to 100–150 lines (Augment, HumanLayer) → The root file is already 51 lines. The secondhand benchmark does not justify a new limit, so keep 200.
- Removing all emphasis (claudefa.st) → Two life-safety invariants justify one marked block. Official guidance allows emphasis on a few lines.
- Regenerating CLAUDE.md with `/init` or bulk agent-writing of instruction files → [ETH] LLM-generated context files reduced success. Edits stay small, failure-driven, and user-reviewed.
- Quarterly scheduled line-by-line audits → A solo operator will not keep a calendar ritual. Use event-driven updates plus `/doctor prompt-audit` on edit or model switch.
- CI dead-link and dead-reference gates, and third-party linters (Context Guard, agnix, Schliff, faf-cli) → This is an unvetted tool chain for a one-person repo. A local check script MAY be proposed later if drift recurs.
- A named owner per doc → There is one operator, so ownership is implicit. Keep only the `Last verified` date.
- Memory-bank folders (`.claude/memory_bank/`) → They duplicate `docs/` and auto memory, adding "attention tax".
- Moving response-format or persona text into an output style → That text lives in the user-level `~/code/CLAUDE.md`, outside this repo and outside this pipeline's scope.
- A shared freshness-review metric (% of docs reviewed in 3/6 months) → Overhead without a team. The per-doc date is enough.

## 5. Directives for doc-editing agents

1. Keep each always-loaded file (root `CLAUDE.md`, unscoped `.claude/rules/*.md`) at or under 200 lines. Keep each SKILL.md under 500 lines. Do not grow root `CLAUDE.md` past about 80 lines without a stated reason.
2. Test every line you add to an instruction file with "Would removing this cause Claude to make mistakes?". Cut or move every line that fails.
3. Do not restate a number, threshold, model name, source on/off state or schedule that lives in `config/config.yaml`. Point to the config key and `docs/reference/config-reference.md`.
4. Fix the confirmed drift: replace the Haiku model line in `CLAUDE.md` with a config pointer, and correct `docs/explanation/architecture.md` (classifier rows) against `config/config.yaml` and `sentinel/classification/`.
5. Verify every factual claim you write against code or config in this session. Never copy a fact from `docs/archive/`, `docs/ideas/`, auto memory or another doc without checking it.
6. Put a doc in exactly one Diataxis type, or in `archive/`, `ideas/`, `incidents/` or `decisions/`. Index every new file in `docs/README.md` with a one-line description.
7. Write how-to docs as numbered actions only, and make each fragile step an exact command followed by a verification command and its expected output.
8. Write reference docs as neutral descriptions that mirror code structure, with no instructions and no opinions.
9. Update `Last verified: YYYY-MM-DD` only on docs whose content you actually checked.
10. Do not delete historic material. Move it to `docs/archive/`, mark it superseded, and link its living equivalent.
11. Keep ADRs and incident records append-only. Record a reversal as a new record and mark the old one superseded.
12. Name secrets only by key and location. Never write a value, a partial value, a token or a phone number into any doc.
13. Use emphasis (bold NEVER, IMPORTANT, ⚠️) only on the two life-safety invariants. Remove it elsewhere when you touch that text.
14. Scope area-specific rules with `paths:` frontmatter, and use no other frontmatter field. Do not use `@imports` to save context.
15. Before adding an instruction, grep all instruction files (both CLAUDE.md files, `.claude/rules/`, `.claude/skills/`) for the topic and resolve conflicts in the same edit.
16. Do not edit hooks, `settings.json`, permissions or user-level files, and do not change production server files. Report them as proposals for the user.
17. Keep current behavior in the main text. Put superseded behavior in an "Old behavior" section or in `archive/`, never as dated inline branches.
18. Give any doc over 100 lines that a skill or CLAUDE.md links to a table of contents at the top.
