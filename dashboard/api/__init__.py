"""API blueprint package for the Article Dashboard.

Each module exposes a Flask `Blueprint`; `dashboard.app` registers them all
under the ``/api`` URL prefix. Endpoints are read-only against the sentinel
database (the sole exception being `POST /api/sync`, which copies the
production DB locally -- it never writes to production).
"""

from dashboard.api.articles import articles_bp
from dashboard.api.stats import stats_bp
from dashboard.api.sync import sync_bp

# All API blueprints, registered in dashboard.app.create_app().
ALL_BLUEPRINTS = (articles_bp, stats_bp, sync_bp)

__all__ = ["ALL_BLUEPRINTS", "articles_bp", "stats_bp", "sync_bp"]
