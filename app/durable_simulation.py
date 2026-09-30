from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .authorization import TenantContext
from .observability import log_event
from .tenant_repository import (
    VerifiedTenantJob,
    TenantScopeError,
    bind_tenant_context,
    require_tenant,
    system_maintenance_scope,
)
from .strategy import STRATEGY_VERSION
from .time_utils import as_utc, utc_now


TERMINAL_STATES = {"stopped", "failed", "killed"}
TRANSITIONS = {
    "requested": {"starting", "killed"},
    "starting": {"running", "failed", "killed", "recovering"},
    "running": {"pausing", "stopping", "failed", "killed", "recovering"},
    "pausing": {"paused", "failed", "killed", "recovering", "stopping"},
    "paused": {"starting", "stopping", "killed"},
    "stopping": {"stopped", "failed", "killed", "recovering"},
    "recovering": {"running", "paused", "stopped", "failed", "killed"},
    "stopped": set(), "failed": set(), "killed": set(),
}
COMMAND_TARGET = {
    "pause": ("pausing", "paused"), "resume": ("starting", "running"),
    "stop": ("stopping", "stopped"), "kill": ("killed", "killed"),
}


class DurableRunError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class WorkerSettings:
    lease_seconds: int = 30
    renewal_seconds: int = 10
    recovery_timeout_seconds: int = 60
    max_retries: int = 5
    outbox_claim_seconds: int = 30

    def __post_init__(self):
        if self.lease_seconds < 6 or self.renewal_seconds >= self.lease_seconds / 2:
            raise ValueError("Renewal cadence must be less than half the lease duration.")
        if self.max_retries < 1 or self.outbox_claim_seconds < 5:
            raise ValueError("Unsafe durable worker settings.")


def _now():
    return utc_now()


def _hash_configuration(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def checkpoint_digest(value: dict) -> str:
    canonical = {key: item for key, item in value.items() if key != "checkpoint_hash"}
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _run(db: Session, tenant: TenantContext, run_id: str, *, lock: bool = False) -> models.SimulationRun:
    try:
        tenant = bind_tenant_context(db, tenant)
    except TenantScopeError as exc:
        raise DurableRunError("run_not_found") from exc
    query = db.query(models.SimulationRun).filter(
        models.SimulationRun.id == run_id, models.SimulationRun.user_id == tenant.user_id
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise DurableRunError("run_not_found")
    return row


def _event(db: Session, run: models.SimulationRun, event_type: str, payload: dict, *, causation_id=None):
    row = models.OutboxEvent(
        id=str(uuid4()), user_id=run.user_id, aggregate_type="simulation_run",
        aggregate_id=run.id, event_type=event_type, payload=payload, correlation_id=run.correlation_id,
        causation_id=causation_id,
        integration_id=run.integration_id, credential_generation=run.credential_generation,
        security_epoch=run.security_epoch,
        stable_identity=f"{run.id}:{event_type}:{causation_id or run.state_version}",
    )
    db.add(row)
    return row


def _audit(name: str, run: models.SimulationRun, **fields):
    log_event("durable_simulation", name, user_id=run.user_id, run_id=run.id,
              state=run.state, fencing_token=run.fencing_token, **fields)


def create_run(
    db: Session, tenant: TenantContext, *, symbol: str, configuration: dict,
    scope_key: str | None = None, strategy_version: str = STRATEGY_VERSION,
    strategy_config_id: int | None = None, correlation_id: str | None = None,
) -> models.SimulationRun:
    tenant = bind_tenant_context(db, tenant)
    if configuration.get("trading_mode", "paper") != "paper":
        raise DurableRunError("live_execution_disabled")
    topstep_integration_id = None
    topstep_credential_generation = None
    topstep_security_epoch = None
    run_configuration = dict(configuration)
    # Never accept generation/epoch claims from the request body. These bindings
    # are populated only from the tenant-owned integration and current credential.
    run_configuration.pop("credential_generation", None)
    run_configuration.pop("security_epoch", None)
    requested_integration_id = configuration.get("integration_id")
    if requested_integration_id is not None:
        provider = db.query(models.PlatformIntegration.provider).filter(
            models.PlatformIntegration.id == requested_integration_id,
            models.PlatformIntegration.user_id == tenant.user_id,
        ).scalar()
        if provider and str(provider).lower() == "topstepx":
            current_credential = db.query(models.TopstepCredential).filter(
                models.TopstepCredential.user_id == tenant.user_id,
                models.TopstepCredential.integration_id == requested_integration_id,
                models.TopstepCredential.is_current == 1,
            ).first()
            integration = db.query(models.PlatformIntegration).filter(
                models.PlatformIntegration.user_id == tenant.user_id,
                models.PlatformIntegration.id == requested_integration_id,
            ).first()
            if current_credential and integration:
                topstep_integration_id = requested_integration_id
                topstep_credential_generation = current_credential.credential_generation
                topstep_security_epoch = integration.security_epoch
                run_configuration["credential_generation"] = topstep_credential_generation
                run_configuration["security_epoch"] = topstep_security_epoch
            else:
                run_configuration.pop("credential_generation", None)
                run_configuration.pop("security_epoch", None)
    correlation = correlation_id or str(uuid4())
    scope = scope_key or f"{tenant.user_id}:{configuration.get('integration_id')}:{configuration.get('account_id')}:{symbol.upper()}"
    row = models.SimulationRun(
        id=str(uuid4()), user_id=tenant.user_id, state="requested", desired_state="running",
        scope_key=scope, active_scope_key=scope, symbol=symbol.upper(), configuration=run_configuration,
        configuration_hash=_hash_configuration(run_configuration), strategy_version=strategy_version,
        integration_id=topstep_integration_id,
        credential_generation=topstep_credential_generation,
        security_epoch=topstep_security_epoch,
        strategy_config_id=strategy_config_id, environment="simulation", correlation_id=correlation,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DurableRunError("active_scope_exists") from exc
    _event(db, row, "simulation.run.requested", {"state_version": row.state_version})
    _audit("run_requested", row)
    return row


def submit_start(
    db: Session, tenant: TenantContext, *, symbol: str, configuration: dict,
    idempotency_key: str, strategy_config_id: int | None = None,
) -> tuple[models.SimulationRun, models.SimulationCommand, bool]:
    # Serialize starts for a tenant before checking command/scope uniqueness.
    # PostgreSQL row locking supplies the concurrency boundary; no process mutex is authoritative.
    tenant = bind_tenant_context(db, tenant)
    # Users use their primary key as tenant key and are intentionally resolved
    # only after the trusted context has been bound.
    db.query(models.User).filter(models.User.id == tenant.user_id).with_for_update().one()
    existing = db.query(models.SimulationCommand).filter_by(
        user_id=tenant.user_id, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.command != "start":
            raise DurableRunError("idempotency_conflict")
        return _run(db, tenant, existing.run_id), existing, True
    run = create_run(db, tenant, symbol=symbol, configuration=configuration, strategy_config_id=strategy_config_id)
    cmd = _new_command(db, run, idempotency_key, "start")
    _set_state(run, "starting", causation_id=cmd.id, db=db)
    return run, cmd, False


def submit_command(
    db: Session, tenant: TenantContext, run_id: str, *, idempotency_key: str, name: str
) -> tuple[models.SimulationRun, models.SimulationCommand, bool]:
    if name not in COMMAND_TARGET:
        raise DurableRunError("unsupported_command")
    run = _run(db, tenant, run_id, lock=True)
    existing = db.query(models.SimulationCommand).filter_by(
        user_id=require_tenant(tenant).user_id, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.run_id != run_id or existing.command != name:
            raise DurableRunError("idempotency_conflict")
        return run, existing, True
    cmd = _new_command(db, run, idempotency_key, name)
    target, completed_target = COMMAND_TARGET[name]
    if name == "kill":
        if run.state != "killed":
            _enforce_kill(db, run, cmd.id)
        _complete_command(cmd, run, completed_target)
    elif run.state == completed_target or (name == "stop" and run.state == "stopped"):
        _complete_command(cmd, run, completed_target)
    elif run.state in TERMINAL_STATES:
        _fail_command(cmd, "terminal_state")
    elif target not in TRANSITIONS.get(run.state, set()):
        _fail_command(cmd, "invalid_transition")
    else:
        run.desired_state = completed_target
        _set_state(run, target, causation_id=cmd.id, db=db)
        cmd.status = "accepted"
    db.flush()
    return run, cmd, False


def _new_command(db, run, key, name):
    cmd = models.SimulationCommand(
        id=str(uuid4()), run_id=run.id, user_id=run.user_id, idempotency_key=key,
        command=name, status="accepted", correlation_id=run.correlation_id, causation_id=run.id,
        integration_id=run.integration_id, credential_generation=run.credential_generation,
        security_epoch=run.security_epoch, stable_identity=f"{run.id}:{key}:{name}",
    )
    db.add(cmd)
    _event(db, run, "simulation.command.accepted", {"command_id": cmd.id, "command": name}, causation_id=cmd.id)
    return cmd


def _complete_command(cmd, run, state):
    cmd.status, cmd.completed_at = "succeeded", _now()
    cmd.result = {"run_state": state, "state_version": run.state_version}


def _fail_command(cmd, code):
    cmd.status, cmd.completed_at, cmd.failure_code = "failed", _now(), code
    cmd.result = {"failure_code": code}


def _set_state(run, target, *, causation_id, db):
    if target not in TRANSITIONS.get(run.state, set()):
        raise DurableRunError("invalid_transition")
    previous = run.state
    run.state, run.state_version = target, run.state_version + 1
    now = _now()
    if target == "running" and run.started_at is None:
        run.started_at = now
    if target in TERMINAL_STATES:
        run.active_scope_key, run.completed_at = None, now
        if target == "stopped":
            run.stopped_at = now
    _event(db, run, f"simulation.run.{target}", {
        "previous_state": previous, "state": target, "state_version": run.state_version
    }, causation_id=causation_id)
    _audit("state_transition", run, previous_state=previous, new_state=target)


def _enforce_kill(db, run, causation_id):
    previous = run.state
    run.kill_requested_at = _now()
    run.desired_state = "killed"
    run.fencing_token += 1
    run.state, run.state_version = "killed", run.state_version + 1
    run.active_scope_key, run.completed_at = None, _now()
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).first()
    if lease:
        lease.expires_at = _now()
    db.query(models.SimulationCommand).filter(
        models.SimulationCommand.run_id == run.id,
        models.SimulationCommand.status.in_(("accepted", "processing")),
    ).update({"status": "cancelled", "completed_at": _now()}, synchronize_session=False)
    _event(db, run, "simulation.run.killed", {"previous_state": previous}, causation_id=causation_id)
    _audit("kill_enforced", run, previous_state=previous)


def acquire_lease(db, tenant, run_id, owner_id, ttl_seconds=30):
    run = _run(db, tenant, run_id, lock=True)
    if run.state in TERMINAL_STATES or run.kill_requested_at:
        raise DurableRunError("terminal_state")
    now = _now()
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).with_for_update().first()
    if lease and as_utc(lease.expires_at) > now:
        if lease.owner_id != owner_id:
            raise DurableRunError("lease_held")
        lease.renewed_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        run.last_heartbeat_at = now
        db.flush()
        return lease
    fence = max(run.fencing_token, lease.fencing_token if lease else 0) + 1
    takeover = bool(lease and lease.owner_id != owner_id)
    if lease is None:
        lease = models.SimulationLease(run_id=run.id, user_id=run.user_id)
        db.add(lease)
    lease.owner_id, lease.fencing_token = owner_id, fence
    lease.acquired_at = lease.renewed_at = now
    lease.expires_at = now + timedelta(seconds=ttl_seconds)
    run.fencing_token, run.last_heartbeat_at = fence, now
    if takeover and run.state not in {"requested", "starting", "paused"}:
        previous = run.state
        run.state, run.state_version = "recovering", run.state_version + 1
        _event(db, run, "simulation.run.recovering", {"previous_state": previous}, causation_id=owner_id)
    db.flush()
    _audit("lease_acquired", run, worker_id=owner_id, takeover=takeover)
    return lease


def assert_fence(db, tenant, run_id, owner_id, fence, *, lock=False):
    run = _run(db, tenant, run_id, lock=lock)
    lease = db.query(models.SimulationLease).filter_by(
        run_id=run_id, user_id=tenant.user_id, owner_id=owner_id, fencing_token=fence
    ).first()
    if (run.state == "killed" or run.kill_requested_at or run.fencing_token != fence
            or not lease or as_utc(lease.expires_at) <= _now()):
        _audit("stale_owner_rejected", run, worker_id=owner_id)
        raise DurableRunError("stale_owner")
    return run


def renew_lease(db, tenant, run_id, owner_id, fence, ttl_seconds=30):
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    lease = db.query(models.SimulationLease).filter_by(run_id=run_id).first()
    lease.renewed_at, lease.expires_at = _now(), _now() + timedelta(seconds=ttl_seconds)
    run.last_heartbeat_at = _now()
    db.flush()
    return lease


def checkpoint(db, tenant, run_id, *, owner_id=None, fence, sequence, value):
    if owner_id is None:
        lease_owner = db.query(models.SimulationLease.owner_id).filter_by(
            run_id=run_id, user_id=tenant.user_id, fencing_token=fence
        ).first()
        owner_id = lease_owner[0] if lease_owner else "missing-owner"
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    if sequence != run.last_checkpoint_sequence + 1:
        raise DurableRunError("checkpoint_sequence_conflict")
    if value.get("configuration_hash") != run.configuration_hash:
        raise DurableRunError("configuration_version_mismatch")
    if value.get("strategy_version") != run.strategy_version:
        raise DurableRunError("strategy_version_mismatch")
    complete_value = {
        "market_data_id": None,
        "last_evaluation_id": None,
        "strategy_state": {},
        "strategy_version": run.strategy_version,
        "configuration_hash": run.configuration_hash,
        "simulation_clock": _now().isoformat(),
        "deterministic_seed": run.id,
        "risk_counters": {},
        "position_version": 0,
        "ledger_version": 0,
        "pending_intent_ids": [],
        "last_order_identity": None,
        "last_fill_identity": None,
        "last_event_id": None,
        "data_freshness": "unknown",
        **value,
    }
    digest = checkpoint_digest(complete_value)
    complete_value["checkpoint_hash"] = digest
    row = models.SimulationCheckpoint(
        run_id=run_id, user_id=run.user_id, fencing_token=fence, sequence=sequence,
        checkpoint=complete_value, market_data_id=complete_value.get("market_data_id"),
        configuration_hash=run.configuration_hash, strategy_version=run.strategy_version,
        checkpoint_hash=digest,
    )
    db.add(row)
    run.last_checkpoint_sequence = sequence
    run.last_checkpoint_hash = digest
    _event(
        db, run, "simulation.checkpoint.committed",
        {"sequence": sequence, "checkpoint_hash": digest},
        causation_id=complete_value.get("last_event_id"),
    )
    db.flush()
    return row


def process_run(db, tenant, run_id, worker_id, settings=WorkerSettings()):
    run = _run(db, tenant, run_id)
    if run.state == "killed" or run.kill_requested_at:
        return run
    lease = acquire_lease(db, tenant, run_id, worker_id, settings.lease_seconds)
    run = assert_fence(db, tenant, run_id, worker_id, lease.fencing_token, lock=True)
    if run.state == "starting":
        _set_state(run, "running", causation_id=worker_id, db=db)
    elif run.state == "pausing":
        _safe_checkpoint_if_missing(db, tenant, run, worker_id, lease.fencing_token)
        _set_state(run, "paused", causation_id=worker_id, db=db)
    elif run.state == "stopping":
        _safe_checkpoint_if_missing(db, tenant, run, worker_id, lease.fencing_token)
        _set_state(run, "stopped", causation_id=worker_id, db=db)
    elif run.state == "recovering":
        recover_owned_run(db, tenant, run, worker_id, lease.fencing_token)
    for cmd in db.query(models.SimulationCommand).filter(
        models.SimulationCommand.run_id == run.id,
        models.SimulationCommand.status == "accepted",
    ).all():
        if cmd.command == "start" and run.state == "running":
            _complete_command(cmd, run, "running")
        elif cmd.command == "pause" and run.state == "paused":
            _complete_command(cmd, run, "paused")
        elif cmd.command == "resume" and run.state == "running":
            _complete_command(cmd, run, "running")
        elif cmd.command == "stop" and run.state == "stopped":
            _complete_command(cmd, run, "stopped")
    db.flush()
    return run


def _safe_checkpoint_if_missing(db, tenant, run, owner, fence):
    if run.last_checkpoint_sequence == 0:
        checkpoint(db, tenant, run.id, owner_id=owner, fence=fence, sequence=1, value={
            "market_data_id": None, "configuration_hash": run.configuration_hash,
            "strategy_version": run.strategy_version, "strategy_state": {},
            "risk_counters": {}, "pending_intent_ids": [], "position_ledger_version": 0,
            "simulation_clock": _now().isoformat(), "deterministic_seed": run.id,
            "last_event_id": None,
        })


def recover_owned_run(db, tenant, run, owner_id, fence):
    assert_fence(db, tenant, run.id, owner_id, fence, lock=True)
    from .risk_service import risk_service
    from .simulation_evaluation import reconcile_checkpoint

    config = run.configuration or {}
    active_kill = risk_service.find_active_kill_switch(
        db,
        user_id=run.user_id,
        integration_id=config.get("integration_id"),
        account_id=config.get("account_id"),
        bot_session_id=run.id,
    )
    if run.kill_requested_at or active_kill:
        _enforce_kill(db, run, owner_id)
        return run
    cp = db.query(models.SimulationCheckpoint).filter_by(
        run_id=run.id, user_id=tenant.user_id, sequence=run.last_checkpoint_sequence
    ).first()
    valid_digest = bool(cp and cp.checkpoint_hash == checkpoint_digest(cp.checkpoint or {}))
    if (
        not cp
        or not valid_digest
        or cp.configuration_hash != run.configuration_hash
        or cp.strategy_version != run.strategy_version
    ):
        run.failure_code, run.failure_summary = "unreconcilable_checkpoint", "Recovery could not validate durable state."
        _set_state(run, "failed", causation_id=owner_id, db=db)
        return run
    try:
        reconcile_checkpoint(db, run)
    except DurableRunError as exc:
        run.failure_code = exc.code
        run.failure_summary = "Recovery could not reconcile durable simulation state."
        _set_state(run, "failed", causation_id=owner_id, db=db)
        return run
    freshness = (cp.checkpoint or {}).get("data_freshness", "unknown")
    if freshness in {"too_old", "stale", "out_of_order", "unknown"} and run.desired_state == "running":
        run.data_freshness = freshness
        run.degraded_reason = f"market_data_{freshness}"
        _set_state(run, "paused", causation_id=owner_id, db=db)
        return run
    target = run.desired_state if run.desired_state in {"running", "paused", "stopped"} else "failed"
    _set_state(run, target, causation_id=owner_id, db=db)
    return run


def fail_owned_run(db, tenant, run_id, *, owner_id, fence, code, summary):
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    if run.state == "killed" or run.kill_requested_at:
        raise DurableRunError("stale_owner")
    run.failure_code = code
    run.failure_summary = summary
    run.degraded_reason = code
    _set_state(run, "failed", causation_id=owner_id, db=db)
    return run


def recover_expired_runs(db, *, worker_id, job_secret="development-recovery-key",
                         job_environment="test", settings=WorkerSettings()):
    now = _now()
    with system_maintenance_scope(db, "durable-recovery-discovery"):
        candidates = db.query(models.SimulationRun).outerjoin(
            models.SimulationLease, models.SimulationLease.run_id == models.SimulationRun.id
        ).filter(
            models.SimulationRun.state.notin_(TERMINAL_STATES),
            or_(models.SimulationLease.run_id.is_(None), models.SimulationLease.expires_at <= now),
        ).all()
    outcomes = []
    for run in candidates:
        tenant = VerifiedTenantJob.issue(
            TenantContext(run.user_id, "recovery-job"), run.id, job_secret,
            job_type="simulation-recovery", purpose="recover-run",
            environment=job_environment, payload={"run_id": run.id},
        ).validate(
            job_secret, expected_tenant=run.user_id, expected_command=run.id,
            expected_actor=run.user_id,
            expected_job_type="simulation-recovery", expected_purpose="recover-run",
            expected_environment=job_environment, payload={"run_id": run.id},
        )
        try:
            outcomes.append(process_run(db, tenant, run.id, worker_id, settings).state)
        except DurableRunError as exc:
            outcomes.append(exc.code)
    return outcomes


def process_pending_commands(
    db,
    *,
    worker_id,
    job_secret="development-recovery-key",
    job_environment="test",
    settings=WorkerSettings(),
):
    with system_maintenance_scope(db, "durable-command-discovery"):
        commands = (
            db.query(models.SimulationCommand)
            .join(models.SimulationRun, models.SimulationRun.id == models.SimulationCommand.run_id)
            .filter(
                models.SimulationCommand.status == "accepted",
                models.SimulationRun.state.notin_(TERMINAL_STATES),
            )
            .order_by(models.SimulationCommand.created_at)
            .all()
        )
    outcomes = []
    seen_runs = set()
    for command_row in commands:
        if command_row.run_id in seen_runs:
            continue
        seen_runs.add(command_row.run_id)
        if command_row.integration_id is not None:
            from .topstep_session_security import credential_work_is_current
            current, reason = credential_work_is_current(
                db, TenantContext(command_row.user_id, "simulation-command-job"),
                integration_id=command_row.integration_id,
                credential_generation=command_row.credential_generation or 0,
                security_epoch=command_row.security_epoch or 0,
            )
            if not current:
                command_row.status = "cancelled"
                command_row.failure_code = reason
                command_row.completed_at = _now()
                outcomes.append({"run_id": command_row.run_id, "state": reason})
                continue
        tenant = VerifiedTenantJob.issue(
            TenantContext(command_row.user_id, "simulation-command-job"),
            command_row.id,
            job_secret,
            job_type="simulation-command", purpose="process-command",
            environment=job_environment,
            payload={"run_id": command_row.run_id, "command": command_row.command},
        ).validate(
            job_secret,
            expected_tenant=command_row.user_id,
            expected_command=command_row.id,
            expected_actor=command_row.user_id,
            expected_job_type="simulation-command",
            expected_purpose="process-command",
            expected_environment=job_environment,
            payload={"run_id": command_row.run_id, "command": command_row.command},
        )
        try:
            run = process_run(db, tenant, command_row.run_id, worker_id, settings)
            outcomes.append({"run_id": run.id, "state": run.state})
        except DurableRunError as exc:
            outcomes.append({"run_id": command_row.run_id, "state": exc.code})
    return outcomes


def create_simulated_order(
    db, tenant, run_id, *, owner_id, fence, execution_identity, side, quantity, reference_price
):
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    if run.state != "running":
        raise DurableRunError("run_not_running")
    prior = db.query(models.PaperOrder).filter_by(
        user_id=tenant.user_id, idempotency_key=execution_identity
    ).first()
    if prior:
        return prior, True
    config = run.configuration or {}
    order = models.PaperOrder(
        user_id=tenant.user_id, integration_id=config.get("integration_id"),
        account_id=config.get("account_id"), symbol=run.symbol, side=side,
        quantity=quantity, trading_mode="paper", order_type="market", source="durable-simulation",
        idempotency_key=execution_identity, order_fingerprint=execution_identity,
        status="submitted", remaining_quantity=quantity,
        response={"reference_price": reference_price, "simulation": True, "live": False},
        simulation_run_id=run.id, simulation_fencing_token=fence,
    )
    db.add(order)
    _event(db, run, "simulation.order.submitted", {
        "execution_identity": execution_identity, "side": side, "quantity": quantity
    }, causation_id=execution_identity)
    db.flush()
    return order, False


def record_simulated_fill(
    db, tenant, run_id, *, owner_id, fence, order_id, execution_identity, quantity, price
):
    run = assert_fence(db, tenant, run_id, owner_id, fence, lock=True)
    if run.state != "running":
        raise DurableRunError("run_not_running")
    order = db.query(models.PaperOrder).filter_by(
        id=order_id, user_id=tenant.user_id, simulation_run_id=run.id
    ).first()
    if not order:
        raise DurableRunError("order_not_found")
    prior = db.query(models.PaperFill).filter_by(execution_identity=execution_identity).first()
    if prior:
        return prior, True
    fill = models.PaperFill(
        order_id=order.id, user_id=tenant.user_id, symbol=order.symbol, side=order.side,
        quantity=quantity, price=price, simulation_run_id=run.id,
        simulation_fencing_token=fence, execution_identity=execution_identity,
    )
    db.add(fill)
    order.filled_quantity += quantity
    order.remaining_quantity = max(0, order.quantity - order.filled_quantity)
    order.status = "filled" if order.remaining_quantity == 0 else "partially_filled"
    _event(db, run, "simulation.fill.recorded", {
        "execution_identity": execution_identity, "order_id": order.id, "quantity": quantity
    }, causation_id=execution_identity)
    db.flush()
    return fill, False


def claim_outbox(db, *, owner_id, limit=10, claim_seconds=30):
    now = _now()
    with system_maintenance_scope(db, "outbox-claim-discovery"):
        events = db.query(models.OutboxEvent).filter(
            models.OutboxEvent.status.in_(("pending", "claimed")),
            models.OutboxEvent.available_at <= now,
            or_(models.OutboxEvent.claim_expires_at.is_(None), models.OutboxEvent.claim_expires_at <= now),
        ).order_by(models.OutboxEvent.created_at).with_for_update(skip_locked=True).limit(limit).all()
    for event in events:
        event.status, event.claim_owner = "claimed", owner_id
        event.claim_expires_at = now + timedelta(seconds=claim_seconds)
    db.flush()
    return events


def consume_outbox(db, tenant, event_id, consumer, effect):
    try:
        tenant = bind_tenant_context(db, tenant)
    except TenantScopeError as exc:
        raise DurableRunError("event_not_found") from exc
    event = db.query(models.OutboxEvent).filter_by(id=event_id, user_id=tenant.user_id).with_for_update().first()
    if not event:
        raise DurableRunError("event_not_found")
    if event.integration_id is not None:
        from .topstep_session_security import credential_work_is_current
        current, reason = credential_work_is_current(
            db, tenant, integration_id=event.integration_id,
            credential_generation=event.credential_generation or 0,
            security_epoch=event.security_epoch or 0,
        )
        if not current:
            event.status = "terminal"
            event.terminal_reason = reason
            event.claim_owner = event.claim_expires_at = None
            db.flush()
            return False
    prior = db.query(models.OutboxDelivery).filter_by(event_id=event_id, consumer=consumer, outcome="succeeded").first()
    if prior:
        return False
    effect(event)
    attempt = db.query(models.OutboxDelivery).filter_by(event_id=event_id, consumer=consumer).count() + 1
    db.add(models.OutboxDelivery(
        user_id=event.user_id, event_id=event_id, consumer=consumer,
        outcome="succeeded", attempt=attempt,
    ))
    event.status, event.claim_owner, event.claim_expires_at = "consumed", None, None
    db.flush()
    return True


def record_outbox_failure(db_or_event, event=None, *, consumer="worker", max_attempts=5, retryable=True, code="consumer_failure"):
    if event is None:
        event, db = db_or_event, None
    else:
        db = db_or_event
    event.attempt_count += 1
    if db is not None:
        db.add(models.OutboxDelivery(
            user_id=event.user_id, event_id=event.id,
            consumer=f"{consumer}:attempt:{event.attempt_count}",
            outcome="failed", attempt=event.attempt_count, failure_code=code,
        ))
    event.claim_owner = event.claim_expires_at = None
    if not retryable or event.attempt_count >= max_attempts:
        terminal_code = "retry_exhausted" if retryable and code == "consumer_failure" else code
        event.status, event.terminal_reason = "terminal", terminal_code
    else:
        event.status = "pending"
        event.available_at = _now() + timedelta(seconds=min(60, 2 ** event.attempt_count))


# Backward-compatible names used by earlier focused tests.
def command(db, tenant, run_id, idempotency_key, name):
    if name == "start":
        run = _run(db, tenant, run_id)
        existing = db.query(models.SimulationCommand).filter_by(
            user_id=tenant.user_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            if existing.run_id != run_id or existing.command != name:
                raise DurableRunError("idempotency_conflict")
            return existing
        return _new_command(db, run, idempotency_key, name)
    return submit_command(db, tenant, run_id, idempotency_key=idempotency_key, name=name)[1]
consume_once = lambda db, tenant, event_id, consumer: consume_outbox(
    db, tenant, event_id, consumer, lambda _event: None
)
transition = lambda db, tenant, run_id, expected_version, fence, target: _legacy_transition(
    db, tenant, run_id, expected_version, fence, target
)


def _legacy_transition(db, tenant, run_id, expected_version, fence, target):
    run = _run(db, tenant, run_id, lock=True)
    lease = db.query(models.SimulationLease).filter_by(run_id=run_id, user_id=tenant.user_id, fencing_token=fence).first()
    if (
        not lease
        or as_utc(lease.expires_at) <= _now()
        or run.fencing_token != fence
        or run.state_version != expected_version
    ):
        raise DurableRunError("stale_owner")
    _set_state(run, target, causation_id="legacy-test", db=db)
    db.flush()
    return run
