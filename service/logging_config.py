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

        # Defaults to on. The thing you need when a local model misbehaves is
        # the exact bytes it was sent and sent back, and that is never the run
        # you thought to enable logging for. LOG_DIR="" turns it off.
        log_dir = os.environ.get("LOG_DIR", "logs")
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


def clip(value, limit: int = 2000):
    """Recursively shorten long strings so one dump cannot bury the log.

    The system prompt is thousands of tokens and identical every turn; the
    model's own output is the part worth reading, and it is short.
    """
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}… [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [clip(v, limit) for v in value]
    return value


def log_payload(logger: logging.Logger, label: str, payload, limit: int = 2000) -> None:
    """Dump a request or reply body, pretty-printed and clipped.

    Deliberately one line per key rather than one long line: this gets read by
    eye, and pasted into a chat with someone who is going to read it by eye too.

    These files hold the creator's own material — `logs/` is gitignored along
    with everything else that is not explicitly allowed, and it should stay
    that way.
    """
    import json

    try:
        body = json.dumps(clip(payload, limit), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        body = repr(payload)[:limit]
    logger.info("%s\n%s", label, body)
