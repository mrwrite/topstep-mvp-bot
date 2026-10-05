from __future__ import annotations

from dataclasses import dataclass

from .secret_store import SecretNotFound, SecretStore, SecretStoreUnavailable


TOPSTEP_USERNAME_SLOT = "topstep_username"
TOPSTEP_API_KEY_SLOT = "topstep_api_key"
TELEMETRY_CREDENTIAL_SLOT = "telemetry_credential"


@dataclass(frozen=True, repr=False)
class TopstepCredentials:
    username: str
    api_key: str

    def __repr__(self) -> str:
        return "TopstepCredentials(username='[REDACTED]', api_key='[REDACTED]')"


class CredentialEnrollment:
    def __init__(self, store: SecretStore) -> None:
        self._store = store

    def _ensure_available(self) -> None:
        if not self._store.available:
            raise SecretStoreUnavailable("credential_store_unavailable")

    def enroll_topstep(self, *, username: str, api_key: str) -> None:
        self._ensure_available()
        if not username.strip() or not api_key.strip():
            raise ValueError("topstep_credentials_required")
        previous_key = None
        try:
            previous_key = self._store.get_secret(TOPSTEP_API_KEY_SLOT)
        except SecretNotFound:
            pass
        # Each Credential Manager write is atomic. Preserve the prior key so the
        # two-slot operation can compensate if the username write fails.
        self._store.set_secret(TOPSTEP_API_KEY_SLOT, api_key)
        try:
            self._store.set_secret(TOPSTEP_USERNAME_SLOT, username)
        except Exception:
            if previous_key is None:
                self._store.delete_secret(TOPSTEP_API_KEY_SLOT)
            else:
                self._store.set_secret(TOPSTEP_API_KEY_SLOT, previous_key)
            raise

    def load_topstep(self) -> TopstepCredentials:
        self._ensure_available()
        try:
            username = self._store.get_secret(TOPSTEP_USERNAME_SLOT)
            api_key = self._store.get_secret(TOPSTEP_API_KEY_SLOT)
        except SecretNotFound as exc:
            raise SecretNotFound("topstep_credentials_incomplete") from exc
        return TopstepCredentials(username=username, api_key=api_key)

    def enroll_telemetry(self, credential: str) -> None:
        self._ensure_available()
        self._store.set_secret(TELEMETRY_CREDENTIAL_SLOT, credential)

    def load_telemetry(self) -> str:
        self._ensure_available()
        return self._store.get_secret(TELEMETRY_CREDENTIAL_SLOT)

    def delete_all(self) -> tuple[str, ...]:
        self._ensure_available()
        deleted = []
        for slot in (
            TOPSTEP_USERNAME_SLOT,
            TOPSTEP_API_KEY_SLOT,
            TELEMETRY_CREDENTIAL_SLOT,
        ):
            if self._store.delete_secret(slot):
                deleted.append(slot)
        return tuple(deleted)
