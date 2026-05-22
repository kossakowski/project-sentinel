"""Statistics / aggregation API endpoint.

Route (registered under the ``/api`` prefix by `dashboard.app`):

* ``GET /api/stats`` -- aggregate pipeline + distribution statistics
"""

from flask import Blueprint, jsonify

from dashboard.api._common import get_db

stats_bp = Blueprint("stats", __name__)


@stats_bp.route("/stats", methods=["GET"])
def get_stats():
    """Return aggregate statistics for the dashboard overview (req 1.6).

    Delegates to `DashboardDB.get_stats()`. The response includes total
    counts, ``articles_per_day`` for the last 30 days (zero-filled, req 1.6a),
    urgency / source / language / event-type distributions, and the
    ``pipeline_funnel`` stage counts (req 1.6b).
    """
    db = get_db()
    try:
        stats = db.get_stats()
    finally:
        db.close()
    return jsonify(stats)
