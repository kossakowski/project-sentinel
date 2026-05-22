"""Database sync trigger / status API endpoints.

Routes (registered under the ``/api`` prefix by `dashboard.app`):

* ``POST /api/sync``        -- trigger an SCP sync of the production DB
* ``GET  /api/sync/status`` -- last sync timestamp + result

The last-sync record is persisted to a small JSON file in the data directory
so the status survives a server restart. The sync itself runs synchronously
(the production DB is only ~42 MB; SCP takes well under 10 seconds).
"""

import json
import os
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from dashboard import config, sync

sync_bp = Blueprint("sync", __name__)


def _state_path() -> str:
    """Return the path of the JSON file recording the last sync.

    Policy: the sync-state file follows ``--db``'s directory (matches the FTS
    co-location rule in `cli.py._derive_fts_path`). Switching ``--db`` between
    runs therefore isolates the last_sync record per DB -- a custom DB's sync
    state lives next to that DB, not next to the default one. This is
    intentional: each ``--db`` location is treated as its own data island.
    """
    db_path = current_app.config.get("SENTINEL_DB_PATH") or config.DEFAULT_DB_PATH
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "sync_state.json")


def _read_last_sync() -> dict | None:
    """Return the persisted last-sync record, or None if none exists."""
    path = _state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _write_last_sync(record: dict) -> None:
    """Persist the last-sync record to the JSON state file."""
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)


@sync_bp.route("/sync", methods=["POST"])
def trigger_sync():
    """Trigger a synchronous DB sync from production and return the result.

    Runs `dashboard.sync.sync_db()` (SCP copy + FTS5 index rebuild), records
    the outcome with a UTC timestamp, and returns the `SyncResult` as JSON
    (req 1.7). A failed sync still returns HTTP 200 with ``success: false`` so
    the client can surface the structured error.
    """
    cfg = current_app.config
    result = sync.sync_db(
        db_path=cfg.get("SENTINEL_DB_PATH"),
        fts_db_path=cfg.get("SENTINEL_FTS_DB_PATH"),
    )
    record = {
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "result": result.to_dict(),
    }
    _write_last_sync(record)
    return jsonify(record)


@sync_bp.route("/sync/status", methods=["GET"])
def sync_status():
    """Return the timestamp + result of the last sync (req 1.7a).

    Returns ``{"last_sync": null}`` when no sync has ever been performed.
    """
    record = _read_last_sync()
    if record is None:
        return jsonify({"last_sync": None})
    return jsonify(record)
