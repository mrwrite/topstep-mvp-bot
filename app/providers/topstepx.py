from __future__ import annotations

import os
from typing import Any
from datetime import datetime, timedelta, timezone

import requests

from .base import ProviderAdapter, ProviderCapabilityError, ProviderError
from .types import IntegrationCapability, IntegrationProvider


LOCAL_EXECUTOR_REQUIRED = "local_executor_required"


def _local_executor_required(action: str) -> ProviderCapabilityError:
    return ProviderCapabilityError(
        f"TopStepX provider {action} is disabled on hosted services; "
        "use the personal-device executor.",
        code=LOCAL_EXECUTOR_REQUIRED,
        details={"execution_origin": "personal_device"},
    )


class TopStepXAdapter(ProviderAdapter):
    provider = IntegrationProvider.TOPSTEPX
    mutation_capabilities_enabled = False
    capabilities = {
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
            and self._session_token_expires_at > datetime.now(timezone.utc)
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
        token = data.get("token")
        if data.get("success") is True and data.get("errorCode", 0) == 0 and isinstance(token, str) and token:
            self._session_token_cache = data["token"]
            # Official tokens last 24 hours; use a one-hour safety margin.
            self._session_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=23)
            return self._session_token_cache
        raise ProviderError("TopStepX authentication failed.", code="auth_failed")

    async def healthcheck(self) -> dict:
        try:
            self._get_session_token()
        except Exception:
            return {"status": "error", "message": "Provider authentication failed."}
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

    def _search_active_accounts(self, token: str) -> list[dict]:
        url = f"{self.base_url}/api/Account/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            response = requests.post(
                url, headers=headers, json={"onlyActiveAccounts": True}, timeout=20
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ProviderError(
                "TopStepX account search failed.", code="account_search_failed", retryable=True
            ) from exc
        except ValueError as exc:
            raise ProviderError(
                "TopStepX account search returned invalid JSON.", code="account_search_invalid"
            ) from exc
        if data.get("success") is not True or data.get("errorCode", 0) != 0:
            raise ProviderError("TopStepX account search failed.", code="account_search_failed")
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            raise ProviderError("TopStepX account search returned invalid data.", code="account_search_invalid")
        return accounts

    def authenticate_session(self) -> tuple[str, datetime]:
        """Authenticate without exposing the token through an HTTP response."""
        token = self._get_session_token()
        if self._session_token_expires_at is None:  # defensive: successful login always sets it
            raise ProviderError("TopStepX session expiry is unavailable.", code="auth_invalid_response")
        return token, self._session_token_expires_at

    def validate_session(self, token: str) -> tuple[str, datetime]:
        """Rotate a provider token through the documented validation endpoint.

        Callers remain responsible for durable leasing/fencing. This method holds
        the plaintext token only for the provider request and never includes it in
        exceptions or returned diagnostics.
        """
        url = f"{self.base_url}/api/Auth/validate"
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise ProviderError("TopStepX session validation timed out.", code="auth_timeout", retryable=True) from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = "auth_rate_limited" if status == 429 else "auth_provider_unavailable"
            raise ProviderError("TopStepX session validation failed.", code=code, retryable=True) from exc
        except ValueError as exc:
            raise ProviderError("TopStepX session validation returned invalid data.", code="auth_malformed_response") from exc
        new_token = data.get("newToken")
        if data.get("success") is not True or data.get("errorCode", 0) != 0 or not isinstance(new_token, str) or not new_token:
            raise ProviderError("TopStepX session validation was rejected.", code="auth_invalid_session")
        return new_token, datetime.now(timezone.utc) + timedelta(hours=23)

    def safe_accounts_for_session(self, token: str) -> list[dict]:
        accounts = self._search_active_accounts(token)
        return [
            {
                "id": str(account.get("id")),
                "name": str(account.get("name") or account.get("id")),
                "canTrade": account.get("canTrade") is True,
                "isVisible": account.get("isVisible") is True,
            }
            for account in accounts
            if account.get("id") is not None
        ]

    async def list_accounts(self) -> list[dict]:
        token = self._get_session_token()
        accounts = self._search_active_accounts(token)
        return [
            {
                "id": account.get("id"),
                "name": account.get("name") or str(account.get("id")),
                "balance": account.get("balance"),
                "canTrade": account.get("canTrade") is True,
                "isVisible": account.get("isVisible") is True,
            }
            for account in accounts
            if account.get("id") is not None
        ]

    async def get_account(self) -> dict:
        raise ProviderCapabilityError(
            "TopStepX account selection requires the durable tenant approval service."
        )

    async def place_order(self, order: dict) -> dict:
        raise _local_executor_required("order submission")

    async def cancel_order(self, provider_order_id: str) -> dict:
        raise _local_executor_required("order cancellation")

    async def modify_order(self, provider_order_id: str, order: dict) -> dict:
        raise _local_executor_required("order modification")

    async def close_position(self, account_id: str, contract_id: str) -> dict:
        raise _local_executor_required("position close")

    async def partial_close_position(
        self, account_id: str, contract_id: str, quantity: int
    ) -> dict:
        raise _local_executor_required("partial position close")

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
