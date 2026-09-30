from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.authorization import TenantContext
from app.tenant_repository import TenantRepository
from app.launch_gate_service import launch_gate_service, serialize_acknowledgement, serialize_launch_gate_evaluation


router = APIRouter()


class AcknowledgementRequest(BaseModel):
    integration_id: int
    account_id: str
    symbol: str
    risk_settings_id: int | None = None
    confirm_no_profit_guarantee: bool
    confirm_user_responsibility: bool
    confirm_live_trading_still_disabled: bool


def _repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session"))


def _owned_integration(repository: TenantRepository, *, integration_id: int) -> models.PlatformIntegration:
    integration = repository.get(models.PlatformIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")
    return integration


@router.get("")
def evaluate_launch_gate(
    integration_id: int | None = Query(default=None),
    account_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return launch_gate_service.evaluate(
        db,
        user_id=current_user.id,
        integration_id=integration_id,
        account_id=account_id,
        symbol=symbol,
    )


@router.get("/evaluations")
def list_launch_gate_evaluations(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    evaluations = _repository(db, current_user).list(
        models.LaunchGateEvaluation,
        order_by=(models.LaunchGateEvaluation.created_at.desc(),), limit=100,
    )
    return [serialize_launch_gate_evaluation(evaluation) for evaluation in evaluations]


@router.post("/acknowledgements")
def create_acknowledgement(
    request: AcknowledgementRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    repository = _repository(db, current_user)
    _owned_integration(repository, integration_id=request.integration_id)
    if not (
        request.confirm_no_profit_guarantee
        and request.confirm_user_responsibility
        and request.confirm_live_trading_still_disabled
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All live-risk acknowledgement confirmations are required.",
        )
    risk_settings_id = request.risk_settings_id
    if risk_settings_id is None:
        settings_rows = repository.list(
                models.RiskSettings,
                models.RiskSettings.user_id == current_user.id,
                models.RiskSettings.integration_id == request.integration_id,
                models.RiskSettings.account_id == request.account_id,
                models.RiskSettings.trading_mode == "paper",
                models.RiskSettings.enabled == 1,
                order_by=(models.RiskSettings.id.desc(),), limit=1,
        )
        settings = settings_rows[0] if settings_rows else None
        if not settings:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Risk settings are required before acknowledgement.")
        risk_settings_id = settings.id
    else:
        settings = repository.get(models.RiskSettings, risk_settings_id)
        if not settings:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk settings not found.")

    ack = launch_gate_service.create_acknowledgement(
        db,
        user_id=current_user.id,
        integration_id=request.integration_id,
        account_id=request.account_id,
        symbol=request.symbol,
        risk_settings_id=risk_settings_id,
        metadata={
            "paper_only_currently": True,
            "no_profit_guarantee": request.confirm_no_profit_guarantee,
            "user_accepts_responsibility": request.confirm_user_responsibility,
            "live_trading_still_disabled": request.confirm_live_trading_still_disabled,
        },
    )
    return serialize_acknowledgement(ack)


@router.get("/acknowledgements")
def list_acknowledgements(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    acknowledgements = _repository(db, current_user).list(
        models.LiveReadinessAcknowledgement,
        order_by=(models.LiveReadinessAcknowledgement.accepted_at.desc(),), limit=100,
    )
    return [serialize_acknowledgement(ack) for ack in acknowledgements]
