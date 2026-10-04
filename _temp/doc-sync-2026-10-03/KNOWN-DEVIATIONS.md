# Known accepted deviations from the edit pass (editor and consistency reports)

### ?
- Added "Last verified: 2026-10-03 (deployed commit 6429124)" only to CLAUDE.md and README.md. I re-checked their full content against code and config in this session. I did not add it to dashboard/CLAUDE.md (the tunnel-mode line and the annotation endpoints were not fully re-checked), to .claude/rules/corroboration.md (a rule file; a dated line there would add always-loaded noise) or to mobile/AGENTS.md (a short instruction file).
- CLAUDE.md is 80 lines, up from 51. The growth is the blocker and major content: live routing, the deliberate Twilio-401 state, the config-is-production note and the local `--config` note. I replaced stale text instead of appending, and merged Tests and Full CLI into one line to stay at 80.
- The CLAUDE.md classifier line names the provider ("OpenAI via openai_provider.py") but not the model ID. This follows directive 3/4: use a config pointer. README.md does the same.
- In CLAUDE.md I removed bold from all lines except the two life-safety lines, which keep the ⚠️ marker (the warning icon moved from the heading to those two lines). I also removed bold from the intro and Docs lines that I touched. In dashboard/CLAUDE.md I left the pre-existing bold on lines I did not touch ("production", "never deployed", the EVENT_ID_RETENTION_DAYS note), so the edit stays surgical.
- corroboration.md keeps bold on exactly one item: the life-safety warning about the live critical-urgency protections. It is the "never miss 9-10" invariant.
- Removed "GDELT is currently disabled" and the "3 min/15 min" numbers from the CLAUDE.md Stack line. They now point to the `scheduler.fast_interval_minutes` and `scheduler.interval_minutes` config keys (directive 3: no source on/off state or schedule numbers).
- The F-003 runbook troubleshooting entry for Twilio 401 is outside my file set. CLAUDE.md now describes that known state itself, and README.md points to CLAUDE.md, not to a runbook anchor I cannot verify.
- The TODO items for the "require 2 sources" decision (F-001/F-015) and the former-invariant sign-off (F-014) are referenced by topic only ("open owner decision in TODO.md"). TODO.md is not in my file set.
- Not addressed, because it is not my finding: the dashboard has no push icon or label (the SPEC.md F-127-area finding). It is owned by the SPEC/TODO editors.

### ?
- F-065 (deploy, minor): I did not log the TODO item that asks to narrow the secret-mask regex to whole key names. Only the TODO.md editor may add TODO items, and TODO.md is outside my file set. The skill now documents the over-masking and says how to read the real value from the Step 5 backup. The pipeline should file this TODO item: "deploy 6a SECRET regex masks keyword lists and *_tokens values; narrow it to whole key names".
- F-066 (deploy, minor): For the same reason, I did not log the TODO item about the missing `|| exit 4` guards. The skill calls it "a known gap in the script" and does not point to a TODO number. The pipeline should file this TODO item: "deploy 6a drift-check script lacks exit guards after `sudo cat` and both `git show` lines".
- F-060 (deploy): I skipped the optional backup of `/etc/systemd/system/sentinel.service.d/`. The guidance says to fix only what the findings prove wrong.
- F-061 (deploy): I could not check the `openai.env` and `20-openai.conf` owner, mode and content myself, because ssh to production is not allowed. These facts come from server-runbook.md:64/:187-188 and luna-deployment-20260920.md:45-47, plus the orchestrator's server checks. I did not label the drop-in row with a mode; it says only "root".
- F-062 (deploy): I could not see the Rzeczpospolita 403 and the Twilio 401 in live logs (no ssh). I checked them against rss.py:56, twilio_client.py:61/:94, config/config.yaml:319-323 (enabled), runbook:327, luna record:78 and the owner's run context. Rzeczpospolita is a priority-2 source, so I wrote "whenever that source is fetched" instead of "every cycle".
- F-074 (sentinel-audit): I replaced the generic scale with a pointer to `classification.policy.ranges` and `policy.py system_prompt()`. I named only the band keys and one example, without the numbers, because directive 3 forbids restating config numbers.
- F-069 (sentinel-audit): I wrote "today OpenAI `gpt-5.6-luna`" together with a pointer to the config keys, because the owner's guidance asks to make the Haiku-vs-Luna split explicit. This is a deliberate small restatement of a config value.
- F-070 (sentinel-audit): I did not add the TODO item "require 2 sources?". It is outside my file set, and the owner decision says it lives in TODO.md only. The skill states the current behaviour: corroboration_required is 1, so one source triggers a call.
- F-116 (filed under TODO.md, it names the dashboard skill): I only touched my file. The `--sync` sentence now says that

### ?
- These edits went beyond the findings. Step 0 had a hidden lockout bug. It told the reader to allow only TCP 2222 in the Hetzner firewall before the first login, yet a fresh server runs SSH on port 22. As written, Step 1 and the script run would both be blocked. I added a temporary rule for port 22 from the admin IP, with an instruction to delete it after Step 3e. I also added that deletion to checklist row 1.
- I also corrected 3a. The doc offered `ssh-copy-id` to the deploy user, which cannot work because deploy has no usable password. The doc now says so and shows the script's real method, which copies root's `authorized_keys`.
- The doc points to TODO.md for five open items: the Hetzner firewall source restriction, the pending reboot and the automatic-reboot decision, `log_martians`, the AIDE baseline, and Postfix on loopback. A grep of TODO.md at edit time found none of these items. The doc assumes the TODO.md editor in this run adds them. It names them by topic only, with no numbers.
- The production facts come from prod-auditor evidence quoted in FINDINGS.md: firewall reachability, fail2ban runtime values, kernel and reboot state, sysctl runtime, AIDE timer and baseline, Postfix, the missing login-notify file, and the `whitelist.conf` content. These are UNVERIFIABLE in this session because there was no ssh access. I re-verified everything that lives in the repo against `deploy/*.sh`, `deploy/configs/*` and the commit dates of 791ed0a, dc50f73 and bd87079 (all 2026-03-23).
- F-034 sits under the server-runbook section. I touched only its part that concerns my file, the effective fail2ban values, as part of F-047 and F-059. I did not edit server-runbook.md.
- I kept the AIDE update commands (`aide --update` + cp) as they were. Whether they need an explicit `--config /etc/aide/aide.conf` on Ubuntu 24.04 is UNVERIFIED, because I could not test on the host.
- F-051 cites `03-setup-services.sh:184-214`. The file has 128 lines, and the matching content is at lines 44-68. The substance is correct, so I applied the fix.
- I did not add the "Old behavior" section that directive 17 calls for. The custom AIDE cron script was never deployed, so the doc now says that in one sentence instead.
- The vps-hardening.md file grew from 602 to 789 lines. The growth comes from additions the findings require: the TOC, the script-versus-production table, the socket override, the whitelist, the sudoers section, the file-mode table, the sandbox section and the production-sta

### ?
- No SSH (forbidden in this run). Server-only facts come from the 2026-10-03 audit evidence in FINDINGS.md and were not re-checked by me. These cover the stray .env and session files, the /etc/sentinel *.bak* copies, the live fail2ban values, the absence of the venv/ directory, LSM Latvia health, the Hetzner firewall exposure, the pending reboot, the AIDE timer, the unattended-upgrade restarts, the sentinel.env key names and the backups contents. I re-checked every repo-side claim against code, config and the skill: config/config.yaml, deploy/scripts/check-health.sh, deploy/configs/fail2ban-jail.local, the log strings in sentinel/*, state_machine retry_pending, push_client EXPO_ACCESS_TOKEN, .claude/skills/deploy/SKILL.md steps 1–7/6a–6f, and the git tags.
- 'Last verified: 2026-10-03 (deployed commit 6429124)' was added under the H1. The repo content was really re-checked. The server facts rely on the audit evidence, as stated above.
- Directive 3: the Log Rotation and Pipeline Schedule tables now point to config keys (`logging.*`, `scheduler.*`) instead of restating the numbers. The budget is referenced as `classification.budget.monthly_usd` and the value 30 is not restated, because directive 3 overrides the guidance item "budget 30 USD".
- Concurrent edit: .claude/skills/deploy/SKILL.md was edited during this run. It now backs up model-usage.db, and its rollback says to keep both DBs and restore one only if damaged. The runbook's step-5 row does not list file contents, and the rollback wording follows the new skill text.
- TODO items are referred to by topic only: health watchdog, stray secrets files, Hetzner firewall, reboot/auto-reboot. I did not edit TODO.md.
- I did not add SRE-style per-symptom field blocks to every table row, because that would bloat the file. The top symptom (undeliverable urgency 9–10 alert) has the full structure: impact, known state, safe checks, escalation, do-not.
- Directive 7 was applied to the emergency manual deploy, the rollback and the Telegram re-auth. Each is a numbered or exact command with a verification step. The restore drill is out of scope, because it would need a real server action.

### ?
- F-282 (docs/archive/README.md) was adjusted, not applied as suggested. The suggested fix says the nuclear-keyword gap is "resolved in config", and that is wrong. None of Issue #1's proposed keys are in config/config.yaml: `grep -c` returns 0 for "nuclear warheads", "nuclear munitions", "nuclear arsenal", "nuclear weapon", "głowice jądrowe", "ćwiczenia jądrowe", "ядерные учения", "Калининград", "Калінінград" and "Obwód Kaliningradzki". "nuclear strike/drill/forces" predate the audit (commit 9d60198, 2026-03-26). EN "Kaliningrad" was added 2026-04-12 (d96f4a4). The finding's other claim holds: TODO.md has no nuclear item. Both archive files now say exactly this. Flag for the TODO.md editor and the consistency agent: this is a possible live keyword-coverage gap with no TODO item, so the owner should decide on it.
- F-285 was only partly applied. Its suggested fix also asks for the same banner on docs/archive/prompts/phase-1-agent-1-models-config.md, phase-1-agent-2-database-cli.md and phase-1-agent-3-tests.md. These files are not in my file set and I left them unedited. Hand them to the consistency agent. The docs/archive/README.md prompts row now says "Do not execute any of them" for the whole folder.
- The only file move was `git mv MOBILE_APP_START_HERE.md docs/archive/MOBILE_APP_START_HERE.md`, and it is staged in the index. A grep of the repo (*.md/json/yaml/py/sh/ts/tsx, excluding .git, .venv, node_modules and _temp) and of the auto-memory dir finds no links to the old root path, so no file outside my set needs a link fix.
- F-289 asked for a "> **[ARCHIVED 2026-10-03]**" banner. I used the "> **[AMENDMENT 2026-10-03]**" form instead, because the run context makes that form binding.
- On the append-only files I also added blank lines after each banner, besides the banner lines themselves. Without them, markdown lazy continuation would fold the next line (for example "**1.5a** —" or "## Overview") into the blockquote. No existing line was changed or deleted; `git diff -U0` shows 0 removed lines on every append-only file.
- review_report_pending.md is gitignored and untracked, so the banner was added but git does not show the change. The banner suggests the owner move or delete the file.
- docs/README.md shows no deployment tag for the Luna record. F-083 suggested "currently tag deploy-20260925-143105", but that changes often, so the blurb points to the server runbook instead.
- docs/README.md is 59 lines, under 100, so no table of contents was needed. 

### ?
- UNVERIFIABLE (no ssh allowed): the server-side facts were accepted from the audit evidence without a fresh check. They cover F-030 (server copy, venv missing on host), F-031/F-105 (stray .env and session files), F-049, F-050, F-055, F-056, F-057, F-058, F-106, F-122, the prod-DB counts in F-088 (4422 rows, 736 Russian), the F-095 event IDs, and the Rzeczpospolita 403 census used for F-113. The repo-side evidence for each of these was re-checked where it exists: telegram.py:96-119, check-health.sh:9, config keys, corroborator and state_machine lines.
- F-107: I dropped the finding's line refs push_client.py:59-60 and state_machine.py:426-427 because they do not point at the cited behaviour. The claim itself stays and is backed by state_machine.py:435/525 routing.
- F-108: the line ref was corrected from sentinel.py:343 to :340, which is where `data.get` sits.
- F-238/F-120: I added `alerts.language` to the dead-key list. It is defined at sentinel/config.py:160 and grep finds no reader.
- F-092: per the "do not delete history" guidance, the ANTHROPIC_API_KEY note and the Haiku cost table were kept. They now sit under a "Superseded plan" heading with a banner instead of being dropped. The "Current" label became "Then-current".
- F-099: the PWA/FCM open questions and "SMS stays as a fallback" were not removed. They were moved under "Original plan (kept for history)" and marked resolved or superseded.
- F-282: no TODO item was added. The finding says the nuclear-keyword gap is resolved and not tracked.
- "Last verified: 2026-10-03 (deployed commit 6429124)" was added because every factual claim I touched was re-checked. The opinion and strategy sections (§4, Commentary) are not facts that can be verified.
- Size: TODO.md grew from 242 to 388 lines because 34 items were added, each kept to a few lines. It is not an always-loaded file, so there is no hard ceiling.

### ?
- F-143, Expo Enhanced Push Security: I could not verify from the code or the Expo dashboard that production has "Enhanced Security for Push Notifications" turned on. No ssh was allowed. The claim rests on docs/how-to/server-runbook.md:224-227, which lists EXPO_ACCESS_TOKEN in sentinel.env as the "Enhanced Push Security token", and on the push_client.py docstring. The doc points to the runbook as its source.
- api-setup intro: the line "production service reads its secrets from env files under /etc/sentinel/" is based on deploy/configs/sentinel.service (EnvironmentFile=/etc/sentinel/sentinel.env) and the runbook, which also mentions openai.env. The server itself was not checked.
- Twilio prices in the api-setup "Cost" section: not in the findings and not verifiable offline, so I left them unchanged.
- The "a few cents" dry-run cost estimate from F-136 was not verifiable. The doc now says "spends a small amount of real money" instead of giving a figure.
- Directive 13 (emphasis): I removed bold only from text I touched. Bold UI labels such as "Enforce a hard limit" and the account-field labels stay. The pre-existing bold in Telegram §4 ("keep this file secure", "production") was not otherwise touched, so it stays.
- Nothing was run beyond read-only checks. The direct_luna offline check, the dry run and the tests were not executed. The local-config path (data/config.local.yaml copied from the template) is checked against the code but was not run end to end. The checks were: data/ is in .gitignore; the template uses relative paths; the template's ${VAR}s are only TELEGRAM_API_ID, TELEGRAM_API_HASH and ALERT_PHONE_NUMBER, and .env.example fills all three.
- New content outside the findings: TOCs in both docs (directive 18); "Last verified: 2026-10-03 (deployed commit 6429124)" in both docs (directive 9, content re-checked); .env export lines before the Twilio and Telegram python snippets; a warning on the stale "previous tag" rollback step in luna-deployment-20260920.md (tags checked: deploy-20260925-141910 runs provider: openai).
- Directive 3: I removed restated numbers from getting-started (feed counts, intervals, log rotation) and replaced them with config keys. The corroboration "single source" fact is kept on purpose as current behavior, per the owner's run context. The 30 USD budget is stated once, in api-setup §1.

### ?
- F-149: I did not write a total test count, following the run guidance. Instead I added the command `.venv/bin/pytest tests/ -q --co | tail -1`. When run this session, it printed "583 tests collected".
- F-154: I dropped the number ("~20") instead of changing it to "39". The guidance says test counts are volatile and should not be stated. The bullet now reads "the alert-path tests are async".
- F-148: I did not put case counts or action counts in the fixture rows, because they are volatile. I kept the facts that do not change: eval_set.yaml has no phone_call (9-10) case and its highest expected urgency is 8; eval_set_human.yaml includes phone_call cases. I added a one-line command that counts the cases. I re-checked the counts this session: 44 cases (29 log_only, 15 sms) and 50 cases (28 log_only, 16 sms, 6 phone_call).
- F-146: The finding says config.example.yaml has no ${VAR} placeholders. That is partly wrong: it uses ${TELEGRAM_API_ID}, ${TELEGRAM_API_HASH} and ${ALERT_PHONE_NUMBER}. All three are listed in .env.example and present in .env. I loaded the template locally and it worked (provider openai, model gpt-5.6-luna, local paths). The doc therefore says the template "needs only the variable names listed in .env.example".
- F-150: polish_summary_guard_fresh.yaml has no code consumer. Only docs/ideas/polish-summary-guard.md references it. The doc says so ("No module or test loads it by default") and does not invent a consumer.
- F-155: The frontend table's Phase column shows "—" for EventDetailPage.test.tsx and datetime.test.ts. Finding the phase that added them would have needed a git-history dig I did not do.
- F-169: I could not name the exact config commit the 2026-09-20 report ran with. The note gives a generic `git show <commit>:config/config.yaml` recipe.
- Directive 7 (how-to docs as numbered actions only): I did not restructure either file. Both are mixed reference/how-to documents, and the brief asked for surgical edits.
- Directive 9: I added "Last verified: 2026-10-03 (deployed commit 6429124)" to both files. For model-comparison.md I re-checked the compare_models flags, the default dataset, the four model IDs, the 30 s default timeout, the dataset sizes (50 = 34+16; v2 = 36 and 64) and the help output of cached_runtime, rescore_dimensions, export_candidates and direct_luna.
- Directive 18: I added a table of contents to both files, since both are over 100 lines.
- Nothing ran beyond read-only checks: pytest collection, `--help` output,

### ?
- UNVERIFIABLE: The claim that "Enhanced Security for Push Notifications" is on, so Expo rejects sends without EXPO_ACCESS_TOKEN (F-224, F-160), comes from the owner's record of 2026-06-04 and is not in the repo. The docs attribute it to the owner's record. The repo itself only shows that push_client.py sends a Bearer header when the token is set, and that server-runbook lists EXPO_ACCESS_TOKEN in sentinel.env.
- UNVERIFIABLE: The claim that MA-1…MA-7 were validated on the device on 2026-06-03 (F-222) comes from the owner's memory only. The docs attribute it to the owner's project notes and do not state it as a fact. TODO.md does confirm "live 2026-06-03, standalone preview build".
- Accepted: The comment in the config.yaml push block saying Expo's API is "unauthenticated" is outdated. mobile-app.md says so and points to the existing TODO item on misleading config comments. Config was not edited (docs only).
- Accepted: The PushPanel Polish hint ("Wklej ten token do konfiguracji serwera") and the inert OSTATNI PUSH section are code issues. They are described truthfully and point to the existing TODO item. Code was not edited.
- Skipped: EXPO_PUBLIC_* is not mentioned. grep finds no use in mobile/ or docs, so there was nothing to qualify as public by design.
- Skipped: The api-setup.md section anchor is not used. Another editor owns that file and may rename the heading, so the link names the section in plain text instead.
- Skipped: The TODO.md:208 closure that F-221 suggests. TODO.md is outside my file set, and it already marks the placeholder item as Done.
- Limitation: mobile-app.md grew from 287 to 363 lines. The growth comes from the new production-config, known-state and payload content plus the table of contents. It stays within "no hard ceiling".
- Directive 3: I stated the push-only routing for tiers 5–8 by its config key, because the owner context makes it binding. Byte and character caps are named by their code constants. The only number written out is the code constant 3500; no config number is restated. Corroboration values are not restated.
- I added "Last verified: 2026-10-03 (deployed commit 6429124)" to all three files after re-checking their content against config, code and the mobile sources. The on-device MA behaviors themselves were not run; I only checked their UI labels by grep (Usuń, Wyczyść, ✓, dismissFromTray).

### ?
- F-234 is adjusted. The finding says 14 range bands, but it lists 13. `sentinel/classification/policy.py` uses exactly 13 band names, and the live config defines exactly 13, so the doc says 13.
- F-236: the TODO item about the misleading push comment in `config.example.yaml` is out of my file set. TODO.md already has it as item 8, "Misleading config comments", so no TODO edit was needed. The same applies to F-238: TODO.md item 6, "Dead alert config keys", already exists.
- F-240 cannot be verified in this session. The claim that production has Expo Enhanced Security turned on comes from the finding's evidence and an operator memory record. The server was not checked (no ssh). The code side was checked: `push_client.py` treats `EXPO_ACCESS_TOKEN` as optional.
- The Twilio "known state" note is also unverified this session. I added one neutral line under `alerts`: the account is deliberately unfunded, HTTP 401 since 2026-09-21, calls return when the owner recharges. It comes from the binding run context, not from a check.
- Accepted limitation: the file grew from 397 to 478 lines. The growth comes from the required table of contents, the new `classification.policy` subsection (F-234), the constraint columns (F-243) and the live-value columns (F-244). The file has no hard ceiling.
- The "16 queries" count in `sources.google_news` was replaced with a pointer to config/config.yaml and sources.md (directive 3, frequently changing fact).
- Defence24 is now named `Defence24`, its real live name, instead of "Defence24 PL". This came from verifying the source list.
- Extra correction beyond the findings: my first draft said a `retry_pending` event gets a new call round automatically on the next cycle. That is wrong. The code has no idle-cycle sweep, and a new round starts only when a later article re-dispatches the event. The doc now says this.
- An extra wording fix in the incident_memory prose: "during its call cooldown" became "the acknowledged gate prevents another call", because `cooldown_hours` is not read by any code.
- Added `Last verified: 2026-10-03 (deployed commit 6429124)` under the H1. All content was re-checked against sentinel/config.py, config/config.yaml and config/config.example.yaml. `git diff 6429124 HEAD` shows no change to config/ or sentinel/.
- I did not run the bot, did not use ssh and did not commit.

### ?
- F-203 (adjusted): The Stage 7 score bands state their numeric ranges next to the `classification.policy.ranges` band names (for example official_warning 9–10, routine 1–3). This goes against directive 3 (do not restate config numbers). I accepted it because F-203 explicitly asks for these band rules, and the bands cannot be explained without the numbers.
- F-204, F-206, F-211 (adjusted): I wrote the live on/off states as behaviour: "tiers 5-8 push-only", "push enabled", "one source triggers a phone call today". I did not restate config numbers. `max_call_retries` is described as "kept low on purpose after the 2026-07-30 call storm" with a pointer to the config comment, not as "live value 1". Reason: directive 3 overrides the finding's suggestion.
- F-206 / F-210 TODO items: I added no TODO items because TODO.md is outside my file set. I linked the existing TODO.md items by title instead: corroboration 1 vs 2, acknowledged-event guard sign-off, urgency-9 fragmentation, stale retry_pending, unacknowledged calls retried only on a new article, Telegram mislabelling, Ukraine-only shelter orders. The unused `cooldown_hours` key is already covered in TODO.md 6.1 item 6 ("Dead alert config keys").
- Out-of-finding fix: old Phone Call step 6 said a new round starts after 5 minutes and "repeats indefinitely". The code has no scheduled re-call; a new round starts only when a later article joins the event. I corrected this forward-looking false claim and pointed to the TODO items. Verified in sentinel/scheduler.py run_cycle and state_machine.py `_execute_phone_call`.
- Out-of-finding addition: Telegram known-defect sentence with a pointer to TODO.md. It comes from the TODO.md finding omission that cites pipeline.md:44.
- Structure: I renumbered the stages from 7 to 9 (queue/budget and enrichment became their own stages). I grepped for inbound anchor links to pipeline.md in docs, CLAUDE.md, tests and .claude and found none. mobile/PUSH_APP_SPEC.md checks only that the word `channel` appears, and it still does.
- Directive 9: I added "Last verified: 2026-10-03 (deployed commit 6429124)" under the H1. The whole content was re-checked against the code and config this session. `git diff 6429124 HEAD -- sentinel config` is empty.
- Directive 18: I added a table of contents.
- Size: the file grew from 217 to 307 lines. Explanation docs have no hard ceiling, and the growth comes from the queue/budget stage, the Polish-summary guard, incident memory and the revision-aware de

### ?
- Placement: every banner sits at the top of its file, directly under the H1. Several findings suggested placing it above a specific section, but the orchestrator's guidance asks for one banner per file at the top. Each banner names the affected section, so the pointer is not lost. Each file gained exactly two lines (one blank line and the banner). `git diff` shows 0 deleted or modified lines.
- Moves not done (F-267, F-269, F-274, F-276): these findings suggest moving the file to `docs/archive/`. The run context forbids moving or renaming files, so these files stay in `docs/ideas/`.
- Unverifiable (F-271): I could not check whether the OpenAI project hard cap is still $10. The banner says it was $10 on 2026-09-20, citing `docs/reference/luna-deployment-20260920.md`, and that no record shows it was raised.
- Pointer limit (F-269, F-273, F-274): these banners point to the living guide `docs/how-to/model-comparison.md`. Its line 3 still says "Production still uses Haiku". That file belongs to another editor, and the claim is filed under its own finding.
- Point-in-time values (directive 3): the budget and threshold numbers that correct stale figures ($30, 0.85/0.9, corroboration_required 1) are named by their config key and anchored to commit 6429124. The figures 420-580 per day and $11-17 per month are quoted as recorded in the message of commit 31acd3a.
- Not written on purpose: no "Last verified" line was added to any file, because all of them are append-only ideas records.
- Read-only checks run this session:
  - git log, tags and `merge-base --is-ancestor` against 6429124 for 9db4916, 8864861, 7048a91, 0cdb3cb and 31acd3a.
  - Tags: deploy-20260920-232235 points to 7048a91, and deploy-20260925-143105 points to 6429124.
  - In `config/config.yaml`: provider openai, model gpt-5.6-luna, gdelt enabled false, incident_memory enabled true with 0.85/0.9, monthly_usd 30, policy near_border_strike awareness and neutralised_drone original_severity, corroboration_required 1.
  - Code defaults in `sentinel/config.py`: incident_memory False and monthly_usd 10. `config/config.example.yaml` also has monthly_usd 10.
  - The live `classification.policy` gives prompt_hash aa4d4ca8…, computed locally with no API call.
  - `benchmark_policy_v2.yaml` has status resolved, confirmed 2026-09-20. In the v2 development fixture, mc-scramble-pl-01 is 2–3, silent, not critical.
  - `compare_models.py` still defaults to the first50 fixture (DEFAULT_DATASET), and v2 cases need `--pol

### ?
- Directive 3 was applied only in part. §6 still has a "Live" column, because F-173, F-182, F-183, F-184 and F-185 ask for live values. The column header carries the date 2026-10-03 and points to config/config.yaml as the source of truth. The budget prices per million are not repeated; the table points to config instead.
- F-192: the production row counts (sms 665 and the others) are not repeated. They are point-in-time numbers, and I could not check them without ssh. The doc states the mechanism instead, which I checked in code: a push-only delivery never updates alert_status.
- F-191: the claim that model-usage.db has file mode 600 is left out. It cannot be checked without server access.
- The Twilio 401 state since 2026-09-21 comes from the owner run context. The code cannot confirm it. The code does confirm that a Twilio error is logged and the method returns None.
- The "Last verified: 2026-10-03 (deployed commit 6429124)" line is backed only by §§1–9, which I re-checked against the code. §10 (dashboard) was not re-checked in full. A note at the top of §10 says that only the rows for classifier_input.py, types.ts and EventTimeline.tsx were re-verified.
- TODO.md is not in my file set. The doc refers to TODO items by topic only: retry of unacknowledged critical events, dead alert config keys, Cyrillic title normalization, and dashboard classifier input for OpenAI rows. Whether those items exist depends on the TODO.md editor. I did not add the TODO item that F-183 asks for, nor the optional push-icon TODO from F-202.
- Directive 13: bold emphasis is removed from all rewritten text in §§1–9. The bold in the unchanged §10 text is left as it was.
- Headings now hold plain text, with the code anchor on a "Source:" line below. This keeps the TOC anchors stable. No inbound anchor links to this file existed (checked with grep).
- The file grew from 462 to 559 lines. The growth comes from the TOC plus the modules, fields, tables and config keys the findings require. It stays within the no-bloat rule for docs without a hard ceiling.
- Extra fixes beyond the findings, all checked in code:
  - Event.aggressor and Event.event_type come from the first article and are not updated.
  - `pending` is never stored on a real event.
  - `expired` is read but never written.
  - The enricher's OpenAI vagueness call counts against the budget ledger.
  - The per-level retry_interval_minutes key is also dead.
  - The legacy `_call_api` makes one retry after 5 s.

### ?
- F-262: I added the three RSS rows from `config/config.yaml`. I did not copy the production fetch counts from the finding (4216/2161/710 and the DB article counts). I could not re-check them without ssh, and they are point-in-time statistics.
- F-264: I could not check the 7-day log census (710/710 failures with 403) without ssh. The wording rests on the audit, on the 403 already recorded in luna-deployment-20260920.md (2026-09-20), and on the existing runbook entry. The doc says "seen at the 2026-09-20 deploy and in the 2026-10-03 audit".
- F-265: Whether the OpenAI project hard cap was raised cannot be checked from the repo, so I left it UNVERIFIABLE. The banner says that nothing in the repo shows it was raised, and points to the TODO.md item "OpenAI project hard spend cap vs the 30 USD app allowance".
- F-088 (TODO.md section, sources.md part only): I added a Known Issues row and a note under the Telegram section. Both point to the TODO.md item by its title, "Telegram fetcher mislabels every channel as Ukrainian Air Force". I checked the code defect in sentinel/fetchers/telegram.py:96-119. I could not re-check the production DB counts and did not restate them.
- cli.md: I wrote the precedence order, the exit codes and the dry-run behaviour fresh from sentinel.py and scheduler.py at HEAD. This code is the same in 6429124.
- cli.md: The "Other entry points" table marks sentinel.eval.incident_memory as "Not documented elsewhere". Grep found no doc mention outside testing.md's fixture table. model-comparison.md already covers export_candidates in the working tree, so the table links it there.
- Directive 13: I removed bold emphasis only from the cli.md text I rewrote. Bold in lines I did not touch, and the bold labels in the sources.md tables, stay as they were.
- sources.md: The "16 queries" count is kept as it was. It is still correct against config, and this file is the config mirror by design.
- luna-deployment-20260920.md: This file is append-only. The diff shows 3 banner lines and 3 blank lines added, with 0 lines changed or deleted. I added no "Last verified" line, as the run rules require for append-only records.
- Directive 18: I added a table of contents to cli.md (138 lines) and to sources.md (115 lines).

### ?
CHECKS
1. Cross-file contradictions: FIXED (6 stale statements found and aligned)
   - CLAUDE.md said "Don't spam: call round repeated after retry_interval_minutes until acknowledged". That is wrong. The code has no scheduled re-call, and an unacknowledged event is called again only when a later article joins it. I aligned the line with pipeline.md, config-reference.md, architecture.md and TODO.md. Checked against state_machine.py `_execute_phone_call` and scheduler.py `run_cycle`.
   - docs/how-to/server-runbook.md troubleshooting #1 said retry_pending events "retry every few minutes". It now says a new round starts only when a later article joins the event, and points to the TODO item "Unacknowledged calls are retried only when a new article joins the event".
   - CLAUDE.md said `.env.example` holds Expo keys. It does not. The line now says to add `EXPO_PUSH_TOKEN` and `EXPO_ACCESS_TOKEN` by hand, because the template lacks them (TODO.md 6.1 item 11). This matches mobile-push-setup.md and api-setup.md.
   - docs/explanation/architecture.md CLI table hardcoded `data/diagnostic.html`. It is now `<dirname(database.path)>/diagnostic.html`, as in cli.md, testing.md and sentinel.py:140.
   - docs/reference/sources.md:24 said Rzeczpospolita fails "every cycle". It now says "every slow-lane cycle" (priority-2 source), which matches sources.md:107, the runbook and the deploy skill.
   - docs/README.md described mobile-push-setup as "provision an EAS projectId". It now says the guide