# app/trading_routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.integrations_service import resolve_integration
from app.paper_execution import execute_paper_order
from app.providers.factory import get_adapter
from app.providers.types import IntegrationCapability, IntegrationProvider, PROVIDER_CAPABILITIES
from app.trading_safety import build_order_intent

router = APIRouter()

class TradingSignal(BaseModel):
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: int
    signal_integration_id: int | None = None
    broker_integration_id: int | None = None
    secret: str | None = None
    trading_mode: str = "paper"
    order_type: str = "market"
    idempotency_key: str | None = None

@router.get("/test-trade")
async def test_trade(
    trading_mode: str = "paper",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = resolve_integration(
        db,
        current_user.id,
        required_capabilities={IntegrationCapability.BROKER_TRADING},
    )
    if not integration:
        raise HTTPException(status_code=400, detail="No active broker integration configured.")
    intent = build_order_intent(
        user_id=current_user.id,
        symbol="NQU5",
        side="BUY",
        quantity=1,
        trading_mode=trading_mode,
        integration_id=integration.id,
        idempotency_key=f"test-trade:{current_user.id}",
        source="test-trade",
    )
    return execute_paper_order(db, intent)

@router.post("/webhook")
async def receive_signal(
    signal: TradingSignal,
    db: Session = Depends(database.get_db),
):
    if not signal.signal_integration_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="signal_integration_id is required for webhook routing.",
        )
    if not signal.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="idempotency_key is required for webhook replay protection.",
        )

    signal_integration = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.id == signal.signal_integration_id)
        .first()
    )
    if not signal_integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal integration not found.")
    if signal_integration.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signal integration is not active.")

    try:
        signal_provider = IntegrationProvider(signal_integration.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported signal provider.") from exc
    if IntegrationCapability.SIGNALS not in PROVIDER_CAPABILITIES.get(signal_provider, set()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Integration does not support signals.")

    signal_adapter = get_adapter(signal_integration)
    if hasattr(signal_adapter, "validate_webhook_secret"):
        if not signal_adapter.validate_webhook_secret(signal.secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret.")

    broker_integration = None
    if signal.broker_integration_id is not None:
        broker_integration = resolve_integration(
            db,
            signal_integration.user_id,
            integration_id=signal.broker_integration_id,
            required_capabilities={IntegrationCapability.BROKER_TRADING},
        )
        if not broker_integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Broker integration not found for signal owner.",
            )

    intent = build_order_intent(
        user_id=signal_integration.user_id,
        symbol=signal.symbol,
        side=signal.side,
        quantity=signal.quantity,
        trading_mode=signal.trading_mode,
        order_type=signal.order_type,
        integration_id=broker_integration.id if broker_integration else None,
        idempotency_key=signal.idempotency_key,
        source="webhook",
    )
    result = execute_paper_order(db, intent)
    return {"status": "duplicate" if result["duplicate"] else "received", "result": result}
