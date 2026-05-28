from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import database, models
from .auth_routes import get_current_user_model
from .crypto import encrypt_credentials
from .integrations_service import set_active_integration
from .observability import log_event
from .providers.base import ProviderCapabilityError
from .providers.factory import get_adapter
from .providers.types import (
    IMPLEMENTED_PROVIDER_CAPABILITIES,
    PROVIDER_CAPABILITIES,
    ROADMAP_PROVIDER_CAPABILITIES,
)

router = APIRouter()


def _get_integration_or_404(db: Session, integration_id: int, user_id: int) -> models.PlatformIntegration:
    integration = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.id == integration_id)
        .filter(models.PlatformIntegration.user_id == user_id)
        .first()
    )
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")
    return integration


def _to_public(integration: models.PlatformIntegration) -> models.IntegrationOut:
    return models.IntegrationOut(
        id=integration.id,
        display_name=integration.display_name,
        provider=models.IntegrationProvider(integration.provider),
        status=integration.status,
        metadata=integration.integration_metadata,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        has_credentials=bool(integration.credentials_encrypted),
    )


@router.get("/integrations", response_model=list[models.IntegrationOut])
def list_integrations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integrations = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.user_id == current_user.id)
        .order_by(models.PlatformIntegration.created_at.desc())
        .all()
    )
    return [_to_public(integration) for integration in integrations]


@router.post(
    "/integrations",
    response_model=models.IntegrationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_integration(
    payload: models.IntegrationCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    encrypted = None
    if payload.credentials:
        encrypted = encrypt_credentials(payload.credentials)
    integration = models.PlatformIntegration(
        user_id=current_user.id,
        display_name=payload.display_name,
        provider=payload.provider.value,
        status=payload.status or "active",
        integration_metadata=payload.metadata,
        credentials_encrypted=encrypted,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return _to_public(integration)


@router.get("/integrations/active")
def get_active_integration(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    if not current_user.active_integration_id:
        return {"active": None}
    integration = _get_integration_or_404(db, current_user.active_integration_id, current_user.id)
    return {"active": _to_public(integration)}


@router.get("/integrations/providers")
def list_providers():
    providers = []
    for provider, capabilities in PROVIDER_CAPABILITIES.items():
        providers.append(
            {
                "provider": provider.value,
                "capabilities": [cap.value for cap in capabilities],
                "implemented_capabilities": [
                    cap.value for cap in IMPLEMENTED_PROVIDER_CAPABILITIES.get(provider, set())
                ],
                "roadmap_capabilities": [
                    cap.value for cap in ROADMAP_PROVIDER_CAPABILITIES.get(provider, set())
                ],
            }
        )
    return {"providers": providers}


@router.get("/integrations/{integration_id}", response_model=models.IntegrationOut)
def get_integration(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(db, integration_id, current_user.id)
    return _to_public(integration)


@router.put("/integrations/{integration_id}", response_model=models.IntegrationOut)
def update_integration(
    integration_id: int,
    payload: models.IntegrationUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(db, integration_id, current_user.id)
    if payload.display_name is not None:
        integration.display_name = payload.display_name
    if payload.status is not None:
        integration.status = payload.status
    if payload.metadata is not None:
        integration.integration_metadata = payload.metadata
    if payload.credentials is not None:
        integration.credentials_encrypted = encrypt_credentials(payload.credentials)
    db.commit()
    db.refresh(integration)
    return _to_public(integration)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(db, integration_id, current_user.id)
    if current_user.active_integration_id == integration.id:
        current_user.active_integration_id = None
    db.delete(integration)
    db.commit()
    return None


@router.put("/integrations/{integration_id}/activate")
def activate_integration(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    try:
        integration = set_active_integration(db, current_user.id, integration_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_event(
        "integration",
        "integration_activated",
        user_id=current_user.id,
        integration_id=integration.id,
        provider=integration.provider,
    )
    return {"active": _to_public(integration)}


@router.get("/integrations/{integration_id}/accounts")
async def list_integration_accounts(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(db, integration_id, current_user.id)
    if integration.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Integration is not active.")
    if not integration.credentials_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integration credentials are required to fetch accounts.",
        )

    adapter = get_adapter(integration)
    try:
        accounts = await adapter.list_accounts()
    except ProviderCapabilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        log_event(
            "integration",
            "provider_accounts_failed",
            user_id=current_user.id,
            integration_id=integration.id,
            provider=integration.provider,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to fetch accounts for {integration.provider}.",
        ) from exc

    return {
        "accounts": accounts,
        "source": integration.provider.lower(),
        "integration_id": integration.id,
    }


@router.get("/integrations/{integration_id}/diagnostics")
async def get_integration_diagnostics(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(db, integration_id, current_user.id)
    adapter = get_adapter(integration)
    diagnostics = await adapter.diagnostics()
    return {
        "integration_id": integration.id,
        "provider": integration.provider,
        "status": integration.status,
        "has_credentials": bool(integration.credentials_encrypted),
        "diagnostics": diagnostics,
    }
