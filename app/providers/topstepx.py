from __future__ import annotations

import logging
import os
from typing import Any
from datetime import datetime, timedelta

import requests

from .base import ProviderAdapter, ProviderCapabilityError, ProviderError
from .types import IntegrationCapability, IntegrationProvider


logger = logging.getLogger(__name__)


class TopStepXAdapter(ProviderAdapter):
    provider = IntegrationProvider.TOPSTEPX
    capabilities = {
        IntegrationCapability.BROKER_TRADING,
        IntegrationCapability.MARKET_DATA,
        IntegrationCapability.ACCOUNT_INFO,
    }

    def __init__(self, credentials: dict, metadata: dict | None = None) -> None:
        super().__init__(credentials, metadata)
        self.base_url = (
            credentials.get("baseUrl")
            or (metadata or {}).get("baseUrl")
            or os.getenv("TOPSTEP_BASE_URL", "https://api.topstepx.com")
        )
        self._session_token_cache: str | None = None
        self._session_token_expires_at: datetime | None = None

    def validate_credentials(self) -> None:
        if not self.credentials.get("userName") or not self.credentials.get("apiKey"):
            raise ValueError("TopStepX credentials require userName and apiKey.")

    def _get_session_token(self) -> str:
        if (
            self._session_token_cache
            and self._session_token_expires_at
            and self._session_token_expires_at > datetime.utcnow()
        ):
            return self._session_token_cache

        self.validate_credentials()
        url = f"{self.base_url}/api/Auth/loginKey"
        payload = {"userName": self.credentials["userName"], "apiKey": self.credentials["apiKey"]}
        headers = {"accept": "text/plain", "Content-Type": "application/json"}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ProviderError(
                "TopStepX authentication request failed.",
                code="auth_request_failed",
                retryable=True,
            ) from exc
        except ValueError as exc:
            raise ProviderError("TopStepX authentication returned invalid JSON.", code="auth_invalid_response") from exc
        if data.get("success") and data.get("token"):
            self._session_token_cache = data["token"]
            self._session_token_expires_at = datetime.utcnow() + timedelta(minutes=20)
            return self._session_token_cache
        raise ProviderError(data.get("errorMessage") or "TopStepX authentication failed.", code="auth_failed")

    async def healthcheck(self) -> dict:
        try:
            self._get_session_token()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "ok"}

    async def diagnostics(self) -> dict:
        health = await self.healthcheck()
        return {
            "provider": self.provider.value,
            "health": health,
            "session": {
                "cached": bool(self._session_token_cache),
                "expires_at": self._session_token_expires_at.isoformat()
                if self._session_token_expires_at
                else None,
            },
            "implemented_capabilities": [cap.value for cap in self.capabilities],
        }

    async def get_contracts(self) -> list[dict]:
        token = self._get_session_token()
        url = f"{self.base_url}/api/Contract/search"
        payload = {"searchText": "", "live": False}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data.get("contracts", [])

    def get_contract_id(self, symbol: str) -> int | None:
        token = self._get_session_token()
        url = f"{self.base_url}/api/Contract/search"
        payload = {"searchText": symbol.upper(), "live": False}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if not response.ok:
            return None
        data = response.json()
        for contract in data.get("contracts", []):
            if symbol.upper() in (contract.get("name"), contract.get("description")):
                return contract.get("id")
        return None

    def _get_active_account_id(self, token: str) -> int | None:
        url = f"{self.base_url}/api/Account/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"onlyActiveAccounts": True}
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if not response.ok:
            logger.warning("TopStepX account search failed with status %s", response.status_code)
            return None
        data = response.json()
        accounts = data.get("accounts") or []
        if not accounts:
            return None
        return accounts[0].get("id")

    async def list_accounts(self) -> list[dict]:
        token = self._get_session_token()
        url = f"{self.base_url}/api/Account/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"onlyActiveAccounts": True}
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        accounts = data.get("accounts") or []
        return [
            {
                "id": account.get("id"),
                "name": account.get("name") or str(account.get("id")),
                "active": account.get("active", True),
                "raw": account,
            }
            for account in accounts
            if account.get("id") is not None
        ]

    async def get_account(self) -> dict:
        accounts = await self.list_accounts()
        if not accounts:
            raise ProviderCapabilityError("No active account available for TopStepX.")
        return accounts[0]

    async def place_order(self, order: dict) -> dict:
        symbol = order.get("symbol")
        side = order.get("side")
        quantity = order.get("quantity")
        if not symbol or not side or not quantity:
            raise ValueError("Order requires symbol, side, and quantity.")

        account_id = order.get("account_id")
        if not account_id:
            return {"success": False, "errorMessage": "Order requires a selected account_id."}

        token = self._get_session_token()
        contract_id = self.get_contract_id(symbol)
        if not contract_id:
            return {"success": False, "errorMessage": f"Could not find contract for symbol: {symbol}"}

        url = f"{self.base_url}/api/Order/place"
        payload = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": 2,
            "side": 0 if str(side).upper() == "BUY" else 1,
            "size": quantity,
            "timeInForce": "GTC",
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if not response.ok:
            try:
                payload = response.json()
            except ValueError:
                payload = {"errorMessage": response.text}
            return {
                "success": False,
                "status": response.status_code,
                "errorMessage": payload.get("errorMessage") or payload,
            }
        return response.json()

    def get_bars(
        self,
        token: str,
        contract_id: int,
        interval_minutes: int,
        start_time: str,
        end_time: str,
        limit: int,
    ) -> list[dict]:
        url = f"{self.base_url}/api/History/retrieveBars"
        payload = {
            "contractId": contract_id,
            "live": False,
            "startTime": start_time,
            "endTime": end_time,
            "unit": 2,
            "unitNumber": interval_minutes,
            "limit": limit,
            "includePartialBar": False,
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not data.get("success") or "bars" not in data:
            raise ValueError("Invalid response from TopStepX bars API.")
        return data["bars"]
