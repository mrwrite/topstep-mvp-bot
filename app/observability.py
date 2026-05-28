from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from typing import Any


SECRET_KEYS = re.compile(r"(password|secret|token|apikey|api_key|authorization|credential)", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if SECRET_KEYS.search(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str) and len(value) > 128:
        return value[:125] + "..."
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = getattr(record, "event", None)
        if isinstance(extras, dict):
            payload.update(redact(extras))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


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
