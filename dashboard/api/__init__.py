"""API blueprint package for the Article Dashboard.

Each module exposes a Flask `Blueprint`; `dashboard.app` registers them all
under the ``/api`` URL prefix. Endpoints are read-only against the sentinel
database, with two exceptions: `POST /api/sync` (copies the production DB
locally; never writes to production) and the annotations endpoints (which
write to a separate local annotations database — see ``dashboard.annotations``).
"""

from dashboard.api.annotations import annotations_bp
from dashboard.api.articles import articles_bp
from dashboard.api.events import events_bp
from dashboard.api.stats import stats_bp
from dashboard.api.sync import sync_bp

# All API blueprints, registered in dashboard.app.create_app().
ALL_BLUEPRINTS = (articles_bp, stats_bp, sync_bp, annotations_bp, events_bp)

__all__ = [
    "ALL_BLUEPRINTS",
    "annotations_bp",
    "articles_bp",
    "events_bp",
    "stats_bp",
    "sync_bp",
]
