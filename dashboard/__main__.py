"""Module entry point so ``python -m dashboard`` starts the dashboard.

Delegates to `dashboard.cli.main`, which parses arguments and launches the
Flask server.
"""

import sys

from dashboard.cli import main

if __name__ == "__main__":
    sys.exit(main())
