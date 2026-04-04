---
name: deploy
description: >-
  Deploy Project Sentinel to production. Runs pre-flight checks (uncommitted changes,
  failing tests, unmerged branch), merges current branch to master, tags the deploy commit,
  pushes master and tag to remote, creates a full server backup (code, config, database,
  Telegram session), pulls the tagged commit from GitHub on the server, rebuilds the venv
  if needed, restarts the service, and verifies everything is running. Only invoke when
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
| `/home/deploy/sentinel/` | Application code (git clone) | deploy:deploy | Deployed via git pull from GitHub |
| `/home/deploy/sentinel/venv/` | Python venv (server-side) | deploy:deploy | Rebuilt on server after deploy |
| `/etc/sentinel/config.yaml` | Live config | root:sentinel 640 | Needs sudo to read |
| `/etc/sentinel/sentinel.env` | API keys and secrets | root:deploy 640 | NEVER touch — not backed up, not deployed |
| `/var/lib/sentinel/sentinel.db` | SQLite database | sentinel:sentinel | Hot-backup via sqlite3 .backup |
| `/var/lib/sentinel/sentinel_session.session` | Telegram auth session | sentinel:sentinel 600 | Needs sudo to read |
| `/var/lib/sentinel/health.json` | Health status | sentinel:sentinel | Updated every pipeline cycle |
| `/home/deploy/backups/` | Backup storage | deploy:deploy | Deploy backups stored here |
</server_file_layout>

---

## Prerequisites (One-Time Setup)

The server must have a git clone of the repository at `/home/deploy/sentinel/` with a GitHub deploy key configured for SSH access. See `docs/migration-git-deploy.md` for the full step-by-step migration guide. In short:

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

Tag the exact commit that is about to be deployed. Use the same timestamp format as the backup so they match.

```bash
DEPLOY_TAG="deploy-$(date +%Y%m%d-%H%M%S)"
git tag "$DEPLOY_TAG"
```

Report: "Tagged as `{tag}`."

This tag marks the exact commit deployed to production. To rollback later: `git checkout {tag}` and re-deploy.

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

**6a. Pull code from GitHub** (server fetches the exact tagged commit directly from the remote):

```bash
ssh -p 2222 deploy@178.104.76.254 "cd /home/deploy/sentinel && git fetch --tags origin && git checkout $DEPLOY_TAG"
```

This puts the server on the exact tagged commit (detached HEAD — expected for production). Tracked files are updated to match the tag; untracked server files (`venv/`, `data/`, `logs/`, etc.) are preserved because they're in `.gitignore`.

If `git fetch` fails → **STOP:** "Failed to fetch from GitHub on the server. Check the deploy key and network access."

If `git checkout` fails (e.g., uncommitted changes on the server) → **STOP:** "Server working tree has local modifications. Investigate before deploying." Show the error output. Do NOT run `git checkout --force` — local server edits may be intentional emergency patches.

**6b. Rebuild Python dependencies:**

```bash
ssh -p 2222 deploy@178.104.76.254 'cd /home/deploy/sentinel && venv/bin/pip install -r requirements.txt'
```

If pip install fails → **STOP.** Report the error and remind the user that a backup exists.

**6c. Restart the service:**

```bash
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl restart sentinel'
```

If restart fails → **STOP.** Report the error.

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

**7c. Health check:**
```bash
ssh -p 2222 deploy@178.104.76.254 'cat /var/lib/sentinel/health.json 2>/dev/null || echo "health.json not yet available"'
```
Report the health status. Note: health.json may take up to 3 minutes to refresh (first fast-lane cycle after restart).

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
- Backup contents: code.tar.gz, config.yaml, sentinel.db, sentinel_session.session
- Git checkout: {DEPLOY_TAG} on server
- pip install: {success/no changes}
- Service status: active (running)
- Health: {health.json contents or "awaiting first cycle"}
- Log errors: none (or list them)
```

## On Failure (at any verification step)

1. Report **exactly what failed** with the full command output
2. State the backup location: "A pre-deployment backup exists at `/home/deploy/backups/deploy-{timestamp}/`"
3. **STOP** — do not attempt automatic rollback
4. Suggest: "To rollback: restore the backup on the server and restart the service, or re-deploy a previous git tag (`git tag -l 'deploy-*'` to list)."

---

## Critical Safety Rules

1. **Always `deploy@`** — never `root@` or `kossa@` for SSH. A wrong username triggers a fail2ban ban.
2. **Never touch `/etc/sentinel/sentinel.env`** — not in backups, not in deploys, not ever.
3. **This skill overrides the no-server-modification CLAUDE.md rule** — /deploy is blanket authorization. No confirmation prompts between steps.
4. **On failure: STOP** — do not retry, do not work around, do not auto-rollback. Report and stop.
5. **Stay on `master`** — after deployment completes (or fails after merge), leave the local repo on the `master` branch.
