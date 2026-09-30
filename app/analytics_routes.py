from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import analytics_service, database, models
from app.auth_routes import get_current_user_model
from app.authorization import require_operator_user as require_admin_user
from app.tenant_repository import TenantRepository, TenantScopeError, operator_aggregate_scope


router = APIRouter()


def _repository(db: Session) -> TenantRepository:
    context = db.info.get("tenant_context")
    if context is None:
        raise TenantScopeError("validated_tenant_required")
    return TenantRepository(db, context)


class AnalyticsEventCreate(BaseModel):
    event_name: str = Field(..., min_length=2, max_length=120)
    metadata: dict[str, Any] | None = None
    source: str = Field(default="frontend", max_length=80)


@router.get("/status")
def analytics_status():
    return {
        "analytics": analytics_service.analytics_status(),
        "error_tracking": analytics_service.sentry_status(),
        "live_trading_enabled": False,
    }


@router.post("/events")
def capture_event(
    request: AnalyticsEventCreate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    event = analytics_service.capture_event(
        db,
        event_name=request.event_name,
        user_id=current_user.id,
        metadata=request.metadata,
        source=request.source,
    )
    if event is None:
        return {
            "captured": False,
            "reason": "analytics_disabled",
            "analytics": analytics_service.analytics_status(),
            "live_trading_enabled": False,
        }
    db.commit()
    db.refresh(event)
    payload = analytics_service.serialize_event(event)
    payload["captured"] = True
    payload["live_trading_enabled"] = False
    return payload


def _window(start: str | None, end: str | None):
    return analytics_service.date_window(start, end)


@router.get("/admin/events")
def admin_list_events(
    start: str | None = None,
    end: str | None = None,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt = _window(start, end)
    events = _repository(db).list(
        models.AnalyticsEvent,
        models.AnalyticsEvent.created_at >= start_dt,
        models.AnalyticsEvent.created_at <= end_dt,
        order_by=(models.AnalyticsEvent.created_at.desc(),), limit=100,
    )
    return {
        "events": [analytics_service.serialize_event(event) for event in events],
        "privacy": {"user_safe_ids_only": True, "raw_user_ids_returned": False},
    }


@router.get("/admin/onboarding-funnel")
def admin_onboarding_funnel(
    start: str | None = None,
    end: str | None = None,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt = _window(start, end)
    with operator_aggregate_scope(db, "analytics-aggregate"):
        return analytics_service.onboarding_funnel(db, start=start_dt, end=end_dt)


@router.get("/admin/activation-retention")
def admin_activation_retention(
    start: str | None = None,
    end: str | None = None,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt = _window(start, end)
    with operator_aggregate_scope(db, "analytics-aggregate"):
        return analytics_service.activation_retention(db, start=start_dt, end=end_dt)


@router.get("/admin/engagement")
def admin_engagement(
    start: str | None = None,
    end: str | None = None,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt = _window(start, end)
    with operator_aggregate_scope(db, "analytics-aggregate"):
        return analytics_service.engagement_metrics(db, start=start_dt, end=end_dt)


@router.get("/admin/summary")
def admin_summary(
    start: str | None = None,
    end: str | None = None,
    admin_user: models.User = Depends(require_admin_user),
    db: Session = Depends(database.get_db),
):
    start_dt, end_dt = _window(start, end)
    with operator_aggregate_scope(db, "analytics-aggregate"):
        return analytics_service.analytics_summary(db, start=start_dt, end=end_dt)
