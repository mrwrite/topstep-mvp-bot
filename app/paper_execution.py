from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.trading_safety import PAPER_MODE, OrderIntent


ORDER_STATUS_SUBMITTED = "submitted"
ORDER_STATUS_ACCEPTED = "accepted"
ORDER_STATUS_FILLED = "filled"
OPEN_ORDER_STATUSES = {ORDER_STATUS_SUBMITTED, ORDER_STATUS_ACCEPTED}


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
        ),
    )
    return {
        "success": order.status == ORDER_STATUS_FILLED,
        "paper": True,
        "live": False,
        "duplicate": duplicate,
        "status": order.status,
        "order_id": order.provider_order_id,
        "message": "Paper order filled. No live broker order was placed.",
        "order": {
            "id": order.id,
            "order_id": order.provider_order_id,
            "status": order.status,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "trading_mode": order.trading_mode,
            "order_type": order.order_type,
            "integration_id": order.integration_id,
            "account_id": order.account_id,
            "source": order.source,
            "idempotency_key": order.idempotency_key,
            "created_at": _utc_iso(order.created_at),
            "updated_at": _utc_iso(order.updated_at),
        },
        "fills": [_serialize_fill(fill) for fill in fills],
        "position": _serialize_position(position),
        "events": [_serialize_event(event) for event in events],
    }


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
        return _serialize_order(db, existing, duplicate=True)

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
        source=intent.source,
        idempotency_key=intent.idempotency_key,
        status=ORDER_STATUS_SUBMITTED,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    db.flush()
    order.provider_order_id = f"paper-{order.id}"
    _event(
        db,
        order=order,
        event_type="submitted",
        status_value=ORDER_STATUS_SUBMITTED,
        message="Paper order accepted into the local execution lifecycle.",
    )

    order.status = ORDER_STATUS_ACCEPTED
    order.updated_at = datetime.utcnow()
    _event(
        db,
        order=order,
        event_type="accepted",
        status_value=ORDER_STATUS_ACCEPTED,
        message="Paper order accepted for simulated fill.",
    )

    fill = models.PaperFill(
        order_id=order.id,
        user_id=order.user_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=None,
    )
    db.add(fill)

    position = _find_position(db, intent)
    if not position:
        position = models.PaperPosition(
            user_id=intent.user_id,
            integration_id=intent.integration_id,
            account_id=intent.account_id,
            symbol=intent.symbol,
            quantity=0,
        )
        db.add(position)
        db.flush()
    position.quantity += intent.quantity if intent.side == "BUY" else -intent.quantity
    position.updated_at = datetime.utcnow()

    order.status = ORDER_STATUS_FILLED
    order.updated_at = datetime.utcnow()
    _event(
        db,
        order=order,
        event_type="filled",
        status_value=ORDER_STATUS_FILLED,
        message="Paper order filled locally. No broker API order was placed.",
        metadata={"position_quantity": position.quantity},
    )
    db.flush()

    response = _serialize_order(db, order)
    order.response = response
    db.commit()
    db.refresh(order)
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
