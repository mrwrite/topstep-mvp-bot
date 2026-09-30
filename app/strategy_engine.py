from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import analytics_service, models
from app.observability import log_event
from app.strategy import STRATEGY_DESCRIPTION, STRATEGY_NAME, STRATEGY_VERSION, check_trade_signal
from app.trading_safety import PAPER_MODE


DEFAULT_PARAMETERS = {
    "buy_threshold": 30,
    "sell_threshold": 70,
    "min_bars": 30,
    "max_staleness_seconds": 300,
    "cooldown_seconds": 0,
    "max_signals_per_hour": 12,
    "use_moving_average_confirmation": False,
    "use_momentum_confirmation": False,
}


def normalized_strategy_parameters(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {**DEFAULT_PARAMETERS, **(parameters or {})}
    buy = int(merged["buy_threshold"])
    sell = int(merged["sell_threshold"])
    if buy < 0 or buy > 100 or sell < 0 or sell > 100 or buy >= sell:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RSI thresholds must be 0-100 and buy_threshold must be below sell_threshold.",
        )
    if merged.get("use_moving_average_confirmation") or merged.get("use_momentum_confirmation"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "rsi-threshold-v1 does not support moving-average or momentum confirmation. "
                "Those indicators are informational only in this phase."
            ),
        )
    merged["buy_threshold"] = buy
    merged["sell_threshold"] = sell
    merged["min_bars"] = max(1, int(merged["min_bars"]))
    merged["max_staleness_seconds"] = max(1, int(merged["max_staleness_seconds"]))
    merged["cooldown_seconds"] = max(0, int(merged["cooldown_seconds"]))
    merged["max_signals_per_hour"] = max(1, int(merged["max_signals_per_hour"]))
    return merged


def create_strategy_config(
    db: Session,
    *,
    user_id: int,
    integration_id: int,
    account_id: str,
    symbol: str,
    trading_mode: str,
    parameters: dict[str, Any] | None = None,
    bot_session_id: str | None = None,
) -> models.StrategyConfig:
    if trading_mode != PAPER_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Strategy automation is paper-only. Live trading remains disabled.",
        )
    if not integration_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="integration_id is required.")
    if not account_id or not account_id.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account_id is required.")
    if not symbol or not symbol.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="symbol is required.")

    config = models.StrategyConfig(
        user_id=user_id,
        integration_id=integration_id,
        account_id=account_id.strip(),
        symbol=symbol.strip().upper(),
        trading_mode=trading_mode,
        strategy_name=STRATEGY_NAME,
        strategy_version=STRATEGY_VERSION,
        parameters=normalized_strategy_parameters(parameters),
        bot_session_id=bot_session_id,
    )
    db.add(config)
    analytics_service.capture_event(
        db,
        event_name="strategy_config_created",
        user_id=user_id,
        metadata={"symbol": config.symbol, "trading_mode": trading_mode},
        source="strategy",
    )
    db.commit()
    db.refresh(config)
    return config


def serialize_strategy_config(config: models.StrategyConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "user_id": config.user_id,
        "integration_id": config.integration_id,
        "account_id": config.account_id,
        "symbol": config.symbol,
        "trading_mode": config.trading_mode,
        "strategy_name": config.strategy_name,
        "strategy_version": config.strategy_version,
        "description": STRATEGY_DESCRIPTION,
        "parameters": config.parameters,
        "bot_session_id": config.bot_session_id,
        "enabled": bool(config.enabled),
        "created_at": config.created_at.isoformat() + "Z",
        "updated_at": config.updated_at.isoformat() + "Z",
    }


def _latest_timestamp(df: pd.DataFrame) -> datetime | None:
    if df.empty:
        return None
    index_value = df.index[-1]
    if isinstance(index_value, pd.Timestamp):
        return index_value.to_pydatetime().replace(tzinfo=None)
    if isinstance(index_value, datetime):
        return index_value.replace(tzinfo=None)
    return None


def data_quality_warnings(df: pd.DataFrame, parameters: dict[str, Any], now: datetime | None = None) -> list[str]:
    warnings: list[str] = []
    if df is None or df.empty:
        return ["market_data_empty"]
    min_bars = int(parameters["min_bars"])
    if len(df) < min_bars:
        warnings.append("insufficient_bars")
    required = {"close", "rsi"}
    missing = sorted(required - set(df.columns))
    if missing:
        warnings.append(f"missing_columns:{','.join(missing)}")
    if required.issubset(df.columns) and df[list(required)].tail(1).isnull().any().any():
        warnings.append("latest_indicator_nan")
    latest = _latest_timestamp(df)
    if latest:
        current = now or datetime.utcnow()
        if current - latest > timedelta(seconds=int(parameters["max_staleness_seconds"])):
            warnings.append("latest_bar_stale")
    return warnings


def _recent_executable_signals(
    db: Session,
    *,
    config: models.StrategyConfig,
    since: datetime,
) -> int:
    return (
        db.query(models.StrategySignal)
        .filter(
            models.StrategySignal.strategy_config_id == config.id,
            models.StrategySignal.signal.in_(["BUY", "SELL"]),
            models.StrategySignal.status.in_(["emitted", "executed"]),
            models.StrategySignal.created_at >= since,
        )
        .count()
    )


def guardrail_decision(db: Session, config: models.StrategyConfig, signal_value: str, now: datetime) -> dict[str, Any]:
    parameters = config.parameters or DEFAULT_PARAMETERS
    if signal_value not in {"BUY", "SELL"}:
        return {"allowed": True, "reason": "hold"}

    cooldown_seconds = int(parameters.get("cooldown_seconds", 0))
    if cooldown_seconds > 0:
        last_signal = (
            db.query(models.StrategySignal)
            .filter(
                models.StrategySignal.strategy_config_id == config.id,
                models.StrategySignal.signal.in_(["BUY", "SELL"]),
                models.StrategySignal.status.in_(["emitted", "executed"]),
            )
            .order_by(models.StrategySignal.created_at.desc())
            .first()
        )
        if last_signal and now - last_signal.created_at < timedelta(seconds=cooldown_seconds):
            return {"allowed": False, "reason": "cooldown_active"}

    max_signals = int(parameters.get("max_signals_per_hour", 12))
    recent_count = _recent_executable_signals(db, config=config, since=now - timedelta(hours=1))
    if recent_count >= max_signals:
        return {"allowed": False, "reason": "max_signals_per_hour"}

    return {"allowed": True, "reason": "allowed"}


def record_strategy_signal(
    db: Session,
    *,
    config: models.StrategyConfig,
    indicators: pd.DataFrame,
    now: datetime | None = None,
) -> models.StrategySignal:
    current = now or datetime.utcnow()
    parameters = normalized_strategy_parameters(config.parameters)
    warnings = data_quality_warnings(indicators, parameters, current)
    latest = indicators.iloc[-1] if indicators is not None and not indicators.empty else None
    market_snapshot = {}
    if latest is not None:
        for field in ["close", "rsi", "ma_fast", "ma_slow", "macd", "macd_signal"]:
            if field in indicators.columns and pd.notna(latest.get(field)):
                market_snapshot[field] = float(latest[field])

    if warnings:
        signal_value = "HOLD"
        decision = {"allowed": False, "reason": "data_quality", "warnings": warnings}
        status_value = "suppressed"
        reason = ",".join(warnings)
    else:
        signal_value = check_trade_signal(
            indicators,
            buy_threshold=parameters["buy_threshold"],
            sell_threshold=parameters["sell_threshold"],
        )
        decision = guardrail_decision(db, config, signal_value, current)
        status_value = "emitted" if decision["allowed"] and signal_value in {"BUY", "SELL"} else "suppressed"
        if signal_value == "HOLD":
            status_value = "observed"
        reason = decision["reason"]

    signal_record = models.StrategySignal(
        user_id=config.user_id,
        strategy_config_id=config.id,
        integration_id=config.integration_id,
        account_id=config.account_id,
        symbol=config.symbol,
        signal=signal_value,
        status=status_value,
        reason=reason,
        guardrail_decision=decision,
        market_snapshot=market_snapshot,
        created_at=current,
    )
    db.add(signal_record)
    analytics_service.capture_event(
        db,
        event_name="strategy_signal_created",
        user_id=config.user_id,
        metadata={"symbol": config.symbol, "signal": signal_value, "status": status_value},
        source="strategy",
    )
    db.commit()
    db.refresh(signal_record)
    log_event(
        "strategy",
        "strategy_signal_recorded",
        user_id=config.user_id,
        strategy_config_id=config.id,
        signal_id=signal_record.id,
        symbol=config.symbol,
        signal=signal_record.signal,
        status=signal_record.status,
        reason=signal_record.reason,
        integration_id=config.integration_id,
        account_id=config.account_id,
    )
    return signal_record


def mark_signal_executed(db: Session, *, signal_id: int, paper_order_id: int) -> None:
    signal_record = db.query(models.StrategySignal).filter(models.StrategySignal.id == signal_id).first()
    if not signal_record:
        return
    signal_record.paper_order_id = paper_order_id
    signal_record.status = "executed"
    db.commit()


def serialize_strategy_signal(signal_record: models.StrategySignal) -> dict[str, Any]:
    return {
        "id": signal_record.id,
        "strategy_config_id": signal_record.strategy_config_id,
        "paper_order_id": signal_record.paper_order_id,
        "integration_id": signal_record.integration_id,
        "account_id": signal_record.account_id,
        "symbol": signal_record.symbol,
        "signal": signal_record.signal,
        "status": signal_record.status,
        "reason": signal_record.reason,
        "guardrail_decision": signal_record.guardrail_decision or {},
        "market_snapshot": signal_record.market_snapshot or {},
        "created_at": signal_record.created_at.isoformat() + "Z",
    }


def paper_performance_metrics(db: Session, *, user_id: int) -> dict[str, Any]:
    orders = db.query(models.PaperOrder).filter(models.PaperOrder.user_id == user_id).count()
    signals = db.query(models.StrategySignal).filter(models.StrategySignal.user_id == user_id).count()
    executed_signals = (
        db.query(models.StrategySignal)
        .filter(models.StrategySignal.user_id == user_id, models.StrategySignal.status == "executed")
        .count()
    )
    suppressed_signals = (
        db.query(models.StrategySignal)
        .filter(models.StrategySignal.user_id == user_id, models.StrategySignal.status == "suppressed")
        .count()
    )

    fills = (
        db.query(models.PaperFill)
        .filter(models.PaperFill.user_id == user_id, models.PaperFill.price.isnot(None))
        .order_by(models.PaperFill.created_at.asc(), models.PaperFill.id.asc())
        .all()
    )
    position_qty: dict[str, int] = {}
    average_cost: dict[str, float] = {}
    realized: list[float] = []
    for fill in fills:
        symbol = fill.symbol
        qty = fill.quantity if fill.side == "BUY" else -fill.quantity
        price = float(fill.price)
        current_qty = position_qty.get(symbol, 0)
        current_cost = average_cost.get(symbol, price)
        if current_qty == 0 or (current_qty > 0 and qty > 0) or (current_qty < 0 and qty < 0):
            new_qty = current_qty + qty
            average_cost[symbol] = ((abs(current_qty) * current_cost) + (abs(qty) * price)) / abs(new_qty)
            position_qty[symbol] = new_qty
            continue
        closed = min(abs(current_qty), abs(qty))
        pnl = (price - current_cost) * closed if current_qty > 0 else (current_cost - price) * closed
        realized.append(pnl)
        position_qty[symbol] = current_qty + qty
        if position_qty[symbol] == 0:
            average_cost.pop(symbol, None)

    return {
        "paper_only": True,
        "orders": orders,
        "signals": signals,
        "executed_signals": executed_signals,
        "suppressed_signals": suppressed_signals,
        "wins": sum(1 for value in realized if value > 0),
        "losses": sum(1 for value in realized if value <= 0),
        "realized_pnl": sum(realized),
        "assumptions": [
            "Paper fills use the latest strategy close price when available.",
            "No commissions, slippage, margin, liquidity, or exchange fees are modeled.",
            "Paper results do not predict or guarantee live trading performance.",
        ],
    }
