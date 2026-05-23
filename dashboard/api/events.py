"""Event detail API endpoint.

Route (registered under the ``/api`` prefix by `dashboard.app`):

* ``GET /api/events/<event_id>`` -- one event with its full article list and
  alert timeline (spec req 2.1).

Read-only by design — only ``GET`` is exposed; ``POST``/``PUT``/``DELETE``
fall through to Flask's automatic ``405 Method Not Allowed`` response
(spec req 2.1c).
"""

from flask import Blueprint, jsonify

from dashboard.api._common import get_db

events_bp = Blueprint("events", __name__)


@events_bp.route("/events/<event_id>", methods=["GET"])
def event_detail(event_id: str):
    """Return one event with its full article list and alert timeline.

    Spec req 2.1, 2.1a. The response shape is
    ``{id, event_type, urgency_score, affected_countries, aggressor,
    summary_pl, first_seen_at, last_updated_at, source_count, article_ids,
    alert_status, acknowledged_at, articles[], alert_records[]}``. Each
    article entry carries the same fields the article-list endpoint returns,
    so the frontend can render them via the same component used in the list.

    Returns HTTP 404 with ``{"error": "event not found"}`` when no event has
    the given id (spec req 2.1b).
    """
    db = get_db()
    try:
        event = db.get_event_with_articles(event_id)
    finally:
        db.close()

    if event is None:
        return jsonify({"error": "event not found"}), 404

    return jsonify(event)
