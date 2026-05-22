"""Article list / detail / search API endpoints.

Routes (registered under the ``/api`` prefix by `dashboard.app`):

* ``GET /api/articles``            -- paginated, filtered, sorted list + search
* ``GET /api/articles/<id>``       -- full article detail with classifier input
"""

from flask import Blueprint, jsonify, request

from dashboard.api._common import get_db
from dashboard.classifier_input import build_classifier_input
from dashboard.db import ALLOWED_PAGE_SIZES, DEFAULT_PAGE_SIZE

articles_bp = Blueprint("articles", __name__)


def _parse_int(value: str | None, default: int | None = None) -> int | None:
    """Parse a query-param int, returning ``default`` on missing/invalid."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: str | None) -> bool | None:
    """Parse a query-param boolean. Returns None when the param is absent."""
    if value is None or value == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


@articles_bp.route("/articles", methods=["GET"])
def list_articles():
    """Return a page of articles (req 1.4, 1.4a, 1.4c).

    Query params: page, page_size (25/50/100), sort, order, source_name,
    source_type, language, urgency_min, urgency_max, date_from, date_to,
    pipeline_status, event_type, has_alert, q (search query).

    When ``q`` is provided, the search composes with every filter parameter
    plus ``sort``/``order`` (req 1.4c): the request returns articles whose
    title or summary matches the query AND that satisfy all other filters.
    FTS rank ordering is used as the default sort under search only when no
    explicit ``sort`` parameter is provided; an explicit ``sort`` overrides
    rank ordering.
    """
    args = request.args

    page = _parse_int(args.get("page"), 1) or 1
    page_size = _parse_int(args.get("page_size"), DEFAULT_PAGE_SIZE)
    if page_size not in ALLOWED_PAGE_SIZES:
        page_size = DEFAULT_PAGE_SIZE

    query = (args.get("q") or "").strip()

    # Build the filters dict from query params -- used by both search and list.
    filters = {
        "source_name": args.get("source_name"),
        "source_type": args.get("source_type"),
        "language": args.get("language"),
        "urgency_min": _parse_int(args.get("urgency_min")),
        "urgency_max": _parse_int(args.get("urgency_max")),
        "date_from": args.get("date_from"),
        "date_to": args.get("date_to"),
        "pipeline_status": args.get("pipeline_status"),
        "event_type": args.get("event_type"),
        "has_alert": _parse_bool(args.get("has_alert")),
    }

    # Detect whether the caller explicitly asked for a sort. Under search this
    # determines FTS rank vs explicit-sort ordering (req 1.4c).
    explicit_sort = args.get("sort")
    sort = explicit_sort or "published_at"
    order = args.get("order", "desc")

    db = get_db()
    try:
        if query:
            result = db.search_articles(
                query,
                filters=filters,
                sort=explicit_sort,  # None when no explicit sort was given
                order=order,
                page=page,
                page_size=page_size,
            )
        else:
            result = db.get_articles(
                filters=filters,
                sort=sort,
                order=order,
                page=page,
                page_size=page_size,
            )
    finally:
        db.close()

    return jsonify(result)


@articles_bp.route("/articles/<article_id>", methods=["GET"])
def article_detail(article_id: str):
    """Return one article with classification, classifier input, events.

    Includes (req 1.5, 1.5a, 1.5b):
      * the full article + nested classification
      * ``classifier_input`` -- the reconstructed text sent to the classifier
      * ``events`` -- linked events, each with their ``alert_records``

    Returns HTTP 404 when no article has the given id.
    """
    db = get_db()
    try:
        article = db.get_article_detail(article_id)
    finally:
        db.close()

    if article is None:
        return jsonify({"error": "Article not found"}), 404

    article["classifier_input"] = build_classifier_input(article)
    return jsonify(article)
