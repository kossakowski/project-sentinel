"""Article list / detail / search API endpoints.

Routes (registered under the ``/api`` prefix by `dashboard.app`):

* ``GET /api/articles``            -- paginated, filtered, sorted list + search
* ``GET /api/articles/<id>``       -- full article detail with classifier input
"""

from datetime import datetime

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


def _validate_iso_date(value: str | None) -> str | None:
    """Validate ``value`` as an ISO-8601 date / datetime.

    Returns ``None`` when the value is valid (or empty -- absent filter), and
    a short error string describing the problem when it is not. The full
    calendar is enforced via ``datetime.fromisoformat`` so impossible dates
    like ``2026-13-01``, ``2026-02-30``, or ``2026-05-22T25:00`` are rejected
    -- the previous shape-only regex let those through and SQLite's lex
    comparison silently returned wrong-or-empty results.

    Accepts ``YYYY-MM-DD`` and ``YYYY-MM-DDTHH:MM[:SS[.fff]][Z|±HH:MM]``.
    A trailing ``Z`` is normalised to ``+00:00`` for compatibility with
    Python versions whose ``fromisoformat`` predates 3.11's ``Z`` support.
    """
    if value is None or value == "":
        return None
    # Normalise a trailing "Z" (Zulu / UTC) so the value parses on Python
    # versions whose fromisoformat doesn't accept it directly.
    normalised = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalised)
    except (TypeError, ValueError):
        return f"Expected ISO 8601 (YYYY-MM-DD or full datetime), got {value!r}"
    return None


@articles_bp.route("/articles", methods=["GET"])
def list_articles():
    """Return a page of articles (req 1.4, 1.4a, 1.4c).

    Query params: page, page_size (25/50/100), sort, order, source_name,
    source_type, language, urgency_min, urgency_max, date_from, date_to,
    pipeline_status, event_type, has_alert, q (search query).

    ``date_from`` and ``date_to`` accept ISO-8601 dates (``YYYY-MM-DD``) or
    full datetimes (``YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM]``). A bare ``date_to``
    is interpreted INCLUSIVELY of the whole day (it expands to end-of-day at
    the DB layer), so ``date_to=2026-05-17`` returns every article published
    on 2026-05-17. Calendar-impossible values (``2026-13-01``, ``2026-02-30``,
    hour 25 etc.) are rejected with HTTP 400.

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

    # Validate date filters at the API boundary -- ``published_at`` is an
    # ISO-8601 string column, so non-ISO inputs would silently misbehave under
    # lex comparison. Validate BOTH endpoints and surface both errors at once
    # so a user with two bad dates gets one round-trip, not two.
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    field_errors: dict[str, str] = {}
    for label, value in (("date_from", date_from), ("date_to", date_to)):
        error = _validate_iso_date(value)
        if error is not None:
            field_errors[label] = error
    if field_errors:
        return (
            jsonify({"error": "Invalid ISO date(s)", "fields": field_errors}),
            400,
        )

    # Build the filters dict from query params -- used by both search and list.
    filters = {
        "source_name": args.get("source_name"),
        "source_type": args.get("source_type"),
        "language": args.get("language"),
        "urgency_min": _parse_int(args.get("urgency_min")),
        "urgency_max": _parse_int(args.get("urgency_max")),
        "date_from": date_from,
        "date_to": date_to,
        "pipeline_status": args.get("pipeline_status"),
        "event_type": args.get("event_type"),
        "has_alert": _parse_bool(args.get("has_alert")),
    }

    # Detect whether the caller explicitly asked for a sort. Under search this
    # determines FTS rank vs explicit-sort ordering (req 1.4c). An empty-string
    # ``sort=`` is normalised to None here so it consistently means "use the
    # default" -- search then uses FTS rank, list uses published_at desc.
    explicit_sort = args.get("sort") or None
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
