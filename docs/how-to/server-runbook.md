# Server Runbook — Project Sentinel

Last verified: 2026-10-03 (deployed commit 6429124)

> **Owner:** Łukasz (kossakowski87@gmail.com)

## Contents

- [Prerequisites](#prerequisites)
- [Current deployment](#current-deployment)
- [Server Facts](#server-facts) · [SSH Access](#ssh-access) · [File Layout](#file-layout)
- [Service Management](#service-management) · [Logs](#logs) · [Log Rotation](#log-rotation)
- [Deployment](#deployment) · [Rollback](#rollback)
- [Configuration](#configuration) · [Secrets](#secrets)
- [Database Operations](#database-operations) · [Health Check](#health-check) · [Scheduled Cron Jobs](#scheduled-cron-jobs)
- [Pipeline Schedule](#pipeline-schedule)
- [Troubleshooting](#troubleshooting) — starts with undeliverable urgency 9–10 alerts
- [Known Server Hazards](#known-server-hazards) · [Security Stack](#security-stack) · [Known Issues](#known-issues)

Every command below is labeled **read-only** (safe to run at any time) or **state-changing**
(changes the server; needs the owner's explicit approval, except inside `/deploy`).

## Prerequisites

Before running anything in this runbook:

- **SSH only as `deploy@178.104.76.254` on port 2222.** `ssh -p 2222 deploy@178.104.76.254`. Never use `root@` or `kossa@`: a wrong username counts as a failed login. 3 failed logins within 10 minutes ban the source IP for 24 hours, and repeat bans double up to 7 days. The home IP in `ignoreip` is never banned. Port 22 is firewalled.
- **Read-only by default.** Do **not** modify files on the production server unless the owner explicitly authorises it. Log, health and DB inspection commands are safe. Anything that writes (deploy, config edits, session re-auth, restarts) needs a deliberate decision.
- **Required env vars (loaded by systemd):** see [Secrets](#secrets) for the full list and which file holds each one.

## Current deployment

- Production runs tag `deploy-20260925-143105`, code commit `6429124`. The server checkout sits in detached HEAD on that tag, which is the intended state.
- Check it (read-only): `ssh -p 2222 deploy@178.104.76.254 'git -C /home/deploy/sentinel describe --tags'` → expected `deploy-20260925-143105`.
- The repo `master` may be ahead of production. Never call something live only because it is on `master`.
- The live classifier is OpenAI `gpt-5.6-luna` (`sentinel/classification/openai_provider.py`), with incident memory, the persistent model-budget ledger and the Polish-summary guard. Claude Haiku is kept only as a rollback path.
- The [Luna deployment record](../reference/luna-deployment-20260920.md) documents the 2026-09-20 migration to Luna. It is a historical record, not the current deployment. Its hand-merge of classification fields was a one-off for that rollout.
- Routine deploys use `/deploy` (see [Deployment](#deployment)). It copies the tracked `config/config.yaml` to the server and never touches the secrets files.

## Server Facts

| Field | Value |
|---|---|
| Provider | Hetzner Cloud, Nuremberg |
| Spec | CX23 — 2 vCPU, 4 GB RAM |
| OS | Ubuntu 24.04 LTS |
| IP | `178.104.76.254` |
| SSH port | `2222` (port 22 firewalled) |
| SSH auth | Key only, password disabled |
| Admin user | `deploy` (passwordless sudo, SSH key login) |
| Service user | `sentinel` (no shell, no sudo, runs app via systemd) |
| Whitelisted IP | `79.184.239.122` (kossa home) |

## SSH Access

```bash
ssh -p 2222 deploy@178.104.76.254        # read-only by itself
```

**Always use `deploy@`.** Using `root@` or `kossa@` counts as a failed attempt. 3 failures in 10 minutes ban the IP for 24 hours (repeat bans double, up to 7 days).

Emergency (SSH blocked): Hetzner Cloud web console → server → Console tab → login as `root`. Type `exit` to log out of the console when done; never leave a root console session open.

## File Layout

```
/home/deploy/sentinel/               # App code (git clone of github:kossakowski/project-sentinel), detached HEAD on a deploy-* tag
├── sentinel.py                      # Entry point
├── sentinel/                        # Python package
├── .venv/                           # Python virtual environment (the only venv; the legacy venv/ is gone)
├── deploy/                          # Deploy scripts and systemd unit
├── tests/                           # Test suite
└── requirements.txt

/etc/sentinel/                       # Secrets and config (root:sentinel 750)
├── config.yaml                      # Live config, a copy of the repo's config/config.yaml (root:sentinel 640)
├── sentinel.env                     # Twilio, Telegram, Expo push and legacy Anthropic credentials (root:deploy 640)
├── openai.env                       # OPENAI_API_KEY only (root:root 600)
└── *.bak*                           # Root-only copies of earlier config and env files (contain secrets; root:root 640)

/etc/systemd/system/sentinel.service.d/20-openai.conf   # Drop-in that loads openai.env (server-only, see Secrets)

/var/lib/sentinel/                   # Runtime state (sentinel:sentinel 750)
├── sentinel.db                      # SQLite DB (articles, events, alerts, pending classification queue)
├── model-usage.db                   # Persistent OpenAI reservations/accounting (sentinel:sentinel 600)
├── sentinel_session.session         # Telegram auth session (sentinel:sentinel 600)
└── health.json                      # Written after each scheduled cycle (not the startup cycle)

/var/log/sentinel/                   # App logs (sentinel:sentinel 750)
└── sentinel.log                     # Two rotation mechanisms coexist (see Log Rotation below)

/home/deploy/backups/
├── sentinel_YYYYMMDD.db             # Daily SQLite backups (7-day retention, backup-db.sh)
├── deploy-YYYYMMDD-HHMMSS/          # /deploy snapshots (code, config, DB, cost ledger, Telegram session; snapshots older than the October 2026 skill change lack the ledger); 10 newest kept
└── config-*.yaml                    # Ad-hoc root-only config copies

/home/deploy/check-health.sh         # Cron health check script (see Health Check: its SMS path is inert)
/home/deploy/backup-db.sh            # Cron backup script
```

## Service Management

```bash
sudo systemctl status sentinel --no-pager   # read-only
sudo systemctl is-active sentinel           # read-only
sudo systemctl start sentinel               # state-changing
sudo systemctl stop sentinel                # state-changing — stops monitoring
sudo systemctl restart sentinel             # state-changing
```

## Logs

All commands in this section are read-only.

```bash
sudo journalctl -u sentinel -f                          # live tail (service stdout)
sudo journalctl -u sentinel --since "1 hour ago"
sudo tail -100 /var/log/sentinel/sentinel.log
```

Log lines have the format `<timestamp> [LEVEL] <logger>: <message>`. Useful signals in `sentinel.log`:

| Signal | Logger and message | Grep (read-only) |
|---|---|---|
| Cycle heartbeat | `sentinel.pipeline: === Pipeline cycle starting [FAST] ===` / `[FULL]`, then `=== Cycle complete in Ns: fetched=… classified=… alerts=… ===` | `sudo grep 'Cycle complete' /var/log/sentinel/sentinel.log \| tail -5` |
| LLM call and cost | `sentinel.openai: OpenAI classification: input=… cached=… output=… estimated_usd=… month_usd=…` | `sudo grep 'month_usd' /var/log/sentinel/sentinel.log \| tail -5` |
| Alert decision | `sentinel.alerts.state_machine: Event …: urgency=N, sources=N, action=…` | `sudo grep 'action=' /var/log/sentinel/sentinel.log \| tail -20` |
| Push delivered | `sentinel.alerts.push_client: Push sent for event … ticket=…` | `sudo grep 'Push sent' /var/log/sentinel/sentinel.log \| tail -5` |
| Twilio failure | `sentinel.alerts.twilio_client: Twilio call failed …` / `Twilio SMS failed …` | `sudo grep 'twilio_client' /var/log/sentinel/sentinel.log \| tail -5` |
| Source down | `sentinel.fetcher.rss: Failed to fetch RSS source X: …` | `sudo grep 'Failed to fetch' /var/log/sentinel/sentinel.log \| tail -10` |
| Telegram up | `sentinel.fetcher.telegram: Telegram fetcher started, monitoring N channels` | `sudo grep 'Telegram fetcher started' /var/log/sentinel/sentinel.log \| tail -2` |

## Log Rotation

Two independent rotation mechanisms apply to `sentinel.log` — both are real and both run:

| Mechanism | Trigger | Config | Behaviour |
|---|---|---|---|
| App-side `RotatingFileHandler` | **Size-based** | `logging.max_size_mb`, `logging.backup_count` in `config/config.yaml` | Rotates when the file reaches the size limit and keeps that many backups |
| OS `logrotate` | **Time-based** | `deploy/configs/sentinel-logrotate` (`daily`, `rotate 14`, `compress`, `copytruncate`) | Rotates once daily, keeps 14 compressed days |

`copytruncate` in the logrotate config lets the OS rotate the file without the process needing to reopen its handle, so the two mechanisms coexist without fighting over the file.

## Deployment

Remote: `git@github.com:kossakowski/project-sentinel.git` (SSH deploy key at `/home/deploy/.ssh/github_deploy`).

**Standard deploy: run `/deploy` from the local repo.** The owner deploys from `master`. The skill
(`.claude/skills/deploy/SKILL.md`) is the source of truth; its steps are:

| Step | What it does |
|---|---|
| 1 | Pre-flight: no uncommitted changes, tests pass, branch check |
| 2 | Merge the current branch to `master` (skipped when deploying `master` as-is) |
| 3 | Tag the deploy commit `deploy-YYYYMMDD-HHMMSS` |
| 4 | Push `master` and the tag to GitHub |
| 5 | Full server backup to `/home/deploy/backups/deploy-<ts>/` |
| 6a | Config drift check: compares the live config key by key with the repo config of the previous deploy and of the new tag. It stops the deploy, before anything on the server changes, when the live config has server-only edits that the sync would overwrite |
| 6b | Check out the tag on the server (detached HEAD — expected for production) |
| 6c | Copy `config/config.yaml` to `/etc/sentinel/config.yaml` (`root:sentinel 640`) |
| 6d | `pip install -r requirements.txt` into the existing `.venv/` |
| 6e | Restart the service |
| 6f | Prune deploy snapshots, keeping the 10 newest |
| 7 | Verify: service status, error scan, `health.json`, extended log check |

If step 6a stops the deploy: copy the reported server-only values into `config/config.yaml`,
commit, and run `/deploy` again. Do not hand-edit the server to "fix" the drift.

**Emergency manual deploy (only when `/deploy` cannot run, with owner approval; all state-changing):**

1. Push the commit and a `deploy-YYYYMMDD-HHMMSS` tag from the local repo: `git tag <tag> && git push origin master <tag>`.
2. SSH in and take a backup:
   `TS=$(date +%Y%m%d-%H%M%S); B=/home/deploy/backups/deploy-$TS; mkdir -p $B && sudo cp /etc/sentinel/config.yaml $B/ && sudo sqlite3 /var/lib/sentinel/sentinel.db ".backup '$B/sentinel.db'" && sudo sqlite3 /var/lib/sentinel/model-usage.db ".backup '$B/model-usage.db'" && ls -l $B`
3. Check for server-only config edits (read-only; run it before the checkout): `sudo diff /etc/sentinel/config.yaml /home/deploy/sentinel/config/config.yaml` → expected: no output. If it prints differences, stop. Copy those values into the repo `config/config.yaml`, commit, and start again from step 1. This is the manual form of `/deploy` step 6a; skipping it can overwrite a server-only value and stop the service.
4. Check out the tag (never `master`): `cd /home/deploy/sentinel && git fetch --tags origin && git checkout <tag>`.
5. Sync the config: `sudo cp config/config.yaml /etc/sentinel/config.yaml && sudo chown root:sentinel /etc/sentinel/config.yaml && sudo chmod 640 /etc/sentinel/config.yaml`.
6. Only if `requirements.txt` changed: `.venv/bin/pip install -r requirements.txt`.
7. Restart: `sudo systemctl restart sentinel`.
8. Verify (read-only): `git describe --tags` → `<tag>`; `sudo systemctl is-active sentinel` → `active`; `sudo journalctl -u sentinel --since "1 minute ago" --no-pager` shows no `Traceback`.

**Deploy key setup** (one-time, already done — documented for reference):
- Key at `/home/deploy/.ssh/github_deploy` (ed25519)
- SSH config: `/home/deploy/.ssh/config` routes `github.com` to that key
- Public key registered as read-only deploy key at `github.com/kossakowski/project-sentinel/settings/keys`
- Test (read-only): `ssh -T git@github.com` → should greet `kossakowski/project-sentinel`

## Rollback

Each deploy replaces `/etc/sentinel/config.yaml`, so old code must go back together with its
matching config. Old code with a newer config can fail at startup. All steps are state-changing
and need owner approval.

1. List deploy tags locally or on the server: `git tag -l 'deploy-*'`. Pick the last good tag. Its live config is in the snapshot `/home/deploy/backups/deploy-<ts>/` that the *next* deploy took before replacing it. The snapshot name does not equal the tag name: the tag is stamped in local time on the machine that ran `/deploy`, and the snapshot in server UTC time during Step 5. Pick the snapshot by order instead (`ls -1d /home/deploy/backups/deploy-*`; UTC names sort by time): it is the first snapshot taken after the last-good tag was deployed. Do not use the snapshot made during the last-good deploy itself: it is only seconds newer than that tag, but it holds the older config that the last-good deploy replaced. Use the next one in the list. Confirm it before restoring, for example `diff <(git show <last-good-tag>:config/config.yaml) <(sudo cat /home/deploy/backups/deploy-<ts>/config.yaml)` shows no unexpected differences.
2. Check out the tag: `cd /home/deploy/sentinel && git fetch --tags origin && git checkout <last-good-tag>`.
3. Restore the matching config: `sudo cp /home/deploy/backups/deploy-<ts>/config.yaml /etc/sentinel/config.yaml && sudo chown root:sentinel /etc/sentinel/config.yaml && sudo chmod 640 /etc/sentinel/config.yaml`.
4. Restart: `sudo systemctl restart sentinel`.
5. Verify (read-only): `git describe --tags` → `<last-good-tag>`; `sudo systemctl is-active sentinel` → `active`.

- **Keep the live `sentinel.db` and `model-usage.db`.** Restore a database from a backup only if it is damaged: an old `sentinel.db` loses newer alert records and can make old events alert again.
- After a rollback, the next `/deploy` step 6a compares against the rolled-back commit, so commit the intended config to `config/config.yaml` first.
- Rolling back from Luna to the Anthropic classifier needs extra steps (remove the `20-openai.conf` drop-in, `systemctl daemon-reload`). Follow the rollback plan in the [Luna deployment record](../reference/luna-deployment-20260920.md).

## Configuration

- The tracked `config/config.yaml` in the repo is the live config. `/deploy` step 6c copies it to `/etc/sentinel/config.yaml`, and the two files are byte-identical today.
- Keep three files apart: `config/config.yaml` (live values), `config/config.example.yaml` (template) and `sentinel/config.py` (code defaults).
- **To change production:** edit `config/config.yaml`, commit, and run `/deploy`. Do not hand-edit `/etc/sentinel/config.yaml`; `/deploy` step 6a would stop the next deploy on that drift.
- Read the live file (read-only): `sudo cat /etc/sentinel/config.yaml`.
- The live config differs from the template in more than the server paths (`database.path`, `logging.file`, `sources.telegram.session_name`, `classification.budget.ledger_path`). It also sets push routing, the call retry cap (`alerts.acknowledgment.max_call_retries`) and the model budget (`classification.budget.monthly_usd`). See the [config reference](../reference/config-reference.md) for every key.

**Alert delivery as configured today:**

- Push is on in production: `alerts.push.enabled: true`, and the device token comes from `EXPO_PUSH_TOKEN` in `sentinel.env`. Never put a literal token in the config: the repo is public.
- Urgency 5–8 (`alerts.urgency_levels.high` and `.medium`) use `channel: push`, so they are push-only by owner decision. No SMS is sent for them.
- Urgency 9–10 (`critical`) places a phone call with an SMS fallback, plus an additive push. The critical tier has `corroboration_required: 1`, so a single source can trigger a call.
- The Twilio account is currently unfunded by owner choice, so calls and SMS fail (see [Troubleshooting](#troubleshooting)). They stay configured and return when the owner recharges the account.
- The code default (`sentinel/config.py`) and the template both have push off; the template also uses `channel: both`. Only the live config turns push on.

## Secrets

Never print credential values in logs, docs or deployment output. Name secrets by key only.

| File | Keys | Owner / mode |
|---|---|---|
| `/etc/sentinel/sentinel.env` | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `ALERT_PHONE_NUMBER`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `EXPO_PUSH_TOKEN`, `EXPO_ACCESS_TOKEN`, `ANTHROPIC_API_KEY` (rollback only), `TWILIO_WHATSAPP_NUMBER` (present, unused) | `root:deploy 640` |
| `/etc/sentinel/openai.env` | `OPENAI_API_KEY` | `root:root 600` |

- `EXPO_PUSH_TOKEN` is substituted into `alerts.push.tokens`. `EXPO_ACCESS_TOKEN` is the Expo Enhanced Push Security token read by `sentinel/alerts/push_client.py`. Together they carry the only working channel for urgency 5–8.
- systemd loads both files before dropping to the `sentinel` user. The unit `deploy/configs/sentinel.service` loads `sentinel.env`. The drop-in `/etc/systemd/system/sentinel.service.d/20-openai.conf` adds `openai.env`.
- The drop-in exists only on the server; it is not in `deploy/configs/`. Its content is `[Service]` followed by `EnvironmentFile=/etc/sentinel/openai.env`. On a server rebuild, recreate it by hand and run `sudo systemctl daemon-reload`, or the service starts without `OPENAI_API_KEY`.
- `/deploy` never touches either secrets file.

Edit the OpenAI key only when authorised (state-changing):
```bash
sudo nano /etc/sentinel/openai.env
sudo systemctl restart sentinel
```

## Database Operations

```bash
# Row counts (read-only)
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*) FROM articles;"
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*) FROM events;"

# Recent articles (read-only)
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT * FROM articles ORDER BY fetched_at DESC LIMIT 10;"

# Recent events (read-only)
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT * FROM events ORDER BY first_seen_at DESC LIMIT 10;"

# Schema (read-only)
sudo sqlite3 /var/lib/sentinel/sentinel.db ".tables"
sudo sqlite3 /var/lib/sentinel/sentinel.db ".schema articles"

# Manual backup (state-changing: writes a new file, does not touch the live DB)
sudo sqlite3 /var/lib/sentinel/sentinel.db ".backup '/home/deploy/backups/sentinel_manual.db'"
```

Automated backup: cron runs `/home/deploy/backup-db.sh` at `03:00` daily. Keeps 7 days. Output: `/home/deploy/backups/sentinel_YYYYMMDD.db`.

## Health Check

```bash
sudo cat /var/lib/sentinel/health.json                          # read-only
sudo journalctl -t sentinel-health --since "2 hours ago"        # read-only: watchdog results
```

- `health.json` is written after each scheduled cycle, not after the startup cycle that runs right after a restart, so right after a restart it can still show the pre-restart state. Check `last_cycle_at` (fresh within a few minutes), `is_healthy`, `classification_status` (`degraded` must be false) and `fetcher_status` (`telegram` should be true).
- Cron runs `/home/deploy/check-health.sh` every 30 minutes and pipes its output to syslog with the tag `sentinel-health`. A healthy run logs `Project Sentinel healthy`. A missing or stale (> 30 min) `health.json` logs a warning.
- **There is no working out-of-band alert when the service stalls.** The script's SMS fallback is inert for two reasons:
  1. It points at the removed legacy venv (`PYTHON=/home/deploy/sentinel/venv/bin/python`), so it never tries to send. The repo copy `deploy/scripts/check-health.sh` has the same path.
  2. Even with that fixed, it would send by Twilio SMS, and the Twilio account is unfunded.
- A stalled service is therefore visible only in the syslog line above. The fix is a code change, tracked in `TODO.md` (health watchdog item).

## Scheduled Cron Jobs

View (read-only): `ssh -p 2222 deploy@178.104.76.254 'crontab -l'`

| Schedule | Script | Purpose |
|---|---|---|
| `*/30 * * * *` | `/home/deploy/check-health.sh 2>&1 \| logger -t sentinel-health` | Health file staleness check → syslog (SMS path inert, see Health Check) |
| `0 3 * * *` | `/home/deploy/backup-db.sh` | SQLite backup, 7-day retention |

## Pipeline Schedule

Intervals and jitter come from `scheduler.*` in `config/config.yaml`; see the [config reference](../reference/config-reference.md).

| Lane | Interval | Sources | Jitter |
|---|---|---|---|
| Fast | `scheduler.fast_interval_minutes` | Telegram channels, priority-1 RSS, Google News | `min(jitter_seconds, 10)` — capped at 10 s |
| Slow | `scheduler.interval_minutes` | All **enabled** sources (superset of fast) plus lower-priority RSS | `jitter_seconds` |

> Disabled sources (for example GDELT, `sources.gdelt.enabled: false`) are not instantiated, so they do not run in either lane. Source on/off state is listed in [sources.md](../reference/sources.md).

## Troubleshooting

### 1. An urgency 9–10 alert cannot be delivered (check first)

- **Impact:** the owner may miss a real attack alert. This is the most important symptom.
- **Known state today:** the Twilio account is unfunded by owner choice since 2026-09-21. Every Twilio call and SMS fails with HTTP 401 (`account … with status 4 is not active`). This is expected, not an outage. Calls and SMS stay configured and return when the owner recharges the account. Until then the additive push is the only delivery that reaches the phone.
- **What it looks like:**
  - The log shows `Twilio call failed for event … HTTP 401 …`, then `Event …: Twilio call failed to initiate`, and `Failed to check SMS confirmations: … 401`.
  - Urgency 9–10 events stay at `alert_status = retry_pending`. A new call round starts only when a later article joins the same event (no scheduled re-call; see TODO.md, "Unacknowledged calls are retried only when a new article joins the event").
  - Failed Twilio attempts write no `alert_records` row, so the database shows no call attempt. Check the log, not the DB.
- **Safe checks (read-only):**
  - `sudo grep -E 'twilio_client|Twilio call failed' /var/log/sentinel/sentinel.log | tail -10` → 401 lines mean the known state.
  - `sudo grep 'Push sent' /var/log/sentinel/sentinel.log | tail -5` → a recent `Push sent for event …` line means the push path works.
  - `sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT urgency_score, alert_status, COUNT(*) FROM events WHERE urgency_score >= 9 GROUP BY 1,2;"`
- **If push also fails** (`Expo push failed` or `no tickets accepted` in the log): check that `EXPO_PUSH_TOKEN` and `EXPO_ACCESS_TOKEN` exist in `sentinel.env` (key names only: `sudo sed 's/=.*//' /etc/sentinel/sentinel.env`). Then see [mobile push setup](mobile-push-setup.md).
- **Do not** "re-auth Twilio" or rotate Twilio credentials because of a 401: the credentials are fine, the account is unfunded. Recharging is the owner's decision.

### 2. Other symptoms

Checks are read-only unless marked. Fixes are state-changing and need owner approval.

| Symptom | Check | Fix |
|---|---|---|
| Service not running | `sudo journalctl -u sentinel --since "5 minutes ago" --no-pager` | Fix the logged error; `sudo systemctl start sentinel` |
| No alerts at all (not even push) | `health.json` freshness; `sudo grep 'action=' /var/log/sentinel/sentinel.log \| tail -20`; `sudo grep 'month_usd' /var/log/sentinel/sentinel.log \| tail -5` | Depends on cause: no `action=` lines means nothing scored high enough or classification is paused (next rows) |
| Classification paused / `health.json` degraded | Log line `Model budget reached: classification paused; articles remain pending`; `classification_status.degraded` is true | Raise `classification.budget.monthly_usd` in `config/config.yaml`, commit, `/deploy`. Do not delete the queue or `model-usage.db` |
| `OpenAI rejected the key` / `OpenAI access denied` | `sudo ls -l /etc/sentinel/openai.env` (`root:root 600`); `systemctl cat sentinel` shows the `20-openai.conf` drop-in | Replace the key in `openai.env` (see [Secrets](#secrets)); restart |
| `Classification failed … OpenAI request failed or timed out. Article remains pending` | Occasional provider timeout; `classification_status` pending/failed counts in `health.json` | Nothing; the article is retried. Do not delete the queue or ledger |
| `Polish summary unavailable: … Original danger and incident decision preserved.` | Warning from `sentinel.summary_language` | Expected degraded summary; the alert still goes out with `summary_language.fallback_pl` (see [config reference](../reference/config-reference.md)) |
| Permission denied on startup | Ownership: `/etc/sentinel` → `root:sentinel 750`; `config.yaml` → `root:sentinel 640`; `sentinel.env` → `root:deploy 640`; `openai.env` → `root:root 600`; `/var/lib/sentinel` → `sentinel:sentinel 750`; `model-usage.db` → `sentinel:sentinel 600` | `sudo chown` + `sudo chmod` to correct values |
| Telegram not connecting | `sudo grep 'Telegram fetcher started' /var/log/sentinel/sentinel.log \| tail -2` must appear after each restart; `fetcher_status.telegram` in `health.json` must be true | Re-authenticate session (see below) |
| Service restarted unexpectedly | `sudo journalctl --since "<time>" \| grep -E 'apt-daily-upgrade\|Stopping sentinel'` | Usually nothing: unattended-upgrades restarts services after library updates (seen about twice a week around 06:40 UTC) |
| DB too large | `df -h /var/lib/sentinel/`; check article count | `sudo journalctl --vacuum-size=100M`; prune old backups: `sudo find /home/deploy/backups -name "sentinel_*.db" -mtime +3 -delete` |
| Disk full | `df -h /` | Vacuum journald + old backups (see above) |
| SSH locked out | `ping 178.104.76.254` works but SSH refused = fail2ban ban | Hetzner web console → root login → `fail2ban-client set sshd unbanip YOUR_IP` → `exit` |
| SSH connection timed out | Port blocked or sshd down | Hetzner console → `ss -tlnp \| grep 2222`; `systemctl restart ssh.socket` |
| git fetch fails on server | `ssh -T git@github.com` from server | Re-add deploy key or re-check `/home/deploy/.ssh/config` |
| Server checkout is in detached HEAD | `git -C /home/deploy/sentinel describe --tags` | Nothing: detached HEAD on a `deploy-*` tag is expected. Never check out `master` on the server |

**Telegram session re-authentication (state-changing):**
```bash
ssh -p 2222 deploy@178.104.76.254
cd /home/deploy/sentinel && source .venv/bin/activate
set -a && source <(sudo cat /etc/sentinel/sentinel.env) && set +a
python -c "
import os, asyncio
from telethon import TelegramClient
c = TelegramClient('/tmp/tg_reauth', int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
asyncio.run(c.start())
print('Done')
"
sudo cp /tmp/tg_reauth.session /var/lib/sentinel/sentinel_session.session
sudo chown sentinel:sentinel /var/lib/sentinel/sentinel_session.session
sudo chmod 600 /var/lib/sentinel/sentinel_session.session
rm -f /tmp/tg_reauth.session
sudo systemctl restart sentinel
# Verify (read-only): the line below must appear within a minute
sudo grep 'Telegram fetcher started' /var/log/sentinel/sentinel.log | tail -1
```

**fail2ban — update whitelisted IP (if home IP changes; state-changing):**
```bash
sudo nano /etc/fail2ban/jail.d/whitelist.conf     # edit ignoreip
sudo fail2ban-client reload
sudo fail2ban-client get sshd ignoreip            # verify (read-only)
```

`whitelist.conf` also contains a 5-try / 1-hour override for `[sshd]`. It has no effect: `jail.local` is read after `jail.d/*.conf`, so its `maxretry = 3` and `bantime = 86400` win.

## Known Server Hazards

> **Audit snapshot:** first audited 2026-04-12; the debt was worked off 2026-05-25 through 2026-05-27; re-audited read-only on 2026-10-03. Resolved rows are kept for context and marked **RESOLVED**; open items are marked **OPEN**.

| # | Hazard | Location | Impact | Status / Fix |
|---|---|---|---|---|
| 1 | **Detached HEAD** | `/home/deploy/sentinel/.git` | In 2026-04 this blocked `git pull origin master` | **Now expected.** `/deploy` step 6b checks out a `deploy-*` tag, which leaves detached HEAD. Do not check out `master` on the server: that would run undeployed code without backup, config sync or drift check. See the deployed tag with `git describe --tags` |
| 2 | **Stray secrets and session files outside `/etc/sentinel`** | `/home/deploy/sentinel/.env` (0644, git-ignored; Twilio, Anthropic and Telegram keys); `/home/deploy/sentinel/sentinel_session.session` and its `-journal` (0644); `/home/deploy/sentinel.bak-20260324/` (stale March checkout with a 0644 Telegram session) | Credentials and a Telegram session readable by any local user | **OPEN (re-audit 2026-10-03).** The two `.env` files named in 2026-04 are gone, but the files listed here remain. Secrets otherwise live in `/etc/sentinel/sentinel.env`, `/etc/sentinel/openai.env` and the root-only `*.bak*` copies there. Removal and rotation are an owner decision, tracked in `TODO.md` |
| 3 | **Legacy venv** | `/home/deploy/sentinel/venv/` (removed) | `check-health.sh` still points at it | **RESOLVED for the service** (`deploy/configs/sentinel.service` uses `.venv/`); the legacy `venv/` no longer exists. **OPEN for the watchdog:** `check-health.sh` still references `venv/`, so its SMS fallback never runs (see [Health Check](#health-check)) |
| 4 | **Live config behind repo** | `/etc/sentinel/config.yaml` | In 2026-04 commit `d96f4a4` keywords were never deployed | **RESOLVED.** `/deploy` 6c syncs the config on every deploy. If the live config drifts, copy the server-only values into `config/config.yaml`, commit, and run `/deploy`; step 6a stops the deploy while server-only edits exist |
| 5 | **Backup directory growth** | `/home/deploy/backups/` | Deploy snapshots used to accumulate | **RESOLVED.** `/deploy` step 6f keeps the 10 newest `deploy-*` snapshots; daily DB backups are pruned after 7 days. Ad-hoc `config-*.yaml` copies are not pruned |
| 6 | **TVN24 and LSM Latvia 403ing** | RSS fetcher logs | Both returned 403 from server IPs in 2026-04 | **RESOLVED.** TVN24 is `enabled: false` (see Known Issues). LSM Latvia verified healthy 2026-10-03 (709 of 710 slow cycles fetched, no 403) |

## Security Stack

| Layer | Tool | Config path / state |
|---|---|---|
| Provider firewall | Hetzner Cloud Firewall | SSH 2222 is reachable from any IP today (2026-10-03 audit); fail2ban and key-only auth are the effective protection. Whether `sentinel-fw` is applied is tracked in `TODO.md` |
| Firewall | UFW | port 2222/tcp only |
| Brute force | fail2ban | `/etc/fail2ban/jail.local` (sshd: 3 tries / 10 min → 24 h ban, increment up to 7 days), `/etc/fail2ban/jail.d/whitelist.conf` (`ignoreip`) |
| Kernel | sysctl | `/etc/sysctl.d/99-sentinel-hardening.conf` |
| SSH hardening | sshd_config.d | `/etc/ssh/sshd_config.d/99-sentinel-hardening.conf` |
| SSH socket | systemd override | `/etc/systemd/system/ssh.socket.d/override.conf` |
| Auto-updates | unattended-upgrades | Security and ESM updates install automatically and may restart `sentinel` (expected). Automatic reboot is **not** enabled, so kernel and libc updates need a manual reboot; one has been pending since 2026-03 (check `/var/run/reboot-required`). A reboot interrupts monitoring, so it is the owner's decision (tracked in `TODO.md`) |
| File integrity | AIDE | `dailyaidecheck.timer`, log `/var/log/aide/aide.log`, baseline `/var/lib/aide/aide.db` from 2026-03-23 (never refreshed, so reports are noisy) |
| Service sandbox | systemd unit | `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `CapabilityBoundingSet=` (empty) |

## Known Issues

| Source | Issue | Status |
|---|---|---|
| Rzeczpospolita RSS | Returns HTTP 403 from the VPS on every slow cycle (`Failed to fetch RSS source Rzeczpospolita`). Other RSS sources and pipeline health are unaffected. | Known; source still enabled in config |
| RMF24 RSS | Intermittent 5xx errors (short bursts of 503) | Transient; no action |
| PAP RSS | WAF blocks server IPs — malformed XML or connection refused | `enabled: false` in config; covered via Google News |
| TVN24 RSS | Returns 403 Forbidden from server IPs | `enabled: false` in config |
| GDELT | IP-level 429 throttling (~20% success) | `enabled: false` in config — the fetcher is not instantiated while disabled. Re-enable only if the throttling clears |
