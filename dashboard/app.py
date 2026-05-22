"""Flask application factory for the Article Dashboard.

`create_app()` builds the Flask app: it registers the API blueprints under
``/api``, configures CORS for the Vite dev server, and serves the built React
SPA from ``dashboard/frontend/dist/`` when that directory exists (it does not
until Phase 2 -- until then ``/`` returns a JSON status message).

In tunnel mode (req 1.1c) the factory performs ONE SCP fetch at startup,
caches the resulting temp-file path on ``app.config["SENTINEL_DB_PATH"]``,
and registers an ``atexit`` cleanup so the file is removed when the process
exits. Per-request handlers open new SQLite connections against this cached
file -- they never trigger another SCP.
"""

import atexit
import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from dashboard import config
from dashboard.api import ALL_BLUEPRINTS
from dashboard.db import DashboardDB, DashboardDBError


def create_app(
    db_path: str | None = None,
    tunnel: bool = False,
    fts_db_path: str | None = None,
    dev_cors: bool = True,
) -> Flask:
    """Create and configure the dashboard Flask application.

    Args:
        db_path: path to the local sentinel SQLite DB. Defaults to
            ``config.DEFAULT_DB_PATH``. Ignored when ``tunnel`` is True.
        tunnel: when True, the factory pre-fetches the production DB via SCP
            into a temp file ONCE at startup (req 1.1c). Per-request handlers
            then open new SQLite connections against that cached file. The
            temp file is removed on process exit via ``atexit``.
        fts_db_path: path to the separate FTS index DB. Defaults to
            ``config.FTS_DB_PATH``.
        dev_cors: when True (default), enable CORS for the Vite dev server
            origin so the React dev server can call the API (req 1.1a).

    Returns:
        A configured `Flask` app with the API blueprints registered.
    """
    app = Flask(__name__)

    fts_path = fts_db_path or config.FTS_DB_PATH
    app.config["SENTINEL_FTS_DB_PATH"] = fts_path
    app.config["USE_TUNNEL"] = tunnel

    if tunnel:
        # ONE SCP at app startup -- spec req 1.1c "fetches a fresh copy of the
        # production database over SSH on each dashboard startup". Per-request
        # handlers reuse this cached path instead of re-SCPing.
        cached_path = _fetch_tunnel_db_once(app)
        app.config["SENTINEL_DB_PATH"] = cached_path
    else:
        app.config["SENTINEL_DB_PATH"] = db_path or config.DEFAULT_DB_PATH

    # CORS for the Vite dev server -- scoped to /api/* routes only (req 1.1a).
    if dev_cors:
        CORS(
            app,
            resources={r"/api/*": {"origins": config.DEV_FRONTEND_ORIGIN}},
        )

    # Register every API blueprint under the /api prefix (req 1.1).
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/api")

    _register_frontend_routes(app)
    _register_error_handlers(app)
    return app


def _fetch_tunnel_db_once(app: Flask) -> str:
    """Perform the one-time SCP fetch for tunnel mode and arrange cleanup.

    Uses DashboardDB's self-fetching path (``tunnel=True`` with no ``db_path``)
    purely to drive the SCP+temp-file logic, then transfers ownership of the
    temp file out to the factory via ``DashboardDB.detach_tempfile()`` and
    closes the bootstrap SQLite connection. The temp file path is captured and
    an ``atexit`` cleanup hook is registered so the file is removed when the
    process exits.
    """
    # Use a path that definitely cannot have an FTS sibling -- tunnel mode
    # always falls back to LIKE (the temp copy has no co-located FTS DB).
    bootstrap = DashboardDB(tunnel=True, db_path=None, fts_db_path="/nonexistent/fts.db")
    # detach_tempfile() returns the just-fetched path AND tells the bootstrap
    # not to delete it on close -- ownership transfers to the factory.
    cached_path = bootstrap.detach_tempfile()
    if cached_path is None:  # pragma: no cover -- bootstrap raises on SCP failure
        bootstrap.close()
        raise RuntimeError("Tunnel bootstrap did not produce a temp file path")
    # Close just the SQLite connection; ownership of the file is already ours.
    # Any close() error is surfaced rather than silently swallowed: a broken
    # connection at this point indicates a real problem worth seeing.
    bootstrap.conn.close()

    def _cleanup() -> None:
        try:
            if os.path.exists(cached_path):
                os.remove(cached_path)
        except OSError:  # pragma: no cover -- best-effort teardown
            pass

    atexit.register(_cleanup)
    # Stash on app.config so tests / introspection can also clean up early.
    app.config["TUNNEL_TEMPFILE"] = cached_path
    app.config["TUNNEL_CLEANUP"] = _cleanup
    return cached_path


def _register_frontend_routes(app: Flask) -> None:
    """Register routes serving the built React SPA (or a placeholder).

    When ``dashboard/frontend/dist/`` exists, ``/`` serves its ``index.html``
    and a catch-all serves other static assets / client-side routes. When it
    does not exist (pre-Phase-2), ``/`` returns a JSON status message
    (req 1.1). API routes are unaffected -- they are matched by their own
    blueprints first.
    """
    dist_dir = config.FRONTEND_DIST_DIR

    @app.route("/")
    def index():
        index_html = os.path.join(dist_dir, "index.html")
        if os.path.isfile(index_html):
            return send_from_directory(dist_dir, "index.html")
        return jsonify({"status": "frontend not built"})

    @app.route("/<path:path>")
    def static_or_spa(path: str):
        # /api/* is owned by the blueprints; nothing to serve here for it.
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404
        # Serve a real static asset if it exists in the build output.
        asset = os.path.join(dist_dir, path)
        if os.path.isfile(asset):
            return send_from_directory(dist_dir, path)
        # Otherwise fall back to the SPA entry point for client-side routing.
        index_html = os.path.join(dist_dir, "index.html")
        if os.path.isfile(index_html):
            return send_from_directory(dist_dir, "index.html")
        return jsonify({"status": "frontend not built"}), 404


def _register_error_handlers(app: Flask) -> None:
    """Register JSON error handlers so the API never returns HTML errors."""

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(DashboardDBError)
    def db_unavailable(error):
        # No DB synced yet (or it is unreadable): return a clean 503 with a
        # actionable message rather than a 500 stack trace.
        return jsonify({"error": str(error), "needs_sync": True}), 503
