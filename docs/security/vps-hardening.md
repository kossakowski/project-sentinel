# VPS Security Hardening Guide

## When to Do This

**Immediately after VPS creation, BEFORE deploying anything.** The correct order is:

1. Create VPS
2. Complete this entire guide
3. Reboot and verify everything works
4. Only then deploy the application (Phase 7)

Automated bots scan new IPs within minutes. Every step below should be done in your first SSH session.

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

## Step 2: Create a Non-Root User

Never run services as root. Create a dedicated user.

```bash
# Create user
adduser sentinel
# (set a strong password -- you'll disable password login later, but it's needed for sudo)

# Grant sudo access
usermod -aG sudo sentinel
```

---

## Step 3: SSH Hardening

This is the single most important step. SSH is the #1 attack vector on any VPS.

### 3a: Copy SSH Key to New User

```bash
# Still logged in as root:
mkdir -p /home/sentinel/.ssh
cp ~/.ssh/authorized_keys /home/sentinel/.ssh/
chown -R sentinel:sentinel /home/sentinel/.ssh
chmod 700 /home/sentinel/.ssh
chmod 600 /home/sentinel/.ssh/authorized_keys
```

### 3b: Test the New User Login (BEFORE Locking Root)

**Critical:** Open a NEW terminal window and verify you can log in as the new user before changing SSH config. If you lock yourself out, you'll need VPS console access to recover.

```bash
# In a NEW terminal:
ssh sentinel@<server-ip>
sudo whoami  # should print "root"
```

Only proceed if this works.

### 3c: Harden SSH Configuration

```bash
# Back in the root session:
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup
nano /etc/ssh/sshd_config
```

Find and change (or add) these lines:

```
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

# Only allow your specific user
AllowUsers sentinel

# Disable unused authentication methods
ChallengeResponseAuthentication no
KerberosAuthentication no
GSSAPIAuthentication no
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
ssh -p 2222 sentinel@<server-ip>

# This should FAIL:
ssh -p 2222 root@<server-ip>

# This should FAIL (old port):
ssh sentinel@<server-ip>
```

Only close the root session after confirming the new login works.

---

## Step 4: Firewall (UFW)

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
# Restrict cron to the sentinel user only
sudo bash -c 'echo "sentinel" > /etc/cron.allow'

# Restrict at to the sentinel user only
sudo bash -c 'echo "sentinel" > /etc/at.allow'

# Secure the home directory
chmod 750 /home/sentinel

# Secure SSH directory
chmod 700 /home/sentinel/.ssh
chmod 600 /home/sentinel/.ssh/authorized_keys
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
ssh -p 2222 sentinel@<server-ip>

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
```

---

## Post-Hardening Checklist

Run through this checklist before proceeding to application deployment:

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Root SSH disabled | `ssh root@<ip> -p 2222` | Connection refused / denied |
| 2 | Password auth disabled | `ssh -o PasswordAuthentication=yes sentinel@<ip> -p 2222` | Permission denied |
| 3 | Old SSH port closed | `ssh sentinel@<ip> -p 22` | Connection refused |
| 4 | UFW active, only SSH open | `sudo ufw status` | 2222/tcp ALLOW |
| 5 | Fail2ban monitoring SSH | `sudo fail2ban-client status sshd` | Shows active jail |
| 6 | Auto-updates enabled | `sudo systemctl status unattended-upgrades` | Active |
| 7 | Sysctl hardening applied | `sudo sysctl net.ipv4.conf.all.rp_filter` | = 1 |
| 8 | Non-root user has sudo | `sudo whoami` | root |
| 9 | No unnecessary services | `sudo systemctl list-units --type=service --state=running` | Minimal list |
| 10 | AIDE database initialized | `sudo aide --check` | No unexpected changes |

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

### After Every `apt upgrade`

- Update AIDE database (so it doesn't flag legitimate updates as intrusions)

---

## Emergency: Locked Out?

If you lock yourself out of SSH:

1. **Hetzner Cloud Console** -- go to the Hetzner dashboard, select your server, click "Console". This gives you direct access regardless of SSH config.
2. **Rescue Mode** -- Hetzner lets you boot into a rescue system to fix config files.
3. From rescue/console, fix `/etc/ssh/sshd_config` and restart sshd.

**Tip:** Before making SSH config changes, always keep at least one existing session open as a safety net.
