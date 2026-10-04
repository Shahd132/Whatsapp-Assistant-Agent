"""Structured (JSON-lines) logging to stdout and data/app.log.

Rule: never put message text, coordinates or phone numbers in a log line.
Log lengths, flags and an anonymised contact id (anon()) instead.
"""
import hashlib
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logger: logging.Logger | None = None


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": round(record.created, 3), "level": record.levelname.lower(), "event": record.getMessage()}
        data.update(getattr(record, "fields", {}))
        return json.dumps(data, ensure_ascii=False, default=str)


def _get() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("assistant")
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        fmt = _JsonFormatter()
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        path = Path(os.getenv("APP_LOG_FILE") or Path(__file__).resolve().parent.parent / "data" / "app.log")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
        except OSError:
            pass  # file logging is a bonus
        for h in handlers:
            h.setFormatter(fmt)
            _logger.addHandler(h)
    return _logger


def log_event(event: str, level: str = "info", **fields) -> None:
    _get().log(getattr(logging, level.upper(), logging.INFO), event, extra={"fields": fields})


def anon(identifier: str) -> str:
    """Stable short id for a chat, so you can follow one conversation in the logs without storing who it is."""
    return hashlib.sha256(identifier.encode()).hexdigest()[:8]
