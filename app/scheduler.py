from datetime import timedelta
from uuid import uuid4
import asyncio
import json
import os

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import analytics_service, database, models
from app.auth_routes import get_current_user_model
from app.indicators import compute_indicators
from app.providers.factory import get_adapter
from app.providers.topstepx import TopStepXAdapter
from app.providers.types import IntegrationCapability
from app.paper_execution import (
    execute_paper_order,
    get_paper_order,
    list_open_paper_orders,
    list_paper_account_snapshots,
    list_paper_ledger_entries,
    list_paper_positions,
)
from app.observability import log_event
from app.risk_service import risk_service
from app.strategy_engine import (
    create_strategy_config,
    mark_signal_executed,
    paper_performance_metrics,
    record_strategy_signal,
    serialize_strategy_config,
    serialize_strategy_signal,
)
from app.trading_context import trading_context_service
from app.trading_safety import build_order_intent
from app.authorization import TenantContext
from app.tenant_repository import TenantRepository
from app.time_utils import as_utc, utc_now
from app.durable_simulation import (
    DurableRunError,
    submit_command,
    submit_start,
)
from logger import log_trade


DEBUG = os.getenv("DEBUG", "0") == "1"
router = APIRouter()


def _tenant_repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(
        db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session")
    )

DEFAULT_BOT_STATE = {
    "buy_threshold": 30,
    "sell_threshold": 70,
    "auto_trade": False,
    "quantity": 1,
    "interval_seconds": 60,
    "bar_interval_minutes": 1,
    "stop": False,
    "trading_mode": "paper",
}

BOT_STATES: dict[int, dict] = {}
BOT_SESSIONS: dict[str, dict] = {}


def get_bot_state(user_id: int) -> dict:
    """Deprecated test compatibility only; never authorizes or owns execution."""
    if user_id not in BOT_STATES:
        BOT_STATES[user_id] = dict(DEFAULT_BOT_STATE)
    return BOT_STATES[user_id]


class BotConfig(BaseModel):
    buy_threshold: int | None = None
    sell_threshold: int | None = None
    auto_trade: bool | None = None
    quantity: int | None = Field(default=None, ge=1)
    interval_seconds: int | None = Field(default=None, ge=1)
    bar_interval_minutes: int | None = Field(default=None, ge=1)
    trading_mode: str | None = None


class BotSessionCreate(BotConfig):
    symbol: str = "RTYZ4"
    integration_id: int | None = None
    account_id: str | None = None


class TradeRequest(BaseModel):
    symbol: str
    side: str
    quantity: int = Field(..., ge=1)
    integration_id: int | None = None
    trading_mode: str = "paper"
    order_type: str = "market"
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    reference_price: float | None = Field(default=None, gt=0)
    account_id: str | None = None
    idempotency_key: str | None = None


class StrategyConfigRequest(BaseModel):
    symbol: str
    integration_id: int
    account_id: str
    trading_mode: str = "paper"
    parameters: dict | None = None


def apply_bot_config(state: dict, config: BotConfig, user_id: int) -> None:
    if config.buy_threshold is not None:
        state["buy_threshold"] = config.buy_threshold
    if config.sell_threshold is not None:
        state["sell_threshold"] = config.sell_threshold
    if config.auto_trade is not None:
        state["auto_trade"] = config.auto_trade
    if config.quantity is not None:
        state["quantity"] = config.quantity
    if config.interval_seconds is not None:
        state["interval_seconds"] = config.interval_seconds
    if config.bar_interval_minutes is not None:
        state["bar_interval_minutes"] = config.bar_interval_minutes
    if config.trading_mode is not None:
        intent = build_order_intent(
            user_id=user_id,
            symbol="VALIDATION",
            side="BUY",
            quantity=1,
            trading_mode=config.trading_mode,
            source="config-validation",
        )
        state["trading_mode"] = intent.trading_mode


@router.post("/update-config")
def update_config(
    config: BotConfig,
    current_user: models.User = Depends(get_current_user_model),
):
    validated = dict(DEFAULT_BOT_STATE)
    apply_bot_config(validated, config, current_user.id)
    validated.pop("stop", None)
    return {"status": "validated_not_persisted", **validated}


@router.post("/stop-bot")
def stop_bot(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    runs = _tenant_repository(db, current_user).list(
        models.SimulationRun,
        models.SimulationRun.state.notin_(("stopped", "failed", "killed")),
        order_by=(models.SimulationRun.created_at.desc(),), limit=1,
    )
    run = runs[0] if runs else None
    if not run:
        return {"status": "stopped", "duplicate": True}
    tenant = TenantContext(current_user.id, current_user.username)
    run, command_row, duplicate = submit_command(
        db, tenant, run.id, idempotency_key=idempotency_key or f"legacy-stop:{uuid4().hex}", name="stop"
    )
    db.commit()
    return {
        "status": run.state,
        "run_id": run.id,
        "command_id": command_row.id,
        "command_status": command_row.status,
        "duplicate": duplicate,
    }


@router.post("/bot-sessions")
def create_bot_session(
    config: BotSessionCreate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    state_for_user = dict(DEFAULT_BOT_STATE)
    apply_bot_config(state_for_user, config, current_user.id)

    if config.integration_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="integration_id is required for paper strategy sessions.",
        )
    if not config.account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="account_id is required for paper strategy sessions.",
        )

    context = trading_context_service.resolve(
        db,
        user_id=current_user.id,
        trading_mode=state_for_user["trading_mode"],
        integration_id=config.integration_id,
        account_id=config.account_id,
        symbol=config.symbol,
        required_capabilities={IntegrationCapability.PAPER_TRADING},
        require_integration=True,
        require_account=True,
        require_contract=True,
    )
    integration = context.integration
    risk_service.assert_no_active_kill_switch(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=context.account_id,
    )

    session_id = uuid4().hex
    strategy_config = create_strategy_config(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=context.account_id,
        symbol=context.symbol,
        trading_mode=state_for_user["trading_mode"],
        parameters={
            "buy_threshold": state_for_user["buy_threshold"],
            "sell_threshold": state_for_user["sell_threshold"],
        },
        bot_session_id=session_id,
    )
    tenant = TenantContext(current_user.id, current_user.username)
    try:
        run, command_row, duplicate = submit_start(
            db,
            tenant,
            symbol=context.symbol,
            configuration={
                "environment": "simulation",
                "trading_mode": "paper",
                "integration_id": integration.id,
                "account_id": context.account_id,
                "strategy_config_id": strategy_config.id,
                "buy_threshold": state_for_user["buy_threshold"],
                "sell_threshold": state_for_user["sell_threshold"],
                "auto_trade": state_for_user["auto_trade"],
                "quantity": state_for_user["quantity"],
                "interval_seconds": state_for_user["interval_seconds"],
                "bar_interval_minutes": state_for_user["bar_interval_minutes"],
            },
            strategy_config_id=strategy_config.id,
            idempotency_key=idempotency_key or f"start:{session_id}",
        )
    except DurableRunError as exc:
        raise HTTPException(status_code=409, detail="Simulation run could not be started.", headers={"X-Run-Failure": exc.code}) from exc
    session_id = run.id
    BOT_SESSIONS[session_id] = {"durable_compatibility_marker": True}
    log_event(
        "bot",
        "bot_session_created",
        user_id=current_user.id,
        session_id=session_id,
        integration_id=integration.id,
        account_id=context.account_id,
        symbol=context.symbol,
        trading_mode=state_for_user["trading_mode"],
        auto_trade=state_for_user["auto_trade"],
    )
    analytics_service.capture_event(
        db,
        event_name="paper_session_started",
        user_id=current_user.id,
        metadata={"symbol": context.symbol, "auto_trade": state_for_user["auto_trade"]},
        source="scheduler",
    )
    db.commit()
    return {
        "session_id": session_id,
        "run_id": session_id,
        "command_id": command_row.id,
        "command_status": command_row.status,
        "run_state": run.state,
        "duplicate": duplicate,
        "trading_mode": state_for_user["trading_mode"],
        "strategy_config": serialize_strategy_config(strategy_config),
    }


@router.post("/strategy-configs")
def create_strategy_config_endpoint(
    request: StrategyConfigRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    context = trading_context_service.resolve(
        db,
        user_id=current_user.id,
        trading_mode=request.trading_mode,
        integration_id=request.integration_id,
        account_id=request.account_id,
        symbol=request.symbol,
        required_capabilities={IntegrationCapability.PAPER_TRADING},
        require_integration=True,
        require_account=True,
        require_contract=True,
    )
    integration = context.integration
    config = create_strategy_config(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=context.account_id,
        symbol=context.symbol,
        trading_mode=context.trading_mode,
        parameters=request.parameters,
    )
    return serialize_strategy_config(config)


@router.get("/strategy-configs")
def list_strategy_configs(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    configs = _tenant_repository(db, current_user).list(
        models.StrategyConfig, order_by=(models.StrategyConfig.created_at.desc(),)
    )
    return [serialize_strategy_config(config) for config in configs]


@router.get("/strategy-signals")
def list_strategy_signals(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    signals = _tenant_repository(db, current_user).list(
        models.StrategySignal, order_by=(models.StrategySignal.created_at.desc(),), limit=100
    )
    return [serialize_strategy_signal(signal) for signal in signals]


@router.get("/strategy-metrics")
def get_strategy_metrics(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return paper_performance_metrics(db, user_id=current_user.id)


@router.post("/execute-trade")
async def execute_trade_endpoint(
    order: TradeRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    context = trading_context_service.resolve(
        db,
        user_id=current_user.id,
        trading_mode=order.trading_mode,
        integration_id=order.integration_id,
        account_id=order.account_id,
        symbol=order.symbol,
        required_capabilities={IntegrationCapability.PAPER_TRADING},
        require_integration=False,
        require_account=False,
        require_contract=True,
        allow_paper_fallback=True,
    )
    integration = context.integration

    intent = build_order_intent(
        user_id=current_user.id,
        symbol=context.symbol,
        side=order.side,
        quantity=order.quantity,
        trading_mode=context.trading_mode,
        order_type=order.order_type,
        integration_id=integration.id if integration else None,
        account_id=context.account_id,
        idempotency_key=order.idempotency_key,
        source="manual",
        reference_price=order.reference_price,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
    )
    response = execute_paper_order(db, intent)
    log_trade(intent.symbol, intent.side, intent.quantity, 0, "PAPER", str(response))
    return response


@router.get("/orders/{order_id}")
def get_order_status(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    return get_paper_order(db, user_id=current_user.id, order_id=order_id)


@router.get("/open-orders")
def get_open_orders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    return list_open_paper_orders(db, user_id=current_user.id)


@router.get("/positions")
def get_positions(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    return list_paper_positions(db, user_id=current_user.id)


@router.get("/paper-accounts")
def get_paper_accounts(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    return list_paper_account_snapshots(db, user_id=current_user.id)


@router.get("/paper-ledger")
def get_paper_ledger(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    return list_paper_ledger_entries(db, user_id=current_user.id)


def fetch_price_data(adapter: TopStepXAdapter, symbol: str, interval_minutes=1, lookback_minutes=100):
    end_time = utc_now()
    start_time = end_time - timedelta(days=30)

    token = adapter._get_session_token()
    contract_id = adapter.get_contract_id(symbol)
    if not contract_id:
        raise Exception("Could not get contract ID.")

    bars = adapter.get_bars(
        token=token,
        contract_id=contract_id,
        interval_minutes=interval_minutes,
        start_time=start_time.isoformat().replace("+00:00", "Z"),
        end_time=end_time.isoformat().replace("+00:00", "Z"),
        limit=lookback_minutes,
    )
    if not bars:
        return None
    df = pd.DataFrame(bars)
    df.rename(
        columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        },
        inplace=True,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)
    return df


@router.get("/run-bot")
def run_bot(
    session_id: str,
    symbol: str = "RTYZ4",
    quantity: int = 1,
    interval_seconds: int = 60,
    buy_threshold: int = 30,
    sell_threshold: int = 70,
    auto_trade: bool = True,
    bar_interval_minutes: int = 1,
    integration_id: int | None = None,
    current_user: models.User = Depends(get_current_user_model),
):
    # Compatibility SSE is status-only. It cannot evaluate strategy or place orders.
    db = database.SessionLocal()
    try:
        run = _tenant_repository(db, current_user).get(models.SimulationRun, session_id)
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot session not found.")
    finally:
        db.close()

    def event(message: str):
        return f"data: {message}\n\n"

    async def event_stream():
        status_db = database.SessionLocal()
        try:
            current = _tenant_repository(status_db, current_user).get(models.SimulationRun, session_id)
            if not current:
                yield event(json.dumps({"type": "run_status", "state": "unavailable"}))
                return
            yield event(json.dumps({
                "type": "run_status", "run_id": current.id, "state": current.state,
                "state_version": current.state_version,
                "last_heartbeat_at": current.last_heartbeat_at.isoformat() + "Z" if current.last_heartbeat_at else None,
                "updated_at": current.updated_at.isoformat() + "Z",
                "fresh": bool(
                    current.last_heartbeat_at
                    and utc_now() - as_utc(current.last_heartbeat_at) < timedelta(seconds=60)
                ),
                "failure_code": current.failure_code,
                "simulation": True, "live": False,
            }))
        finally:
            status_db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
