from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import analytics_service, database, models
from .auth_routes import get_current_user_model
from .crypto import encrypt_credentials
from .integrations_service import set_active_integration
from .observability import log_event
from .providers.base import ProviderCapabilityError
from .providers.factory import get_adapter
from .providers.types import (
    IMPLEMENTED_PROVIDER_CAPABILITIES,
    IntegrationCapability,
    PROVIDER_CAPABILITIES,
    ROADMAP_PROVIDER_CAPABILITIES,
    provider_definition,
)
from .trading_context import TradingContextError, trading_context_service
from .authorization import TenantContext
from .tenant_repository import TenantRepository

router = APIRouter()


def _repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session"))


def _get_integration_or_404(repository: TenantRepository, integration_id: int) -> models.PlatformIntegration:
    integration = repository.get(models.PlatformIntegration, integration_id)
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
    integrations = _repository(db, current_user).list(
        models.PlatformIntegration, order_by=(models.PlatformIntegration.created_at.desc(),)
    )
    return [_to_public(integration) for integration in integrations]


@router.post(
    "/integrations",
    response_model=models.IntegrationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_integration(
    payload: models.IntegrationCreate,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    definition = provider_definition(payload.provider)
    internal_fixture = (
        database.APP_CONFIG.app_env == "test"
        and request.headers.get("X-Internal-Paper-Fixture") == "true"
    )
    if not definition.enabled and not internal_fixture:
        raise HTTPException(status_code=422, detail=definition.summary)
    if payload.credentials and not definition.accepts_credentials and not internal_fixture:
        raise HTTPException(status_code=422, detail="This provider does not accept credentials.")
    integration = models.PlatformIntegration(
        user_id=current_user.id,
        display_name=payload.display_name,
        provider=payload.provider.value,
        status=payload.status or "active",
        integration_metadata=payload.metadata,
        credentials_encrypted=None,
    )
    _repository(db, current_user).add(integration)
    db.flush()
    if payload.credentials:
        integration.credentials_encrypted = encrypt_credentials(
            payload.credentials, user_id=current_user.id, record_id=integration.id
        )
    analytics_service.capture_event(
        db,
        event_name="integration_created",
        user_id=current_user.id,
        metadata={"provider": integration.provider, "status": integration.status},
        source="integrations",
    )
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
    integration = _get_integration_or_404(_repository(db, current_user), current_user.active_integration_id)
    return {"active": _to_public(integration)}


@router.get("/integrations/providers")
def list_providers():
    providers = []
    for provider, capabilities in PROVIDER_CAPABILITIES.items():
        definition = provider_definition(provider)
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
                "availability": definition.availability.value,
                "enabled": definition.enabled,
                "accepts_credentials": definition.accepts_credentials,
                "live_trading_enabled": definition.live_trading_enabled,
                "summary": definition.summary,
                "evidence_reviewed_at": definition.evidence_reviewed_at,
            }
        )
    return {"providers": providers}


@router.get("/integrations/{integration_id}", response_model=models.IntegrationOut)
def get_integration(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(_repository(db, current_user), integration_id)
    return _to_public(integration)


@router.put("/integrations/{integration_id}", response_model=models.IntegrationOut)
def update_integration(
    integration_id: int,
    payload: models.IntegrationUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(_repository(db, current_user), integration_id)
    if integration.provider.lower() == "topstepx" and database.APP_CONFIG.app_env != "test":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Use the durable TopstepX lifecycle workflow.")
    definition = provider_definition(models.IntegrationProvider(integration.provider))
    if payload.display_name is not None:
        integration.display_name = payload.display_name
    if payload.status is not None:
        integration.status = payload.status
    if payload.metadata is not None:
        integration.integration_metadata = payload.metadata
    if payload.credentials is not None:
        if not definition.enabled or not definition.accepts_credentials:
            raise HTTPException(status_code=422, detail="Credentials cannot be saved for this provider.")
        integration.credentials_encrypted = encrypt_credentials(
            payload.credentials, user_id=current_user.id, record_id=integration.id
        )
    db.commit()
    db.refresh(integration)
    return _to_public(integration)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    integration = _get_integration_or_404(_repository(db, current_user), integration_id)
    if integration.provider.lower() == "topstepx" and database.APP_CONFIG.app_env != "test":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the durable TopstepX deletion workflow.",
        )
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
    candidate = _get_integration_or_404(_repository(db, current_user), integration_id)
    if candidate.provider.lower() == "topstepx" and database.APP_CONFIG.app_env != "test":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="TopstepX activation requires durable approval and eligibility.")
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
    analytics_service.capture_event(
        db,
        event_name="integration_activated",
        user_id=current_user.id,
        metadata={"provider": integration.provider},
        source="integrations",
    )
    db.commit()
    return {"active": _to_public(integration)}


@router.get("/integrations/{integration_id}/accounts")
async def list_integration_accounts(
    integration_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user_model),
):
    candidate = _get_integration_or_404(_repository(db, current_user), integration_id)
    if candidate.provider.lower() == "topstepx" and database.APP_CONFIG.app_env != "test":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Use durable TopstepX account discovery.")
    try:
        context = trading_context_service.resolve(
            db,
            user_id=current_user.id,
            trading_mode="paper",
            integration_id=integration_id,
            required_capabilities={IntegrationCapability.ACCOUNT_INFO},
            require_integration=True,
        )
    except TradingContextError as exc:
        if exc.code == "missing_provider_capability":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected integration does not provide implemented account info.",
            ) from exc
        raise
    integration = context.integration

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
    integration = _get_integration_or_404(_repository(db, current_user), integration_id)
    adapter = get_adapter(integration)
    diagnostics = await adapter.diagnostics()
    return {
        "integration_id": integration.id,
        "provider": integration.provider,
        "status": integration.status,
        "has_credentials": bool(integration.credentials_encrypted),
        "diagnostics": diagnostics,
    }
