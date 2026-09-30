import base64
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.key_management import EncryptionContext, EnvelopeEncryptionService, LocalDevelopmentKeyProvider
from app.key_rotation import (claim_items, create_operation, process_item, reconcile,
                              retirement_allowed, retry_failed, transition)


def _database():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _integration(db, blob):
    user = models.User(username="key-user", email="key@example.test", hashed_password="hash")
    db.add(user)
    db.flush()
    integration = models.PlatformIntegration(user_id=user.id, display_name="test", provider="tradingview",
                                             status="active", credentials_encrypted=blob)
    db.add(integration)
    db.commit()
    return integration


def _context(integration):
    return EncryptionContext(str(integration.user_id), "integration-credentials",
                             "platform-integration", str(integration.id), "test", "1")


def _decode(value):
    encoded = value.removeprefix("envelope:v2:")
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def test_rotation_is_idempotent_resumable_and_retirement_guarded():
    db = _database()
    old = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    integration = _integration(db, None)
    integration.credentials_encrypted = old.encrypt(b'{"token":"value"}', _context(integration))
    db.commit()
    before = _decode(integration.credentials_encrypted)
    operation = create_operation(db, operation_type="rotation", source_version="v1",
                                 target_version="v2", operation_id="rotation-1", backup_verified=True)
    assert create_operation(db, operation_type="rotation", source_version="v1",
                            target_version="v2", operation_id="rotation-1").id == operation.id
    transition(db, operation.id, "active-write")
    transition(db, operation.id, "rewrapping")
    item = claim_items(db, operation.id, "worker-a", 1)[0]
    assert claim_items(db, operation.id, "worker-b", 1) == []
    rotating = EnvelopeEncryptionService(LocalDevelopmentKeyProvider(
        {"v1": b"1" * 32, "v2": b"2" * 32}, "v2"))
    process_item(db, item.id, rotating)
    process_item(db, item.id, rotating)
    counts = reconcile(db, operation.id)
    db.refresh(integration)
    after = _decode(integration.credentials_encrypted)
    assert counts == {"total": 1, "pending": 0, "processing": 0, "succeeded": 1, "failed": 0}
    assert (before["nonce"], before["ciphertext"], before["tag"]) == (
        after["nonce"], after["ciphertext"], after["tag"])
    transition(db, operation.id, "verifying")
    transition(db, operation.id, "ready-to-retire")
    assert not retirement_allowed(operation, counts)
    operation.operation_metadata = {"backup_verified": True, "recovery_verified": True,
                                    "rollback_approved": True, "retirement_approved": True}
    db.commit()
    assert retirement_allowed(operation, counts)


def test_fernet_migration_failure_retry_and_envelope_only_rejection(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "migration-secret")
    monkeypatch.setenv("KEY_MANAGEMENT_PROVIDER", "local-development")
    monkeypatch.setenv("LEGACY_FERNET_MODE", "migration")
    from app import crypto
    legacy = crypto._get_fernet().encrypt(b'{"apiKey":"legacy"}').decode()
    db = _database()
    integration = _integration(db, legacy)
    operation = create_operation(db, operation_type="fernet-migration", target_version="local-v1",
                                 operation_id="migration-1", backup_verified=True)
    transition(db, operation.id, "migrating")
    item = claim_items(db, operation.id, "worker", 1)[0]
    service = crypto._envelope_service()
    process_item(db, item.id, service)
    assert reconcile(db, operation.id)["succeeded"] == 1
    db.refresh(integration)
    assert integration.credentials_encrypted.startswith("envelope:v2:")
    assert service.decrypt(integration.credentials_encrypted, _context(integration))[0] == b'{"apiKey":"legacy"}'
    assert retry_failed(db, operation.id) == 0
    monkeypatch.setenv("LEGACY_FERNET_MODE", "envelope-only")
    try:
        crypto.decrypt_credentials(legacy, user_id=integration.user_id, record_id=integration.id)
    except ValueError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("legacy ciphertext was accepted after cutover")


def test_changed_record_fails_closed_and_can_be_reconciled():
    db = _database()
    integration = _integration(db, "legacy-a")
    operation = create_operation(db, operation_type="fernet-migration", target_version="local-v1",
                                 operation_id="migration-change")
    transition(db, operation.id, "migrating")
    item = claim_items(db, operation.id, "worker", 1)[0]
    integration.credentials_encrypted = "legacy-b"
    db.commit()
    service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"local-v1": b"1" * 32}, "local-v1"))
    process_item(db, item.id, service)
    counts = reconcile(db, operation.id)
    assert counts["failed"] == 1
    assert retry_failed(db, operation.id) == 1


def test_crash_before_migration_commit_rolls_back_and_retry_is_idempotent(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "crash-test-secret")
    monkeypatch.setenv("KEY_MANAGEMENT_PROVIDER", "local-development")
    monkeypatch.setenv("LEGACY_FERNET_MODE", "migration")
    from app import crypto
    legacy = crypto._get_fernet().encrypt(b'{"apiKey":"legacy"}').decode()
    db = _database()
    integration = _integration(db, legacy)
    operation = create_operation(db, operation_type="fernet-migration", target_version="local-v1",
                                 operation_id="migration-crash", backup_verified=True)
    transition(db, operation.id, "migrating")
    item = claim_items(db, operation.id, "crashing-worker", 1)[0]
    real_commit = db.commit

    def crash_before_commit():
        raise RuntimeError("simulated_crash_before_commit")

    monkeypatch.setattr(db, "commit", crash_before_commit)
    with pytest.raises(RuntimeError, match="simulated_crash"):
        process_item(db, item.id, crypto._envelope_service())
    monkeypatch.setattr(db, "commit", real_commit)
    db.rollback()
    db.refresh(integration)
    assert integration.credentials_encrypted == legacy
    claimed = db.query(models.KeyManagementItem).filter_by(id=item.id).one()
    claimed.claim_expires_at = claimed.created_at
    real_commit()
    retried = claim_items(db, operation.id, "replacement-worker", 1)[0]
    process_item(db, retried.id, crypto._envelope_service())
    db.refresh(integration)
    migrated_once = integration.credentials_encrypted
    process_item(db, retried.id, crypto._envelope_service())
    db.refresh(integration)
    assert integration.credentials_encrypted == migrated_once
    assert reconcile(db, operation.id)["succeeded"] == 1
