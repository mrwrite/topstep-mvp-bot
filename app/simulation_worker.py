from __future__ import annotations

import asyncio
from uuid import uuid4

from . import database
from .authorization import TenantContext
from .durable_simulation import (
    claim_outbox, consume_outbox, process_pending_commands, recover_expired_runs,
    record_outbox_failure,
)
from .observability import log_event, safe_exception
from .simulation_evaluation import process_pending_market_inputs
from .hosted_combine_dryrun import process_pending_dry_runs
from .tenant_repository import VerifiedTenantJob


def recovery_cycle(*, worker_id: str | None = None) -> dict:
    db = database.SessionLocal()
    worker_id = worker_id or f"simulation-worker:{uuid4().hex}"
    try:
        if database.APP_CONFIG.deployment_profile == "hosted_topstep_combine_beta":
            from .topstep_session_security import bootstrap_security_epoch, security_epoch_status
            epoch = security_epoch_status(db)
            if epoch.state == "uninitialized":
                bootstrap_security_epoch(db)
                db.commit()
                epoch = security_epoch_status(db)
            if not epoch.ready:
                if epoch.state == "rollback_rejected":
                    raise RuntimeError("Hosted security epoch rollback rejected; worker processing stopped.")
                return {
                    "recovered": [], "commands": [], "evaluations": [], "consumed": 0,
                    "credential_work": "suppressed", "security_epoch_state": epoch.state,
                }
        states = recover_expired_runs(
            db, worker_id=worker_id, job_secret=database.APP_CONFIG.secret_key,
            job_environment=database.APP_CONFIG.app_env,
        )
        commands = process_pending_commands(
            db, worker_id=worker_id, job_secret=database.APP_CONFIG.secret_key,
            job_environment=database.APP_CONFIG.app_env,
        )
        evaluations = process_pending_market_inputs(
            db,
            worker_id=worker_id,
            job_secret=database.APP_CONFIG.secret_key,
            job_environment=database.APP_CONFIG.app_env,
        )
        dry_runs = process_pending_dry_runs(db, worker_id=worker_id)
        events = claim_outbox(db, owner_id=worker_id)
        consumed = 0
        for event in events:
            try:
                tenant = VerifiedTenantJob.issue(
                    TenantContext(event.user_id, "outbox-job"), event.id,
                    database.APP_CONFIG.secret_key,
                    job_type="simulation-outbox", purpose="consume-outbox",
                    environment=database.APP_CONFIG.app_env,
                    payload={"event_id": event.id, "aggregate_id": event.aggregate_id},
                ).validate(
                    database.APP_CONFIG.secret_key,
                    expected_tenant=event.user_id,
                    expected_command=event.id,
                    expected_actor=event.user_id,
                    expected_job_type="simulation-outbox",
                    expected_purpose="consume-outbox",
                    expected_environment=database.APP_CONFIG.app_env,
                    payload={"event_id": event.id, "aggregate_id": event.aggregate_id},
                )
                if consume_outbox(
                    db, tenant, event.id, "structured-audit",
                    lambda row: log_event(
                        "durable_outbox", "event_consumed", user_id=row.user_id,
                        run_id=row.aggregate_id, outbox_event_id=row.id,
                        durable_event_type=row.event_type,
                    ),
                ):
                    consumed += 1
            except Exception as exc:
                record_outbox_failure(db, event, code="consumer_failure")
                log_event(
                    "durable_outbox", "event_failed", user_id=event.user_id,
                    run_id=event.aggregate_id, outbox_event_id=event.id,
                    error=safe_exception(exc),
                )
        db.commit()
        return {
            "recovered": states,
            "commands": commands,
            "evaluations": evaluations,
            "hosted_dry_runs": dry_runs,
            "consumed": consumed,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def periodic_recovery(
    stop: asyncio.Event,
    interval_seconds: int = 10,
    *,
    worker_id: str | None = None,
):
    worker_id = worker_id or f"simulation-worker:{uuid4().hex}"
    while not stop.is_set():
        try:
            await asyncio.to_thread(recovery_cycle, worker_id=worker_id)
        except Exception as exc:
            log_event("durable_worker", "recovery_cycle_failed", error=safe_exception(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
