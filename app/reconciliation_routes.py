from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.authorization import TenantContext
from app.tenant_repository import TenantRepository
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


def _repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session"))


def _assert_integration_owned(repository: TenantRepository, *, integration_id: int | None) -> None:
    if integration_id is None:
        return
    integration = repository.get(models.PlatformIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")


@router.get("/runs")
def list_reconciliation_runs(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    runs = _repository(db, current_user).list(
        models.ProviderReconciliationRun,
        order_by=(models.ProviderReconciliationRun.created_at.desc(),), limit=100,
    )
    return [serialize_reconciliation_run(run) for run in runs]


@router.get("/runs/{run_id}/events")
def list_reconciliation_events(
    run_id: int,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    repository = _repository(db, current_user)
    run = repository.get(models.ProviderReconciliationRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found.")
    events = repository.list(
        models.ProviderReconciliationEvent,
        models.ProviderReconciliationEvent.run_id == run.id,
        order_by=(models.ProviderReconciliationEvent.created_at.asc(),),
    )
    return [serialize_reconciliation_event(event) for event in events]


@router.get("/retry-decisions")
def list_retry_decisions(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    decisions = _repository(db, current_user).list(
        models.ProviderRetryDecision,
        order_by=(models.ProviderRetryDecision.created_at.desc(),), limit=100,
    )
    return [serialize_retry_decision(decision) for decision in decisions]


@router.post("/retry-decisions")
def create_retry_decision(
    request: RetryDecisionRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    _assert_integration_owned(_repository(db, current_user), integration_id=request.integration_id)
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
