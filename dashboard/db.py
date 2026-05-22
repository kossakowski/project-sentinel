"""Database access layer for the Article Dashboard.

`DashboardDB` is a separate, read-only access layer over Project Sentinel's
SQLite database. It deliberately does NOT reuse `sentinel.database.Database`
(which is read-write and creates tables) -- the dashboard must never modify
production data. It supports two connection modes:

* **local** (default): opens the synced SQLite file directly in read-only mode.
* **tunnel**: SCPs a fresh temporary copy of the production DB on connect
  (no port-forwarding -- the production DB is a plain file with no remote query
  service, so ``ssh -L`` would target nothing). When this class is constructed
  with ``tunnel=True`` and no ``db_path``, it fetches a fresh copy and owns the
  temp file (removed on close). When constructed with ``tunnel=True`` and an
  explicit ``db_path``, it treats the path as an already-fetched copy (the app
  factory pre-fetches once at startup; per-request connections then reuse that
  file -- see `dashboard.app.create_app`).

FTS5 full-text search is used when an `articles_fts` index exists (built by
`dashboard.sync` into a separate DB file and ATTACHed here); otherwise search
falls back to a `LIKE` scan. The temporary copy used in tunnel mode has no FTS
index, so tunnel-mode search always uses the LIKE fallback.
"""

import contextlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta

from dashboard import config

# Bare ``YYYY-MM-DD`` (no time portion). When ``date_to`` matches this shape,
# we normalise to end-of-day so the filter is inclusive of the whole day,
# rather than lex-comparing against ``"2026-05-17"`` and excluding every
# row whose ``published_at`` starts ``"2026-05-17T..."``.
_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Latest ISO timestamp within a single day; appending this to a bare date
# produces a lexicographically-correct upper bound for SQLite's TEXT column.
_END_OF_DAY_SUFFIX = "T23:59:59.999999"

# Whitelisted sort columns -> the SQL expression they map to. Whitelisting
# prevents SQL injection via the `sort` parameter (column names cannot be
# parameterized). `urgency_score` and `confidence` live on the joined
# classifications table.
_SORT_COLUMNS = {
    "published_at": "a.published_at",
    "fetched_at": "a.fetched_at",
    "urgency_score": "c.urgency_score",
    "source_name": "a.source_name",
    "title": "a.title",
    "confidence": "c.confidence",
}

# Allowed page sizes for the API (req 1.4).
ALLOWED_PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50

# Default sort column when no explicit ``sort`` is supplied. Used by both the
# list path (`get_articles`) and the search path (`search_articles`) so the
# default is defined exactly once -- preventing the two paths from drifting.
DEFAULT_SORT = "published_at"


class DashboardDBError(RuntimeError):
    """Raised when the dashboard cannot open the sentinel database.

    The most common cause is that no DB has been synced yet (the local file
    does not exist). API endpoints catch this and return a clean JSON error
    instead of a 500, so a fresh install degrades gracefully.
    """


class DashboardDB:
    """Read-only SQLite access layer for the sentinel database."""

    def __init__(
        self,
        db_path: str | None = None,
        tunnel: bool = False,
        fts_db_path: str | None = None,
    ) -> None:
        """Open a read-only connection to the sentinel database.

        Args:
            db_path: Path to the local sentinel SQLite file. In ``tunnel`` mode
                this is interpreted as the path to an already-fetched temporary
                copy (typical when the app factory pre-fetches once at startup
                and many request-scoped DashboardDB instances share that file);
                when None in ``tunnel`` mode, this instance fetches its own
                temp copy via SCP and owns its lifecycle. Defaults to
                ``config.DEFAULT_DB_PATH`` in non-tunnel mode.
            tunnel: When True, open against the production server's DB. With
                ``db_path`` set, the path is treated as pre-fetched; otherwise
                this instance performs the SCP itself.
            fts_db_path: Path to the separate FTS index database. Defaults to
                ``config.FTS_DB_PATH``. When the file exists it is ATTACHed and
                full-text search uses it.
        """
        self.tunnel = tunnel
        self.db_path = db_path or config.DEFAULT_DB_PATH
        self.fts_db_path = fts_db_path or config.FTS_DB_PATH
        # Path to the temporary DB copy fetched in tunnel mode (None otherwise).
        # Removed on close() ONLY when this instance fetched it itself; when
        # the caller pre-fetched and passed ``db_path``, cleanup is the
        # caller's responsibility (the app factory tears it down on shutdown).
        self._tunnel_tempfile: str | None = None
        self._fts_available = False

        if tunnel and db_path is None:
            # Self-fetching tunnel mode: own the temp file end-to-end.
            self.conn = self._connect_via_tunnel()
        else:
            # Either local mode, or tunnel mode with a pre-fetched db_path
            # (the app factory uses this branch -- one SCP per process).
            self.conn = self._connect_local()

        self.conn.row_factory = sqlite3.Row
        self._maybe_attach_fts()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect_local(self) -> sqlite3.Connection:
        """Open the local SQLite file in read-only mode via a file: URI.

        Raises `DashboardDBError` when the file does not exist -- SQLite's
        read-only mode refuses to create a missing file, and a clear error is
        far more useful than a bare OperationalError.
        """
        abs_path = os.path.abspath(self.db_path)
        if not os.path.exists(abs_path):
            raise DashboardDBError(
                f"Sentinel database not found at {abs_path}. "
                "Run a sync first (POST /api/sync, the --sync CLI flag, "
                "or ./dashboard/run-dashboard.sh --sync)."
            )
        uri = f"file:{abs_path}?mode=ro"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    def _connect_via_tunnel(self) -> sqlite3.Connection:
        """SCP a fresh copy of the production DB and open it read-only.

        The production sentinel DB is a plain SQLite file with no remote query
        service, so port-forwarding (``ssh -L``) would target nothing. Instead
        we use ``scp`` to copy the file into a fresh temporary local path on
        every connection. The temp file is opened with ``?mode=ro`` and removed
        on ``close()``, so each session gets data current as of the moment it
        started (req 1.1c / 1.2a).

        The SCP invocation uses ``BatchMode=yes`` (no interactive prompts) and
        the configured SSH port + user. FTS5 is not built for the temp copy, so
        search falls back to LIKE in tunnel mode.
        """
        # mkstemp gives us a unique path without the cleanup-on-GC behaviour
        # of NamedTemporaryFile: we hand the path to scp / sqlite and tear it
        # down ourselves in close()/atexit.
        fd, path = tempfile.mkstemp(prefix="dashboard_tunnel_", suffix=".db")
        os.close(fd)
        self._tunnel_tempfile = path

        try:
            result = subprocess.run(
                [
                    "scp",
                    "-P",
                    str(config.SSH_PORT),
                    "-o",
                    "BatchMode=yes",
                    config.scp_source(),
                    self._tunnel_tempfile,
                ],
                capture_output=True,
                text=True,
                timeout=config.SCP_TIMEOUT_SECONDS,
            )
        except Exception:
            self._remove_tunnel_tempfile()
            raise

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            self._remove_tunnel_tempfile()
            raise RuntimeError(f"SSH tunnel DB fetch failed: {stderr}")

        uri = f"file:{os.path.abspath(self._tunnel_tempfile)}?mode=ro"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    def _remove_tunnel_tempfile(self) -> None:
        """Remove the temp DB copy fetched in tunnel mode, if any."""
        path = self._tunnel_tempfile
        if path is None:
            return
        self._tunnel_tempfile = None
        # Already gone, or never created -- nothing to clean up.
        with contextlib.suppress(OSError):
            os.remove(path)

    def detach_tempfile(self) -> str | None:
        """Detach and return the path of the tunnel-mode temp DB, if any.

        Transfers ownership of the temp file FROM this `DashboardDB` TO the
        caller: after this call, ``close()`` will no longer delete the file,
        and the caller is responsible for removing it.

        Returns the path (still on disk) or ``None`` when this instance does
        not own a temp file -- i.e. local mode, pre-fetched tunnel mode (a
        ``db_path`` was supplied), or a second call after ownership was
        already detached. Calling it on non-tunnel instances or twice in a
        row is safe (idempotent): the second call simply returns ``None``.
        Used by the app factory's startup bootstrap to keep the SCP'd file
        alive for the lifetime of the Flask app.
        """
        path = self._tunnel_tempfile
        self._tunnel_tempfile = None
        return path

    def _maybe_attach_fts(self) -> None:
        """ATTACH the FTS index DB if it exists and holds an articles_fts table.

        In **tunnel mode** the FTS index is intentionally never attached: the
        SCP'd temp copy has no co-located FTS DB, and any locally present FTS
        file (from a prior ``--sync``) is STALE relative to the freshly fetched
        production rows. Attaching it would silently return wrong/empty hits.
        Spec req 1.1c is explicit: "FTS5 is not built for the temporary copy,
        so search falls back to LIKE." So tunnel mode short-circuits here and
        leaves `self._fts_available = False` -- ``search_articles`` then takes
        the LIKE branch on every query.
        """
        if self.tunnel:
            # Tunnel mode contract: no FTS, always LIKE fallback (req 1.1c).
            self._fts_available = False
            return
        if not os.path.exists(self.fts_db_path):
            self._fts_available = False
            return
        try:
            self.conn.execute("ATTACH DATABASE ? AS fts", (os.path.abspath(self.fts_db_path),))
            row = self.conn.execute(
                "SELECT name FROM fts.sqlite_master WHERE type = 'table' AND name = 'articles_fts'"
            ).fetchone()
            self._fts_available = row is not None
        except sqlite3.Error:
            self._fts_available = False

    @property
    def fts_available(self) -> bool:
        """True when an FTS5 `articles_fts` index is attached and usable."""
        return self._fts_available

    def close(self) -> None:
        """Close the DB connection and remove the tunnel temp copy if any."""
        try:
            self.conn.close()
        finally:
            self._remove_tunnel_tempfile()

    def __enter__(self) -> "DashboardDB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Row -> dict helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(value: str | None) -> list:
        """Parse a JSON-array text column into a list, tolerating bad data."""
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _classification_from_row(row: sqlite3.Row) -> dict | None:
        """Build the nested `classification` dict from a joined row, or None.

        The query LEFT JOINs classifications; an unclassified article yields
        NULLs for every classification column, in which case None is returned.
        """
        if row["classification_id"] is None:
            return None
        return {
            "id": row["classification_id"],
            "is_military_event": bool(row["is_military_event"]),
            "event_type": row["event_type"],
            "urgency_score": row["urgency_score"],
            "affected_countries": DashboardDB._parse_json_list(row["affected_countries"]),
            "aggressor": row["aggressor"],
            "is_new_event": bool(row["is_new_event"]) if row["is_new_event"] is not None else None,
            "confidence": row["confidence"],
            "summary_pl": row["summary_pl"],
            "classified_at": row["classified_at"],
            "model_used": row["model_used"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
        }

    def _article_from_row(self, row: sqlite3.Row) -> dict:
        """Build a full article dict (with nested classification + status)."""
        classification = self._classification_from_row(row)
        has_alert = bool(row["alert_count"])
        pipeline_status = self._derive_pipeline_status(
            classification is not None,
            event_created=bool(row["event_count"]),
            alert_sent=has_alert,
        )
        return {
            "id": row["id"],
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "source_type": row["source_type"],
            "title": row["title"],
            "summary": row["summary"],
            "language": row["language"],
            "published_at": row["published_at"],
            "fetched_at": row["fetched_at"],
            "classification": classification,
            "pipeline_status": pipeline_status,
            "has_alert": has_alert,
        }

    @staticmethod
    def _derive_pipeline_status(is_classified: bool, event_created: bool, alert_sent: bool) -> str:
        """Map join results to a pipeline status string (req 1.4b).

        Order matters: an article with an alert is also event_created and
        classified -- the most advanced stage reached wins.
        """
        if alert_sent:
            return "alert_sent"
        if event_created:
            return "event_created"
        if is_classified:
            return "classified"
        return "unclassified"

    # ------------------------------------------------------------------
    # WHERE-clause builder shared by get_articles + count
    # ------------------------------------------------------------------

    def _build_filters(self, filters: dict) -> tuple[str, list]:
        """Translate a filters dict into a SQL WHERE fragment + bound params.

        Returns ('' , []) when there are no filters. The fragment, when not
        empty, starts with ' WHERE '. Every value is parameterized.
        """
        filters = filters or {}
        clauses: list[str] = []
        params: list = []

        if filters.get("source_name"):
            clauses.append("a.source_name = ?")
            params.append(filters["source_name"])

        if filters.get("source_type"):
            clauses.append("a.source_type = ?")
            params.append(filters["source_type"])

        if filters.get("language"):
            clauses.append("a.language = ?")
            params.append(filters["language"])

        if filters.get("event_type"):
            clauses.append("c.event_type = ?")
            params.append(filters["event_type"])

        if filters.get("urgency_min") is not None:
            clauses.append("c.urgency_score >= ?")
            params.append(int(filters["urgency_min"]))

        if filters.get("urgency_max") is not None:
            clauses.append("c.urgency_score <= ?")
            params.append(int(filters["urgency_max"]))

        if filters.get("date_from"):
            clauses.append("a.published_at >= ?")
            params.append(filters["date_from"])

        if filters.get("date_to"):
            # Bare ``YYYY-MM-DD`` upper bounds expand to end-of-day so the
            # whole day is included. ``published_at`` is a full ISO-8601
            # string like ``"2026-05-17T04:00:00..."``, so lex-comparing
            # against ``"2026-05-17"`` would EXCLUDE the entire day (every
            # row sorts strictly greater than the bare-date prefix). A
            # value that already carries a time portion is passed through.
            date_to = filters["date_to"]
            if _BARE_DATE_RE.match(date_to):
                date_to = date_to + _END_OF_DAY_SUFFIX
            clauses.append("a.published_at <= ?")
            params.append(date_to)

        pipeline_status = filters.get("pipeline_status")
        if pipeline_status and pipeline_status != "all":
            if pipeline_status == "unclassified":
                clauses.append("c.id IS NULL")
            elif pipeline_status == "classified":
                # "classified" tab includes classified, event_created,
                # alert_sent -- i.e. anything that reached classification.
                clauses.append("c.id IS NOT NULL")
            elif pipeline_status == "event_created":
                # SQL does not allow referencing a SELECT-list alias in
                # WHERE, so the correlated subqueries are inlined here.
                clauses.append(f"{self._EVENT_COUNT_SQL} > 0")
            elif pipeline_status == "alert_sent":
                clauses.append(f"{self._ALERT_COUNT_SQL} > 0")

        has_alert = filters.get("has_alert")
        if has_alert is not None:
            if has_alert:
                clauses.append(f"{self._ALERT_COUNT_SQL} > 0")
            else:
                clauses.append(f"{self._ALERT_COUNT_SQL} = 0")

        if not clauses:
            return "", params
        return " WHERE " + " AND ".join(clauses), params

    # ------------------------------------------------------------------
    # SQL building blocks
    # ------------------------------------------------------------------

    # Per-article correlated subqueries computing event/alert counts. An
    # article is "event_created" when its id appears in any events.article_ids
    # JSON array; "alert_sent" when one of those events has alert_records.
    # json_each expands the JSON array so the membership test is index-free
    # but correct.
    _EVENT_COUNT_SQL = (
        "(SELECT COUNT(*) FROM events e "
        " WHERE EXISTS (SELECT 1 FROM json_each(e.article_ids) je "
        "               WHERE je.value = a.id))"
    )
    _ALERT_COUNT_SQL = (
        "(SELECT COUNT(*) FROM alert_records ar "
        " WHERE ar.event_id IN ("
        "   SELECT e.id FROM events e "
        "   WHERE EXISTS (SELECT 1 FROM json_each(e.article_ids) je "
        "                 WHERE je.value = a.id)))"
    )

    # Article columns that every list/detail query needs to populate
    # `_article_from_row`. `raw_metadata` is intentionally excluded here -- it
    # is a JSON blob used only by `get_article_detail`, so list/search queries
    # avoid reading and discarding it per row (low-severity I/O cleanup).
    _LIST_ARTICLE_COLUMNS = (
        "a.id, a.source_name, a.source_url, a.source_type, a.title, a.summary, a.language, a.published_at, a.fetched_at"
    )

    def _list_select_columns(self) -> str:
        """Lean SELECT column list for ``get_articles`` / ``search_articles``.

        Includes the classification join columns and event/alert count
        subqueries needed by `_article_from_row`. Omits ``raw_metadata`` --
        only ``get_article_detail`` reads it.
        """
        return (
            f"{self._LIST_ARTICLE_COLUMNS}, "
            "c.id AS classification_id, c.is_military_event, c.event_type, "
            "c.urgency_score, c.affected_countries, c.aggressor, "
            "c.is_new_event, c.confidence, c.summary_pl, c.classified_at, "
            "c.model_used, c.input_tokens, c.output_tokens, "
            f"{self._EVENT_COUNT_SQL} AS event_count, "
            f"{self._ALERT_COUNT_SQL} AS alert_count"
        )

    def _detail_select_columns(self) -> str:
        """SELECT column list for ``get_article_detail``.

        Same as `_list_select_columns` plus ``a.raw_metadata`` -- the detail
        endpoint exposes the parsed metadata blob to the dashboard.
        """
        return (
            f"{self._LIST_ARTICLE_COLUMNS}, a.raw_metadata, "
            "c.id AS classification_id, c.is_military_event, c.event_type, "
            "c.urgency_score, c.affected_countries, c.aggressor, "
            "c.is_new_event, c.confidence, c.summary_pl, c.classified_at, "
            "c.model_used, c.input_tokens, c.output_tokens, "
            f"{self._EVENT_COUNT_SQL} AS event_count, "
            f"{self._ALERT_COUNT_SQL} AS alert_count"
        )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_articles(
        self,
        filters: dict | None = None,
        sort: str = "published_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """Return paginated, sorted, filtered articles with classification join.

        Args:
            filters: dict with any of: source_name, source_type, language,
                urgency_min, urgency_max, date_from, date_to, pipeline_status
                ("all"|"classified"|"unclassified"|"event_created"|
                "alert_sent"), event_type, has_alert (bool).
            sort: one of the keys of `_SORT_COLUMNS`.
            order: "asc" or "desc".
            page: 1-based page number.
            page_size: rows per page.

        Returns:
            dict with keys: articles (list), total (int), page (int),
            page_size (int), total_pages (int).
        """
        page = max(1, int(page))
        page_size = int(page_size)
        if page_size <= 0:
            page_size = DEFAULT_PAGE_SIZE

        sort_expr = _SORT_COLUMNS.get(sort, _SORT_COLUMNS[DEFAULT_SORT])
        direction = "ASC" if str(order).lower() == "asc" else "DESC"

        where_sql, params = self._build_filters(filters or {})
        base = " FROM articles a LEFT JOIN classifications c ON c.article_id = a.id" + where_sql

        total = self.conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0]

        offset = (page - 1) * page_size
        # Stable secondary sort on a.id so equal sort keys paginate predictably.
        rows = self.conn.execute(
            f"SELECT {self._list_select_columns()}{base} "
            f"ORDER BY {sort_expr} {direction}, a.id {direction} "
            "LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size
        return {
            "articles": [self._article_from_row(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_article_detail(self, article_id: str) -> dict | None:
        """Return the full article joined with classification, events, alerts.

        Returns None when no article has the given id. The result dict has the
        same shape as a `get_articles` row plus:

        * ``raw_metadata`` -- parsed JSON object (or {})
        * ``events`` -- list of linked events, each with an ``alert_records``
          list (req 1.5b)
        """
        row = self.conn.execute(
            f"SELECT {self._detail_select_columns()} "
            "FROM articles a "
            "LEFT JOIN classifications c ON c.article_id = a.id "
            "WHERE a.id = ?",
            (article_id,),
        ).fetchone()
        if row is None:
            return None

        article = self._article_from_row(row)
        try:
            article["raw_metadata"] = json.loads(row["raw_metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            article["raw_metadata"] = {}
        article["events"] = self._events_for_article(article_id)
        return article

    def _events_for_article(self, article_id: str) -> list[dict]:
        """Return events whose article_ids JSON contains this article id.

        Fetches all linked events in one query, then all alert_records for
        those events in a single ``IN`` query, and groups them by event_id in
        Python. This avoids the N+1 pattern of running one alert query per
        event when an article is linked to multiple events.
        """
        event_rows = self.conn.execute(
            "SELECT e.* FROM events e "
            "WHERE EXISTS (SELECT 1 FROM json_each(e.article_ids) je "
            "              WHERE je.value = ?) "
            "ORDER BY e.first_seen_at",
            (article_id,),
        ).fetchall()

        if not event_rows:
            return []

        # Fetch all alert_records for the matched event ids in ONE query, then
        # group by event_id. Placeholders are generated dynamically (one ? per
        # id) -- safe because the ids are server-issued UUIDs we just SELECTed.
        # SQLite caps compiled-statement variables at SQLITE_MAX_VARIABLE_NUMBER
        # (default 999 on older builds, 32766 on builds since 3.32). This is
        # effectively unreachable on the current dataset (501 events total, and
        # an article is realistically linked to at most a handful), so no
        # chunking is needed -- documented here in case events-per-article ever
        # spikes orders of magnitude beyond today's distribution.
        event_ids = [ev["id"] for ev in event_rows]
        placeholders = ",".join("?" * len(event_ids))
        alert_rows = self.conn.execute(
            f"SELECT * FROM alert_records WHERE event_id IN ({placeholders}) ORDER BY sent_at",
            event_ids,
        ).fetchall()
        alerts_by_event: dict[str, list[dict]] = {eid: [] for eid in event_ids}
        for ar in alert_rows:
            alerts_by_event[ar["event_id"]].append(
                {
                    "id": ar["id"],
                    "event_id": ar["event_id"],
                    "alert_type": ar["alert_type"],
                    "twilio_sid": ar["twilio_sid"],
                    "status": ar["status"],
                    "duration_seconds": ar["duration_seconds"],
                    "attempt_number": ar["attempt_number"],
                    "sent_at": ar["sent_at"],
                    "message_body": ar["message_body"],
                }
            )

        events: list[dict] = []
        for ev in event_rows:
            events.append(
                {
                    "id": ev["id"],
                    "event_type": ev["event_type"],
                    "urgency_score": ev["urgency_score"],
                    "affected_countries": self._parse_json_list(ev["affected_countries"]),
                    "aggressor": ev["aggressor"],
                    "summary_pl": ev["summary_pl"],
                    "first_seen_at": ev["first_seen_at"],
                    "last_updated_at": ev["last_updated_at"],
                    "source_count": ev["source_count"],
                    "article_ids": self._parse_json_list(ev["article_ids"]),
                    "alert_status": ev["alert_status"],
                    "acknowledged_at": ev["acknowledged_at"],
                    "alert_records": alerts_by_event[ev["id"]],
                }
            )
        return events

    def search_articles(
        self,
        query: str,
        filters: dict | None = None,
        sort: str | None = None,
        order: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """Full-text search across article title + summary, composable with filters.

        Args:
            query: search terms (whitespace-separated, AND-ed by FTS5).
            filters: same shape as ``get_articles`` -- composed with the search
                via AND (req 1.4c).
            sort: same whitelist as ``get_articles``. When None (no explicit
                sort), FTS results are ordered by relevance rank and LIKE
                results by published_at DESC. When an explicit sort is given,
                it overrides the default rank/date ordering.
            order: "asc" or "desc". When None, defaults to "desc".
            page: 1-based page number.
            page_size: rows per page.

        Returns the same shape as ``get_articles``.

        Uses the FTS5 `articles_fts` index when available; otherwise falls
        back to a LIKE scan over title and summary.
        """
        page = max(1, int(page))
        page_size = int(page_size)
        if page_size <= 0:
            page_size = DEFAULT_PAGE_SIZE
        offset = (page - 1) * page_size

        query = (query or "").strip()
        if not query:
            return {
                "articles": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0,
            }

        # explicit_sort: caller provided a sort column override.
        explicit_sort = sort is not None
        effective_sort = sort or DEFAULT_SORT
        effective_order = order or "desc"

        if self._fts_available:
            return self._search_fts(
                query,
                filters or {},
                effective_sort,
                effective_order,
                explicit_sort,
                page,
                page_size,
                offset,
            )
        return self._search_like(
            query,
            filters or {},
            effective_sort,
            effective_order,
            explicit_sort,
            page,
            page_size,
            offset,
        )

    def _search_fts(
        self,
        query: str,
        filters: dict,
        sort: str,
        order: str,
        explicit_sort: bool,
        page: int,
        page_size: int,
        offset: int,
    ) -> dict:
        """FTS5-backed search; rank-ordered by default, overridable by sort."""
        match_query = self._fts_match_query(query)

        where_sql, filter_params = self._build_filters(filters)
        # Combine the FTS MATCH predicate with the filter predicates.
        if where_sql:
            where_clause = " WHERE f.articles_fts MATCH ? AND " + where_sql.removeprefix(" WHERE ")
        else:
            where_clause = " WHERE f.articles_fts MATCH ?"

        base = (
            " FROM fts.articles_fts f "
            "JOIN articles a ON a.id = f.article_id "
            "LEFT JOIN classifications c ON c.article_id = a.id" + where_clause
        )

        total = self.conn.execute(
            "SELECT COUNT(*)" + base,
            [match_query, *filter_params],
        ).fetchone()[0]

        # Order by rank ascending = best first; explicit sort overrides.
        if explicit_sort:
            sort_expr = _SORT_COLUMNS.get(sort, _SORT_COLUMNS[DEFAULT_SORT])
            direction = "ASC" if str(order).lower() == "asc" else "DESC"
            order_clause = f"ORDER BY {sort_expr} {direction}, a.id {direction}"
        else:
            order_clause = "ORDER BY f.rank, a.id ASC"

        rows = self.conn.execute(
            f"SELECT {self._list_select_columns()}{base} {order_clause} LIMIT ? OFFSET ?",
            [match_query, *filter_params, page_size, offset],
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size
        return {
            "articles": [self._article_from_row(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @staticmethod
    def _fts_match_query(query: str) -> str:
        """Build a safe FTS5 MATCH expression from raw user input.

        Each whitespace-separated token is wrapped in double quotes (with any
        embedded double quotes doubled, per FTS5 string syntax) so punctuation
        and FTS operator characters in user input cannot break the query or be
        interpreted as operators. Tokens are implicitly AND-ed by FTS5.
        ``search_articles`` returns early on empty input, so this function is
        always called with at least one token.
        """
        tokens = query.split()
        quoted = ['"' + tok.replace('"', '""') + '"' for tok in tokens]
        return " ".join(quoted)

    def _search_like(
        self,
        query: str,
        filters: dict,
        sort: str,
        order: str,
        explicit_sort: bool,
        page: int,
        page_size: int,
        offset: int,
    ) -> dict:
        """LIKE-based fallback search when no FTS5 index exists."""
        # Escape LIKE wildcards in user input; use an explicit ESCAPE clause.
        # We use '|' (vertical bar) as the ESCAPE character rather than '\\':
        # backslash works but the double-escaping in Python literals
        # ("\\\\" -> SQL '\\') is hard to read, and SQLite's LIKE has no
        # special semantics for backslash by default (so the Python-to-SQL
        # mapping is easy to misread). '|' is a single ASCII character that
        # never appears as a LIKE metacharacter and reads cleanly here.
        escaped = query.replace("|", "||").replace("%", "|%").replace("_", "|_")
        like = f"%{escaped}%"

        where_sql, filter_params = self._build_filters(filters)
        like_clause = "(a.title LIKE ? ESCAPE '|' OR a.summary LIKE ? ESCAPE '|')"
        if where_sql:
            where_clause = " WHERE " + like_clause + " AND " + where_sql.removeprefix(" WHERE ")
        else:
            where_clause = " WHERE " + like_clause

        base = " FROM articles a LEFT JOIN classifications c ON c.article_id = a.id" + where_clause

        total = self.conn.execute(
            "SELECT COUNT(*)" + base,
            [like, like, *filter_params],
        ).fetchone()[0]

        # Default LIKE ordering: most-recent first. Explicit sort overrides.
        if explicit_sort:
            sort_expr = _SORT_COLUMNS.get(sort, _SORT_COLUMNS[DEFAULT_SORT])
            direction = "ASC" if str(order).lower() == "asc" else "DESC"
            order_clause = f"ORDER BY {sort_expr} {direction}, a.id {direction}"
        else:
            order_clause = "ORDER BY a.published_at DESC, a.id DESC"

        rows = self.conn.execute(
            f"SELECT {self._list_select_columns()}{base} {order_clause} LIMIT ? OFFSET ?",
            [like, like, *filter_params, page_size, offset],
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size
        return {
            "articles": [self._article_from_row(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_stats(self) -> dict:
        """Return aggregate pipeline + distribution statistics (req 1.2e).

        Keys: total_articles, total_classified, total_events, total_alerts,
        articles_per_day (last 30 days incl. zero days), urgency_distribution,
        source_distribution, language_distribution, event_type_distribution,
        pipeline_funnel.
        """
        cur = self.conn

        total_articles = cur.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        total_classified = cur.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        total_events = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        total_alerts = cur.execute("SELECT COUNT(*) FROM alert_records").fetchone()[0]

        # Articles per day for the last 30 days, including days with zero
        # articles (req 1.6a). Build the full 30-day calendar, then overlay
        # the DB counts keyed by YYYY-MM-DD.
        raw_per_day = cur.execute(
            "SELECT substr(published_at, 1, 10) AS day, COUNT(*) AS n "
            "FROM articles "
            "WHERE substr(published_at, 1, 10) >= ? "
            "GROUP BY day",
            ((datetime.now(UTC) - timedelta(days=29)).strftime("%Y-%m-%d"),),
        ).fetchall()
        counts_by_day = {r["day"]: r["n"] for r in raw_per_day}
        today = datetime.now(UTC).date()
        articles_per_day = []
        for offset in range(29, -1, -1):
            day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            articles_per_day.append({"date": day, "count": counts_by_day.get(day, 0)})

        # Urgency distribution: count per score 1-10, including zero buckets.
        urgency_raw = {
            r["urgency_score"]: r["n"]
            for r in cur.execute(
                "SELECT urgency_score, COUNT(*) AS n FROM classifications GROUP BY urgency_score"
            ).fetchall()
        }
        urgency_distribution = [{"urgency_score": score, "count": urgency_raw.get(score, 0)} for score in range(1, 11)]

        source_distribution = [
            {"source_name": r["source_name"], "count": r["n"]}
            for r in cur.execute(
                "SELECT source_name, COUNT(*) AS n FROM articles GROUP BY source_name ORDER BY n DESC"
            ).fetchall()
        ]

        language_distribution = [
            {"language": r["language"], "count": r["n"]}
            for r in cur.execute(
                "SELECT language, COUNT(*) AS n FROM articles GROUP BY language ORDER BY n DESC"
            ).fetchall()
        ]

        event_type_distribution = [
            {"event_type": r["event_type"], "count": r["n"]}
            for r in cur.execute(
                "SELECT event_type, COUNT(*) AS n FROM events GROUP BY event_type ORDER BY n DESC"
            ).fetchall()
        ]

        # Pipeline funnel: collected -> classified -> events_created ->
        # alerts_sent (req 1.6b). events_created counts distinct articles that
        # reached an event; alerts_sent counts distinct articles whose event
        # produced an alert.
        events_created = cur.execute(
            "SELECT COUNT(DISTINCT je.value) FROM events e, json_each(e.article_ids) je"
        ).fetchone()[0]
        alerts_sent = cur.execute(
            "SELECT COUNT(DISTINCT je.value) "
            "FROM events e, json_each(e.article_ids) je "
            "WHERE e.id IN (SELECT event_id FROM alert_records)"
        ).fetchone()[0]

        return {
            "total_articles": total_articles,
            "total_classified": total_classified,
            "total_events": total_events,
            "total_alerts": total_alerts,
            "articles_per_day": articles_per_day,
            "urgency_distribution": urgency_distribution,
            "source_distribution": source_distribution,
            "language_distribution": language_distribution,
            "event_type_distribution": event_type_distribution,
            "pipeline_funnel": {
                "collected": total_articles,
                "classified": total_classified,
                "events_created": events_created,
                "alerts_sent": alerts_sent,
            },
        }
