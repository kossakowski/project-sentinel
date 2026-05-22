"""Database access layer for the Article Dashboard.

`DashboardDB` is a separate, read-only access layer over Project Sentinel's
SQLite database. It deliberately does NOT reuse `sentinel.database.Database`
(which is read-write and creates tables) -- the dashboard must never modify
production data. It supports two connection modes:

* **local** (default): opens the synced SQLite file directly in read-only mode.
* **tunnel**: opens an SSH tunnel via `subprocess` and connects through it.

FTS5 full-text search is used when an `articles_fts` index exists (built by
`dashboard.sync` into a separate DB file and ATTACHed here); otherwise search
falls back to a `LIKE` scan.
"""

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone

from dashboard import config

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
            db_path: Path to the local sentinel SQLite file. Ignored when
                ``tunnel`` is True. Defaults to ``config.DEFAULT_DB_PATH``.
            tunnel: When True, open an SSH tunnel to the production server and
                connect through it instead of using a local file.
            fts_db_path: Path to the separate FTS index database. Defaults to
                ``config.FTS_DB_PATH``. When the file exists it is ATTACHed and
                full-text search uses it.
        """
        self.tunnel = tunnel
        self.db_path = db_path or config.DEFAULT_DB_PATH
        self.fts_db_path = fts_db_path or config.FTS_DB_PATH
        self._tunnel_proc: subprocess.Popen | None = None
        self._fts_available = False

        if tunnel:
            self.conn = self._connect_via_tunnel()
        else:
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
        """Establish an SSH tunnel to the production server and connect.

        The remote sentinel DB is a plain file, so we cannot "forward a port"
        to it directly. Instead we open an SSH master connection with a local
        port forward (`ssh -L`) kept alive in the background, then SCP the file
        through that already-authenticated channel into a temp local copy and
        open that copy read-only. The tunnel process is torn down on close().
        """
        local_copy = os.path.join(config.DATA_DIR, "sentinel_tunnel.db")
        os.makedirs(config.DATA_DIR, exist_ok=True)

        # Background SSH process holding the -L forward open. This satisfies
        # req 1.2a (use subprocess to establish an `ssh -L` tunnel) and gives a
        # live, authenticated channel; the file is then pulled over it.
        self._tunnel_proc = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-p", str(config.SSH_PORT),
                "-L",
                f"{config.TUNNEL_LOCAL_PORT}:127.0.0.1:{config.SSH_PORT}",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                config.ssh_target(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)  # Give the forward a moment to come up.

        result = subprocess.run(
            [
                "scp",
                "-P", str(config.SSH_PORT),
                "-o", "BatchMode=yes",
                config.scp_source(),
                local_copy,
            ],
            capture_output=True,
            text=True,
            timeout=config.SCP_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            self._kill_tunnel()
            raise RuntimeError(
                f"SSH tunnel DB fetch failed: {result.stderr.strip()}"
            )

        uri = f"file:{os.path.abspath(local_copy)}?mode=ro"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    def _kill_tunnel(self) -> None:
        """Terminate the background SSH tunnel process, if any."""
        if self._tunnel_proc is not None:
            self._tunnel_proc.terminate()
            try:
                self._tunnel_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._tunnel_proc.kill()
            self._tunnel_proc = None

    def _maybe_attach_fts(self) -> None:
        """ATTACH the FTS index DB if it exists and holds an articles_fts table."""
        if not os.path.exists(self.fts_db_path):
            self._fts_available = False
            return
        try:
            self.conn.execute(
                "ATTACH DATABASE ? AS fts", (os.path.abspath(self.fts_db_path),)
            )
            row = self.conn.execute(
                "SELECT name FROM fts.sqlite_master "
                "WHERE type = 'table' AND name = 'articles_fts'"
            ).fetchone()
            self._fts_available = row is not None
        except sqlite3.Error:
            self._fts_available = False

    @property
    def fts_available(self) -> bool:
        """True when an FTS5 `articles_fts` index is attached and usable."""
        return self._fts_available

    def close(self) -> None:
        """Close the DB connection and tear down the SSH tunnel if present."""
        try:
            self.conn.close()
        finally:
            self._kill_tunnel()

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
            "affected_countries": DashboardDB._parse_json_list(
                row["affected_countries"]
            ),
            "aggressor": row["aggressor"],
            "is_new_event": bool(row["is_new_event"])
            if row["is_new_event"] is not None
            else None,
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
    def _derive_pipeline_status(
        is_classified: bool, event_created: bool, alert_sent: bool
    ) -> str:
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
            clauses.append("a.published_at <= ?")
            params.append(filters["date_to"])

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

    def _select_columns(self) -> str:
        """Column list for article SELECTs, including the classification join."""
        return (
            "a.id, a.source_name, a.source_url, a.source_type, a.title, "
            "a.summary, a.language, a.published_at, a.fetched_at, "
            "a.raw_metadata, "
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

        sort_expr = _SORT_COLUMNS.get(sort, _SORT_COLUMNS["published_at"])
        direction = "ASC" if str(order).lower() == "asc" else "DESC"

        where_sql, params = self._build_filters(filters or {})
        base = (
            " FROM articles a "
            "LEFT JOIN classifications c ON c.article_id = a.id"
            + where_sql
        )

        total = self.conn.execute(
            "SELECT COUNT(*)" + base, params
        ).fetchone()[0]

        offset = (page - 1) * page_size
        # Stable secondary sort on a.id so equal sort keys paginate predictably.
        rows = self.conn.execute(
            f"SELECT {self._select_columns()}{base} "
            f"ORDER BY {sort_expr} {direction}, a.id {direction} "
            "LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size if page_size else 0
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
            f"SELECT {self._select_columns()} "
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
        """Return events whose article_ids JSON contains this article id."""
        event_rows = self.conn.execute(
            "SELECT e.* FROM events e "
            "WHERE EXISTS (SELECT 1 FROM json_each(e.article_ids) je "
            "              WHERE je.value = ?) "
            "ORDER BY e.first_seen_at",
            (article_id,),
        ).fetchall()

        events: list[dict] = []
        for ev in event_rows:
            alert_rows = self.conn.execute(
                "SELECT * FROM alert_records WHERE event_id = ? "
                "ORDER BY sent_at",
                (ev["id"],),
            ).fetchall()
            events.append(
                {
                    "id": ev["id"],
                    "event_type": ev["event_type"],
                    "urgency_score": ev["urgency_score"],
                    "affected_countries": self._parse_json_list(
                        ev["affected_countries"]
                    ),
                    "aggressor": ev["aggressor"],
                    "summary_pl": ev["summary_pl"],
                    "first_seen_at": ev["first_seen_at"],
                    "last_updated_at": ev["last_updated_at"],
                    "source_count": ev["source_count"],
                    "article_ids": self._parse_json_list(ev["article_ids"]),
                    "alert_status": ev["alert_status"],
                    "acknowledged_at": ev["acknowledged_at"],
                    "alert_records": [
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
                        for ar in alert_rows
                    ],
                }
            )
        return events

    def search_articles(
        self,
        query: str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """Full-text search across article title + summary.

        Uses the FTS5 `articles_fts` index when available, ordered by
        relevance rank; otherwise falls back to a LIKE scan over title and
        summary. Result shape matches `get_articles`.
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

        if self._fts_available:
            return self._search_fts(query, page, page_size, offset)
        return self._search_like(query, page, page_size, offset)

    def _search_fts(
        self, query: str, page: int, page_size: int, offset: int
    ) -> dict:
        """FTS5-backed search ordered by relevance rank."""
        match_query = self._fts_match_query(query)

        total = self.conn.execute(
            "SELECT COUNT(*) FROM fts.articles_fts WHERE articles_fts MATCH ?",
            (match_query,),
        ).fetchone()[0]

        # Join the FTS hits (carrying article id + rank) back to the full
        # article + classification rows. Order by rank ascending = best first.
        rows = self.conn.execute(
            f"SELECT {self._select_columns()} "
            "FROM fts.articles_fts f "
            "JOIN articles a ON a.id = f.article_id "
            "LEFT JOIN classifications c ON c.article_id = a.id "
            "WHERE f.articles_fts MATCH ? "
            "ORDER BY f.rank "
            "LIMIT ? OFFSET ?",
            (match_query, page_size, offset),
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size if page_size else 0
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
        """
        tokens = query.split()
        quoted = ['"' + tok.replace('"', '""') + '"' for tok in tokens]
        return " ".join(quoted) if quoted else '""'

    def _search_like(
        self, query: str, page: int, page_size: int, offset: int
    ) -> dict:
        """LIKE-based fallback search when no FTS5 index exists."""
        # Escape LIKE wildcards in user input; use an explicit ESCAPE clause.
        escaped = (
            query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        like = f"%{escaped}%"
        where = (
            " FROM articles a "
            "LEFT JOIN classifications c ON c.article_id = a.id "
            "WHERE a.title LIKE ? ESCAPE '\\' "
            "OR a.summary LIKE ? ESCAPE '\\'"
        )

        total = self.conn.execute(
            "SELECT COUNT(*)" + where, (like, like)
        ).fetchone()[0]

        rows = self.conn.execute(
            f"SELECT {self._select_columns()}{where} "
            "ORDER BY a.published_at DESC, a.id DESC "
            "LIMIT ? OFFSET ?",
            (like, like, page_size, offset),
        ).fetchall()

        total_pages = (total + page_size - 1) // page_size if page_size else 0
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

        total_articles = cur.execute(
            "SELECT COUNT(*) FROM articles"
        ).fetchone()[0]
        total_classified = cur.execute(
            "SELECT COUNT(*) FROM classifications"
        ).fetchone()[0]
        total_events = cur.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        total_alerts = cur.execute(
            "SELECT COUNT(*) FROM alert_records"
        ).fetchone()[0]

        # Articles per day for the last 30 days, including days with zero
        # articles (req 1.6a). Build the full 30-day calendar, then overlay
        # the DB counts keyed by YYYY-MM-DD.
        raw_per_day = cur.execute(
            "SELECT substr(published_at, 1, 10) AS day, COUNT(*) AS n "
            "FROM articles "
            "WHERE substr(published_at, 1, 10) >= ? "
            "GROUP BY day",
            ((datetime.now(timezone.utc) - timedelta(days=29)).strftime(
                "%Y-%m-%d"
            ),),
        ).fetchall()
        counts_by_day = {r["day"]: r["n"] for r in raw_per_day}
        today = datetime.now(timezone.utc).date()
        articles_per_day = []
        for offset in range(29, -1, -1):
            day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            articles_per_day.append(
                {"date": day, "count": counts_by_day.get(day, 0)}
            )

        # Urgency distribution: count per score 1-10, including zero buckets.
        urgency_raw = {
            r["urgency_score"]: r["n"]
            for r in cur.execute(
                "SELECT urgency_score, COUNT(*) AS n FROM classifications "
                "GROUP BY urgency_score"
            ).fetchall()
        }
        urgency_distribution = [
            {"urgency_score": score, "count": urgency_raw.get(score, 0)}
            for score in range(1, 11)
        ]

        source_distribution = [
            {"source_name": r["source_name"], "count": r["n"]}
            for r in cur.execute(
                "SELECT source_name, COUNT(*) AS n FROM articles "
                "GROUP BY source_name ORDER BY n DESC"
            ).fetchall()
        ]

        language_distribution = [
            {"language": r["language"], "count": r["n"]}
            for r in cur.execute(
                "SELECT language, COUNT(*) AS n FROM articles "
                "GROUP BY language ORDER BY n DESC"
            ).fetchall()
        ]

        event_type_distribution = [
            {"event_type": r["event_type"], "count": r["n"]}
            for r in cur.execute(
                "SELECT event_type, COUNT(*) AS n FROM events "
                "GROUP BY event_type ORDER BY n DESC"
            ).fetchall()
        ]

        # Pipeline funnel: collected -> classified -> events_created ->
        # alerts_sent (req 1.6b). events_created counts distinct articles that
        # reached an event; alerts_sent counts distinct articles whose event
        # produced an alert.
        events_created = cur.execute(
            "SELECT COUNT(DISTINCT je.value) "
            "FROM events e, json_each(e.article_ids) je"
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
