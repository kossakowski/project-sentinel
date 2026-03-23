#!/bin/bash
# =============================================================================
# Project Sentinel -- Service & Monitoring Setup
# =============================================================================
# Run as: deploy user (needs sudo)
# Prerequisites: 02-deploy-app.sh completed, secrets in /etc/sentinel/sentinel.env
#
# This script:
#   1. Installs systemd service (auto-start on boot, auto-restart on crash)
#   2. Configures log rotation
#   3. Sets up health-check cron (SMS alert if sentinel stops)
#   4. Sets up daily database backup cron
#   5. Configures journald log retention
# =============================================================================

set -euo pipefail

APP_DIR="/home/deploy/sentinel"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Preflight ----------------------------------------------------------------

if [ "$(whoami)" = "root" ]; then
    echo "ERROR: Do not run this as root. Run as the deploy user."
    exit 1
fi

if [ ! -f "$APP_DIR/sentinel.py" ]; then
    echo "ERROR: App not found at $APP_DIR. Run 02-deploy-app.sh first."
    exit 1
fi

echo "=== Project Sentinel -- Service Setup ==="

# --- Step 1: systemd service --------------------------------------------------

echo "[1/5] Installing systemd service..."
sudo cp "$DEPLOY_DIR/configs/sentinel.service" /etc/systemd/system/sentinel.service
sudo systemctl daemon-reload
sudo systemctl enable sentinel
echo "  Service installed and enabled (will start on boot)."

# Verify sandbox score
echo "  Checking sandbox score..."
SCORE=$(sudo systemd-analyze security sentinel.service 2>/dev/null | tail -1 | grep -oP '[\d.]+' || echo "?")
echo "  Exposure score: $SCORE (aim for under 4.0)"

# --- Step 2: Log rotation -----------------------------------------------------

echo "[2/5] Configuring log rotation..."
sudo cp "$DEPLOY_DIR/configs/sentinel-logrotate" /etc/logrotate.d/sentinel
echo "  Logrotate configured (daily, 14 days retention)."

# --- Step 3: journald retention ------------------------------------------------

echo "[3/5] Configuring journald retention..."
if ! grep -q "SystemMaxUse=500M" /etc/systemd/journald.conf 2>/dev/null; then
    sudo bash -c 'cat >> /etc/systemd/journald.conf << EOF

# Project Sentinel -- limit journal size
SystemMaxUse=500M
MaxRetentionSec=30day
EOF'
    sudo systemctl restart systemd-journald
    echo "  journald limited to 500MB / 30 days."
else
    echo "  journald already configured."
fi

# --- Step 4: Health check cron ------------------------------------------------

echo "[4/5] Setting up health check cron..."
chmod +x "$DEPLOY_DIR/scripts/check-health.sh"
cp "$DEPLOY_DIR/scripts/check-health.sh" /home/deploy/check-health.sh

# Install cron jobs (replace existing sentinel crons to avoid duplicates)
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'check-health.sh' | grep -v 'backup-db.sh' > "$CRON_TMP" || true
cat >> "$CRON_TMP" << 'CRONEOF'
# Project Sentinel -- health check every 30 min
*/30 * * * * /home/deploy/check-health.sh 2>&1 | logger -t sentinel-health
CRONEOF
echo "  Health check cron installed (every 30 min, alerts via SMS)."

# --- Step 5: Database backup cron ---------------------------------------------

echo "[5/5] Setting up database backup cron..."
chmod +x "$DEPLOY_DIR/scripts/backup-db.sh"
cp "$DEPLOY_DIR/scripts/backup-db.sh" /home/deploy/backup-db.sh

cat >> "$CRON_TMP" << 'CRONEOF'
# Project Sentinel -- daily database backup at 03:00
0 3 * * * /home/deploy/backup-db.sh 2>&1 | logger -t sentinel-backup
CRONEOF

crontab "$CRON_TMP"
rm -f "$CRON_TMP"
echo "  Database backup cron installed (daily at 03:00)."

# --- Start the service --------------------------------------------------------

echo ""
read -p "Start sentinel service now? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl start sentinel
    sleep 2
    if sudo systemctl is-active --quiet sentinel; then
        echo "  Sentinel is RUNNING."
        echo ""
        sudo systemctl status sentinel --no-pager
    else
        echo "  WARNING: Sentinel failed to start. Check logs:"
        echo "    sudo journalctl -u sentinel --since '1 minute ago'"
    fi
else
    echo "  Skipped. Start manually with: sudo systemctl start sentinel"
fi

echo ""
echo "=== Service setup complete ==="
echo ""
echo "Useful commands:"
echo "  sudo systemctl status sentinel     -- check status"
echo "  sudo systemctl restart sentinel    -- restart after changes"
echo "  sudo journalctl -u sentinel -f     -- follow live logs"
echo "  sudo journalctl -u sentinel --since '1 hour ago'  -- recent logs"
echo "  sudo systemd-analyze security sentinel.service    -- check sandbox score"
