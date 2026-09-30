from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import beta_access_service, database, models
from .auth_routes import get_current_user_model
from .authorization import require_operator_user as require_admin_user
from .tenant_repository import OperatorRepository, operator_global_scope
from .time_utils import utc_now

router = APIRouter()


class InviteCreateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=8, max_length=80)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)
    email_restriction: str | None = Field(default=None, max_length=255)
    campaign: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class InviteRedeemRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=80)
    metadata: dict[str, Any] | None = None


class WaitlistRequest(BaseModel):
    email: str = Field(..., max_length=255)
    name: str | None = Field(default=None, max_length=120)
    use_case: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] | None = None


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


def require_current_beta_access(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
) -> models.User:
    beta_access_service.require_beta_access(db, current_user)
    return current_user


@router.get("/status")
def get_beta_status(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return beta_access_service.combined_beta_readiness(db, current_user)


@router.get("/access-check")
def beta_access_check(
    current_user: models.User = Depends(require_current_beta_access),
    db: Session = Depends(database.get_db),
):
    return beta_access_service.combined_beta_readiness(db, current_user)


@router.post("/invites/redeem")
def redeem_invite(
    request: InviteRedeemRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    payload = beta_access_service.redeem_invite(
        db,
        user=current_user,
        code=request.code,
        metadata=request.metadata,
    )
    db.commit()
    return payload


@router.post("/waitlist")
def join_waitlist(request: WaitlistRequest, db: Session = Depends(database.get_db)):
    entry = beta_access_service.upsert_waitlist(
        db,
        email=request.email,
        name=request.name,
        use_case=request.use_case,
        source=request.source,
        metadata=request.metadata,
    )
    db.commit()
    return {
        "status": entry.status,
        "message": "Waitlist request received.",
        "live_trading_enabled": False,
    }


@router.post("/waitlist/me")
def join_authenticated_waitlist(
    request: WaitlistRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    entry = beta_access_service.upsert_waitlist(
        db,
        email=request.email,
        user_id=current_user.id,
        name=request.name,
        use_case=request.use_case,
        source=request.source,
        metadata=request.metadata,
    )
    db.commit()
    return {
        "status": entry.status,
        "message": "Waitlist request received.",
        "live_trading_enabled": False,
    }


@router.post("/admin/invites")
def create_invite(
    request: InviteCreateRequest,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    invite, raw_code = beta_access_service.create_invite(
        db,
        issued_by_user_id=admin_user.id,
        code=request.code,
        max_uses=request.max_uses,
        expires_in_days=request.expires_in_days,
        email_restriction=request.email_restriction,
        campaign=request.campaign,
        source=request.source,
        notes=request.notes,
        metadata=request.metadata,
    )
    db.commit()
    db.refresh(invite)
    return beta_access_service.serialize_invite(invite, include_code=raw_code)


@router.get("/admin/invites")
def list_invites(
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    invites = OperatorRepository(db).global_list(
        models.BetaInviteCode, order_by=(models.BetaInviteCode.created_at.desc(),), limit=100
    )
    return {"invites": [beta_access_service.serialize_invite(invite) for invite in invites]}


@router.post("/admin/invites/{invite_id}/disable")
def disable_invite(
    invite_id: int,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    invite = OperatorRepository(db).global_get(models.BetaInviteCode, invite_id)
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    invite.status = beta_access_service.INVITE_STATUS_DISABLED
    invite.disabled_at = utc_now().replace(tzinfo=None)
    db.commit()
    db.refresh(invite)
    return beta_access_service.serialize_invite(invite)


@router.get("/admin/waitlist")
def list_waitlist(
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    entries = OperatorRepository(db).global_list(
        models.BetaWaitlistEntry, order_by=(models.BetaWaitlistEntry.created_at.desc(),), limit=100
    )
    return {"waitlist": [beta_access_service.serialize_waitlist(entry) for entry in entries]}


@router.post("/admin/waitlist/{entry_id}/approve")
def approve_waitlist_entry(
    entry_id: int,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    entry = OperatorRepository(db).global_get(models.BetaWaitlistEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found.")
    with operator_global_scope(db, "beta-waitlist-administration"):
        entry.status = "approved"
        entry.approved_by_user_id = admin_user.id
        entry.approved_at = utc_now().replace(tzinfo=None)
        if entry.user_id:
            beta_access_service.ensure_active_beta_status(
                db,
                user_id=entry.user_id,
                source="waitlist",
                approved_by_user_id=admin_user.id,
                reason="waitlist_approved",
            )
        db.commit()
        db.refresh(entry)
    return beta_access_service.serialize_waitlist(entry)


@router.post("/admin/users/{user_id}/suspend")
def suspend_user_beta_access(
    user_id: int,
    request: SuspendRequest,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    record = beta_access_service.beta_status_record(db, user_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beta status not found.")
    record.status = beta_access_service.BETA_STATUS_SUSPENDED
    record.reason = request.reason
    record.suspended_at = utc_now().replace(tzinfo=None)
    record.updated_at = record.suspended_at
    db.commit()
    return {"status": record.status, "user_id": user_id, "live_trading_enabled": False}
