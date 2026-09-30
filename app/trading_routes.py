# app/trading_routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.paper_execution import execute_paper_order
from app.providers.factory import get_adapter
from app.providers.types import IntegrationCapability
from app.trading_context import trading_context_service
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
    limit_price: float | None = None
    stop_price: float | None = None
    reference_price: float | None = None
    idempotency_key: str | None = None

@router.get("/test-trade")
async def test_trade(
    trading_mode: str = "paper",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    context = trading_context_service.resolve(
        db,
        user_id=current_user.id,
        trading_mode=trading_mode,
        required_capabilities={IntegrationCapability.BROKER_TRADING},
        require_integration=True,
    )
    integration = context.integration
    intent = build_order_intent(
        user_id=current_user.id,
        symbol="ES",
        side="BUY",
        quantity=1,
        trading_mode=context.trading_mode,
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
    # Compatibility fixture only. Hosted beta has no approved webhook signal
    # provider and must not perform a global integration lookup by opaque ID.
    if database.APP_CONFIG.app_env != "test":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal endpoint not available.",
        )
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

    signal_context = trading_context_service.resolve(
        db,
        user_id=signal_integration.user_id,
        trading_mode=signal.trading_mode,
        integration_id=signal_integration.id,
        symbol=signal.symbol,
        required_capabilities={IntegrationCapability.SIGNALS},
        require_integration=True,
        require_contract=True,
    )

    signal_adapter = get_adapter(signal_context.integration)
    if hasattr(signal_adapter, "validate_webhook_secret"):
        if not signal_adapter.validate_webhook_secret(signal.secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret.")

    broker_integration = None
    if signal.broker_integration_id is not None:
        context = trading_context_service.resolve(
            db,
            user_id=signal_integration.user_id,
            trading_mode=signal.trading_mode,
            integration_id=signal.broker_integration_id,
            symbol=signal.symbol,
            required_capabilities={IntegrationCapability.BROKER_TRADING},
            require_integration=True,
            require_contract=True,
        )
        broker_integration = context.integration
    else:
        context = trading_context_service.resolve(
            db,
            user_id=signal_integration.user_id,
            trading_mode=signal.trading_mode,
            symbol=signal.symbol,
            required_capabilities={IntegrationCapability.BROKER_TRADING},
            require_integration=False,
            require_contract=True,
            allow_paper_fallback=True,
        )

    intent = build_order_intent(
        user_id=signal_integration.user_id,
        symbol=context.symbol,
        side=signal.side,
        quantity=signal.quantity,
        trading_mode=context.trading_mode,
        order_type=signal.order_type,
        integration_id=broker_integration.id if broker_integration else None,
        idempotency_key=signal.idempotency_key,
        source="webhook",
        reference_price=signal.reference_price,
        limit_price=signal.limit_price,
        stop_price=signal.stop_price,
    )
    result = execute_paper_order(db, intent)
    return {"status": "duplicate" if result["duplicate"] else "received", "result": result}
