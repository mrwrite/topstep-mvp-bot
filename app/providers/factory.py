from __future__ import annotations

from app.crypto import decrypt_credentials as decrypt_blob
from app.models import PlatformIntegration
from .base import ProviderAdapter
from .types import IntegrationProvider
from app.integrations_service import normalize_credentials


def decrypt_integration_credentials(integration: PlatformIntegration) -> dict:
    if not integration.credentials_encrypted:
        return {}
    return decrypt_blob(
        integration.credentials_encrypted,
        user_id=integration.user_id,
        record_id=integration.id,
    )


def get_adapter(integration: PlatformIntegration) -> ProviderAdapter:
    provider = IntegrationProvider(integration.provider)
    credentials = decrypt_integration_credentials(integration)
    normalized = normalize_credentials(provider, credentials, integration.integration_metadata)

    if provider == IntegrationProvider.TOPSTEPX:
        from .topstepx import TopStepXAdapter

        return TopStepXAdapter(normalized, integration.integration_metadata)
    if provider == IntegrationProvider.TRADOVATE:
        from .tradovate import TradovateAdapter

        return TradovateAdapter(normalized, integration.integration_metadata)
    if provider == IntegrationProvider.NINJATRADER:
        from .ninjatrader import NinjaTraderAdapter

        return NinjaTraderAdapter(normalized, integration.integration_metadata)
    if provider == IntegrationProvider.IBKR:
        from .ibkr import IbkrAdapter

        return IbkrAdapter(normalized, integration.integration_metadata)
    if provider == IntegrationProvider.ETX:
        from .etx import EtxAdapter

        return EtxAdapter(normalized, integration.integration_metadata)
    if provider == IntegrationProvider.TRADINGVIEW:
        from .tradingview import TradingViewAdapter

        return TradingViewAdapter(normalized, integration.integration_metadata)

    raise ValueError(f"Unsupported provider: {provider}")
