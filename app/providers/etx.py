from __future__ import annotations

from .base import ProviderAdapter
from .types import IntegrationCapability, IntegrationProvider


class EtxAdapter(ProviderAdapter):
    provider = IntegrationProvider.ETX
    capabilities: set[IntegrationCapability] = set()

    def validate_credentials(self) -> None:
        if not self.credentials:
            raise ValueError("ETX credentials are not configured.")

    async def healthcheck(self) -> dict:
        if not self.credentials:
            return {"status": "not_configured", "message": "ETX credentials missing."}
        return {"status": "unavailable", "message": "ETX adapter is not implemented yet."}

    async def place_order(self, order: dict) -> dict:
        raise NotImplementedError("ETX trading adapter is not implemented yet.")
