# VPS Security Hardening Guide

## When to Do This

**Immediately after VPS creation, BEFORE deploying anything.** The correct order is:

1. Create VPS + configure Hetzner Cloud Firewall
2. Complete this entire guide
3. Reboot and verify everything works
4. Only then deploy the application (Phase 7)

Automated bots scan new IPs within minutes. Every step below should be done in your first SSH session.

---

## Step 0: Hetzner Cloud Firewall

Configure a provider-level firewall **before your first SSH login**. This works at the hypervisor level -- even if UFW or sshd is misconfigured, this firewall still blocks traffic.

1. In [Hetzner Cloud Console](https://console.hetzner.cloud), go to **Firewalls** → **Create Firewall**
2. Name it `sentinel-fw`
3. Add **inbound rules**:
   | Protocol | Port | Source IPs | Description |
   |----------|------|-----------|-------------|
   | TCP | 2222 | `<your-admin-ip>/32` | SSH from admin IP only |
4. **Outbound rules**: leave default (allow all) -- Sentinel only makes outbound connections
5. Apply the firewall to your server

> **Tip:** If your home IP is dynamic, use a small CIDR range (e.g., `<your-ip-prefix>.0/24`) or update the rule when your IP changes. You can also add a second source IP entry if you SSH from multiple locations.

> **Fallback:** If you get locked out because your IP changed, use the Hetzner web console (browser-based) to access the server and update the firewall rule.

---

## Step 1: First Login and System Update

```bash
# SSH in as root (the only time you'll use root directly)
ssh root@<server-ip>

# Update everything immediately
apt update && apt upgrade -y

# Install essential tools
apt install -y curl wget gnupg2 software-properties-common
```

---

## Step 2: Create Users

Two separate users provide privilege separation: a compromise of the daemon process does not give the attacker sudo, SSH access, or the ability to modify the codebase.

```bash
# --- Admin user: SSH access, sudo, manages the repo and deploys updates ---
adduser deploy
# (set a strong password -- needed for sudo, but password SSH login is disabled later)

usermod -aG sudo deploy

# --- Service user: runs the daemon only, no login shell, no sudo ---
adduser --system --group --home /var/lib/sentinel --shell /usr/sbin/nologin sentinel

# Create state and log directories owned by the service user
mkdir -p /var/lib/sentinel /var/log/sentinel
chown sentinel:sentinel /var/lib/sentinel /var/log/sentinel
chmod 750 /var/lib/sentinel /var/log/sentinel

# Add deploy to the sentinel group (allows deploy to read state files for health checks)
usermod -aG sentinel deploy

# Create config/secrets directory
mkdir -p /etc/sentinel
chmod 700 /etc/sentinel
```

---

## Step 3: SSH Hardening

This is the single most important step. SSH is the #1 attack vector on any VPS.

### 3a: Set Up SSH Key for Admin User

If you don't already have an ed25519 key on your **local machine**, generate one:

```bash
# On your LOCAL machine:
ssh-keygen -t ed25519 -a 100 -C "sentinel-vps"
```

> **Why ed25519?** Shorter keys, faster operations, and no known weak-parameter risks (unlike certain RSA or ECDSA configurations). If you already have an RSA-4096 key, it's fine to keep using it.

Copy the key to the server:

```bash
# Still logged in as root on the server:
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

### 3b: Test the New User Login (BEFORE Locking Root)

**Critical:** Open a NEW terminal window and verify you can log in as the new user before changing SSH config. If you lock yourself out, you'll need the Hetzner web console to recover.

```bash
# In a NEW terminal:
ssh deploy@<server-ip>
sudo whoami  # should print "root"
```

Only proceed if this works.

### 3c: Harden SSH Configuration

Ubuntu 24.04 supports drop-in config snippets via `/etc/ssh/sshd_config.d/`. Use a snippet instead of editing the main config -- it's cleaner and survives package upgrades.

```bash
# Back in the root session:
cat > /etc/ssh/sshd_config.d/99-sentinel-hardening.conf << 'EOF'
# Change default port (pick any unused port between 1024-65535)
Port 2222

# Disable root login entirely
PermitRootLogin no

# Disable password authentication (key-only)
PasswordAuthentication no

# Disable empty passwords
PermitEmptyPasswords no

# Disable X11 forwarding (not needed for a server)
X11Forwarding no

# Limit authentication attempts per connection
MaxAuthTries 3

# Disconnect idle sessions after 5 minutes
ClientAliveInterval 300
ClientAliveCountMax 2

# Only allow the admin user (service user has no shell and cannot SSH)
AllowUsers deploy

# Disable unused authentication methods
KbdInteractiveAuthentication no
KerberosAuthentication no
GSSAPIAuthentication no
EOF
```

### 3d: Validate and Restart SSH

```bash
# Test config is valid BEFORE restarting (critical!)
sshd -t

# If no errors:
systemctl restart sshd
```

### 3e: Test Again

**Do NOT close your current session.** Open a new terminal:

```bash
# This should work:
ssh -p 2222 deploy@<server-ip>

# This should FAIL:
ssh -p 2222 root@<server-ip>

# This should FAIL (old port):
ssh deploy@<server-ip>
```

Only close the root session after confirming the new login works.

---

## Step 4: Firewall (UFW)

UFW provides a host-level firewall as a second layer behind the Hetzner Cloud Firewall.

```bash
# Install ufw (usually pre-installed on Ubuntu)
sudo apt install -y ufw

# Set defaults: deny all incoming, allow all outgoing
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow your custom SSH port (MUST match what you set in sshd_config)
sudo ufw allow 2222/tcp comment 'SSH'

# DO NOT allow port 22 -- that's the old default

# Enable the firewall
sudo ufw enable

# Verify
sudo ufw status verbose
```

Expected output should show only port 2222/tcp allowed incoming.

### What About Other Ports?

Project Sentinel is an **outbound-only** system -- it fetches RSS/Telegram and makes Twilio calls. It does not need any incoming ports besides SSH. Do NOT open ports 80, 443, or anything else unless you add a web dashboard later.

If you ever need to temporarily open a port:

```bash
sudo ufw allow <port>/tcp comment 'reason'
# ... do your work ...
sudo ufw delete allow <port>/tcp
```

---

## Step 5: Fail2ban

Fail2ban monitors log files and bans IPs that show malicious behavior.

```bash
sudo apt install -y fail2ban
```

### Configure Fail2ban

```bash
# Never edit jail.conf directly -- it gets overwritten on updates
sudo nano /etc/fail2ban/jail.local
```

```ini
[DEFAULT]
# Ban for 1 hour after 3 failures
bantime = 3600
findtime = 600
maxretry = 3

# Use more aggressive banning for repeat offenders
bantime.increment = true
bantime.factor = 2
bantime.maxtime = 604800

# Email notifications (optional -- requires mailutils)
# destemail = your@email.com
# sender = fail2ban@sentinel
# action = %(action_mwl)s

[sshd]
enabled = true
port = 2222
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400
```

```bash
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban

# Verify it's running and monitoring SSH
sudo fail2ban-client status
sudo fail2ban-client status sshd
```

### Useful Fail2ban Commands

```bash
# Check banned IPs
sudo fail2ban-client status sshd

# Manually unban an IP (if you lock yourself out)
sudo fail2ban-client set sshd unbanip <ip-address>

# View fail2ban log
sudo tail -f /var/log/fail2ban.log
```

---

## Step 6: Automatic Security Updates

```bash
sudo apt install -y unattended-upgrades apt-listchanges

# Enable automatic security updates
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

### Configure What Gets Updated

```bash
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```

Ensure these lines are uncommented:

```
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

// Auto-reboot if a kernel update requires it (at 4 AM)
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";

// Remove unused dependencies
Unattended-Upgrade::Remove-Unused-Dependencies "true";
```

### Enable the Update Timer

```bash
sudo nano /etc/apt/apt.conf.d/20auto-upgrades
```

```
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
```

```bash
# Verify it's active
sudo systemctl status unattended-upgrades
```

---

## Step 7: Kernel and Network Hardening (sysctl)

These settings harden the network stack against common attacks.

```bash
sudo nano /etc/sysctl.d/99-sentinel-hardening.conf
```

```ini
# Prevent IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Ignore ICMP redirects (prevents MITM)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Ignore ICMP broadcasts (prevents Smurf attacks)
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Log suspicious packets
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# Disable source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# SYN flood protection
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2

# Disable IPv6 if not needed (reduces attack surface)
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
```

```bash
# Apply immediately
sudo sysctl --system

# Verify a few settings
sudo sysctl net.ipv4.tcp_syncookies
sudo sysctl net.ipv4.conf.all.rp_filter
```

---

## Step 8: Disable Unnecessary Services

```bash
# List all running services
sudo systemctl list-units --type=service --state=running

# Disable anything you don't need. Common ones to disable on a minimal VPS:
sudo systemctl disable --now snapd.service 2>/dev/null
sudo systemctl disable --now snapd.socket 2>/dev/null
sudo systemctl disable --now ModemManager.service 2>/dev/null
sudo systemctl disable --now cups.service 2>/dev/null
sudo systemctl disable --now avahi-daemon.service 2>/dev/null
sudo systemctl disable --now bluetooth.service 2>/dev/null
```

---

## Step 9: File Permission Hardening

```bash
# Restrict cron to the admin user only (service user has no shell and doesn't need cron)
sudo bash -c 'echo "deploy" > /etc/cron.allow'

# Restrict at to the admin user only
sudo bash -c 'echo "deploy" > /etc/at.allow'

# Secure the admin home directory
chmod 750 /home/deploy

# Secure SSH directory
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

---

## Step 10: Intrusion Detection with AIDE

AIDE (Advanced Intrusion Detection Environment) monitors files for unauthorized changes.

```bash
sudo apt install -y aide

# Initialize the database (takes a few minutes)
sudo aideinit

# Move the new database into place
sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db

# Run a check (should show no changes)
sudo aide --check
```

### Schedule Daily Checks

```bash
sudo nano /etc/cron.daily/aide-check
```

```bash
#!/bin/bash
/usr/bin/aide --check > /var/log/aide-check.log 2>&1
if [ $? -ne 0 ]; then
    echo "AIDE detected file changes on sentinel server" | \
    mail -s "AIDE Alert: File Integrity Change" your@email.com 2>/dev/null
fi
```

```bash
sudo chmod +x /etc/cron.daily/aide-check
```

> **Note:** After legitimate system updates, you need to update the AIDE database:
> ```bash
> sudo aide --update
> sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db
> ```

---

## Step 11: Login Notifications

Get notified whenever someone logs into your server.

```bash
sudo nano /etc/profile.d/ssh-login-notify.sh
```

```bash
#!/bin/bash
# Send a notification on SSH login
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')
    logger -t ssh-login "SSH login by $(whoami) from $IP at $TIMESTAMP"

    # Optional: send a Telegram/SMS notification here
    # curl -s "https://api.telegram.org/bot<token>/sendMessage" \
    #   -d "chat_id=<chat_id>" \
    #   -d "text=SSH login on sentinel: $(whoami) from $IP at $TIMESTAMP"
fi
```

```bash
sudo chmod +x /etc/profile.d/ssh-login-notify.sh
```

---

## Step 12: Reboot and Final Verification

```bash
sudo reboot
```

After reboot, verify everything survived:

```bash
# Log in with new SSH config
ssh -p 2222 deploy@<server-ip>

# Verify firewall is active
sudo ufw status

# Verify fail2ban is running
sudo fail2ban-client status sshd

# Verify sysctl settings persisted
sudo sysctl net.ipv4.tcp_syncookies

# Verify unattended-upgrades is active
sudo systemctl status unattended-upgrades

# Verify AIDE is installed
sudo aide --check

# Verify service user cannot log in
sudo -u sentinel bash 2>&1 | head -1
# Expected: "This account is currently not available."
```

---

## Post-Hardening Checklist

Run through this checklist before proceeding to application deployment:

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Hetzner Cloud Firewall active | Hetzner Console → Firewalls | `sentinel-fw` applied, only 2222/tcp from admin IP |
| 2 | Root SSH disabled | `ssh root@<ip> -p 2222` | Connection refused / denied |
| 3 | Password auth disabled | `ssh -o PasswordAuthentication=yes deploy@<ip> -p 2222` | Permission denied |
| 4 | Old SSH port closed | `ssh deploy@<ip> -p 22` | Connection refused |
| 5 | UFW active, only SSH open | `sudo ufw status` | 2222/tcp ALLOW |
| 6 | Fail2ban monitoring SSH | `sudo fail2ban-client status sshd` | Shows active jail |
| 7 | Auto-updates enabled | `sudo systemctl status unattended-upgrades` | Active |
| 8 | Sysctl hardening applied | `sudo sysctl net.ipv4.conf.all.rp_filter` | = 1 |
| 9 | Admin user has sudo | `sudo whoami` | root |
| 10 | Service user has no shell | `sudo -u sentinel bash` | "This account is currently not available" |
| 11 | No unnecessary services | `sudo systemctl list-units --type=service --state=running` | Minimal list |
| 12 | AIDE database initialized | `sudo aide --check` | No unexpected changes |

---

## Ongoing Maintenance

### Weekly

- Review auth log for suspicious activity: `sudo journalctl -u sshd --since "7 days ago" | tail -50`
- Check fail2ban bans: `sudo fail2ban-client status sshd`

### Monthly

- Review and remove old SSH keys if any were added
- Check for new CVEs affecting your Ubuntu version
- Review running services: `sudo systemctl list-units --type=service --state=running`
- Update AIDE database after legitimate changes: `sudo aide --update && sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db`
- Verify Hetzner Cloud Firewall rules still match your admin IP(s)

### After Every `apt upgrade`

- Update AIDE database (so it doesn't flag legitimate updates as intrusions)

---

## Emergency: Locked Out?

If you lock yourself out of SSH:

1. **Hetzner Cloud Console** -- go to the Hetzner dashboard, select your server, click "Console". This gives you direct access regardless of SSH config or Cloud Firewall rules.
2. **Rescue Mode** -- Hetzner lets you boot into a rescue system to fix config files.
3. From rescue/console, fix `/etc/ssh/sshd_config.d/99-sentinel-hardening.conf` and restart sshd.
4. If locked out by the Cloud Firewall, update the firewall rules in the Hetzner Console web UI -- no SSH needed.

**Tip:** Before making SSH config changes, always keep at least one existing session open as a safety net.
