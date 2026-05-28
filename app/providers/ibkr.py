from __future__ import annotations

from .base import ProviderAdapter
from .types import IntegrationCapability, IntegrationProvider


class IbkrAdapter(ProviderAdapter):
    provider = IntegrationProvider.IBKR
    capabilities: set[IntegrationCapability] = set()

    def validate_credentials(self) -> None:
        if not self.credentials:
            raise ValueError("IBKR credentials are not configured.")

    async def healthcheck(self) -> dict:
        if not self.credentials:
            return {"status": "not_configured", "message": "IBKR credentials missing."}
        return {"status": "unavailable", "message": "IBKR adapter is not implemented yet."}

    async def place_order(self, order: dict) -> dict:
        raise NotImplementedError("IBKR trading adapter is not implemented yet.")
