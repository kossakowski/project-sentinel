"""Annotation database layer for the Article Dashboard (Phase 4).

`AnnotationDB` manages a small, write-capable SQLite database at
``dashboard/data/annotations.db`` holding user-supplied annotations on
articles (correctness label, expected urgency, free-text notes). It lives in
its OWN file so that a fresh production-DB sync (which overwrites
``sentinel.db`` byte-for-byte) never blows away annotation work — the user's
labels persist across syncs and are joined back to articles by ``article_id``
at query time (see ``dashboard.db.DashboardDB._maybe_attach_annotations``).

Schema (single table, one row per article):

    CREATE TABLE annotations (
        id TEXT PRIMARY KEY,                -- UUID
        article_id TEXT NOT NULL UNIQUE,    -- FK -> sentinel.articles(id)
        label TEXT NOT NULL,                -- "correct" | "incorrect" | "uncertain"
        expected_urgency INTEGER,           -- 1-10, nullable
        notes TEXT,                         -- free-text, nullable
        created_at TEXT NOT NULL,           -- ISO 8601 UTC
        updated_at TEXT NOT NULL            -- ISO 8601 UTC
    )

The file + table are auto-created on first access (req 4.1a). Upsert semantics
preserve ``created_at`` on update so a re-labelled article keeps its original
creation timestamp while the ``updated_at`` ticks forward (req 4.1b).
"""

import os
import sqlite3
import uuid
from datetime import UTC, datetime

from dashboard import config

# Validation whitelists. Kept module-level so the API layer can reuse them
# without re-importing them through the DB class.
ALLOWED_LABELS: tuple[str, ...] = ("correct", "incorrect", "uncertain")
MIN_URGENCY = 1
MAX_URGENCY = 10

# Whitelisted sort columns for the list endpoint. Kept narrow on purpose —
# arbitrary column names cannot be SQL-parameterised, so the API never lets
# user input near the ORDER BY without going through this dict first.
_ALLOWED_SORT_COLUMNS: dict[str, str] = {
    "created_at": "ann.created_at",
    "updated_at": "ann.updated_at",
    "label": "ann.label",
    "expected_urgency": "ann.expected_urgency",
}

_DEFAULT_SORT = "updated_at"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    expected_urgency INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class AnnotationValidationError(ValueError):
    """Raised when an annotation payload fails validation.

    Carries a short human-readable message; the API layer maps this to a
    400 response with ``{"error": <message>}``.
    """


def _utc_now_iso() -> str:
    """Return the current UTC instant as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def validate_label(label: object) -> str:
    """Return ``label`` if it is one of the allowed strings, else raise.

    Used by both the DB layer (defence-in-depth on upsert) and the API layer
    (to produce the right HTTP error before touching the DB).
    """
    if not isinstance(label, str) or label not in ALLOWED_LABELS:
        raise AnnotationValidationError("Invalid label")
    return label


def validate_expected_urgency(value: object) -> int | None:
    """Validate ``value`` is None or an int in [1, 10].

    Booleans are rejected even though Python treats them as ``int`` subtypes
    — accepting ``True`` as urgency 1 would be a confusing footgun.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly.
        raise AnnotationValidationError("Invalid expected_urgency")
    if not isinstance(value, int):
        raise AnnotationValidationError("Invalid expected_urgency")
    if value < MIN_URGENCY or value > MAX_URGENCY:
        raise AnnotationValidationError("Invalid expected_urgency")
    return value


class AnnotationDB:
    """Write-capable SQLite store for per-article annotations.

    Opens its own connection on construction and keeps it for the lifetime of
    the instance. The DB file + ``annotations`` table are created on first
    access (req 4.1a). Designed to be short-lived in the API request scope:
    the Flask blueprint constructs one per request, runs one operation, and
    closes — concurrent writes are extremely rare in a single-user dashboard.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Open / create the annotations DB and ensure the table exists.

        Args:
            db_path: Path to the SQLite file. Defaults to
                ``config.ANNOTATIONS_DB_PATH``. The parent directory is
                created on demand so a fresh install never has to manually
                ``mkdir dashboard/data`` before annotating its first article.
        """
        self.db_path = db_path or config.ANNOTATIONS_DB_PATH
        # mkdir -p the data dir so the SQLite file open succeeds on a fresh
        # checkout where ``dashboard/data/`` does not yet exist.
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Foreign keys are not declared on this table (article_id references
        # the *other* DB), but turning the pragma on is a harmless future-
        # proofing in case we ever co-locate.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self.conn.close()

    def __enter__(self) -> "AnnotationDB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Row -> dict helper
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Render an ``annotations`` row as the API-facing dict shape."""
        return {
            "id": row["id"],
            "article_id": row["article_id"],
            "label": row["label"],
            "expected_urgency": row["expected_urgency"],
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, article_id: str) -> dict | None:
        """Return the annotation for ``article_id``, or None when none exists."""
        row = self.conn.execute(
            "SELECT id, article_id, label, expected_urgency, notes, created_at, updated_at "
            "FROM annotations WHERE article_id = ?",
            (article_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(
        self,
        *,
        label: str | None = None,
        sort: str | None = None,
        order: str = "desc",
        page: int = 1,
        page_size: int = 50,
        sentinel_db_path: str | None = None,
    ) -> dict:
        """Return paginated annotations with optional ``article`` context (req 4.2b).

        When ``sentinel_db_path`` is supplied, the sentinel DB is briefly
        ATTACHed so each annotation row can be enriched with the article's
        ``title`` + classification ``urgency_score`` for the UI. Articles
        that no longer exist in the sentinel DB (e.g. after a sync that
        dropped them) still surface with ``title=None`` and
        ``urgency_score=None`` rather than vanishing — the annotation work
        itself remains the user's source of truth.

        Pagination + sorting mirror the article list contract for UI parity.

        Args:
            label: optional ``correct``/``incorrect``/``uncertain`` filter.
            sort: one of the keys of `_ALLOWED_SORT_COLUMNS`. Defaults to
                ``updated_at``.
            order: ``asc`` or ``desc`` (default).
            page: 1-based page number.
            page_size: rows per page; clamped to >= 1.
            sentinel_db_path: optional path to the sentinel DB for the
                article-title + urgency join (req 4.2b).
        """
        page = max(1, int(page))
        page_size = max(1, int(page_size))

        sort_expr = _ALLOWED_SORT_COLUMNS.get(sort or _DEFAULT_SORT, _ALLOWED_SORT_COLUMNS[_DEFAULT_SORT])
        direction = "ASC" if str(order).lower() == "asc" else "DESC"

        clauses: list[str] = []
        params: list = []
        if label is not None:
            # Defensive validation: list() may be called from places other
            # than the API (e.g. tests, future tooling) so re-validate here.
            validate_label(label)
            clauses.append("ann.label = ?")
            params.append(label)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""

        # ATTACH the sentinel DB on a separate, short-lived connection so the
        # primary AnnotationDB connection is never polluted with cross-DB
        # state. Reuse the existing connection when no sentinel path is
        # given (no join required, simpler query).
        if sentinel_db_path and os.path.exists(sentinel_db_path):
            # Build a fresh connection ATTACHing the sentinel DB read-only.
            # `?mode=ro` mirrors how DashboardDB opens the sentinel DB.
            join_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            join_conn.row_factory = sqlite3.Row
            try:
                join_conn.execute(
                    "ATTACH DATABASE ? AS sentinel",
                    (f"file:{os.path.abspath(sentinel_db_path)}?mode=ro",),
                )
            except sqlite3.Error:
                # ATTACH failed — fall back to the title-less query so the
                # endpoint still returns annotations rather than 500ing.
                join_conn.close()
                return self._list_without_articles(where_sql, params, sort_expr, direction, page, page_size)

            try:
                total = join_conn.execute("SELECT COUNT(*) FROM annotations ann" + where_sql, params).fetchone()[0]
                offset = (page - 1) * page_size
                rows = join_conn.execute(
                    "SELECT ann.id, ann.article_id, ann.label, ann.expected_urgency, "
                    "ann.notes, ann.created_at, ann.updated_at, "
                    "a.title AS article_title, c.urgency_score AS article_urgency_score "
                    "FROM annotations ann "
                    "LEFT JOIN sentinel.articles a ON a.id = ann.article_id "
                    "LEFT JOIN sentinel.classifications c ON c.article_id = ann.article_id"
                    f"{where_sql} "
                    f"ORDER BY {sort_expr} {direction}, ann.id {direction} "
                    "LIMIT ? OFFSET ?",
                    [*params, page_size, offset],
                ).fetchall()
            finally:
                join_conn.close()

            annotations = []
            for row in rows:
                payload = self._row_to_dict(row)
                payload["article_title"] = row["article_title"]
                payload["article_urgency_score"] = row["article_urgency_score"]
                annotations.append(payload)

            total_pages = (total + page_size - 1) // page_size
            return {
                "annotations": annotations,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }

        return self._list_without_articles(where_sql, params, sort_expr, direction, page, page_size)

    def _list_without_articles(
        self,
        where_sql: str,
        params: list,
        sort_expr: str,
        direction: str,
        page: int,
        page_size: int,
    ) -> dict:
        """List annotations with no sentinel-DB join (article_title is null)."""
        total = self.conn.execute("SELECT COUNT(*) FROM annotations ann" + where_sql, params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = self.conn.execute(
            "SELECT ann.id, ann.article_id, ann.label, ann.expected_urgency, "
            "ann.notes, ann.created_at, ann.updated_at "
            "FROM annotations ann"
            f"{where_sql} "
            f"ORDER BY {sort_expr} {direction}, ann.id {direction} "
            "LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
        annotations = []
        for row in rows:
            payload = self._row_to_dict(row)
            payload["article_title"] = None
            payload["article_urgency_score"] = None
            annotations.append(payload)
        total_pages = (total + page_size - 1) // page_size
        return {
            "annotations": annotations,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert(
        self,
        article_id: str,
        *,
        label: str,
        expected_urgency: int | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create or update the annotation for ``article_id`` (req 4.1b).

        Uses ``INSERT ... ON CONFLICT(article_id) DO UPDATE`` so an existing
        annotation keeps its original ``id`` + ``created_at`` while ``label``,
        ``expected_urgency``, ``notes``, and ``updated_at`` are refreshed.
        Preserving ``created_at`` matches the user's mental model: they're
        editing a label they already created, not starting over.
        """
        if not article_id or not isinstance(article_id, str):
            raise AnnotationValidationError("Invalid article_id")
        validate_label(label)
        validate_expected_urgency(expected_urgency)

        now = _utc_now_iso()
        new_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO annotations (id, article_id, label, expected_urgency, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(article_id) DO UPDATE SET "
            "    label = excluded.label, "
            "    expected_urgency = excluded.expected_urgency, "
            "    notes = excluded.notes, "
            "    updated_at = excluded.updated_at",
            (new_id, article_id, label, expected_urgency, notes, now, now),
        )
        self.conn.commit()
        return self.get(article_id) or {}

    def delete(self, article_id: str) -> bool:
        """Delete the annotation for ``article_id``. Returns True if removed."""
        cur = self.conn.execute("DELETE FROM annotations WHERE article_id = ?", (article_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Aggregates (used by /api/stats — see dashboard.db.get_stats)
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return summary counts for the dashboard /api/stats payload.

        Keys: ``total``, ``by_label`` (per allowed label with zero-fill).
        Urgency-deviation is computed on the sentinel DB side because it
        needs the classifier's ``urgency_score`` — see
        ``dashboard.db.DashboardDB.get_stats``.
        """
        total = self.conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        by_label_raw = {
            row["label"]: row["n"]
            for row in self.conn.execute("SELECT label, COUNT(*) AS n FROM annotations GROUP BY label").fetchall()
        }
        by_label = {label: int(by_label_raw.get(label, 0)) for label in ALLOWED_LABELS}
        return {"total": int(total), "by_label": by_label}
