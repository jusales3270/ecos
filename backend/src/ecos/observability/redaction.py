"""Central redaction and canonicalization policy for persistent records."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any
from uuid import UUID

from ecos.observability.exceptions import SerializationError

REDACTED = "[REDACTED]"
TRUNCATED = "[TRUNCATED]"

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "cookie",
    "session_cookie",
    "private_key",
    "client_secret",
    "credential",
    "connection_string",
}


class RedactionPolicy:
    """Redact sensitive recursive structures without mutating the original."""

    def __init__(
        self,
        *,
        max_depth: int = 8,
        max_string_length: int = 500,
        max_items: int = 200,
    ) -> None:
        self.max_depth = max_depth
        self.max_string_length = max_string_length
        self.max_items = max_items

    def redact(self, value: Any) -> Any:
        """Return a safe JSON-serializable copy of value."""
        return self._redact(value, depth=0, key=None)

    def canonical_json(self, value: Any) -> str:
        """Serialize a redacted value to deterministic JSON."""
        safe = self.redact(value)
        try:
            return json.dumps(
                safe,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
                default=str,
            )
        except (TypeError, ValueError) as error:
            raise SerializationError("value is not JSON serializable") from error

    def _redact(self, value: Any, *, depth: int, key: str | None) -> Any:
        if key is not None and key.lower() in SENSITIVE_KEYS:
            return REDACTED
        if depth > self.max_depth:
            return TRUNCATED
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, float):
            if not isfinite(value):
                raise SerializationError("non-finite numeric values are not allowed")
            return value
        if isinstance(value, str):
            if len(value) > self.max_string_length:
                return f"{value[: self.max_string_length]}{TRUNCATED}"
            return value
        if isinstance(value, bytes | bytearray | memoryview):
            raise SerializationError("bytes cannot be persisted in observability data")
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise SerializationError("datetime values must be timezone-aware")
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            safe: dict[str, Any] = {}
            for index, (item_key, item_value) in enumerate(value.items()):
                if index >= self.max_items:
                    safe["_truncated"] = True
                    break
                safe_key = str(item_key)
                if safe_key.strip() == "":
                    raise SerializationError("blank keys cannot be persisted")
                safe[safe_key] = self._redact(
                    item_value,
                    depth=depth + 1,
                    key=safe_key,
                )
            return safe
        if isinstance(value, list | tuple | set | frozenset):
            return [
                self._redact(item, depth=depth + 1, key=None)
                for item in list(value)[: self.max_items]
            ]
        raise SerializationError(
            f"unsupported observability value: {type(value).__name__}"
        )


default_redaction_policy = RedactionPolicy()
