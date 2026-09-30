import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from app.key_management import (
    KeyManagementError,
    EncryptionContext,
    EnvelopeEncryptionService,
    LocalDevelopmentKeyProvider,
    RailwaySecretEnvelopeProvider,
    RecoveryPublicKey,
    Tpm2KeyProvider,
    decode_local_keys,
)


def _derive_key_from_secret(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    if not key:
        app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()
        if app_env in {"production", "prod"}:
            raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY must be set explicitly in production.")
        secret = os.getenv("SECRET_KEY")
        if not secret:
            raise RuntimeError("SECRET_KEY must be set to derive the credentials encryption key.")
        key = _derive_key_from_secret(secret).decode("utf-8")
    return Fernet(key.encode("utf-8"))


def _envelope_service() -> EnvelopeEncryptionService:
    provider = os.getenv("KEY_MANAGEMENT_PROVIDER", "local-development").strip().lower()
    recovery = None
    recovery_file = os.getenv("RECOVERY_PUBLIC_KEY_FILE")
    if recovery_file:
        recovery = RecoveryPublicKey(
            os.getenv("RECOVERY_KEY_ID", ""),
            open(recovery_file, "rb").read(),
            os.getenv("RECOVERY_PUBLIC_KEY_FINGERPRINT", ""),
        )
    if provider == "tpm2":
        handles = json.loads(os.getenv("TPM_KEY_HANDLES_JSON", "{}"))
        public_files = json.loads(os.getenv("TPM_PUBLIC_KEY_FILES_JSON", "{}"))
        fingerprints = json.loads(os.getenv("TPM_KEY_FINGERPRINTS_JSON", "{}"))
        public_keys = {version: open(path, "rb").read() for version, path in public_files.items()}
        key_provider = Tpm2KeyProvider(
            key_id=os.getenv("KEY_MANAGEMENT_KEY_ID", ""),
            active_version=os.getenv("KEY_MANAGEMENT_ACTIVE_VERSION", ""),
            handles=handles,
            public_keys_pem=public_keys,
            approved_fingerprints=fingerprints,
            device_path=os.getenv("TPM_DEVICE_PATH", "/dev/tpmrm0"),
            auth_file=os.getenv("TPM_AUTH_FILE"),
            require_physical_device=True,
        )
        return EnvelopeEncryptionService(key_provider, recovery)
    if provider == "railway-secret-envelope-v1":
        if os.getenv("DEPLOYMENT_PROFILE", "").strip().lower() != "hosted_topstep_combine_beta":
            raise KeyManagementError("invalid_configuration")
        raw_keys = os.getenv("RAILWAY_ENVELOPE_KEY_VERSIONS_JSON", "")
        key_provider = RailwaySecretEnvelopeProvider(
            key_id=os.getenv("KEY_MANAGEMENT_KEY_ID", ""),
            keys=decode_local_keys(raw_keys),
            active_version=os.getenv("KEY_MANAGEMENT_ACTIVE_VERSION", ""),
        )
        return EnvelopeEncryptionService(key_provider, recovery)
    if provider != "local-development":
        raise KeyManagementError("invalid_configuration")
    if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower() in {"prod", "production"}:
        raise KeyManagementError("invalid_configuration")
    raw_keys = os.getenv("LOCAL_KEY_VERSIONS_JSON")
    if raw_keys:
        keys = decode_local_keys(raw_keys)
        active = os.getenv("KEY_MANAGEMENT_ACTIVE_VERSION", "")
    else:
        fernet = _get_fernet()
        keys = {"local-v1": fernet._signing_key + fernet._encryption_key}
        active = "local-v1"
    return EnvelopeEncryptionService(LocalDevelopmentKeyProvider(keys, active), recovery)


def key_management_health() -> dict[str, Any]:
    health = _envelope_service().provider.readiness()
    return {
        "provider_type": health.provider_type,
        "available": health.available,
        "active_key_version": health.active_key_version,
        "approved_prior_versions": list(health.approved_prior_versions),
        "key_id": health.key_id,
        "last_self_test": health.last_self_test,
        "classification": health.classification,
        "failure_code": health.failure_code,
        "legacy_migration_state": os.getenv("LEGACY_FERNET_MODE", "migration"),
        "recovery_configured": bool(os.getenv("RECOVERY_PUBLIC_KEY_FILE")),
    }


def _context(user_id: int, record_id: int) -> EncryptionContext:
    return EncryptionContext(
        tenant_id=str(user_id),
        purpose="integration-credentials",
        record_type="platform-integration",
        record_id=str(record_id),
        environment=os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower(),
        schema_version="1",
    )


def protected_context(
    *, user_id: int, purpose: str, record_type: str, record_id: str, schema_version: str = "1"
) -> EncryptionContext:
    """Build the tenant-bound context used by non-legacy protected records."""
    return EncryptionContext(
        tenant_id=str(user_id),
        purpose=purpose,
        record_type=record_type,
        record_id=str(record_id),
        environment=os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower(),
        schema_version=schema_version,
    )


def encrypt_protected_value(value: str, *, context: EncryptionContext) -> str:
    return _envelope_service().encrypt(value.encode("utf-8"), context)


def decrypt_protected_value(blob: str, *, context: EncryptionContext) -> str:
    plaintext, _needs_rotation = _envelope_service().decrypt(blob, context)
    return plaintext.decode("utf-8")


def active_encryption_key_version() -> str:
    health = _envelope_service().provider.readiness()
    if not health.available or not health.active_key_version:
        raise KeyManagementError(health.failure_code or "provider_unavailable")
    return health.active_key_version


def encrypt_credentials(
    payload: dict[str, Any], *, user_id: int | None = None, record_id: int | None = None
) -> str:
    if user_id is not None and record_id is not None:
        service = _envelope_service()
        if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower() in {"prod", "production"}:
            if not service.provider.readiness().available:
                raise KeyManagementError("provider_unavailable")
        return service.encrypt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            _context(user_id, record_id),
        )
    fernet = _get_fernet()
    serialized = json.dumps(payload).encode("utf-8")
    return fernet.encrypt(serialized).decode("utf-8")


def decrypt_credentials(
    blob: str, *, user_id: int | None = None, record_id: int | None = None
) -> dict[str, Any]:
    credentials, _needs_rotation = decrypt_credentials_with_rotation(
        blob, user_id=user_id, record_id=record_id
    )
    return credentials


def decrypt_credentials_with_rotation(
    blob: str, *, user_id: int | None = None, record_id: int | None = None
) -> tuple[dict[str, Any], bool]:
    if blob.startswith("envelope:v2:"):
        if user_id is None or record_id is None:
            raise ValueError("Credential record context is required.")
        decrypted, needs_rotation = _envelope_service().decrypt(
            blob, _context(user_id, record_id)
        )
        return json.loads(decrypted), needs_rotation
    if os.getenv("LEGACY_FERNET_MODE", "migration").strip().lower() != "migration":
        raise ValueError("Legacy credentials are disabled after envelope-only cutover.")
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(blob.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Invalid credentials payload.") from exc
    return json.loads(decrypted.decode("utf-8")), True


def migrate_legacy_credentials(
    blob: str, *, user_id: int, record_id: int
) -> str:
    """Convert one legacy Fernet value without exposing plaintext to callers."""
    if blob.startswith("envelope:v2:"):
        return blob
    credentials, _ = decrypt_credentials_with_rotation(
        blob, user_id=user_id, record_id=record_id
    )
    return _envelope_service().encrypt(
        json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode(),
        _context(user_id, record_id),
        migration_source="fernet-v1",
    )
