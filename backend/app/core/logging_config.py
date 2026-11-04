"""Logging setup with rotating file handler and sensitive data redaction."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
from typing import Any

from backend.app.core.config import settings


class SensitiveDataRedactionFilter(logging.Filter):
    """Filter that strips tokens, passwords, and RTSP credentials from log records."""

    @staticmethod
    def redact(text: str) -> str:
        if not isinstance(text, str):
            return text
        # Redact token parameter in URLs/queries (e.g., token=xyz or &token=xyz)
        text = re.sub(r"(token=)[^&\s'\"]+", r"\1REDACTED", text, flags=re.IGNORECASE)
        # Redact RTSP credentials: rtsp://user:password@host
        text = re.sub(r"(rtsp://[^:]+:)[^@]+(@)", r"\1***\2", text, flags=re.IGNORECASE)
        # Redact passwords in JSON strings
        text = re.sub(r'("password"\s*:\s*)"[^"]+"', r'\1"***"', text, flags=re.IGNORECASE)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (self.redact(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    (self.redact(item) if isinstance(item, str) else item)
                    for item in record.args
                )
        return True


def setup_logging() -> logging.Logger:
    """Configure root and uvicorn loggers with rotation and redaction filter."""
    logger = logging.getLogger("traffic_ai")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on reload
    if logger.handlers:
        return logger

    log_file = settings.logs_dir / "backend.log"
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    redaction_filter = SensitiveDataRedactionFilter()
    file_handler.addFilter(redaction_filter)
    console_handler.addFilter(redaction_filter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Also attach the filter to uvicorn access logs so URL tokens are redacted
    for uvicorn_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        u_logger = logging.getLogger(uvicorn_name)
        u_logger.addFilter(redaction_filter)

    return logger
