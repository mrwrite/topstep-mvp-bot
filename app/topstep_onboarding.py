from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from . import models
from .authorization import OperatorContext, TenantContext
from .crypto import active_encryption_key_version, encrypt_protected_value, protected_context
from .providers.topstepx import TopStepXAdapter
from .risk_service import risk_service
from .tenant_repository import TenantRepository
from .time_utils import as_utc, utc_now
from .topstep_session_security import (
    TopstepSessionError,
    bootstrap_security_epoch,
    require_current_epoch,
)


PROVIDER = "topstepx"
ATTESTATION_VERSION = "topstep-combine-v1"
ATTESTATION_TEXT = (
    "I attest that this account is a Topstep Trading Combine, not an Express Funded "
    "Account or Live Funded Account; automated actions can affect evaluation results, "
    "and I authorize this application to act only within configured limits."
)
TERMINAL_STATES = frozenset({"deleted"})
NON_EXECUTABLE_STATES = frozenset({"suspended", "replacing", "revoking", "revoked", "deleting", "deleted", "failed"})
ALLOWED_TRANSITIONS = {
    "pending_validation": {"validated", "failed", "deleting"},
    "validated": {"account_discovered", "suspended", "replacing", "deleting"},
    "account_discovered": {"awaiting_attestation", "replacing", "deleting"},
    "awaiting_attestation": {"awaiting_approval", "replacing", "deleting"},
    "awaiting_approval": {"approved", "suspended", "replacing", "revoking", "deleting"},
    "approved": {"suspended", "replacing", "revoking", "deleting"},
    "suspended": {"replacing", "revoking", "deleting"},
    "replacing": {"awaiting_attestation", "suspended", "deleting"},
    "revoking": {"revoked", "deleting"},
    "revoked": {"awaiting_approval", "replacing", "deleting"},
    "deleting": {"deleted"},
    "failed": {"replacing", "deleting"},
    "deleted": set(),
}


class TopstepWorkflowError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EligibilityDecision:
    allowed: bool
    reason: str
    integration_id: int | None = None
    provider_account_id: str | None = None
    credential_generation: int | None = None


def _fingerprint_key() -> bytes:
    raw = os.getenv("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY", "")
    if raw:
        try:
            value = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception as exc:
            raise TopstepWorkflowError("fingerprint_key_invalid") from exc
        if len(value) < 32:
            raise TopstepWorkflowError("fingerprint_key_invalid")
        return value
    if os.getenv("DEPLOYMENT_PROFILE", "").lower() == "hosted_topstep_combine_beta":
        raise TopstepWorkflowError("fingerprint_key_missing")
    secret = os.getenv("SECRET_KEY", "development-only-fingerprint-key")
    return hashlib.sha256(("topstep-fingerprint:" + secret).encode()).digest()


def _fingerprint(api_key: str) -> str:
    return hmac.new(_fingerprint_key(), api_key.encode(), hashlib.sha256).hexdigest()


def _context(user_id: int, integration_id: int, generation: int, field: str):
    return protected_context(
        user_id=user_id,
        purpose=f"topstep-{field}",
        record_type="topstep-credential",
        record_id=f"{integration_id}:g{generation}:{field}",
    )


def _audit(repo: TenantRepository, tenant: TenantContext, action: str, outcome: str, **metadata) -> None:
    repo.add_security_event(models.SecurityAuditEvent(
        actor_user_id=tenant.actor_id,
        target_user_id=tenant.user_id,
        event_type="topstep_integration_lifecycle",
        action=action,
        outcome=outcome,
        event_metadata={"correlation_id": tenant.correlation_id, **metadata},
    ))


def _transition(integration: models.PlatformIntegration, target: str) -> None:
    current = integration.status
    if current in TERMINAL_STATES or target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise TopstepWorkflowError("invalid_lifecycle_transition")
    integration.status = target
    integration.lifecycle_version += 1


def _assert_version(integration: models.PlatformIntegration, expected_version: int | None) -> None:
    if expected_version is not None and integration.lifecycle_version != expected_version:
        raise TopstepWorkflowError("stale_lifecycle_version")


def _integration(repo: TenantRepository, integration_id: int | None = None, *, lock: bool = False):
    criteria = [models.PlatformIntegration.provider == PROVIDER]
    if integration_id is not None:
        criteria.append(models.PlatformIntegration.id == integration_id)
    row = repo.first(models.PlatformIntegration, *criteria, lock=lock)
    if row is None:
        raise TopstepWorkflowError("integration_not_found")
    return row


def _current_credential(repo: TenantRepository, integration_id: int, *, lock: bool = False):
    row = repo.first(
        models.TopstepCredential,
        models.TopstepCredential.integration_id == integration_id,
        models.TopstepCredential.is_current == 1,
        lock=lock,
    )
    if row is None or row.deleted_at is not None or not row.api_key_encrypted:
        raise TopstepWorkflowError("credential_unavailable")
    return row


def _provider_result(username: str, api_key: str, provider_factory: Callable | None = None):
    adapter = (provider_factory or TopStepXAdapter)({"userName": username, "apiKey": api_key})
    token, expires_at = adapter.authenticate_session()
    accounts = adapter.safe_accounts_for_session(token)
    return token, expires_at, accounts


def _persist_generation(
    repo: TenantRepository,
    integration: models.PlatformIntegration,
    *,
    username: str,
    api_key: str,
    generation: int,
    token: str,
    token_expires_at,
    accounts: list[dict],
    correlation_id: str,
) -> tuple[models.TopstepCredential, models.TopstepDiscoverySnapshot]:
    now = utc_now()
    epoch = integration.security_epoch
    credential = repo.add(models.TopstepCredential(
        user_id=repo.tenant.user_id,
        integration_id=integration.id,
        lifecycle_status="validated",
        credential_fingerprint=_fingerprint(api_key),
        encryption_key_version=active_encryption_key_version(),
        credential_generation=generation,
        security_epoch=epoch,
        validated_at=now,
        last_auth_succeeded_at=now,
    ))
    repo.flush()
    credential.username_encrypted = encrypt_protected_value(
        username, context=_context(repo.tenant.user_id, integration.id, generation, "username")
    )
    credential.api_key_encrypted = encrypt_protected_value(
        api_key, context=_context(repo.tenant.user_id, integration.id, generation, "api-key")
    )
    repo.add(models.TopstepProviderSession(
        user_id=repo.tenant.user_id,
        integration_id=integration.id,
        credential_id=credential.id,
        credential_generation=generation,
        security_epoch=epoch,
        state="valid",
        session_generation=1,
        token_encrypted=encrypt_protected_value(
            token, context=_context(repo.tenant.user_id, integration.id, generation, "session")
        ),
        issued_at=now,
        expires_at=token_expires_at,
        renewal_not_before=max(now, as_utc(token_expires_at) - timedelta(
            minutes=int(os.getenv("TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES", "120"))
        )),
        last_validated_at=now,
    ))
    safe_accounts = sorted(
        ({"id": str(a["id"]), "name": str(a["name"])[:128], "canTrade": bool(a["canTrade"]), "isVisible": bool(a["isVisible"])} for a in accounts),
        key=lambda value: value["id"],
    )
    snapshot = repo.add(models.TopstepDiscoverySnapshot(
        id=str(uuid4()), user_id=repo.tenant.user_id, integration_id=integration.id,
        credential_id=credential.id, credential_generation=generation,
        security_epoch=epoch,
        provider_correlation_id=correlation_id, discovered_at=now,
        expires_at=now + timedelta(hours=1),
        safe_response_hash=hashlib.sha256(json.dumps(safe_accounts, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        provider_status="success",
    ))
    for account in safe_accounts:
        repo.add(models.TopstepDiscoveredAccount(
            user_id=repo.tenant.user_id, integration_id=integration.id,
            snapshot_id=snapshot.id, provider_account_id=account["id"],
            safe_display_label=account["name"], can_trade=int(account["canTrade"]),
            is_visible=int(account["isVisible"]), is_active=1,
            first_observed_at=now, last_observed_at=now,
        ))
    return credential, snapshot


def connect(db: Session, tenant: TenantContext, *, username: str, api_key: str,
            provider_factory: Callable | None = None, idempotency_key: str | None = None) -> models.PlatformIntegration:
    approved_tester = os.getenv("TOPSTEP_APPROVED_TESTER_USER_ID")
    if os.getenv("DEPLOYMENT_PROFILE", "").lower() == "hosted_topstep_combine_beta" and (
        not approved_tester or int(approved_tester) != tenant.user_id
    ):
        raise TopstepWorkflowError("tester_not_in_approved_cohort")
    epoch = bootstrap_security_epoch(db)
    repo = TenantRepository(db, tenant)
    request_key = idempotency_key or tenant.correlation_id
    request_identity = hashlib.sha256(f"topstep-connect:{tenant.user_id}:{request_key}".encode()).hexdigest()
    try:
        repo.lock_tenant_owner()
        prior_request = repo.first(
            models.PlatformIntegration,
            models.PlatformIntegration.provider == PROVIDER,
            models.PlatformIntegration.onboarding_request_identity == request_identity,
            lock=True,
        )
        if prior_request is not None:
            if prior_request.status == "deleted":
                raise TopstepWorkflowError("deleted_integration_terminal")
            return prior_request
        existing = repo.first(
            models.PlatformIntegration,
            models.PlatformIntegration.provider == PROVIDER,
            models.PlatformIntegration.status != "deleted",
            lock=True,
        )
        if existing is not None:
            raise TopstepWorkflowError("integration_already_exists")
    except Exception:
        db.rollback()
        raise
    try:
        token, expires_at, accounts = _provider_result(username, api_key, provider_factory)
        integration = repo.add(models.PlatformIntegration(
            user_id=tenant.user_id, display_name="TopstepX Trading Combine",
            provider=PROVIDER, status="pending_validation",
            security_epoch=epoch,
            onboarding_request_identity=request_identity,
            integration_metadata={"credential_generation": 1, "account_classification": "user_attested_only"},
        ))
        repo.flush()
        _transition(integration, "validated")
        _persist_generation(repo, integration, username=username, api_key=api_key, generation=1,
                            token=token, token_expires_at=expires_at, accounts=accounts,
                            correlation_id=tenant.correlation_id)
        _transition(integration, "account_discovered")
        _transition(integration, "awaiting_attestation")
        _audit(repo, tenant, "onboarding_completed", "success", integration_id=integration.id,
               credential_generation=1, account_count=len(accounts))
        db.commit()
        db.refresh(integration)
        return integration
    except Exception:
        db.rollback()
        raise


def accounts(db: Session, tenant: TenantContext, integration_id: int | None = None) -> list[models.TopstepDiscoveredAccount]:
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id)
    credential = _current_credential(repo, integration.id)
    snapshot = repo.first(
        models.TopstepDiscoverySnapshot,
        models.TopstepDiscoverySnapshot.integration_id == integration.id,
        models.TopstepDiscoverySnapshot.credential_generation == credential.credential_generation,
        models.TopstepDiscoverySnapshot.is_current == 1,
    )
    if snapshot is None or as_utc(snapshot.expires_at) <= utc_now():
        return []
    return repo.list(models.TopstepDiscoveredAccount, models.TopstepDiscoveredAccount.snapshot_id == snapshot.id,
                     order_by=(models.TopstepDiscoveredAccount.provider_account_id,))


def attest(db: Session, tenant: TenantContext, *, integration_id: int, provider_account_id: str,
           accepted: bool, attestation_version: str, expected_version: int | None = None) -> models.TopstepCombineAttestation:
    if not accepted or attestation_version != ATTESTATION_VERSION:
        raise TopstepWorkflowError("attestation_required")
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id, lock=True)
    _assert_version(integration, expected_version)
    credential = _current_credential(repo, integration.id)
    eligible = accounts(db, tenant, integration.id)
    account = next((row for row in eligible if row.provider_account_id == str(provider_account_id)
                    and row.can_trade == 1 and row.is_visible == 1 and row.is_active == 1), None)
    if account is None:
        raise TopstepWorkflowError("discovered_account_not_found")
    now = utc_now()
    row = repo.add(models.TopstepCombineAttestation(
        id=str(uuid4()), user_id=tenant.user_id, integration_id=integration.id,
        discovered_account_id=account.id, credential_generation=credential.credential_generation,
        security_epoch=integration.security_epoch,
        provider_account_id=account.provider_account_id, attestation_version=ATTESTATION_VERSION,
        attestation_text=ATTESTATION_TEXT, accepted_at=now, expires_at=now + timedelta(days=7),
        correlation_id=tenant.correlation_id,
    ))
    _transition(integration, "awaiting_approval")
    _audit(repo, tenant, "combine_attestation_accepted", "success", integration_id=integration.id,
           credential_generation=credential.credential_generation, attestation_id=row.id)
    db.commit()
    return row


def approve(db: Session, operator: OperatorContext, *, integration_id: int, provider_account_id: str,
            attestation_id: str, expires_at, cohort: str, expected_version: int | None = None) -> models.TopstepAccountApproval:
    configured_cohort = os.getenv("TOPSTEP_BETA_COHORT_ID")
    if configured_cohort and cohort != configured_cohort:
        raise TopstepWorkflowError("cohort_mismatch")
    tenant = operator.tenant_context(f"tenant-{operator.target_tenant_id}")
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id, lock=True)
    _assert_version(integration, expected_version)
    if integration.status not in {"awaiting_approval", "revoked"}:
        raise TopstepWorkflowError("integration_not_approvable")
    credential = _current_credential(repo, integration.id)
    attestation = repo.get(models.TopstepCombineAttestation, attestation_id, lock=True)
    now = utc_now()
    if (attestation is None or attestation.integration_id != integration.id
            or attestation.credential_generation != credential.credential_generation
            or attestation.provider_account_id != str(provider_account_id)
            or attestation.revoked_at is not None or as_utc(attestation.expires_at) <= now):
        raise TopstepWorkflowError("attestation_not_current")
    account = repo.get(models.TopstepDiscoveredAccount, attestation.discovered_account_id)
    if account is None or account.provider_account_id != str(provider_account_id):
        raise TopstepWorkflowError("discovery_evidence_mismatch")
    current = repo.first(models.TopstepAccountApproval,
                         models.TopstepAccountApproval.integration_id == integration.id,
                         models.TopstepAccountApproval.state == "approved",
                         models.TopstepAccountApproval.revoked_at.is_(None), lock=True)
    if current is not None:
        if current.provider_account_id == str(provider_account_id) and current.attestation_id == attestation.id:
            return current
        raise TopstepWorkflowError("active_approval_exists")
    if as_utc(expires_at) <= now:
        raise TopstepWorkflowError("approval_expired")
    row = repo.add(models.TopstepAccountApproval(
        id=str(uuid4()), user_id=tenant.user_id, integration_id=integration.id,
        discovered_account_id=account.id, attestation_id=attestation.id,
        credential_generation=credential.credential_generation, provider_account_id=account.provider_account_id,
        security_epoch=integration.security_epoch,
        cohort=cohort, approving_operator_id=operator.actor_user_id,
        operator_context={"action": operator.action, "expires_at": operator.expires_at.isoformat()},
        purpose=operator.purpose, case_reference=operator.case_id, approved_at=now,
        expires_at=expires_at, correlation_id=operator.correlation_id,
    ))
    if integration.status == "revoked":
        _transition(integration, "awaiting_approval")
    _transition(integration, "approved")
    _audit(repo, tenant, "account_approval_granted", "success", integration_id=integration.id,
           credential_generation=credential.credential_generation, approval_id=row.id)
    db.commit()
    return row


def _invalidate_authorization(repo: TenantRepository, integration, classification: str, *, operator_id: int | None = None) -> None:
    now = utc_now()
    for session in repo.list(models.TopstepProviderSession,
                             models.TopstepProviderSession.integration_id == integration.id,
                             models.TopstepProviderSession.revoked_at.is_(None)):
        session.revoked_at = now
        session.token_encrypted = None
        session.state = "deleted" if classification == "integration_deleted" else "revoked"
        session.deleted_at = now if classification == "integration_deleted" else session.deleted_at
        session.renewal_lease_owner = None
        session.renewal_lease_expires_at = None
        session.fencing_token += 1
        session.lifecycle_version += 1
        session.version += 1
    for snapshot in repo.list(models.TopstepDiscoverySnapshot,
                              models.TopstepDiscoverySnapshot.integration_id == integration.id,
                              models.TopstepDiscoverySnapshot.is_current == 1):
        snapshot.is_current = 0
    for attestation in repo.list(models.TopstepCombineAttestation,
                                 models.TopstepCombineAttestation.integration_id == integration.id,
                                 models.TopstepCombineAttestation.revoked_at.is_(None)):
        attestation.revoked_at = now
        attestation.revocation_classification = classification
    for approval in repo.list(models.TopstepAccountApproval,
                              models.TopstepAccountApproval.integration_id == integration.id,
                              models.TopstepAccountApproval.revoked_at.is_(None)):
        approval.state = "revoked"
        approval.revoked_at = now
        approval.revoking_operator_id = operator_id
        approval.revocation_classification = classification
        approval.version += 1


def replace_credentials(db: Session, tenant: TenantContext, *, integration_id: int,
                        username: str, api_key: str, provider_factory: Callable | None = None,
                        expected_version: int | None = None,
                        failure_injector: Callable[[str], None] | None = None):
    repo = TenantRepository(db, tenant)
    candidate = _integration(repo, integration_id)
    require_current_epoch(db, candidate.security_epoch)
    token, expires_at, discovered = _provider_result(username, api_key, provider_factory)
    try:
        integration = _integration(repo, integration_id, lock=True)
        require_current_epoch(db, integration.security_epoch)
        _assert_version(integration, expected_version)
        old = _current_credential(repo, integration.id, lock=True)
        if integration.status in {"deleting", "deleted"}:
            raise TopstepWorkflowError("deleted_integration_terminal")
        _transition(integration, "replacing")
        if failure_injector:
            failure_injector("during_replacement")
        now = utc_now()
        _invalidate_authorization(repo, integration, "credential_replaced")
        old.is_current = 0
        old.lifecycle_status = "replaced"
        old.replaced_at = now
        old.version += 1
        generation = old.credential_generation + 1
        _persist_generation(repo, integration, username=username, api_key=api_key, generation=generation,
                            token=token, token_expires_at=expires_at, accounts=discovered,
                            correlation_id=tenant.correlation_id)
        integration.integration_metadata = {"credential_generation": generation, "account_classification": "user_attested_only"}
        _transition(integration, "awaiting_attestation")
        _suppress_execution(repo, integration, "credential_replaced")
        _audit(repo, tenant, "credentials_replaced", "success", integration_id=integration.id,
               credential_generation=generation)
        db.commit()
        return integration
    except Exception:
        db.rollback()
        raise


def execution_eligibility(db: Session, tenant: TenantContext, *, integration_id: int,
                          provider_account_id: str) -> EligibilityDecision:
    repo = TenantRepository(db, tenant)
    try:
        integration = _integration(repo, integration_id)
        credential = _current_credential(repo, integration.id)
    except TopstepWorkflowError as exc:
        return EligibilityDecision(False, exc.code)
    try:
        epoch = require_current_epoch(db, integration.security_epoch)
    except TopstepSessionError as exc:
        return EligibilityDecision(False, exc.code, integration.id)
    if integration.status != "approved":
        return EligibilityDecision(False, "integration_not_approved", integration.id)
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"}:
        return EligibilityDecision(False, "live_trading_configuration_forbidden", integration.id)
    user = repo.tenant_user()
    beta = repo.first(models.UserBetaStatus, models.UserBetaStatus.status == "active")
    if user is None or user.account_status != "active" or beta is None:
        return EligibilityDecision(False, "tester_membership_inactive", integration.id)
    configured_tester = os.getenv("TOPSTEP_APPROVED_TESTER_USER_ID")
    if configured_tester and str(tenant.user_id) != configured_tester:
        return EligibilityDecision(False, "tester_not_in_approved_cohort", integration.id)
    now = utc_now()
    session = repo.first(models.TopstepProviderSession,
                         models.TopstepProviderSession.integration_id == integration.id,
                         models.TopstepProviderSession.credential_generation == credential.credential_generation,
                         models.TopstepProviderSession.revoked_at.is_(None))
    snapshot = repo.first(models.TopstepDiscoverySnapshot,
                          models.TopstepDiscoverySnapshot.integration_id == integration.id,
                          models.TopstepDiscoverySnapshot.credential_generation == credential.credential_generation,
                          models.TopstepDiscoverySnapshot.is_current == 1)
    attestation = repo.first(models.TopstepCombineAttestation,
                             models.TopstepCombineAttestation.integration_id == integration.id,
                             models.TopstepCombineAttestation.credential_generation == credential.credential_generation,
                             models.TopstepCombineAttestation.provider_account_id == str(provider_account_id),
                             models.TopstepCombineAttestation.revoked_at.is_(None))
    approval = repo.first(models.TopstepAccountApproval,
                          models.TopstepAccountApproval.integration_id == integration.id,
                          models.TopstepAccountApproval.credential_generation == credential.credential_generation,
                          models.TopstepAccountApproval.provider_account_id == str(provider_account_id),
                          models.TopstepAccountApproval.state == "approved",
                          models.TopstepAccountApproval.revoked_at.is_(None))
    checks = (
        (session is not None and session.security_epoch == epoch and session.state == "valid"
         and session.token_encrypted and as_utc(session.expires_at) > now, "provider_session_unavailable"),
        (snapshot is not None and snapshot.security_epoch == epoch and as_utc(snapshot.expires_at) > now,
         "discovery_evidence_expired"),
        (attestation is not None and attestation.security_epoch == epoch and as_utc(attestation.expires_at) > now,
         "attestation_not_current"),
        (approval is not None and approval.security_epoch == epoch and as_utc(approval.expires_at) > now,
         "approval_not_current"),
        (os.getenv("TOPSTEP_BETA_COHORT_ENABLED", "false").lower() in {"1", "true", "yes"}, "cohort_disabled"),
        (risk_service.find_active_kill_switch(db, user_id=tenant.user_id, integration_id=integration.id,
                                              account_id=str(provider_account_id)) is None, "kill_switch_active"),
    )
    for passed, reason in checks:
        if not passed:
            return EligibilityDecision(False, reason, integration.id, str(provider_account_id), credential.credential_generation)
    return EligibilityDecision(True, "eligible", integration.id, str(provider_account_id), credential.credential_generation)


def _suppress_execution(repo: TenantRepository, integration, reason: str) -> None:
    now = utc_now()
    runs = repo.list(models.SimulationRun, models.SimulationRun.state.notin_(("completed", "stopped", "killed", "failed")))
    run_ids = []
    for run in runs:
        if str(run.integration_id or (run.configuration or {}).get("integration_id")) != str(integration.id):
            continue
        run.state = "killed"
        run.desired_state = "stopped"
        run.kill_requested_at = now
        run.stopped_at = now
        run.degraded_reason = reason
        run.active_scope_key = None
        run_ids.append(run.id)
    if run_ids:
        repo.update(models.SimulationCommand,
                    (models.SimulationCommand.run_id.in_(run_ids),
                     models.SimulationCommand.status.in_(("pending", "accepted", "claimed", "processing"))),
                    {"status": "cancelled", "failure_code": reason, "completed_at": now})
    dry_runs = repo.list(
        models.HostedCombineDryRun,
        models.HostedCombineDryRun.integration_id == integration.id,
        models.HostedCombineDryRun.state.in_(
            ("requested", "eligibility_checking", "market_data_loading", "evaluating", "risk_evaluating")),
        lock=True,
    )
    for dry_run in dry_runs:
        dry_run.state = "canceled"
        dry_run.result_classification = reason
        dry_run.completed_at = now
        dry_run.lease_owner = None
        dry_run.lease_expires_at = None
        dry_run.fencing_token += 1
        if dry_run.proposal_id:
            proposal = repo.get(models.HostedCombineProposal, dry_run.proposal_id, lock=True)
            if proposal:
                proposal.expires_at = now
    pending = repo.list(models.OutboxEvent, models.OutboxEvent.status.in_(("pending", "claimed")))
    for event in pending:
        payload = event.payload or {}
        if str(event.integration_id or payload.get("integration_id")) == str(integration.id) or event.aggregate_id in run_ids:
            event.status = "terminal"
            event.terminal_reason = reason
            event.claim_owner = None
            event.claim_expires_at = None


def revoke(db: Session, operator: OperatorContext, *, integration_id: int, classification: str,
           expected_version: int | None = None,
           failure_injector: Callable[[str], None] | None = None) -> None:
    tenant = operator.tenant_context(f"tenant-{operator.target_tenant_id}")
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id, lock=True)
    _assert_version(integration, expected_version)
    if integration.status == "deleted":
        return
    if integration.status != "revoked":
        if integration.status != "revoking":
            _transition(integration, "revoking")
        if failure_injector:
            failure_injector("during_revocation")
        _invalidate_authorization(repo, integration, classification, operator_id=operator.actor_user_id)
        _suppress_execution(repo, integration, classification)
        _transition(integration, "revoked")
        _audit(repo, tenant, "account_approval_revoked", "success", integration_id=integration.id,
               classification=classification)
        db.commit()


def deny_or_suspend(db: Session, operator: OperatorContext, *, integration_id: int,
                    classification: str, action: str, expected_version: int | None = None) -> None:
    if action not in {"account_approval_denied", "integration_emergency_suspended"}:
        raise TopstepWorkflowError("invalid_operator_action")
    tenant = operator.tenant_context(f"tenant-{operator.target_tenant_id}")
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id, lock=True)
    if integration.status == "deleted":
        raise TopstepWorkflowError("integration_not_found")
    _assert_version(integration, expected_version)
    if integration.status != "suspended":
        if "suspended" not in ALLOWED_TRANSITIONS.get(integration.status, set()):
            raise TopstepWorkflowError("integration_not_suspendable")
        _invalidate_authorization(repo, integration, classification, operator_id=operator.actor_user_id)
        _suppress_execution(repo, integration, classification)
        _transition(integration, "suspended")
        _audit(repo, tenant, action, "success", integration_id=integration.id,
               classification=classification, case_reference=operator.case_id)
        db.commit()


def disconnect(db: Session, tenant: TenantContext, *, integration_id: int,
               expected_version: int | None = None) -> None:
    delete(db, tenant, integration_id=integration_id, expected_version=expected_version,
           audit_action="integration_disconnected_and_deleted")


def delete(db: Session, tenant: TenantContext, *, integration_id: int,
           audit_action: str = "integration_deleted", expected_version: int | None = None,
           failure_injector: Callable[[str], None] | None = None) -> None:
    repo = TenantRepository(db, tenant)
    integration = _integration(repo, integration_id, lock=True)
    if integration.status == "deleted":
        return
    _assert_version(integration, expected_version)
    credential = repo.first(models.TopstepCredential,
                            models.TopstepCredential.integration_id == integration.id,
                            models.TopstepCredential.is_current == 1, lock=True)
    generation = credential.credential_generation if credential else 0
    if integration.status != "deleting":
        _transition(integration, "deleting")
    if failure_injector:
        failure_injector("during_deletion")
    _invalidate_authorization(repo, integration, "integration_deleted")
    _suppress_execution(repo, integration, "integration_deleted")
    now = utc_now()
    for row in repo.list(models.TopstepCredential, models.TopstepCredential.integration_id == integration.id):
        row.username_encrypted = None
        row.api_key_encrypted = None
        row.is_current = 0
        row.lifecycle_status = "deleted"
        row.revoked_at = row.revoked_at or now
        row.deleted_at = now
        row.version += 1
    for row in repo.list(models.TopstepProviderSession,
                         models.TopstepProviderSession.integration_id == integration.id):
        row.token_encrypted = None
        row.state = "deleted"
        row.revoked_at = row.revoked_at or now
        row.deleted_at = now
        row.renewal_lease_owner = None
        row.renewal_lease_expires_at = None
        row.fencing_token += 1
        row.lifecycle_version += 1
        row.version += 1
    if repo.first(models.TopstepIntegrationTombstone,
                  models.TopstepIntegrationTombstone.integration_id == integration.id) is None:
        repo.add(models.TopstepIntegrationTombstone(
            id=str(uuid4()), user_id=tenant.user_id, integration_id=integration.id,
            credential_generation=generation,
            security_epoch=integration.security_epoch,
            identity_hash=hmac.new(_fingerprint_key(), f"{tenant.user_id}:{integration.id}".encode(), hashlib.sha256).hexdigest(),
            correlation_id=tenant.correlation_id, created_at=now,
        ))
    integration.credentials_encrypted = None
    integration.integration_metadata = {"deleted": True, "credential_generation": generation}
    _transition(integration, "deleted")
    _audit(repo, tenant, audit_action, "success", integration_id=integration.id,
           credential_generation=generation, pending_work_suppressed=True)
    db.commit()
