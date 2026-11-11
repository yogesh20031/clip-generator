"""Logging: stderr (never stdout — stdout is the MCP wire) plus a rotating file."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    # MCPServer() already installs a stderr handler via basicConfig; only add ours when nothing is there.
    if not root.handlers:
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(fmt)
        root.addHandler(stderr)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "viral-clipper.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # read-only location: keep going with stderr only
        root.warning("Could not open log file in %s: %s", log_dir, exc)

    # Third-party chatter we never want at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "numba", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
