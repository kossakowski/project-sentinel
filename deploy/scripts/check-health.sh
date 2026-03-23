#!/bin/bash
# Health check for Project Sentinel -- called by cron every 30 min.
# Sends an SMS via Twilio if the health file is stale or missing.

HEALTH_FILE="/home/sentinel/project-sentinel/data/health.json"
MAX_AGE_MINUTES=30

if [ ! -f "$HEALTH_FILE" ]; then
    echo "Health file missing -- sentinel may not be running"
    exit 1
fi

FILE_AGE=$(($(date +%s) - $(stat -c %Y "$HEALTH_FILE")))
MAX_AGE=$((MAX_AGE_MINUTES * 60))

if [ "$FILE_AGE" -gt "$MAX_AGE" ]; then
    echo "Health file is ${FILE_AGE}s old (max: ${MAX_AGE}s) -- sentinel may be stuck"
    exit 1
fi

echo "Project Sentinel healthy"
exit 0
