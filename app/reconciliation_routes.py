from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.reconciliation_service import (
    reconciliation_service,
    serialize_reconciliation_event,
    serialize_reconciliation_run,
    serialize_retry_decision,
)


router = APIRouter()


class RetryDecisionRequest(BaseModel):
    integration_id: int | None = None
    account_id: str | None = None
    provider_order_id: str | None = None
    client_order_id: str | None = None
    error: str


def _assert_integration_owned(db: Session, *, user_id: int, integration_id: int | None) -> None:
    if integration_id is None:
        return
    integration = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.id == integration_id, models.PlatformIntegration.user_id == user_id)
        .first()
    )
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")


@router.get("/runs")
def list_reconciliation_runs(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    runs = (
        db.query(models.ProviderReconciliationRun)
        .filter(models.ProviderReconciliationRun.user_id == current_user.id)
        .order_by(models.ProviderReconciliationRun.created_at.desc())
        .limit(100)
        .all()
    )
    return [serialize_reconciliation_run(run) for run in runs]


@router.get("/runs/{run_id}/events")
def list_reconciliation_events(
    run_id: int,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    run = (
        db.query(models.ProviderReconciliationRun)
        .filter(models.ProviderReconciliationRun.id == run_id, models.ProviderReconciliationRun.user_id == current_user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found.")
    events = (
        db.query(models.ProviderReconciliationEvent)
        .filter(models.ProviderReconciliationEvent.run_id == run.id)
        .order_by(models.ProviderReconciliationEvent.created_at.asc())
        .all()
    )
    return [serialize_reconciliation_event(event) for event in events]


@router.get("/retry-decisions")
def list_retry_decisions(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    decisions = (
        db.query(models.ProviderRetryDecision)
        .filter(models.ProviderRetryDecision.user_id == current_user.id)
        .order_by(models.ProviderRetryDecision.created_at.desc())
        .limit(100)
        .all()
    )
    return [serialize_retry_decision(decision) for decision in decisions]


@router.post("/retry-decisions")
def create_retry_decision(
    request: RetryDecisionRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    _assert_integration_owned(db, user_id=current_user.id, integration_id=request.integration_id)
    decision = reconciliation_service.create_retry_decision(
        db,
        user_id=current_user.id,
        integration_id=request.integration_id,
        account_id=request.account_id,
        provider_order_id=request.provider_order_id,
        client_order_id=request.client_order_id,
        error=request.error,
    )
    db.commit()
    db.refresh(decision)
    return serialize_retry_decision(decision)
