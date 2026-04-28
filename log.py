"""Structured JSON logging for Replay."""

from __future__ import annotations

import json
import logging
import os
import sys
import time


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge all extra structured fields attached to the record, skipping
        # standard LogRecord attributes that are already captured above or
        # are internal Python logging bookkeeping.
        _SKIP = frozenset({
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "taskName",
        })
        for key, val in record.__dict__.items():
            if key not in _SKIP and not key.startswith("_") and val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup(name: str = "replay") -> logging.Logger:
    """Configure and return the application logger.

    Uses JSON format when LOG_FORMAT=json (default in production).
    Falls back to human-readable format when LOG_FORMAT=text.
    """
    log_format = os.environ.get("LOG_FORMAT", "json").lower()
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers on re-import
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    logger.addHandler(handler)

    # Prevent propagation to root logger (which may have basicConfig)
    logger.propagate = False

    return logger
