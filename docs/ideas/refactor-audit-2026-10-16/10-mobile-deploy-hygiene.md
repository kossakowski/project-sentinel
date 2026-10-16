# Auditor 10 — Mobile app, deployment, repo hygiene

Audited at master 835ed8e on 2026-10-16. Read-only; no repo file edited, no ssh, no paid calls.

What I ran this session:
- `systemd-analyze verify` on a scratch copy of `deploy/configs/sentinel.service` (systemd 255).
- `ruff check` and `ruff format --check` (no `--fix`, `--no-cache`).
- `finance/build_full_audit_20261014.py --check`, `finance/build_report.py --check` and `finance/build_hetzner_provider_report.py --check` (all three only compare; `git status` stayed clean).
- Secret and PII pattern scans over `git ls-files` and over `git log -p --all` for Expo tokens. I record file:line only, never values.

Not run: mobile `jest` and `tsc`, because `mobile/node_modules` does not exist. Every mobile finding below is from reading the code; none of them is verified by a test run.

Contract note: the task named `sentinel/alerts/push_client.py` as the payload side. `push_client.py` is only the transport. The `data` contract is built by `_build_push_data` in `sentinel/alerts/state_machine.py:301-372`. `mobile/AGENTS.md` names it correctly. I compared the two sides. All 12 keys the server emits (`state_machine.py:319-336`) match `PushPayload` (`mobile/src/messages/types.ts:46-60`), and so do their types. **No contract drift today.** The risk is that nothing enforces it (finding M3).

---

## Part 1 — Mobile app (`mobile/`)

### M1 — Store read-modify-write race can permanently lose inbox messages
- **File:line:** `mobile/src/messages/store.ts:87-95` (`ingest`), `:97-125` (`markRead`/`markAllRead`/`remove`). Concurrent callers: `mobile/App.tsx:59` (`sweepPresented` on mount and on foreground), `mobile/src/notifications/useNotificationRouting.ts:44` (cold or warm tap), `mobile/src/notifications/capture.ts:63` (foreground listener), and the screens' mutations through `useMessages`.
- **Category:** correctness bug / concurrency.
- **Severity:** med. Only inbox visibility is at risk; the 9–10 call path is not affected. For urgency 5–8, though, push is the only channel.
- **What's wrong:** each operation does `await load()` → compute → `await persist()`. Two async callers interleave at those awaits, and the last writer wins. The store's header comment says "any lost duplicate self-heals on the next dedup". That holds only for a *duplicate*. Two *different* messages are a different case:
  - The cold-start tap ingests message A while the mount sweep ingests B. One of the two writes drops the other message.
  - Each capture path then calls `dismissFromTray()` (`capture.ts:64,102`, `useNotificationRouting.ts:45`). The tray copy is deleted, so the next sweep cannot bring the lost message back. **The loss is permanent.**
  - `remove()` that interleaves with `ingest()` can bring a deleted message back. `markAllRead()` that interleaves with `ingest()` can undo a read mark.
- **Refactor:** serialize every mutation in `store.ts` through a module-level promise chain, for example `let chain = Promise.resolve(); const serial = <T>(fn: () => Promise<T>) => (chain = chain.then(fn, fn));`. Wrap `ingest`, `markRead`, `markAllRead`, `remove` and `clear` in it. Then fix the header comment.
- **Behavior-preserving:** yes for single callers. It fixes the concurrent case.
- **Effort:** S.
- **Verify:** add a jest test. Use `Promise.all([ingest(a), ingest(b)])` with distinct ids and expect both to be stored. Add a second test where `remove(x)` races `ingest(y)` and expect x to stay gone. This test should fail on today's code. Then run `npm test` and `npm run typecheck`.

### M2 — Legacy `mobile/push/` folder sits outside `src/` and half of it is dead
- **File:line:** `mobile/push/usePushReceiver.ts:39` has no call sites; only its `LastPush` type is used. `mobile/push/PushPanel.tsx:25-28,64` is the "OSTATNI PUSH" block that is never fed. `mobile/src/screens/MessageListScreen.tsx:35` reaches out with `'../../push/PushPanel'`.
- **Category:** structure / dead code.
- **Severity:** low.
- **What's wrong:** this is TODO §3.1 item 2, which is accurately described. The structural side is not in TODO:
  - The push code from the push-only phase lives in a sibling tree next to `src/`, and `src/` imports back out of it.
  - `usePushReceiver` duplicates the listener wiring that `src/notifications/capture.ts` and `useNotificationRouting.ts` now own: the same received, response and last-response handling.
- **Refactor:**
  - Delete `usePushReceiver.ts` and the `LastPush`/`lastPush` prop.
  - Either remove the "OSTATNI PUSH" section or feed it from `store.all()[0]`.
  - Move `registerForPush.ts` to `src/push/`, and move `PushPanel.tsx` with its test to `src/screens/SettingsPanel.tsx`.
  - Update `docs/explanation/mobile-app.md:188-190`.
- **Behavior-preserving:** yes, except that the inert UI section disappears.
- **Effort:** S.
- **Verify:** `npm test` and `npm run typecheck`. Run `grep -rn "push/" mobile/src`; it should return nothing.

### M3 — The push `data` contract has no shared golden fixture
- **File:line:** server `sentinel/alerts/state_machine.py:319-336` and `tests/test_state_machine.py:1318-1332`. That test asserts only that `expected_keys.issubset(...)`. Client: `mobile/src/messages/types.ts:46-60` and `mobile/src/messages/__tests__/parsePayload.test.ts`, which uses hand-written literals.
- **Category:** contract / testing.
- **Severity:** med. A silent drift would degrade the 5–8 push (the only channel) to a "thin push" fallback that nobody notices.
- **What's wrong:** the contract is enforced only by a prose rule in `mobile/AGENTS.md`. The two test suites never see the same bytes. A rename on the server, such as `summary_pl` → `summary`, would pass both suites.
- **Refactor:**
  - Add a fixture, for example `tests/fixtures/push_payload_contract.json`, that holds one full event payload, one update payload and one byte-trimmed payload.
  - A pytest test regenerates it from `_build_push_data` with a frozen uuid and clock, and asserts byte equality. It must also assert the exact key set, not a subset.
  - A jest test imports the same JSON with a relative path outside `mobile/` and asserts that `parsePayload` maps each field without falling back.
- **Behavior-preserving:** yes. The change adds tests only.
- **Effort:** S–M.
- **Verify:** rename one key on the server in a scratch branch. Both suites must go red.

### M4 — `mobile/designs/` is 953 lines of dead UI
- **File:line:** `mobile/designs/{Original,Moro,MoroActive,MoroArctic,Tactical}.tsx`. Nothing imports them; `App.tsx:6` says so.
- **Category:** dead code.
- **Severity:** low.
- **What's wrong:** the files are compiled by `tsc` (tsconfig has no `include`, so it takes everything) and they show up in searches. They also carry their own copies of the colour and font constants.
- **Refactor:** delete them; git history keeps them. If the owner wants to keep them, move them to `docs/archive/mobile-designs/` or a tag.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** `npm run typecheck` and `npm test`.

### M5 — Ingest → dismiss → badge sequence is copied three times; palette is copied in five files
- **File:line:**
  - Ingest sequence: `capture.ts:62-65` and `:98-103`, `useNotificationRouting.ts:43-46`.
  - Colours: `#0a0a0a`, `#e8e8e8`, `#3dff9a`, `#ff2e4a`, `#222` and others are repeated as literals in `MessageListScreen.tsx`, `MessageDetailScreen.tsx`, `MessageTile.tsx` and `push/PushPanel.tsx:15-21`.
- **Category:** duplication.
- **Severity:** low.
- **Refactor:**
  - Add `ingestNotification(n): Promise<StoredMessage>` in `capture.ts` (parse, ingest, dismiss) and call it from all three paths.
  - Add `src/theme.ts` for the colours and the `MONO` font.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** jest and tsc. The existing capture and routing tests cover all three paths.

### M6 — Small `parseHeadless` and `app.json` inconsistencies
- **File:line:**
  - `mobile/src/messages/parsePayload.ts:211-212`: `let title` and `let body` are never reassigned, so a headless thin push always shows "(alert)".
  - `mobile/app.json:8`: `userInterfaceStyle: "light"`, but the app is fully dark (`#0a0a0a`, `StatusBar style="light"`).
  - `mobile/app.json:13`: splash `backgroundColor: "#ffffff"`, which causes a white flash before the dark UI.
- **Category:** cleanup / cosmetic.
- **Severity:** low.
- **Refactor:**
  - Make `title` and `body` `const`, or read `taskData.notification?.request?.content` when it is present.
  - Set `userInterfaceStyle` to `"dark"` and the splash background to `"#0a0a0a"`. Both are native config changes, so they need an EAS rebuild; batch them with TODO §3.1.
- **Behavior-preserving:** the code part is yes. The `app.json` part is a visible but intended change.
- **Effort:** S.
- **Verify:** tsc; on-device check after the next preview build.

### M7 — Historic spec files and refiner manifests sit at the mobile root
- **File:line:** `mobile/INBOX_APP_SPEC.md` (710 lines), `mobile/PUSH_APP_SPEC.md` (527 lines), `mobile/spec_manifest.json`, `mobile/inbox_spec_manifest.json`.
- **Category:** hygiene.
- **Severity:** low.
- **What's wrong:** both specs are DONE (TODO §3), but they sit next to the live code. The repo convention is `docs/archive/` for historic specs.
- **Refactor:** `git mv` all four files to `docs/archive/mobile/` and fix the links in `TODO.md` §3/3.1 and `docs/explanation/mobile-app.md`.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** `grep -rn "INBOX_APP_SPEC\|PUSH_APP_SPEC" --include=*.md .` shows only updated links.

### M8 (cross-area, for the alerts auditor) — Push formatting lives inside the alert state machine
- **File:line:** `sentinel/alerts/state_machine.py:38-372`. Its SMS and push size constants, `_format_push`, `_build_sources_payload`, `_data_byte_size`, `_truncate_to_byte_budget` and `_build_push_data` take about 330 lines before `class AlertStateMachine` starts.
- **Category:** structure.
- **Severity:** low–med.
- **Refactor:** move the pure builders to `sentinel/alerts/push_payload.py`, and the SMS builders to `sms_format.py` if wanted. Re-export the old names so tests and imports keep working. Update `mobile/AGENTS.md` so it points at the new file as the contract's home. This pairs with M3.
- **Behavior-preserving:** yes.
- **Effort:** S–M.
- **Verify:** `.venv/bin/pytest tests/test_state_machine.py tests/test_push_client.py -q`.
- **Also noted, not refactor:** `ExpoPushClient.send_push` (`push_client.py:62-68`) makes one attempt with no retry on a transient HTTP error and never checks Expo receipts. For tiers 5–8, push is the only channel. This belongs with the alerting auditor.

---

## Part 2 — Deployment

### D1 — TODO 6.1 #2 is mis-described, and its proposed fix would hurt life-safety
- **File:line:** `deploy/configs/sentinel.service:12-15`.
- **Category:** deploy correctness / life-safety.
- **Severity:** **high**, because the fix that TODO.md prescribes is the danger.
- **What's wrong:** `systemd-analyze verify` (systemd 255) prints only `sentinel.service:15: Unknown key name 'StartLimitIntervalSec' in section 'Service', ignoring.` It does **not** complain about `StartLimitBurst`, which systemd still accepts in `[Service]` for compatibility. The effective limit is therefore 5 starts in the default 10 s. With `RestartSec=30` that limit can never trip, so the unit retries forever.
  - TODO's fix is to move both keys to `[Unit]` as written (5 starts in 300 s).
  - With `RestartSec=30`, five crash-restarts fit inside 300 s (at 0, 30, 60, 90 and 120 s).
  - systemd would then put the unit in `failed` and **stop restarting it permanently**. Today's watchdog (`check-health.sh`) cannot alert anyone (TODO §0).
  - A crash loop, for example a transient DNS or OpenAI outage at import time, would turn into a silent, permanent outage of a life-safety monitor.
- **Refactor:** do not apply TODO's version. Delete both keys from `[Service]` and add `StartLimitIntervalSec=0` under `[Unit]`. That disables rate limiting explicitly: restart forever, every 30 s, which is today's effective behaviour made explicit. Rewrite TODO 6.1 #2 to match.
- **Behavior-preserving:** yes. The behaviour stays the same; the config is honest and no longer warns.
- **Effort:** S. It is a server change, so it needs the owner's go, via `/deploy` or by hand together with D3.
- **Verify:** `systemd-analyze verify deploy/configs/sentinel.service` prints no "Unknown key". On the server, `systemctl show sentinel -p StartLimitIntervalUSec -p StartLimitBurst` returns `0` after the change.

### D2 — `check-health.sh` is broken in a third way that TODO does not mention
- **File:line:** `deploy/scripts/check-health.sh:9,25-31`.
- **Category:** deploy correctness / watchdog.
- **Severity:** med. The venv path and the Twilio-only channel are already TODO §0.
- **What's wrong:** even with `PYTHON` fixed to `.venv`, the script runs `python -c "from sentinel.alerts.twilio_client import ..."` from cron's working directory, which is `$HOME=/home/deploy`. It never `cd`s into `/home/deploy/sentinel`, and `python -c` puts the current directory on `sys.path`. The import therefore fails with `ModuleNotFoundError` before Twilio is even tried. In addition, `$MSG` is spliced into Python source; that is harmless today because the strings are constant. TODO §0 says "Even with the path fixed, its only channel is Twilio SMS". That is incomplete: with the path fixed, it still cannot import.
- **Refactor:** rewrite the alert step as `cd /home/deploy/sentinel && .venv/bin/python sentinel.py --health-alert` (new CLI flag) or as `deploy/scripts/health_alert.py`, so the `sys.path` is correct. Send the alert through `ExpoPushClient` first and Twilio second, which matches the TODO §0 decision. Pass the message as an argv, not by string splicing.
- **Behavior-preserving:** no; it turns on a watchdog that never worked.
- **Effort:** S–M.
- **Verify:** locally, run with `HEALTH_FILE` pointing at a stale temp file, `--config data/config.local.yaml` and a `--dry-run` push. Then, with the owner's permission, run it once on the server by hand.

### D3 — Fresh-install path drifts in four places (extends TODO 6.1 #15/#16)
- **File:line:** `deploy/02-deploy-app.sh:61-67` and `:121` (`venv`; TODO #16), `:78` (copies the example config; TODO #16), `:90-94`, `:97-104`, `deploy/03-setup-services.sh:40`.
- **Category:** deploy drift.
- **Severity:** med. A rebuild from `deploy/` would come up without classification and without push.
- **What's wrong (new beyond TODO):**
  - `:97-104` is the env template the script prints. It lists the legacy `ANTHROPIC_API_KEY` but not `OPENAI_API_KEY`, `EXPO_PUSH_TOKEN` or `EXPO_ACCESS_TOKEN`.
  - `:90-94` copies the repo-root `.env` into `/etc/sentinel/sentinel.env` but leaves the original in the code checkout. This is the likely origin of the stray world-readable `/home/deploy/sentinel/.env` in TODO §0. The fix: after copying, `shred`/`rm` the source, or refuse when it exists.
  - `03-setup-services.sh:40` installs only the base unit. Without the drop-in (TODO #15) there is no `OPENAI_API_KEY`.
- **Refactor:** do one "rebuild parity" change: `.venv`, the tracked `config/config.yaml`, `deploy/configs/sentinel.service.d/20-openai.conf` installed by 03, the full env-key template, and removal of the source `.env`.
- **Behavior-preserving:** no change for the live server; it fixes the fresh-install path.
- **Effort:** M.
- **Verify:** `bash -n` on both scripts. Ideally, a throwaway Hetzner VM or a local Ubuntu 24.04 container runs 01→02→03, then `systemctl cat sentinel` shows the drop-in and `--health` passes.

### D4 — Dependencies are unpinned, runtime and dev are mixed, and nothing is locked
- **File:line:** `requirements.txt:1-21`, `pyproject.toml` (no `[project]` table).
- **Category:** reproducibility / supply chain.
- **Severity:** med–high, because a rebuild is the disaster-recovery path.
- **What's wrong:**
  - **Open ranges:** only `twilio` and `python-dotenv` are pinned. `apscheduler>=3.10` and `telethon>=1.36` have no upper bound, and both projects have major rewrites (APScheduler 4, Telethon 2) with incompatible APIs. `httpx>=0.27`, `pydantic>=2.0`, `anthropic>=0.40`, `feedparser>=6.0` and `rapidfuzz>=3.0` are also open.
  - **Server drift:** the server venv is never recreated (SKILL 6d), and pip leaves already-satisfied packages alone. The server therefore runs whatever resolved in March, while a fresh rebuild would resolve to unknown newer majors.
  - **Dev and dashboard packages in production:** `pytest`, `pytest-mock`, `pytest-cov` and `pytest-asyncio` are installed on prod. So are `flask` and `flask-cors`, which only the local-only `dashboard/` imports.
  - **Lint tooling:** `ruff` and `pre-commit` are installed in the local venv but declared nowhere.
- **Refactor:**
  - Move the dependencies into `pyproject.toml` `[project] dependencies` with compatible ranges, for example `apscheduler>=3.10,<4` and `telethon>=1.36,<2`.
  - Add `[project.optional-dependencies] dev = [pytest…, ruff, pre-commit]` and `dashboard = [flask, flask-cors]`. Add `requires-python = ">=3.11"`.
  - Generate `requirements.lock` with hashes (`uv pip compile` or `pip-compile --generate-hashes`) from the **server's** current `pip freeze`, so the lock records what prod actually runs.
  - `/deploy` 6d then installs the lock. Keep `requirements.txt` as `-r` or as the lock, so the systemd and SKILL paths stay the same.
- **Behavior-preserving:** yes, if the lock is seeded from the server freeze.
- **Effort:** M.
- **Verify:** `.venv/bin/pip install -r requirements.lock --dry-run` reports nothing to change locally. The owner, or `/deploy`, compares the lock with `pip freeze` on the server read-only. Then run `pytest`.

### D5 — `/deploy` keeps about 120 lines of untestable bash and Python inline in SKILL.md
- **File:line:** `.claude/skills/deploy/SKILL.md:144-177` (backup), `:198-250` (drift check: TODO 6.1 #14), `:253`, `:259` (prose workarounds for script gaps), `:264-300`.
- **Category:** deploy tooling structure.
- **Severity:** med.
- **What's wrong:** the drift check is pure Python with clear inputs (three YAML files) and outputs (exit code 0, 2 or 3). It cannot be unit-tested because it lives in a markdown heredoc. Its known bugs (TODO #14) are patched with prose instructions to the agent instead of code. The host and port are also hard-coded 14 times in the skill.
- **Refactor:**
  - Extract `deploy/scripts/config_drift_check.py` and `deploy/scripts/remote-backup.sh`, and test the former locally with three tiny YAML fixtures.
  - Fix TODO #14 in that file: match whole key names with `re.compile(r"(^|_)(token|key|secret|password|sid|auth)s?$")` on the last path segment, minus `max_tokens`, and add explicit `|| exit 4` after `sudo cat` and `git show`.
  - The SKILL then calls `ssh … 'cd sentinel && .venv/bin/python deploy/scripts/config_drift_check.py "$TAG"'`. Because the script comes from the fetched tag, use `git show "$TAG:deploy/scripts/config_drift_check.py" | .venv/bin/python -`.
  - Define `HOST` and `PORT` once at the top of the skill.
- **Behavior-preserving:** yes. The masking change is the intended TODO #14 fix.
- **Effort:** M.
- **Verify:** new `tests/test_config_drift_check.py` with these cases: secret masked; keyword list not masked; `sudo cat` failure gives exit 4; `git show` failure gives exit 4; a server-only edit gives exit 3.

### D6 — Half-deployed window: pip runs after checkout and config sync
- **File:line:** `.claude/skills/deploy/SKILL.md:281-287` (6d after 6b and 6c).
- **Category:** deploy ordering.
- **Severity:** low–med. The SKILL itself documents the risk.
- **Refactor:** install the new tag's requirements before 6b, while the old code still runs: `git show "$DEPLOY_TAG:requirements.txt" > "$tmp" && .venv/bin/pip install -r "$tmp"`. The pip failure then happens with the server still untouched, and the "half-deployed" warning goes away. pip only adds or upgrades packages, which is safe for the running old process as long as D4's upper bounds hold.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** dry-read the SKILL; on the next `/deploy`, step 6d's failure message no longer applies.

### D7 — Logs are kept by three overlapping mechanisms
- **File:line:** `sentinel/logging_setup.py:34-47` (RotatingFileHandler 50 MB × 5 plus a stdout handler), `deploy/configs/sentinel-logrotate` (daily, 14 days, `copytruncate` on the same file), `deploy/configs/sentinel.service:47-48` together with `03-setup-services.sh:58-64` (journald 500 MB or 30 days).
- **Category:** ops simplification.
- **Severity:** low.
- **What's wrong:** two rotators act on `/var/log/sentinel/sentinel.log`. The Python handler renames the file when it reaches its size limit, while logrotate copies and truncates the same file daily. Every line is also stored a third time in journald. CLAUDE.md notes that log lines older than 2026-09-21 are not kept, which is consistent with retention nobody owns.
- **Refactor:** pick one regime. One option: drop the logrotate file and keep Python rotation plus journald. The other: keep only journald, `logging.file: null` in prod, and raise `MaxRetentionSec`. Document the choice in the runbook.
- **Behavior-preserving:** yes, apart from where old logs live.
- **Effort:** S.
- **Verify:** on the server (owner) run `ls -l /var/log/sentinel/` and `journalctl --disk-usage`.

### D8 — The cron DB backup misses the cost ledger and stays on the same disk
- **File:line:** `deploy/scripts/backup-db.sh:7,16-19`.
- **Category:** ops.
- **Severity:** low.
- **What's wrong:** only `sentinel.db` is backed up daily. `model-usage.db`, the OpenAI cost ledger, is backed up only at `/deploy` time. All copies sit on the same VPS disk.
- **Refactor:** add `sudo sqlite3 /var/lib/sentinel/model-usage.db ".backup …"`, the same as SKILL step 5. Off-host copying is an owner decision; log it to TODO.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** `bash -n`; one manual server run (owner).

---

## Part 3 — Repo hygiene

### H1 — `.gitignore` contradicts what is tracked
- **File:line:** `.gitignore:15` (`config/config.yaml` is ignored but tracked, and CLAUDE.md says it is tracked on purpose), `.gitignore:6` (`data/` is ignored but 8 files under it are tracked: `data/eval/human-labels.yaml` and `data/audit-reports/*`), and the nine individual `.code-refiner-state-*` lines (`:12-13,30-35`) that miss `-redesign-phase0/2` (TODO 6.1 #13).
- **Category:** hygiene.
- **Severity:** med.
- **What's wrong:**
  - New files in `data/eval/` silently never get committed.
  - The owner's ground-truth labels, which are the only source of truth for classification, sit in an ignored directory.
  - Every new refiner state directory needs a hand-added line. The redesign ones were missed, and that is how they reached the public repo.
  - `.claude/settings.local.json` is ignored only by the user's global gitignore, not by the repo's.
- **Refactor:**
  - Replace the nine lines with `.code-refiner-state*/` and `.code-surgeon-state*/`.
  - Delete the dead `config/config.yaml` line.
  - Move `data/eval/human-labels.yaml` to `tests/fixtures/` or `eval/labels/` and update `docs/ideas/HANDOFF-fix-vague-inputs.md:108,138` and any loader.
  - Add `.claude/settings.local.json`.
- **Behavior-preserving:** yes. The label move needs a path update wherever the file is read.
- **Effort:** S.
- **Verify:** `git status --ignored` before and after; `git ls-files -ci --exclude-standard` (tracked-but-ignored list) returns nothing.

### H2 — Mutable audit state is tracked, which blocks `/deploy`'s clean-tree check
- **File:line:** `data/audit-reports/.last-audit-timestamp` (tracked), written by `.claude/skills/sentinel-audit/SKILL.md:285`. Evidence: `git stash list` → `stash@{4}: On master: pre-deploy: audit timestamp`.
- **Category:** hygiene / workflow friction. This extends TODO 6.1 #13 with the concrete harm.
- **Severity:** low–med.
- **What's wrong:** each `/sentinel-audit` run dirties a tracked file. `/deploy` step 1a then refuses to deploy until the file is stashed or committed. Six old reports from March and April are tracked, and newer ones are not.
- **Refactor:** `git rm --cached data/audit-reports/.last-audit-timestamp`. Decide whether to version the reports; if yes, move them to `docs/audits/`, which is outside the ignored `data/`.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** run the audit skill's timestamp step, then `git status --porcelain` is empty.

### H3 — Tool output from one-off runs is committed (`_temp/`, refiner state, `specs/`)
- **File:line:**
  - `_temp/doc-sync-2026-10-03/*` (8 files, about 0.9 MB, mostly `FINDINGS.json` and `FINDINGS.md`) came in through the single commit 7284b88, "backup: automatyczna migawka 2026-10-04". That looks like a one-time blanket snapshot commit on master.
  - `.code-refiner-state-redesign-phase{0,2}/*` (12 files; the branches are closed per TODO §0).
  - `specs/fulltext-second-read/*` (deferred 2026-09-25 per `PRODUCTION_NOTES.md:3`).
- **Category:** hygiene.
- **Severity:** low. Together it is about 1.4 MB of noise in a public repo, and grep and agent context pick it up.
- **Refactor:**
  - `git rm -r --cached` the refiner state directories, which H1's glob covers afterwards.
  - Move `_temp/doc-sync-2026-10-03/{FINDINGS.md,KNOWN-DEVIATIONS.md}` to `docs/archive/doc-sync-2026-10-03/` if the owner wants a record; otherwise delete. Delete `wf*.js`. Add `_temp/` to `.gitignore`.
  - Move `specs/fulltext-second-read/` under `docs/ideas/`, where deferred designs live.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** `git ls-files | grep -E '^(_temp|specs|\.code-refiner)'` is empty; doc links resolve.

### H4 — `finance/` dated builders rot: one already fails its own `--check`
- **File:line:**
  - `finance/build_hetzner_provider_report.py:861`: `assert len(ledger) == 42` fails now, because it reads the **living** `finance/ledger.csv`, which has grown.
  - `finance/build_report.py`, `build_reconciliation_update.py` and `build_coding_scenario.py` each hard-code a dated `OUT` directory (`:11`).
  - `finance/build_full_audit_20261014.py` (3352 lines) is the only one `docs/reference/costs.md:10` names as current. Its `--check` passed this session.
- **Category:** hygiene / structure.
- **Severity:** low. Finance is not runtime, but these 6,000 lines of Python sit at the finance root and look like live tooling.
- **What's wrong:** these are one-off generators for frozen, dated snapshots, yet they read living inputs, so they stop reproducing their snapshots. Four of the five are superseded.
- **Refactor:**
  - Move each superseded builder into its own report directory, for example `finance/reports/2026-10-11-hetzner-provider/build.py`.
  - Point dated builders at a frozen copy of their input under `input/`, the way the 2026-10-14 audit already does.
  - Keep a single living entry point, `finance/build.py`, which is the current full-audit builder renamed without its date, and add its `--check` to the test suite or to pre-commit.
- **Behavior-preserving:** yes for the outputs.
- **Effort:** M.
- **Verify:** each builder's `--check` exits 0 from its new location.

### H5 — Lint is configured but never enforced; there is no CI and no type check
- **File:line:** `pyproject.toml:9-29`, `.pre-commit-config.yaml`, and there is no `.github/workflows/`. `ruff check` this session: 78 errors (38 UP017, 12 F401, 11 E402, 8 I001, 7 F541, …), 23 of them in `test_e2e_live.py`. `ruff format --check`: 11 files would be reformatted, among them `sentinel/fetchers/telegram.py`, `google_news.py` and `processing/normalizer.py`, `keyword_filter.py`.
- **Category:** tooling.
- **Severity:** med, given the "every phase passes its tests" rule and a public repo with free Actions.
- **What's wrong:**
  - The pre-commit hook checks only staged files, so old files never get fixed.
  - Nothing runs `pytest`, `ruff` or the mobile `jest`/`tsc` automatically. `/deploy` 1b runs only pytest, and only locally.
  - There is no mypy or pyright, although the codebase is fully typed with pydantic.
- **Refactor:**
  - (a) One "ruff --fix + format" commit, which is mechanical.
  - (b) A minimal `.github/workflows/ci.yml`: Python 3.12, install the lock and dev extras from D4, `ruff check`, `ruff format --check`, `pytest -m "not integration"`; in `mobile/`: `npm ci && npm test && npm run typecheck`. No secrets are needed, because the tests mock their providers.
  - (c) Optional: `pyright` in basic mode on `sentinel/` only, as a non-blocking job.
  - (d) Add a mobile gate to `/deploy` 1b when `mobile/` changed.
- **Behavior-preserving:** (a) yes, but review the E402 and SIM fixes, which are not auto-fixed. (b)–(d) are tooling only.
- **Effort:** S for (a), M for (b)–(d).
- **Verify:** `ruff check .` and `ruff format --check .` exit 0; the CI run is green on a PR.

### H6 — `test_e2e_live.py` at the repo root is stale and places a real call
- **File:line:** `test_e2e_live.py:1-20,144` (`Classifier(config)` is the legacy Haiku path, not the live OpenAI provider); `docs/reference/cli.md:130`.
- **Category:** stale code.
- **Severity:** low.
- **What's wrong:** the script claims to exercise "EVERY component", but it skips the live classifier provider and incident memory. It is named like a pytest file at the repo root; pytest's `testpaths=["tests"]` keeps it out of normal runs. It also holds 23 lint errors. `--test-alert` already covers the real-call check.
- **Refactor:** delete it, or move it to `scripts/e2e_live.py` and switch it to the provider factory `classification.provider`. Update `cli.md:130`.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Verify:** `grep -rn test_e2e_live` shows only updated docs.

### H7 — Root layout: `sentinel.py` CLI next to the `sentinel/` package; root `SPEC.md` is the dashboard spec
- **File:line:** `sentinel.py` (16 KB CLI, and the systemd `ExecStart` target at `deploy/configs/sentinel.service:11`), `SPEC.md` (CLAUDE.md calls it the "Dashboard spec (living)").
- **Category:** structure.
- **Severity:** low.
- **What's wrong:**
  - A module and a package with the same name sit in one directory. It works because packages win, but it confuses tools and readers.
  - `SPEC.md` at the root reads as the system spec, but it describes the dashboard.
- **Refactor:**
  - Move the CLI body to `sentinel/cli.py` and add `sentinel/__main__.py`. Keep `sentinel.py` as a 3-line shim, so `ExecStart`, `run.sh` and the docs keep working. Optionally add a `[project.scripts] sentinel = "sentinel.cli:main"` entry point.
  - `git mv SPEC.md dashboard/SPEC.md` and fix the links in CLAUDE.md and the docs.
- **Behavior-preserving:** yes.
- **Effort:** S–M.
- **Verify:** `./run.sh --health` with a local config, `pytest tests/test_cli.py`, and `systemd-analyze verify` unchanged.

### H8 — Stale branches, stashes, worktrees and a leaked token in a local stash
- **Facts:** `git branch -a` lists 13 local branches.
  - Merged into master and deletable: `eval/gpt-6-luna`, `eval/model-comparison`, `eval/model-suite`, `fix/incident-memory`, `hotfix/temp-disable-calls`, each local and on origin.
  - Unmerged and closed by the owner: `redesign-phase0-geography`, `-phase1-alerting`, `-phase2-policy`. TODO §0 says they stay on GitHub as a record, so a `archive/redesign-*` **tag** each, then deleting the branches, keeps the record with less clutter.
  - Unmerged and old: `backup/docs-overhaul-pre-rebase` (2026-05-31), `docs-overhaul` (2026-07-11), `code-surgeon/multi-tenant-evolution` (2026-03-28), `eval/clarified-policy` (2026-09-23), `build/worktree-base` (2026-08-28, checked out in worktree `/home/kossa/code/project-sentinel-buildtree`).
  - There is also a detached worktree, `/home/kossa/code/sentinel-mobile`. Memory says the mobile worktree was removed on 2026-06-03, so this is a different or re-created one; check it.
  - There are 5 stashes from 2026-06-03 to 06-05. The stash commit `4b96337` ("untracked files on docs-overhaul") contains a **real Expo push token** (`ExponentPushToken[REDACTED]`). It is local only: no remote ref contains it, according to `git branch -a --contains`. Memory records that this token was neutralized by Enhanced Push Security. It is still worth dropping that stash.
- **Category:** hygiene / secret.
- **Severity:** low (the token is neutralized and local only). The branch clutter is low.
- **Refactor:** the owner decides each branch. Proposed:
  - Delete the 5 merged branches locally and on origin.
  - Tag and delete the 3 redesign branches.
  - Ask about the other 5.
  - `git stash drop` the 5 stashes after a look.
  - Prune the worktrees.
- **Behavior-preserving:** yes. Deleting branches on origin is irreversible without the tags, so it needs the owner's go.
- **Effort:** S.
- **Verify:** `git branch -a`, `git stash list` and `git worktree list`.

### H9 — Public-repo exposure scan
- **Result:** no live credentials in tracked HEAD files.
  - Checked: OpenAI `sk-`, `sk-ant-`, Twilio `AC…`/`SK…`, GitHub `gh?_`, AWS `AKIA`, PEM keys, Expo tokens.
  - `tests/fixtures/eval_set_human.yaml:247` matches `sk-` only because a slug contains "…polsk-…".
  - `docs/how-to/api-setup.md:348` holds a placeholder `ExponentPushToken[REDACTED]`.
  - The 32-hex values in `.env.example:21` and `api-setup.md:240,244,344` are the placeholder `abcd…7890`.
  - All phone numbers are test fixtures (`+48123456789`, `+48999888777`, and Twilio magic numbers `+1500…`/`+1555…`).
- **Personal data in public files (low; the owner decides):**
  - The owner's personal Gmail address appears in `docs/how-to/server-runbook.md:5` and is **hard-coded** in the GDELT User-Agent at `sentinel/fetchers/gdelt.py:124`. That is also against the "nothing hardcoded" rule. Move it to `sources.gdelt.user_agent` in config, or use a project alias.
  - The production IP and SSH port appear 37 times across `.claude/skills/deploy/SKILL.md`, the runbook, `SPEC.md`, `docs/archive/*`, `data/audit-reports/*`, `tests/test_dashboard_db.py` and `sentinel/eval/*`. Key-only SSH and fail2ban limit the risk. Still, it hands scanners a target, and TODO 6.3 #2 says the firewall does not restrict SSH. Consider an `SENTINEL_HOST` env var or ssh-config alias (`ssh sentinel-prod`) in the skill and docs.
  - `finance/` holds the owner's detailed personal spending with dates and amounts. The design is deliberately public-safe (there is a `public_evidence_label` field, and `finance/private/` is ignored). I found no IBAN, card number, NIP or invoice number. This is only a flag that it is public.
- **Effort:** S.

### H10 — Untracked but valuable scripts hide in the ignored `data/`
- **File:line:** local only. `data/` holds `grading_server.py`, `install-luna-production.py`, `receive-openai-key.py`, `luna-language-repeat.py`, `test-polish-summary-guard-live.py`, `luna-setup-browser.cjs` and `playwright-chrome-session.mjs`.
- **Category:** hygiene / bus factor.
- **Severity:** low.
- **What's wrong:** these look like production-install and grading tooling. They are in no backup and no history, and the next `rm -rf data/` deletes them. Some may contain secrets; I did not read them.
- **Refactor:** the owner reviews them. Move the reusable ones, after a secret scan, to `scripts/` (tracked) and delete the rest.
- **Behavior-preserving:** yes.
- **Effort:** S.

---

## TODO cross-check
- **6.1 #2: mis-described, and the prescribed fix is harmful.** See D1. Only `StartLimitIntervalSec` is ignored. Moving both keys to `[Unit]` would make systemd give up after 5 crashes in 300 s.
- **§0 "No working out-of-band watchdog": incomplete.** See D2. Even with the venv fixed, the `sentinel` import fails from cron's working directory.
- **6.1 #13, #14, #15, #16 and §3.1 #2:** accurate. Extended by H2 (the deploy friction), D5 (move the script out of the markdown), D3 (env template and the `.env` copy) and M2 (the structure).

## Proposed phase grouping

| Phase | Content | Behavior change | Gate |
|---|---|---|---|
| **P1 — Safe hygiene (one PR, repo only)** | H1 (gitignore globs and label move), H2, H3, M4, M7, H6, H8 (local branches and stashes; remote deletes after the owner's go) | none | `pytest`, `npm test` and `npm run typecheck` in a fresh `npm ci`; `git ls-files -ci --exclude-standard` empty |
| **P2 — Tooling baseline** | H5a (ruff fix and format commit), D4 (pyproject deps, extras, lock seeded from the server freeze), H5b CI workflow, H4 (finance builders) | none (lock = prod versions) | CI green; `pip install -r requirements.lock --dry-run` shows no changes on the server (read by the owner) |
| **P3 — Mobile correctness and structure (one EAS rebuild batch with §3.1)** | M1 (store mutex and race tests), M3 (shared contract fixture, both suites), M2, M5, M6 | M1 fixes lost messages; M2 removes the inert UI; M6 is cosmetic | jest and tsc green; the new race test fails before the fix and passes after; on-device check after `eas build --profile preview` |
| **P4 — Deploy tooling (needs `/deploy`, owner present)** | D1 (`StartLimitIntervalSec=0`), D5 (drift-check script and tests), D6 (pip before checkout), D3 (rebuild parity with the 20-openai drop-in), D8 | D1: none (makes today's behaviour explicit) | `systemd-analyze verify` clean; `tests/test_config_drift_check.py`; one `/deploy` end to end |
| **P5 — Watchdog and ops (owner decisions)** | D2 (working health alert over push), D7 (one log regime), H9 (host alias, GDELT UA to config), H10, M8 | D2 turns on alerting | manual stale-health drill on the server with the owner's permission |
