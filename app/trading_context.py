from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.providers.types import (
    IMPLEMENTED_PROVIDER_CAPABILITIES,
    IntegrationCapability,
    IntegrationProvider,
    provider_supports,
)
from app.trading_safety import LIVE_MODE, PAPER_MODE, normalize_mode


@dataclass(frozen=True)
class ReadinessBlocker:
    code: str
    message: str


@dataclass(frozen=True)
class TradingContext:
    user_id: int
    trading_mode: str
    integration: models.PlatformIntegration | None = None
    account_id: str | None = None
    symbol: str | None = None
    provider: IntegrationProvider | None = None
    required_capabilities: tuple[IntegrationCapability, ...] = field(default_factory=tuple)
    implemented_capabilities: tuple[IntegrationCapability, ...] = field(default_factory=tuple)
    blockers: tuple[ReadinessBlocker, ...] = field(default_factory=tuple)

    @property
    def integration_id(self) -> int | None:
        return self.integration.id if self.integration else None

    def readiness(self) -> dict:
        return {
            "ready": not self.blockers,
            "blockers": [
                {"code": blocker.code, "message": blocker.message}
                for blocker in self.blockers
            ],
            "trading_mode": self.trading_mode,
            "integration_id": self.integration_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "provider": self.provider.value if self.provider else None,
            "implemented_capabilities": [capability.value for capability in self.implemented_capabilities],
            "required_capabilities": [capability.value for capability in self.required_capabilities],
        }


class TradingContextError(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        blockers: Iterable[ReadinessBlocker] | None = None,
    ) -> None:
        all_blockers = list(blockers or [ReadinessBlocker(code=code, message=message)])
        super().__init__(
            status_code=status_code,
            detail=message,
            headers={"X-Readiness-Blocker": code},
        )
        self.code = code
        self.blockers = tuple(all_blockers)


def _provider_for(integration: models.PlatformIntegration) -> IntegrationProvider:
    try:
        return IntegrationProvider(integration.provider)
    except ValueError as exc:
        raise TradingContextError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_provider",
            message="Selected integration has an unsupported provider.",
        ) from exc


def _metadata_account_ids(metadata: dict | None) -> set[str]:
    metadata = metadata or {}
    account_ids: set[str] = set()
    for key in ("account_id", "accountId", "demo_account_id"):
        value = metadata.get(key)
        if value:
            account_ids.add(str(value))
    for key in ("accounts", "demo_accounts"):
        values = metadata.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and value.get("id") is not None:
                    account_ids.add(str(value["id"]))
                elif value is not None:
                    account_ids.add(str(value))
    return account_ids


def _metadata_contract_symbols(metadata: dict | None) -> set[str]:
    metadata = metadata or {}
    symbols: set[str] = set()
    values = metadata.get("contracts") or metadata.get("symbols") or []
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict):
                symbol = value.get("symbol") or value.get("name")
            else:
                symbol = value
            if symbol:
                symbols.add(str(symbol).upper())
    return symbols


class TradingContextService:
    def resolve(
        self,
        db: Session,
        *,
        user_id: int,
        trading_mode: str | None = PAPER_MODE,
        integration_id: int | None = None,
        required_provider: IntegrationProvider | None = None,
        required_capabilities: Iterable[IntegrationCapability] | None = None,
        account_id: str | None = None,
        symbol: str | None = None,
        require_integration: bool = False,
        require_account: bool = False,
        require_contract: bool = False,
        allow_paper_fallback: bool = False,
    ) -> TradingContext:
        mode = normalize_mode(trading_mode)
        required = tuple(required_capabilities or ())
        normalized_symbol = symbol.strip().upper() if symbol and symbol.strip() else None
        normalized_account = account_id.strip() if account_id and account_id.strip() else None

        if mode == LIVE_MODE:
            raise TradingContextError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="live_disabled",
                message="Live trading is disabled until live-readiness gates are complete.",
            )

        integration = self._resolve_integration(
            db,
            user_id=user_id,
            integration_id=integration_id,
            required_provider=required_provider,
            required_capabilities=required,
            require_integration=require_integration,
            allow_paper_fallback=allow_paper_fallback,
        )
        provider = _provider_for(integration) if integration else None
        implemented = (
            tuple(sorted(IMPLEMENTED_PROVIDER_CAPABILITIES.get(provider, set()), key=lambda cap: cap.value))
            if provider
            else tuple()
        )

        blockers: list[ReadinessBlocker] = []
        if require_account and not normalized_account:
            blockers.append(ReadinessBlocker("missing_account", "account_id is required."))
        if require_contract and not normalized_symbol:
            blockers.append(ReadinessBlocker("missing_contract", "symbol or contract is required."))

        if integration and normalized_account:
            allowed_accounts = _metadata_account_ids(integration.integration_metadata)
            if allowed_accounts and normalized_account not in allowed_accounts:
                blockers.append(
                    ReadinessBlocker(
                        "account_not_selected_for_integration",
                        "Selected account is not listed on the selected integration metadata.",
                    )
                )

        if integration and normalized_symbol:
            allowed_symbols = _metadata_contract_symbols(integration.integration_metadata)
            if allowed_symbols and normalized_symbol not in allowed_symbols:
                blockers.append(
                    ReadinessBlocker(
                        "contract_not_selected_for_integration",
                        "Selected contract is not listed on the selected integration metadata.",
                    )
                )

        if blockers:
            raise TradingContextError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=blockers[0].code,
                message=blockers[0].message,
                blockers=blockers,
            )

        return TradingContext(
            user_id=user_id,
            trading_mode=mode,
            integration=integration,
            account_id=normalized_account,
            symbol=normalized_symbol,
            provider=provider,
            required_capabilities=required,
            implemented_capabilities=implemented,
        )

    def _resolve_integration(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None,
        required_provider: IntegrationProvider | None,
        required_capabilities: tuple[IntegrationCapability, ...],
        require_integration: bool,
        allow_paper_fallback: bool,
    ) -> models.PlatformIntegration | None:
        candidate: models.PlatformIntegration | None = None
        if integration_id is not None:
            candidate = (
                db.query(models.PlatformIntegration)
                .filter(models.PlatformIntegration.id == integration_id)
                .filter(models.PlatformIntegration.user_id == user_id)
                .first()
            )
            if not candidate:
                raise TradingContextError(
                    status_code=status.HTTP_404_NOT_FOUND,
                    code="integration_not_found",
                    message="Integration not found for current user.",
                )
        else:
            user = db.query(models.User).filter(models.User.id == user_id).first()
            if user and user.active_integration_id:
                candidate = (
                    db.query(models.PlatformIntegration)
                    .filter(models.PlatformIntegration.id == user.active_integration_id)
                    .filter(models.PlatformIntegration.user_id == user_id)
                    .first()
                )

        if not candidate:
            if require_integration and not allow_paper_fallback:
                raise TradingContextError(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="missing_integration",
                    message="A selected integration is required.",
                )
            return None

        if candidate.status != "active":
            raise TradingContextError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="integration_inactive",
                message="Integration is not active.",
            )
        if not candidate.credentials_encrypted:
            raise TradingContextError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="missing_credentials",
                message="Integration credentials are required.",
            )

        provider = _provider_for(candidate)
        if required_provider and provider != required_provider:
            raise TradingContextError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="provider_mismatch",
                message="Selected integration does not match the required provider.",
            )
        if required_capabilities and not provider_supports(provider, set(required_capabilities), implemented_only=True):
            raise TradingContextError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="missing_provider_capability",
                message="Selected integration does not provide required implemented capabilities.",
                blockers=[
                    ReadinessBlocker(
                        "missing_provider_capability",
                        "Selected integration does not provide required implemented capabilities.",
                    )
                ],
            )
        return candidate


trading_context_service = TradingContextService()
