from __future__ import annotations

import os
from typing import Iterable

from sqlalchemy.orm import Session

from app.crypto import decrypt_credentials as decrypt_blob
from app.models import PlatformIntegration, User
from app.providers.types import (
    IntegrationCapability,
    IntegrationProvider,
    IMPLEMENTED_PROVIDER_CAPABILITIES,
    provider_supports,
)


def get_integration_for_user(
    db: Session, user_id: int, integration_id: int | None
) -> PlatformIntegration | None:
    if integration_id is None:
        return None
    return (
        db.query(PlatformIntegration)
        .filter(PlatformIntegration.id == integration_id)
        .filter(PlatformIntegration.user_id == user_id)
        .first()
    )


def ensure_provider_compat(
    integration: PlatformIntegration,
    required_provider: IntegrationProvider | None,
    required_capabilities: Iterable[IntegrationCapability] | None,
) -> bool:
    try:
        provider = IntegrationProvider(integration.provider)
    except ValueError:
        return False
    if required_provider and provider != required_provider:
        return False
    if required_capabilities:
        if not provider_supports(provider, set(required_capabilities), implemented_only=True):
            return False
    return True


def implemented_capabilities_for_provider(provider_value: str) -> set[IntegrationCapability]:
    try:
        provider = IntegrationProvider(provider_value)
    except ValueError:
        return set()
    return IMPLEMENTED_PROVIDER_CAPABILITIES.get(provider, set())


def resolve_integration(
    db: Session,
    user_id: int,
    *,
    integration_id: int | None = None,
    required_provider: IntegrationProvider | None = None,
    required_capabilities: Iterable[IntegrationCapability] | None = None,
) -> PlatformIntegration | None:
    if integration_id is not None:
        candidate = get_integration_for_user(db, user_id, integration_id)
        if not candidate:
            return None
        if candidate.status != "active":
            return None
        if not candidate.credentials_encrypted:
            return None
        if not ensure_provider_compat(candidate, required_provider, required_capabilities):
            return None
        return candidate

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    if user.active_integration_id:
        active = get_integration_for_user(db, user_id, user.active_integration_id)
        if (
            active
            and active.status == "active"
            and active.credentials_encrypted
            and ensure_provider_compat(active, required_provider, required_capabilities)
        ):
            return active

    return None


def decrypt_credentials(integration: PlatformIntegration) -> dict:
    if not integration.credentials_encrypted:
        return {}
    return decrypt_blob(
        integration.credentials_encrypted,
        user_id=integration.user_id,
        record_id=integration.id,
    )


def normalize_credentials(
    provider: IntegrationProvider,
    creds: dict,
    metadata: dict | None,
) -> dict:
    normalized = dict(creds or {})
    metadata = metadata or {}

    if provider == IntegrationProvider.TOPSTEPX:
        if "userName" not in normalized and "username" in normalized:
            normalized["userName"] = normalized["username"]
        if "userName" not in normalized and "apiSecret" in normalized:
            normalized["userName"] = normalized["apiSecret"]
        if "apiKey" not in normalized and "api_key" in normalized:
            normalized["apiKey"] = normalized["api_key"]
        if "baseUrl" not in normalized and metadata.get("baseUrl"):
            normalized["baseUrl"] = metadata.get("baseUrl")
    if provider == IntegrationProvider.TRADINGVIEW:
        if "webhookSecret" not in normalized and "secret" in normalized:
            normalized["webhookSecret"] = normalized["secret"]
    return normalized


def set_active_integration(
    db: Session, user_id: int, integration_id: int
) -> PlatformIntegration:
    integration = get_integration_for_user(db, user_id, integration_id)
    if not integration:
        raise ValueError("Integration not found.")
    if integration.status != "active":
        raise ValueError("Integration must be active to be selected.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found.")
    user.active_integration_id = integration.id
    db.commit()
    db.refresh(integration)
    return integration


def env_fallback_enabled() -> bool:
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()
    if environment not in {"development", "test", "demo"}:
        return False
    return os.getenv("ALLOW_ENV_BROKER_FALLBACK", "false").lower() == "true"


def env_topstepx_credentials() -> dict | None:
    user_name = os.getenv("TOPSTEP_USER")
    api_key = os.getenv("TOPSTEP_API_KEY")
    if not user_name or not api_key:
        return None
    return {"userName": user_name, "apiKey": api_key, "baseUrl": os.getenv("TOPSTEP_BASE_URL")}
