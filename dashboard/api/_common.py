"""Shared helpers for the API blueprints.

Centralises how a request obtains a `DashboardDB`. The DB connection settings
(local file path / FTS path / tunnel mode) are stashed on `app.config` by the
application factory; each request opens its own short-lived read-only
connection, which keeps SQLite access thread-safe under Flask's threaded
server and avoids a shared cross-thread connection.
"""

from flask import current_app

from dashboard.db import DashboardDB


def get_db() -> DashboardDB:
    """Open a `DashboardDB` for the current request using app config.

    The caller is responsible for calling ``.close()`` (typically in a
    ``finally`` block).
    """
    cfg = current_app.config
    return DashboardDB(
        db_path=cfg.get("SENTINEL_DB_PATH"),
        tunnel=cfg.get("USE_TUNNEL", False),
        fts_db_path=cfg.get("SENTINEL_FTS_DB_PATH"),
    )
