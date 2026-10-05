from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .journal import LOCAL_SCHEMA_REVISION


# RFC 8032 test-vector public key. Production release engineering must replace
# this constant through a reviewed source change; it is never read from config.
EMBEDDED_RELEASE_PUBLIC_KEY_B64 = "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="
RELEASE_MANIFEST_FIELDS = frozenset(
    {
        "artifact_sha256",
        "expires_at",
        "issued_at",
        "minimum_policy_version",
        "revoked",
        "schema_max",
        "schema_min",
        "signature",
        "version",
    }
)
KNOWN_SCHEMA_REVISIONS = (LOCAL_SCHEMA_REVISION,)


class ReleaseVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class ReleaseVerification:
    accepted: bool
    classification: str
    version: str | None = None
    artifact_sha256: str | None = None


def canonical_manifest_payload(manifest: Mapping[str, Any]) -> bytes:
    payload = {key: manifest[key] for key in sorted(RELEASE_MANIFEST_FIELDS - {"signature"})}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ReleaseVerificationError("release_manifest_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseVerificationError("release_manifest_time_invalid") from exc
    if parsed.tzinfo is None:
        raise ReleaseVerificationError("release_manifest_time_invalid")
    return parsed.astimezone(timezone.utc)


class ReleaseVerifier:
    def __init__(self, public_key_b64: str = EMBEDDED_RELEASE_PUBLIC_KEY_B64) -> None:
        try:
            raw = base64.b64decode(public_key_b64, validate=True)
            self._public_key = Ed25519PublicKey.from_public_bytes(raw)
        except Exception as exc:
            raise ReleaseVerificationError("release_public_key_invalid") from exc

    def verify(
        self,
        manifest: Mapping[str, Any],
        artifact: Path,
        *,
        expected_version: str,
        current_schema: str = LOCAL_SCHEMA_REVISION,
        policy_version: int,
        now: datetime | None = None,
    ) -> ReleaseVerification:
        try:
            self._verify_or_raise(
                manifest,
                artifact,
                expected_version=expected_version,
                current_schema=current_schema,
                policy_version=policy_version,
                now=now,
            )
        except ReleaseVerificationError as exc:
            return ReleaseVerification(False, str(exc))
        except OSError:
            return ReleaseVerification(False, "release_artifact_unreadable")
        return ReleaseVerification(
            True,
            "release_verified",
            version=str(manifest["version"]),
            artifact_sha256=str(manifest["artifact_sha256"]),
        )

    def _verify_or_raise(
        self,
        manifest: Mapping[str, Any],
        artifact: Path,
        *,
        expected_version: str,
        current_schema: str,
        policy_version: int,
        now: datetime | None,
    ) -> None:
        if set(manifest) != RELEASE_MANIFEST_FIELDS:
            raise ReleaseVerificationError("release_manifest_shape_invalid")
        signature = manifest.get("signature")
        if not isinstance(signature, str):
            raise ReleaseVerificationError("release_signature_invalid")
        try:
            self._public_key.verify(
                base64.b64decode(signature, validate=True),
                canonical_manifest_payload(manifest),
            )
        except (ValueError, InvalidSignature) as exc:
            raise ReleaseVerificationError("release_signature_invalid") from exc
        if manifest.get("revoked") is not False:
            raise ReleaseVerificationError("release_revoked")
        if manifest.get("version") != expected_version:
            raise ReleaseVerificationError("release_version_mismatch")
        actual_hash = sha256(artifact.read_bytes()).hexdigest()
        expected_hash = manifest.get("artifact_sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or actual_hash != expected_hash.lower():
            raise ReleaseVerificationError("release_artifact_hash_mismatch")
        issued_at = _parse_time(manifest.get("issued_at"))
        expires_at = _parse_time(manifest.get("expires_at"))
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if issued_at > current_time or expires_at <= current_time or expires_at <= issued_at:
            raise ReleaseVerificationError("release_manifest_expired")
        minimum_policy = manifest.get("minimum_policy_version")
        if not isinstance(minimum_policy, int) or isinstance(minimum_policy, bool) or policy_version < minimum_policy:
            raise ReleaseVerificationError("release_policy_version_unsupported")
        self._verify_schema_range(
            current_schema,
            manifest.get("schema_min"),
            manifest.get("schema_max"),
        )

    @staticmethod
    def _verify_schema_range(current: str, minimum: object, maximum: object) -> None:
        if not all(isinstance(value, str) for value in (current, minimum, maximum)):
            raise ReleaseVerificationError("release_schema_range_invalid")
        try:
            current_index = KNOWN_SCHEMA_REVISIONS.index(current)
            minimum_index = KNOWN_SCHEMA_REVISIONS.index(minimum)
            maximum_index = KNOWN_SCHEMA_REVISIONS.index(maximum)
        except ValueError as exc:
            raise ReleaseVerificationError("release_schema_unsupported") from exc
        if minimum_index > current_index or current_index > maximum_index:
            raise ReleaseVerificationError("release_schema_unsupported")


def load_and_verify_release(
    manifest_path: Path,
    artifact_path: Path,
    **verification: Any,
) -> ReleaseVerification:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ReleaseVerification(False, "release_manifest_unreadable")
    if not isinstance(manifest, dict):
        return ReleaseVerification(False, "release_manifest_shape_invalid")
    return ReleaseVerifier().verify(manifest, artifact_path, **verification)
