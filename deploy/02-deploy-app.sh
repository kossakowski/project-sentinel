#!/bin/bash
# =============================================================================
# Project Sentinel -- Application Deployment
# =============================================================================
# Run as: sentinel user
# Prerequisites: 01-harden-server.sh completed
#
# This script:
#   1. Clones the repo (or pulls if already cloned)
#   2. Creates Python venv and installs dependencies
#   3. Creates data/ and logs/ directories
#   4. Copies config.example.yaml to config.yaml if not present
#
# After running, you still need to:
#   - Copy .env with your secrets to ~/project-sentinel/.env
#   - Edit config/config.yaml if needed
#   - Run Telegram first-time auth (interactive)
#   - Run 03-setup-services.sh
# =============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-}"
APP_DIR="/home/sentinel/project-sentinel"

# --- Preflight ----------------------------------------------------------------

if [ "$(whoami)" = "root" ]; then
    echo "ERROR: Do not run this as root. Run as the sentinel user."
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

if [ -d "$APP_DIR/.venv" ]; then
    echo "  Venv exists. Updating dependencies..."
    "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
else
    python3 -m venv "$APP_DIR/.venv"
    "$APP_DIR/.venv/bin/pip" install --upgrade pip --quiet
    "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
    echo "  Venv created and dependencies installed."
fi

# --- Step 3: Create directories -----------------------------------------------

echo "[3/4] Creating data and log directories..."
mkdir -p "$APP_DIR/data" "$APP_DIR/logs"

# --- Step 4: Config -----------------------------------------------------------

echo "[4/4] Checking configuration..."

if [ ! -f "$APP_DIR/config/config.yaml" ]; then
    cp "$APP_DIR/config/config.example.yaml" "$APP_DIR/config/config.yaml"
    echo "  Copied config.example.yaml -> config.yaml (edit as needed)."
else
    echo "  config.yaml already exists."
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "  WARNING: .env file not found at $APP_DIR/.env"
    echo "  You need to create it with your API keys. Required variables:"
    echo "    TWILIO_ACCOUNT_SID=..."
    echo "    TWILIO_AUTH_TOKEN=..."
    echo "    TWILIO_PHONE_NUMBER=..."
    echo "    ALERT_PHONE_NUMBER=..."
    echo "    ANTHROPIC_API_KEY=..."
    echo "    TELEGRAM_API_ID=..."
    echo "    TELEGRAM_API_HASH=..."
fi

# --- Quick smoke test ---------------------------------------------------------

echo ""
echo "Running smoke test (dry-run, single cycle)..."
cd "$APP_DIR"
if "$APP_DIR/.venv/bin/python" sentinel.py --once --dry-run 2>&1 | tail -5; then
    echo ""
    echo "=== Deployment complete ==="
else
    echo ""
    echo "Smoke test had issues (may be OK if .env is missing)."
    echo "=== Deployment complete (with warnings) ==="
fi

echo ""
echo "NEXT STEPS:"
echo "  1. Create .env file:  nano $APP_DIR/.env"
echo "  2. Edit config if needed:  nano $APP_DIR/config/config.yaml"
echo "  3. Telegram auth (interactive -- must do manually):"
echo "       cd $APP_DIR && .venv/bin/python -c \\"
echo "         'from telethon import TelegramClient; \\"
echo "          c = TelegramClient(\"sentinel_session\", API_ID, API_HASH); \\"
echo "          c.start(); c.disconnect()'"
echo "  4. Run 03-setup-services.sh"
