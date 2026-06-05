from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import beta_access_service, database, models, onboarding_service
from .auth_routes import get_current_user_model

router = APIRouter()


class MilestoneRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=120)


class SupportRequestCreate(BaseModel):
    category: str = Field(..., min_length=2, max_length=80)
    severity: str = Field(default="normal", max_length=40)
    subject: str = Field(..., min_length=4, max_length=160)
    message: str = Field(..., min_length=8, max_length=4000)
    integration_id: int | None = None
    paper_order_id: int | None = None
    bot_session_id: str | None = Field(default=None, max_length=120)
    diagnostics: dict[str, Any] | None = None


class SupportRequestUpdate(BaseModel):
    status: str = Field(..., min_length=2, max_length=40)


def require_admin_user(current_user: models.User = Depends(get_current_user_model)) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return current_user


def _assert_beta_gate(db: Session, user: models.User) -> None:
    readiness = beta_access_service.combined_beta_readiness(db, user)
    if not readiness["ready"]:
        first = readiness["blockers"][0]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Complete beta prerequisites before onboarding.", "blockers": readiness["blockers"]},
            headers={"X-Readiness-Blocker": first["code"]},
        )


@router.get("/status")
def get_onboarding_status(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return onboarding_service.onboarding_status(db, current_user)


@router.get("/gate")
def get_onboarding_gate(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    _assert_beta_gate(db, current_user)
    return onboarding_service.onboarding_status(db, current_user)


@router.post("/milestones")
def complete_milestone(
    request: MilestoneRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    payload = onboarding_service.mark_milestone(db, user=current_user, code=request.code)
    db.commit()
    return payload


@router.get("/help")
def help_topics():
    return {
        "topics": onboarding_service.HELP_TOPICS,
        "live_trading_enabled": False,
    }


@router.post("/support")
def create_support_request(
    request: SupportRequestCreate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    if request.severity not in {"low", "normal", "high", "urgent"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported severity.")
    record = onboarding_service.create_support_request(
        db,
        user=current_user,
        category=request.category,
        severity=request.severity,
        subject=request.subject,
        message=request.message,
        integration_id=request.integration_id,
        paper_order_id=request.paper_order_id,
        bot_session_id=request.bot_session_id,
        diagnostics=request.diagnostics,
    )
    db.commit()
    db.refresh(record)
    return onboarding_service.serialize_support_request(record)


@router.get("/support")
def list_support_requests(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    records = (
        db.query(models.SupportRequest)
        .filter(models.SupportRequest.user_id == current_user.id)
        .order_by(models.SupportRequest.created_at.desc())
        .limit(50)
        .all()
    )
    return {"support_requests": [onboarding_service.serialize_support_request(record) for record in records]}


@router.get("/admin/support")
def admin_list_support_requests(
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    records = (
        db.query(models.SupportRequest)
        .order_by(models.SupportRequest.created_at.desc())
        .limit(100)
        .all()
    )
    return {"support_requests": [onboarding_service.serialize_support_request(record) for record in records]}


@router.patch("/admin/support/{support_request_id}")
def admin_update_support_request(
    support_request_id: int,
    request: SupportRequestUpdate,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    if request.status not in {"open", "in_progress", "resolved", "closed"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported support request status.")
    record = db.query(models.SupportRequest).filter(models.SupportRequest.id == support_request_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support request not found.")
    record.status = request.status
    db.commit()
    db.refresh(record)
    return onboarding_service.serialize_support_request(record)
