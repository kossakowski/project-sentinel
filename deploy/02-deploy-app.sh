#!/bin/bash
# =============================================================================
# Project Sentinel -- Application Deployment
# =============================================================================
# Run as: deploy user
# Prerequisites: 01-harden-server.sh completed
#
# This script:
#   1. Clones the repo (or pulls if already cloned)
#   2. Creates Python venv and installs dependencies
#   3. Copies config and secrets to /etc/sentinel/
#   4. Runs a smoke test
#
# After running, you still need to:
#   - Edit /etc/sentinel/config.yaml (set absolute paths for DB, logs, session)
#   - Run Telegram first-time auth (interactive)
#   - Run 03-setup-services.sh
# =============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-}"
APP_DIR="/home/deploy/sentinel"

# --- Preflight ----------------------------------------------------------------

if [ "$(whoami)" = "root" ]; then
    echo "ERROR: Do not run this as root. Run as the deploy user."
    exit 1
fi

# --- Step 1: Get the code -----------------------------------------------------

echo "[1/4] Setting up application code..."

if [ -d "$APP_DIR/.git" ]; then
    echo "  Repo already exists, pulling latest from master..."
    cd "$APP_DIR"
    git pull origin master
elif [ -n "$REPO_URL" ]; then
    echo "  Cloning from $REPO_URL..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
else
    # No repo URL and no existing clone -- assume files were copied via scp
    if [ -d "$APP_DIR" ]; then
        echo "  App directory exists (likely copied via scp). Skipping clone."
        cd "$APP_DIR"
    else
        echo "ERROR: No repo URL provided and $APP_DIR doesn't exist."
        echo "Either set REPO_URL or scp the project to $APP_DIR first."
        echo "  Usage: REPO_URL=git@github.com:user/repo.git ./02-deploy-app.sh"
        exit 1
    fi
fi

# --- Step 2: Python venv -----------------------------------------------------

echo "[2/4] Setting up Python virtual environment..."

if [ -d "$APP_DIR/venv" ]; then
    echo "  Venv exists. Updating dependencies..."
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
else
    python3 -m venv "$APP_DIR/venv"
    "$APP_DIR/venv/bin/pip" install --upgrade pip --quiet
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
    echo "  Venv created and dependencies installed."
fi

# --- Step 3: Config and secrets -----------------------------------------------

echo "[3/4] Setting up configuration and secrets..."

# Config -- server copy with absolute paths
if [ ! -f /etc/sentinel/config.yaml ]; then
    sudo cp "$APP_DIR/config/config.example.yaml" /etc/sentinel/config.yaml
    sudo chown deploy:deploy /etc/sentinel/config.yaml
    sudo chmod 644 /etc/sentinel/config.yaml
    echo "  Copied config.example.yaml -> /etc/sentinel/config.yaml"
    echo "  IMPORTANT: Edit /etc/sentinel/config.yaml and set absolute paths:"
    echo "    database.path:                /var/lib/sentinel/sentinel.db"
    echo "    logging.file:                 /var/log/sentinel/sentinel.log"
    echo "    sources.telegram.session_name: /var/lib/sentinel/sentinel_session"
else
    echo "  /etc/sentinel/config.yaml already exists."
fi

# Secrets -- isolated from repo, readable only by root and deploy
if [ -f "$APP_DIR/.env" ]; then
    sudo cp "$APP_DIR/.env" /etc/sentinel/sentinel.env
    sudo chown root:deploy /etc/sentinel/sentinel.env
    sudo chmod 640 /etc/sentinel/sentinel.env
    echo "  .env copied to /etc/sentinel/sentinel.env (root:deploy 0640)"
    echo "  The .env in the repo is no longer used -- you can delete it."
elif [ ! -f /etc/sentinel/sentinel.env ]; then
    echo ""
    echo "  WARNING: No .env file found. Create /etc/sentinel/sentinel.env with:"
    echo "    TWILIO_ACCOUNT_SID=..."
    echo "    TWILIO_AUTH_TOKEN=..."
    echo "    TWILIO_PHONE_NUMBER=..."
    echo "    ALERT_PHONE_NUMBER=..."
    echo "    ANTHROPIC_API_KEY=..."
    echo "    TELEGRAM_API_ID=..."
    echo "    TELEGRAM_API_HASH=..."
    echo ""
    echo "  Then set permissions:"
    echo "    sudo chown root:deploy /etc/sentinel/sentinel.env"
    echo "    sudo chmod 640 /etc/sentinel/sentinel.env"
fi

# --- Step 4: Smoke test -------------------------------------------------------

echo ""
echo "[4/4] Running smoke test (dry-run, single cycle)..."
cd "$APP_DIR"

if [ -f /etc/sentinel/sentinel.env ]; then
    set -a; source /etc/sentinel/sentinel.env; set +a
fi

if "$APP_DIR/venv/bin/python" sentinel.py --config /etc/sentinel/config.yaml --once --dry-run 2>&1 | tail -5; then
    echo ""
    echo "=== Deployment complete ==="
else
    echo ""
    echo "Smoke test had issues (may be OK if config paths need updating)."
    echo "=== Deployment complete (with warnings) ==="
fi

echo ""
echo "NEXT STEPS:"
echo "  1. Edit config:  nano /etc/sentinel/config.yaml"
echo "     Set absolute paths for database, logging, and telegram session."
echo "  2. Telegram auth (interactive -- must do manually):"
echo "       cd $APP_DIR && source venv/bin/activate"
echo "       set -a; source /etc/sentinel/sentinel.env; set +a"
echo "       python -c \""
echo "         import os, asyncio"
echo "         from telethon import TelegramClient"
echo "         client = TelegramClient('/var/lib/sentinel/sentinel_session',"
echo "             int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])"
echo "         asyncio.run(client.start())"
echo "       \""
echo "       sudo chown sentinel:sentinel /var/lib/sentinel/sentinel_session.session"
echo "       sudo chmod 600 /var/lib/sentinel/sentinel_session.session"
echo "  3. Run 03-setup-services.sh"
