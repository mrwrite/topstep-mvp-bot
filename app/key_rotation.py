from __future__ import annotations

import hashlib
from collections import Counter
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.crypto import migrate_legacy_credentials
from app.key_management import EncryptionContext, EnvelopeEncryptionService, KeyManagementError
from app.time_utils import utc_now


ACTIVE_STATES = {"planned", "active-write", "rewrapping", "migrating", "verifying", "paused", "failed"}
FINAL_STATES = {"ready-to-retire", "envelope-only", "completed"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_operation(db: Session, *, operation_type: str, target_version: str,
                     source_version: str | None = None, operation_id: str | None = None,
                     backup_verified: bool = False) -> models.KeyManagementOperation:
    if operation_type not in {"rotation", "fernet-migration", "recovery"}:
        raise ValueError("Unsupported key-management operation.")
    operation = models.KeyManagementOperation(
        id=operation_id or str(uuid4()), operation_type=operation_type,
        source_version=source_version, target_version=target_version, state="planned",
        operation_metadata={"backup_verified": backup_verified, "recovery_verified": False,
                            "rollback_approved": False, "retirement_approved": False},
    )
    db.add(operation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.query(models.KeyManagementOperation).filter_by(id=operation.id).one()

    query = db.query(models.PlatformIntegration).filter(
        models.PlatformIntegration.credentials_encrypted.isnot(None))
    if operation_type == "fernet-migration":
        query = query.filter(~models.PlatformIntegration.credentials_encrypted.startswith("envelope:v2:"))
    elif operation_type == "rotation":
        query = query.filter(models.PlatformIntegration.credentials_encrypted.startswith("envelope:v2:"))
    for integration in query.order_by(models.PlatformIntegration.id):
        db.add(models.KeyManagementItem(
            operation_id=operation.id, user_id=integration.user_id, integration_id=integration.id,
            status="pending", source_hash=_hash(integration.credentials_encrypted),
        ))
        operation.total_count += 1
    db.commit()
    db.refresh(operation)
    return operation


def transition(db: Session, operation_id: str, state: str) -> models.KeyManagementOperation:
    operation = db.query(models.KeyManagementOperation).filter_by(id=operation_id).with_for_update().one()
    allowed = {
        "planned": {"active-write", "migrating", "paused"},
        "active-write": {"rewrapping", "paused", "failed"},
        "rewrapping": {"verifying", "paused", "failed"},
        "migrating": {"verifying", "paused", "failed"},
        "verifying": {"ready-to-retire", "envelope-only", "paused", "failed"},
        "paused": {"rewrapping", "migrating", "verifying", "failed"},
        "failed": {"rewrapping", "migrating", "paused"},
        "ready-to-retire": {"completed"}, "envelope-only": {"completed"}, "completed": set(),
    }
    if state not in allowed.get(operation.state, set()):
        raise ValueError("Invalid key-management state transition.")
    operation.state = state
    if state == "completed":
        operation.completed_at = utc_now()
    db.commit()
    db.refresh(operation)
    return operation


def claim_items(db: Session, operation_id: str, worker_id: str, limit: int = 50,
                lease_seconds: int = 60) -> list[models.KeyManagementItem]:
    operation = db.query(models.KeyManagementOperation).filter_by(id=operation_id).first()
    if not operation or operation.state not in {"rewrapping", "migrating", "verifying"}:
        return []
    now = utc_now()
    (db.query(models.KeyManagementItem)
     .filter(models.KeyManagementItem.operation_id == operation_id,
             models.KeyManagementItem.status == "processing",
             models.KeyManagementItem.claim_expires_at < now)
     .update({"status": "pending", "claimed_by": None, "claim_expires_at": None},
             synchronize_session=False))
    query = (db.query(models.KeyManagementItem)
             .filter_by(operation_id=operation_id, status="pending")
             .order_by(models.KeyManagementItem.id))
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    else:
        query = query.with_for_update()
    items = query.limit(limit).all()
    for item in items:
        item.status = "processing"
        item.claimed_by = worker_id
        item.claim_expires_at = now + timedelta(seconds=lease_seconds)
        item.attempt_count += 1
    db.commit()
    return items


def process_item(db: Session, item_id: int, service: EnvelopeEncryptionService) -> None:
    item = db.query(models.KeyManagementItem).filter_by(id=item_id).with_for_update().one()
    operation = db.query(models.KeyManagementOperation).filter_by(id=item.operation_id).one()
    integration = (db.query(models.PlatformIntegration)
                   .filter_by(id=item.integration_id, user_id=item.user_id).with_for_update().one())
    current = integration.credentials_encrypted or ""
    context = EncryptionContext(str(item.user_id), "integration-credentials", "platform-integration",
                                str(item.integration_id), service_environment(), "1")
    try:
        if item.status == "succeeded" and item.result_hash == _hash(current):
            return
        if _hash(current) != item.source_hash and item.result_hash != _hash(current):
            raise ValueError("record_changed_since_inventory")
        if operation.operation_type == "rotation":
            replacement = service.rewrap(current, context)
        elif operation.operation_type == "fernet-migration":
            replacement = migrate_legacy_credentials(current, user_id=item.user_id, record_id=item.integration_id)
        else:
            raise ValueError("offline_recovery_requires_explicit_tool")
        service.decrypt(replacement, context)
        integration.credentials_encrypted = replacement
        item.result_hash = _hash(replacement)
        item.status = "succeeded"
        item.failure_code = None
    except (KeyManagementError, ValueError) as exc:
        item.status = "failed"
        item.failure_code = exc.code.value if isinstance(exc, KeyManagementError) else str(exc)
        item.claimed_by = None
        item.claim_expires_at = None
    db.commit()


def service_environment() -> str:
    import os
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()


def retry_failed(db: Session, operation_id: str) -> int:
    count = (db.query(models.KeyManagementItem).filter_by(operation_id=operation_id, status="failed")
             .update({"status": "pending", "failure_code": None, "claimed_by": None,
                      "claim_expires_at": None}, synchronize_session=False))
    db.commit()
    return count


def reconcile(db: Session, operation_id: str) -> dict[str, int]:
    operation = db.query(models.KeyManagementOperation).filter_by(id=operation_id).with_for_update().one()
    counts = Counter(status for (status,) in db.query(models.KeyManagementItem.status)
                     .filter_by(operation_id=operation_id).all())
    operation.succeeded_count = counts["succeeded"]
    operation.failed_count = counts["failed"]
    db.commit()
    return {"total": operation.total_count, "pending": counts["pending"],
            "processing": counts["processing"], "succeeded": counts["succeeded"],
            "failed": counts["failed"]}


def retirement_allowed(operation: models.KeyManagementOperation, counts: dict[str, int]) -> bool:
    evidence = operation.operation_metadata or {}
    return (operation.state == "ready-to-retire" and counts["total"] == counts["succeeded"]
            and not counts["pending"] and not counts["processing"] and not counts["failed"]
            and all(evidence.get(key) is True for key in (
                "backup_verified", "recovery_verified", "rollback_approved", "retirement_approved")))
