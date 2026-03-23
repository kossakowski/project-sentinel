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

set -uo pipefail
# Note: -e intentionally omitted -- we handle errors explicitly

REPO_URL="${REPO_URL:-}"
APP_DIR="/home/deploy/sentinel"

die()  { echo "FATAL: $1"; exit 1; }

# --- Preflight ----------------------------------------------------------------

[ "$(whoami)" != "root" ] || die "Do not run this as root. Run as the deploy user."

# --- Step 1: Get the code -----------------------------------------------------

echo "[1/4] Setting up application code..."

if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    if git remote get-url origin &>/dev/null; then
        echo "  Repo already exists, pulling latest from master..."
        git pull origin master || die "git pull failed"
    else
        echo "  Repo exists but has no remote (copied via scp). Skipping pull."
    fi
elif [ -n "$REPO_URL" ]; then
    echo "  Cloning from $REPO_URL..."
    git clone "$REPO_URL" "$APP_DIR" || die "git clone failed"
    cd "$APP_DIR"
else
    if [ -d "$APP_DIR" ]; then
        echo "  App directory exists (copied via scp). Skipping clone."
        cd "$APP_DIR"
    else
        die "No repo URL provided and $APP_DIR doesn't exist. Set REPO_URL or scp the project first."
    fi
fi

# --- Step 2: Python venv -----------------------------------------------------

echo "[2/4] Setting up Python virtual environment..."

if [ -d "$APP_DIR/venv" ]; then
    echo "  Venv exists. Updating dependencies..."
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet || die "pip install failed"
else
    python3 -m venv "$APP_DIR/venv" || die "venv creation failed"
    "$APP_DIR/venv/bin/pip" install --upgrade pip --quiet
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet || die "pip install failed"
    echo "  Venv created and dependencies installed."
fi

# --- Step 3: Config and secrets -----------------------------------------------

echo "[3/4] Setting up configuration and secrets..."

sudo mkdir -p /etc/sentinel

if [ ! -f /etc/sentinel/config.yaml ]; then
    sudo cp "$APP_DIR/config/config.example.yaml" /etc/sentinel/config.yaml
    sudo chown root:sentinel /etc/sentinel/config.yaml
    sudo chmod 640 /etc/sentinel/config.yaml
    echo "  Copied config.example.yaml -> /etc/sentinel/config.yaml"
    echo "  IMPORTANT: Edit /etc/sentinel/config.yaml and set absolute paths:"
    echo "    database.path:                /var/lib/sentinel/sentinel.db"
    echo "    logging.file:                 /var/log/sentinel/sentinel.log"
    echo "    sources.telegram.session_name: /var/lib/sentinel/sentinel_session"
else
    echo "  /etc/sentinel/config.yaml already exists."
fi

if [ -f "$APP_DIR/.env" ]; then
    sudo cp "$APP_DIR/.env" /etc/sentinel/sentinel.env
    sudo chown root:deploy /etc/sentinel/sentinel.env
    sudo chmod 640 /etc/sentinel/sentinel.env
    echo "  .env copied to /etc/sentinel/sentinel.env (root:deploy 0640)"
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

# --- Step 4: Smoke test (non-fatal) ------------------------------------------

echo ""
echo "[4/4] Running smoke test (dry-run, single cycle)..."
cd "$APP_DIR"

if [ -f /etc/sentinel/sentinel.env ]; then
    set -a; source /etc/sentinel/sentinel.env; set +a
fi

if "$APP_DIR/venv/bin/python" sentinel.py --config /etc/sentinel/config.yaml --once --dry-run 2>&1 | tail -5; then
    echo "  Smoke test passed."
else
    echo "  Smoke test had issues (may be OK if .env or config paths need updating)."
fi

echo ""
echo "=== Deployment complete ==="
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
