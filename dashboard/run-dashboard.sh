#!/usr/bin/env bash
# Launcher for the Article Dashboard -- no manual venv activation needed.
# Mirrors the project's top-level run.sh pattern.
# Usage:
#   ./dashboard/run-dashboard.sh                   # start on port 5001
#   ./dashboard/run-dashboard.sh --sync            # sync DB, then start
#   ./dashboard/run-dashboard.sh --tunnel          # use SSH tunnel
#   ./dashboard/run-dashboard.sh --port 5005       # custom port
# All arguments are forwarded to `python -m dashboard`.

set -euo pipefail

# Project root is the parent of this script's directory (dashboard/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"
PYTHON="$VENV/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Virtual environment not found at $VENV"
    echo "Creating it now..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
fi

# Run from the project root so `python -m dashboard` resolves the package.
cd "$PROJECT_ROOT"
exec "$PYTHON" -m dashboard "$@"
