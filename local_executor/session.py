from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .credentials import CredentialEnrollment, TopstepCredentials


class LocalSessionError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


@dataclass(frozen=True, repr=False)
class SessionToken:
    value: str
    expires_at: datetime

    def __repr__(self) -> str:
        return "SessionToken(value='[REDACTED]', expires_at=<redacted>)"


class MemoryOnlySessionManager:
    """Owns a provider session only for the lifetime of this Python object."""

    def __init__(
        self,
        enrollment: CredentialEnrollment,
        authenticate: Callable[[TopstepCredentials], SessionToken],
        validate: Callable[[str], SessionToken] | None = None,
    ) -> None:
        self._enrollment = enrollment
        self._authenticate = authenticate
        self._validate = validate
        self._session: SessionToken | None = None

    @property
    def has_session(self) -> bool:
        return self._session is not None

    def get_token(self, *, now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        if self._session is not None and self._session.expires_at > current:
            return self._session.value
        credentials = self._enrollment.load_topstep()
        try:
            session = self._authenticate(credentials)
        except Exception:
            self._session = None
            raise LocalSessionError("provider_authentication_failed") from None
        self._validate_token(session, current)
        self._session = session
        return session.value

    def renew(self, *, now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        if self._session is None or self._validate is None:
            return self.get_token(now=current)
        try:
            session = self._validate(self._session.value)
        except Exception:
            self._session = None
            raise LocalSessionError("provider_session_renewal_failed") from None
        self._validate_token(session, current)
        self._session = session
        return session.value

    def clear(self) -> None:
        self._session = None

    def safe_status(self) -> dict[str, object]:
        return {
            "has_session": self._session is not None,
            "expires_at": self._session.expires_at.isoformat() if self._session else None,
        }

    @staticmethod
    def _validate_token(session: SessionToken, now: datetime) -> None:
        if not session.value or session.expires_at <= now:
            raise LocalSessionError("provider_session_invalid")
