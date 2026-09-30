from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import database, models, topstep_onboarding as workflow
from .authorization import OperatorContext, TenantContext, require_operator_user, tenant_context
from .tenant_repository import TenantRepository
from .topstep_session_security import security_epoch_status

router = APIRouter()


class CredentialInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=8, max_length=2048)
    expected_lifecycle_version: int | None = None


class AttestationInput(BaseModel):
    integration_id: int
    provider_account_id: str = Field(min_length=1, max_length=128)
    accepted: bool
    attestation_version: str
    expected_lifecycle_version: int | None = None


class ApprovalInput(BaseModel):
    integration_id: int
    provider_account_id: str = Field(min_length=1, max_length=128)
    attestation_id: str
    expires_at: datetime
    cohort: str = Field(min_length=1, max_length=64)
    expected_lifecycle_version: int | None = None


class RevocationInput(BaseModel):
    integration_id: int
    classification: str = Field(min_length=3, max_length=64)
    expected_lifecycle_version: int | None = None


def _fail(exc: workflow.TopstepWorkflowError):
    code = 404 if exc.code in {"integration_not_found", "discovered_account_not_found"} else 409
    raise HTTPException(status_code=code, detail=exc.code) from exc


def _status(db: Session, tenant: TenantContext):
    repo = TenantRepository(db, tenant)
    rows = repo.list(models.PlatformIntegration, models.PlatformIntegration.provider == workflow.PROVIDER,
                     order_by=(models.PlatformIntegration.created_at.desc(),))
    integration = next((row for row in rows if row.status != "deleted"), None)
    if integration is None:
        return {"connection_state": "deleted" if rows else "not_connected", "approval_state": "none",
                "can_reconnect": True}
    credential = repo.first(models.TopstepCredential, models.TopstepCredential.integration_id == integration.id,
                            models.TopstepCredential.is_current == 1)
    approval = repo.first(models.TopstepAccountApproval, models.TopstepAccountApproval.integration_id == integration.id,
                          models.TopstepAccountApproval.state == "approved",
                          models.TopstepAccountApproval.revoked_at.is_(None))
    account = repo.get(models.TopstepDiscoveredAccount, approval.discovered_account_id) if approval else None
    provider_session = repo.first(
        models.TopstepProviderSession,
        models.TopstepProviderSession.integration_id == integration.id,
        models.TopstepProviderSession.credential_generation == credential.credential_generation
        if credential else models.TopstepProviderSession.id == -1,
    )
    epoch = security_epoch_status(db)
    return {"integration_id": integration.id, "connection_state": integration.status,
            "lifecycle_version": integration.lifecycle_version,
            "last_validated_at": credential.validated_at if credential else None,
            "credentials_require_replacement": credential is None or bool(credential.failure_classification),
            "approval_state": approval.state if approval else "none",
            "approved_account_label": account.safe_display_label if account else None,
            "approval_expiration": approval.expires_at if approval else None,
            "degraded_reason": credential.failure_classification if credential else None,
            "revocation_or_deletion_pending": integration.status in {"revoking", "deleting"},
            "session_state": provider_session.state if provider_session else "absent",
            "session_expires_at": provider_session.expires_at if provider_session else None,
            "session_renewal_state": provider_session.state if provider_session else "absent",
            "last_session_validation_at": provider_session.last_validated_at if provider_session else None,
            "reauthentication_required": bool(provider_session and provider_session.state in {"expired", "failed"}),
            "security_epoch": epoch.environment_epoch,
            "restore_reconciliation_required": not epoch.ready,
            "restore_reconciliation_state": epoch.state}


@router.post("/integrations/topstepx/connect", status_code=201)
def connect(payload: CredentialInput, db: Session = Depends(database.get_db),
            tenant: TenantContext = Depends(tenant_context),
            idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key")):
    try:
        integration = workflow.connect(db, tenant, username=payload.username, api_key=payload.api_key,
                                       idempotency_key=idempotency_key)
        found = workflow.accounts(db, tenant, integration.id)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return {"integration_id": integration.id, "connection_state": integration.status,
            "accounts": [{"provider_account_id": x.provider_account_id, "display_label": x.safe_display_label,
                           "can_trade": bool(x.can_trade), "is_visible": bool(x.is_visible)} for x in found]}


@router.get("/integrations/topstepx/status")
def connection_status(db: Session = Depends(database.get_db), tenant: TenantContext = Depends(tenant_context)):
    return _status(db, tenant)


@router.get("/integrations/topstepx/accounts")
def discovered_accounts(integration_id: int, db: Session = Depends(database.get_db),
                        tenant: TenantContext = Depends(tenant_context)):
    try:
        found = workflow.accounts(db, tenant, integration_id)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return {"accounts": [{"provider_account_id": x.provider_account_id, "display_label": x.safe_display_label,
                           "can_trade": bool(x.can_trade), "is_visible": bool(x.is_visible)} for x in found]}


@router.post("/integrations/topstepx/attest")
def attest(payload: AttestationInput, db: Session = Depends(database.get_db),
           tenant: TenantContext = Depends(tenant_context)):
    try:
        row = workflow.attest(db, tenant, integration_id=payload.integration_id,
                              provider_account_id=payload.provider_account_id, accepted=payload.accepted,
                              attestation_version=payload.attestation_version,
                              expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return {"attestation_id": row.id, "attestation_version": row.attestation_version,
            "state": "awaiting_administrator_approval", "expires_at": row.expires_at}


@router.put("/integrations/topstepx/credentials")
def replace(integration_id: int, payload: CredentialInput, db: Session = Depends(database.get_db),
            tenant: TenantContext = Depends(tenant_context)):
    try:
        integration = workflow.replace_credentials(db, tenant, integration_id=integration_id,
                                                   username=payload.username, api_key=payload.api_key,
                                                   expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return {"integration_id": integration.id, "connection_state": integration.status, "approval_state": "none"}


@router.post("/integrations/topstepx/disconnect", status_code=204)
def disconnect(integration_id: int, expected_lifecycle_version: int | None = None,
               db: Session = Depends(database.get_db),
               tenant: TenantContext = Depends(tenant_context)):
    try:
        workflow.disconnect(db, tenant, integration_id=integration_id, expected_version=expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return Response(status_code=204)


@router.delete("/integrations/topstepx", status_code=204)
def delete(integration_id: int, expected_lifecycle_version: int | None = None,
           db: Session = Depends(database.get_db),
           tenant: TenantContext = Depends(tenant_context)):
    try:
        workflow.delete(db, tenant, integration_id=integration_id, expected_version=expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return Response(status_code=204)


@router.post("/operator/topstepx/{user_id}/approval")
def approve(user_id: int, payload: ApprovalInput, _admin: models.User = Depends(require_operator_user),
            db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    if not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id:
        raise HTTPException(status_code=404, detail="Target not found")
    try:
        row = workflow.approve(db, operator, integration_id=payload.integration_id,
                               provider_account_id=payload.provider_account_id,
                               attestation_id=payload.attestation_id, expires_at=payload.expires_at,
                               cohort=payload.cohort, expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return {"approval_id": row.id, "state": row.state, "expires_at": row.expires_at}


@router.post("/operator/topstepx/{user_id}/revoke", status_code=204)
def revoke(user_id: int, payload: RevocationInput, _admin: models.User = Depends(require_operator_user),
           db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    if not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id:
        raise HTTPException(status_code=404, detail="Target not found")
    try:
        workflow.revoke(db, operator, integration_id=payload.integration_id,
                        classification=payload.classification,
                        expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return Response(status_code=204)


@router.post("/operator/topstepx/{user_id}/deny", status_code=204)
def deny(user_id: int, payload: RevocationInput, _admin: models.User = Depends(require_operator_user),
         db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    if not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id:
        raise HTTPException(status_code=404, detail="Target not found")
    try:
        workflow.deny_or_suspend(db, operator, integration_id=payload.integration_id,
            classification=payload.classification, action="account_approval_denied",
            expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return Response(status_code=204)


@router.post("/operator/topstepx/{user_id}/suspend", status_code=204)
def emergency_suspend(user_id: int, payload: RevocationInput,
                      _admin: models.User = Depends(require_operator_user),
                      db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    if not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id:
        raise HTTPException(status_code=404, detail="Target not found")
    try:
        workflow.deny_or_suspend(db, operator, integration_id=payload.integration_id,
            classification=payload.classification, action="integration_emergency_suspended",
            expected_version=payload.expected_lifecycle_version)
    except workflow.TopstepWorkflowError as exc:
        _fail(exc)
    return Response(status_code=204)


@router.get("/operator/topstepx/{user_id}/status")
def operator_status(user_id: int, _admin: models.User = Depends(require_operator_user),
                    db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    tenant = db.info.get("tenant_context")
    if (not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id
            or not isinstance(tenant, TenantContext)):
        raise HTTPException(status_code=404, detail="Target not found")
    return _status(db, tenant)
