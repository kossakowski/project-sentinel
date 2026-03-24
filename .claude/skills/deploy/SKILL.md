---
name: deploy
description: >-
  Deploy Project Sentinel to production. Runs pre-flight checks (uncommitted changes,
  failing tests, unmerged branch), merges current branch to master, tags the deploy commit,
  creates a full server backup (code, config, database, Telegram session), deploys code
  via rsync, rebuilds the venv if needed, restarts the service, and verifies everything
  is running. Only invoke when the user explicitly calls /deploy. Do NOT auto-trigger.
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
| `/home/deploy/sentinel/` | Application code | deploy:deploy | Deployed via rsync |
| `/home/deploy/sentinel/venv/` | Python venv (server-side) | deploy:deploy | Rebuilt on server after deploy |
| `/etc/sentinel/config.yaml` | Live config | root:sentinel 640 | Needs sudo to read |
| `/etc/sentinel/sentinel.env` | API keys and secrets | root:deploy 640 | NEVER touch — not backed up, not deployed |
| `/var/lib/sentinel/sentinel.db` | SQLite database | sentinel:sentinel | Hot-backup via sqlite3 .backup |
| `/var/lib/sentinel/sentinel_session.session` | Telegram auth session | sentinel:sentinel 600 | Needs sudo to read |
| `/var/lib/sentinel/health.json` | Health status | sentinel:sentinel | Updated every pipeline cycle |
| `/home/deploy/backups/` | Backup storage | deploy:deploy | Deploy backups stored here |
</server_file_layout>

---

## Deployment Pipeline

Execute steps 1–6 in strict order. If ANY step fails, report the error clearly and **STOP**. Do not continue, do not attempt workarounds, do not auto-rollback.

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

### Step 4: Full Server Backup

SSH to the server and create a timestamped backup directory containing all critical data. Compute the timestamp on the remote server.

```bash
ssh -p 2222 deploy@178.104.76.254 'bash -s' <<'BACKUP_SCRIPT'
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/home/deploy/backups/deploy-$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "Creating backup at $BACKUP_DIR ..."

# 1. Application code (full archive of current server state)
echo "  Backing up code..."
tar -czf "$BACKUP_DIR/code.tar.gz" -C /home/deploy sentinel/

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

### Step 5: Deploy Code

**5a. Sync code via rsync** (transfers only changed files, excludes build artifacts and local state):

```bash
rsync -avz --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.coverage' \
  --exclude '.pytest_cache' \
  --exclude '.code-refiner-state' \
  --exclude '.claude' \
  --exclude 'data' \
  --exclude '.env' \
  --exclude 'sentinel_session.session' \
  --exclude 'logs' \
  -e 'ssh -p 2222' \
  /home/kossa/code/project-sentinel/ \
  deploy@178.104.76.254:/home/deploy/sentinel/
```

The `--delete` flag removes files on the server that no longer exist locally (excluding the patterns above, which are preserved on the server). This ensures the server code exactly mirrors the `master` branch.

If rsync fails → **STOP.** Report the error.

**5b. Rebuild Python dependencies:**

```bash
ssh -p 2222 deploy@178.104.76.254 'cd /home/deploy/sentinel && venv/bin/pip install -r requirements.txt'
```

If pip install fails → **STOP.** Report the error and remind the user that a backup exists.

**5c. Restart the service:**

```bash
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl restart sentinel'
```

If restart fails → **STOP.** Report the error.

### Step 6: Verify Deployment

Run ALL verification checks. Collect results, then report them together.

**6a. Service status:**
```bash
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl status sentinel --no-pager'
```
Check that the service is `active (running)`. If not → **ALERT.**

**6b. Immediate error scan** (first 15 seconds of logs after restart):
```bash
sleep 15
ssh -p 2222 deploy@178.104.76.254 'sudo journalctl -u sentinel --since "30 seconds ago" --no-pager'
```
Scan for `ERROR`, `Exception`, `Traceback`, `CRITICAL`. If found → **ALERT** and show the relevant lines.

**6c. Health check:**
```bash
ssh -p 2222 deploy@178.104.76.254 'cat /var/lib/sentinel/health.json 2>/dev/null || echo "health.json not yet available"'
```
Report the health status. Note: health.json may take up to 3 minutes to refresh (first fast-lane cycle after restart).

**6d. Extended log check** (wait for first pipeline cycle):
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
- Backup location: /home/deploy/backups/deploy-{timestamp}/
- Backup contents: code.tar.gz, config.yaml, sentinel.db, sentinel_session.session
- rsync: {N} files transferred, {size} total
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
