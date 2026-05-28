from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import IntegrationCapability, IntegrationProvider


class ProviderCapabilityError(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class ProviderAdapter(ABC):
    provider: IntegrationProvider
    capabilities: set[IntegrationCapability]

    def __init__(self, credentials: dict, metadata: dict | None = None) -> None:
        self.credentials = credentials
        self.metadata = metadata or {}

    async def healthcheck(self) -> dict:
        return {"status": "ok"}

    async def diagnostics(self) -> dict:
        health = await self.healthcheck()
        return {
            "provider": self.provider.value,
            "health": health,
            "implemented_capabilities": [cap.value for cap in self.capabilities],
        }

    async def get_contracts(self) -> list[dict]:
        raise ProviderCapabilityError("Provider does not support market data.")

    async def list_accounts(self) -> list[dict]:
        account = await self.get_account()
        return [account] if account else []

    async def get_account(self) -> dict:
        raise ProviderCapabilityError("Provider does not support account info.")

    async def place_order(self, order: dict) -> dict:
        raise ProviderCapabilityError("Provider does not support trading.")

    async def get_order(self, provider_order_id: str) -> dict:
        raise ProviderCapabilityError("Provider does not support order status.")

    async def list_open_orders(self) -> list[dict]:
        raise ProviderCapabilityError("Provider does not support open orders.")

    async def get_positions(self) -> list[dict]:
        raise ProviderCapabilityError("Provider does not support positions.")

    async def cancel_order(self, provider_order_id: str) -> dict:
        raise ProviderCapabilityError("Provider does not support order cancellation.")

    async def flatten_positions(self, account_id: str | None = None) -> dict:
        raise ProviderCapabilityError("Provider does not support position flattening.")

    @abstractmethod
    def validate_credentials(self) -> None:
        raise NotImplementedError
