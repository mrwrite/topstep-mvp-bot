from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import database, models
from .authorization import OperatorContext, TenantContext, require_operator_user, tenant_context
from .hosted_combine_dryrun import (
    CONSENT_TEXT, CONSENT_VERSION, HostedDryRunError, accept_consent, create_policy,
    request_dry_run, serialize_dry_run,
)
from .tenant_repository import TenantRepository

router = APIRouter()


class RiskPolicyInput(BaseModel):
    integration_id: int
    provider_account_id: str = Field(min_length=1, max_length=128)
    required_consent_version: str = Field(default=CONSENT_VERSION, min_length=1, max_length=64)
    policy: dict
    expires_at: datetime | None = None


class ConsentInput(BaseModel):
    integration_id: int
    provider_account_id: str = Field(min_length=1, max_length=128)
    policy_version: int = Field(gt=0)
    consent_version: str = Field(default=CONSENT_VERSION, max_length=64)
    accepted: bool


class DryRunInput(BaseModel):
    integration_id: int
    provider_account_id: str = Field(min_length=1, max_length=128)
    policy_version: int = Field(gt=0)


def _fail(exc: HostedDryRunError):
    code = 404 if exc.code in {"integration_not_found", "dry_run_not_found"} else 409
    raise HTTPException(status_code=code, detail={"code": exc.code}) from exc


@router.get("/integrations/topstepx/risk-policy")
def get_policy(integration_id: int, tenant: TenantContext = Depends(tenant_context),
               db: Session = Depends(database.get_db)):
    repo = TenantRepository(db, tenant)
    row = repo.first(models.HostedCombineRiskPolicy,
                     models.HostedCombineRiskPolicy.integration_id == integration_id,
                     models.HostedCombineRiskPolicy.state == "active",
                     order_by=(models.HostedCombineRiskPolicy.policy_version.desc(),))
    if row is None:
        return {"state": "missing", "dry_run_eligible": False, "provider_order_execution_enabled": False}
    return {"state": row.state, "policy_version": row.policy_version,
            "required_consent_version": row.required_consent_version,
            "allowed_strategies": row.policy.get("allowed_strategies", []),
            "allowed_instruments": row.policy.get("allowed_instruments", []),
            "max_order_quantity": row.policy.get("max_order_quantity"),
            "max_open_position": row.policy.get("max_open_position"),
            "max_orders_per_session": row.policy.get("max_orders_per_session"),
            "max_orders_per_day": row.policy.get("max_orders_per_day"),
            "max_consecutive_losses": row.policy.get("max_consecutive_losses"),
            "max_daily_realized_loss": row.policy.get("max_daily_realized_loss"),
            "max_session_loss": row.policy.get("max_session_loss"),
            "max_stale_data_seconds": row.policy.get("max_stale_data_seconds"),
            "trading_schedule": row.policy.get("schedule"),
            "cooldown_seconds": row.policy.get("cooldown_seconds"),
            "dry_run_enabled": bool(row.policy.get("dry_run_enabled")),
            "provider_order_execution_enabled": False,
            "effective_at": row.effective_at, "expires_at": row.expires_at}


@router.post("/integrations/topstepx/consent", status_code=201)
def consent(payload: ConsentInput, tenant: TenantContext = Depends(tenant_context),
            db: Session = Depends(database.get_db)):
    if not payload.accepted:
        raise HTTPException(status_code=400, detail={"code": "explicit_consent_required"})
    try:
        row = accept_consent(db, tenant, integration_id=payload.integration_id,
                             provider_account_id=payload.provider_account_id,
                             policy_version=payload.policy_version,
                             consent_version=payload.consent_version)
        db.commit()
    except HostedDryRunError as exc:
        db.rollback()
        _fail(exc)
    return {"consent_id": row.id, "consent_version": row.consent_version,
            "accepted_at": row.accepted_at, "execution_enabled": False}


@router.post("/integrations/topstepx/dry-runs", status_code=202)
def start_dry_run(payload: DryRunInput, tenant: TenantContext = Depends(tenant_context),
                  db: Session = Depends(database.get_db),
                  idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key")):
    try:
        row, duplicate = request_dry_run(
            db, tenant, integration_id=payload.integration_id,
            provider_account_id=payload.provider_account_id, policy_version=payload.policy_version,
            idempotency_key=idempotency_key,
        )
        db.commit()
    except HostedDryRunError as exc:
        db.rollback()
        _fail(exc)
    return {"dry_run": serialize_dry_run(row), "duplicate": duplicate,
            "execution": "durable_worker", "provider_order_submitted": False}


@router.get("/integrations/topstepx/dry-runs/{dry_run_id}")
def dry_run_status(dry_run_id: str, tenant: TenantContext = Depends(tenant_context),
                   db: Session = Depends(database.get_db)):
    repo = TenantRepository(db, tenant)
    row = repo.get(models.HostedCombineDryRun, dry_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Dry run not found.")
    proposal = repo.get(models.HostedCombineProposal, row.proposal_id) if row.proposal_id else None
    return serialize_dry_run(row, proposal)


@router.post("/operator/topstepx/{user_id}/risk-policy", status_code=201)
def set_policy(user_id: int, payload: RiskPolicyInput,
               _admin: models.User = Depends(require_operator_user),
               db: Session = Depends(database.get_db)):
    operator = db.info.get("operator_context")
    if not isinstance(operator, OperatorContext) or operator.target_tenant_id != user_id:
        raise HTTPException(status_code=404, detail="Target not found.")
    try:
        row = create_policy(db, operator, tenant_id=user_id, integration_id=payload.integration_id,
                            provider_account_id=payload.provider_account_id, policy=payload.policy,
                            required_consent_version=payload.required_consent_version,
                            expires_at=payload.expires_at)
        db.add(models.SecurityAuditEvent(
            actor_user_id=operator.actor_user_id, target_user_id=user_id,
            event_type="hosted_combine_risk_policy", action="policy_published", outcome="success",
            case_id=operator.case_id, reason=operator.purpose,
            event_metadata={"correlation_id": operator.correlation_id,
                            "policy_id": row.id, "policy_version": row.policy_version},
        ))
        db.commit()
    except HostedDryRunError as exc:
        db.rollback()
        _fail(exc)
    return {"policy_id": row.id, "policy_version": row.policy_version, "state": row.state,
            "provider_order_execution_enabled": False, "requires_new_consent": True}
