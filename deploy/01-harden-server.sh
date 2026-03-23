#!/bin/bash
# =============================================================================
# Project Sentinel -- Server Hardening Script
# =============================================================================
# Run as: root (first and last time you'll use root)
# Tested on: Ubuntu 24.04
#
# This script:
#   1. Creates the 'sentinel' user with sudo
#   2. Copies root's SSH key to the new user
#   3. Installs and configures UFW, fail2ban, AIDE
#   4. Applies kernel/network hardening
#   5. Enables automatic security updates
#   6. Disables unnecessary services
#   7. Hardens SSH (LAST -- so we don't lock ourselves out mid-script)
#
# After running:
#   - Test SSH in a NEW terminal: ssh -p 2222 sentinel@<server-ip>
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

echo "[1/9] Updating system packages..."
apt update && apt upgrade -y
apt install -y curl wget gnupg2 software-properties-common python3 python3-pip python3-venv git sqlite3

# --- Step 2: Create sentinel user ---------------------------------------------

echo "[2/9] Creating sentinel user..."
if id "sentinel" &>/dev/null; then
    echo "  User 'sentinel' already exists, skipping."
else
    adduser --disabled-password --gecos "Project Sentinel" sentinel
    echo "sentinel:$(openssl rand -base64 32)" | chpasswd
    usermod -aG sudo sentinel
    echo "  User created. Random password set (you'll use SSH keys, not password)."
fi

# Copy SSH keys from root
mkdir -p /home/sentinel/.ssh
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys /home/sentinel/.ssh/
    chown -R sentinel:sentinel /home/sentinel/.ssh
    chmod 700 /home/sentinel/.ssh
    chmod 600 /home/sentinel/.ssh/authorized_keys
    echo "  SSH keys copied from root."
else
    echo "  WARNING: /root/.ssh/authorized_keys not found."
    echo "  You'll need to manually add your SSH public key to /home/sentinel/.ssh/authorized_keys"
fi

# --- Step 3: Firewall (UFW) ---------------------------------------------------

echo "[3/9] Configuring firewall (UFW)..."
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow "$SSH_PORT/tcp" comment 'SSH'
echo "y" | ufw enable
echo "  Firewall active. Only port $SSH_PORT/tcp allowed inbound."

# --- Step 4: Fail2ban ---------------------------------------------------------

echo "[4/9] Installing and configuring fail2ban..."
apt install -y fail2ban

# Substitute the SSH port into the config
sed "s/port = 2222/port = $SSH_PORT/" "$DEPLOY_DIR/configs/fail2ban-jail.local" \
    > /etc/fail2ban/jail.local

systemctl enable fail2ban
systemctl restart fail2ban
echo "  Fail2ban active, monitoring SSH on port $SSH_PORT."

# --- Step 5: Kernel/network hardening -----------------------------------------

echo "[5/9] Applying kernel and network hardening (sysctl)..."
cp "$DEPLOY_DIR/configs/sysctl-hardening.conf" /etc/sysctl.d/99-sentinel-hardening.conf
sysctl --system > /dev/null 2>&1
echo "  sysctl hardening applied."

# --- Step 6: Automatic security updates ----------------------------------------

echo "[6/9] Enabling automatic security updates..."
apt install -y unattended-upgrades apt-listchanges
# Enable non-interactively
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'APTEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APTEOF
echo "  Automatic security updates enabled."

# --- Step 7: Disable unnecessary services --------------------------------------

echo "[7/9] Disabling unnecessary services..."
for svc in snapd.service snapd.socket ModemManager.service cups.service avahi-daemon.service bluetooth.service; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl disable --now "$svc" 2>/dev/null && echo "  Disabled: $svc"
    fi
done

# --- Step 8: File permissions and AIDE ----------------------------------------

echo "[8/9] Hardening permissions and installing AIDE..."
chmod 750 /home/sentinel
echo "sentinel" > /etc/cron.allow 2>/dev/null || true
echo "sentinel" > /etc/at.allow 2>/dev/null || true

apt install -y aide
aideinit 2>/dev/null || true
if [ -f /var/lib/aide/aide.db.new ]; then
    cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db
fi
echo "  AIDE initialized."

# --- Step 9: SSH hardening (LAST!) --------------------------------------------

echo "[9/9] Hardening SSH configuration..."
echo ""
echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "  !!  DO NOT CLOSE THIS TERMINAL SESSION                 !!"
echo "  !!  After this step, test SSH in a NEW terminal:       !!"
echo "  !!    ssh -p $SSH_PORT sentinel@<server-ip>             !!"
echo "  !!  Only close this session after confirming it works.  !!"
echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""

cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

# Write the hardened config (expand SSH_PORT variable)
export SSH_PORT
envsubst < "$DEPLOY_DIR/configs/sshd_config" > /etc/ssh/sshd_config

# Validate before restarting
if sshd -t; then
    systemctl restart sshd
    echo "  SSH hardened and restarted on port $SSH_PORT."
else
    echo "  ERROR: SSH config validation failed. Restoring backup."
    cp /etc/ssh/sshd_config.backup /etc/ssh/sshd_config
    exit 1
fi

# --- Done ---------------------------------------------------------------------

echo ""
echo "=== Hardening complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Open a NEW terminal and test:  ssh -p $SSH_PORT sentinel@<server-ip>"
echo "  2. Verify sudo works:             sudo whoami  (should print 'root')"
echo "  3. Only then close this root session."
echo "  4. Run 02-deploy-app.sh as the sentinel user."
echo ""
echo "If you get locked out: use Hetzner Cloud Console to fix /etc/ssh/sshd_config"
echo "Backup saved at: /etc/ssh/sshd_config.backup"
