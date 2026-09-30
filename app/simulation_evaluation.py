from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models
from .authorization import TenantContext
from .durable_simulation import (
    DurableRunError,
    _event,
    _hash_configuration,
    assert_fence,
    checkpoint,
    checkpoint_digest,
    fail_owned_run,
    process_run,
)
from .indicators import compute_indicators
from .observability import log_event
from .risk_service import risk_service
from .strategy import STRATEGY_NAME, STRATEGY_VERSION, check_trade_signal
from .strategy_engine import normalized_strategy_parameters
from .tenant_repository import (
    VerifiedTenantJob,
    TenantScopeError,
    bind_tenant_context,
    require_tenant,
    system_maintenance_scope,
)
from .time_utils import as_utc, utc_now
from .trading_safety import build_order_intent


FailureInjector = Callable[[str], None]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def market_source_identity(
    *, source: str, instrument: str, timeframe: str, event_at: datetime,
    provider_sequence: str | None,
) -> str:
    return _digest({
        "source": source.strip().lower(),
        "instrument": instrument.strip().upper(),
        "timeframe": timeframe.strip().lower(),
        "event_at": as_utc(event_at).isoformat(),
        "provider_sequence": provider_sequence,
    })


def market_content_hash(payload: dict[str, Any]) -> str:
    return _digest(payload)


def queue_market_input(
    db: Session,
    tenant: TenantContext,
    run_id: str,
    *,
    source: str,
    timeframe: str,
    event_at: datetime,
    payload: dict[str, Any],
    provider_sequence: str | None = None,
) -> tuple[models.SimulationMarketInput, bool]:
    try:
        tenant = bind_tenant_context(db, tenant)
    except TenantScopeError as exc:
        raise DurableRunError("run_not_found") from exc
    run = (
        db.query(models.SimulationRun)
        .filter(models.SimulationRun.id == run_id, models.SimulationRun.user_id == tenant.user_id)
        .with_for_update()
        .first()
    )
    if not run:
        raise DurableRunError("run_not_found")
    if run.environment != "simulation" or (run.configuration or {}).get("trading_mode", "paper") != "paper":
        raise DurableRunError("live_execution_disabled")
    if run.state in {"stopped", "failed", "killed"} or run.kill_requested_at:
        raise DurableRunError("terminal_state")
    event_at = as_utc(event_at)
    identity = market_source_identity(
        source=source,
        instrument=run.symbol,
        timeframe=timeframe,
        event_at=event_at,
        provider_sequence=provider_sequence,
    )
    content_hash = market_content_hash(payload)
    existing = (
        db.query(models.SimulationMarketInput)
        .filter_by(run_id=run.id, source_identity=identity)
        .first()
    )
    if existing:
        if existing.content_hash != content_hash:
            run.data_freshness = "conflicting"
            run.degraded_reason = "market_data_conflict"
            _event(
                db, run, "simulation.market.conflict",
                {"market_data_id": identity, "classification": "conflicting"},
                causation_id=identity,
            )
            raise DurableRunError("market_data_conflict")
        return existing, True
    row = models.SimulationMarketInput(
        id=str(uuid4()),
        run_id=run.id,
        user_id=run.user_id,
        source=source.strip().lower(),
        instrument=run.symbol,
        timeframe=timeframe.strip().lower(),
        event_at=event_at,
        provider_sequence=provider_sequence,
        source_identity=identity,
        content_hash=content_hash,
        payload=payload,
        status="pending",
        freshness="unknown",
    )
    db.add(row)
    _event(
        db, run, "simulation.market.queued",
        {"market_input_id": row.id, "market_data_id": identity},
        causation_id=identity,
    )
    db.flush()
    return row, False


def _bars_frame(payload: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        raise DurableRunError("market_history_missing")
    normalized: list[dict[str, Any]] = []
    identities: list[str] = []
    for bar in bars:
        if not isinstance(bar, dict) or "timestamp" not in bar or "close" not in bar:
            raise DurableRunError("market_history_invalid")
        timestamp = as_utc(datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00")))
        record = {
            "timestamp": timestamp,
            "open": float(bar.get("open", bar["close"])),
            "high": float(bar.get("high", bar["close"])),
            "low": float(bar.get("low", bar["close"])),
            "close": float(bar["close"]),
            "volume": float(bar.get("volume", 0)),
        }
        normalized.append(record)
        identities.append(_digest({**record, "timestamp": timestamp.isoformat()}))
    normalized.sort(key=lambda item: item["timestamp"])
    if len({item["timestamp"] for item in normalized}) != len(normalized):
        raise DurableRunError("market_history_conflicting")
    frame = pd.DataFrame(normalized).set_index("timestamp")
    return frame, _digest(identities)


def evaluate_rsi_threshold(
    payload: dict[str, Any],
    parameters: dict[str, Any],
) -> tuple[str, str, dict[str, Any], str]:
    """Pure deterministic evaluation for the versioned RSI strategy."""

    frame, lookback_identity = _bars_frame(payload)
    if len(frame) < int(parameters["min_bars"]):
        raise DurableRunError("market_history_missing")
    indicators = compute_indicators(frame.copy())
    latest = indicators.iloc[-1]
    if pd.isna(latest.get("rsi")):
        raise DurableRunError("indicator_state_invalid")
    signal = check_trade_signal(
        indicators,
        buy_threshold=int(parameters["buy_threshold"]),
        sell_threshold=int(parameters["sell_threshold"]),
    )
    rationale = (
        f"RSI {float(latest['rsi']):.6f}; buy below {parameters['buy_threshold']}, "
        f"sell above {parameters['sell_threshold']}."
    )
    snapshot = {
        "close": float(latest["close"]),
        "rsi": float(latest["rsi"]),
        "classification": "new",
    }
    return signal, rationale, snapshot, lookback_identity


def _market_classification(
    db: Session,
    run: models.SimulationRun,
    market: models.SimulationMarketInput,
    *,
    max_staleness_seconds: int,
    now: datetime,
) -> str:
    event_at = as_utc(market.event_at)
    if event_at > now + timedelta(seconds=5):
        return "conflicting"
    if now - event_at > timedelta(seconds=max_staleness_seconds):
        return "too_old"
    previous = (
        db.query(models.SimulationMarketInput)
        .filter(
            models.SimulationMarketInput.run_id == run.id,
            models.SimulationMarketInput.status == "processed",
            models.SimulationMarketInput.id != market.id,
        )
        .order_by(models.SimulationMarketInput.event_at.desc())
        .first()
    )
    if previous and event_at < as_utc(previous.event_at):
        return "out_of_order"
    if previous and event_at == as_utc(previous.event_at):
        return "stale"
    if previous and previous.provider_sequence and market.provider_sequence:
        try:
            if int(market.provider_sequence) != int(previous.provider_sequence) + 1:
                return "missing_predecessor"
        except ValueError:
            pass
    return "new"


def _schedule_allows(configuration: dict[str, Any], event_at: datetime) -> bool:
    schedule = configuration.get("schedule")
    if not schedule:
        return True
    weekdays = schedule.get("weekdays")
    if weekdays is not None and event_at.weekday() not in {int(value) for value in weekdays}:
        return False
    current = event_at.strftime("%H:%M")
    start = str(schedule.get("start_utc", "00:00"))
    end = str(schedule.get("end_utc", "23:59"))
    return start <= current <= end


def _get_position(db: Session, run: models.SimulationRun):
    config = run.configuration or {}
    query = db.query(models.PaperPosition).filter(
        models.PaperPosition.user_id == run.user_id,
        models.PaperPosition.symbol == run.symbol,
    )
    integration_id, account_id = config.get("integration_id"), config.get("account_id")
    query = query.filter(
        models.PaperPosition.integration_id.is_(None)
        if integration_id is None else models.PaperPosition.integration_id == integration_id,
        models.PaperPosition.account_id.is_(None)
        if account_id is None else models.PaperPosition.account_id == account_id,
    )
    return query.with_for_update().first()


def _get_snapshot(db: Session, run: models.SimulationRun):
    config = run.configuration or {}
    query = db.query(models.PaperAccountSnapshot).filter(
        models.PaperAccountSnapshot.user_id == run.user_id
    )
    integration_id, account_id = config.get("integration_id"), config.get("account_id")
    query = query.filter(
        models.PaperAccountSnapshot.integration_id.is_(None)
        if integration_id is None else models.PaperAccountSnapshot.integration_id == integration_id,
        models.PaperAccountSnapshot.account_id.is_(None)
        if account_id is None else models.PaperAccountSnapshot.account_id == account_id,
    )
    return query.order_by(models.PaperAccountSnapshot.id.desc()).with_for_update().first()


def _risk_counter(db: Session, run: models.SimulationRun) -> models.SimulationRiskCounter:
    row = (
        db.query(models.SimulationRiskCounter)
        .filter_by(run_id=run.id, user_id=run.user_id)
        .with_for_update()
        .first()
    )
    if row is None:
        row = models.SimulationRiskCounter(run_id=run.id, user_id=run.user_id)
        db.add(row)
        db.flush()
    return row


def _apply_fill(
    db: Session,
    run: models.SimulationRun,
    order: models.PaperOrder,
    *,
    fence: int,
    execution_identity: str,
    side: str,
    quantity: int,
    price: float,
    fee: float,
) -> tuple[models.PaperFill, models.PaperPosition, models.PaperAccountSnapshot, float]:
    prior = db.query(models.PaperFill).filter_by(execution_identity=execution_identity).first()
    if prior:
        position = _get_position(db, run)
        snapshot = _get_snapshot(db, run)
        return prior, position, snapshot, 0.0
    fill = models.PaperFill(
        order_id=order.id,
        user_id=run.user_id,
        symbol=run.symbol,
        side=side,
        quantity=quantity,
        price=price,
        simulation_run_id=run.id,
        simulation_fencing_token=fence,
        execution_identity=execution_identity,
    )
    db.add(fill)
    config = run.configuration or {}
    position = _get_position(db, run)
    if position is None:
        position = models.PaperPosition(
            user_id=run.user_id,
            integration_id=config.get("integration_id"),
            account_id=config.get("account_id"),
            symbol=run.symbol,
            quantity=0,
            avg_price=0.0,
        )
        db.add(position)
        db.flush()
    snapshot = _get_snapshot(db, run)
    if snapshot is None:
        snapshot = models.PaperAccountSnapshot(
            user_id=run.user_id,
            integration_id=config.get("integration_id"),
            account_id=config.get("account_id"),
            cash_balance=float(config.get("starting_balance", 100000.0)),
            equity=float(config.get("starting_balance", 100000.0)),
            buying_power=float(config.get("starting_balance", 100000.0)),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            margin_used=0.0,
        )
        db.add(snapshot)
        db.flush()

    previous_quantity = int(position.quantity)
    previous_avg = float(position.avg_price or 0)
    signed_quantity = quantity if side == "BUY" else -quantity
    new_quantity = previous_quantity + signed_quantity
    realized_delta = 0.0
    if previous_quantity == 0 or (previous_quantity > 0) == (signed_quantity > 0):
        total = abs(previous_quantity) + quantity
        position.avg_price = (
            (abs(previous_quantity) * previous_avg + quantity * price) / total if total else 0.0
        )
    else:
        closed = min(abs(previous_quantity), quantity)
        realized_delta = (
            (price - previous_avg) * closed
            if previous_quantity > 0 else (previous_avg - price) * closed
        )
        if new_quantity == 0:
            position.avg_price = 0.0
        elif (previous_quantity > 0) != (new_quantity > 0):
            position.avg_price = price
    position.quantity = new_quantity
    position.simulation_run_id = run.id
    position.simulation_fencing_token = fence
    position.state_version = int(position.state_version or 0) + 1
    position.updated_at = utc_now()

    cash_delta = (-price * quantity if side == "BUY" else price * quantity) - fee
    snapshot.cash_balance = float(snapshot.cash_balance) + cash_delta
    snapshot.realized_pnl = float(snapshot.realized_pnl) + realized_delta - fee
    snapshot.unrealized_pnl = (
        (price - float(position.avg_price or 0)) * int(position.quantity)
        if position.quantity else 0.0
    )
    snapshot.equity = float(snapshot.cash_balance) + int(position.quantity) * price
    snapshot.buying_power = snapshot.equity
    snapshot.margin_used = abs(int(position.quantity)) * price
    snapshot.last_mark_price = price
    snapshot.simulation_run_id = run.id
    snapshot.simulation_fencing_token = fence
    snapshot.state_version = int(snapshot.state_version or 0) + 1
    snapshot.updated_at = utc_now()

    db.add(models.PaperLedgerEntry(
        user_id=run.user_id,
        integration_id=config.get("integration_id"),
        account_id=config.get("account_id"),
        paper_order_id=order.id,
        entry_type="simulated_fill",
        amount=cash_delta,
        cash_balance=snapshot.cash_balance,
        equity=snapshot.equity,
        buying_power=snapshot.buying_power,
        realized_pnl=snapshot.realized_pnl,
        unrealized_pnl=snapshot.unrealized_pnl,
        description="Modeled simulation fill and costs; no broker execution occurred.",
        entry_metadata={
            "symbol": run.symbol,
            "side": side,
            "quantity": quantity,
            "fill_price": price,
            "modeled_fee": fee,
            "realized_pnl_delta": realized_delta,
            "simulation": True,
        },
        simulation_run_id=run.id,
        simulation_fencing_token=fence,
        execution_identity=f"ledger:{execution_identity}",
    ))
    return fill, position, snapshot, realized_delta


def _checkpoint_value(
    db: Session,
    run: models.SimulationRun,
    market: models.SimulationMarketInput,
    evaluation: models.SimulationEvaluation,
    counter: models.SimulationRiskCounter,
    *,
    event_id: str | None,
) -> dict[str, Any]:
    position = _get_position(db, run)
    snapshot = _get_snapshot(db, run)
    latest_order = (
        db.query(models.PaperOrder)
        .filter_by(simulation_run_id=run.id, user_id=run.user_id)
        .order_by(models.PaperOrder.id.desc())
        .first()
    )
    latest_fill = (
        db.query(models.PaperFill)
        .filter_by(simulation_run_id=run.id, user_id=run.user_id)
        .order_by(models.PaperFill.id.desc())
        .first()
    )
    ledger_count = db.query(models.PaperLedgerEntry).filter_by(
        simulation_run_id=run.id, user_id=run.user_id
    ).count()
    trading_day = as_utc(market.event_at).date().isoformat()
    daily = db.query(models.DailyRiskState).filter(
        models.DailyRiskState.user_id == run.user_id,
        models.DailyRiskState.trading_mode == "paper",
        models.DailyRiskState.trading_day == trading_day,
    ).order_by(models.DailyRiskState.id.desc()).first()
    return {
        "market_data_id": market.source_identity,
        "last_evaluation_id": evaluation.evaluation_identity,
        "strategy_state": {"last_signal": evaluation.signal},
        "strategy_version": run.strategy_version,
        "configuration_hash": run.configuration_hash,
        "simulation_clock": as_utc(market.event_at).isoformat(),
        "deterministic_seed": _digest({"run_id": run.id, "market": market.source_identity}),
        "risk_counters": {
            "trade_count": counter.trade_count,
            "consecutive_losses": counter.consecutive_losses,
            "realized_pnl": counter.realized_pnl,
            "fees": counter.fees,
            "version": counter.version,
        },
        "daily_risk_state": {
            "trading_day": trading_day,
            "realized_pnl": float(daily.realized_pnl),
            "locked": bool(daily.locked),
        } if daily else None,
        "position_version": int(position.state_version or 0) if position else 0,
        "position": {
            "quantity": int(position.quantity),
            "avg_price": float(position.avg_price),
        } if position else {"quantity": 0, "avg_price": 0.0},
        "ledger_version": ledger_count,
        "account": {
            "cash_balance": float(snapshot.cash_balance),
            "equity": float(snapshot.equity),
            "realized_pnl": float(snapshot.realized_pnl),
            "unrealized_pnl": float(snapshot.unrealized_pnl),
            "state_version": int(snapshot.state_version or 0),
        } if snapshot else None,
        "pending_intent_ids": [],
        "last_order_identity": latest_order.idempotency_key if latest_order else None,
        "last_fill_identity": latest_fill.execution_identity if latest_fill else None,
        "last_event_id": event_id,
        "data_freshness": market.freshness,
        "market_content_hash": market.content_hash,
    }


def reconcile_checkpoint(db: Session, run: models.SimulationRun) -> None:
    if run.last_checkpoint_sequence == 0:
        return
    cp = (
        db.query(models.SimulationCheckpoint)
        .filter_by(run_id=run.id, user_id=run.user_id, sequence=run.last_checkpoint_sequence)
        .first()
    )
    if (
        cp is None
        or cp.checkpoint_hash != run.last_checkpoint_hash
        or cp.checkpoint_hash != checkpoint_digest(cp.checkpoint or {})
    ):
        raise DurableRunError("checkpoint_integrity_failure")
    value = cp.checkpoint or {}
    counter = db.query(models.SimulationRiskCounter).filter_by(run_id=run.id).first()
    expected_risk = value.get("risk_counters") or {}
    actual_risk = {
        "trade_count": int(counter.trade_count if counter else 0),
        "consecutive_losses": int(counter.consecutive_losses if counter else 0),
        "realized_pnl": float(counter.realized_pnl if counter else 0),
        "fees": float(counter.fees if counter else 0),
        "version": int(counter.version if counter else 0),
    }
    if expected_risk != actual_risk:
        raise DurableRunError("risk_state_mismatch")
    expected_daily = value.get("daily_risk_state")
    if expected_daily:
        daily = db.query(models.DailyRiskState).filter(
            models.DailyRiskState.user_id == run.user_id,
            models.DailyRiskState.trading_mode == "paper",
            models.DailyRiskState.trading_day == expected_daily["trading_day"],
        ).order_by(models.DailyRiskState.id.desc()).first()
        actual_daily = {
            "trading_day": daily.trading_day,
            "realized_pnl": float(daily.realized_pnl),
            "locked": bool(daily.locked),
        } if daily else None
        if expected_daily != actual_daily:
            raise DurableRunError("daily_risk_state_mismatch")
    position = _get_position(db, run)
    expected_position = value.get("position") or {"quantity": 0, "avg_price": 0.0}
    actual_position = {
        "quantity": int(position.quantity if position else 0),
        "avg_price": float(position.avg_price if position else 0),
    }
    if expected_position != actual_position:
        raise DurableRunError("position_state_mismatch")
    ledger_count = db.query(models.PaperLedgerEntry).filter_by(
        simulation_run_id=run.id, user_id=run.user_id
    ).count()
    if int(value.get("ledger_version", 0)) != ledger_count:
        raise DurableRunError("ledger_state_mismatch")
    fills = db.query(models.PaperFill).filter_by(simulation_run_id=run.id, user_id=run.user_id).all()
    orders = db.query(models.PaperOrder).filter_by(
        simulation_run_id=run.id, user_id=run.user_id
    ).all()
    order_by_id = {row.id: row for row in orders}
    fill_quantity_by_order: dict[int, int] = {}
    for fill in fills:
        order = order_by_id.get(fill.order_id)
        if order is None:
            raise DurableRunError("orphan_fill")
        if fill.quantity <= 0 or fill.quantity > order.quantity:
            raise DurableRunError("fill_quantity_invalid")
        fill_quantity_by_order[fill.order_id] = (
            fill_quantity_by_order.get(fill.order_id, 0) + fill.quantity
        )
        if fill_quantity_by_order[fill.order_id] > order.quantity:
            raise DurableRunError("order_overfilled")
        ledger = db.query(models.PaperLedgerEntry).filter_by(
            execution_identity=f"ledger:{fill.execution_identity}",
            simulation_run_id=run.id,
            user_id=run.user_id,
        ).first()
        if ledger is None:
            raise DurableRunError("fill_ledger_missing")
    if int(actual_risk["trade_count"]) != len(fills):
        raise DurableRunError("risk_trade_count_mismatch")
    modeled_fees = sum(
        float((entry.entry_metadata or {}).get("modeled_fee", 0))
        for entry in db.query(models.PaperLedgerEntry).filter_by(
            simulation_run_id=run.id, user_id=run.user_id
        ).all()
    )
    if abs(modeled_fees - float(actual_risk["fees"])) > 1e-9:
        raise DurableRunError("fee_state_mismatch")
    reconciled_quantity = sum(
        fill.quantity if fill.side == "BUY" else -fill.quantity for fill in fills
    )
    if fills and reconciled_quantity != actual_position["quantity"]:
        raise DurableRunError("fill_position_mismatch")
    last_evaluation_id = value.get("last_evaluation_id")
    if last_evaluation_id and not db.query(models.SimulationEvaluation).filter_by(
        run_id=run.id,
        user_id=run.user_id,
        evaluation_identity=last_evaluation_id,
    ).first():
        raise DurableRunError("evaluation_state_mismatch")
    market_data_id = value.get("market_data_id")
    if market_data_id:
        market = db.query(models.SimulationMarketInput).filter_by(
            run_id=run.id,
            user_id=run.user_id,
            source_identity=market_data_id,
            status="processed",
        ).first()
        if market is None or market.content_hash != value.get("market_content_hash"):
            raise DurableRunError("market_sequence_mismatch")


def process_market_input(
    db: Session,
    tenant: TenantContext,
    run_id: str,
    market_input_id: str,
    *,
    owner_id: str,
    fence: int,
    now: datetime | None = None,
    inject: FailureInjector | None = None,
) -> models.SimulationEvaluation | None:
    now = as_utc(now or utc_now())
    inject = inject or (lambda _stage: None)
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    inject("after_fence")
    if run.state != "running":
        raise DurableRunError("run_not_running")
    if run.configuration_hash != _hash_configuration(run.configuration or {}):
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code="configuration_version_mismatch",
            summary="The immutable simulation configuration no longer matches.",
        )
        return None
    if run.strategy_version != STRATEGY_VERSION:
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code="strategy_version_mismatch",
            summary="The durable strategy version cannot be replayed safely.",
        )
        return None
    config_row = None
    if run.strategy_config_id:
        config_row = db.query(models.StrategyConfig).filter(
            models.StrategyConfig.id == run.strategy_config_id,
            models.StrategyConfig.user_id == tenant.user_id,
        ).first()
        if (
            config_row is None
            or config_row.strategy_name != STRATEGY_NAME
            or config_row.strategy_version != STRATEGY_VERSION
        ):
            fail_owned_run(
                db, tenant, run.id, owner_id=owner_id, fence=fence,
                code="strategy_version_mismatch",
                summary="The configured strategy cannot be replayed safely.",
            )
            return None
    active_kill = risk_service.find_active_kill_switch(
        db,
        user_id=run.user_id,
        integration_id=(run.configuration or {}).get("integration_id"),
        account_id=(run.configuration or {}).get("account_id"),
        bot_session_id=run.id,
    )
    if active_kill or run.kill_requested_at:
        raise DurableRunError("kill_switch_active")
    reconciliation_lock = db.query(models.AccountReconciliationLock).filter(
        models.AccountReconciliationLock.user_id == run.user_id,
        models.AccountReconciliationLock.active == 1,
        or_(
            models.AccountReconciliationLock.integration_id.is_(None),
            models.AccountReconciliationLock.integration_id == (run.configuration or {}).get("integration_id"),
        ),
    ).first()
    if reconciliation_lock:
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code="reconciliation_required",
            summary="Simulation state requires operator reconciliation.",
        )
        return None
    reconcile_checkpoint(db, run)
    market = db.query(models.SimulationMarketInput).filter(
        models.SimulationMarketInput.id == market_input_id,
        models.SimulationMarketInput.run_id == run.id,
        models.SimulationMarketInput.user_id == tenant.user_id,
    ).with_for_update().first()
    if not market:
        raise DurableRunError("market_input_not_found")
    existing = db.query(models.SimulationEvaluation).filter_by(
        run_id=run.id,
        market_input_id=market.id,
    ).first()
    if existing:
        market.status = "processed"
        return existing
    if market.status == "processed":
        raise DurableRunError("processed_input_missing_evaluation")
    if market.content_hash != market_content_hash(market.payload or {}):
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code="market_content_tampered",
            summary="Persisted market input failed its integrity check.",
        )
        return None

    parameters = normalized_strategy_parameters(
        config_row.parameters if config_row else {
            "buy_threshold": (run.configuration or {}).get("buy_threshold", 30),
            "sell_threshold": (run.configuration or {}).get("sell_threshold", 70),
            "min_bars": (run.configuration or {}).get("min_bars", 30),
            "max_staleness_seconds": (run.configuration or {}).get("max_staleness_seconds", 300),
        }
    )
    classification = _market_classification(
        db, run, market,
        max_staleness_seconds=parameters["max_staleness_seconds"],
        now=now,
    )
    market.processing_owner, market.processing_fence = owner_id, fence
    market.freshness = classification
    run.last_market_data_at = market.event_at
    run.data_freshness = classification
    inject("after_market_classification")

    if classification in {"conflicting", "missing_predecessor"}:
        market.status, market.failure_code = "failed", f"market_data_{classification}"
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code=market.failure_code,
            summary="Market-data sequence could not be reconciled safely.",
        )
        return None

    frame, lookback_identity = _bars_frame(market.payload or {})
    if as_utc(frame.index[-1].to_pydatetime()) != as_utc(market.event_at):
        fail_owned_run(
            db, tenant, run.id, owner_id=owner_id, fence=fence,
            code="market_history_boundary_mismatch",
            summary="The market lookback does not end at the durable event boundary.",
        )
        return None
    evaluation_identity = _digest({
        "run": run.id,
        "configuration": run.configuration_hash,
        "strategy": run.strategy_version,
        "market": market.source_identity,
        "content": market.content_hash,
        "checkpoint": run.last_checkpoint_hash,
    })
    signal = "HOLD"
    status = "suppressed"
    rationale = classification
    snapshot: dict[str, Any] = {"classification": classification}
    if classification == "new":
        try:
            signal, rationale, snapshot, replay_lookback_identity = evaluate_rsi_threshold(
                market.payload or {}, parameters
            )
        except DurableRunError as exc:
            fail_owned_run(
                db, tenant, run.id, owner_id=owner_id, fence=fence,
                code=exc.code,
                summary=(
                    "Required deterministic strategy history is unavailable."
                    if exc.code == "market_history_missing"
                    else "RSI could not be calculated at the durable market boundary."
                ),
            )
            return None
        if replay_lookback_identity != lookback_identity:
            raise DurableRunError("deterministic_replay_mismatch")
        status = "observed" if signal == "HOLD" else "emitted"
        if not _schedule_allows(run.configuration or {}, as_utc(market.event_at)):
            status, rationale = "suppressed", "outside_configured_schedule"
    else:
        run.degraded_reason = f"market_data_{classification}"

    evaluation = models.SimulationEvaluation(
        id=str(uuid4()),
        run_id=run.id,
        user_id=run.user_id,
        market_input_id=market.id,
        evaluation_identity=evaluation_identity,
        fencing_token=fence,
        strategy_name=STRATEGY_NAME,
        strategy_version=run.strategy_version,
        configuration_hash=run.configuration_hash,
        lookback_identity=lookback_identity,
        signal=signal,
        status=status,
        rationale=rationale,
        market_snapshot=snapshot,
        freshness=classification,
        correlation_id=run.correlation_id,
        causation_id=market.source_identity,
    )
    db.add(evaluation)
    db.flush()
    inject("after_evaluation")

    counter = _risk_counter(db, run)
    outbox = _event(
        db, run, "simulation.evaluation.completed",
        {
            "evaluation_identity": evaluation_identity,
            "signal": signal,
            "status": status,
            "freshness": classification,
        },
        causation_id=market.source_identity,
    )
    if (
        classification == "new"
        and status == "emitted"
        and bool((run.configuration or {}).get("auto_trade", False))
    ):
        inject("before_order_intent")
        quantity = int((run.configuration or {}).get("quantity", 1))
        order_identity = f"simulation-order:{evaluation_identity}"
        intent = build_order_intent(
            user_id=run.user_id,
            symbol=run.symbol,
            side=signal,
            quantity=quantity,
            trading_mode="paper",
            order_type="market",
            integration_id=(run.configuration or {}).get("integration_id"),
            account_id=(run.configuration or {}).get("account_id"),
            idempotency_key=order_identity,
            source="durable-simulation",
            reference_price=float(snapshot["close"]),
        )
        try:
            risk_decision = risk_service.evaluate_order_intent(
                db,
                intent,
                commit_on_reject=False,
                simulation_run_id=run.id,
                simulation_fencing_token=fence,
                evaluation_identity=evaluation_identity,
            )
        except HTTPException:
            risk_decision = db.query(models.RiskDecision).filter_by(
                evaluation_identity=evaluation_identity
            ).first()
            evaluation.status = "risk_blocked"
        else:
            order = models.PaperOrder(
                user_id=run.user_id,
                integration_id=intent.integration_id,
                account_id=intent.account_id,
                symbol=run.symbol,
                side=signal,
                quantity=quantity,
                trading_mode="paper",
                order_type="market",
                source="durable-simulation",
                idempotency_key=order_identity,
                order_fingerprint=order_identity,
                status="submitted",
                filled_quantity=0,
                remaining_quantity=quantity,
                response={
                    "simulation": True,
                    "broker_execution": False,
                    "reference_price": snapshot["close"],
                },
                simulation_run_id=run.id,
                simulation_fencing_token=fence,
            )
            db.add(order)
            db.flush()
            risk_decision.paper_order_id = order.id
            db.add(models.PaperOrderEvent(
                order_id=order.id,
                user_id=run.user_id,
                event_type="submitted",
                status="submitted",
                message="Submitted to the local durable simulator; no broker order was placed.",
                event_metadata={"evaluation_identity": evaluation_identity, "simulation": True},
            ))
            inject("after_order_intent")
            assert_fence(db, tenant, run.id, owner_id, fence, lock=True)
            slippage_bps = float((run.configuration or {}).get("slippage_bps", 0.0))
            fee = float((run.configuration or {}).get("fee_per_contract", 0.0)) * quantity
            reference_price = float(snapshot["close"])
            fill_price = reference_price * (
                1 + slippage_bps / 10000 if signal == "BUY"
                else 1 - slippage_bps / 10000
            )
            fill_identity = f"simulation-fill:{evaluation_identity}"
            fill, position, account, realized_delta = _apply_fill(
                db,
                run,
                order,
                fence=fence,
                execution_identity=fill_identity,
                side=signal,
                quantity=quantity,
                price=fill_price,
                fee=fee,
            )
            inject("after_fill")
            assert_fence(db, tenant, run.id, owner_id, fence, lock=True)
            order.filled_quantity = quantity
            order.remaining_quantity = 0
            order.status = "filled"
            order.response = {
                **(order.response or {}),
                "simulated_fill_id": fill.id,
                "modeled_fill_price": fill_price,
                "modeled_slippage_bps": slippage_bps,
                "modeled_fee": fee,
            }
            db.add(models.PaperOrderEvent(
                order_id=order.id,
                user_id=run.user_id,
                event_type="filled",
                status="filled",
                message="Modeled simulation fill committed; no broker fill occurred.",
                event_metadata={
                    "evaluation_identity": evaluation_identity,
                    "fill_identity": fill_identity,
                    "modeled_fee": fee,
                    "modeled_slippage_bps": slippage_bps,
                },
            ))
            evaluation.status = "executed"
            counter.trade_count = int(counter.trade_count or 0) + 1
            counter.realized_pnl = float(counter.realized_pnl or 0) + realized_delta - fee
            counter.fees = float(counter.fees or 0) + fee
            counter.consecutive_losses = (
                int(counter.consecutive_losses or 0) + 1
                if realized_delta - fee < 0 else 0
            )
            counter.version = int(counter.version or 0) + 1
            counter.last_execution_identity = fill_identity
            counter.updated_at = utc_now()
            trading_day = as_utc(market.event_at).date().isoformat()
            daily_query = db.query(models.DailyRiskState).filter(
                models.DailyRiskState.user_id == run.user_id,
                models.DailyRiskState.trading_mode == "paper",
                models.DailyRiskState.trading_day == trading_day,
            )
            daily_query = daily_query.filter(
                models.DailyRiskState.integration_id.is_(None)
                if intent.integration_id is None
                else models.DailyRiskState.integration_id == intent.integration_id,
                models.DailyRiskState.account_id.is_(None)
                if intent.account_id is None
                else models.DailyRiskState.account_id == intent.account_id,
            )
            daily = daily_query.with_for_update().first()
            if daily is None:
                daily = models.DailyRiskState(
                    user_id=run.user_id,
                    integration_id=intent.integration_id,
                    account_id=intent.account_id,
                    trading_mode="paper",
                    trading_day=trading_day,
                )
                db.add(daily)
            daily.realized_pnl = float(daily.realized_pnl or 0) + realized_delta - fee
            daily.equity = account.equity
            daily.buying_power = account.buying_power
            settings = db.get(models.RiskSettings, risk_decision.risk_settings_id)
            if (
                settings
                and settings.max_daily_loss > 0
                and daily.realized_pnl <= -settings.max_daily_loss
            ):
                daily.locked = 1
                daily.lock_reason = "Maximum daily simulation loss reached."
            _event(
                db, run, "simulation.fill.committed",
                {
                    "evaluation_identity": evaluation_identity,
                    "order_identity": order_identity,
                    "fill_identity": fill_identity,
                    "position_quantity": position.quantity,
                    "modeled_fee": fee,
                },
                causation_id=evaluation_identity,
            )
            inject("after_ledger")

    assert_fence(db, tenant, run.id, owner_id, fence, lock=True)
    market.status = "processed"
    market.processed_at = now
    run.last_evaluation_at = now
    if classification == "new":
        run.degraded_reason = None
    db.flush()
    next_checkpoint = _checkpoint_value(
        db, run, market, evaluation, counter, event_id=outbox.id
    )
    checkpoint(
        db,
        tenant,
        run.id,
        owner_id=owner_id,
        fence=fence,
        sequence=run.last_checkpoint_sequence + 1,
        value=next_checkpoint,
    )
    inject("after_checkpoint")
    log_event(
        "durable_simulation",
        "evaluation_committed",
        user_id=run.user_id,
        run_id=run.id,
        market_input_id=market.id,
        evaluation_id=evaluation.id,
        signal=evaluation.signal,
        status=evaluation.status,
        data_freshness=classification,
        fencing_token=fence,
    )
    return evaluation


def process_pending_market_inputs(
    db: Session,
    *,
    worker_id: str,
    job_secret: str,
    job_environment: str = "test",
    limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    with system_maintenance_scope(db, "durable-market-discovery"):
        pending = (
            db.query(models.SimulationMarketInput)
            .filter(models.SimulationMarketInput.status == "pending")
            .order_by(models.SimulationMarketInput.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
    outcomes: list[dict[str, str]] = []
    for market in pending:
        tenant = VerifiedTenantJob.issue(
            TenantContext(market.user_id, "simulation-market-job"),
            market.id,
            job_secret,
            job_type="simulation-market", purpose="evaluate-market",
            environment=job_environment,
            payload={"run_id": market.run_id, "market_input_id": market.id},
        ).validate(
            job_secret,
            expected_tenant=market.user_id,
            expected_command=market.id,
            expected_actor=market.user_id,
            expected_job_type="simulation-market",
            expected_purpose="evaluate-market",
            expected_environment=job_environment,
            payload={"run_id": market.run_id, "market_input_id": market.id},
        )
        run = process_run(db, tenant, market.run_id, worker_id)
        if run.state != "running":
            outcomes.append({"market_input_id": market.id, "outcome": run.state})
            continue
        lease = db.query(models.SimulationLease).filter_by(
            run_id=run.id, user_id=tenant.user_id, owner_id=worker_id
        ).one()
        try:
            evaluation = process_market_input(
                db,
                tenant,
                run.id,
                market.id,
                owner_id=worker_id,
                fence=lease.fencing_token,
                now=now,
            )
            outcomes.append({
                "market_input_id": market.id,
                "outcome": evaluation.status if evaluation else run.state,
            })
        except DurableRunError as exc:
            outcomes.append({"market_input_id": market.id, "outcome": exc.code})
    return outcomes
