"""Centralized logging setup."""

from __future__ import annotations

import logging
import re
import sys


_TELEGRAM_TOKEN = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_URL_PASSWORD = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:)(?P<password>[^\s/@]+)(?=@)"
)


def redact_secrets(value: str) -> str:
    """Mask credentials that may be embedded in application or dependency logs."""
    value = _TELEGRAM_TOKEN.sub("[REDACTED_TELEGRAM_TOKEN]", value)
    return _URL_PASSWORD.sub(r"\g<prefix>[REDACTED]", value)


class RedactingFormatter(logging.Formatter):
    """Apply redaction after the message and traceback have been formatted."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger for console output."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)

    # Keep noisy third-party loggers quieter by default.
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
