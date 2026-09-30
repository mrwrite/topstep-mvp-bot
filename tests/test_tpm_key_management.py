import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.app_config import AppConfig, ConfigError, validate_config
from app.key_management import (
    EncryptionContext,
    EnvelopeEncryptionService,
    KeyFailure,
    KeyManagementError,
    LocalDevelopmentKeyProvider,
    RecoveryPublicKey,
    Tpm2KeyProvider,
    rewrap_recovered_envelope,
)
from scripts.offline_tpm_recovery import recover_package


def _context(**changes):
    values = dict(tenant_id="tenant-1", purpose="integration-credentials",
                  record_type="platform-integration", record_id="42",
                  environment="test", schema_version="1")
    values.update(changes)
    return EncryptionContext(**values)


def _decode(value):
    encoded = value.removeprefix("envelope:v2:")
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def _encode(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "envelope:v2:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pem_and_fingerprint(public):
    pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return pem, hashlib.sha256(der).hexdigest()


class FakePhysicalTpm:
    def __init__(self, private, public_pem, *, capability=b"manufacturer: IFX"):
        self.private = private
        self.public_pem = public_pem
        self.capability = capability
        self.commands = []

    def __call__(self, args, input_bytes):
        self.commands.append(tuple(args))
        if args[0] == "tpm2_getcap":
            return self.capability
        if args[0] == "tpm2_readpublic":
            return self.public_pem
        if args[0] == "tpm2_rsadecrypt":
            return self.private.decrypt(input_bytes, padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        raise RuntimeError("unexpected command")


def _tpm_provider(version="v1", *, runner=None, private=None):
    private = private or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem, fingerprint = _pem_and_fingerprint(private.public_key())
    fake = runner or FakePhysicalTpm(private, pem)
    return Tpm2KeyProvider(key_id="pi-wrap", active_version=version,
                           handles={version: "0x81010020"}, public_keys_pem={version: pem},
                           approved_fingerprints={version: fingerprint}, command_runner=fake), fake


def test_tpm_wrap_unwrap_readiness_and_safe_status():
    provider, fake = _tpm_provider()
    status = provider.readiness()
    assert status.available and status.provider_type == "tpm2"
    assert status.active_key_version == "v1"
    assert any(command[0] == "tpm2_rsadecrypt" for command in fake.commands)


def test_tpm_rejects_wrong_identity_and_software_tpm():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem, fingerprint = _pem_and_fingerprint(private.public_key())
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem, _ = _pem_and_fingerprint(other.public_key())
    provider = Tpm2KeyProvider(key_id="pi-wrap", active_version="v1",
        handles={"v1": "0x81010020"}, public_keys_pem={"v1": pem},
        approved_fingerprints={"v1": fingerprint},
        command_runner=FakePhysicalTpm(private, other_pem))
    assert provider.readiness().failure_code == KeyFailure.KEY_IDENTITY_MISMATCH.value
    provider = Tpm2KeyProvider(key_id="pi-wrap", active_version="v1",
        handles={"v1": "0x81010020"}, public_keys_pem={"v1": pem},
        approved_fingerprints={"v1": fingerprint},
        command_runner=FakePhysicalTpm(private, pem, capability=b"swtpm simulator"))
    assert provider.readiness().failure_code == KeyFailure.SOFTWARE_TPM_REJECTED.value


@pytest.mark.parametrize("failure", [KeyFailure.PROVIDER_UNAVAILABLE,
                                      KeyFailure.AUTHORIZATION_FAILED, KeyFailure.TPM_LOCKOUT])
def test_tpm_command_failures_are_typed_and_redacted(failure):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem, fingerprint = _pem_and_fingerprint(private.public_key())

    def failing(args, _input):
        if args[0] == "tpm2_getcap":
            return b"manufacturer: IFX"
        if args[0] == "tpm2_readpublic":
            return pem
        raise KeyManagementError(failure)

    provider = Tpm2KeyProvider(key_id="pi-wrap", active_version="v1",
        handles={"v1": "0x81010020"}, public_keys_pem={"v1": pem},
        approved_fingerprints={"v1": fingerprint}, command_runner=failing)
    status = provider.readiness()
    assert not status.available and status.failure_code == failure.value
    assert "secret" not in repr(status)


def test_missing_physical_tpm_device_fails_readiness():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem, fingerprint = _pem_and_fingerprint(private.public_key())
    provider = Tpm2KeyProvider(key_id="pi-wrap", active_version="v1",
        handles={"v1": "0x81010020"}, public_keys_pem={"v1": pem},
        approved_fingerprints={"v1": fingerprint}, device_path="/definitely/missing/tpmrm0")
    assert provider.readiness().failure_code == KeyFailure.UNSAFE_DEVICE.value


@pytest.mark.parametrize("field", ["ciphertext", "tag", "nonce", "wrapped_data_key", "context_hash",
                                    "integrity_hmac", "key_version", "encryption_algorithm"])
def test_envelope_tampering_fails_closed(field):
    service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    value = service.encrypt(b"secret", _context())
    payload = _decode(value)
    payload[field] = "tampered"
    with pytest.raises(KeyManagementError):
        service.decrypt(_encode(payload), _context())


@pytest.mark.parametrize("change", [
    {"tenant_id": "tenant-2"}, {"purpose": "other"}, {"record_id": "99"},
    {"environment": "production"}, {"schema_version": "2"},
])
def test_context_substitution_fails_closed(change):
    service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    value = service.encrypt(b"secret", _context())
    with pytest.raises(KeyManagementError, match="context_mismatch"):
        service.decrypt(value, _context(**change))


def test_unique_data_keys_nonces_and_recovery_wraps():
    recovery_private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    recovery_pem, recovery_fingerprint = _pem_and_fingerprint(recovery_private.public_key())
    recovery = RecoveryPublicKey("offline-2026", recovery_pem, recovery_fingerprint)
    service = EnvelopeEncryptionService(
        LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"), recovery)
    first, second = _decode(service.encrypt(b"same", _context())), _decode(service.encrypt(b"same", _context()))
    assert first["nonce"] != second["nonce"]
    assert first["wrapped_data_key"] != second["wrapped_data_key"]
    assert first["recovery_wrapped_data_key"] != second["recovery_wrapped_data_key"]
    recovered = recovery_private.decrypt(base64.urlsafe_b64decode(
        first["recovery_wrapped_data_key"] + "=" * (-len(first["recovery_wrapped_data_key"]) % 4)),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    assert len(recovered) == 32


def test_data_key_only_rewrap_preserves_ciphertext_nonce_and_tag():
    old = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    value = old.encrypt(b"credential", _context())
    rotating = EnvelopeEncryptionService(LocalDevelopmentKeyProvider(
        {"v1": b"1" * 32, "v2": b"2" * 32}, "v2"))
    rewrapped = rotating.rewrap(value, _context())
    before, after = _decode(value), _decode(rewrapped)
    assert (before["ciphertext"], before["nonce"], before["tag"]) == (
        after["ciphertext"], after["nonce"], after["tag"])
    assert before["wrapped_data_key"] != after["wrapped_data_key"]
    assert rotating.decrypt(rewrapped, _context()) == (b"credential", False)


def test_replacement_tpm_recovery_and_wrong_key_failure():
    recovery_private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    recovery_pem, recovery_fingerprint = _pem_and_fingerprint(recovery_private.public_key())
    original = EnvelopeEncryptionService(
        LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"),
        RecoveryPublicKey("offline-2026", recovery_pem, recovery_fingerprint))
    value = original.encrypt(b"credential", _context())
    payload = _decode(value)
    wrapped_recovery = base64.urlsafe_b64decode(payload["recovery_wrapped_data_key"]
                                                + "=" * (-len(payload["recovery_wrapped_data_key"]) % 4))
    recovered = bytearray(recovery_private.decrypt(wrapped_recovery, padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)))
    replacement, _ = _tpm_provider("v2")
    rewrapped = rewrap_recovered_envelope(value, _context(), recovered, replacement)
    assert EnvelopeEncryptionService(replacement).decrypt(rewrapped, _context()) == (b"credential", False)
    wrong = bytearray(b"x" * 32)
    with pytest.raises(KeyManagementError):
        rewrap_recovered_envelope(value, _context(), wrong, replacement)


def test_offline_recovery_package_rewrap_and_corruption_failure():
    recovery_private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    recovery_pem, recovery_fingerprint = _pem_and_fingerprint(recovery_private.public_key())
    original = EnvelopeEncryptionService(
        LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"),
        RecoveryPublicKey("offline-2026", recovery_pem, recovery_fingerprint))
    envelope = original.encrypt(b"credential", _context())
    replacement, _ = _tpm_provider("v2")
    password = b"offline-test-password"
    encrypted_private = recovery_private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password))
    package = {"records": [{"record_reference": "integration:42",
                             "context": _context().canonical(), "envelope": envelope}]}
    output, report = recover_package(package, encrypted_private, password, replacement)
    assert report["rewrapped"] == 1 and report["failed"] == 0
    assert EnvelopeEncryptionService(replacement).decrypt(
        output["records"][0]["envelope"], _context())[0] == b"credential"

    corrupted = json.loads(json.dumps(package))
    payload = _decode(corrupted["records"][0]["envelope"])
    payload["recovery_wrapped_data_key"] = "corrupted"
    corrupted["records"][0]["envelope"] = _encode(payload)
    _, corrupt_report = recover_package(corrupted, encrypted_private, password, replacement)
    assert corrupt_report == {"total": 1, "rewrapped": 0, "failed": 1,
                              "replacement_key_id": "pi-wrap", "replacement_key_version": "v2"}

    wrong_private = rsa.generate_private_key(public_exponent=65537, key_size=3072).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password))
    _, wrong_report = recover_package(package, wrong_private, password, replacement)
    assert wrong_report["failed"] == 1


def test_truncated_unknown_and_invalid_envelopes_fail_closed():
    service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    value = service.encrypt(b"secret", _context())
    for invalid in (value[:-5], "envelope:v2:not-base64", "legacy-value"):
        with pytest.raises(KeyManagementError):
            service.decrypt(invalid, _context())
    payload = _decode(value)
    payload["unknown"] = "ambiguous"
    with pytest.raises(KeyManagementError, match="invalid_envelope"):
        service.decrypt(_encode(payload), _context())


def test_production_rejects_non_tpm_and_recovery_private_material():
    base = dict(app_env="production", database_url="postgresql://db", secret_key="secret",
        credentials_encryption_key=None, cors_origins=("https://example.test",), allow_create_all=False,
        rate_limit_requests_per_minute=10, log_level="INFO", resend_api_key="configured",
        resend_from_email="noreply@example.test", frontend_url="https://example.test",
        legacy_fernet_mode="envelope-only")
    with pytest.raises(ConfigError, match="TPM2"):
        validate_config(AppConfig(**base))
    tpm = dict(key_management_provider="tpm2", key_management_key_id="pi-wrap",
        key_management_active_version="v1", tpm_device_path="/dev/tpmrm0",
        tpm_key_handles_json='{"v1":"0x81010020"}', tpm_public_key_files_json='{"v1":"/run/key.pub"}',
        tpm_key_fingerprints_json='{"v1":"abc"}', tpm_auth_file="/run/credentials/tpm-auth",
        recovery_key_id="offline-2026", recovery_public_key_file="/etc/app/recovery.pub",
        recovery_public_key_fingerprint="def")
    validate_config(AppConfig(**base, **tpm))
    with pytest.raises(ConfigError, match="Recovery private"):
        validate_config(AppConfig(**base, **tpm, recovery_private_key_file="/secret/private.pem"))
