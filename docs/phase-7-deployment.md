# Phase 7: Deployment

> STATUS: COMPLETE — deployed to production.
> SCOPE: one-time build and harden steps. Day-2 operations (deploy, logs, DB, troubleshooting) live in [`server-runbook.md`](server-runbook.md).
> KEY FILES: `deploy/sentinel.service`, `/etc/sentinel/config.yaml` (server), `/etc/sentinel/sentinel.env` (server), `/etc/systemd/system/sentinel.service`.

## Objective

Provision a Hetzner VPS, install Sentinel as a sandboxed systemd service running under a dedicated `sentinel` user, enable log rotation, health-check cron, and daily DB backup.

## Prerequisites

| Requirement | Source |
|---|---|
| Phases 1–6 complete and tested locally | — |
| VPS hardened: `deploy` admin user, `sentinel` service user, UFW, fail2ban, SSH port 2222 | [`security/vps-hardening.md`](security/vps-hardening.md) |
| Directories `/var/lib/sentinel`, `/var/log/sentinel`, `/etc/sentinel` created with correct ownership | hardening doc |
| Hetzner Cloud Firewall `sentinel-fw` attached (whitelisted home IP on 2222) | hardening doc |
| GitHub deploy key generated at `/home/deploy/.ssh/github_deploy` (ed25519) | see 7.1 |

## 7.1 VPS Spec

| Field | Value |
|---|---|
| Provider | Hetzner Cloud |
| Location | Nuremberg (`nbg1`) |
| Image | Ubuntu 24.04 LTS |
| Type | CX23 (2 vCPU, 4 GB RAM) |
| Backups | Hetzner automatic backups enabled (7-day retention) |
| SSH | Port 2222, key-only, `deploy` user |

See [`server-runbook.md` §Server Facts](server-runbook.md#server-facts) for live IP and access details.

## 7.2 Clone Repo and Install

Production uses **git-pull from GitHub** via a read-only deploy key. No rsync.

**One-time deploy key setup:**

```bash
ssh -p 2222 deploy@<server-ip>

# Generate deploy key
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""

# Route github.com to this key
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# Register public key at github.com/kossakowski/project-sentinel/settings/keys
cat ~/.ssh/github_deploy.pub
# Paste as read-only deploy key.

# Verify
ssh -T git@github.com   # should greet kossakowski/project-sentinel
```

Migration history from rsync → git-pull: [`migration-git-deploy.md`](migration-git-deploy.md).

**Clone and install:**

```bash
sudo apt install -y python3 python3-venv git sqlite3

git clone git@github.com:kossakowski/project-sentinel.git /home/deploy/sentinel
cd /home/deploy/sentinel
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 7.3 Config and Secrets

| Path | Owner | Mode | Purpose |
|---|---|---|---|
| `/etc/sentinel/` | `root:sentinel` | `750` | Config directory |
| `/etc/sentinel/config.yaml` | `root:sentinel` | `640` | Live config with absolute paths |
| `/etc/sentinel/sentinel.env` | `root:deploy` | `640` | API keys; loaded by systemd as root before dropping privileges |

```bash
sudo install -d -o root -g sentinel -m 750 /etc/sentinel

sudo install -o root -g deploy -m 640 .env /etc/sentinel/sentinel.env
sudo install -o root -g sentinel -m 640 config/config.example.yaml /etc/sentinel/config.yaml
sudo nano /etc/sentinel/config.yaml
```

**Required overrides** in `/etc/sentinel/config.yaml` (absolute paths — service user cannot write the repo tree):

```yaml
database:
  path: /var/lib/sentinel/sentinel.db

logging:
  file: /var/log/sentinel/sentinel.log

sources:
  telegram:
    session_name: /var/lib/sentinel/sentinel_session
```

Why secrets live outside the repo: `git pull`/`git clean` cannot touch them; the `sentinel` user never reads the file (systemd injects env vars as root via `EnvironmentFile=` before `User=sentinel` takes effect).

## 7.4 Telegram First-Run Authentication

Telethon needs interactive phone verification once. Run as `deploy`, then hand the session file to `sentinel`:

```bash
cd /home/deploy/sentinel
source venv/bin/activate
set -a; source <(sudo cat /etc/sentinel/sentinel.env); set +a

python -c "
import os, asyncio
from telethon import TelegramClient
c = TelegramClient('/var/lib/sentinel/sentinel_session',
    int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
async def main():
    await c.start()
    me = await c.get_me()
    print(f'Authenticated as: {me.first_name} ({me.phone})')
    await c.disconnect()
asyncio.run(main())
"

sudo chown sentinel:sentinel /var/lib/sentinel/sentinel_session.session
sudo chmod 600 /var/lib/sentinel/sentinel_session.session
```

Re-auth procedure if the session expires: [`server-runbook.md` §Telegram session re-authentication](server-runbook.md#troubleshooting-decision-tree).

## 7.5 Dry-Run Smoke Test

```bash
set -a; source <(sudo cat /etc/sentinel/sentinel.env); set +a
/home/deploy/sentinel/venv/bin/python /home/deploy/sentinel/sentinel.py \
  --config /etc/sentinel/config.yaml --once --dry-run
```

Expect a full pipeline cycle with no Twilio calls and `health.json` written under `/var/lib/sentinel/`.

## 7.6 systemd Unit

File: `/etc/systemd/system/sentinel.service`.

```ini
[Unit]
Description=Project Sentinel Military Alert Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sentinel
Group=sentinel
WorkingDirectory=/home/deploy/sentinel
ExecStart=/home/deploy/sentinel/venv/bin/python sentinel.py --config /etc/sentinel/config.yaml
Restart=always
RestartSec=30
StartLimitBurst=5
StartLimitIntervalSec=300

EnvironmentFile=/etc/sentinel/sentinel.env

# Sandbox — verified; targets systemd-analyze security score < 4.0
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/sentinel /var/log/sentinel
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
CapabilityBoundingSet=
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
SystemCallArchitectures=native
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

StandardOutput=journal
StandardError=journal
SyslogIdentifier=sentinel

[Install]
WantedBy=multi-user.target
```

| Directive | Effect |
|---|---|
| `User=sentinel` + `WorkingDirectory=/home/deploy/sentinel` | Code owned by `deploy`, read-only to `sentinel` |
| `EnvironmentFile=/etc/sentinel/sentinel.env` | Loaded as PID 1 root before user drop |
| `ProtectSystem=strict` + `ReadWritePaths=/var/lib/sentinel /var/log/sentinel` | Only DB dir and log dir are writable |
| `ProtectHome=read-only` | `/home/deploy/sentinel` readable for code import, not writable |
| `CapabilityBoundingSet=` (empty) | No capabilities at all |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` | No raw sockets, no netlink |

**Enable:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel
sudo systemd-analyze security sentinel.service    # expect exposure < 4.0
```

Day-2 service management: [`server-runbook.md` §Service Management](server-runbook.md#service-management).

## 7.7 Log Rotation

**App logs** — `/etc/logrotate.d/sentinel`:

```
/var/log/sentinel/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**journald** — `/etc/systemd/journald.conf`:

```
SystemMaxUse=500M
MaxRetentionSec=30day
```

```bash
sudo systemctl restart systemd-journald
```

## 7.8 Cron Jobs

Owner: `deploy`. View with `crontab -l`.

| Schedule | Script | Purpose |
|---|---|---|
| `*/30 * * * *` | `/home/deploy/check-health.sh` | SMS via Twilio if `/var/lib/sentinel/health.json` is missing or older than 30 min. Doubles as deadman switch. |
| `0 3 * * *` | `/home/deploy/backup-db.sh` | SQLite `.backup` to `/home/deploy/backups/sentinel_YYYYMMDD.db`, 7-day retention. |

**`/home/deploy/check-health.sh`:**

```bash
#!/bin/bash
HEALTH_FILE="/var/lib/sentinel/health.json"
MAX_AGE_MINUTES=30
ENV_FILE="/etc/sentinel/sentinel.env"
CONFIG="/etc/sentinel/config.yaml"
PYTHON="/home/deploy/sentinel/venv/bin/python"

if [ ! -f "$HEALTH_FILE" ]; then
    MSG="Health file missing -- sentinel may not be running."
elif [ $(($(date +%s) - $(stat -c %Y "$HEALTH_FILE"))) -gt $((MAX_AGE_MINUTES * 60)) ]; then
    MSG="Health file stale -- sentinel may be stuck."
else
    exit 0
fi

set -a; source "$ENV_FILE"; set +a
$PYTHON -c "
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import load_config
config = load_config('$CONFIG')
client = TwilioClient(config)
client.send_sms(config.alerts.phone_number, 'Project Sentinel: $MSG Sprawdź serwer.', 'health-check')
"
```

**`/home/deploy/backup-db.sh`:**

```bash
#!/bin/bash
BACKUP_DIR="/home/deploy/backups"
DB_FILE="/var/lib/sentinel/sentinel.db"
DATE=$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/sentinel_$DATE.db'"
find "$BACKUP_DIR" -name "sentinel_*.db" -mtime +7 -delete
```

```bash
chmod +x /home/deploy/check-health.sh /home/deploy/backup-db.sh
crontab -e
# */30 * * * * /home/deploy/check-health.sh 2>&1 | logger -t sentinel-health
# 0 3 * * *   /home/deploy/backup-db.sh   2>&1 | logger -t sentinel-backup
```

## 7.9 Off-Host Backup (Manual, Weekly)

Local backups don't survive host loss. Run from your workstation:

```bash
SERVER="deploy@<server-ip>"; SSH_PORT=2222
LOCAL="$HOME/sentinel-backups/$(date +%Y%m%d)"
mkdir -p "$LOCAL"

LATEST=$(ssh -p $SSH_PORT $SERVER 'ls -t /home/deploy/backups/ | head -1')
scp -P $SSH_PORT "$SERVER:/home/deploy/backups/$LATEST" "$LOCAL/"
scp -P $SSH_PORT "$SERVER:/etc/systemd/system/sentinel.service" "$LOCAL/"
ssh -p $SSH_PORT -t "$SERVER" "sudo cat /etc/sentinel/config.yaml"    > "$LOCAL/config.yaml"
ssh -p $SSH_PORT -t "$SERVER" "sudo cat /etc/sentinel/sentinel.env"    > "$LOCAL/sentinel.env"
ssh -p $SSH_PORT -t "$SERVER" "sudo cat /var/lib/sentinel/sentinel_session.session" > "$LOCAL/sentinel_session.session"
chmod 600 "$LOCAL/sentinel.env" "$LOCAL/sentinel_session.session"
```

| Asset | Local daily | Off-host weekly | Hetzner auto |
|---|---|---|---|
| SQLite DB | Yes (7d) | Yes | Yes (7d) |
| `sentinel.env` secrets | — | Yes | Yes |
| `config.yaml` | — | Yes | Yes |
| Telegram session | — | Yes | Yes |
| systemd unit | — | Yes | Yes |
| Code | in GitHub remote | in GitHub remote | Yes |

## 7.10 Unattended Security Updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

Security patches only — no feature upgrades.

## Acceptance Criteria

| # | Check | Command |
|---|---|---|
| 1 | Service active | `sudo systemctl is-active sentinel` → `active` |
| 2 | Cycles running | `sudo journalctl -u sentinel` shows `[PIPELINE]` heartbeats |
| 3 | Health file fresh | `stat -c %Y /var/lib/sentinel/health.json` within 30 min |
| 4 | Auto-restart | `sudo kill -9 $(pgrep -f sentinel.py)` → service respawns in ≤30 s |
| 5 | Boot persistence | `sudo reboot` → service up after boot |
| 6 | Dry-run OK | `--config /etc/sentinel/config.yaml --once --dry-run` prints full cycle |
| 7 | Sandbox score | `sudo systemd-analyze security sentinel.service` < 4.0 |
| 8 | Logrotate | `/var/log/sentinel/sentinel.log.1.gz` exists after day 2 |
| 9 | Health cron | Stop service → within 30 min SMS arrives |
| 10 | Daily DB backup | `ls /home/deploy/backups/sentinel_*.db` grows daily, capped at 7 |
| 11 | Hetzner backups | Console → Backups tab shows daily snapshots |

## KNOWN QUIRKS

| Quirk | Impact |
|---|---|
| Four filesystem roots: code at `/home/deploy/sentinel/`, config at `/etc/sentinel/`, state at `/var/lib/sentinel/`, logs at `/var/log/sentinel/` | `sentinel` user has no shell — service-only; any manual test must run as `deploy` with `sudo cat` for secrets. |
| SSH port 2222 + fail2ban (5 fails / 10 min → 1 h ban) | Wrong username (`root@`, `kossa@`) counts as a failure. Always `deploy@`. |
| Config path is absolute on server (`/etc/sentinel/config.yaml`), relative in local dev (`config/config.yaml`) | `ExecStart` must pass `--config /etc/sentinel/config.yaml` explicitly. |
| Health cron doubles as deadman switch | If cron itself dies, you lose the alert — verify with `systemctl status cron` monthly. |
| Service user can only write `/var/lib/sentinel` and `/var/log/sentinel` (per `ReadWritePaths`) | Any new write path (new DB, new log) requires updating the unit and `daemon-reload`. |
| Git-pull deploy requires the deploy key on `/home/deploy/.ssh/github_deploy` | If `ssh -T git@github.com` fails, re-register the public key in GitHub settings. |

## Cross-References

| Topic | Doc |
|---|---|
| Day-2 deploy, rollback, logs, DB queries, troubleshooting | [`server-runbook.md`](server-runbook.md) |
| VPS hardening (must precede this phase) | [`security/vps-hardening.md`](security/vps-hardening.md) |
| rsync → git-pull migration history | [`migration-git-deploy.md`](migration-git-deploy.md) |
| Config parameter reference | [`config-reference.md`](config-reference.md) |
