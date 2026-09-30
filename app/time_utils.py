from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return an aware UTC timestamp for new durable-execution code."""

    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize database timestamps, including legacy naive UTC values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
