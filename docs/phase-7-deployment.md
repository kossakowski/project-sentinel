# Phase 7: Deployment

## Objective
Deploy Project Sentinel to a Hetzner Cloud VPS, configure it as a systemd service with auto-restart, set up log rotation, and establish basic monitoring.

## Prerequisites
- All phases 1-6 complete and tested locally
- Hetzner Cloud account created
- **[VPS Security Hardening](security/vps-hardening.md) completed** -- do this BEFORE deployment
- Domain name (optional, not required)
- Local `.env` file with all secrets configured and working

## 7.1 VPS Setup

### Order the VPS

1. Go to https://console.hetzner.cloud
2. Create a new project (e.g., "sentinel")
3. Create a new server:
   - **Location:** Falkenstein (fsn1) or Nuremberg (nbg1) -- closest to Poland
   - **Image:** Ubuntu 24.04
   - **Type:** CX22 (2 vCPU, 4 GB RAM, 40 GB disk) -- €3.99/month
   - **SSH Key:** Add your public SSH key (never use password auth)
   - **Name:** `sentinel`
4. Note the server IP address

### Initial Server Configuration

```bash
# SSH into server
ssh root@<server-ip>

# Update system
apt update && apt upgrade -y

# Create a non-root user
adduser sentinel
usermod -aG sudo sentinel

# Copy SSH key to new user
mkdir -p /home/sentinel/.ssh
cp ~/.ssh/authorized_keys /home/sentinel/.ssh/
chown -R sentinel:sentinel /home/sentinel/.ssh
chmod 700 /home/sentinel/.ssh
chmod 600 /home/sentinel/.ssh/authorized_keys

# Disable root SSH login and password auth
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# Install fail2ban
apt install -y fail2ban
systemctl enable fail2ban

# Configure firewall (ufw)
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw enable

# Install Python 3.11+
apt install -y python3 python3-pip python3-venv git

# Log out and re-login as sentinel user
exit
```

### Deploy the Application

```bash
# SSH as sentinel user
ssh sentinel@<server-ip>

# Clone the repo (or copy files)
git clone <your-repo-url> ~/sentinel
cd ~/sentinel

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create directories
mkdir -p data logs

# Copy .env file (from your local machine)
# On your LOCAL machine:
# scp .env sentinel@<server-ip>:~/sentinel/.env

# Copy config file
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your settings:
nano config/config.yaml

# Test the installation
python sentinel.py --config config/config.yaml --once --dry-run
```

### Telegram First-Time Authentication

The Telegram client needs phone verification on first run:

```bash
cd ~/sentinel
source venv/bin/activate
python -c "
from telethon import TelegramClient
client = TelegramClient('sentinel_session', API_ID, API_HASH)
client.start()
print('Telegram authenticated successfully')
client.disconnect()
"
# Follow the prompts to enter your phone number and verification code
# This creates a session file that persists the auth
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
WorkingDirectory=/home/sentinel/sentinel
ExecStart=/home/sentinel/sentinel/venv/bin/python sentinel.py --config config/config.yaml
Restart=always
RestartSec=30
StartLimitBurst=5
StartLimitIntervalSec=300

# Environment
EnvironmentFile=/home/sentinel/sentinel/.env

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/sentinel/sentinel/data /home/sentinel/sentinel/logs
PrivateTmp=yes

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sentinel

[Install]
WantedBy=multi-user.target
```

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

Python's `RotatingFileHandler` handles log rotation within the app (configured in `config.yaml`). But also configure system logrotate as a backup:

```bash
sudo nano /etc/logrotate.d/sentinel
```

```
/home/sentinel/sentinel/logs/*.log {
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

Create a script that checks if Sentinel is healthy and sends an SMS if it's down:

```bash
#!/bin/bash
# /home/sentinel/check_health.sh

HEALTH_FILE="/home/sentinel/sentinel/data/health.json"
MAX_AGE_MINUTES=30

if [ ! -f "$HEALTH_FILE" ]; then
    echo "Health file missing -- sentinel may not be running"
    exit 1
fi

# Check file age
FILE_AGE=$(($(date +%s) - $(stat -c %Y "$HEALTH_FILE")))
MAX_AGE=$((MAX_AGE_MINUTES * 60))

if [ "$FILE_AGE" -gt "$MAX_AGE" ]; then
    echo "Health file is ${FILE_AGE}s old (max: ${MAX_AGE}s) -- sentinel may be stuck"
    exit 1
fi

echo "Project Sentinel healthy"
exit 0
```

Add to crontab:
```bash
crontab -e
```
```
*/30 * * * * /home/sentinel/check_health.sh || /home/sentinel/sentinel/venv/bin/python -c "
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import load_config
config = load_config('/home/sentinel/sentinel/config/config.yaml')
client = TwilioClient(config)
client.send_sms(config.alerts.phone_number, 'Project Sentinel: system nie odpowiada! Sprawdź serwer.', 'health-check')
"
```

### Disk Space Monitoring

```bash
# Add to crontab -- alert if disk > 80%
0 */6 * * * df -h / | awk 'NR==2 {gsub(/%/,"",$5); if ($5 > 80) print "Disk usage: "$5"%"}' | while read msg; do echo "$msg" | mail -s "Sentinel: disk alert" your@email.com; done
```

### Automatic Updates

For security updates only:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## 7.5 Backup

### Database Backup

SQLite database is a single file. Back it up daily:

```bash
# /home/sentinel/backup.sh
#!/bin/bash
BACKUP_DIR="/home/sentinel/backups"
DB_FILE="/home/sentinel/sentinel/data/sentinel.db"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/sentinel_$DATE.db'"

# Keep only last 7 days
find "$BACKUP_DIR" -name "sentinel_*.db" -mtime +7 -delete
```

```bash
chmod +x /home/sentinel/backup.sh
crontab -e
# Add:
0 3 * * * /home/sentinel/backup.sh
```

## 7.6 Updating the Application

```bash
ssh sentinel@<server-ip>
cd ~/sentinel

# Pull latest code
git pull origin main

# Update dependencies if requirements.txt changed
source venv/bin/activate
pip install -r requirements.txt

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
2. `sentinel.log` shows pipeline cycles executing every ~15 minutes
3. `data/health.json` is updated after each cycle
4. Service auto-restarts after being killed (`kill -9`)
5. Service starts automatically after VPS reboot
6. `--dry-run --once` produces expected output when run manually
7. Log rotation keeps log files under configured max size
8. Health check cron detects if service is stuck and sends SMS
9. Database backup runs daily
