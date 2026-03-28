# Multi-Tenant Migration: Backup & Rollback Guide

This guide ensures you can return to the exact current state of the server
if anything goes wrong during the multi-tenant migration.

---

## STEP 1: Create the Backup (DO THIS BEFORE ANYTHING ELSE)

Open your terminal and run these commands one by one:

```bash
# Connect to the server
ssh -p 2222 deploy@178.104.76.254
```

You are now on the server. Run these commands:

```bash
# Create a backups directory (if it doesn't exist)
mkdir -p /home/deploy/backups

# Backup the entire application code (including all local modifications)
tar czf /home/deploy/backups/sentinel_pre_migration.tar.gz -C /home/deploy sentinel/

# Backup the config file
sudo cp /etc/sentinel/config.yaml /home/deploy/backups/config.yaml.pre-migration

# Backup the secrets file
sudo cp /etc/sentinel/sentinel.env /home/deploy/backups/sentinel.env.pre-migration

# Backup the SQLite database
cp /var/lib/sentinel/sentinel.db /home/deploy/backups/sentinel.db.pre-migration

# Backup the health file
cp /var/lib/sentinel/health.json /home/deploy/backups/health.json.pre-migration 2>/dev/null || true
```

Now verify the backup exists and looks reasonable:

```bash
# This should show a file of at least a few MB
ls -lh /home/deploy/backups/sentinel_pre_migration.tar.gz

# This should show all your backup files
ls -lh /home/deploy/backups/*pre-migration*
```

You should see output like:
```
-rw-r--r-- 1 deploy deploy  XXM  ... sentinel_pre_migration.tar.gz
-rw-r--r-- 1 deploy deploy  XXK  ... config.yaml.pre-migration
-rw-r--r-- 1 deploy deploy  XXK  ... sentinel.env.pre-migration
-rw-r--r-- 1 deploy deploy  XXK  ... sentinel.db.pre-migration
```

If you see all four files, the backup is complete. You can disconnect:

```bash
exit
```

---

## STEP 2: How to Restore (USE THIS IF SOMETHING GOES WRONG)

If at any point after the migration you want to go back to how
the server was before, run these commands:

```bash
# Connect to the server
ssh -p 2222 deploy@178.104.76.254

# Stop the service
sudo systemctl stop sentinel

# Delete the current (broken) application code
rm -rf /home/deploy/sentinel

# Restore the original application code from backup
cd /home/deploy
tar xzf /home/deploy/backups/sentinel_pre_migration.tar.gz

# Restore the original config
sudo cp /home/deploy/backups/config.yaml.pre-migration /etc/sentinel/config.yaml

# Restore the original secrets
sudo cp /home/deploy/backups/sentinel.env.pre-migration /etc/sentinel/sentinel.env

# Restore the original SQLite database
cp /home/deploy/backups/sentinel.db.pre-migration /var/lib/sentinel/sentinel.db

# Reinstall the old Python dependencies (the old code uses SQLite, not PostgreSQL)
cd /home/deploy/sentinel
venv/bin/pip install -r requirements.txt

# Start the service again
sudo systemctl start sentinel

# Verify it is running
sudo systemctl status sentinel
```

The last command should show "active (running)". If it does, the server
is back to exactly how it was before the migration.

To double-check, wait 3-5 minutes and then:

```bash
# Check that the pipeline is running
cat /var/lib/sentinel/health.json
```

You should see `"is_healthy": true`.

```bash
# Disconnect from the server
exit
```

---

## Important Notes

- The SQLite database is NEVER modified by the migration. Even without
  a backup, your data is safe. The migration only reads from SQLite.
- The backup captures the exact code on the server, including local
  modifications that exist nowhere else (not in Git, not on your laptop).
- PostgreSQL can remain installed on the server after a rollback. It does
  not interfere with the old SQLite-based code.
- The backup files at /home/deploy/backups/ are not affected by the
  restore process. You can restore multiple times.
