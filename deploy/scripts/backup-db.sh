#!/bin/bash
# Daily SQLite backup for Project Sentinel -- called by cron at 03:00.
# Runs as deploy user.

BACKUP_DIR="/home/deploy/backups"
DB_FILE="/var/lib/sentinel/sentinel.db"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "Database file not found: $DB_FILE"
    exit 1
fi

sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/sentinel_$DATE.db'"

# Keep only last 7 days
find "$BACKUP_DIR" -name "sentinel_*.db" -mtime +7 -delete

echo "Backup complete: sentinel_$DATE.db"
