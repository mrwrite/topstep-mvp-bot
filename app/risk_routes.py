from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.risk_service import risk_service, serialize_kill_switch, serialize_risk_decision, serialize_risk_settings
from app.trading_safety import PAPER_MODE, normalize_mode
from app.authorization import TenantContext
from app.durable_simulation import submit_command
from app.tenant_repository import TenantRepository


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


def _repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session"))


def _assert_integration_owned(repository: TenantRepository, *, integration_id: int | None) -> None:
    if integration_id is None:
        return
    integration = repository.get(models.PlatformIntegration, integration_id)
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
    _assert_integration_owned(_repository(db, current_user), integration_id=integration_id)
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
    _assert_integration_owned(_repository(db, current_user), integration_id=request.integration_id)
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
    criteria = (models.KillSwitch.active == 1,) if active_only else ()
    switches = _repository(db, current_user).list(
        models.KillSwitch, *criteria, order_by=(models.KillSwitch.activated_at.desc(),), limit=100
    )
    return [serialize_kill_switch(kill_switch) for kill_switch in switches]


@router.post("/kill-switches")
def activate_kill_switch(
    request: KillSwitchActivateRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    repository = _repository(db, current_user)
    _assert_integration_owned(repository, integration_id=request.integration_id)
    kill_switch = risk_service.activate_kill_switch(
        db,
        user_id=current_user.id,
        actor_user_id=current_user.id,
        integration_id=request.integration_id,
        account_id=request.account_id,
        bot_session_id=request.bot_session_id,
        reason=request.reason,
    )
    tenant = TenantContext(current_user.id, current_user.username)
    active_runs = repository.list(models.SimulationRun,
        models.SimulationRun.state.notin_(("stopped", "failed", "killed")),
        lock=True,
    )
    for run in active_runs:
        config = run.configuration or {}
        if request.bot_session_id and run.id != request.bot_session_id:
            continue
        if request.integration_id is not None and config.get("integration_id") != request.integration_id:
            continue
        if request.account_id is not None and config.get("account_id") != request.account_id:
            continue
        submit_command(
            db, tenant, run.id,
            idempotency_key=f"kill-switch:{kill_switch.id}:{run.id}",
            name="kill",
        )
    db.commit()
    db.refresh(kill_switch)
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
    decisions = _repository(db, current_user).list(
        models.RiskDecision, order_by=(models.RiskDecision.created_at.desc(),), limit=100
    )
    return [serialize_risk_decision(decision) for decision in decisions]
