from datetime import datetime, timedelta
from uuid import uuid4
import asyncio
import json
import os

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.indicators import compute_indicators
from app.integrations_service import resolve_integration
from app.providers.factory import get_adapter
from app.providers.topstepx import TopStepXAdapter
from app.providers.types import IntegrationCapability
from app.paper_execution import execute_paper_order, get_paper_order, list_open_paper_orders, list_paper_positions
from app.strategy_engine import (
    create_strategy_config,
    mark_signal_executed,
    paper_performance_metrics,
    record_strategy_signal,
    serialize_strategy_config,
    serialize_strategy_signal,
)
from app.trading_safety import build_order_intent
from logger import log_trade


DEBUG = os.getenv("DEBUG", "0") == "1"
router = APIRouter()

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
    state_for_user = get_bot_state(current_user.id)
    apply_bot_config(state_for_user, config, current_user.id)
    return {"status": "updated", **state_for_user}


@router.post("/stop-bot")
def stop_bot(current_user: models.User = Depends(get_current_user_model)):
    state_for_user = get_bot_state(current_user.id)
    state_for_user["stop"] = True
    return {"status": "stopping"}


@router.post("/bot-sessions")
def create_bot_session(
    config: BotSessionCreate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    state_for_user = get_bot_state(current_user.id)
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

    integration = resolve_integration(
        db,
        current_user.id,
        integration_id=config.integration_id,
        required_capabilities={IntegrationCapability.BROKER_TRADING},
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found for current user.",
        )

    state_for_user["stop"] = False
    session_id = uuid4().hex
    strategy_config = create_strategy_config(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=config.account_id,
        symbol=config.symbol,
        trading_mode=state_for_user["trading_mode"],
        parameters={
            "buy_threshold": state_for_user["buy_threshold"],
            "sell_threshold": state_for_user["sell_threshold"],
        },
        bot_session_id=session_id,
    )
    BOT_SESSIONS[session_id] = {
        "user_id": current_user.id,
        "symbol": config.symbol,
        "integration_id": integration.id,
        "account_id": config.account_id,
        "strategy_config_id": strategy_config.id,
    }
    return {
        "session_id": session_id,
        "trading_mode": state_for_user["trading_mode"],
        "strategy_config": serialize_strategy_config(strategy_config),
    }


@router.post("/strategy-configs")
def create_strategy_config_endpoint(
    request: StrategyConfigRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    integration = resolve_integration(
        db,
        current_user.id,
        integration_id=request.integration_id,
        required_capabilities={IntegrationCapability.BROKER_TRADING},
    )
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found for current user.")
    config = create_strategy_config(
        db,
        user_id=current_user.id,
        integration_id=integration.id,
        account_id=request.account_id,
        symbol=request.symbol,
        trading_mode=request.trading_mode,
        parameters=request.parameters,
    )
    return serialize_strategy_config(config)


@router.get("/strategy-configs")
def list_strategy_configs(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    configs = (
        db.query(models.StrategyConfig)
        .filter(models.StrategyConfig.user_id == current_user.id)
        .order_by(models.StrategyConfig.created_at.desc())
        .all()
    )
    return [serialize_strategy_config(config) for config in configs]


@router.get("/strategy-signals")
def list_strategy_signals(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    signals = (
        db.query(models.StrategySignal)
        .filter(models.StrategySignal.user_id == current_user.id)
        .order_by(models.StrategySignal.created_at.desc())
        .limit(100)
        .all()
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
    integration = None
    if order.integration_id is not None:
        integration = resolve_integration(
            db,
            current_user.id,
            integration_id=order.integration_id,
            required_capabilities={IntegrationCapability.BROKER_TRADING},
        )
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Integration not found for current user.",
            )

    intent = build_order_intent(
        user_id=current_user.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        trading_mode=order.trading_mode,
        order_type=order.order_type,
        integration_id=integration.id if integration else None,
        account_id=order.account_id,
        idempotency_key=order.idempotency_key,
        source="manual",
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


def fetch_price_data(adapter: TopStepXAdapter, symbol: str, interval_minutes=1, lookback_minutes=100):
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=30)

    token = adapter._get_session_token()
    contract_id = adapter.get_contract_id(symbol)
    if not contract_id:
        raise Exception("Could not get contract ID.")

    bars = adapter.get_bars(
        token=token,
        contract_id=contract_id,
        interval_minutes=interval_minutes,
        start_time=start_time.isoformat() + "Z",
        end_time=end_time.isoformat() + "Z",
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
):
    session = BOT_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot session not found.")

    def log(message: str):
        print(message)
        return f"data: {message}\n\n"

    async def wait_interval():
        nonlocal interval_seconds
        for remaining in range(interval_seconds, 0, -1):
            if DEBUG:
                yield log(f"Next fetch in {remaining} seconds")
            await asyncio.sleep(1)
            session_state = get_bot_state(session["user_id"])
            interval_seconds = session_state.get("interval_seconds", interval_seconds)
            if session_state.get("stop"):
                yield log("Bot stop requested. Exiting loop.")
                return

    async def event_stream():
        nonlocal buy_threshold, sell_threshold, auto_trade, quantity, interval_seconds, bar_interval_minutes
        session_state = get_bot_state(session["user_id"])
        session_state.update(
            {
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "auto_trade": auto_trade,
                "quantity": quantity,
                "interval_seconds": interval_seconds,
                "bar_interval_minutes": bar_interval_minutes,
                "stop": False,
                "trading_mode": session_state.get("trading_mode", "paper"),
            }
        )

        yield log(f"Starting paper bot loop at {datetime.now()}")

        db = database.SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.id == session["user_id"]).first()
            if not user:
                yield log("User not found for bot session.")
                return

            integration = resolve_integration(
                db,
                user.id,
                integration_id=integration_id or session.get("integration_id"),
                required_capabilities={
                    IntegrationCapability.BROKER_TRADING,
                    IntegrationCapability.MARKET_DATA,
                },
            )

            adapter = get_adapter(integration) if integration else None

            if not adapter:
                yield log("No active market data integration configured.")
                return

            if not isinstance(adapter, TopStepXAdapter):
                yield log("Market data is not implemented for the selected provider.")
                return

            strategy_config = (
                db.query(models.StrategyConfig)
                .filter(
                    models.StrategyConfig.user_id == user.id,
                    models.StrategyConfig.id == session.get("strategy_config_id"),
                )
                .first()
            )
            if not strategy_config:
                yield log("Strategy config not found for bot session.")
                return
        finally:
            db.close()

        yield log(
            f"Rules: BUY below {session_state['buy_threshold']} | "
            f"SELL above {session_state['sell_threshold']}"
        )

        while True:
            session_state = get_bot_state(session["user_id"])
            if session_state.get("stop"):
                yield log("Bot stop requested. Exiting loop.")
                break

            buy_threshold = session_state.get("buy_threshold", buy_threshold)
            sell_threshold = session_state.get("sell_threshold", sell_threshold)
            auto_trade = session_state.get("auto_trade", auto_trade)
            quantity = session_state.get("quantity", quantity)
            interval_seconds = session_state.get("interval_seconds", interval_seconds)
            bar_interval_minutes = session_state.get("bar_interval_minutes", bar_interval_minutes)
            try:
                yield log(f"Fetching data at {datetime.now()}")
                bar_interval = bar_interval_minutes if bar_interval_minutes in (1, 3) else 1
                df = fetch_price_data(adapter=adapter, symbol=symbol, interval_minutes=bar_interval)

                if df is None or df.empty:
                    yield log("No data returned.")
                    async for msg in wait_interval():
                        yield msg
                    continue

                indicators = compute_indicators(df)
                required_cols = ["rsi", "ma_fast", "ma_slow"]
                if not all(col in indicators.columns for col in required_cols):
                    missing = set(required_cols) - set(indicators.columns)
                    raise Exception(f"Missing indicator columns in DataFrame: {missing}")

                signal_db = database.SessionLocal()
                try:
                    strategy_config = (
                        signal_db.query(models.StrategyConfig)
                        .filter(
                            models.StrategyConfig.user_id == session["user_id"],
                            models.StrategyConfig.id == session.get("strategy_config_id"),
                        )
                        .first()
                    )
                    if not strategy_config:
                        yield log("Strategy config not found for bot session.")
                        break
                    signal_record = record_strategy_signal(signal_db, config=strategy_config, indicators=indicators)
                    signal = signal_record.signal
                finally:
                    signal_db.close()
                yield log(f"Latest Close: {df['close'].iloc[-1]:.2f} | Signal: {signal}")

                if signal in {"BUY", "SELL"} and signal_record.status == "emitted":
                    yield log(f"{signal} signal detected.")
                    signal_time = indicators.index[-1].isoformat()
                    idempotency_key = f"bot:{session_id}:{symbol}:{signal}:{signal_time}"
                    if auto_trade:
                        intent = build_order_intent(
                            user_id=session["user_id"],
                            symbol=symbol,
                            side=signal,
                            quantity=quantity,
                            trading_mode=session_state.get("trading_mode", "paper"),
                            integration_id=integration.id if integration else None,
                            account_id=session.get("account_id"),
                            idempotency_key=idempotency_key,
                            source="bot",
                            reference_price=float(df["close"].iloc[-1]),
                        )
                        order_db = database.SessionLocal()
                        try:
                            response = execute_paper_order(order_db, intent)
                            mark_signal_executed(
                                order_db,
                                signal_id=signal_record.id,
                                paper_order_id=response["order"]["id"],
                            )
                        finally:
                            order_db.close()
                        yield log(f"Paper trade response: {response}")
                        log_trade(
                            symbol,
                            signal,
                            quantity,
                            df["close"].iloc[-1],
                            "PAPER",
                            str(response),
                        )
                    else:
                        prompt = {
                            "type": "prompt",
                            "side": signal,
                            "price": df["close"].iloc[-1],
                            "symbol": symbol,
                            "quantity": quantity,
                            "idempotency_key": idempotency_key,
                        }
                        yield log(json.dumps(prompt))
                else:
                    if signal_record.status == "suppressed":
                        yield log(f"Strategy signal suppressed: {signal_record.reason}")
                    else:
                        yield log("No trade signal at this time.")

            except Exception as exc:
                yield log(f"Error during bot loop: {exc}")

            async for msg in wait_interval():
                yield msg

    return StreamingResponse(event_stream(), media_type="text/event-stream")
