from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from . import models
from .authorization import OperatorContext, TenantContext
from .crypto import decrypt_protected_value, encrypt_protected_value
from .providers.base import ProviderError
from .providers.topstepx import TopStepXAdapter
from .tenant_repository import TenantRepository, system_maintenance_scope
from .time_utils import as_utc, utc_now


DISALLOWED_RENEWAL_STATES = frozenset({"suspended", "replacing", "revoking", "revoked", "deleting", "deleted", "failed"})
SESSION_TERMINAL_STATES = frozenset({"revoked", "deleted"})
SESSION_RENEWAL_STATES = frozenset({"renewing", "validating", "reauthenticating"})


class TopstepSessionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EpochStatus:
    environment_epoch: int
    database_epoch: int | None
    state: str

    @property
    def ready(self) -> bool:
        return self.database_epoch == self.environment_epoch and self.state == "ready"


def configured_security_epoch() -> int:
    raw = os.getenv("HOSTED_SECURITY_EPOCH")
    hosted = os.getenv("DEPLOYMENT_PROFILE", "").strip().lower() == "hosted_topstep_combine_beta"
    if raw is None:
        if hosted:
            raise TopstepSessionError("security_epoch_missing")
        return 1
    try:
        epoch = int(raw)
    except ValueError as exc:
        raise TopstepSessionError("security_epoch_malformed") from exc
    if epoch <= 0:
        raise TopstepSessionError("security_epoch_malformed")
    return epoch


def security_epoch_status(db: Session) -> EpochStatus:
    environment_epoch = configured_security_epoch()
    row = db.get(models.HostedSecurityEpoch, 1)
    if row is None:
        return EpochStatus(environment_epoch, None, "uninitialized")
    if environment_epoch < row.database_epoch:
        return EpochStatus(environment_epoch, row.database_epoch, "rollback_rejected")
    if environment_epoch > row.database_epoch:
        return EpochStatus(environment_epoch, row.database_epoch, "reconciliation_required")
    return EpochStatus(environment_epoch, row.database_epoch, row.reconciliation_state)


def bootstrap_security_epoch(db: Session) -> int:
    """Initialize a genuinely empty installation; never bless restored Topstep data."""
    epoch = configured_security_epoch()
    row = db.get(models.HostedSecurityEpoch, 1)
    if row is not None:
        status = security_epoch_status(db)
        if not status.ready:
            raise TopstepSessionError(status.state)
        return epoch
    with system_maintenance_scope(db, "hosted-security-epoch-bootstrap"):
        if db.query(models.PlatformIntegration).filter(models.PlatformIntegration.provider == "topstepx").first():
            raise TopstepSessionError("security_epoch_reconciliation_required")
    db.add(models.HostedSecurityEpoch(id=1, database_epoch=epoch, reconciliation_state="ready"))
    db.flush()
    return epoch


def require_current_epoch(db: Session, record_epoch: int | None = None) -> int:
    status = security_epoch_status(db)
    if not status.ready:
        raise TopstepSessionError(status.state)
    if record_epoch is not None and record_epoch != status.environment_epoch:
        raise TopstepSessionError("security_epoch_mismatch")
    return status.environment_epoch


def _context(user_id: int, integration_id: int, generation: int, field: str):
    # Delayed import avoids duplicating the canonical credential/session context contract.
    from .topstep_onboarding import _context
    return _context(user_id, integration_id, generation, field)


def _safe_failure(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return exc.code if exc.code in {
            "auth_invalid_session", "auth_invalid_credentials", "auth_provider_unavailable",
            "auth_rate_limited", "auth_timeout", "auth_malformed_response",
        } else "auth_provider_failure"
    if isinstance(exc, TopstepSessionError):
        return exc.code
    return "auth_ambiguous_failure"


def acquire_renewal_lease(
    db: Session,
    tenant: TenantContext,
    *,
    integration_id: int,
    owner_id: str,
    lease_seconds: int | None = None,
    force: bool = False,
) -> tuple[int, int]:
    repo = TenantRepository(db, tenant)
    integration = repo.first(models.PlatformIntegration, models.PlatformIntegration.id == integration_id, lock=True)
    if integration is None:
        raise TopstepSessionError("integration_not_found")
    epoch = require_current_epoch(db, integration.security_epoch)
    if integration.status in DISALLOWED_RENEWAL_STATES:
        raise TopstepSessionError("integration_not_renewable")
    credential = repo.first(
        models.TopstepCredential,
        models.TopstepCredential.integration_id == integration.id,
        models.TopstepCredential.is_current == 1,
        lock=True,
    )
    if credential is None or credential.security_epoch != epoch or not credential.api_key_encrypted:
        raise TopstepSessionError("credential_unavailable")
    session = repo.first(
        models.TopstepProviderSession,
        models.TopstepProviderSession.integration_id == integration.id,
        models.TopstepProviderSession.credential_generation == credential.credential_generation,
        lock=True,
    )
    now = utc_now()
    if session is None or session.state in SESSION_TERMINAL_STATES or session.security_epoch != epoch:
        raise TopstepSessionError("provider_session_unavailable")
    if not force and session.state == "valid" and as_utc(session.renewal_not_before) > now:
        return session.id, session.fencing_token
    if (session.state in SESSION_RENEWAL_STATES and session.renewal_lease_expires_at is not None
            and as_utc(session.renewal_lease_expires_at) > now):
        raise TopstepSessionError("renewal_in_progress")
    session.state = "renewing"
    session.renewal_lease_owner = owner_id
    session.renewal_lease_expires_at = now + timedelta(
        seconds=lease_seconds or int(os.getenv("TOPSTEP_SESSION_RENEWAL_LEASE_SECONDS", "60"))
    )
    session.fencing_token += 1
    session.attempt_count += 1
    session.lifecycle_version += 1
    fence = session.fencing_token
    db.commit()
    return session.id, fence


def _load_renewal_material(db: Session, tenant: TenantContext, session_id: int, owner_id: str, fence: int):
    repo = TenantRepository(db, tenant)
    session = repo.get(models.TopstepProviderSession, session_id, lock=True)
    now = utc_now()
    if (session is None or session.state not in SESSION_RENEWAL_STATES or session.renewal_lease_owner != owner_id
            or session.fencing_token != fence or not session.token_encrypted
            or session.renewal_lease_expires_at is None
            or as_utc(session.renewal_lease_expires_at) <= now):
        raise TopstepSessionError("stale_renewal_fence")
    integration = repo.get(models.PlatformIntegration, session.integration_id, lock=True)
    credential = repo.get(models.TopstepCredential, session.credential_id, lock=True)
    epoch = require_current_epoch(db, session.security_epoch)
    if (integration is None or credential is None or integration.status in DISALLOWED_RENEWAL_STATES
            or integration.security_epoch != epoch or credential.security_epoch != epoch
            or credential.is_current != 1 or credential.credential_generation != session.credential_generation):
        raise TopstepSessionError("renewal_generation_superseded")
    return integration, credential, session


def heartbeat_renewal_lease(db: Session, tenant: TenantContext, *, session_id: int,
                            owner_id: str, fence: int, lease_seconds: int | None = None) -> None:
    repo = TenantRepository(db, tenant)
    session = repo.get(models.TopstepProviderSession, session_id, lock=True)
    if (session is None or session.state not in SESSION_RENEWAL_STATES
            or session.renewal_lease_owner != owner_id or session.fencing_token != fence
            or session.renewal_lease_expires_at is None
            or as_utc(session.renewal_lease_expires_at) <= utc_now()):
        raise TopstepSessionError("stale_renewal_fence")
    session.renewal_lease_expires_at = utc_now() + timedelta(
        seconds=lease_seconds or int(os.getenv("TOPSTEP_SESSION_RENEWAL_LEASE_SECONDS", "60"))
    )
    session.lifecycle_version += 1
    db.commit()


def renew_session(
    db: Session,
    tenant: TenantContext,
    *,
    integration_id: int,
    owner_id: str,
    provider_factory: Callable = TopStepXAdapter,
    allow_reauthentication: bool = True,
    force: bool = False,
    failure_injector: Callable[[str], None] | None = None,
) -> models.TopstepProviderSession:
    try:
        tenant.assert_valid()
    except ValueError as exc:
        raise TopstepSessionError("trusted_tenant_required") from exc
    session_id, fence = acquire_renewal_lease(
        db, tenant, integration_id=integration_id, owner_id=owner_id, force=force
    )
    repo = TenantRepository(db, tenant)
    current = repo.get(models.TopstepProviderSession, session_id)
    if current is not None and current.state == "valid":
        return current
    try:
        if failure_injector:
            failure_injector("before_provider_validation")
        _, credential, claimed = _load_renewal_material(db, tenant, session_id, owner_id, fence)
        claimed.state = "validating"
        claimed.lifecycle_version += 1
        db.commit()
        _, credential, claimed = _load_renewal_material(db, tenant, session_id, owner_id, fence)
        token = decrypt_protected_value(
            claimed.token_encrypted,
            context=_context(tenant.user_id, integration_id, claimed.credential_generation, "session"),
        )
        adapter = provider_factory({})
        try:
            new_token, expires_at = adapter.validate_session(token)
        except ProviderError as exc:
            if not allow_reauthentication or exc.code not in {"auth_invalid_session"}:
                raise
            claimed.state = "reauthenticating"
            claimed.lifecycle_version += 1
            db.commit()
            _, credential, claimed = _load_renewal_material(db, tenant, session_id, owner_id, fence)
            username = decrypt_protected_value(
                credential.username_encrypted,
                context=_context(tenant.user_id, integration_id, credential.credential_generation, "username"),
            )
            api_key = decrypt_protected_value(
                credential.api_key_encrypted,
                context=_context(tenant.user_id, integration_id, credential.credential_generation, "api-key"),
            )
            adapter = provider_factory({"userName": username, "apiKey": api_key})
            new_token, expires_at = adapter.authenticate_session()
        if failure_injector:
            failure_injector("after_provider_response")
        encrypted = encrypt_protected_value(
            new_token,
            context=_context(tenant.user_id, integration_id, claimed.credential_generation, "session"),
        )
        if failure_injector:
            failure_injector("after_encryption")
        _, credential, claimed = _load_renewal_material(db, tenant, session_id, owner_id, fence)
        now = utc_now()
        renewal_window = timedelta(minutes=int(os.getenv("TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES", "120")))
        claimed.token_encrypted = encrypted
        claimed.issued_at = now
        claimed.expires_at = expires_at
        claimed.renewal_not_before = max(now, as_utc(expires_at) - renewal_window)
        claimed.last_validated_at = now
        claimed.session_generation += 1
        claimed.state = "valid"
        claimed.failure_classification = None
        claimed.renewal_lease_owner = None
        claimed.renewal_lease_expires_at = None
        claimed.lifecycle_version += 1
        credential.last_auth_succeeded_at = now
        credential.failure_classification = None
        if failure_injector:
            failure_injector("during_audit_persistence")
        repo.add_security_event(models.SecurityAuditEvent(
            actor_user_id=tenant.actor_id, target_user_id=tenant.user_id,
            event_type="topstep_session_lifecycle", action="session_renewed", outcome="success",
            event_metadata={"correlation_id": tenant.correlation_id, "integration_id": integration_id,
                            "credential_generation": credential.credential_generation,
                            "session_generation": claimed.session_generation, "fencing_token": fence},
        ))
        if failure_injector:
            failure_injector("before_session_commit")
        db.commit()
        if failure_injector:
            failure_injector("after_session_commit")
        return claimed
    except Exception as exc:
        db.rollback()
        failure = _safe_failure(exc)
        try:
            repo = TenantRepository(db, tenant)
            row = repo.get(models.TopstepProviderSession, session_id, lock=True)
            if row is not None and row.state in SESSION_RENEWAL_STATES and row.renewal_lease_owner == owner_id and row.fencing_token == fence:
                row.state = "expired" if as_utc(row.expires_at) <= utc_now() else "failed"
                row.failure_classification = failure
                row.renewal_lease_owner = None
                row.renewal_lease_expires_at = None
                row.lifecycle_version += 1
                db.commit()
        except Exception:
            db.rollback()
        if isinstance(exc, (TopstepSessionError, ProviderError)):
            raise TopstepSessionError(failure) from exc
        raise


def reconcile_restored_database(
    db: Session,
    operator: OperatorContext,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> models.HostedRestoreReconciliation:
    if as_utc(operator.expires_at) <= utc_now():
        raise TopstepSessionError("restore_operator_context_expired")
    if "restore:reconcile" not in operator.permissions:
        raise TopstepSessionError("restore_operator_permission_required")
    if os.getenv("TOPSTEP_PROVIDER_EXECUTION_ENABLED", "false").lower() in {"1", "true", "yes"}:
        raise TopstepSessionError("provider_execution_must_be_disabled")
    if os.getenv("HOSTED_WORKER_PROCESSING_ENABLED", "false").lower() in {"1", "true", "yes"}:
        raise TopstepSessionError("worker_processing_must_be_disabled")
    target = configured_security_epoch()
    now = utc_now()
    with system_maintenance_scope(db, "topstep-restore-reconciliation"):
        epoch = db.query(models.HostedSecurityEpoch).filter_by(id=1).with_for_update().first()
        if epoch is None:
            raise TopstepSessionError("database_security_epoch_missing")
        if target < epoch.database_epoch:
            raise TopstepSessionError("security_epoch_rollback_rejected")
        existing = db.query(models.HostedRestoreReconciliation).filter_by(correlation_id=operator.correlation_id).first()
        if target == epoch.database_epoch:
            if existing is not None and existing.state == "completed":
                return existing
            raise TopstepSessionError("security_epoch_not_advanced")
        if existing is None:
            existing = models.HostedRestoreReconciliation(
                id=str(uuid4()), source_epoch=epoch.database_epoch, target_epoch=target,
                correlation_id=operator.correlation_id, operator_id=operator.actor_user_id,
                state="started", started_at=now,
            )
            db.add(existing)
        epoch.target_epoch = target
        epoch.reconciliation_state = "reconciling"
        epoch.correlation_id = operator.correlation_id
        epoch.started_at = epoch.started_at or now
        epoch.lifecycle_version += 1
        db.flush()
        if failure_injector:
            failure_injector("restore_started")
        integrations = db.query(models.PlatformIntegration).filter(
            models.PlatformIntegration.provider == "topstepx",
            models.PlatformIntegration.security_epoch < target,
        ).with_for_update().all()
        integration_ids = [row.id for row in integrations]
        tenant_by_integration = {row.id: row.user_id for row in integrations}
        for integration in integrations:
            if integration.status != "deleted":
                integration.status = "suspended"
                integration.lifecycle_version += 1
            integration.integration_metadata = {
                "restore_reconciliation_required": True,
                "prior_credential_generation": (integration.integration_metadata or {}).get("credential_generation"),
            }
            db.add(models.SecurityAuditEvent(
                actor_user_id=operator.actor_user_id, target_user_id=integration.user_id,
                event_type="hosted_restore_reconciliation", action="restored_integration_revoked",
                outcome="success", case_id=operator.case_id,
                event_metadata={"correlation_id": operator.correlation_id, "source_epoch": epoch.database_epoch,
                                "target_epoch": target, "integration_id": integration.id},
            ))
        if integration_ids:
            credentials = db.query(models.TopstepCredential).filter(
                models.TopstepCredential.integration_id.in_(integration_ids)
            ).with_for_update().all()
            for credential in credentials:
                credential.username_encrypted = None
                credential.api_key_encrypted = None
                credential.is_current = 0
                credential.lifecycle_status = "restore_revoked"
                credential.revoked_at = credential.revoked_at or now
                credential.version += 1
            sessions = db.query(models.TopstepProviderSession).filter(
                models.TopstepProviderSession.integration_id.in_(integration_ids)
            ).with_for_update().all()
            for session in sessions:
                session.token_encrypted = None
                session.state = "revoked" if session.state != "deleted" else "deleted"
                session.revoked_at = session.revoked_at or now
                session.renewal_lease_owner = None
                session.renewal_lease_expires_at = None
                session.fencing_token += 1
                session.lifecycle_version += 1
            db.query(models.TopstepDiscoverySnapshot).filter(
                models.TopstepDiscoverySnapshot.integration_id.in_(integration_ids)
            ).update({"is_current": 0}, synchronize_session=False)
            attestations = db.query(models.TopstepCombineAttestation).filter(
                models.TopstepCombineAttestation.integration_id.in_(integration_ids),
                models.TopstepCombineAttestation.revoked_at.is_(None),
            ).all()
            for row in attestations:
                row.revoked_at, row.revocation_classification = now, "database_restore"
            approvals = db.query(models.TopstepAccountApproval).filter(
                models.TopstepAccountApproval.integration_id.in_(integration_ids),
                models.TopstepAccountApproval.revoked_at.is_(None),
            ).all()
            for row in approvals:
                row.state, row.revoked_at = "revoked", now
                row.revoking_operator_id = operator.actor_user_id
                row.revocation_classification = "database_restore"
                row.version += 1
            dry_runs = db.query(models.HostedCombineDryRun).filter(
                models.HostedCombineDryRun.integration_id.in_(integration_ids),
                models.HostedCombineDryRun.state.in_(
                    ("requested", "eligibility_checking", "market_data_loading", "evaluating", "risk_evaluating")),
            ).with_for_update().all()
            for dry_run in dry_runs:
                dry_run.state = "canceled"
                dry_run.result_classification = "database_restore"
                dry_run.completed_at = now
                dry_run.lease_owner = None
                dry_run.lease_expires_at = None
                dry_run.fencing_token += 1
                if dry_run.proposal_id:
                    proposal = db.query(models.HostedCombineProposal).filter_by(
                        id=dry_run.proposal_id, user_id=dry_run.user_id).with_for_update().first()
                    if proposal:
                        proposal.expires_at = now
            existing.dry_runs_suppressed = len(dry_runs)
            runs = db.query(models.SimulationRun).filter(
                models.SimulationRun.user_id.in_(tuple(tenant_by_integration.values())),
                models.SimulationRun.state.notin_(("completed", "stopped", "killed", "failed")),
            ).all()
            run_ids = []
            for run in runs:
                integration_id = run.integration_id or (run.configuration or {}).get("integration_id")
                if integration_id not in integration_ids:
                    continue
                run.state, run.desired_state, run.degraded_reason = "killed", "stopped", "database_restore"
                run.kill_requested_at = run.stopped_at = now
                run.active_scope_key = None
                run_ids.append(run.id)
            commands = db.query(models.SimulationCommand).filter(
                models.SimulationCommand.status.in_(("pending", "accepted", "claimed", "processing"))
            ).all()
            for command in commands:
                if command.integration_id in integration_ids or command.run_id in run_ids:
                    command.status, command.failure_code, command.completed_at = "cancelled", "stale_security_epoch", now
                    existing.commands_suppressed += 1
            events = db.query(models.OutboxEvent).filter(models.OutboxEvent.status.in_(("pending", "claimed"))).all()
            for event in events:
                payload_integration = (event.payload or {}).get("integration_id")
                if event.integration_id in integration_ids or payload_integration in integration_ids or event.aggregate_id in run_ids:
                    event.status, event.terminal_reason = "terminal", "stale_security_epoch"
                    event.claim_owner = event.claim_expires_at = None
                    existing.outbox_suppressed += 1
        existing.integrations_suppressed = len(integrations)
        existing.state = "suppressing"
        existing.lifecycle_version += 1
        db.flush()
        if failure_injector:
            failure_injector("after_work_suppression")
        if failure_injector:
            failure_injector("before_epoch_advance")
        epoch.database_epoch = target
        epoch.target_epoch = None
        epoch.reconciliation_state = "ready"
        epoch.completed_at = utc_now()
        epoch.failure_classification = None
        epoch.lifecycle_version += 1
        existing.state = "completed"
        existing.completed_at = epoch.completed_at
        existing.lifecycle_version += 1
        db.commit()
        if failure_injector:
            failure_injector("after_epoch_advance")
        return existing


def credential_work_is_current(db: Session, tenant: TenantContext, *, integration_id: int,
                               credential_generation: int, security_epoch: int) -> tuple[bool, str]:
    repo = TenantRepository(db, tenant)
    try:
        epoch = require_current_epoch(db, security_epoch)
    except TopstepSessionError as exc:
        return False, exc.code
    integration = repo.first(models.PlatformIntegration, models.PlatformIntegration.id == integration_id)
    credential = repo.first(
        models.TopstepCredential, models.TopstepCredential.integration_id == integration_id,
        models.TopstepCredential.credential_generation == credential_generation,
        models.TopstepCredential.is_current == 1,
    )
    if integration is None or integration.security_epoch != epoch or integration.status != "approved":
        return False, "integration_not_approved"
    if credential is None or credential.security_epoch != epoch or not credential.api_key_encrypted:
        return False, "credential_generation_stale"
    return True, "current"
