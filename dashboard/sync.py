"""Database sync: SCP the production sentinel DB locally + rebuild FTS5 index.

`sync_db()` is the high-level entry point. It is deliberately split into small,
individually testable units:

* `scp_database()` -- the network copy (subprocess SCP). Mock THIS in tests
  that must not touch the network.
* `build_fts_index()` -- the FTS5 virtual-table build. This runs against a
  local SQLite file and is exercised for real by the test suite (no network).

The FTS5 index lives in a SEPARATE database file (``sentinel_fts.db``) so the
synced ``sentinel.db`` stays byte-for-byte identical to production.
"""

import os
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass

from dashboard import config


@dataclass
class SyncResult:
    """Outcome of a `sync_db()` call (req 1.3b)."""

    success: bool
    file_size: int = 0  # bytes of the synced sentinel.db
    article_count: int = 0  # rows in the articles table after sync
    duration: float = 0.0  # wall-clock seconds for the whole sync
    error: str | None = None  # error message when success is False

    def to_dict(self) -> dict:
        """Return a plain-dict form for JSON responses."""
        return asdict(self)


def ensure_data_dir(data_dir: str | None = None) -> str:
    """Create the dashboard data directory if missing (req 1.3c).

    Returns the directory path.
    """
    target = data_dir or config.DATA_DIR
    os.makedirs(target, exist_ok=True)
    return target


def scp_database(dest_path: str) -> None:
    """Copy the production sentinel DB to ``dest_path`` via SCP.

    This is the single network-touching unit -- tests mock this function (or
    the `subprocess.run` it calls) to stay hermetic. Raises RuntimeError on a
    non-zero SCP exit code and TimeoutExpired if SCP hangs.
    """
    result = subprocess.run(
        [
            "scp",
            "-P",
            str(config.SSH_PORT),
            "-o",
            "BatchMode=yes",
            config.scp_source(),
            dest_path,
        ],
        capture_output=True,
        text=True,
        timeout=config.SCP_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SCP failed (exit {result.returncode}): {result.stderr.strip()}")


def build_fts_index(db_path: str, fts_db_path: str | None = None) -> int:
    """Build (or rebuild) the FTS5 `articles_fts` index for ``db_path``.

    The FTS5 virtual table is created in a SEPARATE database file
    (``fts_db_path``) which is ATTACHed to the source DB only for the duration
    of the build, so the synced ``sentinel.db`` is never modified. The index
    covers the ``title`` and ``summary`` columns and stores each article's
    ``id`` as an unindexed column so search results can be joined back to the
    full article rows.

    Returns the article count read from the same connection used to build the
    index -- callers (notably ``sync_db``) can reuse this rather than opening
    a second connection just to ``SELECT COUNT(*)``.

    This function performs the REAL FTS build -- it is exercised directly by
    the test suite against a local DB file and is never mocked.
    """
    fts_path = fts_db_path or config.FTS_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(fts_path)), exist_ok=True)

    # Rebuild from scratch: drop any stale FTS DB file so the index always
    # reflects the freshly synced data.
    if os.path.exists(fts_path):
        os.remove(fts_path)

    # Open the (read-only) source DB and attach a fresh writable FTS DB.
    src_uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(src_uri, uri=True)
    try:
        conn.execute("ATTACH DATABASE ? AS fts", (os.path.abspath(fts_path),))
        # `id` is UNINDEXED: stored for the join-back but not tokenized.
        conn.execute("CREATE VIRTUAL TABLE fts.articles_fts USING fts5(article_id UNINDEXED, title, summary)")
        conn.execute(
            "INSERT INTO fts.articles_fts (article_id, title, summary) "
            "SELECT id, title, COALESCE(summary, '') FROM main.articles"
        )
        conn.commit()
        # Read the count on the same connection -- avoids a second open of
        # the source DB just to SELECT COUNT(*).
        article_count = conn.execute("SELECT COUNT(*) FROM main.articles").fetchone()[0]
    finally:
        conn.close()
    return article_count


def sync_db(
    db_path: str | None = None,
    fts_db_path: str | None = None,
) -> SyncResult:
    """Sync the production DB locally and rebuild the FTS5 index.

    Steps:
      1. Ensure the local data directory exists (req 1.3c).
      2. SCP the production sentinel DB to ``db_path`` (req 1.3).
      3. Build the FTS5 ``articles_fts`` index into ``fts_db_path`` (req 1.3a)
         and capture the article count from that same connection.
      4. Return a `SyncResult` describing the outcome (req 1.3b).

    Any failure is captured and returned as ``SyncResult(success=False, ...)``
    rather than raised, so API callers get a structured response.
    """
    started = time.monotonic()
    dest = db_path or config.DEFAULT_DB_PATH
    fts_path = fts_db_path or config.FTS_DB_PATH

    try:
        ensure_data_dir(os.path.dirname(os.path.abspath(dest)))
        scp_database(dest)
        article_count = build_fts_index(dest, fts_path)

        return SyncResult(
            success=True,
            file_size=os.path.getsize(dest),
            article_count=article_count,
            duration=round(time.monotonic() - started, 3),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 -- surface any failure to caller
        return SyncResult(
            success=False,
            duration=round(time.monotonic() - started, 3),
            error=str(exc),
        )
