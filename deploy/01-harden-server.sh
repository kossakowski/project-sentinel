#!/bin/bash
# =============================================================================
# Project Sentinel -- Server Hardening Script
# =============================================================================
# Run as: root (first and last time you'll use root)
# Tested on: Ubuntu 24.04 (Hetzner CX-series)
#
# This script:
#   1. Creates 'deploy' admin user (SSH, sudo) and 'sentinel' service user (no login, no sudo)
#   2. Copies root's SSH key to the admin user
#   3. Creates FHS directories (/etc/sentinel, /var/lib/sentinel, /var/log/sentinel)
#   4. Installs and configures UFW, fail2ban
#   5. Applies kernel/network hardening
#   6. Enables automatic security updates
#   7. Disables unnecessary services
#   8. Hardens SSH via sshd_config.d snippet (LAST -- so we don't lock ourselves out)
#
# Designed to be run non-interactively over SSH.
# All output is logged to /var/log/sentinel-hardening.log
# =============================================================================

# --- Environment: suppress ALL interactive prompts ----------------------------
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

SSH_PORT="${SSH_PORT:-2222}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/var/log/sentinel-hardening.log"

# Log everything to file AND stdout
exec > >(tee -a "$LOG") 2>&1

# --- Helper: exit on critical failure, warn on non-critical -------------------
die()  { echo "FATAL: $1"; exit 1; }
warn() { echo "  WARNING: $1 (non-critical, continuing)"; }

# --- Preflight checks --------------------------------------------------------

[ "$(id -u)" -eq 0 ] || die "This script must be run as root."
[ -f "$DEPLOY_DIR/configs/sysctl-hardening.conf" ] || die "Cannot find configs/ directory."

echo "=== Project Sentinel -- Server Hardening ==="
echo "SSH port will be set to: $SSH_PORT"
echo "Log file: $LOG"
echo "Started at: $(date)"
echo ""

# --- Step 1: System update ----------------------------------------------------

echo "[1/10] Updating system packages..."
apt-get update -qq || die "apt-get update failed"
apt-get upgrade -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" || die "apt-get upgrade failed"
apt-get install -y -qq curl wget gnupg2 software-properties-common python3 python3-pip python3-venv git sqlite3 gettext-base || die "apt-get install failed"
echo "  System updated and base packages installed."

# --- Step 2: Create admin user ------------------------------------------------

echo "[2/10] Creating admin user (deploy)..."
if id "deploy" &>/dev/null; then
    echo "  User 'deploy' already exists, skipping."
else
    adduser --disabled-password --gecos "Sentinel Admin" deploy || die "Failed to create deploy user"
    echo "deploy:$(openssl rand -base64 32)" | chpasswd
    usermod -aG sudo deploy
    echo "  Admin user created."
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
    die "/root/.ssh/authorized_keys not found -- cannot set up SSH for deploy user."
fi

# Passwordless sudo for deploy (needed for scripts 02 and 03 over SSH)
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy
visudo -c || die "sudoers syntax error"
echo "  Passwordless sudo configured for deploy."

# --- Step 3: Create service user ----------------------------------------------

echo "[3/10] Creating service user (sentinel)..."
if id "sentinel" &>/dev/null; then
    echo "  User 'sentinel' already exists, skipping."
else
    adduser --system --group --home /var/lib/sentinel --shell /usr/sbin/nologin sentinel || die "Failed to create sentinel user"
    echo "  Service user created (no login shell, no sudo)."
fi

usermod -aG sentinel deploy
echo "  deploy added to sentinel group."

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
apt-get install -y -qq ufw
ufw --force reset >/dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH current (removed after port change)'
ufw allow "$SSH_PORT/tcp" comment 'SSH hardened'
echo "y" | ufw enable
echo "  Firewall active. Ports 22 + $SSH_PORT open (22 removed after SSH moves)."

# --- Step 6: Fail2ban ---------------------------------------------------------

echo "[6/10] Installing and configuring fail2ban..."
apt-get install -y -qq fail2ban

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
apt-get install -y -qq unattended-upgrades apt-listchanges
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
    systemctl disable --now "$svc" 2>/dev/null && echo "  Disabled: $svc" || true
done

chmod 750 /home/deploy
echo "deploy" > /etc/cron.allow 2>/dev/null || true
echo "deploy" > /etc/at.allow 2>/dev/null || true

# AIDE -- non-critical, don't let it block the deployment
echo "  Installing AIDE (intrusion detection)..."
if apt-get install -y -qq aide 2>/dev/null; then
    aideinit 2>/dev/null &
    AIDE_PID=$!
    echo "  AIDE initializing in background (PID $AIDE_PID). This takes a few minutes."
    echo "  It will finalize on its own. Not blocking on it."
else
    warn "AIDE installation failed"
fi

# --- Step 10: SSH hardening (LAST!) -------------------------------------------

echo "[10/10] Hardening SSH configuration..."

# Install the sshd_config.d drop-in snippet (survives package upgrades)
export SSH_PORT
envsubst '$SSH_PORT' < "$DEPLOY_DIR/configs/sshd_config" > /etc/ssh/sshd_config.d/99-sentinel-hardening.conf

# Validate BEFORE restarting
if sshd -t; then
    systemctl restart sshd
    echo "  SSH hardened and restarted on port $SSH_PORT."

    # Remove the temporary port 22 rule
    ufw --force delete allow 22/tcp
    echo "  Port 22 removed from firewall. Only $SSH_PORT remains."
else
    echo "  ERROR: SSH config validation failed. Removing snippet."
    rm -f /etc/ssh/sshd_config.d/99-sentinel-hardening.conf
    die "SSH config invalid -- removed snippet, SSH unchanged."
fi

# --- Done ---------------------------------------------------------------------

echo ""
echo "=== Hardening complete at $(date) ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Test SSH:  ssh -p $SSH_PORT deploy@<server-ip>"
echo "  2. Verify sudo works:  sudo whoami  (should print 'root')"
echo "  3. Run 02-deploy-app.sh as the deploy user."
echo ""
echo "Full log: $LOG"
echo "If locked out: Hetzner Console -> remove /etc/ssh/sshd_config.d/99-sentinel-hardening.conf"
