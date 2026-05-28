import logging
import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import database, models
from app.auth_routes import get_current_user_model
from app.integrations_service import (
    get_integration_for_user,
    resolve_integration,
)
from app.providers.factory import get_adapter
from app.providers.types import IntegrationCapability, IntegrationProvider
from app.trading_safety import LIVE_MODE, normalize_mode

router = APIRouter()
logger = logging.getLogger(__name__)


def _fallback_contracts():
    """Provide a small set of recognizable contracts when API auth is unavailable."""
    fallback_env = os.getenv("FALLBACK_CONTRACTS", "ES,NQ,YM,CL,GC")
    return [symbol.strip() for symbol in fallback_env.split(",") if symbol.strip()]


@router.get("/contracts")
async def list_contracts(
    integration_id: int | None = None,
    provider: IntegrationProvider | None = None,
    trading_mode: str = "paper",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    """Return a list of available contract symbols."""
    mode = normalize_mode(trading_mode)
    integration = resolve_integration(
        db,
        current_user.id,
        integration_id=integration_id,
        required_provider=provider,
        required_capabilities={IntegrationCapability.MARKET_DATA},
    )
    if integration_id is not None and not integration:
        candidate = get_integration_for_user(db, current_user.id, integration_id)
        if not candidate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Integration not found for current user.",
            )
        if candidate.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Integration is not active.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected integration does not provide implemented market data.",
        )

    if not integration:
        if mode == LIVE_MODE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Live mode requires contracts from a selected market data integration.",
            )
        return {
            "contracts": _fallback_contracts(),
            "source": "fallback",
            "tradable_live": False,
            "message": "Paper-mode fallback contracts are simulated and not live-tradable.",
        }

    adapter = get_adapter(integration)
    try:
        contracts = await adapter.get_contracts()
    except Exception as exc:
        logger.warning("Failed to load contracts: %s", exc)
        if mode == LIVE_MODE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Live mode requires provider contracts; market data integration unavailable.",
            ) from exc
        return {
            "contracts": _fallback_contracts(),
            "source": "fallback",
            "tradable_live": False,
            "message": "Paper-mode fallback contracts are simulated and not live-tradable.",
        }
    symbols = [c.get("name") for c in contracts if c.get("name")]
    return {"contracts": symbols, "source": integration.provider.lower(), "tradable_live": False}
