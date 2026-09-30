from __future__ import annotations

from .base import ProviderAdapter
from .types import IntegrationCapability, IntegrationProvider


class TradingViewAdapter(ProviderAdapter):
    provider = IntegrationProvider.TRADINGVIEW
    capabilities = {
        IntegrationCapability.SIGNALS,
    }

    def validate_credentials(self) -> None:
        return None

    async def healthcheck(self) -> dict:
        return {"status": "ok"}

    def validate_webhook_secret(self, incoming_secret: str | None) -> bool:
        expected = self.credentials.get("webhookSecret") or self.metadata.get("webhookSecret")
        if not expected:
            return False
        return bool(incoming_secret) and incoming_secret == expected
