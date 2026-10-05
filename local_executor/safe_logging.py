from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable
from uuid import UUID, uuid4


_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "password",
        "secret",
        "token",
        "session_token",
        "api_key",
        "apikey",
        "credentials",
        "username",
    }
)
_INLINE_SECRET = re.compile(
    r"(?i)(authorization|bearer|password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)


class SecretRedactor:
    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        self._secret_values = tuple(value for value in secret_values if value)

    def _text(self, value: str) -> str:
        redacted = value
        for secret in self._secret_values:
            redacted = redacted.replace(secret, "[REDACTED]")
        return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and key.lower().replace("-", "_") in _SENSITIVE_KEYS:
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): self.redact(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self._text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._text(str(value))


def safe_correlation_id(value: str | None = None) -> str:
    if value is None:
        return uuid4().hex
    try:
        return UUID(value).hex
    except (ValueError, AttributeError, TypeError):
        return uuid4().hex


class LocalJsonFormatter(logging.Formatter):
    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        super().__init__()
        self.redactor = redactor or SecretRedactor()

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": safe_correlation_id(
                getattr(record, "correlation_id", None)
            ),
        }
        fields = getattr(record, "safe_fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(self.redactor.redact(payload), sort_keys=True, separators=(",", ":"))


def configure_local_logging(
    *, secret_values: Iterable[str] = (), level: int = logging.INFO
) -> logging.Logger:
    logger = logging.getLogger("local_executor")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(LocalJsonFormatter(SecretRedactor(secret_values)))
    logger.addHandler(handler)
    return logger
