"""Entry point: `tide-pod` console script."""

from __future__ import annotations

import logging
import os
import sys

from .app import TidePodApp


def main() -> int:
    log_level = os.environ.get("TIDE_POD_LOG", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = TidePodApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
