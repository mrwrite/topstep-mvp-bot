from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyFailure(StrEnum):
    INVALID_CONFIGURATION = "invalid_configuration"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    KEY_UNAVAILABLE = "key_unavailable"
    KEY_IDENTITY_MISMATCH = "key_identity_mismatch"
    AUTHORIZATION_FAILED = "authorization_failed"
    TPM_LOCKOUT = "tpm_lockout"
    UNSAFE_DEVICE = "unsafe_device"
    SOFTWARE_TPM_REJECTED = "software_tpm_rejected"
    UNSUPPORTED_POLICY = "unsupported_policy"
    INVALID_ENVELOPE = "invalid_envelope"
    CONTEXT_MISMATCH = "context_mismatch"
    AUTHENTICATION_FAILED = "authentication_failed"
    RECOVERY_FAILED = "recovery_failed"


class KeyManagementError(RuntimeError):
    """A deliberately non-sensitive key-management failure."""

    def __init__(self, code: KeyFailure | str):
        self.code = KeyFailure(code)
        super().__init__(f"Protected secret operation failed ({self.code.value}).")


@dataclass(frozen=True)
class EncryptionContext:
    tenant_id: str
    purpose: str
    record_type: str
    record_id: str
    environment: str = "development"
    schema_version: str = "1"

    def canonical(self) -> dict[str, str]:
        values = asdict(self)
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        return values


@dataclass(frozen=True)
class ProviderHealth:
    provider_type: str
    available: bool
    active_key_version: str
    approved_prior_versions: tuple[str, ...]
    key_id: str
    last_self_test: str | None
    classification: str
    failure_code: str | None = None


class KeyManagementProvider(Protocol):
    provider_id: str
    wrapping_algorithm: str

    @property
    def active_version(self) -> str: ...

    @property
    def key_id(self) -> str: ...

    @property
    def approved_versions(self) -> tuple[str, ...]: ...

    def readiness(self) -> ProviderHealth: ...

    def generate_data_key(self) -> bytearray: ...

    def wrap(self, data_key: bytes, *, version: str, aad: bytes) -> bytes: ...

    def unwrap(self, wrapped_key: bytes, *, version: str, aad: bytes) -> bytearray: ...

    def validate_context(self, supplied: bytes, expected: bytes) -> None: ...

    def shutdown(self) -> None: ...


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise KeyManagementError(KeyFailure.INVALID_ENVELOPE)
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise KeyManagementError(KeyFailure.INVALID_ENVELOPE) from exc


def _wipe(value: bytearray | None) -> None:
    if value is not None:
        for index in range(len(value)):
            value[index] = 0


class LocalDevelopmentKeyProvider:
    """Visible software-only provider; production configuration rejects it."""

    provider_id = "local-development"
    wrapping_algorithm = "AES-256-GCM-DEVELOPMENT-ONLY"

    def __init__(self, keys: dict[str, bytes], active_version: str, *, available: bool = True):
        if active_version not in keys or any(len(value) != 32 for value in keys.values()):
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        self._keys = {version: bytearray(value) for version, value in keys.items()}
        self._active_version = active_version
        self._available = available
        self._last_self_test: str | None = None

    @property
    def active_version(self) -> str:
        return self._active_version

    @property
    def key_id(self) -> str:
        return "development-software-key"

    @property
    def approved_versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def _key(self, version: str) -> bytes:
        if not self._available:
            raise KeyManagementError(KeyFailure.PROVIDER_UNAVAILABLE)
        try:
            return bytes(self._keys[version])
        except KeyError as exc:
            raise KeyManagementError(KeyFailure.KEY_UNAVAILABLE) from exc

    def readiness(self) -> ProviderHealth:
        if not self._available:
            return ProviderHealth(self.provider_id, False, self.active_version, (), self.key_id, None,
                                  "failed", KeyFailure.PROVIDER_UNAVAILABLE.value)
        probe = bytearray(os.urandom(32))
        recovered: bytearray | None = None
        try:
            wrapped = self.wrap(bytes(probe), version=self.active_version, aad=b"self-test")
            recovered = self.unwrap(wrapped, version=self.active_version, aad=b"self-test")
            if not hmac.compare_digest(probe, recovered):
                raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
            self._last_self_test = datetime.now(timezone.utc).isoformat()
        finally:
            _wipe(recovered)
            _wipe(probe)
        return ProviderHealth(self.provider_id, True, self.active_version,
                              tuple(v for v in self.approved_versions if v != self.active_version),
                              self.key_id, self._last_self_test, "development-only")

    def generate_data_key(self) -> bytearray:
        return bytearray(os.urandom(32))

    def wrap(self, data_key: bytes, *, version: str, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._key(version)).encrypt(nonce, data_key, aad + b":wrapped-dek")

    def unwrap(self, wrapped_key: bytes, *, version: str, aad: bytes) -> bytearray:
        if len(wrapped_key) < 29:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
        try:
            return bytearray(AESGCM(self._key(version)).decrypt(
                wrapped_key[:12], wrapped_key[12:], aad + b":wrapped-dek"
            ))
        except (InvalidTag, ValueError) as exc:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED) from exc

    def validate_context(self, supplied: bytes, expected: bytes) -> None:
        if not hmac.compare_digest(supplied, expected):
            raise KeyManagementError(KeyFailure.CONTEXT_MISMATCH)

    def shutdown(self) -> None:
        for value in self._keys.values():
            _wipe(value)
        self._keys.clear()


class RailwaySecretEnvelopeProvider:
    """Explicit hosted-beta provider backed only by Railway service variables.

    This provider is deliberately not a generic environment-key provider. The
    deployment-profile guard lives in configuration and is repeated by the
    runtime factory before this class can be constructed.
    """

    provider_id = "railway-secret-envelope-v1"
    wrapping_algorithm = "AES-256-GCM-KEYWRAP"

    def __init__(self, *, key_id: str, keys: dict[str, bytes], active_version: str):
        if (not key_id or not keys or active_version not in keys
                or any(not version or len(value) != 32 for version, value in keys.items())):
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        self._key_id = key_id
        self._keys = {version: bytearray(value) for version, value in keys.items()}
        self._active_version = active_version
        self._last_self_test: str | None = None

    @property
    def active_version(self) -> str:
        return self._active_version

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def approved_versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))

    def _key(self, version: str) -> bytes:
        try:
            return bytes(self._keys[version])
        except KeyError as exc:
            raise KeyManagementError(KeyFailure.KEY_UNAVAILABLE) from exc

    def readiness(self) -> ProviderHealth:
        probe = bytearray(os.urandom(32))
        recovered: bytearray | None = None
        try:
            wrapped = self.wrap(bytes(probe), version=self.active_version, aad=b"self-test")
            recovered = self.unwrap(wrapped, version=self.active_version, aad=b"self-test")
            if not hmac.compare_digest(probe, recovered):
                raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
            self._last_self_test = datetime.now(timezone.utc).isoformat()
            return ProviderHealth(
                self.provider_id, True, self.active_version,
                tuple(v for v in self.approved_versions if v != self.active_version),
                self.key_id, self._last_self_test, "hosted-beta-accepted-risk",
            )
        except KeyManagementError as exc:
            return ProviderHealth(
                self.provider_id, False, self.active_version,
                tuple(v for v in self.approved_versions if v != self.active_version),
                self.key_id, self._last_self_test, "failed", exc.code.value,
            )
        finally:
            _wipe(recovered)
            _wipe(probe)

    def generate_data_key(self) -> bytearray:
        return bytearray(os.urandom(32))

    def wrap(self, data_key: bytes, *, version: str, aad: bytes) -> bytes:
        if len(data_key) != 32:
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        nonce = os.urandom(12)
        try:
            return nonce + AESGCM(self._key(version)).encrypt(
                nonce, data_key, aad + b":railway-wrapped-dek:" + version.encode("utf-8")
            )
        except ValueError as exc:
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION) from exc

    def unwrap(self, wrapped_key: bytes, *, version: str, aad: bytes) -> bytearray:
        if len(wrapped_key) != 60:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
        try:
            plaintext = AESGCM(self._key(version)).decrypt(
                wrapped_key[:12], wrapped_key[12:],
                aad + b":railway-wrapped-dek:" + version.encode("utf-8"),
            )
        except (InvalidTag, ValueError) as exc:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED) from exc
        if len(plaintext) != 32:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
        return bytearray(plaintext)

    def validate_context(self, supplied: bytes, expected: bytes) -> None:
        if not hmac.compare_digest(supplied, expected):
            raise KeyManagementError(KeyFailure.CONTEXT_MISMATCH)

    def shutdown(self) -> None:
        for value in self._keys.values():
            _wipe(value)
        self._keys.clear()


CommandRunner = Callable[[list[str], bytes | None], bytes]


def _run_tpm_command(args: list[str], input_bytes: bytes | None, timeout: float) -> bytes:
    try:
        completed = subprocess.run(args, input=input_bytes, capture_output=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KeyManagementError(KeyFailure.PROVIDER_UNAVAILABLE) from exc
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", "ignore").lower()
        if "lockout" in diagnostic or "dictionary" in diagnostic:
            code = KeyFailure.TPM_LOCKOUT
        elif "auth" in diagnostic:
            code = KeyFailure.AUTHORIZATION_FAILED
        elif "handle" in diagnostic or "not found" in diagnostic:
            code = KeyFailure.KEY_UNAVAILABLE
        else:
            code = KeyFailure.PROVIDER_UNAVAILABLE
        raise KeyManagementError(code)
    return completed.stdout


class Tpm2KeyProvider:
    """Physical TPM provider. All TPM subprocess interaction is confined here."""

    provider_id = "tpm2"
    wrapping_algorithm = "RSA-OAEP-SHA256"

    def __init__(self, *, key_id: str, active_version: str, handles: dict[str, str],
                 public_keys_pem: dict[str, bytes], approved_fingerprints: dict[str, str],
                 device_path: str = "/dev/tpmrm0", auth_file: str | None = None,
                 command_runner: CommandRunner | None = None, timeout_seconds: float = 5.0,
                 require_physical_device: bool = True):
        versions = set(handles)
        if (not key_id or active_version not in versions or versions != set(public_keys_pem)
                or versions != set(approved_fingerprints)):
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        self._key_id = key_id
        self._active_version = active_version
        self._handles = dict(handles)
        self._public_keys: dict[str, rsa.RSAPublicKey] = {}
        for version, pem in public_keys_pem.items():
            try:
                public = serialization.load_pem_public_key(pem)
            except ValueError as exc:
                raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION) from exc
            if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 2048:
                raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
            actual = hashlib.sha256(public.public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )).hexdigest()
            if not hmac.compare_digest(actual, approved_fingerprints[version].lower()):
                raise KeyManagementError(KeyFailure.KEY_IDENTITY_MISMATCH)
            self._public_keys[version] = public
        self._fingerprints = {key: value.lower() for key, value in approved_fingerprints.items()}
        self._device_path = device_path
        self._auth_file = auth_file
        self._timeout = timeout_seconds
        self._runner = command_runner
        self._require_physical = require_physical_device
        self._last_self_test: str | None = None

    @property
    def active_version(self) -> str:
        return self._active_version

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def approved_versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._handles))

    def _run(self, args: list[str], input_bytes: bytes | None = None) -> bytes:
        if self._runner is not None:
            try:
                return self._runner(args, input_bytes)
            except KeyManagementError:
                raise
            except Exception as exc:
                raise KeyManagementError(KeyFailure.PROVIDER_UNAVAILABLE) from exc
        return _run_tpm_command([*args, "-T", f"device:{self._device_path}"], input_bytes, self._timeout)

    def _device_ready(self) -> None:
        if self._runner is not None:
            return
        path = Path(self._device_path)
        if not path.exists() or (self._require_physical and not stat.S_ISCHR(path.stat().st_mode)):
            raise KeyManagementError(KeyFailure.UNSAFE_DEVICE)
        if self._require_physical and path.name != "tpmrm0":
            raise KeyManagementError(KeyFailure.SOFTWARE_TPM_REJECTED)
        if self._auth_file:
            auth = Path(self._auth_file)
            if not auth.is_file() or auth.stat().st_mode & 0o077:
                raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)

    def _read_public(self, version: str) -> bytes:
        try:
            handle = self._handles[version]
        except KeyError as exc:
            raise KeyManagementError(KeyFailure.KEY_UNAVAILABLE) from exc
        if self._runner is not None:
            return self._run(["tpm2_readpublic", "-c", handle, "-f", "pem"])
        with tempfile.TemporaryDirectory(prefix="tpm-public-") as directory:
            output = Path(directory) / "public.pem"
            self._run(["tpm2_readpublic", "-c", handle, "-f", "pem", "-o", str(output)])
            return output.read_bytes()

    def _verify_identity(self, version: str) -> None:
        try:
            public = serialization.load_pem_public_key(self._read_public(version))
        except ValueError as exc:
            raise KeyManagementError(KeyFailure.KEY_IDENTITY_MISMATCH) from exc
        actual = hashlib.sha256(public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )).hexdigest()
        if not hmac.compare_digest(actual, self._fingerprints[version]):
            raise KeyManagementError(KeyFailure.KEY_IDENTITY_MISMATCH)

    def readiness(self) -> ProviderHealth:
        try:
            self._device_ready()
            capabilities = self._run(["tpm2_getcap", "properties-fixed"])
            if self._require_physical and any(marker in capabilities.lower()
                                              for marker in (b"swtpm", b"simulator", b"mssim")):
                raise KeyManagementError(KeyFailure.SOFTWARE_TPM_REJECTED)
            self._verify_identity(self.active_version)
            probe = bytearray(os.urandom(32))
            recovered: bytearray | None = None
            try:
                wrapped = self.wrap(bytes(probe), version=self.active_version, aad=b"self-test")
                recovered = self.unwrap(wrapped, version=self.active_version, aad=b"self-test")
                if not hmac.compare_digest(probe, recovered):
                    raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
            finally:
                _wipe(recovered)
                _wipe(probe)
            self._last_self_test = datetime.now(timezone.utc).isoformat()
            return ProviderHealth(self.provider_id, True, self.active_version,
                                  tuple(v for v in self.approved_versions if v != self.active_version),
                                  self.key_id, self._last_self_test, "ok")
        except KeyManagementError as exc:
            return ProviderHealth(self.provider_id, False, self.active_version,
                                  tuple(v for v in self.approved_versions if v != self.active_version),
                                  self.key_id, self._last_self_test, "failed", exc.code.value)

    def generate_data_key(self) -> bytearray:
        return bytearray(os.urandom(32))

    def wrap(self, data_key: bytes, *, version: str, aad: bytes) -> bytes:
        del aad
        try:
            public = self._public_keys[version]
        except KeyError as exc:
            raise KeyManagementError(KeyFailure.KEY_UNAVAILABLE) from exc
        return public.encrypt(data_key, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ))

    def unwrap(self, wrapped_key: bytes, *, version: str, aad: bytes) -> bytearray:
        del aad
        try:
            handle = self._handles[version]
        except KeyError as exc:
            raise KeyManagementError(KeyFailure.KEY_UNAVAILABLE) from exc
        # The provisioned key template fixes OAEP's name/hash algorithm to SHA-256.
        args = ["tpm2_rsadecrypt", "-c", handle, "-s", "oaep"]
        if self._auth_file:
            args.extend(["-p", f"file:{self._auth_file}"])
        plaintext = self._run(args, wrapped_key)
        if len(plaintext) != 32:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
        return bytearray(plaintext)

    def validate_context(self, supplied: bytes, expected: bytes) -> None:
        if not hmac.compare_digest(supplied, expected):
            raise KeyManagementError(KeyFailure.CONTEXT_MISMATCH)

    def shutdown(self) -> None:
        self._public_keys.clear()


class RecoveryPublicKey:
    wrapping_algorithm = "RSA-OAEP-SHA256"

    def __init__(self, key_id: str, public_key_pem: bytes, expected_fingerprint: str):
        try:
            public = serialization.load_pem_public_key(public_key_pem)
        except ValueError as exc:
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION) from exc
        if not key_id or not isinstance(public, rsa.RSAPublicKey) or public.key_size < 3072:
            raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION)
        fingerprint = hashlib.sha256(public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )).hexdigest()
        if not hmac.compare_digest(fingerprint, expected_fingerprint.lower()):
            raise KeyManagementError(KeyFailure.KEY_IDENTITY_MISMATCH)
        self.key_id = key_id
        self.fingerprint = fingerprint
        self._public = public

    def wrap(self, data_key: bytes) -> bytes:
        return self._public.encrypt(data_key, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ))


class EnvelopeEncryptionService:
    SCHEMA_VERSION = 2
    PREFIX = "envelope:v2:"
    ENCRYPTION_ALGORITHM = "AES-256-GCM"
    _FIELDS = {"schema_version", "encryption_algorithm", "wrapping_algorithm", "provider_id",
               "key_id", "key_version", "context", "context_hash", "wrapped_data_key", "nonce",
               "ciphertext", "tag", "integrity_hmac", "created_at", "migration_source",
               "recovery_key_id", "recovery_wrapped_data_key"}

    def __init__(self, provider: KeyManagementProvider, recovery: RecoveryPublicKey | None = None):
        self.provider = provider
        self.recovery = recovery

    def _content_aad(self, context: EncryptionContext) -> bytes:
        return _canonical_json({"schema_version": self.SCHEMA_VERSION,
                                "encryption_algorithm": self.ENCRYPTION_ALGORITHM,
                                "context": context.canonical()})

    @staticmethod
    def _wrapping_metadata(envelope: dict) -> bytes:
        return _canonical_json({key: envelope[key] for key in (
            "schema_version", "wrapping_algorithm", "provider_id", "key_id", "key_version",
            "context_hash", "wrapped_data_key", "recovery_key_id", "recovery_wrapped_data_key"
        )})

    @staticmethod
    def _integrity(data_key: bytes, envelope: dict) -> str:
        return _b64e(hmac.new(data_key, EnvelopeEncryptionService._wrapping_metadata(envelope),
                              hashlib.sha256).digest())

    def encrypt(self, plaintext: bytes, context: EncryptionContext, *, migration_source: str | None = None) -> str:
        version = self.provider.active_version
        aad = self._content_aad(context)
        context_hash = hashlib.sha256(_canonical_json({**context.canonical(),
                                                       "schema_version": self.SCHEMA_VERSION,
                                                       "key_version": version})).hexdigest()
        data_key = self.provider.generate_data_key()
        nonce = os.urandom(12)
        try:
            combined = AESGCM(bytes(data_key)).encrypt(nonce, plaintext, aad)
            wrapped = self.provider.wrap(bytes(data_key), version=version, aad=aad)
            recovery_wrapped = self.recovery.wrap(bytes(data_key)) if self.recovery else None
            envelope = {
                "schema_version": self.SCHEMA_VERSION, "encryption_algorithm": self.ENCRYPTION_ALGORITHM,
                "wrapping_algorithm": self.provider.wrapping_algorithm, "provider_id": self.provider.provider_id,
                "key_id": self.provider.key_id, "key_version": version, "context": context.canonical(),
                "context_hash": context_hash, "wrapped_data_key": _b64e(wrapped), "nonce": _b64e(nonce),
                "ciphertext": _b64e(combined[:-16]), "tag": _b64e(combined[-16:]),
                "created_at": datetime.now(timezone.utc).isoformat(), "migration_source": migration_source,
                "recovery_key_id": self.recovery.key_id if self.recovery else None,
                "recovery_wrapped_data_key": _b64e(recovery_wrapped) if recovery_wrapped else None,
            }
            envelope["integrity_hmac"] = self._integrity(bytes(data_key), envelope)
            return self.PREFIX + _b64e(_canonical_json(envelope))
        except KeyManagementError:
            raise
        except Exception as exc:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED) from exc
        finally:
            _wipe(data_key)

    def _parse(self, value: str) -> dict:
        if not isinstance(value, str) or not value.startswith(self.PREFIX):
            raise KeyManagementError(KeyFailure.INVALID_ENVELOPE)
        try:
            envelope = json.loads(_b64d(value[len(self.PREFIX):]))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise KeyManagementError(KeyFailure.INVALID_ENVELOPE) from exc
        if not isinstance(envelope, dict) or set(envelope) != self._FIELDS:
            raise KeyManagementError(KeyFailure.INVALID_ENVELOPE)
        if (envelope["schema_version"] != self.SCHEMA_VERSION
                or envelope["encryption_algorithm"] != self.ENCRYPTION_ALGORITHM
                or envelope["wrapping_algorithm"] != self.provider.wrapping_algorithm
                or envelope["provider_id"] != self.provider.provider_id
                or envelope["key_id"] != self.provider.key_id
                or envelope["key_version"] not in self.provider.approved_versions):
            raise KeyManagementError(KeyFailure.UNSUPPORTED_POLICY)
        return envelope

    def _validate_context(self, envelope: dict, context: EncryptionContext) -> bytes:
        if envelope["context"] != context.canonical():
            raise KeyManagementError(KeyFailure.CONTEXT_MISMATCH)
        expected = hashlib.sha256(_canonical_json({**context.canonical(),
                                                   "schema_version": self.SCHEMA_VERSION,
                                                   "key_version": envelope["key_version"]})).hexdigest().encode()
        self.provider.validate_context(str(envelope["context_hash"]).encode(), expected)
        return self._content_aad(context)

    def decrypt(self, value: str, context: EncryptionContext) -> tuple[bytes, bool]:
        envelope = self._parse(value)
        aad = self._validate_context(envelope, context)
        data_key: bytearray | None = None
        try:
            data_key = self.provider.unwrap(_b64d(envelope["wrapped_data_key"]),
                                            version=envelope["key_version"], aad=aad)
            self.provider.validate_context(str(envelope["integrity_hmac"]).encode(),
                                           self._integrity(bytes(data_key), envelope).encode())
            nonce, tag = _b64d(envelope["nonce"]), _b64d(envelope["tag"])
            if len(nonce) != 12 or len(tag) != 16:
                raise KeyManagementError(KeyFailure.INVALID_ENVELOPE)
            plaintext = AESGCM(bytes(data_key)).decrypt(nonce, _b64d(envelope["ciphertext"]) + tag, aad)
            return plaintext, envelope["key_version"] != self.provider.active_version
        except KeyManagementError:
            raise
        except (InvalidTag, ValueError, TypeError) as exc:
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED) from exc
        finally:
            _wipe(data_key)

    def rewrap(self, value: str, context: EncryptionContext) -> str:
        envelope = self._parse(value)
        aad = self._validate_context(envelope, context)
        if envelope["key_version"] == self.provider.active_version:
            return value
        data_key: bytearray | None = None
        try:
            data_key = self.provider.unwrap(_b64d(envelope["wrapped_data_key"]),
                                            version=envelope["key_version"], aad=aad)
            self.provider.validate_context(str(envelope["integrity_hmac"]).encode(),
                                           self._integrity(bytes(data_key), envelope).encode())
            envelope["key_version"] = self.provider.active_version
            envelope["context_hash"] = hashlib.sha256(_canonical_json({**context.canonical(),
                "schema_version": self.SCHEMA_VERSION, "key_version": self.provider.active_version})).hexdigest()
            envelope["wrapped_data_key"] = _b64e(self.provider.wrap(
                bytes(data_key), version=self.provider.active_version, aad=aad))
            envelope["integrity_hmac"] = self._integrity(bytes(data_key), envelope)
            return self.PREFIX + _b64e(_canonical_json(envelope))
        finally:
            _wipe(data_key)

    def rotate(self, value: str, context: EncryptionContext) -> str:
        return self.rewrap(value, context)


def decode_local_keys(raw: str) -> dict[str, bytes]:
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        return {str(version): _b64d(value) for version, value in data.items()}
    except (KeyManagementError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise KeyManagementError(KeyFailure.INVALID_CONFIGURATION) from exc


def rewrap_recovered_envelope(value: str, context: EncryptionContext, data_key: bytearray,
                              replacement: KeyManagementProvider) -> str:
    """Offline-only recovery primitive; callers obtain the DEK from separately held material."""
    if not value.startswith(EnvelopeEncryptionService.PREFIX) or len(data_key) != 32:
        raise KeyManagementError(KeyFailure.RECOVERY_FAILED)
    try:
        envelope = json.loads(_b64d(value[len(EnvelopeEncryptionService.PREFIX):]))
        if not isinstance(envelope, dict) or set(envelope) != EnvelopeEncryptionService._FIELDS:
            raise KeyManagementError(KeyFailure.INVALID_ENVELOPE)
        if envelope["context"] != context.canonical():
            raise KeyManagementError(KeyFailure.CONTEXT_MISMATCH)
        expected_integrity = EnvelopeEncryptionService._integrity(bytes(data_key), envelope)
        if not hmac.compare_digest(str(envelope["integrity_hmac"]), expected_integrity):
            raise KeyManagementError(KeyFailure.AUTHENTICATION_FAILED)
        aad = _canonical_json({"schema_version": EnvelopeEncryptionService.SCHEMA_VERSION,
                               "encryption_algorithm": EnvelopeEncryptionService.ENCRYPTION_ALGORITHM,
                               "context": context.canonical()})
        AESGCM(bytes(data_key)).decrypt(_b64d(envelope["nonce"]),
                                        _b64d(envelope["ciphertext"]) + _b64d(envelope["tag"]), aad)
        envelope["provider_id"] = replacement.provider_id
        envelope["wrapping_algorithm"] = replacement.wrapping_algorithm
        envelope["key_id"] = replacement.key_id
        envelope["key_version"] = replacement.active_version
        envelope["context_hash"] = hashlib.sha256(_canonical_json({**context.canonical(),
            "schema_version": EnvelopeEncryptionService.SCHEMA_VERSION,
            "key_version": replacement.active_version})).hexdigest()
        envelope["wrapped_data_key"] = _b64e(replacement.wrap(
            bytes(data_key), version=replacement.active_version, aad=aad))
        envelope["integrity_hmac"] = EnvelopeEncryptionService._integrity(bytes(data_key), envelope)
        return EnvelopeEncryptionService.PREFIX + _b64e(_canonical_json(envelope))
    except KeyManagementError:
        raise
    except (InvalidTag, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise KeyManagementError(KeyFailure.RECOVERY_FAILED) from exc
