"""Annotation API endpoints (Phase 4).

Routes (registered under the ``/api`` prefix by `dashboard.app`):

* ``POST   /api/annotations``              -- create / update annotation (upsert)
* ``GET    /api/annotations``              -- paginated list, optional label filter
* ``GET    /api/annotations/<article_id>`` -- single annotation, 404 if absent
* ``DELETE /api/annotations/<article_id>`` -- delete annotation, 204 on success

Each request opens its own short-lived `AnnotationDB`. The DB file + table
are auto-created on first access so a fresh install never needs a manual
``mkdir`` / ``CREATE TABLE`` before the first annotation lands (req 4.1a).
"""

from flask import Blueprint, current_app, jsonify, request

from dashboard import config
from dashboard.annotations import AnnotationDB, AnnotationValidationError, validate_label

annotations_bp = Blueprint("annotations", __name__)


def _get_annotation_db() -> AnnotationDB:
    """Open an `AnnotationDB` for the current request.

    Uses the path stashed on ``app.config["ANNOTATIONS_DB_PATH"]`` when
    present (so tests can point at a tmp file via ``create_app``); falls
    back to the module-level default otherwise.
    """
    cfg = current_app.config
    return AnnotationDB(db_path=cfg.get("ANNOTATIONS_DB_PATH") or config.ANNOTATIONS_DB_PATH)


def _sentinel_db_path() -> str | None:
    """Return the configured sentinel DB path (for the list-time join)."""
    return current_app.config.get("SENTINEL_DB_PATH") or config.DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# POST /api/annotations -- create / update (upsert)
# ---------------------------------------------------------------------------


@annotations_bp.route("/annotations", methods=["POST"])
def create_or_update_annotation():
    """Create or update the annotation for an article (req 4.2, 4.1b).

    Body (JSON):
        {
            "article_id": "<uuid>",      -- required
            "label": "correct"|"incorrect"|"uncertain",
            "expected_urgency": 1-10 | null,
            "notes": "<string>" | null
        }

    Validation:
        * Missing ``article_id`` -> 400.
        * Missing / invalid ``label`` -> 400 ``{"error": "Invalid label"}``.
        * Out-of-range ``expected_urgency`` -> 400.

    Returns 200 with the saved annotation dict (incl. ``id``, ``created_at``,
    ``updated_at``).
    """
    payload = request.get_json(silent=True) or {}
    article_id = payload.get("article_id")
    if not isinstance(article_id, str) or not article_id.strip():
        return jsonify({"error": "Missing article_id"}), 400

    label = payload.get("label")
    expected_urgency = payload.get("expected_urgency")
    notes = payload.get("notes")

    # Coerce empty string notes to None — keeps the DB column cleanly null
    # when the user clears the textarea, matching how the API client sends
    # absent values.
    if notes == "":
        notes = None

    try:
        validate_label(label)
        # validate_expected_urgency runs again inside upsert(); calling it
        # here lets us return a 400 BEFORE touching the DB on bad input.
        from dashboard.annotations import validate_expected_urgency

        validate_expected_urgency(expected_urgency)
    except AnnotationValidationError as err:
        return jsonify({"error": str(err)}), 400

    db = _get_annotation_db()
    try:
        saved = db.upsert(
            article_id.strip(),
            label=label,
            expected_urgency=expected_urgency,
            notes=notes,
        )
    finally:
        db.close()

    return jsonify(saved), 200


# ---------------------------------------------------------------------------
# GET /api/annotations -- paginated list with optional filter
# ---------------------------------------------------------------------------


@annotations_bp.route("/annotations", methods=["GET"])
def list_annotations():
    """Return paginated annotations with optional ``?label`` filter (req 4.2b).

    Query params:
        * ``label``     -- optional ``correct``/``incorrect``/``uncertain``.
        * ``sort``      -- ``updated_at`` (default) / ``created_at`` /
                            ``label`` / ``expected_urgency``.
        * ``order``     -- ``asc`` / ``desc`` (default).
        * ``page``      -- 1-based, defaults to 1.
        * ``page_size`` -- defaults to 50.

    Response shape:
        {
            "annotations": [{...annotation, article_title, article_urgency_score}],
            "total": int, "page": int, "page_size": int, "total_pages": int
        }
    """
    args = request.args

    label_arg = args.get("label")
    if label_arg is not None and label_arg != "":
        try:
            validate_label(label_arg)
        except AnnotationValidationError as err:
            return jsonify({"error": str(err)}), 400
    else:
        label_arg = None

    sort = args.get("sort") or None
    order = args.get("order") or "desc"

    try:
        page = max(1, int(args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, int(args.get("page_size", 50)))
    except (TypeError, ValueError):
        page_size = 50

    db = _get_annotation_db()
    try:
        result = db.list(
            label=label_arg,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
            sentinel_db_path=_sentinel_db_path(),
        )
    finally:
        db.close()
    return jsonify(result)


# ---------------------------------------------------------------------------
# GET /api/annotations/<article_id>
# ---------------------------------------------------------------------------


@annotations_bp.route("/annotations/<article_id>", methods=["GET"])
def get_annotation(article_id: str):
    """Return the annotation for ``article_id``, or HTTP 404 (req 4.2a)."""
    db = _get_annotation_db()
    try:
        annotation = db.get(article_id)
    finally:
        db.close()
    if annotation is None:
        return jsonify({"error": "Annotation not found"}), 404
    return jsonify(annotation)


# ---------------------------------------------------------------------------
# DELETE /api/annotations/<article_id>
# ---------------------------------------------------------------------------


@annotations_bp.route("/annotations/<article_id>", methods=["DELETE"])
def delete_annotation(article_id: str):
    """Delete the annotation for ``article_id`` and return HTTP 204 (req 4.2c).

    A delete on a non-existent annotation still returns 204 — DELETE is
    idempotent by HTTP convention, and the user-facing intent ("make sure
    there's no annotation here") is satisfied either way.
    """
    db = _get_annotation_db()
    try:
        db.delete(article_id)
    finally:
        db.close()
    return ("", 204)
