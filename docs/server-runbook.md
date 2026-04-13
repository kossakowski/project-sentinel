# Server Runbook — Project Sentinel

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
ssh -p 2222 deploy@178.104.76.254
```

**ALWAYS use `deploy@`.** Using `root@` or `kossa@` counts as a failed attempt. 5 failures in 10 min = fail2ban bans your IP for 1 hour.

Emergency (SSH blocked): Hetzner Cloud web console → server → Console tab → login as `root`.

## File Layout

```
/home/deploy/sentinel/               # App code (git clone of github:kossakowski/project-sentinel)
├── sentinel.py                      # Entry point
├── sentinel/                        # Python package
├── venv/                            # Python virtual environment
├── deploy/                          # Deploy scripts and systemd unit
├── tests/                           # Test suite
└── requirements.txt

/etc/sentinel/                       # Secrets and config (root:sentinel 750)
├── config.yaml                      # Live config with absolute paths (root:sentinel 640)
└── sentinel.env                     # API keys — loaded by systemd, never read by sentinel user (root:deploy 640)

/var/lib/sentinel/                   # Runtime state (sentinel:sentinel 750)
├── sentinel.db                      # SQLite DB (articles, events, alerts)
├── sentinel_session.session         # Telegram auth session (sentinel:sentinel 600)
└── health.json                      # Updated each pipeline cycle

/var/log/sentinel/                   # App logs (sentinel:sentinel 750)
└── sentinel.log                     # Rotated daily, 14-day retention, 50 MB max

/home/deploy/backups/                # Daily SQLite backups (7-day retention)
└── sentinel_YYYYMMDD.db

/home/deploy/check-health.sh         # Cron health check script
/home/deploy/backup-db.sh            # Cron backup script
```

## Service Management

```bash
sudo systemctl status sentinel
sudo systemctl start sentinel
sudo systemctl stop sentinel
sudo systemctl restart sentinel
sudo systemctl is-active sentinel
```

## Logs

```bash
sudo journalctl -u sentinel -f                          # live tail
sudo journalctl -u sentinel --since "1 hour ago"
sudo journalctl -u sentinel --since "2026-04-12 20:00"
sudo tail -100 /var/log/sentinel/sentinel.log
```

Key log signals: `[ALERT]` = phone/SMS triggered; `[CLASSIFY]` = LLM call; `[FETCH ERROR]` = source down; `[PIPELINE]` = cycle heartbeat.

## Deployment (git-based)

Remote: `git@github.com:kossakowski/project-sentinel.git` (SSH deploy key at `/home/deploy/.ssh/github_deploy`).

**Standard deploy — run from local machine:**

```bash
# 1. Push your changes to GitHub (master or tagged commit)
git push origin master

# 2. SSH in
ssh -p 2222 deploy@178.104.76.254

# 3. Pull latest
cd /home/deploy/sentinel
git fetch --tags origin
git checkout master          # or: git checkout <tag>
git pull origin master       # if staying on master

# 4. Install new deps (only if requirements.txt changed)
venv/bin/pip install -r requirements.txt

# 5. Restart and verify
sudo systemctl restart sentinel
sudo journalctl -u sentinel --since "1 minute ago"
```

**Rollback:**

```bash
cd /home/deploy/sentinel
git fetch --tags origin
git checkout <last-good-tag>      # e.g. v1.0.0
sudo systemctl restart sentinel
```

**Deploy key setup** (one-time, already done — documented for reference):
- Key at `/home/deploy/.ssh/github_deploy` (ed25519)
- SSH config: `/home/deploy/.ssh/config` routes `github.com` to that key
- Public key registered as read-only deploy key at `github.com/kossakowski/project-sentinel/settings/keys`
- Test: `ssh -T git@github.com` → should greet `kossakowski/project-sentinel`

## Configuration

Live config: `/etc/sentinel/config.yaml`

Key overrides vs. `config.example.yaml`:

```yaml
database:
  path: /var/lib/sentinel/sentinel.db

logging:
  file: /var/log/sentinel/sentinel.log

sources:
  telegram:
    session_name: /var/lib/sentinel/sentinel_session
```

Edit live config:
```bash
sudo nano /etc/sentinel/config.yaml
sudo systemctl restart sentinel
```

## Secrets

File: `/etc/sentinel/sentinel.env` — loaded by systemd `EnvironmentFile=` before dropping to `sentinel` user.

Required variables:
```
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER
ALERT_PHONE_NUMBER
ANTHROPIC_API_KEY
TELEGRAM_API_ID
TELEGRAM_API_HASH
```

Edit secrets:
```bash
sudo nano /etc/sentinel/sentinel.env
sudo systemctl restart sentinel
```

## Database Operations

```bash
# Row counts
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*) FROM articles;"
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*) FROM events;"

# Recent articles
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT * FROM articles ORDER BY created_at DESC LIMIT 10;"

# Recent events
sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT * FROM events ORDER BY created_at DESC LIMIT 10;"

# Schema
sudo sqlite3 /var/lib/sentinel/sentinel.db ".tables"
sudo sqlite3 /var/lib/sentinel/sentinel.db ".schema articles"

# Manual backup
sudo sqlite3 /var/lib/sentinel/sentinel.db ".backup '/home/deploy/backups/sentinel_manual.db'"
```

Automated backup: cron runs `/home/deploy/backup-db.sh` at `03:00` daily. Keeps 7 days. Output: `/home/deploy/backups/sentinel_YYYYMMDD.db`.

## Health Check

```bash
sudo cat /var/lib/sentinel/health.json
```

Cron: `/home/deploy/check-health.sh` runs every 30 min. If `health.json` is missing or older than 30 min, sends SMS via Twilio.

## Scheduled Cron Jobs

View: `ssh -p 2222 deploy@178.104.76.254 'crontab -l'`

| Schedule | Script | Purpose |
|---|---|---|
| `*/30 * * * *` | `/home/deploy/check-health.sh` | Health file staleness check → SMS if stale |
| `0 3 * * *` | `/home/deploy/backup-db.sh` | SQLite backup, 7-day retention |

## Pipeline Schedule

| Lane | Interval | Sources |
|---|---|---|
| Fast | every 3 min | Telegram channels, priority-1 RSS, Google News |
| Slow | every 15 min | All sources including GDELT and lower-priority RSS |
| Jitter | ±30 s | Applied to all runs to avoid predictable patterns |

## Troubleshooting Decision Tree

| Symptom | Check | Fix |
|---|---|---|
| Service not running | `sudo journalctl -u sentinel --since "5 minutes ago" --no-pager` | Fix the logged error; `sudo systemctl start sentinel` |
| Permission denied on startup | Check ownership: `/etc/sentinel` → `root:sentinel 750`; `config.yaml` → `root:sentinel 640`; `sentinel.env` → `root:deploy 640`; `/var/lib/sentinel` → `sentinel:sentinel 750` | `sudo chown` + `sudo chmod` to correct values |
| No alerts firing | Check `health.json` freshness; check logs for `[CLASSIFY]` and `[ALERT]` lines; verify Twilio creds in `sentinel.env` | Re-auth Twilio; check `ALERT_PHONE_NUMBER` in `sentinel.env` |
| Telegram not connecting | Look for `[FETCH ERROR]` + `telethon` in logs; session may be expired | Re-authenticate session (see below) |
| DB too large | `df -h /var/lib/sentinel/`; check article count | `sudo journalctl --vacuum-size=100M`; prune old backups: `sudo find /home/deploy/backups -name "*.db" -mtime +3 -delete` |
| Disk full | `df -h /` | Vacuum journald + old backups (see above) |
| SSH locked out | `ping 178.104.76.254` works but SSH refused = fail2ban ban | Hetzner web console → root login → `fail2ban-client set sshd unbanip YOUR_IP` |
| SSH connection timed out | Port blocked or sshd down | Hetzner console → `ss -tlnp \| grep 2222`; `systemctl restart ssh.socket` |
| git fetch fails on server | `ssh -T git@github.com` from server | Re-add deploy key or re-check `/home/deploy/.ssh/config` |

**Telegram session re-authentication:**
```bash
ssh -p 2222 deploy@178.104.76.254
cd /home/deploy/sentinel && source venv/bin/activate
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
sudo systemctl restart sentinel
```

**fail2ban — update whitelisted IP (if home IP changes):**
```bash
sudo nano /etc/fail2ban/jail.d/whitelist.conf
sudo fail2ban-client reload
sudo fail2ban-client get sshd ignoreip    # verify
```

## Security Stack

| Layer | Tool | Config path |
|---|---|---|
| Firewall | UFW | port 2222/tcp only |
| Brute force | fail2ban | `/etc/fail2ban/jail.local`, `/etc/fail2ban/jail.d/whitelist.conf` |
| Kernel | sysctl | `/etc/sysctl.d/99-sentinel-hardening.conf` |
| SSH hardening | sshd_config.d | `/etc/ssh/sshd_config.d/99-sentinel-hardening.conf` |
| SSH socket | systemd override | `/etc/systemd/system/ssh.socket.d/override.conf` |
| Auto-updates | unattended-upgrades | security patches only |
| File integrity | AIDE | — |
| Service sandbox | systemd unit | `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `CapabilityBoundingSet=` (empty) |

## Known Issues

| Source | Issue | Status |
|---|---|---|
| PAP RSS | WAF blocks server IPs — malformed XML or connection refused | Disabled in config |
| TVN24 RSS | Returns 403 Forbidden from server IPs | Disabled / intermittent |
| GDELT | 429 rate limit on first pipeline cycle | Auto-recovers on subsequent cycles |
