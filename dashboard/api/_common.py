"""Shared helpers for the API blueprints.

Centralises how a request obtains a `DashboardDB`. The DB connection settings
(local file path / FTS path / tunnel mode) are stashed on `app.config` by the
application factory; each request opens its own short-lived read-only SQLite
connection, which keeps SQLite access thread-safe under Flask's threaded
server (each connection lives on the request's worker thread) and avoids
sharing a cross-thread connection.

Tunnel mode (req 1.1c) caches the SCP at app-startup: the application factory
pre-fetches the production DB into a temp file once, stores that path on
``app.config["SENTINEL_DB_PATH"]``, and `get_db()` here opens fresh SQLite
connections against the cached file -- no per-request SCP.
"""

from flask import current_app

from dashboard.db import DashboardDB


def get_db() -> DashboardDB:
    """Open a `DashboardDB` for the current request using app config.

    In tunnel mode the app factory has already fetched the production DB into
    a temp file at startup and stored its path under ``SENTINEL_DB_PATH``; we
    pass ``db_path`` to DashboardDB so it opens that pre-fetched file directly
    instead of triggering another SCP. The caller is responsible for calling
    ``.close()`` on the returned DashboardDB (typically in a ``finally`` block).
    """
    cfg = current_app.config
    return DashboardDB(
        db_path=cfg.get("SENTINEL_DB_PATH"),
        tunnel=cfg.get("USE_TUNNEL", False),
        fts_db_path=cfg.get("SENTINEL_FTS_DB_PATH"),
        annotations_db_path=cfg.get("ANNOTATIONS_DB_PATH"),
    )
