import base64
import json

import pytest

from app.app_config import AppConfig, ConfigError, validate_config
from app.key_management import (
    EncryptionContext,
    EnvelopeEncryptionService,
    KeyFailure,
    KeyManagementError,
    RailwaySecretEnvelopeProvider,
)


def _context(**changes):
    values = dict(
        tenant_id="tenant-1",
        purpose="integration-credentials",
        record_type="platform-integration",
        record_id="credential-42",
        environment="production",
        schema_version="1",
    )
    values.update(changes)
    return EncryptionContext(**values)


def _provider(active="v1", keys=None):
    return RailwaySecretEnvelopeProvider(
        key_id="railway-combine-credentials",
        keys=keys or {"v1": b"1" * 32},
        active_version=active,
    )


def _decode(envelope):
    value = envelope.removeprefix("envelope:v2:")
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def _production_config(**changes):
    values = dict(
        app_env="production",
        database_url="postgresql://db",
        secret_key="authentication-secret",
        credentials_encryption_key=None,
        cors_origins=("https://beta.example.test",),
        allow_create_all=False,
        rate_limit_requests_per_minute=10,
        log_level="INFO",
        resend_api_key="configured",
        resend_from_email="noreply@example.test",
        frontend_url="https://beta.example.test",
        key_management_provider="railway-secret-envelope-v1",
        key_management_key_id="railway-combine-credentials",
        key_management_active_version="v1",
        deployment_profile="hosted_topstep_combine_beta",
        hosted_security_epoch=1,
        railway_key_versions_json=json.dumps({
            "v1": base64.urlsafe_b64encode(b"1" * 32).decode()
        }),
        topstep_credential_fingerprint_key=base64.urlsafe_b64encode(b"f" * 32).decode(),
        topstep_beta_cohort_id="initial-tester",
        topstep_approved_tester_user_id=42,
        legacy_fernet_mode="envelope-only",
    )
    values.update(changes)
    return AppConfig(**values)


def test_hosted_provider_wraps_unique_deks_and_reports_safe_health():
    service = EnvelopeEncryptionService(_provider())
    first = _decode(service.encrypt(b"same", _context()))
    second = _decode(service.encrypt(b"same", _context()))
    assert first["wrapped_data_key"] != second["wrapped_data_key"]
    assert first["nonce"] != second["nonce"]
    assert first["provider_id"] == "railway-secret-envelope-v1"
    health = service.provider.readiness()
    assert health.available
    assert health.classification == "hosted-beta-accepted-risk"
    assert "111111" not in repr(health)


@pytest.mark.parametrize("change", [
    {"tenant_id": "tenant-2"},
    {"record_id": "credential-99"},
    {"environment": "staging"},
    {"schema_version": "2"},
])
def test_hosted_provider_context_substitution_fails_closed(change):
    service = EnvelopeEncryptionService(_provider())
    envelope = service.encrypt(b"topstep-key", _context())
    with pytest.raises(KeyManagementError, match="context_mismatch"):
        service.decrypt(envelope, _context(**change))


def test_hosted_provider_rotation_rewraps_only_the_dek():
    original = EnvelopeEncryptionService(_provider())
    envelope = original.encrypt(b"topstep-key", _context())
    rotating = EnvelopeEncryptionService(_provider(
        active="v2", keys={"v1": b"1" * 32, "v2": b"2" * 32}
    ))
    rotated = rotating.rewrap(envelope, _context())
    before, after = _decode(envelope), _decode(rotated)
    assert before["ciphertext"] == after["ciphertext"]
    assert before["nonce"] == after["nonce"]
    assert before["tag"] == after["tag"]
    assert after["key_version"] == "v2"
    assert rotating.decrypt(rotated, _context()) == (b"topstep-key", False)


def test_hosted_provider_missing_prior_key_and_tampering_fail_closed():
    envelope = EnvelopeEncryptionService(_provider()).encrypt(b"topstep-key", _context())
    with pytest.raises(KeyManagementError) as missing:
        EnvelopeEncryptionService(_provider(active="v2", keys={"v2": b"2" * 32})).decrypt(
            envelope, _context()
        )
    assert missing.value.code is KeyFailure.UNSUPPORTED_POLICY

    payload = _decode(envelope)
    payload["wrapped_data_key"] = payload["wrapped_data_key"][:-2] + "AA"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    tampered = "envelope:v2:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(KeyManagementError):
        EnvelopeEncryptionService(_provider()).decrypt(tampered, _context())


def test_hosted_provider_production_configuration_is_narrow_and_validated():
    validate_config(_production_config())
    with pytest.raises(ConfigError, match="restricted"):
        validate_config(_production_config(deployment_profile="production"))
    with pytest.raises(ConfigError, match="exactly 32 bytes"):
        validate_config(_production_config(railway_key_versions_json=json.dumps({
            "v1": base64.urlsafe_b64encode(b"short").decode()
        })))
    with pytest.raises(ConfigError, match="separate"):
        encoded = base64.urlsafe_b64encode(b"1" * 32).decode()
        validate_config(_production_config(secret_key=encoded))


def test_hosted_provider_shutdown_removes_keys():
    provider = _provider()
    provider.shutdown()
    with pytest.raises(KeyManagementError) as error:
        provider.wrap(b"x" * 32, version="v1", aad=b"context")
    assert error.value.code is KeyFailure.KEY_UNAVAILABLE
    assert "xxxxxxxx" not in str(error.value)
