"""Dashboard configuration.

This module IS the dashboard's configuration. Every path, port, and server
detail the dashboard needs is defined here as a module-level default so that
nothing is hardcoded deeper inside the code -- callers and the CLI override
these values when needed. No secrets live here: SSH uses key-based auth.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Absolute path to the dashboard package directory.
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

# Local data directory -- holds the synced sentinel DB and the FTS index DB.
# Matched by the project's .gitignore rule "data/", so synced DBs are never
# committed. Created automatically at runtime (see sync.py / db.py).
DATA_DIR = os.path.join(DASHBOARD_DIR, "data")

# Default path to the locally synced copy of the production sentinel database.
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "sentinel.db")

# Separate database file holding the FTS5 virtual table. Kept separate so the
# synced sentinel.db file remains byte-for-byte unmodified after a sync.
FTS_DB_PATH = os.path.join(DATA_DIR, "sentinel_fts.db")

# Local annotations database (Phase 4). Kept separate from the sentinel DB so
# user annotations persist across production-DB syncs — re-running ``--sync``
# overwrites ``sentinel.db`` byte-for-byte, but this file lives next to it
# untouched. Joined into article queries at runtime via SQLite ATTACH.
ANNOTATIONS_DB_PATH = os.path.join(DATA_DIR, "annotations.db")

# Built React frontend directory (Phase 2 deliverable -- may not exist yet).
FRONTEND_DIST_DIR = os.path.join(DASHBOARD_DIR, "frontend", "dist")

# ---------------------------------------------------------------------------
# Flask server
# ---------------------------------------------------------------------------

# Port for the Flask API server. 5001 avoids the default Flask port 5000
# (used by AirPlay on macOS) and collisions with other local Flask apps.
DEFAULT_PORT = 5001

# Origin allowed for CORS in development -- the Vite dev server.
DEV_FRONTEND_ORIGIN = "http://localhost:5173"

# ---------------------------------------------------------------------------
# Production server (SSH / SCP) -- configurable defaults, no secrets
# ---------------------------------------------------------------------------

# SSH user, host, and port for the production server. Key-based auth only.
SSH_USER = "deploy"
SSH_HOST = "178.104.76.254"
SSH_PORT = 2222

# Absolute path to the sentinel SQLite database on the production server.
REMOTE_DB_PATH = "/var/lib/sentinel/sentinel.db"

# Seconds to wait for the SCP copy before giving up.
SCP_TIMEOUT_SECONDS = 60


def ssh_target() -> str:
    """Return the ``user@host`` SSH target string."""
    return f"{SSH_USER}@{SSH_HOST}"


def scp_source() -> str:
    """Return the SCP source spec ``user@host:/remote/path`` for the DB."""
    return f"{ssh_target()}:{REMOTE_DB_PATH}"
