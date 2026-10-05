from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging

import pytest

from local_executor.credentials import (
    CredentialEnrollment,
    TELEMETRY_CREDENTIAL_SLOT,
    TOPSTEP_API_KEY_SLOT,
    TOPSTEP_USERNAME_SLOT,
)
from local_executor.safe_logging import LocalJsonFormatter, SecretRedactor
from local_executor.secret_store import (
    MacOSKeychain,
    MemorySecretStore,
    SecretNotFound,
    SecretStoreUnavailable,
    WindowsCredentialManager,
    personal_device_secret_store,
)
from local_executor.session import LocalSessionError, MemoryOnlySessionManager, SessionToken


def test_missing_os_credential_store_fails_closed():
    enrollment = CredentialEnrollment(MemorySecretStore(available=False))
    with pytest.raises(SecretStoreUnavailable, match="credential_store_unavailable"):
        enrollment.enroll_topstep(username="tester", api_key="secret")


def test_macos_keychain_rejects_invalid_slot_names_without_touching_keychain():
    store = MacOSKeychain()
    with pytest.raises(ValueError, match="invalid_secret_slot"):
        store._service("../unsafe")


@pytest.mark.parametrize(
    ("system_name", "store_type"),
    [("Windows", WindowsCredentialManager), ("Darwin", MacOSKeychain)],
)
def test_personal_device_store_selects_native_keychain(
    monkeypatch, system_name, store_type
):
    monkeypatch.setattr("local_executor.secret_store.platform.system", lambda: system_name)
    assert isinstance(personal_device_secret_store(), store_type)


def test_personal_device_store_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr("local_executor.secret_store.platform.system", lambda: "Linux")
    with pytest.raises(
        SecretStoreUnavailable, match="supported_credential_store_unavailable"
    ):
        personal_device_secret_store()


def test_enrollment_replacement_and_deletion_are_scoped_to_fixed_slots():
    store = MemorySecretStore()
    enrollment = CredentialEnrollment(store)
    enrollment.enroll_topstep(username="tester-one", api_key="key-one")
    enrollment.enroll_telemetry("telemetry-one")
    enrollment.enroll_topstep(username="tester-two", api_key="key-two")

    loaded = enrollment.load_topstep()
    assert loaded.username == "tester-two"
    assert loaded.api_key == "key-two"
    assert enrollment.load_telemetry() == "telemetry-one"
    assert store.slot_names == {
        TOPSTEP_USERNAME_SLOT,
        TOPSTEP_API_KEY_SLOT,
        TELEMETRY_CREDENTIAL_SLOT,
    }
    assert "tester-two" not in repr(loaded)
    assert "key-two" not in repr(loaded)

    assert set(enrollment.delete_all()) == set(store.slot_names) | {
        TOPSTEP_USERNAME_SLOT,
        TOPSTEP_API_KEY_SLOT,
        TELEMETRY_CREDENTIAL_SLOT,
    }
    assert store.slot_names == frozenset()
    assert enrollment.delete_all() == ()
    with pytest.raises(SecretNotFound):
        enrollment.load_topstep()


def test_restart_reauthenticates_and_session_token_is_never_persisted(tmp_path):
    store = MemorySecretStore()
    enrollment = CredentialEnrollment(store)
    enrollment.enroll_topstep(username="tester", api_key="dedicated-key")
    issued = []

    def authenticate(credentials):
        token = f"memory-token-{len(issued) + 1}"
        issued.append((credentials.username, token))
        return SessionToken(
            token,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )

    first = MemoryOnlySessionManager(enrollment, authenticate)
    assert first.get_token() == "memory-token-1"
    assert first.get_token() == "memory-token-1"
    assert store.slot_names == {TOPSTEP_USERNAME_SLOT, TOPSTEP_API_KEY_SLOT}

    second = MemoryOnlySessionManager(enrollment, authenticate)
    assert second.has_session is False
    assert second.get_token() == "memory-token-2"
    assert store.slot_names == {TOPSTEP_USERNAME_SLOT, TOPSTEP_API_KEY_SLOT}
    assert list(tmp_path.iterdir()) == []
    assert "memory-token" not in json.dumps(second.safe_status())


def test_session_renewal_rotates_only_in_memory():
    store = MemorySecretStore()
    enrollment = CredentialEnrollment(store)
    enrollment.enroll_topstep(username="tester", api_key="dedicated-key")
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    manager = MemoryOnlySessionManager(
        enrollment,
        lambda _credentials: SessionToken("token-one", expiry),
        lambda token: SessionToken("token-two", expiry) if token == "token-one" else None,
    )
    assert manager.get_token() == "token-one"
    assert manager.renew() == "token-two"
    assert "token-one" not in store._values.values()
    assert "token-two" not in store._values.values()


def test_secret_bearing_provider_exception_is_reclassified_and_redacted():
    secret = "provider-secret-fixture"
    store = MemorySecretStore()
    enrollment = CredentialEnrollment(store)
    enrollment.enroll_topstep(username="tester", api_key=secret)

    def fail(_credentials):
        raise RuntimeError(f"authorization={secret}")

    manager = MemoryOnlySessionManager(enrollment, fail)
    with pytest.raises(LocalSessionError) as exc_info:
        manager.get_token()
    assert str(exc_info.value) == "provider_authentication_failed"
    assert secret not in str(exc_info.value)

    formatter = LocalJsonFormatter(SecretRedactor([secret]))
    record = logging.LogRecord(
        "local_executor",
        logging.ERROR,
        __file__,
        1,
        f"authorization={secret}",
        (),
        None,
    )
    assert secret not in formatter.format(record)
