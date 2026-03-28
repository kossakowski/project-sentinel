#!/bin/bash
# Health check for Project Sentinel -- called by cron every 30 min.
# Runs as deploy user. Sends an SMS via Twilio if the service appears stuck or dead.

HEALTH_FILE="/var/lib/sentinel/health.json"
MAX_AGE_MINUTES=30
ENV_FILE="/etc/sentinel/sentinel.env"
CONFIG="/etc/sentinel/config.yaml"
PYTHON="/home/deploy/sentinel/venv/bin/python"

if [ ! -f "$HEALTH_FILE" ]; then
    MSG="Health file missing -- sentinel may not be running."
elif [ $(($(date +%s) - $(stat -c %Y "$HEALTH_FILE"))) -gt $((MAX_AGE_MINUTES * 60)) ]; then
    MSG="Health file stale -- sentinel may be stuck."
else
    echo "Project Sentinel healthy"
    exit 0
fi

echo "$MSG"

# Send SMS alert via Twilio
if [ -f "$ENV_FILE" ] && [ -f "$CONFIG" ] && [ -x "$PYTHON" ]; then
    set -a; source "$ENV_FILE"; set +a
    $PYTHON -c "
from sentinel.alerts.twilio_client import TwilioClient
from sentinel.config import load_config
config = load_config('$CONFIG')
client = TwilioClient(config)
client.send_sms(config.alerts.system_phone_number, 'Project Sentinel: $MSG Sprawdź serwer.', 'health-check')
" 2>&1 || echo "Failed to send SMS alert"
fi

exit 1
