from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.risk_service import risk_service, serialize_kill_switch, serialize_risk_decision, serialize_risk_settings
from app.trading_safety import PAPER_MODE, normalize_mode


router = APIRouter()


class RiskSettingsUpdate(BaseModel):
    integration_id: int | None = None
    account_id: str | None = None
    trading_mode: str = PAPER_MODE
    max_quantity: int = Field(..., ge=1)
    max_contracts: int = Field(..., ge=1)
    max_daily_loss: float = Field(..., ge=0)
    max_open_positions: int = Field(..., ge=0)
    live_trading_enabled: bool = False


class KillSwitchActivateRequest(BaseModel):
    integration_id: int | None = None
    account_id: str | None = None
    bot_session_id: str | None = None
    reason: str | None = None


def _assert_integration_owned(
    db: Session,
    *,
    user_id: int,
    integration_id: int | None,
) -> None:
    if integration_id is None:
        return
    integration = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.id == integration_id, models.PlatformIntegration.user_id == user_id)
        .first()
    )
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")


@router.get("/settings")
def get_risk_settings(
    integration_id: int | None = Query(default=None),
    account_id: str | None = Query(default=None),
    trading_mode: str = Query(default=PAPER_MODE),
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    mode = normalize_mode(trading_mode)
    _assert_integration_owned(db, user_id=current_user.id, integration_id=integration_id)
    settings = risk_service.get_or_create_settings(
        db,
        user_id=current_user.id,
        integration_id=integration_id,
        account_id=account_id,
        trading_mode=mode,
    )
    db.commit()
    db.refresh(settings)
    return serialize_risk_settings(settings)


@router.put("/settings")
def update_risk_settings(
    request: RiskSettingsUpdate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    mode = normalize_mode(request.trading_mode)
    if request.live_trading_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live trading remains disabled. Risk settings cannot enable live execution.",
            headers={"X-Readiness-Blocker": "live_disabled"},
        )
    _assert_integration_owned(db, user_id=current_user.id, integration_id=request.integration_id)
    settings = risk_service.update_settings(
        db,
        user_id=current_user.id,
        integration_id=request.integration_id,
        account_id=request.account_id,
        trading_mode=mode,
        max_quantity=request.max_quantity,
        max_contracts=request.max_contracts,
        max_daily_loss=request.max_daily_loss,
        max_open_positions=request.max_open_positions,
    )
    return serialize_risk_settings(settings)


@router.get("/kill-switches")
def list_kill_switches(
    active_only: bool = Query(default=False),
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.KillSwitch).filter(models.KillSwitch.user_id == current_user.id)
    if active_only:
        query = query.filter(models.KillSwitch.active == 1)
    switches = query.order_by(models.KillSwitch.activated_at.desc()).limit(100).all()
    return [serialize_kill_switch(kill_switch) for kill_switch in switches]


@router.post("/kill-switches")
def activate_kill_switch(
    request: KillSwitchActivateRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    _assert_integration_owned(db, user_id=current_user.id, integration_id=request.integration_id)
    kill_switch = risk_service.activate_kill_switch(
        db,
        user_id=current_user.id,
        actor_user_id=current_user.id,
        integration_id=request.integration_id,
        account_id=request.account_id,
        bot_session_id=request.bot_session_id,
        reason=request.reason,
    )
    return serialize_kill_switch(kill_switch)


@router.post("/kill-switches/{switch_id}/deactivate")
def deactivate_kill_switch(
    switch_id: int,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    kill_switch = risk_service.deactivate_kill_switch(
        db,
        user_id=current_user.id,
        switch_id=switch_id,
        actor_user_id=current_user.id,
    )
    return serialize_kill_switch(kill_switch)


@router.get("/decisions")
def list_risk_decisions(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    decisions = (
        db.query(models.RiskDecision)
        .filter(models.RiskDecision.user_id == current_user.id)
        .order_by(models.RiskDecision.created_at.desc())
        .limit(100)
        .all()
    )
    return [serialize_risk_decision(decision) for decision in decisions]
