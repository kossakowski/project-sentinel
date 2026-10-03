# VPS Security Hardening Guide

Last verified: 2026-10-03 (deployed commit 6429124)

## Contents

- [How this guide relates to production](#how-this-guide-relates-to-production)
- [When to do this](#when-to-do-this)
- [Step 0: Hetzner Cloud Firewall](#step-0-hetzner-cloud-firewall)
- [Step 1: First Login and System Update](#step-1-first-login-and-system-update)
- [Step 2: Create Users and Directories](#step-2-create-users-and-directories)
- [Step 3: SSH Hardening](#step-3-ssh-hardening)
- [Step 4: Firewall (UFW)](#step-4-firewall-ufw)
- [Step 5: Fail2ban](#step-5-fail2ban)
- [Step 6: Automatic Security Updates](#step-6-automatic-security-updates)
- [Step 7: Kernel and Network Hardening (sysctl)](#step-7-kernel-and-network-hardening-sysctl)
- [Step 8: Disable Unnecessary Services](#step-8-disable-unnecessary-services)
- [Step 9: File Permission Hardening](#step-9-file-permission-hardening)
- [Step 10: Intrusion Detection with AIDE](#step-10-intrusion-detection-with-aide)
- [Step 11: Login Notifications (optional)](#step-11-login-notifications-optional)
- [Step 12: Reboot and Final Verification](#step-12-reboot-and-final-verification)
- [Post-Hardening Checklist](#post-hardening-checklist)
- [Service Sandbox and Log Retention](#service-sandbox-and-log-retention)
- [Ongoing Maintenance](#ongoing-maintenance)
- [Emergency: Locked Out?](#emergency-locked-out)

## How this guide relates to production

This guide is a repeatable procedure for a new server. It is not a log of what was done.

- The production server (Hetzner, Ubuntu 24.04) was hardened on 2026-03-23 by running `deploy/01-harden-server.sh` as root. The script uses the files in `deploy/configs/` and writes its output to `/var/log/sentinel-hardening.log`.
- The script and `deploy/configs/*` are the source of truth. This guide is the manual equivalent and explains each step. Where the two differ, follow the script.
- The script runs SSH hardening last. It keeps a temporary UFW rule for port 22 and deletes it only after SSH has moved to the new port, so you cannot lock yourself out halfway.

The table shows which steps the script performs and what production looks like today.

| Step | Done by `01-harden-server.sh`? | Production state (checked 2026-10-03) |
|---|---|---|
| 0. Hetzner Cloud Firewall | No (web console) | SSH port 2222 is reachable from any IP. See the note in Step 0. |
| 1. System update | Yes, and it also installs `python3`, `python3-pip`, `python3-venv`, `git`, `sqlite3`, `gettext-base` | As the script set it. |
| 2. Users and directories | Yes | As the script set it. |
| 3. SSH hardening | Yes, as the last step | As the script set it, including the `ssh.socket` override. |
| 4. UFW | Yes | Only `2222/tcp` is allowed inbound. |
| 5. Fail2ban | Yes (`jail.local`) | `jail.local` plus a hand-made `jail.d/whitelist.conf`. See Step 5. |
| 6. Automatic updates | Partly: it writes `20auto-upgrades` only | Automatic reboot is not enabled. A reboot has been pending since 2026-03. See Step 6. |
| 7. sysctl | Yes | `log_martians` is configured but runs as 0. See Step 7. |
| 8. Disable services | Yes | As the script set it. |
| 9. File permissions | Yes | As the script set it. |
| 10. AIDE | Install and first database only | The Ubuntu package timer runs daily; the baseline dates from 2026-03-23. See Step 10. |
| 11. Login notifications | No | Not deployed. |
| 12. Reboot and verify | No | Last reboot was 2026-03-24. |

The open production items above are tracked in [TODO.md](../../../TODO.md). This guide only describes them.

## When to do this

Do this right after you create the VPS and before you deploy anything. Automated bots scan new IPs within minutes.

1. Create the VPS and configure the Hetzner Cloud Firewall (Step 0).
2. Harden the server. The quick way is to copy the repo's `deploy/` folder to the server and run `sudo SSH_PORT=2222 bash deploy/01-harden-server.sh` as root. The script needs `/root/.ssh/authorized_keys`, which Hetzner creates when you add an SSH key at server creation. The manual way is Steps 1–11 below.
3. Reboot and run the [Post-Hardening Checklist](#post-hardening-checklist).
4. Deploy the application as `deploy`: run `deploy/02-deploy-app.sh`, then `deploy/03-setup-services.sh`. Later updates go through the `/deploy` skill; see [server-runbook.md](../server-runbook.md). Warning: these scripts do not yet produce a working service. Script 02 creates and uses `venv/`, while the unit installed by script 03 runs `.venv/bin/python`, and script 02 installs `config/config.example.yaml` instead of the repo's `config/config.yaml`. A rebuild also needs `/etc/sentinel/openai.env` and the `20-openai.conf` drop-in, which no script creates (see [server-runbook.md, Secrets](../server-runbook.md#secrets)). Both gaps are tracked in TODO.md §6.1.

This guide has 13 steps: Step 0 (Hetzner Cloud Firewall, done in the web console before your first SSH login) plus Steps 1–12 (run on the server). Do them in order.

---

## Step 0: Hetzner Cloud Firewall

Configure a provider-level firewall before your first SSH login. This works at the hypervisor level -- even if UFW or sshd is misconfigured, this firewall still blocks traffic.

1. In [Hetzner Cloud Console](https://console.hetzner.cloud), go to **Firewalls** → **Create Firewall**
2. Name it `sentinel-fw`
3. Add **inbound rules**:
   | Protocol | Port | Source IPs | Description |
   |----------|------|-----------|-------------|
   | TCP | 2222 | `<your-admin-ip>/32` | SSH from admin IP only |
   | TCP | 22 | `<your-admin-ip>/32` | Temporary: first login on the default port. Delete this rule after Step 3e. |
4. **Outbound rules**: leave default (allow all) -- Sentinel only makes outbound connections
5. Apply the firewall to your server

The temporary port 22 rule is needed because a fresh server runs SSH on port 22. Without it, the first login in Step 1 (or the script run) is blocked.

> **Tip:** If your home IP is dynamic, use a small CIDR range (e.g., `<your-ip-prefix>.0/24`) or update the rule when your IP changes. You can also add a second source IP entry if you SSH from multiple locations.

> **Fallback:** If you get locked out because your IP changed, use the Hetzner web console (browser-based) to access the server and update the firewall rule.

> **Production state (2026-10-03):** SSH on port 2222 accepts connections from any IP. On that day the sshd log showed login attempts from more than 100 unrelated IPs within 24 hours, and fail2ban banned many of them. Either `sentinel-fw` is not applied, or it does not restrict the source to the admin IP. This cannot be checked from the server; the owner must check it in the Hetzner console (see TODO.md). Until then, key-only SSH (Step 3) and fail2ban (Step 5) are the effective protection.

---

## Step 1: First Login and System Update

```bash
# SSH in as root (the only time you'll use root directly)
ssh root@<server-ip>

# Update everything immediately
apt update && apt upgrade -y

# Install essential tools (the script also installs python3, python3-pip,
# python3-venv, git, sqlite3 and gettext-base for the app)
apt install -y curl wget gnupg2 software-properties-common
```

---

## Step 2: Create Users and Directories

Two separate users provide privilege separation: a compromise of the daemon process does not give the attacker sudo, SSH access, or the ability to modify the codebase.

```bash
# --- Admin user: SSH access, sudo, manages the repo and deploys updates ---
adduser --disabled-password --gecos "Sentinel Admin" deploy
# Random password that nobody knows; deploy logs in with an SSH key only
echo "deploy:$(openssl rand -base64 32)" | chpasswd
usermod -aG sudo deploy

# Passwordless sudo: scripts 02 and 03 and /deploy run sudo over SSH without a terminal
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy
visudo -c   # expected: "parsed OK" for every file

# --- Service user: runs the daemon only, no login shell, no sudo ---
adduser --system --group --home /var/lib/sentinel --shell /usr/sbin/nologin sentinel

# Create state and log directories owned by the service user
mkdir -p /var/lib/sentinel /var/log/sentinel
chown sentinel:sentinel /var/lib/sentinel /var/log/sentinel
chmod 750 /var/lib/sentinel /var/log/sentinel

# Add deploy to the sentinel group (allows deploy to read state files for health checks)
usermod -aG sentinel deploy

# Create the config/secrets directory. The sentinel group must be able to enter it,
# because the service reads /etc/sentinel/config.yaml as the sentinel user.
mkdir -p /etc/sentinel
chown root:sentinel /etc/sentinel
chmod 750 /etc/sentinel
```

What this means for security:

- `deploy` has no usable password, and `sudo` never asks for one. Anyone who holds the deploy SSH private key effectively has root. Protect that key accordingly.
- `deploy/02-deploy-app.sh` later puts two files in `/etc/sentinel/`. Their owners and modes are:

| File | Owner:group | Mode | Who reads it |
|---|---|---|---|
| `/etc/sentinel/config.yaml` | `root:sentinel` | 640 | The service, as the `sentinel` user (`--config` in `ExecStart`). |
| `/etc/sentinel/sentinel.env` | `root:deploy` | 640 | systemd itself (PID 1, root) through `EnvironmentFile=`, before it drops to the `sentinel` user. The `sentinel` user never reads it. |

If `/etc/sentinel` is left as `root:root 700`, the service cannot read `config.yaml` and fails to start.

---

## Step 3: SSH Hardening

This is the single most important step. SSH is the #1 attack vector on any VPS.

### 3a: Set Up SSH Key for Admin User

The script does not ask for a key. It copies `/root/.ssh/authorized_keys` (the key you gave Hetzner at server creation) to `/home/deploy/.ssh/`. To do the same by hand: `cp /root/.ssh/authorized_keys /home/deploy/.ssh/` and then set the owner and modes shown below.

If you don't already have an ed25519 key on your **local machine**, generate one:

```bash
# On your LOCAL machine:
ssh-keygen -t ed25519 -a 100 -C "sentinel-vps"
```

> **Why ed25519?** Shorter keys, faster operations, and no known weak-parameter risks (unlike certain RSA or ECDSA configurations). If you already have an RSA-4096 key, it's fine to keep using it.

Copy the **public** key to the server. Print it on your local machine and paste it into the deploy user's `authorized_keys` (only the `.pub` file is the public key — never copy a private key or your local `authorized_keys`):

```bash
# On your LOCAL machine — show the PUBLIC key and copy the output:
cat ~/.ssh/id_ed25519.pub
```

```bash
# Still logged in as root on the server — create the deploy user's authorized_keys
# and paste the public key line you just copied:
mkdir -p /home/deploy/.ssh
echo 'ssh-ed25519 AAAA...your-public-key... sentinel-vps' > /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

`ssh-copy-id` does not work here, because `deploy` has no usable password.

### 3b: Test the New User Login (Before Locking Root)

Open a new terminal window and verify you can log in as the new user before changing the SSH config. If you lock yourself out, you'll need the Hetzner web console to recover.

```bash
# In a NEW terminal:
ssh deploy@<server-ip>
sudo whoami  # should print "root" without asking for a password
```

Only proceed if this works.

### 3c: Harden SSH Configuration

Ubuntu 24.04 supports drop-in config snippets via `/etc/ssh/sshd_config.d/`. Use a snippet instead of editing the main config -- it's cleaner and survives package upgrades. The script installs the same settings from `deploy/configs/sshd_config`.

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

### 3c-bis: Move the SSH Socket to the New Port

On Ubuntu 24.04, SSH is started by `ssh.socket` (socket activation). The socket decides the listening port, so the `Port` line above is not enough on its own. Override the socket:

```bash
# Only if the system uses socket activation:
systemctl is-enabled ssh.socket   # "enabled" means yes

mkdir -p /etc/systemd/system/ssh.socket.d
cat > /etc/systemd/system/ssh.socket.d/override.conf << 'EOF'
[Socket]
ListenStream=
ListenStream=0.0.0.0:2222
ListenStream=[::]:2222
EOF
```

The empty `ListenStream=` line clears the default port 22 before the new port is added.

### 3d: Validate and Restart SSH

```bash
# Test config is valid BEFORE restarting
sshd -t

# If no errors, on a socket-activated system (Ubuntu 24.04):
systemctl daemon-reload
systemctl restart ssh.socket

# On a system without socket activation instead:
#   systemctl restart ssh

# Verify SSH now listens on 2222
ss -tlnp | grep 2222
```

### 3e: Test Again

Do not close your current session. Open a new terminal:

```bash
# This should work:
ssh -p 2222 deploy@<server-ip>

# This should FAIL:
ssh -p 2222 root@<server-ip>

# This should FAIL (old port):
ssh deploy@<server-ip>
```

Only close the root session after confirming the new login works. Then delete the temporary port 22 rule from `sentinel-fw` (Step 0).

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

Expected output should show only port 2222/tcp allowed incoming (once for IPv4 and once for IPv6).

The script does this step before SSH hardening. It therefore also allows `22/tcp` for a while and deletes that rule once SSH has moved to 2222.

### What About Other Ports?

Project Sentinel only makes outbound connections: it fetches news and Telegram sources and calls outside services (the classifier API, Twilio, Expo push). It does not need any incoming ports besides SSH. Do not open ports 80, 443, or anything else. The dashboard is local-only and never runs on the server.

Postfix (local mail delivery) is installed on production and listens on port 25 on all interfaces. UFW blocks it from outside, so it is not exposed. Limiting it to loopback is an open item in TODO.md.

If you ever need to temporarily open a port:

```bash
sudo ufw allow <port>/tcp comment 'reason'
# ... do your work ...
sudo ufw delete allow <port>/tcp
```

---

## Step 5: Fail2ban

Fail2ban watches login failures and bans IPs that show malicious behavior.

```bash
sudo apt install -y fail2ban
```

### Configure Fail2ban

The script copies `deploy/configs/fail2ban-jail.local` to `/etc/fail2ban/jail.local`.

```bash
# Never edit jail.conf directly -- it gets overwritten on updates
sudo nano /etc/fail2ban/jail.local
```

The content is:

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

What this does for SSH, and how it works on Ubuntu 24.04:

- 3 failed logins within 10 minutes ban the source IP for 24 hours. Repeat bans double, up to 7 days.
- Ubuntu's `/etc/fail2ban/jail.d/defaults-debian.conf` sets `backend = systemd` and `banaction = nftables`. Fail2ban therefore reads the systemd journal, and the `logpath` line has no effect. Bans are applied with nftables.
- Fail2ban reads `jail.local` after `jail.d/*.conf`. A setting in `jail.local` wins over the same setting in a `jail.d/*.conf` file.

```bash
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban

# Verify it's running and monitoring SSH
sudo fail2ban-client status
sudo fail2ban-client status sshd
sudo fail2ban-client get sshd maxretry   # expected: 3
sudo fail2ban-client get sshd bantime    # expected: 86400
```

### Admin IP Whitelist

Production also has `/etc/fail2ban/jail.d/whitelist.conf`. It was added by hand on the server and is not in `deploy/`. It keeps the admin home IP from ever being banned. Production sets `ignoreip` under `[DEFAULT]`, which applies to every jail including `sshd`:

```ini
[DEFAULT]
ignoreip = 127.0.0.0/8 ::1 <admin-ip>
```

The production file also has an `[sshd]` block with `maxretry = 5` and `bantime = 3600`. Those two values do not take effect, because `jail.local` overrides `jail.d/*.conf`; the live values stay 3 and 86400.

```bash
sudo fail2ban-client reload
sudo fail2ban-client get sshd ignoreip   # expected: the list above
```

When your home IP changes, follow the whitelist procedure in [server-runbook.md](../server-runbook.md).

SSH as any user other than `deploy` (for example `root@` or a personal user name) is refused by `AllowUsers` and counts as a failed login. From a non-whitelisted IP, three such tries get you banned.

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

The script skips `dpkg-reconfigure` and the `50unattended-upgrades` edits below. It only installs the packages and writes `20auto-upgrades`.

### Configure What Gets Updated

```bash
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```

Ensure these lines are uncommented (they are the Ubuntu defaults):

```
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
```

### Automatic Reboot (owner decision)

Kernel and libc updates take effect only after a reboot. These lines make the server reboot by itself at 04:00 when an update needs it:

```
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
```

A reboot stops monitoring for a short time, so turning this on is the owner's decision.

Production state (2026-10-03): automatic reboot is not enabled. The server last rebooted on 2026-03-24 and still runs the kernel from then. Newer kernel and libc updates are installed but not active. Scheduling a reboot and deciding on automatic reboot are open items in TODO.md. To check whether a reboot is pending:

```bash
ls /var/run/reboot-required && cat /var/run/reboot-required.pkgs
uname -r   # the running kernel
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

These settings harden the network stack against common attacks. The script copies them from `deploy/configs/sysctl-hardening.conf`.

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

# Verify a few settings (expected: = 1 for each)
sudo sysctl net.ipv4.tcp_syncookies
sudo sysctl net.ipv4.conf.all.rp_filter
sudo sysctl net.ipv4.conf.all.log_martians
```

Production state (2026-10-03): all checked values match the file except `log_martians`. The file sets it to 1, but the running kernel reports 0 for `all` and `default`. No other sysctl file sets it, so the cause is unknown. This is an open item in TODO.md.

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

# Admin home directory: 755, not 750
chmod 755 /home/deploy

# Secure SSH directory
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

`/home/deploy` must stay 755. The service runs as the `sentinel` user from `/home/deploy/sentinel`, so `sentinel` must be able to enter `/home/deploy`. With 750 the service cannot start.

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

The script installs AIDE and runs `aideinit` in the background. It does nothing else for AIDE.

### Daily Checks

The Ubuntu `aide` package already schedules a daily check with `dailyaidecheck.timer`. No custom cron script is needed. The check writes its report to `/var/log/aide/aide.log`.

```bash
systemctl list-timers dailyaidecheck.timer   # shows the last and next run
sudo tail -50 /var/log/aide/aide.log
```

An earlier version of this guide suggested a custom `/etc/cron.daily/aide-check` script. It was never installed on production.

After legitimate system updates, update the AIDE database. Otherwise every daily report lists those updates as changes:

```bash
sudo aide --update
sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db
```

Production state (2026-10-03): the baseline `/var/lib/aide/aide.db` dates from 2026-03-23 and has never been updated, and `/etc/default/aide` has `COPYNEWDB=no`. Each daily report is therefore dominated by months of legitimate changes and gives no useful intrusion signal. Refreshing the baseline is an open item in TODO.md.

---

## Step 11: Login Notifications (optional)

This step is optional. It is not deployed on production, and the script does not perform it.

It logs every SSH login to the system log.

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

# Verify the service user has no login shell
getent passwd sentinel | cut -d: -f7
# Expected: /usr/sbin/nologin
```

Do not use `sudo -u sentinel bash` for the last check. It starts bash directly and ignores the login shell, so it proves nothing. `sudo su - sentinel` uses the login shell and should print "This account is currently not available."

---

## Post-Hardening Checklist

Run through this checklist before proceeding to application deployment:

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Hetzner Cloud Firewall active | Hetzner Console → Firewalls | `sentinel-fw` applied, only 2222/tcp from admin IP (temporary port 22 rule deleted). Production does not meet this today; see Step 0. |
| 2 | Root SSH disabled | `ssh root@<ip> -p 2222` | Connection refused / denied |
| 3 | Password auth disabled | `ssh -o PasswordAuthentication=yes deploy@<ip> -p 2222` | Permission denied |
| 4 | Old SSH port closed | `ssh deploy@<ip> -p 22` | Connection timed out (or refused) |
| 5 | UFW active, only SSH open | `sudo ufw status` | 2222/tcp ALLOW |
| 6 | Fail2ban monitoring SSH | `sudo fail2ban-client status sshd` | Shows active jail |
| 7 | Auto-updates enabled | `sudo systemctl status unattended-upgrades` | Active |
| 8 | Sysctl hardening applied | `sudo sysctl net.ipv4.conf.all.rp_filter` | = 1 |
| 9 | Admin user has sudo | `sudo whoami` | root |
| 10 | Service user has no shell | `getent passwd sentinel \| cut -d: -f7` | `/usr/sbin/nologin` |
| 11 | No unnecessary services | `sudo systemctl list-units --type=service --state=running` | Minimal list |
| 12 | AIDE database initialized | `sudo aide --check` | No unexpected changes |

Row 4 usually times out rather than being refused, because UFW drops packets to closed ports instead of rejecting them.

---

## Service Sandbox and Log Retention

`deploy/03-setup-services.sh` installs `deploy/configs/sentinel.service`. The unit runs the bot as `User=sentinel` inside a systemd sandbox:

- No privilege gain: `NoNewPrivileges=yes`, an empty `CapabilityBoundingSet=`, `RestrictSUIDSGID=yes`.
- File system: `ProtectSystem=strict` makes the whole system read-only, and `ProtectHome=read-only` covers `/home`. Only `/var/lib/sentinel` and `/var/log/sentinel` are writable (`ReadWritePaths=`). `PrivateTmp=yes` gives the service its own `/tmp`.
- Kernel and devices: `PrivateDevices`, `ProtectKernelTunables`, `ProtectKernelLogs`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`.
- Other: `LockPersonality`, `RestrictRealtime`, `SystemCallArchitectures=native`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`.

If a code change needs to write a file anywhere else, the service fails with a permission or read-only error. Add the path to `ReadWritePaths=` in `deploy/configs/sentinel.service`, or write under `/var/lib/sentinel` instead.

Check the sandbox score (the script aims for under 4.0):

```bash
sudo systemd-analyze security sentinel.service | tail -1
```

The same script sets log retention:

- journald: `SystemMaxUse=500M` and `MaxRetentionSec=30day` in `/etc/systemd/journald.conf`.
- logrotate: `deploy/configs/sentinel-logrotate` rotates `/var/log/sentinel/*.log` daily and keeps 14 compressed files.

---

## Ongoing Maintenance

### Weekly

- Review auth log for suspicious activity: `sudo journalctl -u ssh --since "7 days ago" | tail -50` (on Ubuntu 24.04 the unit is `ssh`, not `sshd`; `sudo grep sshd /var/log/auth.log | tail -50` also works)
- Check fail2ban bans: `sudo fail2ban-client status sshd`

### Monthly

- Review and remove old SSH keys if any were added
- Check for new CVEs affecting your Ubuntu version
- Check for a pending reboot: `ls /var/run/reboot-required` (see Step 6)
- Review running services: `sudo systemctl list-units --type=service --state=running`
- Update AIDE database after legitimate changes: `sudo aide --update && sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db`
- Verify Hetzner Cloud Firewall rules still match your admin IP(s)

### After Every `apt upgrade`

- Update AIDE database (so it doesn't flag legitimate updates as intrusions)

### When Your Home IP Changes

- Update the fail2ban whitelist and the Hetzner firewall rule. See Step 5 and [server-runbook.md](../server-runbook.md).

---

## Emergency: Locked Out?

If you lock yourself out of SSH:

1. **Hetzner Cloud Console** -- go to the Hetzner dashboard, select your server, click "Console". This gives you direct access regardless of SSH config or Cloud Firewall rules.
2. **Rescue Mode** -- Hetzner lets you boot into a rescue system to fix config files.
3. From rescue/console, fix `/etc/ssh/sshd_config.d/99-sentinel-hardening.conf` (and, if the port is the problem, `/etc/systemd/system/ssh.socket.d/override.conf`). Then run `systemctl daemon-reload && systemctl restart ssh.socket`.
4. If fail2ban banned your IP, run `sudo fail2ban-client set sshd unbanip <your-ip>` from the console.
5. If locked out by the Cloud Firewall, update the firewall rules in the Hetzner Console web UI -- no SSH needed.

Tip: before making SSH config changes, always keep at least one existing session open as a safety net.
