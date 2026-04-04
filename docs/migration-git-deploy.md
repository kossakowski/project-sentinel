# Migration: Switch deploy to git-based pull from GitHub

**What this does:** The production server already has a git clone at `/home/deploy/sentinel/`.
Currently it uses HTTPS (which needs a password/token for private repos). This migration
switches it to SSH with a deploy key so `/deploy` can run `git fetch && git checkout` non-interactively.

**Downtime:** Zero. The service keeps running throughout. We're only changing git remote config.

**Rollback:** If anything goes wrong, the service is untouched. Worst case, re-run the old
rsync-based deploy manually.

---

## Step-by-step

### 1. SSH into the server

```bash
ssh -p 2222 deploy@178.104.76.254
```

> **WARNING:** Always use `deploy@` — never `root@` or `kossa@`.
> Wrong username = fail2ban ban = locked out.

---

### 2. Generate a deploy key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "sentinel-deploy-key"
```

Expected output:
```
Generating public/private ed25519 key pair.
Your identification has been saved in /home/deploy/.ssh/github_deploy
Your public key has been saved in /home/deploy/.ssh/github_deploy.pub
```

Now **copy the public key** — you'll need it in the next step:

```bash
cat ~/.ssh/github_deploy.pub
```

It will look something like:
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... sentinel-deploy-key
```

**Copy that entire line.** Leave the SSH session open.

---

### 3. Add the deploy key to GitHub (in your browser)

1. Go to: https://github.com/kossakowski/project-sentinel/settings/keys
2. Click **"Add deploy key"**
3. Title: `sentinel-server`
4. Key: paste the public key from step 2
5. **Leave "Allow write access" UNCHECKED** — read-only is all we need
6. Click **"Add key"**

---

### 4. Back on the server: configure SSH to use the deploy key

```bash
mkdir -p ~/.ssh
cat >> ~/.ssh/config << 'EOF'
Host github.com
    IdentityFile ~/.ssh/github_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

---

### 5. Test SSH access to GitHub

```bash
ssh -T git@github.com
```

Expected output:
```
Hi kossakowski/project-sentinel! You've been successfully authenticated, but GitHub does not provide shell access.
```

If you get `Permission denied (publickey)` — go back to steps 2-4, something went wrong.

---

### 6. Switch the git remote from HTTPS to SSH

```bash
cd /home/deploy/sentinel
git remote set-url origin git@github.com:kossakowski/project-sentinel.git
```

Verify:
```bash
git remote -v
```

Should show:
```
origin  git@github.com:kossakowski/project-sentinel.git (fetch)
origin  git@github.com:kossakowski/project-sentinel.git (push)
```

---

### 7. Test that git fetch works

```bash
git fetch --tags origin
```

Expected: it fetches without asking for a password. You should see new tags/commits
being downloaded (the server is a few commits behind).

If it hangs or asks for a password — something went wrong with the SSH config (step 4).

---

### 8. Done

```bash
exit
```

The server is now ready for git-based deployments. The next time you run `/deploy`,
Step 6a will do `git fetch --tags origin && git checkout <deploy-tag>` instead of rsync.

---

## Quick verification checklist

After you're done, run these from your **local machine** to confirm everything is set up:

```bash
ssh -p 2222 deploy@178.104.76.254 'cd /home/deploy/sentinel && git remote -v && git fetch --tags origin 2>&1 && echo "OK: git fetch works"'
```

If you see `OK: git fetch works` — you're good.

---

## If something goes wrong

- **Service is unaffected** — we only touched git config, not the running code
- **To revert the remote URL:** `git remote set-url origin https://github.com/kossakowski/project-sentinel.git`
- **To remove the deploy key:** delete it from GitHub settings page + `rm ~/.ssh/github_deploy*`
