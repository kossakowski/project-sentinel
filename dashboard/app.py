"""Flask application factory for the Article Dashboard.

`create_app()` builds the Flask app: it registers the API blueprints under
``/api``, configures CORS for the Vite dev server, and serves the built React
SPA from ``dashboard/frontend/dist/`` when that directory exists (it does not
until Phase 2 -- until then ``/`` returns a JSON status message).
"""

import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from dashboard import config
from dashboard.api import ALL_BLUEPRINTS
from dashboard.db import DashboardDBError


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
        tunnel: when True, the DB layer connects via an SSH tunnel to the
            production server instead of a local file (req 1.1c).
        fts_db_path: path to the separate FTS index DB. Defaults to
            ``config.FTS_DB_PATH``.
        dev_cors: when True (default), enable CORS for the Vite dev server
            origin so the React dev server can call the API (req 1.1a).

    Returns:
        A configured `Flask` app with the API blueprints registered.
    """
    app = Flask(__name__)

    # DB connection settings consumed per-request by dashboard.api._common.
    app.config["SENTINEL_DB_PATH"] = db_path or config.DEFAULT_DB_PATH
    app.config["SENTINEL_FTS_DB_PATH"] = fts_db_path or config.FTS_DB_PATH
    app.config["USE_TUNNEL"] = tunnel

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
