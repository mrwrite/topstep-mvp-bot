from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import database, models, subscription_service
from app.auth_routes import get_current_user_model
from app.authorization import require_operator_user as require_admin_user
from app.tenant_repository import TenantRepository, TenantScopeError


router = APIRouter()


class FeatureCheckRequest(BaseModel):
    feature_code: str = Field(..., min_length=2, max_length=120)


class SubscriptionAssignmentRequest(BaseModel):
    plan_code: str = Field(..., min_length=2, max_length=80)
    status: str = Field(..., min_length=2, max_length=40)
    reason: str | None = Field(default=None, max_length=500)


class EntitlementGrantRequest(BaseModel):
    feature_code: str = Field(..., min_length=2, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


def _user_or_404(db: Session, user_id: int) -> models.User:
    context = db.info.get("tenant_context")
    if context is None or context.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user = TenantRepository(db, context).tenant_user()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.get("/plans")
def list_plans(db: Session = Depends(database.get_db)):
    subscription_service.ensure_default_plans(db)
    db.commit()
    return {
        "plans": subscription_service.list_plans(db),
        "billing": subscription_service.billing_status(),
        "live_trading_enabled": False,
    }


@router.get("/status")
def get_subscription_status(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    payload = subscription_service.status_payload(db, user=current_user)
    db.commit()
    return payload


@router.post("/entitlements/check")
def check_entitlement(
    request: FeatureCheckRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    payload = subscription_service.evaluate_entitlement(db, user=current_user, feature_code=request.feature_code)
    db.commit()
    return payload


@router.post("/billing/checkout")
def checkout_disabled(current_user: models.User = Depends(get_current_user_model)):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": "Billing and checkout are unavailable during invite-only paper beta.",
            "reason_code": subscription_service.BILLING_DISABLED_REASON,
            "billing": subscription_service.billing_status(),
            "live_trading_enabled": False,
        },
    )


@router.put("/admin/users/{user_id}/status")
def admin_assign_subscription_status(
    user_id: int,
    request: SubscriptionAssignmentRequest,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    target = _user_or_404(db, user_id)
    payload = subscription_service.assign_subscription_status(
        db,
        target_user=target,
        admin_user=admin_user,
        plan_code=request.plan_code,
        status_value=request.status,
        reason=request.reason,
    )
    db.commit()
    return payload


@router.post("/admin/users/{user_id}/entitlements")
def admin_grant_entitlement(
    user_id: int,
    request: EntitlementGrantRequest,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    target = _user_or_404(db, user_id)
    payload = subscription_service.grant_entitlement(
        db,
        target_user=target,
        feature_code=request.feature_code,
        admin_user=admin_user,
        reason=request.reason,
    )
    db.commit()
    return payload
