"""CLI entry point for the Article Dashboard.

Starts the Flask API server. Invoked via ``python -m dashboard`` (see
``dashboard/__main__.py``) or the ``run-dashboard.sh`` wrapper.

Flags (req 1.8):
  --port    Port for the Flask server (default 5001)
  --db      Path to the local sentinel SQLite DB
  --tunnel  Connect to the production DB via an SSH tunnel
  --sync    Sync the production DB locally before starting the server
"""

import argparse
import sys

from dashboard import config
from dashboard.app import create_app
from dashboard.sync import sync_db


def build_parser() -> argparse.ArgumentParser:
    """Construct the dashboard CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dashboard",
        description="Article Dashboard -- local web UI over the sentinel DB.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.DEFAULT_PORT,
        help=f"Port for the Flask server (default {config.DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--db",
        default=config.DEFAULT_DB_PATH,
        help="Path to the local sentinel SQLite database.",
    )
    parser.add_argument(
        "--tunnel",
        action="store_true",
        help="Connect to the production DB via an SSH tunnel.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync the production DB locally before starting the server.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code.

    Args:
        argv: argument list (defaults to ``sys.argv[1:]``).
    """
    args = build_parser().parse_args(argv)

    if args.sync:
        print("Syncing production database...")
        result = sync_db(db_path=args.db)
        if result.success:
            print(
                f"Sync OK: {result.article_count} articles, "
                f"{result.file_size:,} bytes, {result.duration:.1f}s"
            )
        else:
            print(f"Sync FAILED: {result.error}", file=sys.stderr)
            return 1

    app = create_app(db_path=args.db, tunnel=args.tunnel)
    print(f"Starting dashboard on http://127.0.0.1:{args.port}")
    # threaded=True so per-request SQLite connections run on worker threads;
    # this is a single-user localhost tool, so the dev server is sufficient.
    app.run(host="127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
