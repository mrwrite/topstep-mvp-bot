from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from local_executor.config import ExecutorMode, LocalExecutorConfig
from local_executor.journal import LOCAL_SCHEMA_REVISION, LocalJournal
from local_executor.journal_models import AccountBinding, Installation, ReconciliationLock
from local_executor.maintenance import MaintenanceError, RecoveryManager, UpdateCoordinator
from local_executor.release import (
    ReleaseVerification,
    ReleaseVerifier,
    canonical_manifest_payload,
)


def signed_fixture(tmp_path: Path):
    artifact = tmp_path / "topstep-local-executor.exe"
    artifact.write_bytes(b"deterministic-executor-artifact")
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    manifest = {
        "artifact_sha256": sha256(artifact.read_bytes()).hexdigest(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "issued_at": (now - timedelta(minutes=1)).isoformat(),
        "minimum_policy_version": 3,
        "revoked": False,
        "schema_max": LOCAL_SCHEMA_REVISION,
        "schema_min": LOCAL_SCHEMA_REVISION,
        "version": "1.0.0",
    }
    manifest["signature"] = base64.b64encode(
        private_key.sign(canonical_manifest_payload({**manifest, "signature": ""}))
    ).decode("ascii")
    return artifact, manifest, ReleaseVerifier(public_key), now, private_key


def verify(verifier, manifest, artifact, now):
    return verifier.verify(
        manifest,
        artifact,
        expected_version="1.0.0",
        current_schema=LOCAL_SCHEMA_REVISION,
        policy_version=3,
        now=now,
    )


def test_signed_manifest_binds_artifact_version_schema_policy_and_time(tmp_path):
    artifact, manifest, verifier, now, _key = signed_fixture(tmp_path)
    result = verify(verifier, manifest, artifact, now)
    assert result.accepted is True
    assert result.classification == "release_verified"


@pytest.mark.parametrize(
    ("field", "value", "classification"),
    [
        ("version", "1.0.1", "release_signature_invalid"),
        ("revoked", True, "release_signature_invalid"),
        ("minimum_policy_version", 4, "release_signature_invalid"),
        ("schema_min", "unknown", "release_signature_invalid"),
    ],
)
def test_manifest_tampering_is_rejected_before_semantic_use(
    tmp_path, field, value, classification
):
    artifact, manifest, verifier, now, _key = signed_fixture(tmp_path)
    manifest[field] = value
    assert verify(verifier, manifest, artifact, now).classification == classification


def test_validly_signed_revoked_expired_policy_and_schema_releases_fail_closed(tmp_path):
    artifact, manifest, verifier, now, key = signed_fixture(tmp_path)
    cases = [
        ({"revoked": True}, "release_revoked"),
        ({"expires_at": (now - timedelta(seconds=1)).isoformat()}, "release_manifest_expired"),
        ({"minimum_policy_version": 4}, "release_policy_version_unsupported"),
        ({"schema_min": "unknown", "schema_max": "unknown"}, "release_schema_unsupported"),
    ]
    for changes, expected in cases:
        candidate = {**manifest, **changes, "signature": ""}
        candidate["signature"] = base64.b64encode(
            key.sign(canonical_manifest_payload(candidate))
        ).decode("ascii")
        assert verify(verifier, candidate, artifact, now).classification == expected


def test_artifact_tamper_and_missing_artifact_are_redacted(tmp_path):
    artifact, manifest, verifier, now, _key = signed_fixture(tmp_path)
    artifact.write_bytes(b"tampered")
    assert verify(verifier, manifest, artifact, now).classification == "release_artifact_hash_mismatch"
    artifact.unlink()
    assert verify(verifier, manifest, artifact, now).classification == "release_artifact_unreadable"


def test_environment_cannot_self_assert_signed_release(tmp_path):
    config = LocalExecutorConfig.from_environment(
        {
            "LOCALAPPDATA": str(tmp_path),
            "LOCAL_EXECUTOR_MODE": ExecutorMode.MUTATION.value,
            "LOCAL_EXECUTOR_SIGNED_RELEASE": "true",
        }
    )
    assert config.signed_release is False
    verified = config.with_verified_release(ReleaseVerification(True, "release_verified"))
    assert verified.signed_release is True


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "journal.db", secure_permissions=False)
    yield value
    value.close()


def test_update_halts_and_never_restores_mutation_state_without_preflight(journal):
    with journal.session_factory.begin() as session:
        installation = Installation(software_version="fixture", lifecycle_state="running")
        session.add(installation)
        session.flush()
        decision = UpdateCoordinator().prepare(
            session, installation, ReleaseVerification(True, "release_verified")
        )
        assert decision.allowed is True
        assert installation.lifecycle_state == "halted"
        failed = UpdateCoordinator.complete(installation, preflight_passed=False)
        assert failed.allowed is False
        assert installation.lifecycle_state == "halted"
        passed = UpdateCoordinator.complete(installation, preflight_passed=True)
        assert passed.allowed is True
        assert installation.lifecycle_state == "observe_only"


def test_update_interruption_preserves_reconciliation_lock_and_journal(journal):
    with journal.session_factory.begin() as session:
        installation = Installation(software_version="fixture", lifecycle_state="running")
        session.add(installation)
        session.flush()
        binding = AccountBinding(
            installation_id=installation.id,
            credential_generation=1,
            provider_account_id="practice-fixture",
            provider_account_hash="fixture-hash",
            account_attestation="practice",
            is_active=True,
        )
        session.add(binding)
        session.flush()
        session.add(ReconciliationLock(account_binding_id=binding.id, reason="ambiguous"))
        session.flush()
        decision = UpdateCoordinator().prepare(
            session, installation, ReleaseVerification(True, "release_verified")
        )
        assert decision.classification == "update_ambiguous_work_preserved"
        assert installation.lifecycle_state == "halted"
        assert decision.preserve_journal is True


def test_update_rejects_incompatible_schema_after_durable_halt(journal):
    with journal.session_factory.begin() as session:
        installation = Installation(software_version="fixture", lifecycle_state="running")
        session.add(installation)
        session.flush()
        decision = UpdateCoordinator().prepare(
            session,
            installation,
            ReleaseVerification(True, "release_verified"),
            target_schema_min="future_schema",
            target_schema_max="future_schema",
        )
        assert decision.classification == "update_schema_incompatible"
        assert installation.lifecycle_state == "halted"


def test_backup_restore_integrity_and_existing_destination_protection(journal, tmp_path):
    with journal.session_factory.begin() as session:
        session.add(Installation(software_version="fixture"))
    manager = RecoveryManager()
    record = manager.backup(journal, tmp_path / "backups" / "journal.db")
    manager.validate_backup(record)
    restored = manager.restore_to_new_path(record, tmp_path / "restored" / "journal.db")
    assert restored.is_file()
    with pytest.raises(MaintenanceError, match="must_not_exist"):
        manager.restore_to_new_path(record, restored)
    record.path.write_bytes(record.path.read_bytes() + b"tamper")
    with pytest.raises(MaintenanceError, match="backup_integrity_failed"):
        manager.validate_backup(record)


def test_uninstall_credential_removal_and_lost_device_never_claim_cancellation():
    removed = []
    manager = RecoveryManager()
    with pytest.raises(MaintenanceError, match="confirmation_required"):
        manager.remove_credentials("DELETE", lambda: removed.append(True))
    removal = manager.remove_credentials(
        "DELETE LOCAL CREDENTIALS", lambda: removed.append(True)
    )
    uninstall = manager.uninstall_plan()
    lost = manager.lost_device_plan()
    assert removed == [True]
    assert all(plan.provider_orders_cancelled is False for plan in (removal, uninstall, lost))
    assert "revoke" in " ".join(lost.steps).lower()
    assert "topstepx" in " ".join(uninstall.steps).lower()


def test_packaging_inputs_are_pinned_and_exclude_hosted_entrypoints():
    root = Path(__file__).resolve().parents[2]
    for lock_name in ("requirements.lock", "requirements-build.lock"):
        lines = [
            line.strip()
            for line in (root / "local_executor" / lock_name).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert lines
        assert all("==" in line for line in lines)
    for spec_name in ("windows_executor.spec", "macos_executor.spec"):
        spec = (root / "local_executor" / spec_name).read_text(encoding="utf-8")
        assert '"app"' in spec and '"uvicorn"' in spec and '"fastapi"' in spec
        assert "upx=False" in spec
        assert "root = Path(SPECPATH).parent\n" in spec
        assert 'root / "scripts" / "local_executor_entrypoint.py"' in spec
    windows_build = (root / "scripts" / "build_local_executor.ps1").read_text(
        encoding="utf-8"
    )
    macos_build = (root / "scripts" / "build_local_executor_macos.sh").read_text(
        encoding="utf-8"
    )
    assert "SOURCE_DATE_EPOCH" in windows_build
    assert "Get-FileHash" in windows_build
    assert "windows_installer.iss" in windows_build
    assert "SOURCE_DATE_EPOCH" in macos_build
    assert "shasum -a 256" in macos_build
    assert "hdiutil create" in macos_build
    assert "notarytool submit" in macos_build
