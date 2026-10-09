"""Logging: readable lines on the console, JSON lines in logs/jobscout.log.

Use `logging.getLogger(__name__)` anywhere and pass structured fields via `extra`:

    log.info("collected postings", extra={"source": "greenhouse", "count": 42})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Attributes every LogRecord has; anything else came in through `extra`.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message"}


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<7} {record.getMessage()}"
        extras = _extras(record)
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    root = logging.getLogger("jobscout")
    root.setLevel(level)
    root.handlers.clear()
    root.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "jobscout.log", maxBytes=5_000_000, backupCount=5)
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
