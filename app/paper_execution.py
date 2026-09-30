from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import analytics_service, models
from app.observability import log_event
from app.risk_service import risk_service
from app.trading_safety import PAPER_MODE, OrderIntent


ORDER_STATUS_SUBMITTED = "submitted"
ORDER_STATUS_CREATED = "created"
ORDER_STATUS_RISK_BLOCKED = "risk_blocked"
ORDER_STATUS_PENDING_SUBMIT = "pending_submit"
ORDER_STATUS_ACCEPTED = "accepted"
ORDER_STATUS_REJECTED = "rejected"
ORDER_STATUS_PARTIALLY_FILLED = "partially_filled"
ORDER_STATUS_FILLED = "filled"
ORDER_STATUS_CANCEL_REQUESTED = "cancel_requested"
ORDER_STATUS_CANCELED = "canceled"
ORDER_STATUS_EXPIRED = "expired"
ORDER_STATUS_TIMEOUT_UNKNOWN = "timeout_unknown"
ORDER_STATUS_RECONCILIATION_REQUIRED = "reconciliation_required"
ORDER_STATUS_FAILED = "failed"
TERMINAL_ORDER_STATUSES = {
    ORDER_STATUS_RISK_BLOCKED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_RECONCILIATION_REQUIRED,
    ORDER_STATUS_FAILED,
}
OPEN_ORDER_STATUSES = {ORDER_STATUS_CREATED, ORDER_STATUS_PENDING_SUBMIT, ORDER_STATUS_SUBMITTED, ORDER_STATUS_ACCEPTED}
DUPLICATE_WINDOW_SECONDS = 60
DEFAULT_PAPER_BALANCE = 100000.0

ALLOWED_TRANSITIONS = {
    ORDER_STATUS_CREATED: {ORDER_STATUS_PENDING_SUBMIT, ORDER_STATUS_REJECTED, ORDER_STATUS_EXPIRED},
    ORDER_STATUS_PENDING_SUBMIT: {ORDER_STATUS_SUBMITTED, ORDER_STATUS_REJECTED, ORDER_STATUS_EXPIRED},
    ORDER_STATUS_SUBMITTED: {
        ORDER_STATUS_ACCEPTED,
        ORDER_STATUS_REJECTED,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_TIMEOUT_UNKNOWN,
        ORDER_STATUS_FAILED,
    },
    ORDER_STATUS_ACCEPTED: {
        ORDER_STATUS_PARTIALLY_FILLED,
        ORDER_STATUS_FILLED,
        ORDER_STATUS_CANCEL_REQUESTED,
        ORDER_STATUS_REJECTED,
        ORDER_STATUS_CANCELED,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_RECONCILIATION_REQUIRED,
    },
    ORDER_STATUS_PARTIALLY_FILLED: {ORDER_STATUS_FILLED, ORDER_STATUS_CANCEL_REQUESTED, ORDER_STATUS_RECONCILIATION_REQUIRED},
    ORDER_STATUS_CANCEL_REQUESTED: {ORDER_STATUS_CANCELED, ORDER_STATUS_RECONCILIATION_REQUIRED},
    ORDER_STATUS_TIMEOUT_UNKNOWN: {ORDER_STATUS_RECONCILIATION_REQUIRED, ORDER_STATUS_FAILED},
}


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _event(
    db: Session,
    *,
    order: models.PaperOrder,
    event_type: str,
    status_value: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> models.PaperOrderEvent:
    event = models.PaperOrderEvent(
        order_id=order.id,
        user_id=order.user_id,
        event_type=event_type,
        status=status_value,
        message=message,
        event_metadata=metadata,
    )
    db.add(event)
    return event


def _transition_order(
    db: Session,
    *,
    order: models.PaperOrder,
    new_status: str,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if order.status in TERMINAL_ORDER_STATUSES:
        _event(
            db,
            order=order,
            event_type="invalid_transition",
            status_value=order.status,
            message=f"Cannot transition terminal order from {order.status} to {new_status}.",
            metadata={"requested_status": new_status},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition terminal order from {order.status} to {new_status}.",
        )
    if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        _event(
            db,
            order=order,
            event_type="invalid_transition",
            status_value=order.status,
            message=f"Invalid paper order transition from {order.status} to {new_status}.",
            metadata={"requested_status": new_status},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid paper order transition from {order.status} to {new_status}.",
        )
    order.status = new_status
    order.updated_at = datetime.utcnow()
    _event(db, order=order, event_type=event_type, status_value=new_status, message=message, metadata=metadata)


def _find_position(db: Session, intent: OrderIntent) -> models.PaperPosition | None:
    query = db.query(models.PaperPosition).filter(
        models.PaperPosition.user_id == intent.user_id,
        models.PaperPosition.symbol == intent.symbol,
    )
    if intent.integration_id is None:
        query = query.filter(models.PaperPosition.integration_id.is_(None))
    else:
        query = query.filter(models.PaperPosition.integration_id == intent.integration_id)
    if intent.account_id is None:
        query = query.filter(models.PaperPosition.account_id.is_(None))
    else:
        query = query.filter(models.PaperPosition.account_id == intent.account_id)
    return query.first()


def _find_snapshot(db: Session, intent: OrderIntent) -> models.PaperAccountSnapshot | None:
    query = db.query(models.PaperAccountSnapshot).filter(models.PaperAccountSnapshot.user_id == intent.user_id)
    if intent.integration_id is None:
        query = query.filter(models.PaperAccountSnapshot.integration_id.is_(None))
    else:
        query = query.filter(models.PaperAccountSnapshot.integration_id == intent.integration_id)
    if intent.account_id is None:
        query = query.filter(models.PaperAccountSnapshot.account_id.is_(None))
    else:
        query = query.filter(models.PaperAccountSnapshot.account_id == intent.account_id)
    return query.order_by(models.PaperAccountSnapshot.id.desc()).first()


def get_or_create_paper_snapshot(db: Session, intent: OrderIntent) -> models.PaperAccountSnapshot:
    snapshot = _find_snapshot(db, intent)
    if snapshot:
        return snapshot
    snapshot = models.PaperAccountSnapshot(
        user_id=intent.user_id,
        integration_id=intent.integration_id,
        account_id=intent.account_id,
        cash_balance=DEFAULT_PAPER_BALANCE,
        equity=DEFAULT_PAPER_BALANCE,
        buying_power=DEFAULT_PAPER_BALANCE,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        margin_used=0.0,
    )
    db.add(snapshot)
    db.flush()
    db.add(
        models.PaperLedgerEntry(
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            entry_type="starting_balance",
            amount=DEFAULT_PAPER_BALANCE,
            cash_balance=snapshot.cash_balance,
            equity=snapshot.equity,
            buying_power=snapshot.buying_power,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            description="Initial paper account balance.",
        )
    )
    return snapshot


def _same_order_intent(order: models.PaperOrder, intent: OrderIntent) -> bool:
    return (
        order.symbol == intent.symbol
        and order.side == intent.side
        and order.quantity == intent.quantity
        and order.trading_mode == intent.trading_mode
        and order.order_type == intent.order_type
        and order.integration_id == intent.integration_id
        and order.account_id == intent.account_id
        and order.source == intent.source
        and order.limit_price == intent.limit_price
        and order.stop_price == intent.stop_price
    )


def _order_fingerprint(intent: OrderIntent) -> str:
    raw = "|".join(
        [
            str(intent.user_id),
            str(intent.integration_id or ""),
            str(intent.account_id or ""),
            intent.symbol,
            intent.side,
            str(intent.quantity),
            intent.order_type,
            str(intent.limit_price or ""),
            str(intent.stop_price or ""),
            intent.source,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _recent_duplicate(db: Session, intent: OrderIntent, fingerprint: str) -> models.PaperOrder | None:
    cutoff = datetime.utcnow() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
    return (
        db.query(models.PaperOrder)
        .filter(
            models.PaperOrder.user_id == intent.user_id,
            models.PaperOrder.order_fingerprint == fingerprint,
            models.PaperOrder.created_at >= cutoff,
        )
        .order_by(models.PaperOrder.created_at.desc())
        .first()
    )


def _serialize_event(event: models.PaperOrderEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "status": event.status,
        "message": event.message,
        "metadata": event.event_metadata or {},
        "created_at": _utc_iso(event.created_at),
    }


def _serialize_fill(fill: models.PaperFill) -> dict[str, Any]:
    return {
        "id": fill.id,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "created_at": _utc_iso(fill.created_at),
    }


def _serialize_position(position: models.PaperPosition | None) -> dict[str, Any] | None:
    if not position:
        return None
    return {
        "id": position.id,
        "symbol": position.symbol,
        "quantity": position.quantity,
        "avg_price": position.avg_price,
        "integration_id": position.integration_id,
        "account_id": position.account_id,
        "updated_at": _utc_iso(position.updated_at),
    }


def _serialize_order(
    db: Session,
    order: models.PaperOrder,
    *,
    duplicate: bool = False,
) -> dict[str, Any]:
    fills = (
        db.query(models.PaperFill)
        .filter(models.PaperFill.order_id == order.id)
        .order_by(models.PaperFill.id.asc())
        .all()
    )
    events = (
        db.query(models.PaperOrderEvent)
        .filter(models.PaperOrderEvent.order_id == order.id)
        .order_by(models.PaperOrderEvent.id.asc())
        .all()
    )
    position = _find_position(
        db,
        OrderIntent(
            user_id=order.user_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            trading_mode=order.trading_mode,
            order_type=order.order_type,
            integration_id=order.integration_id,
            account_id=order.account_id,
            idempotency_key=order.idempotency_key,
            source=order.source,
            reference_price=order.response.get("reference_price") if order.response else None,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
        ),
    )
    snapshot = _find_snapshot(
        db,
        OrderIntent(
            user_id=order.user_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            trading_mode=order.trading_mode,
            order_type=order.order_type,
            integration_id=order.integration_id,
            account_id=order.account_id,
            idempotency_key=order.idempotency_key,
            source=order.source,
        ),
    )
    return {
        "success": order.status == ORDER_STATUS_FILLED,
        "paper": True,
        "live": False,
        "duplicate": duplicate,
        "status": order.status,
        "order_id": order.provider_order_id,
        "message": "Paper order processed locally. No live broker order was placed.",
        "reference_price": order.response.get("reference_price") if order.response else None,
        "order": {
            "id": order.id,
            "order_id": order.provider_order_id,
            "status": order.status,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "trading_mode": order.trading_mode,
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "stop_price": order.stop_price,
            "integration_id": order.integration_id,
            "account_id": order.account_id,
            "source": order.source,
            "idempotency_key": order.idempotency_key,
            "order_fingerprint": order.order_fingerprint,
            "filled_quantity": order.filled_quantity,
            "remaining_quantity": order.remaining_quantity,
            "rejected_reason": order.rejected_reason,
            "reference_price": order.response.get("reference_price") if order.response else None,
            "created_at": _utc_iso(order.created_at),
            "updated_at": _utc_iso(order.updated_at),
        },
        "fills": [_serialize_fill(fill) for fill in fills],
        "position": _serialize_position(position),
        "account": serialize_paper_snapshot(snapshot) if snapshot else None,
        "events": [_serialize_event(event) for event in events],
    }


def serialize_paper_snapshot(snapshot: models.PaperAccountSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "user_id": snapshot.user_id,
        "integration_id": snapshot.integration_id,
        "account_id": snapshot.account_id,
        "cash_balance": snapshot.cash_balance,
        "equity": snapshot.equity,
        "buying_power": snapshot.buying_power,
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "margin_used": snapshot.margin_used,
        "last_mark_price": snapshot.last_mark_price,
        "created_at": _utc_iso(snapshot.created_at),
        "updated_at": _utc_iso(snapshot.updated_at),
    }


def serialize_ledger_entry(entry: models.PaperLedgerEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "integration_id": entry.integration_id,
        "account_id": entry.account_id,
        "paper_order_id": entry.paper_order_id,
        "entry_type": entry.entry_type,
        "amount": entry.amount,
        "cash_balance": entry.cash_balance,
        "equity": entry.equity,
        "buying_power": entry.buying_power,
        "realized_pnl": entry.realized_pnl,
        "unrealized_pnl": entry.unrealized_pnl,
        "description": entry.description,
        "metadata": entry.entry_metadata or {},
        "created_at": _utc_iso(entry.created_at),
    }


def _should_fill(intent: OrderIntent) -> tuple[bool, str | None]:
    price = intent.reference_price
    if intent.order_type == "market":
        return True, None
    if price is None:
        return False, "reference_price is required to simulate non-market paper orders."
    if intent.order_type == "limit":
        if intent.side == "BUY" and price <= (intent.limit_price or 0):
            return True, None
        if intent.side == "SELL" and price >= (intent.limit_price or 0):
            return True, None
        return False, "Limit price was not marketable for the supplied reference price."
    if intent.order_type == "stop":
        if intent.side == "BUY" and price >= (intent.stop_price or 0):
            return True, None
        if intent.side == "SELL" and price <= (intent.stop_price or 0):
            return True, None
        return False, "Stop price was not triggered for the supplied reference price."
    if intent.order_type == "stop-limit":
        stop_triggered = (
            price >= (intent.stop_price or 0)
            if intent.side == "BUY"
            else price <= (intent.stop_price or 0)
        )
        limit_marketable = (
            price <= (intent.limit_price or 0)
            if intent.side == "BUY"
            else price >= (intent.limit_price or 0)
        )
        if stop_triggered and limit_marketable:
            return True, None
        return False, "Stop-limit conditions were not both satisfied."
    return False, "Unsupported paper order type."


def _apply_fill_to_position_and_ledger(
    db: Session,
    *,
    order: models.PaperOrder,
    intent: OrderIntent,
    fill_price: float | None,
) -> models.PaperPosition:
    snapshot = get_or_create_paper_snapshot(db, intent)
    position = _find_position(db, intent)
    if not position:
        position = models.PaperPosition(
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            symbol=intent.symbol,
            quantity=0,
            avg_price=0.0,
        )
        db.add(position)
        db.flush()

    price = fill_price if fill_price is not None else 100.0
    previous_quantity = position.quantity
    previous_avg = position.avg_price or 0.0
    signed_quantity = intent.quantity if intent.side == "BUY" else -intent.quantity
    new_quantity = previous_quantity + signed_quantity
    realized_delta = 0.0

    if previous_quantity == 0 or (previous_quantity > 0 and signed_quantity > 0) or (previous_quantity < 0 and signed_quantity < 0):
        total_abs = abs(previous_quantity) + intent.quantity
        position.avg_price = ((abs(previous_quantity) * previous_avg) + (intent.quantity * price)) / total_abs if total_abs else 0.0
    else:
        closing_quantity = min(abs(previous_quantity), intent.quantity)
        if previous_quantity > 0:
            realized_delta = (price - previous_avg) * closing_quantity
        else:
            realized_delta = (previous_avg - price) * closing_quantity
        if new_quantity == 0:
            position.avg_price = 0.0
        elif (previous_quantity > 0 and new_quantity < 0) or (previous_quantity < 0 and new_quantity > 0):
            position.avg_price = price

    position.quantity = new_quantity
    position.updated_at = datetime.utcnow()

    notional = price * intent.quantity
    cash_delta = -notional if intent.side == "BUY" else notional
    snapshot.cash_balance += cash_delta
    snapshot.realized_pnl += realized_delta
    snapshot.unrealized_pnl = 0.0
    snapshot.equity = snapshot.cash_balance + max(position.quantity, 0) * price
    snapshot.buying_power = snapshot.equity
    snapshot.margin_used = abs(position.quantity) * price
    snapshot.last_mark_price = price
    snapshot.updated_at = datetime.utcnow()

    db.add(
        models.PaperLedgerEntry(
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            paper_order_id=order.id,
            entry_type="fill",
            amount=cash_delta,
            cash_balance=snapshot.cash_balance,
            equity=snapshot.equity,
            buying_power=snapshot.buying_power,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            description="Paper fill applied to account snapshot.",
            entry_metadata={
                "symbol": intent.symbol,
                "side": intent.side,
                "quantity": intent.quantity,
                "fill_price": price,
                "realized_pnl_delta": realized_delta,
            },
        )
    )
    return position


def execute_paper_order(db: Session, intent: OrderIntent) -> dict[str, Any]:
    if intent.trading_mode != PAPER_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live trading remains disabled. Only paper orders can be executed.",
        )
    if not intent.idempotency_key or not intent.idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="idempotency_key is required for paper order execution.",
        )
    fingerprint = _order_fingerprint(intent)

    existing = (
        db.query(models.PaperOrder)
        .filter(
            models.PaperOrder.user_id == intent.user_id,
            models.PaperOrder.idempotency_key == intent.idempotency_key,
        )
        .first()
    )
    if existing:
        if not _same_order_intent(existing, intent):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="idempotency_key was already used for a different paper order.",
            )
        log_event(
            "trade_execution",
            "paper_order_duplicate",
            user_id=intent.user_id,
            order_id=existing.id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            source=intent.source,
        )
        return _serialize_order(db, existing, duplicate=True)

    duplicate = _recent_duplicate(db, intent, fingerprint)
    if duplicate:
        _event(
            db,
            order=duplicate,
            event_type="duplicate_suppressed",
            status_value=duplicate.status,
            message="Suppressed likely duplicate paper order within the duplicate window.",
            metadata={"idempotency_key": intent.idempotency_key, "duplicate_window_seconds": DUPLICATE_WINDOW_SECONDS},
        )
        db.commit()
        log_event(
            "trade_execution",
            "paper_order_fingerprint_duplicate",
            user_id=intent.user_id,
            order_id=duplicate.id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            source=intent.source,
        )
        return _serialize_order(db, duplicate, duplicate=True)

    try:
        risk_decision = risk_service.evaluate_order_intent(db, intent)
    except HTTPException as exc:
        now = datetime.utcnow()
        blocked_order = models.PaperOrder(
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            trading_mode=intent.trading_mode,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            source=intent.source,
            idempotency_key=intent.idempotency_key,
            order_fingerprint=fingerprint,
            status=ORDER_STATUS_RISK_BLOCKED,
            filled_quantity=0,
            remaining_quantity=intent.quantity,
            rejected_reason=str(exc.detail),
            created_at=now,
            updated_at=now,
        )
        db.add(blocked_order)
        db.flush()
        blocked_order.provider_order_id = f"paper-{blocked_order.id}"
        _event(
            db,
            order=blocked_order,
            event_type="risk_blocked",
            status_value=ORDER_STATUS_RISK_BLOCKED,
            message=str(exc.detail),
            metadata={"readiness_blocker": exc.headers.get("X-Readiness-Blocker") if exc.headers else None},
        )
        analytics_service.capture_event(
            db,
            event_name="paper_order_blocked",
            user_id=intent.user_id,
            metadata={"symbol": intent.symbol, "source": intent.source, "reason": str(exc.detail)},
            source="paper_execution",
        )
        db.commit()
        raise
    now = datetime.utcnow()
    order = models.PaperOrder(
        user_id=intent.user_id,
        integration_id=intent.integration_id,
        account_id=intent.account_id,
        symbol=intent.symbol,
        side=intent.side,
        quantity=intent.quantity,
        trading_mode=intent.trading_mode,
        order_type=intent.order_type,
        limit_price=intent.limit_price,
        stop_price=intent.stop_price,
        source=intent.source,
        idempotency_key=intent.idempotency_key,
        order_fingerprint=fingerprint,
        status=ORDER_STATUS_CREATED,
        filled_quantity=0,
        remaining_quantity=intent.quantity,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    db.flush()
    risk_decision.paper_order_id = order.id
    order.provider_order_id = f"paper-{order.id}"
    _event(
        db,
        order=order,
        event_type="created",
        status_value=ORDER_STATUS_CREATED,
        message="Paper order created after persisted risk checks.",
        metadata={"risk_decision_id": risk_decision.id},
    )
    analytics_service.capture_event(
        db,
        event_name="paper_order_created",
        user_id=intent.user_id,
        metadata={"symbol": intent.symbol, "source": intent.source, "order_type": intent.order_type},
        source="paper_execution",
    )
    _transition_order(
        db,
        order=order,
        new_status=ORDER_STATUS_PENDING_SUBMIT,
        event_type="pending_submit",
        message="Paper order queued for local simulation.",
    )
    _transition_order(
        db,
        order=order,
        new_status=ORDER_STATUS_SUBMITTED,
        event_type="submitted",
        message="Paper order submitted to the local simulator.",
    )

    should_fill, rejection_reason = _should_fill(intent)
    if not should_fill:
        order.rejected_reason = rejection_reason
        _transition_order(
            db,
            order=order,
            new_status=ORDER_STATUS_REJECTED,
            event_type="rejected",
            message=rejection_reason or "Paper order rejected by local simulator.",
            metadata={
                "reference_price": intent.reference_price,
                "limit_price": intent.limit_price,
                "stop_price": intent.stop_price,
            },
        )
        db.flush()
        response = _serialize_order(db, order)
        response["reference_price"] = intent.reference_price
        order.response = response
        db.commit()
        db.refresh(order)
        return _serialize_order(db, order)

    _transition_order(
        db,
        order=order,
        new_status=ORDER_STATUS_ACCEPTED,
        event_type="accepted",
        message="Paper order accepted for simulated fill.",
    )

    effective_fill_price = intent.reference_price if intent.reference_price is not None else 100.0
    fill = models.PaperFill(
        order_id=order.id,
        user_id=order.user_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=effective_fill_price,
    )
    db.add(fill)
    position = _apply_fill_to_position_and_ledger(db, order=order, intent=intent, fill_price=effective_fill_price)

    order.filled_quantity = order.quantity
    order.remaining_quantity = 0
    _transition_order(
        db,
        order=order,
        new_status=ORDER_STATUS_FILLED,
        event_type="filled",
        message="Paper order filled locally. No broker API order was placed.",
        metadata={"position_quantity": position.quantity, "fill_price": effective_fill_price},
    )
    db.flush()

    response = _serialize_order(db, order)
    response["reference_price"] = effective_fill_price
    response["order"]["reference_price"] = effective_fill_price
    order.response = response
    db.commit()
    db.refresh(order)
    log_event(
        "trade_execution",
        "paper_order_filled",
        user_id=intent.user_id,
        order_id=order.id,
        provider_order_id=order.provider_order_id,
        symbol=intent.symbol,
        side=intent.side,
        quantity=intent.quantity,
        integration_id=intent.integration_id,
        account_id=intent.account_id,
        source=intent.source,
        live=False,
    )
    analytics_service.capture_event(
        db,
        event_name="paper_order_filled",
        user_id=intent.user_id,
        metadata={"symbol": intent.symbol, "source": intent.source, "order_type": intent.order_type},
        source="paper_execution",
    )
    db.commit()
    return _serialize_order(db, order)


def get_paper_order(db: Session, *, user_id: int, order_id: int) -> dict[str, Any]:
    order = (
        db.query(models.PaperOrder)
        .filter(models.PaperOrder.user_id == user_id, models.PaperOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper order not found.")
    return _serialize_order(db, order)


def list_open_paper_orders(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    orders = (
        db.query(models.PaperOrder)
        .filter(models.PaperOrder.user_id == user_id, models.PaperOrder.status.in_(OPEN_ORDER_STATUSES))
        .order_by(models.PaperOrder.created_at.desc())
        .all()
    )
    return [_serialize_order(db, order) for order in orders]


def list_paper_positions(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    positions = (
        db.query(models.PaperPosition)
        .filter(models.PaperPosition.user_id == user_id)
        .order_by(models.PaperPosition.symbol.asc())
        .all()
    )
    return [_serialize_position(position) for position in positions]


def list_paper_account_snapshots(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    snapshots = (
        db.query(models.PaperAccountSnapshot)
        .filter(models.PaperAccountSnapshot.user_id == user_id)
        .order_by(models.PaperAccountSnapshot.updated_at.desc())
        .all()
    )
    return [serialize_paper_snapshot(snapshot) for snapshot in snapshots]


def list_paper_ledger_entries(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    entries = (
        db.query(models.PaperLedgerEntry)
        .filter(models.PaperLedgerEntry.user_id == user_id)
        .order_by(models.PaperLedgerEntry.created_at.desc())
        .limit(200)
        .all()
    )
    return [serialize_ledger_entry(entry) for entry in entries]
