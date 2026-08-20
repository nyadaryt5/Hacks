"""Central logging configuration for ULTRON.

Provides :func:`configure_logging` with human-readable or JSON (structured)
output, an optional file sink, and a :class:`JsonFormatter` that attaches
``extra={"structured": {...}}`` key/values to the emitted JSON record.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# Third-party loggers that are chatty at INFO.
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "chromadb")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record (structlog-style)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(structured)
        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Configure the root logger.

    Idempotent: replaces previously installed handlers so repeated calls
    (e.g. in tests or embedding apps) do not duplicate output.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    stream_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        stream_handler.setFormatter(JsonFormatter())
    else:
        stream_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
    root.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        if json_format:
            file_handler.setFormatter(JsonFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(LOG_FORMAT, datefmt=_DATE_FORMAT)
            )
        root.addHandler(file_handler)

    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return root


__all__ = ["JsonFormatter", "configure_logging", "LOG_FORMAT"]
