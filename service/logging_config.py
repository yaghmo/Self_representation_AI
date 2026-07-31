"""Logging setup, shared by the service, the runtime, and the CLI tools.

One place so every component formats the same way and a single env var moves
them all. Logs go to stderr always, and to `logs/<name>.log` as well when
LOG_DIR is set — stdout stays clean for tools that pipe their output.

    LOG_LEVEL=DEBUG   default INFO
    LOG_DIR=logs      unset means stderr only
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
DATE_FORMAT = "%H:%M:%S"

_configured: set[str] = set()


class ElapsedFilter(logging.Filter):
    """Adds `%(elapsed)s` — seconds since this logger was configured.

    Load times and token rates are the numbers that matter here, and wall-clock
    timestamps make you do the subtraction yourself.
    """

    def __init__(self) -> None:
        super().__init__()
        import time

        self._start = time.monotonic()

    def filter(self, record: logging.LogRecord) -> bool:
        import time

        record.elapsed = f"{time.monotonic() - self._start:7.2f}s"
        return True


def setup_logging(name: str = "app", level: str | None = None) -> logging.Logger:
    """Configure the root logger once, return a named child."""
    root = logging.getLogger()

    if "root" not in _configured:
        resolved = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
        root.setLevel(resolved)

        stderr = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
        root.addHandler(stderr)

        log_dir = os.environ.get("LOG_DIR")
        if log_dir:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(directory / f"{name}.log", encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
            root.addHandler(file_handler)

        # These are chatty and rarely what you are debugging.
        for noisy in ("httpx", "httpcore", "urllib3", "filelock", "watchfiles"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _configured.add("root")

    return logging.getLogger(name)


def get_logger(name: str) -> logging.Logger:
    """For modules that should not decide global configuration."""
    return logging.getLogger(name)
