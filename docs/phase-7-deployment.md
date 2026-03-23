# Phase 7: Deployment

## Objective
Deploy Project Sentinel to a Hetzner Cloud VPS, configure it as a systemd service with auto-restart, set up log rotation, and establish monitoring and backups.

## Prerequisites
- All phases 1-6 complete and tested locally
- Hetzner Cloud account created
- **[VPS Security Hardening](security/vps-hardening.md) completed** -- do this BEFORE deployment
  - Admin user `deploy` created (SSH + sudo)
  - Service user `sentinel` created (no login, no sudo)
  - Hetzner Cloud Firewall configured
  - Directories `/var/lib/sentinel`, `/var/log/sentinel`, `/etc/sentinel` created
- Domain name (optional, not required)
- Local `.env` file with all secrets configured and working

## 7.1 VPS Setup

### Enable Hetzner Automatic Backups

In the Hetzner Cloud Console:
1. Select your server → **Backups** tab
2. Enable automatic backups (~€0.80/month for CX22)

This creates daily server snapshots with 7-day retention -- cheap insurance against host loss, accidental deletion, or botched updates.

### Order the VPS

1. Go to https://console.hetzner.cloud
2. Create a new project (e.g., "sentinel")
3. Create a new server:
   - **Location:** Falkenstein (fsn1) or Nuremberg (nbg1) -- closest to Poland
   - **Image:** Ubuntu 24.04
   - **Type:** CX22 (2 vCPU, 4 GB RAM, 40 GB disk) -- €3.99/month
   - **SSH Key:** Add your public SSH key (ed25519 recommended)
   - **Firewall:** Attach `sentinel-fw` (created in hardening Step 0)
   - **Backups:** Enable
   - **Name:** `sentinel`
4. Note the server IP address

### Deploy the Application

```bash
# SSH as admin user (port 2222, set during hardening)
ssh -p 2222 deploy@<server-ip>

# Install Python
sudo apt install -y python3 python3-pip python3-venv git sqlite3

# Clone the repo
git clone <your-repo-url> ~/sentinel
cd ~/sentinel

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Set Up Secrets and Config

```bash
# --- Secrets: isolated from the repo, not readable by the service user directly ---
# (systemd reads this as root via EnvironmentFile= before dropping to the sentinel user)
sudo cp .env /etc/sentinel/sentinel.env
sudo chown root:deploy /etc/sentinel/sentinel.env
sudo chmod 640 /etc/sentinel/sentinel.env

# --- Config: server-specific copy with absolute paths ---
sudo cp config/config.example.yaml /etc/sentinel/config.yaml
sudo chown deploy:deploy /etc/sentinel/config.yaml
sudo chmod 644 /etc/sentinel/config.yaml

# Edit the server config:
nano /etc/sentinel/config.yaml
```

In `/etc/sentinel/config.yaml`, update these paths to use absolute locations:

```yaml
database:
  path: /var/lib/sentinel/sentinel.db

logging:
  file: /var/log/sentinel/sentinel.log

sources:
  telegram:
    session_name: /var/lib/sentinel/sentinel_session
```

> **Why move secrets out of the repo?** The `.env` file contains API keys, auth tokens, and phone numbers. At `/etc/sentinel/sentinel.env` (root:deploy 0640): (1) it can't be accidentally committed to git, (2) `git pull` and `git clean` can't touch it, (3) the sentinel service user never reads the file directly -- systemd injects env vars into the process as root before dropping privileges.

### Telegram First-Time Authentication

The Telegram client needs phone verification on first run. Run this interactively, then lock down the session file:

```bash
cd ~/sentinel
source venv/bin/activate

# Load env vars for this interactive session
set -a; source /etc/sentinel/sentinel.env; set +a

python -c "
import os
from telethon import TelegramClient

client = TelegramClient(
    '/var/lib/sentinel/sentinel_session',
    int(os.environ['TELEGRAM_API_ID']),
    os.environ['TELEGRAM_API_HASH']
)

async def main():
    await client.start()
    me = await client.get_me()
    print(f'Authenticated as: {me.first_name} ({me.phone})')
    await client.disconnect()

import asyncio
asyncio.run(main())
"
# Follow the prompts to enter your phone number and verification code

# Lock down the session file -- it grants access to your Telegram account
sudo chown sentinel:sentinel /var/lib/sentinel/sentinel_session.session
sudo chmod 600 /var/lib/sentinel/sentinel_session.session
```

### Test the Installation

```bash
# Run a manual dry-run test using the server config
set -a; source /etc/sentinel/sentinel.env; set +a
~/sentinel/venv/bin/python ~/sentinel/sentinel.py \
  --config /etc/sentinel/config.yaml --once --dry-run
```

## 7.2 systemd Service

### Create Service File

```bash
sudo nano /etc/systemd/system/sentinel.service
```

Contents:
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

# Environment -- loaded by PID 1 (root) before dropping to User=sentinel,
# so the sentinel user never reads the file directly
EnvironmentFile=/etc/sentinel/sentinel.env

# --- Security sandbox ---
# Prevent privilege escalation
NoNewPrivileges=yes

# Filesystem isolation
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/sentinel /var/log/sentinel
PrivateTmp=yes

# Device and kernel isolation
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes

# Restrict capabilities and syscalls
CapabilityBoundingSet=
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
SystemCallArchitectures=native
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sentinel

[Install]
WantedBy=multi-user.target
```

### Verify Sandbox Score

```bash
# Check how well the unit is sandboxed (lower exposure = better)
sudo systemd-analyze security sentinel.service
```

Aim for an exposure score under 4.0. The directives above should get you there.

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable sentinel
sudo systemctl start sentinel

# Check status
sudo systemctl status sentinel

# View logs
sudo journalctl -u sentinel -f
```

### Service Management

```bash
# Start/stop/restart
sudo systemctl start sentinel
sudo systemctl stop sentinel
sudo systemctl restart sentinel

# View recent logs
sudo journalctl -u sentinel --since "1 hour ago"

# Check if running
sudo systemctl is-active sentinel
```

## 7.3 Log Rotation

### Application Logs

Python's `RotatingFileHandler` handles log rotation within the app (configured in `config.yaml`). Also configure system logrotate as a backup:

```bash
sudo nano /etc/logrotate.d/sentinel
```

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

### journald Logs

The systemd journal also captures stdout/stderr. Configure retention:

```bash
sudo nano /etc/systemd/journald.conf
```

Add/modify:
```
SystemMaxUse=500M
MaxRetentionSec=30day
```

```bash
sudo systemctl restart systemd-journald
```

## 7.4 Monitoring

### Health Check Script

Create a script that checks if Sentinel is healthy and sends an SMS alert if it's down:

```bash
nano ~/check_health.sh
```

```bash
#!/bin/bash
# Health check for Project Sentinel
# Runs as deploy user via cron. Checks the health file written by the daemon,
# and sends an SMS alert via Twilio if the service appears stuck or dead.

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

# Load env vars and send SMS alert
set -a; source "$ENV_FILE"; set +a
$PYTHON -c "
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import load_config
config = load_config('$CONFIG')
client = TwilioClient(config)
client.send_sms(config.alerts.phone_number, 'Project Sentinel: $MSG Sprawdź serwer.', 'health-check')
"
```

```bash
chmod +x ~/check_health.sh
```

Add to deploy user's crontab:
```bash
crontab -e
```
```
*/30 * * * * /home/deploy/check_health.sh 2>&1 | logger -t sentinel-health
```

### Disk Space Monitoring

```bash
# Add to crontab -- alert if disk > 80%
0 */6 * * * df -h / | awk 'NR==2 {gsub(/%/,"",$5); if ($5 > 80) print "Disk usage: "$5"%"}' | while read msg; do echo "$msg" | mail -s "Sentinel: disk alert" your@email.com; done
```

## 7.5 Backup

### Local Database Backup

SQLite database is a single file. Back it up daily:

```bash
nano ~/backup.sh
```

```bash
#!/bin/bash
# Daily backup of Sentinel SQLite database
BACKUP_DIR="/home/deploy/backups"
DB_FILE="/var/lib/sentinel/sentinel.db"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

# Safe hot backup via SQLite .backup command
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/sentinel_$DATE.db'"

# Keep only last 7 days
find "$BACKUP_DIR" -name "sentinel_*.db" -mtime +7 -delete
```

```bash
chmod +x ~/backup.sh
crontab -e
# Add:
0 3 * * * /home/deploy/backup.sh 2>&1 | logger -t sentinel-backup
```

### Off-Host Backup

Local backups don't survive host loss. **Pull critical files to your local machine weekly.**

On your **local machine**, create a script:

```bash
#!/bin/bash
# pull_sentinel_backup.sh -- run on your local machine
# Pulls critical Sentinel files from the VPS for disaster recovery

SERVER="deploy@<server-ip>"
SSH_PORT=2222
LOCAL_DIR="$HOME/sentinel-backups/$(date +%Y%m%d)"

mkdir -p "$LOCAL_DIR"

# Database (latest local backup)
scp -P $SSH_PORT "$SERVER:/home/deploy/backups/$(ssh -p $SSH_PORT $SERVER 'ls -t /home/deploy/backups/ | head -1')" "$LOCAL_DIR/"

# Config and systemd unit (not secret, but needed for recovery)
scp -P $SSH_PORT "$SERVER:/etc/sentinel/config.yaml" "$LOCAL_DIR/"
scp -P $SSH_PORT "$SERVER:/etc/systemd/system/sentinel.service" "$LOCAL_DIR/"

# Secrets (requires deploy user's sudo -- will prompt for password)
ssh -p $SSH_PORT -t "$SERVER" "sudo cat /etc/sentinel/sentinel.env" > "$LOCAL_DIR/sentinel.env"
ssh -p $SSH_PORT -t "$SERVER" "sudo cat /var/lib/sentinel/sentinel_session.session" > "$LOCAL_DIR/sentinel_session.session"

chmod 600 "$LOCAL_DIR/sentinel.env" "$LOCAL_DIR/sentinel_session.session"

# Keep only last 4 weekly backups
find "$(dirname "$LOCAL_DIR")" -maxdepth 1 -type d -mtime +28 -exec rm -rf {} \;

echo "Backup complete: $LOCAL_DIR"
```

Add to your **local** crontab:
```
0 4 * * 0 /path/to/pull_sentinel_backup.sh 2>&1 | logger -t sentinel-offhost-backup
```

> **Note:** The scp/ssh commands for secrets require `deploy`'s sudo password, so automatic cron requires either passwordless sudo for specific commands or SSH agent forwarding. For manual weekly pulls, just run the script by hand.

### What's Backed Up Where

| Asset | Local daily backup | Off-host weekly | Hetzner auto-backup |
|-------|-------------------|----------------|-------------------|
| SQLite DB | Yes (7-day retention) | Yes | Yes (7-day retention) |
| `.env` secrets | -- | Yes | Yes |
| `config.yaml` | -- | Yes | Yes |
| Telegram session | -- | Yes | Yes |
| systemd unit | -- | Yes | Yes |
| Code (git repo) | -- | In git remote | Yes |

### Automatic Updates

For security updates only:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## 7.6 Updating the Application

```bash
ssh -p 2222 deploy@<server-ip>
cd ~/sentinel

# Pull latest code
git pull origin main

# Update dependencies if requirements.txt changed
source venv/bin/activate
pip install -r requirements.txt

# If config.yaml schema changed, update the server copy:
# nano /etc/sentinel/config.yaml

# Restart service
sudo systemctl restart sentinel

# Verify it's running
sudo systemctl status sentinel
sudo journalctl -u sentinel --since "1 minute ago"
```

## 7.7 Rollback

If an update breaks something:

```bash
# Check git log for last known good commit
git log --oneline -10

# Revert to previous commit
git checkout <commit-hash>

# Restart
sudo systemctl restart sentinel
```

## Acceptance Criteria

1. `sudo systemctl status sentinel` shows "active (running)"
2. `sudo journalctl -u sentinel` shows pipeline cycles executing
3. `/var/lib/sentinel/health.json` is updated after each cycle
4. Service auto-restarts after being killed (`sudo kill -9 $(pgrep -f sentinel.py)`)
5. Service starts automatically after VPS reboot
6. `--dry-run --once` produces expected output when run manually
7. `sudo systemd-analyze security sentinel.service` scores under 4.0
8. Log rotation keeps log files under configured max size
9. Health check cron detects if service is stuck and sends SMS
10. Database backup runs daily, off-host backup runs weekly
11. Hetzner automatic backups are enabled
