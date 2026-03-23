#!/bin/bash
# =============================================================================
# Project Sentinel -- Server Hardening Script
# =============================================================================
# Run as: root (first and last time you'll use root)
# Tested on: Ubuntu 24.04
#
# This script:
#   1. Creates 'deploy' admin user (SSH, sudo) and 'sentinel' service user (no login, no sudo)
#   2. Copies root's SSH key to the admin user
#   3. Creates FHS directories (/etc/sentinel, /var/lib/sentinel, /var/log/sentinel)
#   4. Installs and configures UFW, fail2ban, AIDE
#   5. Applies kernel/network hardening
#   6. Enables automatic security updates
#   7. Disables unnecessary services
#   8. Hardens SSH via sshd_config.d snippet (LAST -- so we don't lock ourselves out)
#
# Before running:
#   - Set up Hetzner Cloud Firewall in the web console (see docs/security/vps-hardening.md Step 0)
#
# After running:
#   - Test SSH in a NEW terminal: ssh -p 2222 deploy@<server-ip>
#   - Do NOT close this session until you confirm the new login works
# =============================================================================

set -euo pipefail

SSH_PORT="${SSH_PORT:-2222}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Preflight checks --------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root."
    exit 1
fi

if [ ! -f "$DEPLOY_DIR/configs/sysctl-hardening.conf" ]; then
    echo "ERROR: Cannot find configs/ directory. Run this script from the deploy/ folder."
    exit 1
fi

echo "=== Project Sentinel -- Server Hardening ==="
echo "SSH port will be set to: $SSH_PORT"
echo ""

# --- Step 1: System update ----------------------------------------------------

echo "[1/10] Updating system packages..."
apt update && apt upgrade -y
apt install -y curl wget gnupg2 software-properties-common python3 python3-pip python3-venv git sqlite3

# --- Step 2: Create admin user ------------------------------------------------

echo "[2/10] Creating admin user (deploy)..."
if id "deploy" &>/dev/null; then
    echo "  User 'deploy' already exists, skipping."
else
    adduser --disabled-password --gecos "Sentinel Admin" deploy
    echo "deploy:$(openssl rand -base64 32)" | chpasswd
    usermod -aG sudo deploy
    echo "  Admin user created. Random password set (SSH key auth only)."
fi

# Copy SSH keys from root
mkdir -p /home/deploy/.ssh
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys /home/deploy/.ssh/
    chown -R deploy:deploy /home/deploy/.ssh
    chmod 700 /home/deploy/.ssh
    chmod 600 /home/deploy/.ssh/authorized_keys
    echo "  SSH keys copied from root."
else
    echo "  WARNING: /root/.ssh/authorized_keys not found."
    echo "  You'll need to manually add your SSH public key to /home/deploy/.ssh/authorized_keys"
fi

# --- Step 3: Create service user ----------------------------------------------

echo "[3/10] Creating service user (sentinel)..."
if id "sentinel" &>/dev/null; then
    echo "  User 'sentinel' already exists, skipping."
else
    adduser --system --group --home /var/lib/sentinel --shell /usr/sbin/nologin sentinel
    echo "  Service user created (no login shell, no sudo)."
fi

# Add deploy to sentinel group (allows reading state files for health checks)
usermod -aG sentinel deploy

# --- Step 4: Create FHS directories ------------------------------------------

echo "[4/10] Creating application directories..."
mkdir -p /var/lib/sentinel /var/log/sentinel /etc/sentinel
chown sentinel:sentinel /var/lib/sentinel /var/log/sentinel
chmod 750 /var/lib/sentinel /var/log/sentinel
chmod 700 /etc/sentinel
echo "  /var/lib/sentinel  -- state data (DB, Telegram session)"
echo "  /var/log/sentinel  -- application logs"
echo "  /etc/sentinel      -- config and secrets"

# --- Step 5: Firewall (UFW) ---------------------------------------------------

echo "[5/10] Configuring firewall (UFW)..."
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow "$SSH_PORT/tcp" comment 'SSH'
echo "y" | ufw enable
echo "  Firewall active. Only port $SSH_PORT/tcp allowed inbound."

# --- Step 6: Fail2ban ---------------------------------------------------------

echo "[6/10] Installing and configuring fail2ban..."
apt install -y fail2ban

# Substitute the SSH port into the config
sed "s/port = 2222/port = $SSH_PORT/" "$DEPLOY_DIR/configs/fail2ban-jail.local" \
    > /etc/fail2ban/jail.local

systemctl enable fail2ban
systemctl restart fail2ban
echo "  Fail2ban active, monitoring SSH on port $SSH_PORT."

# --- Step 7: Kernel/network hardening -----------------------------------------

echo "[7/10] Applying kernel and network hardening (sysctl)..."
cp "$DEPLOY_DIR/configs/sysctl-hardening.conf" /etc/sysctl.d/99-sentinel-hardening.conf
sysctl --system > /dev/null 2>&1
echo "  sysctl hardening applied."

# --- Step 8: Automatic security updates ----------------------------------------

echo "[8/10] Enabling automatic security updates..."
apt install -y unattended-upgrades apt-listchanges
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'APTEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APTEOF
echo "  Automatic security updates enabled."

# --- Step 9: Disable unnecessary services & harden permissions ----------------

echo "[9/10] Disabling unnecessary services and hardening permissions..."
for svc in snapd.service snapd.socket ModemManager.service cups.service avahi-daemon.service bluetooth.service; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl disable --now "$svc" 2>/dev/null && echo "  Disabled: $svc"
    fi
done

chmod 750 /home/deploy
echo "deploy" > /etc/cron.allow 2>/dev/null || true
echo "deploy" > /etc/at.allow 2>/dev/null || true

apt install -y aide
aideinit 2>/dev/null || true
if [ -f /var/lib/aide/aide.db.new ]; then
    cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db
fi
echo "  AIDE initialized."

# --- Step 10: SSH hardening (LAST!) -------------------------------------------

echo "[10/10] Hardening SSH configuration..."
echo ""
echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "  !!  DO NOT CLOSE THIS TERMINAL SESSION                 !!"
echo "  !!  After this step, test SSH in a NEW terminal:       !!"
echo "  !!    ssh -p $SSH_PORT deploy@<server-ip>               !!"
echo "  !!  Only close this session after confirming it works.  !!"
echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""

# Use sshd_config.d drop-in snippet (survives package upgrades)
export SSH_PORT
envsubst < "$DEPLOY_DIR/configs/sshd_config" > /etc/ssh/sshd_config.d/99-sentinel-hardening.conf

# Validate before restarting
if sshd -t; then
    systemctl restart sshd
    echo "  SSH hardened and restarted on port $SSH_PORT."
else
    echo "  ERROR: SSH config validation failed. Removing snippet."
    rm -f /etc/ssh/sshd_config.d/99-sentinel-hardening.conf
    exit 1
fi

# --- Done ---------------------------------------------------------------------

echo ""
echo "=== Hardening complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Open a NEW terminal and test:  ssh -p $SSH_PORT deploy@<server-ip>"
echo "  2. Verify sudo works:             sudo whoami  (should print 'root')"
echo "  3. Verify service user:           sudo -u sentinel bash  (should say 'not available')"
echo "  4. Only then close this root session."
echo "  5. Run 02-deploy-app.sh as the deploy user."
echo ""
echo "If you get locked out: use Hetzner Cloud Console to fix /etc/ssh/sshd_config.d/99-sentinel-hardening.conf"
