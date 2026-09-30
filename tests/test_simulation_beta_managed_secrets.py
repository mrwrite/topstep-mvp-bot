import base64
import json

import pytest

from app.app_config import AppConfig, ConfigError, validate_config
from app.key_management import (
    EncryptionContext,
    EnvelopeEncryptionService,
    KeyManagementError,
    LocalDevelopmentKeyProvider,
)


def _key(byte: int) -> bytes:
    return bytes([byte]) * 32


def _context(tenant: str = "1") -> EncryptionContext:
    return EncryptionContext(tenant, "broker-credential", "integration", "42")


def test_envelope_round_trip_context_tampering_and_safe_errors():
    service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": _key(1)}, "v1"))
    envelope = service.encrypt(b'{"token":"secret-value"}', _context())
    assert service.decrypt(envelope, _context()) == (b'{"token":"secret-value"}', False)
    with pytest.raises(KeyManagementError, match="context_mismatch") as mismatch:
        service.decrypt(envelope, _context("2"))
    assert "secret-value" not in str(mismatch.value)

    encoded = envelope.removeprefix("envelope:v2:")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["ciphertext"] = base64.urlsafe_b64encode(b"tampered").decode()
    tampered = "envelope:v2:" + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(KeyManagementError, match="authentication_failed"):
        service.decrypt(tampered, _context())


def test_rotation_reads_previous_key_and_reencrypts():
    old = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": _key(1)}, "v1"))
    value = old.encrypt(b"credential", _context())
    rotating = EnvelopeEncryptionService(
        LocalDevelopmentKeyProvider({"v1": _key(1), "v2": _key(2)}, "v2")
    )
    assert rotating.decrypt(value, _context()) == (b"credential", True)
    rotated = rotating.rotate(value, _context())
    assert rotated != value
    assert rotating.decrypt(rotated, _context()) == (b"credential", False)


def test_missing_retired_key_and_provider_outage_fail_closed():
    value = EnvelopeEncryptionService(
        LocalDevelopmentKeyProvider({"v1": _key(1)}, "v1")
    ).encrypt(b"credential", _context())
    with pytest.raises(KeyManagementError, match="unsupported_policy"):
        EnvelopeEncryptionService(
            LocalDevelopmentKeyProvider({"v2": _key(2)}, "v2")
        ).decrypt(value, _context())
    with pytest.raises(KeyManagementError, match="provider_unavailable"):
        EnvelopeEncryptionService(
            LocalDevelopmentKeyProvider({"v1": _key(1)}, "v1", available=False)
        ).encrypt(b"credential", _context())


def test_production_rejects_local_or_incomplete_tpm_configuration():
    base = dict(
        app_env="production",
        database_url="postgresql://db",
        secret_key="secret",
        credentials_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        cors_origins=("https://example.test",),
        allow_create_all=False,
        rate_limit_requests_per_minute=10,
        log_level="INFO",
        resend_api_key="configured",
        resend_from_email="noreply@example.test",
        frontend_url="https://example.test",
    )
    with pytest.raises(ConfigError, match="TPM2"):
        validate_config(AppConfig(**base))
    with pytest.raises(ConfigError, match="KEY_MANAGEMENT_KEY_ID"):
        validate_config(AppConfig(**base, key_management_provider="tpm2"))
    with pytest.raises(ConfigError, match="TPM and offline recovery"):
        validate_config(
            AppConfig(
                **base,
                key_management_provider="tpm2",
                key_management_key_id="owner-selected-key",
            )
        )
