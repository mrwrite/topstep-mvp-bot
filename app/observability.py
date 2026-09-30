from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SECRET_KEYS = re.compile(
    r"(password|passwd|secret|token|api[-_]?key|authorization|credential|cookie|session|"
    r"verification|reset[-_]?code|private[-_]?key|client[-_]?secret)",
    re.IGNORECASE,
)
SENSITIVE_QUERY_KEYS = re.compile(
    r"^(access_token|refresh_token|token|api[-_]?key|key|secret|password|code|"
    r"session|authorization)$",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[-_]?key|authorization|credential|"
    r"session[-_]?token|refresh[-_]?token|verification[-_]?token|reset[-_]?token)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)


def redact_text(value: str) -> str:
    text = BEARER_PATTERN.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    text = JWT_PATTERN.sub("[REDACTED]", text)
    text = ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )
    try:
        parsed = urlsplit(text)
        if parsed.scheme and parsed.netloc and parsed.query:
            query = [
                (key, "[REDACTED]" if SENSITIVE_QUERY_KEYS.search(key) else item)
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            ]
            text = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
            )
    except ValueError:
        pass
    return text[:2048] + ("..." if len(text) > 2048 else "")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if SECRET_KEYS.search(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": redact_text(str(value))}
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_exception(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": redact_text(str(exc))}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        extras = getattr(record, "event", None)
        if isinstance(extras, dict):
            payload.update(redact(extras))
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(redact(payload), default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def log_event(logger_name: str, event_type: str, **event: Any) -> None:
    logger = logging.getLogger(logger_name)
    logger.info(event_type, extra={"event": {"event_type": event_type, **redact(event)}})
