from __future__ import annotations

from .base import ProviderAdapter
from .types import IntegrationCapability, IntegrationProvider


class TradovateAdapter(ProviderAdapter):
    provider = IntegrationProvider.TRADOVATE
    capabilities: set[IntegrationCapability] = set()

    def validate_credentials(self) -> None:
        if not self.credentials:
            raise ValueError("Tradovate credentials are not configured.")

    async def healthcheck(self) -> dict:
        if not self.credentials:
            return {"status": "not_configured", "message": "Tradovate credentials missing."}
        return {"status": "unavailable", "message": "Tradovate adapter is not implemented yet."}

    async def place_order(self, order: dict) -> dict:
        raise NotImplementedError("Tradovate trading adapter is not implemented yet.")
