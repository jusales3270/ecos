"""Structured logging helpers for ECOS."""

import json
import logging
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from ecos.core.settings import Settings

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id() -> str:
    """Return the current correlation identifier."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set and return the current correlation identifier."""
    value = correlation_id or str(uuid4())
    _correlation_id.set(value)
    return value


class CorrelationIdFilter(logging.Filter):
    """Inject the current correlation identifier into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach correlation_id to a log record."""
        record.correlation_id = get_correlation_id()
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a structured JSON representation of the log record."""
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


class _EcosStreamHandler(logging.StreamHandler):
    """Stream handler owned by the ECOS logging configuration."""


def configure_logging(settings: Settings) -> None:
    """Configure process-wide structured logging."""
    handler = _EcosStreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(CorrelationIdFilter())

    root_logger = logging.getLogger()
    root_logger.handlers[:] = [
        existing
        for existing in root_logger.handlers
        if not isinstance(existing, _EcosStreamHandler)
    ]
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
