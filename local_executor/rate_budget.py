from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from .journal_models import ProviderRateBudget


class LocalRateLimitError(RuntimeError):
    def __init__(self, classification: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(classification)
        self.classification = classification
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class RateBudget:
    limit: int
    window_seconds: int


LOCAL_RATE_BUDGETS = {
    # Deliberately below the documented 50 requests / 30 seconds.
    "history": RateBudget(limit=45, window_seconds=30),
    # Deliberately below the documented 200 requests / 60 seconds.
    "general": RateBudget(limit=180, window_seconds=60),
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class DurableRateLimiter:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def acquire(self, bucket: str) -> None:
        budget = LOCAL_RATE_BUDGETS[bucket]
        now = _utc(self._clock())
        with self._session_factory.begin() as session:
            state = session.get(ProviderRateBudget, bucket)
            if state is None:
                state = ProviderRateBudget(bucket=bucket, window_started_at=now, request_count=0)
                session.add(state)
                session.flush()
            if state.cooldown_until is not None and _utc(state.cooldown_until) > now:
                remaining = max(1, int((_utc(state.cooldown_until) - now).total_seconds()))
                raise LocalRateLimitError("provider_rate_cooldown", retry_after_seconds=remaining)
            if now - _utc(state.window_started_at) >= timedelta(seconds=budget.window_seconds):
                state.window_started_at = now
                state.request_count = 0
                state.cooldown_until = None
            if state.request_count >= budget.limit:
                remaining = max(
                    1,
                    int((timedelta(seconds=budget.window_seconds) -
                         (now - _utc(state.window_started_at))).total_seconds()),
                )
                raise LocalRateLimitError("local_rate_budget_exhausted", retry_after_seconds=remaining)
            state.request_count += 1

    def record_provider_429(self, bucket: str, retry_after_seconds: int) -> None:
        now = _utc(self._clock())
        cooldown = max(1, min(int(retry_after_seconds), 300))
        with self._session_factory.begin() as session:
            state = session.get(ProviderRateBudget, bucket)
            if state is None:
                state = ProviderRateBudget(bucket=bucket, window_started_at=now, request_count=0)
                session.add(state)
            state.cooldown_until = now + timedelta(seconds=cooldown)
