from __future__ import annotations

from uuid import uuid4

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import database, models
from .auth_routes import get_current_user_model
from .authorization import TenantContext
from .durable_simulation import DurableRunError, submit_command
from .simulation_evaluation import queue_market_input
from .tenant_repository import TenantRepository
from .time_utils import as_utc, utc_now

router = APIRouter()


def _serialize_run(run, repository: TenantRepository | None = None):
    value = {
        "id": run.id, "environment": run.environment, "simulation": True, "live": False,
        "state": run.state, "desired_state": run.desired_state,
        "state_version": run.state_version, "symbol": run.symbol,
        "failure_code": run.failure_code, "failure_summary": run.failure_summary,
        "last_heartbeat_at": run.last_heartbeat_at,
        "last_checkpoint_sequence": run.last_checkpoint_sequence,
        "kill_requested_at": run.kill_requested_at, "created_at": run.created_at,
        "updated_at": run.updated_at, "started_at": run.started_at,
        "stopped_at": run.stopped_at, "completed_at": run.completed_at,
        "last_market_data_at": run.last_market_data_at,
        "last_evaluation_at": run.last_evaluation_at,
        "data_freshness": run.data_freshness,
        "degraded_reason": run.degraded_reason,
        "last_checkpoint_hash": run.last_checkpoint_hash,
    }
    if repository is not None:
        lease = repository.first(models.SimulationLease, models.SimulationLease.run_id == run.id)
        now = utc_now()
        value["lease"] = {
            "healthy": bool(lease and as_utc(lease.expires_at) > now),
            "last_heartbeat_at": run.last_heartbeat_at,
            "expires_at": lease.expires_at if lease else None,
        }
        value["pending_commands"] = repository.count(models.SimulationCommand,
            models.SimulationCommand.run_id == run.id,
            models.SimulationCommand.status.in_(("accepted", "processing")),
        )
        value["outbox_terminal_failures"] = repository.count(models.OutboxEvent,
            models.OutboxEvent.aggregate_id == run.id,
            models.OutboxEvent.status == "terminal",
        )
        value["status_observed_at"] = now
    return value


class MarketBar(BaseModel):
    timestamp: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)


class MarketInputRequest(BaseModel):
    source: str = Field(default="simulation-feed", min_length=1, max_length=64)
    timeframe: str = Field(default="1m", min_length=1, max_length=16)
    event_at: datetime
    provider_sequence: str | None = Field(default=None, max_length=128)
    bars: list[MarketBar] = Field(min_length=1, max_length=5000)


def _repository(db: Session, user: models.User) -> TenantRepository:
    return TenantRepository(db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session"))


def _owned(repository: TenantRepository, run_id):
    run = repository.get(models.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found.")
    return run


@router.get("")
def list_runs(current_user: models.User = Depends(get_current_user_model), db: Session = Depends(database.get_db)):
    repository = _repository(db, current_user)
    rows = repository.list(models.SimulationRun, order_by=(models.SimulationRun.created_at.desc(),), limit=100)
    return [_serialize_run(row, repository) for row in rows]


@router.get("/{run_id}")
def get_run(run_id: str, current_user: models.User = Depends(get_current_user_model), db: Session = Depends(database.get_db)):
    repository = _repository(db, current_user)
    return _serialize_run(_owned(repository, run_id), repository)


@router.get("/{run_id}/commands/{command_id}")
def get_command(run_id: str, command_id: str, current_user: models.User = Depends(get_current_user_model), db: Session = Depends(database.get_db)):
    repository = _repository(db, current_user)
    _owned(repository, run_id)
    row = repository.first(models.SimulationCommand,
        models.SimulationCommand.id == command_id,
        models.SimulationCommand.run_id == run_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Simulation command not found.")
    return {"id": row.id, "run_id": row.run_id, "command": row.command, "status": row.status,
            "result": row.result, "failure_code": row.failure_code, "created_at": row.created_at,
            "completed_at": row.completed_at}


@router.post("/{run_id}/commands/{name}", status_code=status.HTTP_202_ACCEPTED)
def control_run(
    run_id: str, name: str,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if name not in {"pause", "resume", "stop", "kill"}:
        raise HTTPException(status_code=404, detail="Simulation command not found.")
    tenant = TenantContext(current_user.id, current_user.username)
    try:
        run, command, duplicate = submit_command(
            db, tenant, run_id, idempotency_key=idempotency_key or f"{name}:{uuid4().hex}", name=name
        )
        db.commit()
    except DurableRunError as exc:
        db.rollback()
        code = 404 if exc.code == "run_not_found" else 409
        raise HTTPException(status_code=code, detail="Simulation command rejected.", headers={"X-Run-Failure": exc.code}) from exc
    return {
        "command": {"id": command.id, "name": command.command, "status": command.status,
                    "result": command.result, "failure_code": command.failure_code},
        "run": _serialize_run(run, _repository(db, current_user)), "duplicate": duplicate,
    }


@router.post("/{run_id}/market-inputs", status_code=status.HTTP_202_ACCEPTED)
def submit_market_input(
    run_id: str,
    request: MarketInputRequest,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    tenant = TenantContext(current_user.id, current_user.username)
    try:
        row, duplicate = queue_market_input(
            db,
            tenant,
            run_id,
            source=request.source,
            timeframe=request.timeframe,
            event_at=request.event_at,
            provider_sequence=request.provider_sequence,
            payload={
                "bars": [
                    {
                        **bar.model_dump(exclude_none=True),
                        "timestamp": as_utc(bar.timestamp).isoformat(),
                    }
                    for bar in request.bars
                ]
            },
        )
        db.commit()
    except DurableRunError as exc:
        db.rollback()
        code = 404 if exc.code == "run_not_found" else 409
        raise HTTPException(
            status_code=code,
            detail="Simulation market input was rejected.",
            headers={"X-Run-Failure": exc.code},
        ) from exc
    return {
        "market_input_id": row.id,
        "market_data_id": row.source_identity,
        "status": row.status,
        "duplicate": duplicate,
        "execution": "queued_for_durable_worker",
        "simulation": True,
        "broker_execution": False,
    }
