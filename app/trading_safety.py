from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status


PAPER_MODE = "paper"
LIVE_MODE = "live"
SUPPORTED_ORDER_TYPES = {"market", "limit", "stop", "stop-limit"}
SUPPORTED_MODES = {PAPER_MODE, LIVE_MODE}
SUPPORTED_SIDES = {"BUY", "SELL"}


@dataclass(frozen=True)
class OrderIntent:
    user_id: int
    symbol: str
    side: str
    quantity: int
    trading_mode: str = PAPER_MODE
    order_type: str = "market"
    integration_id: int | None = None
    account_id: str | None = None
    idempotency_key: str | None = None
    source: str = "manual"
    reference_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None


def normalize_mode(mode: str | None) -> str:
    normalized = (mode or PAPER_MODE).strip().lower()
    if normalized not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="trading_mode must be 'paper' or 'live'.",
        )
    return normalized


def normalize_side(side: str | None) -> str:
    normalized = (side or "").strip().upper()
    if normalized not in SUPPORTED_SIDES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="side must be BUY or SELL.",
        )
    return normalized


def normalize_order_type(order_type: str | None) -> str:
    normalized = (order_type or "market").strip().lower()
    if normalized not in SUPPORTED_ORDER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="order_type must be market, limit, stop, or stop-limit.",
        )
    return normalized


def assert_live_trading_blocked(mode: str) -> None:
    if normalize_mode(mode) == LIVE_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Live trading is disabled until Phase 1 safety, user-scoping, "
                "audit, and readiness gates are complete."
            ),
        )


def build_order_intent(
    *,
    user_id: int,
    symbol: str,
    side: str,
    quantity: int,
    trading_mode: str | None = None,
    order_type: str | None = None,
    integration_id: int | None = None,
    account_id: str | None = None,
    idempotency_key: str | None = None,
    source: str = "manual",
    reference_price: float | None = None,
    limit_price: float | None = None,
    stop_price: float | None = None,
) -> OrderIntent:
    if not symbol or not symbol.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="symbol is required.",
        )
    if quantity < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="quantity must be at least 1.",
        )

    mode = normalize_mode(trading_mode)
    assert_live_trading_blocked(mode)
    normalized_order_type = normalize_order_type(order_type)
    if limit_price is not None and limit_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit_price must be greater than 0.",
        )
    if stop_price is not None and stop_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stop_price must be greater than 0.",
        )
    if normalized_order_type in {"limit", "stop-limit"} and limit_price is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit_price is required for limit and stop-limit paper orders.",
        )
    if normalized_order_type in {"stop", "stop-limit"} and stop_price is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stop_price is required for stop and stop-limit paper orders.",
        )

    return OrderIntent(
        user_id=user_id,
        symbol=symbol.strip().upper(),
        side=normalize_side(side),
        quantity=quantity,
        trading_mode=mode,
        order_type=normalized_order_type,
        integration_id=integration_id,
        account_id=account_id,
        idempotency_key=idempotency_key,
        source=source,
        reference_price=reference_price,
        limit_price=limit_price,
        stop_price=stop_price,
    )


def simulate_paper_order(intent: OrderIntent) -> dict[str, Any]:
    return {
        "success": True,
        "status": "simulated",
        "paper": True,
        "live": False,
        "order_id": f"paper-{uuid4()}",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "message": "Paper order simulated. No live broker order was placed.",
        "order": {
            "symbol": intent.symbol,
            "side": intent.side,
            "quantity": intent.quantity,
            "trading_mode": intent.trading_mode,
            "order_type": intent.order_type,
            "integration_id": intent.integration_id,
            "account_id": intent.account_id,
            "source": intent.source,
            "idempotency_key": intent.idempotency_key,
            "reference_price": intent.reference_price,
            "limit_price": intent.limit_price,
            "stop_price": intent.stop_price,
        },
    }
