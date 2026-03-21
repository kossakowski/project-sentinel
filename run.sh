#!/usr/bin/env bash
# Launcher for Project Sentinel — no manual venv activation needed.
# Usage:
#   ./run.sh                        # daemon mode
#   ./run.sh --once --dry-run       # single dry run
#   ./run.sh --test-headline "..."  # test a headline
#   ./run.sh --health               # health check
# All arguments are forwarded to sentinel.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Virtual environment not found at $VENV"
    echo "Creating it now..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

exec "$PYTHON" "$SCRIPT_DIR/sentinel.py" "$@"
