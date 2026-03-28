# Server Runbook

Complete reference for operating the production server. Point Claude Code at this file to give it full context: "Read docs/server-runbook.md and then do X".

## Server Access

```bash
ssh -p 2222 deploy@178.104.76.254
```

- **Provider:** Hetzner Cloud, CX23 (2 vCPU, 4GB RAM), Nuremberg datacenter
- **OS:** Ubuntu 24.04 LTS
- **SSH port:** 2222 (default 22 is firewalled off)
- **Auth:** SSH key only, password auth disabled
- **Admin user:** `deploy` (passwordless sudo, SSH key login)
- **Service user:** `sentinel` (no login shell, no sudo, runs the app via systemd)

> **IMPORTANT:** Always use `deploy@` when connecting. Do NOT use `root@` or `kossa@` — these will be rejected and count as failed login attempts. After **5 failed attempts** within 10 minutes, fail2ban will ban your IP for 1 hour. See [Locked out of SSH](#locked-out-of-ssh-fail2ban) below for recovery.

### Emergency Console Access

If SSH is completely inaccessible, use the **Hetzner Cloud web console**:
1. Log in at https://console.hetzner.cloud
2. Select the server → **Console** tab
3. Log in as `root` (password set during VPS provisioning — check your password manager)

## File Layout

```
/home/deploy/sentinel/           # Application code (copied via scp, no git remote)
├── sentinel.py                  # Main entry point
├── sentinel/                    # Python package
├── config/config.example.yaml   # Template config (repo version)
├── venv/                        # Python virtual environment
├── deploy/                      # Deployment scripts and configs
├── scripts/                     # One-shot setup and migration scripts
├── tests/                       # Test suite
└── requirements.txt

/etc/sentinel/                   # Configuration and secrets (root:sentinel 750)
├── config.yaml                  # Live config with absolute paths (root:sentinel 640)
└── sentinel.env                 # API keys and secrets (root:deploy 640)

/var/lib/sentinel/               # State data (sentinel:sentinel 750)
├── sentinel_session.session     # Telegram auth session
└── health.json                  # Updated each pipeline cycle

/var/log/sentinel/               # Application logs (sentinel:sentinel 750)
└── sentinel.log                 # Rotated daily, 14 days retention, 50MB max

/home/deploy/backups/            # Daily database backups (7 day retention)
└── sentinel_YYYYMMDD.pgdump
```

## Service Management

```bash
# Status
sudo systemctl status sentinel
sudo systemctl is-active sentinel

# Start / stop / restart
sudo systemctl start sentinel
sudo systemctl stop sentinel
sudo systemctl restart sentinel

# Logs (journald)
sudo journalctl -u sentinel -f                          # follow live
sudo journalctl -u sentinel --since "1 hour ago"        # recent
sudo journalctl -u sentinel --since "24 hours ago"      # last day
sudo journalctl -u sentinel --since "2026-03-23 20:00"  # specific time

# Log file
sudo cat /var/log/sentinel/sentinel.log
sudo tail -100 /var/log/sentinel/sentinel.log

# Health check
sudo cat /var/lib/sentinel/health.json

# Database queries (PostgreSQL)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM articles;"
psql $DATABASE_URL -c "\dt"
psql $DATABASE_URL -c "SELECT * FROM articles ORDER BY created_at DESC LIMIT 10;"
psql $DATABASE_URL -c "SELECT * FROM events ORDER BY created_at DESC LIMIT 10;"
psql $DATABASE_URL -c "SELECT * FROM users;"
psql $DATABASE_URL -c "SELECT * FROM tiers;"
```

## Configuration

The live config is at `/etc/sentinel/config.yaml`. It's a copy of `config/config.example.yaml` with these values changed:

```yaml
database:
  url: postgresql://sentinel:PASSWORD@localhost:5432/sentinel  # was: data/sentinel.db path

logging:
  file: /var/log/sentinel/sentinel.log    # was: logs/sentinel.log

sources:
  telegram:
    session_name: /var/lib/sentinel/sentinel_session  # was: sentinel_session
```

To edit the live config:
```bash
sudo nano /etc/sentinel/config.yaml
sudo systemctl restart sentinel
```

## Secrets (.env)

Location: `/etc/sentinel/sentinel.env` (root:deploy 640)

Loaded by systemd via `EnvironmentFile=` — the sentinel user never reads it directly.

Required variables:
```
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
SYSTEM_PHONE_NUMBER=...
DATABASE_URL=postgresql://sentinel:PASSWORD@localhost:5432/sentinel
ANTHROPIC_API_KEY=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
```

> `ALERT_PHONE_NUMBER` is no longer a top-level config variable. Alert destinations are now stored per-user in the `users` table. `ALERT_PHONE_NUMBER` is only used by `scripts/migrate_sqlite_to_pg.py` to set the phone number of the primary user during migration.

## Database Setup (PostgreSQL)

The application uses PostgreSQL. On a fresh server:

```bash
# Install PostgreSQL
sudo apt install -y postgresql

# Create DB user and database
sudo -u postgres psql -c "CREATE USER sentinel WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE sentinel OWNER sentinel;"

# Verify connection
psql postgresql://sentinel:your_password@localhost:5432/sentinel -c "SELECT 1;"
```

The application creates all tables automatically on first run (via `Database._create_tables()` in `sentinel/database.py`). There is no separate schema migration tool.

### Seeding Tiers (required before first run)

```bash
cd /home/deploy/sentinel
DATABASE_URL=postgresql://sentinel:PASSWORD@localhost:5432/sentinel \
  venv/bin/python scripts/seed_tiers.py
```

This seeds the `tiers` table with Standard and Premium tier definitions. Idempotent — safe to run again.

### Creating the Initial User

```bash
DATABASE_URL=postgresql://sentinel:PASSWORD@localhost:5432/sentinel \
  venv/bin/python scripts/create_initial_user.py \
    --name "Your Name" \
    --phone "+48XXXXXXXXX" \
    --tier Standard \
    --countries PL,LT,LV,EE
```

### Migrating from SQLite (existing installations only)

If upgrading from the SQLite version, run the one-shot migration script **before** starting the new version:

```bash
# Set env vars for both databases
export DATABASE_URL=postgresql://sentinel:PASSWORD@localhost:5432/sentinel
export ALERT_PHONE_NUMBER=+48XXXXXXXXX   # phone number for the primary user
export ALERT_USER_NAME="Your Name"       # display name for the primary user

cd /home/deploy/sentinel
venv/bin/python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path /path/to/old/sentinel.db \
  --pg-url "$DATABASE_URL"
```

The script is idempotent (uses `INSERT ... ON CONFLICT DO NOTHING`). It:
1. Creates all PostgreSQL tables
2. Copies articles, classifications, events, and alert_records
3. Seeds tiers
4. Creates the primary user from env vars
5. Backfills `alert_records.user_id` to point at that user

After confirming the migration succeeded, the old SQLite file can be removed.

## Deploying Updates

The server has no git remote — code was copied via scp. To update:

```bash
# From local machine:
scp -P 2222 -r /home/kossa/code/project-sentinel/ deploy@178.104.76.254:/home/deploy/sentinel

# Then on the server:
ssh -p 2222 deploy@178.104.76.254
cd /home/deploy/sentinel
venv/bin/pip install -r requirements.txt  # if deps changed
sudo systemctl restart sentinel
sudo journalctl -u sentinel --since "1 minute ago"  # verify
```

To update only specific files (faster):
```bash
scp -P 2222 path/to/changed/file deploy@178.104.76.254:/home/deploy/sentinel/path/to/changed/file
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl restart sentinel'
```

## Rollback

If an update breaks things:
```bash
# On local machine, check the last known-good tag:
git log --oneline --tags
# Currently: v1.0.0 = first production deploy

# Re-deploy that version:
git checkout v1.0.0
scp -P 2222 -r /home/kossa/code/project-sentinel/ deploy@178.104.76.254:/home/deploy/sentinel
ssh -p 2222 deploy@178.104.76.254 'sudo systemctl restart sentinel'
git checkout master  # go back to latest locally
```

## Scheduled Jobs (cron)

Run as the `deploy` user. View with: `ssh -p 2222 deploy@178.104.76.254 'crontab -l'`

| Schedule | Script | Purpose |
|----------|--------|---------|
| `*/30 * * * *` | `/home/deploy/check-health.sh` | Checks health.json freshness, sends SMS if stale |
| `0 3 * * *` | `/home/deploy/backup-db.sh` | PostgreSQL dump to /home/deploy/backups/, 7-day retention |

## Security Stack

| Layer | Tool | Config |
|-------|------|--------|
| Firewall | UFW | Only port 2222/tcp open |
| Brute force | fail2ban | Monitors SSH, bans after 5 failures for 1h (79.184.239.122 whitelisted) |
| Kernel | sysctl | `/etc/sysctl.d/99-sentinel-hardening.conf` |
| SSH | sshd_config.d | `/etc/ssh/sshd_config.d/99-sentinel-hardening.conf` |
| SSH socket | systemd override | `/etc/systemd/system/ssh.socket.d/override.conf` |
| Updates | unattended-upgrades | Auto security patches |
| Intrusion | AIDE | File integrity monitoring |
| Service sandbox | systemd | NoNewPrivileges, ProtectSystem, CapabilityBoundingSet, etc. |

## Troubleshooting

**Service won't start:**
```bash
sudo journalctl -u sentinel --since "5 minutes ago" --no-pager
```

**Permission denied errors:**
- Config: must be `root:sentinel 640`
- Secrets: must be `root:deploy 640`
- /etc/sentinel: must be `root:sentinel 750`
- /var/lib/sentinel: must be `sentinel:sentinel 750`
- /home/deploy: must be `755` (sentinel needs to traverse to the app)

**Telegram session expired:**
SSH in as deploy, re-authenticate interactively:
```bash
cd /home/deploy/sentinel && source venv/bin/activate
set -a && source <(sudo cat /etc/sentinel/sentinel.env) && set +a
python -c "import os,asyncio;from telethon import TelegramClient;c=TelegramClient('/tmp/tg_reauth',int(os.environ['TELEGRAM_API_ID']),os.environ['TELEGRAM_API_HASH']);asyncio.run(c.start());print('Done')"
sudo cp /tmp/tg_reauth.session /var/lib/sentinel/sentinel_session.session
sudo chown sentinel:sentinel /var/lib/sentinel/sentinel_session.session
sudo chmod 600 /var/lib/sentinel/sentinel_session.session
sudo systemctl restart sentinel
```

**Locked out of SSH (fail2ban):**

Most likely cause: fail2ban banned your IP after repeated failed SSH attempts (e.g., connecting with the wrong username). Symptoms: `ssh` returns "Connection refused" but `ping` works.

Diagnosis from local machine:
```bash
# "Connection refused" + ping works = fail2ban ban (port is open but your IP is rejected)
# "Connection timed out" + ping works = firewall/sshd issue (port is blocked or not listening)
ping 178.104.76.254
ssh -p 2222 deploy@178.104.76.254
```

Recovery via Hetzner Cloud Console (web terminal):
```bash
# Log in as root at: Hetzner Cloud → server → Console tab

# Check if your IP is banned (replace with your actual IP)
fail2ban-client status sshd

# Unban your IP
fail2ban-client set sshd unbanip YOUR_IP_HERE

# Verify the unban worked (test SSH from your local machine)
```

If sshd itself is broken (not fail2ban):
```bash
# Check if SSH socket is listening
ss -tlnp | grep 2222

# Check socket override exists
cat /etc/systemd/system/ssh.socket.d/override.conf

# Restart SSH
systemctl daemon-reload
systemctl restart ssh.socket

# Nuclear option: remove hardening and restart
rm /etc/ssh/sshd_config.d/99-sentinel-hardening.conf && systemctl restart ssh
```

**fail2ban configuration:**
- Config: `/etc/fail2ban/jail.local` + `/etc/fail2ban/jail.d/whitelist.conf`
- Whitelisted IPs: `79.184.239.122` (kossa's home IP)
- Ban threshold: 5 failed attempts in 10 minutes → 1 hour ban
- If your home IP changes, update the whitelist:
  ```bash
  sudo nano /etc/fail2ban/jail.d/whitelist.conf   # update the IP
  sudo fail2ban-client reload
  sudo fail2ban-client get sshd ignoreip           # verify
  ```

**Disk full:**
```bash
df -h /
sudo journalctl --vacuum-size=100M
sudo find /home/deploy/backups -name "*.pgdump" -mtime +3 -delete
```

## Known Issues

- **PAP RSS** returns malformed XML — their feed is broken, not our bug
- **TVN24 RSS** returns 403 Forbidden — they block server IPs
- **GDELT** rate limits (429) on first cycle — works on subsequent runs

## Pipeline Schedule

- **Fast lane (every 3 min):** Telegram channels + priority-1 RSS + Google News
- **Slow lane (every 15 min):** All sources including GDELT and lower-priority RSS
- **Jitter:** ±30 seconds to avoid predictable request patterns
