---
name: deploy
description: >-
  Deploy Project Sentinel to production. Runs pre-flight checks (uncommitted changes,
  failing tests, unmerged branch), merges current branch to master, tags the deploy commit,
  pushes master and tag to remote, creates a full server backup (code, config, database,
  cost ledger, Telegram session), checks the live config for server-only edits, checks out
  the tagged commit on the server, syncs the config, installs dependencies into the existing
  venv, restarts the service, and verifies everything is running. Only invoke when
  the user explicitly calls /deploy. Do NOT auto-trigger.
---

# /deploy — Project Sentinel Production Deployment

You are deploying Project Sentinel to its production Hetzner VPS. Invoking /deploy is explicit authorization for all production server modifications — no additional user confirmation is needed at any step. Execute the entire pipeline automatically, stopping only if a step fails.

## Server Reference

<server_details>
- **Host:** 178.104.76.254
- **SSH port:** 2222
- **SSH user:** deploy (NEVER use root@ or kossa@ — wrong usernames trigger fail2ban bans and lock you out)
- **SSH command:** `ssh -p 2222 deploy@178.104.76.254`
- **systemd service:** sentinel
</server_details>

<server_file_layout>
| Path | Contents | Owner | Notes |
|------|----------|-------|-------|
| `/home/deploy/sentinel/` | Application code (git clone) | deploy:deploy | Detached HEAD on the deployed `deploy-*` tag (set by 6b) |
| `/home/deploy/sentinel/.venv/` | Python venv (server-side) | deploy:deploy | Never recreated; 6d installs `requirements.txt` into it on every deploy |
| `/etc/sentinel/config.yaml` | Live config | root:sentinel 640 | Needs sudo to read; overwritten from the repo's `config/config.yaml` in 6c |
| `/etc/sentinel/sentinel.env` | Twilio, Telegram, Expo push secrets, legacy Anthropic key | root:deploy 640 | Never touch: not read, not backed up, not deployed |
| `/etc/sentinel/openai.env` | `OPENAI_API_KEY` for the live classifier | root:root 600 | Never touch: not read, not backed up, not deployed |
| `/etc/systemd/system/sentinel.service.d/20-openai.conf` | systemd drop-in that loads `openai.env` | root | Not managed by /deploy. The repo's `deploy/configs/sentinel.service` is not the full live unit |
| `/var/lib/sentinel/sentinel.db` | SQLite database | sentinel:sentinel | Hot-backup via sqlite3 .backup |
| `/var/lib/sentinel/model-usage.db` | OpenAI cost ledger (SQLite) | sentinel:sentinel 600 | Hot-backup needs `sudo sqlite3` |
| `/var/lib/sentinel/sentinel_session.session` | Telegram auth session | sentinel:sentinel 600 | Needs sudo to read |
| `/var/lib/sentinel/health.json` | Health status | sentinel:sentinel | Written after each scheduled cycle, not after the startup cycle |
| `/home/deploy/backups/` | Backup storage | deploy:deploy | `deploy-<ts>/` snapshots (6f keeps the 10 newest) |
</server_file_layout>

---

## Prerequisites (One-Time Setup)

The server must have a git clone of the repository at `/home/deploy/sentinel/` with a GitHub deploy key configured for SSH access. In short:

1. On the server, generate a deploy key: `ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""`
2. Add the public key (`~/.ssh/github_deploy.pub`) as a **Deploy Key** in GitHub repo settings (read-only is sufficient)
3. Configure SSH on the server (`~/.ssh/config`):
   ```
   Host github.com
     IdentityFile ~/.ssh/github_deploy
     IdentitiesOnly yes
   ```
4. Switch remote to SSH: `git remote set-url origin git@github.com:kossakowski/project-sentinel.git`
5. Verify: `cd /home/deploy/sentinel && git fetch --tags origin`

---

## Deployment Pipeline

Execute steps 1–7 in strict order. If ANY step fails, report the error clearly and **STOP**. Do not continue, do not attempt workarounds, do not auto-rollback.

### Step 1: Pre-flight Checks

All three checks must pass. If ANY fails, **refuse to deploy** with a clear explanation.

**1a. Uncommitted changes:**
```bash
git status --porcelain
```
If output is non-empty → **REFUSE:** "There are uncommitted changes. Commit or stash them before deploying." List the dirty files.

**1b. Tests must pass:**
```bash
.venv/bin/pytest tests/ -v
```
If any test fails → **REFUSE:** "Tests are failing. Fix them before deploying." Show the failure output.

**1c. Branch check:**
```bash
git branch --show-current
```

- If on **any branch other than `master`** → proceed to Step 2.
- If **already on `master`** → present exactly these options and wait for a response:

> You're already on `master`. What would you like to do?
> **(a)** Deploy master as-is
> **(b)** Abort — switch to a feature branch first
> **(c)** Something else — please describe

If (a) → skip Step 2, proceed to Step 3.
If (b) → stop the pipeline entirely.
If (c) → follow the user's instructions.

### Step 2: Merge to Master

Only runs if the current branch is not `master`.

```bash
CURRENT_BRANCH=$(git branch --show-current)
git checkout master
git merge --no-edit "$CURRENT_BRANCH"
```

If merge conflicts occur → **STOP:** "Merge conflicts detected between `{branch}` and `master`. Resolve them manually, then run /deploy again."

On success, report: "Merged `{branch}` into `master`."

### Step 3: Tag the Deploy Commit

Tag the exact commit that is about to be deployed. The tag uses the same name format as the backup directory, but the two timestamps differ (tag = local time, backup = server UTC).

```bash
DEPLOY_TAG="deploy-$(date +%Y%m%d-%H%M%S)"
git tag "$DEPLOY_TAG"
```

Report: "Tagged as `{tag}`."

This tag marks the exact commit deployed to production. /deploy can only deploy `master` HEAD; it cannot re-deploy an older tag. For a rollback, use the manual procedure under **On Failure**.

### Step 4: Push to Remote

Push the merged `master` branch and the deploy tag to the remote repository so the git history is preserved remotely.

```bash
git push origin master
git push origin "$DEPLOY_TAG"
```

If push fails → **STOP:** "Failed to push to remote. Check your network connection and remote access, then run /deploy again."

On success, report: "Pushed `master` and tag `{tag}` to origin."

### Step 5: Full Server Backup

SSH to the server and create a timestamped backup directory containing all critical data. Compute the timestamp on the remote server.

```bash
ssh -p 2222 deploy@178.104.76.254 'bash -s' <<'BACKUP_SCRIPT'
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/home/deploy/backups/deploy-$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "Creating backup at $BACKUP_DIR ..."

# 1. Application code (full archive of current server state, excluding .git)
echo "  Backing up code..."
tar -czf "$BACKUP_DIR/code.tar.gz" --exclude='.git' -C /home/deploy sentinel/

# 2. Live config (requires sudo — root:sentinel 640)
echo "  Backing up config..."
sudo cp /etc/sentinel/config.yaml "$BACKUP_DIR/config.yaml"

# 3. Database (hot backup — safe while service is running)
echo "  Backing up database..."
sqlite3 /var/lib/sentinel/sentinel.db ".backup '$BACKUP_DIR/sentinel.db'"

# 3b. OpenAI cost ledger (hot backup; requires sudo — sentinel:sentinel 600)
echo "  Backing up cost ledger..."
sudo sqlite3 /var/lib/sentinel/model-usage.db ".backup '$BACKUP_DIR/model-usage.db'"

# 4. Telegram session (requires sudo — sentinel:sentinel 600)
echo "  Backing up Telegram session..."
sudo cp /var/lib/sentinel/sentinel_session.session "$BACKUP_DIR/sentinel_session.session" 2>/dev/null \
  || echo "  (no Telegram session file found — skipping)"

echo ""
echo "Backup complete: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
BACKUP_SCRIPT
```

If SSH connection fails → **STOP:** "Cannot connect to production server. Verify SSH access: `ssh -p 2222 deploy@178.104.76.254`"

If any backup step fails → **STOP:** "Backup failed — deployment aborted to protect production data." Show the error output.

On success, report the backup location and its contents.

### Step 6: Deploy Code

**6a. Config drift check** (runs before anything on the server changes):

Compare, key by key, the live config with the repo config of the previous deploy (the commit the
server is on now) and of the new tag. A key where live differs from the new repo config is
**expected** when it was changed in the repo since the last deploy (live == previous repo config,
previous != new); anything else is **unexpected**: a server-only edit that the config sync (6c)
would silently overwrite. On 2026-09-25 exactly such an edit (`ledger_path`) stopped the service
for ~10 minutes.

```bash
ssh -p 2222 deploy@178.104.76.254 'bash -s' -- "$DEPLOY_TAG" <<'DRIFT_CHECK'
set -uo pipefail
umask 077
cd /home/deploy/sentinel
git fetch --tags origin || { echo "FETCH_FAILED"; exit 2; }
LIVE=$(mktemp); PREV=$(mktemp); NEW=$(mktemp)
trap 'rm -f "$LIVE" "$PREV" "$NEW"' EXIT
sudo cat /etc/sentinel/config.yaml > "$LIVE"
git show "$(git rev-parse HEAD):config/config.yaml" > "$PREV"
git show "$1:config/config.yaml" > "$NEW"
.venv/bin/python - "$LIVE" "$PREV" "$NEW" <<'PY'
import re
import sys

import yaml

live, prev, new = (yaml.safe_load(open(path, encoding="utf-8")) for path in sys.argv[1:4])
SECRET = re.compile(r"token|key|secret|password|sid|auth", re.I)
MISSING = "<missing>"


def leaves(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, (*path, str(key)))
    else:
        yield path


def get(node, path):
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


expected, unexpected = [], []
for path in sorted(set(leaves(live)) | set(leaves(new))):
    lv, pv, nv = get(live, path), get(prev, path), get(new, path)
    if lv == nv:
        continue
    name = ".".join(path)
    show = (lambda v: "***") if SECRET.search(name) else repr
    line = f"  {name}: live={show(lv)} -> repo={show(nv)}"
    (expected if lv == pv and pv != nv else unexpected).append(line)
print("EXPECTED (changed in the repo since the last deploy):")
print("\n".join(expected) or "  none")
print("UNEXPECTED (edited on the server only, would be LOST):")
print("\n".join(unexpected) or "  none")
sys.exit(3 if unexpected else 0)
PY
DRIFT_CHECK
```

Values are shown as `***` when the dotted key path contains `token`, `key`, `secret`, `password`, `sid` or `auth` anywhere. This masks more than secrets: all `monitoring.keywords.*` and `monitoring.exclude_keywords.*` lists and every `*max_tokens` / `*_tokens` value are masked too. For an UNEXPECTED masked key, read the live value from the Step 5 backup copy (`sudo cat /home/deploy/backups/deploy-<ts>/config.yaml`) before telling the user what to copy.

- Exit 0 → report the EXPECTED list and continue to 6b.
- `FETCH_FAILED` → **STOP:** "Failed to fetch from GitHub on the server. Check the deploy key and network access."
- Exit 3 (any UNEXPECTED key) → **STOP:** "The live config has server-only edits that this deploy would overwrite. Nothing on the server has changed yet. Copy these values into `config/config.yaml`, commit, and run /deploy again." Show both lists. Do NOT continue and do NOT copy the config.
- Any other failure (e.g. the script itself fails) → **STOP** and show the output; the server is unchanged.
- The script has no `set -e`, so two failures look like normal results. If `sudo cat` fails, every key shows as UNEXPECTED with exit 3: check that the live values are not all `<missing>` before blaming server edits. If a `git show` fails, the check can pass with exit 0 and repo values of `<missing>`: if any EXPECTED line shows `repo='<missing>'` for many keys, **STOP**. This is a known gap in the script: it lacks explicit exit guards after `sudo cat` and `git show`.

**6b. Check out the tag** (server switches to the exact tagged commit fetched in 6a):

```bash
ssh -p 2222 deploy@178.104.76.254 "cd /home/deploy/sentinel && git checkout $DEPLOY_TAG"
```

This puts the server on the exact tagged commit (detached HEAD — expected for production). Tracked files are updated to match the tag; untracked server files (`.venv/`, `data/`, `logs/`, etc.) are preserved because they're in `.gitignore`.

If `git checkout` fails (e.g., uncommitted changes on the server) → **STOP:** "Server working tree has local modifications. Investigate before deploying." Show the error output. Do NOT run `git checkout --force` — local server edits may be intentional emergency patches.

**6c. Sync config to live path:**

```bash
ssh -p 2222 deploy@178.104.76.254 'sudo cp /home/deploy/sentinel/config/config.yaml /etc/sentinel/config.yaml && sudo chown root:sentinel /etc/sentinel/config.yaml && sudo chmod 640 /etc/sentinel/config.yaml'
```

This copies the repo config (which git just updated) to the live path the service reads. The drift check in 6a has confirmed that it only changes what the repo intends, and the backup in Step 5 preserved the previous live config. Permissions are restored to `root:sentinel 640` to match the expected ownership.

If the copy fails → **STOP.** Report the error. The service is still running with the old config; no damage done.

**6d. Install Python dependencies** (into the existing venv, every deploy; the venv is never recreated, and packages removed from `requirements.txt` stay installed):

```bash
ssh -p 2222 deploy@178.104.76.254 'cd /home/deploy/sentinel && .venv/bin/pip install -r requirements.txt'
```

If pip install fails → **STOP.** Report the error and remind the user that a backup exists. Warn that the server is now half-deployed: the new code (6b) and new config (6c) are on disk, while the old process still runs from memory. The unit has `Restart=always`, so any crash or restart loads the new code and config, possibly without the new dependencies. To restore, follow the manual rollback under **On Failure**.

**6e. Restart the service:**

```bash
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl restart sentinel'
```

If restart fails → **STOP.** Report the error.

**6f. Prune old deploy snapshots (keep last 10):**

```bash
ssh -p 2222 deploy@178.104.76.254 'ls -1dt /home/deploy/backups/deploy-* | tail -n +11 | xargs rm -rf && echo "Kept $(ls -1d /home/deploy/backups/deploy-* | wc -l) snapshots, $(du -sh /home/deploy/backups/ | cut -f1) total"'
```

This deletes all but the 10 most recent deploy snapshots. Non-critical — if it fails, log a warning and continue.

### Step 7: Verify Deployment

Run ALL verification checks. Collect results, then report them together.

**7a. Service status:**
```bash
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl status sentinel --no-pager'
```
Check that the service is `active (running)`. If not → **ALERT.**

**7b. Immediate error scan** (first 15 seconds of logs after restart):
```bash
sleep 15
ssh -p 2222 deploy@178.104.76.254 'sudo journalctl -u sentinel --since "30 seconds ago" --no-pager'
```
Scan for `ERROR`, `Exception`, `Traceback`, `CRITICAL`. If found → **ALERT** and show the relevant lines.

Known pre-existing log lines (not deploy failures; report them, but do not raise ALERT for them):
- `Failed to fetch RSS source Rzeczpospolita` with HTTP 403. The feed blocks the VPS; it appears whenever that source is fetched, including the startup cycle.
- `Twilio call failed` / `Twilio SMS failed` with HTTP 401 and `is not active`. The owner keeps the Twilio account unfunded on purpose since 2026-09-21; calls and SMS return when the owner recharges it.

For any other ERROR, compare it with the journal from before the restart (`sudo journalctl -u sentinel --until "<restart time>" -n 200 --no-pager`). Raise ALERT only if the error is new.

**7c. Health check:**
```bash
ssh -p 2222 deploy@178.104.76.254 'cat /var/lib/sentinel/health.json 2>/dev/null || echo "health.json not yet available"'
```
The startup cycle does not write health.json; the first scheduled fast-lane cycle does, about `scheduler.fast_interval_minutes` (plus up to 10 s jitter) after the restart. Compare `last_cycle_at` with the restart time. If it is older, report "pre-restart snapshot; first post-restart write expected about 3 minutes after restart". Optionally re-check after 3–4 minutes.

**7d. Extended log check** (wait for first pipeline cycle):
```bash
sleep 30
ssh -p 2222 deploy@178.104.76.254 'sudo journalctl -u sentinel --since "1 minute ago" --no-pager | tail -30'
```
Look for signs of normal operation (successful fetch, classify, or scheduling messages). If only errors → **ALERT.**

---

## Completion Report

After all steps succeed, output this summary:

```
## Deployment Complete

- Branch merged: {branch} → master (or "master deployed as-is")
- Git tag: {deploy-YYYYMMDD-HHMMSS}
- Pushed to remote: master + {tag}
- Backup location: /home/deploy/backups/deploy-{timestamp}/
- Backup contents: code.tar.gz, config.yaml, sentinel.db, model-usage.db, sentinel_session.session
- Config drift check: no server-only edits; expected changes: {list or "none"}
- Git checkout: {DEPLOY_TAG} on server
- Config synced: config/config.yaml → /etc/sentinel/config.yaml
- pip install: {success/no changes}
- Service status: active (running)
- Health: {health.json contents, or "pre-restart snapshot; awaiting first scheduled cycle"}
- Log errors: none (or list them; name known pre-existing lines separately)
```

## On Failure (at any verification step)

1. Report **exactly what failed** with the full command output
2. State the backup location: "A pre-deployment backup exists at `/home/deploy/backups/deploy-{timestamp}/`"
3. **STOP** — do not attempt automatic rollback
4. Suggest the manual rollback below. /deploy itself deploys only `master` HEAD, so it cannot roll back.

Manual rollback (run only when the user asks; the user lists tags with `git tag -l 'deploy-*'`):
1. On the server: `cd /home/deploy/sentinel && git fetch --tags origin && git checkout <previous-deploy-tag>`.
2. Restore the matching config: `sudo cp /home/deploy/backups/deploy-<ts>/config.yaml /etc/sentinel/config.yaml && sudo chown root:sentinel /etc/sentinel/config.yaml && sudo chmod 640 /etc/sentinel/config.yaml`. The snapshot `<ts>` is server UTC time (Step 5) and does not equal the tag's local-time name. Pick the first snapshot taken after `<previous-deploy-tag>` was deployed (`ls -1d /home/deploy/backups/deploy-*`). Do not use the snapshot made during that previous deploy itself: it holds the older config that deploy replaced; use the next one in the list. Confirm it with `diff <(git show <previous-deploy-tag>:config/config.yaml) <(sudo cat /home/deploy/backups/deploy-<ts>/config.yaml)`.
3. Keep the live `sentinel.db` and `model-usage.db`. Restore a database from the backup only if it is damaged.
4. `sudo systemctl restart sentinel`, then run the Step 7 checks.

---

## Critical Safety Rules

1. **Always `deploy@`** — never `root@` or `kossa@` for SSH. A wrong username triggers a fail2ban ban.
2. **Never touch `/etc/sentinel/sentinel.env` or `/etc/sentinel/openai.env`** — never read, print, back up or deploy them.
3. **This skill overrides the no-server-modification CLAUDE.md rule** — /deploy is blanket authorization. No confirmation prompts between steps.
4. **On failure: STOP** — do not retry, do not work around, do not auto-rollback. Report and stop.
5. **Stay on `master`** — after deployment completes (or fails after merge), leave the local repo on the `master` branch.
