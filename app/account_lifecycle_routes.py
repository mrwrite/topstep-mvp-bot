from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import database, models
from .auth_routes import get_current_user_model
from .observability import redact
from .security import verify_password
from .authorization import TenantContext
from .tenant_repository import TenantRepository
from .time_utils import utc_now

router = APIRouter()

FORBIDDEN_EXPORT_COLUMNS = {
    "hashed_password",
    "credentials_encrypted",
    "csrf_token_hash",
    "ip_hash",
    "token_hash",
    "confirmation_hash",
    "stripe_secret_key",
    "stripe_webhook_secret",
}


class DeletionConfirmation(BaseModel):
    password: str
    confirmation: str = Field(..., pattern=r"^DELETE MY ACCOUNT$")


class DeletionCancellation(BaseModel):
    password: str
    confirmation: str = Field(..., pattern=r"^KEEP MY ACCOUNT$")


def _serialize(row) -> dict:
    result = {}
    for attribute in row.__mapper__.column_attrs:
        column = attribute.columns[0]
        if column.name in FORBIDDEN_EXPORT_COLUMNS or attribute.key in FORBIDDEN_EXPORT_COLUMNS:
            continue
        value = getattr(row, attribute.key)
        result[column.name] = value.isoformat() + "Z" if isinstance(value, datetime) else redact(value)
    return result


def _user_owned_models() -> list[type]:
    excluded = {
        models.User,
        models.UserSession,
        models.EmailVerificationToken,
        models.PasswordResetToken,
        models.AccountDeletionRequest,
        models.SecurityAuditEvent,
    }
    return sorted(
        (
            mapper.class_
            for mapper in models.Base.registry.mappers
            if mapper.class_ not in excluded and "user_id" in mapper.local_table.c
        ),
        key=lambda model: model.__tablename__,
    )


def _audit(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    outcome: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        models.SecurityAuditEvent(
            actor_user_id=user_id,
            target_user_id=user_id,
            event_type="account_lifecycle",
            action=action,
            reason="user_requested",
            outcome=outcome,
            event_metadata=metadata,
        )
    )


@router.get("/account/export")
def export_account_data(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    repository = TenantRepository(
        db, TenantContext(current_user.id, current_user.username, actor_user_id=current_user.id, source="session")
    )
    records: dict[str, list[dict]] = {}
    for model in _user_owned_models():
        records[model.__tablename__] = [
            _serialize(row)
            for row in repository.list(model)
        ]
    audit_rows = repository.audit_history()
    profile = _serialize(current_user)
    profile.pop("is_admin", None)
    _audit(db, user_id=current_user.id, action="export", outcome="completed")
    db.commit()
    return {
        "schema_version": 1,
        "generated_at": utc_now().isoformat(),
        "profile": profile,
        "records": records,
        "audit_history": [_serialize(row) for row in audit_rows],
        "exclusions": "Passwords, credentials, session secrets, token hashes, and internal security metadata are excluded.",
    }


@router.post("/account/deletion-requests", status_code=status.HTTP_201_CREATED)
def request_account_deletion(
    payload: DeletionConfirmation,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Password confirmation failed.")
    repository = TenantRepository(
        db, TenantContext(current_user.id, current_user.username, actor_user_id=current_user.id, source="session")
    )
    existing = repository.first(
            models.AccountDeletionRequest,
            models.AccountDeletionRequest.status.in_(("pending", "blocked_legal_hold")),
    )
    if existing:
        return {"id": existing.id, "status": existing.status, "execute_after": existing.execute_after}
    now = utc_now().replace(tzinfo=None)
    record = models.AccountDeletionRequest(
        user_id=current_user.id,
        status="blocked_legal_hold" if database.APP_CONFIG.account_legal_hold else "pending",
        execute_after=now + timedelta(days=database.APP_CONFIG.account_deletion_grace_days),
        legal_hold=int(database.APP_CONFIG.account_legal_hold),
        retention_days=database.APP_CONFIG.account_retention_days,
        confirmation_hash=sha256(payload.confirmation.encode()).hexdigest(),
    )
    repository.add(record)
    db.flush()
    _audit(db, user_id=current_user.id, action="deletion_requested", outcome=record.status)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": record.status, "execute_after": record.execute_after}


@router.post("/account/deletion-requests/{request_id}/execute")
def execute_account_deletion(
    request_id: int,
    payload: DeletionConfirmation,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Password confirmation failed.")
    repository = TenantRepository(
        db, TenantContext(current_user.id, current_user.username, actor_user_id=current_user.id, source="session")
    )
    record = repository.get(models.AccountDeletionRequest, request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deletion request not found.")
    now = utc_now().replace(tzinfo=None)
    if record.legal_hold:
        raise HTTPException(status_code=409, detail="Deletion is blocked by a configured legal hold.")
    if record.execute_after > now:
        raise HTTPException(status_code=409, detail="Deletion grace period has not elapsed.")
    if record.status == "completed":
        return {"status": "completed", "revocations": record.outcome_metadata}

    integrations = repository.list(models.PlatformIntegration)
    revocations = []
    for integration in integrations:
        if integration.provider == "TRADINGVIEW":
            outcome, retryable, confirmed = "not_applicable_local_secret_deleted", 0, 0
        else:
            outcome, retryable, confirmed = "provider_revocation_unconfirmed", 1, 0
        db.add(
            models.ProviderRevocationAttempt(
                user_id=current_user.id,
                deletion_request_id=record.id,
                integration_id=integration.id,
                provider=integration.provider,
                outcome=outcome,
                retryable=retryable,
                provider_confirmed=confirmed,
                detail="Stored credential material was deleted; no external revocation was claimed.",
            )
        )
        integration.credentials_encrypted = None
        integration.status = "disabled"
        revocations.append({"provider": integration.provider, "outcome": outcome, "retryable": bool(retryable)})

    repository.update(
        models.UserSession,
        (models.UserSession.revoked_at.is_(None),),
        {"revoked_at": now, "revocation_reason": "account_deleted"},
    )
    original_id = current_user.id
    identity_hash = sha256(f"{original_id}:{current_user.email.lower()}".encode()).hexdigest()
    current_user.account_status = "deleted"
    current_user.deleted_at = now
    current_user.username = f"deleted_{original_id}_{uuid4().hex[:12]}"
    current_user.email = f"deleted_{original_id}_{uuid4().hex[:12]}@deleted.invalid"
    current_user.hashed_password = f"deleted:{uuid4().hex}"
    current_user.display_name = None
    current_user.preferred_contact_email = None
    current_user.active_integration_id = None
    record.status = "completed_with_revocation_gaps" if any(item["retryable"] for item in revocations) else "completed"
    record.executed_at = now
    record.outcome_metadata = {
        "revocations": revocations,
        "retention_days": record.retention_days,
        "irreversible_after": (now + timedelta(days=record.retention_days)).isoformat() + "Z",
    }
    db.add(models.DeletionTombstone(
        id=str(uuid4()),
        user_id=original_id,
        identity_hash=identity_hash,
        deletion_request_id=record.id,
        executed_at=now,
        purge_eligible_at=now + timedelta(days=record.retention_days),
        legal_hold=record.legal_hold,
        status="active",
    ))
    _audit(db, user_id=original_id, action="deletion_executed", outcome=record.status, metadata=record.outcome_metadata)
    db.commit()
    return {"status": record.status, **record.outcome_metadata}


@router.post("/account/deletion-requests/{request_id}/cancel")
def cancel_account_deletion(
    request_id: int,
    payload: DeletionCancellation,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Password confirmation failed.")
    repository = TenantRepository(
        db, TenantContext(current_user.id, current_user.username, actor_user_id=current_user.id, source="session")
    )
    record = repository.get(models.AccountDeletionRequest, request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deletion request not found.")
    if record.status not in {"pending", "blocked_legal_hold"} or record.executed_at is not None:
        raise HTTPException(status_code=409, detail="Deletion request can no longer be cancelled.")
    record.status = "cancelled"
    _audit(db, user_id=current_user.id, action="deletion_cancelled", outcome="cancelled")
    db.commit()
    return {"id": record.id, "status": "cancelled"}
