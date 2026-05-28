from __future__ import annotations

from .base import ProviderAdapter
from .types import IntegrationCapability, IntegrationProvider


class NinjaTraderAdapter(ProviderAdapter):
    provider = IntegrationProvider.NINJATRADER
    capabilities: set[IntegrationCapability] = set()

    def validate_credentials(self) -> None:
        if not self.credentials:
            raise ValueError("NinjaTrader credentials are not configured.")

    async def healthcheck(self) -> dict:
        if not self.credentials:
            return {"status": "not_configured", "message": "NinjaTrader credentials missing."}
        return {"status": "unavailable", "message": "NinjaTrader adapter is not implemented yet."}

    async def place_order(self, order: dict) -> dict:
        raise NotImplementedError("NinjaTrader trading adapter is not implemented yet.")
