from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import (
    claim_outbox,
    consume_outbox,
    process_run,
    renew_lease,
    submit_command,
    submit_start,
)
from app.simulation_evaluation import process_market_input, queue_market_input
from app.time_utils import utc_now


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def _factory():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine)


def _bars(event_at):
    prices = list(range(140, 90, -1))
    return [
        {
            "timestamp": (event_at - timedelta(minutes=len(prices) - index - 1)).isoformat(),
            "close": price,
        }
        for index, price in enumerate(prices)
    ]


def _seed(name):
    engine, Session = _factory()
    db = Session()
    suffix = uuid4().hex
    user = models.User(
        username=f"{name}-{suffix}",
        email=f"{name}-{suffix}@test",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    tenant = TenantContext(user.id, user.username)
    run, _, _ = submit_start(
        db,
        tenant,
        symbol="ES",
        configuration={
            "environment": "simulation",
            "trading_mode": "paper",
            "account_id": suffix,
            "integration_id": None,
            "auto_trade": True,
            "quantity": 1,
            "min_bars": 30,
            "max_staleness_seconds": 300,
        },
        idempotency_key=f"start-{suffix}",
    )
    process_run(db, tenant, run.id, "pg-evaluation-worker")
    event_at = utc_now()
    market, _ = queue_market_input(
        db,
        tenant,
        run.id,
        source="pg-test-feed",
        timeframe="1m",
        event_at=event_at,
        provider_sequence="1",
        payload={"bars": _bars(event_at)},
    )
    db.commit()
    values = user.id, user.username, run.id, market.id, event_at
    db.close()
    return engine, Session, values


def _terminate(engine, pid):
    with engine.begin() as connection:
        assert connection.execute(
            text("select pg_terminate_backend(:pid)"), {"pid": pid}
        ).scalar() is True


def test_postgres_duplicate_workers_commit_one_evaluation_and_economic_effect():
    _, Session, (user_id, username, run_id, market_id, event_at) = _seed("duplicate-eval")
    verify = Session()
    lease = verify.get(models.SimulationLease, run_id)
    fence, owner = lease.fencing_token, lease.owner_id
    verify.close()

    def attempt(_):
        db = Session()
        try:
            evaluation = process_market_input(
                db,
                TenantContext(user_id, username),
                run_id,
                market_id,
                owner_id=owner,
                fence=fence,
                now=event_at,
            )
            db.commit()
            return evaluation.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        evaluation_ids = list(pool.map(attempt, range(2)))
    assert len(set(evaluation_ids)) == 1
    db = Session()
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run_id).count() == 1
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count() == 1
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run_id).count() == 1
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run_id).count() == 1
    assert db.get(models.SimulationRiskCounter, run_id).trade_count == 1
    db.close()


def test_postgres_terminated_market_transaction_rolls_back_all_economic_effects():
    engine, Session, (user_id, username, run_id, market_id, event_at) = _seed("db-cut-eval")
    ready, terminated = Event(), Event()
    outcome = {}

    def worker():
        db = Session()
        try:
            outcome["pid"] = db.execute(text("select pg_backend_pid()")).scalar()
            lease = db.get(models.SimulationLease, run_id)
            process_market_input(
                db,
                TenantContext(user_id, username),
                run_id,
                market_id,
                owner_id=lease.owner_id,
                fence=lease.fencing_token,
                now=event_at,
            )
            ready.set()
            terminated.wait(10)
            db.commit()
        except DBAPIError:
            outcome["interrupted"] = True
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert ready.wait(10)
        _terminate(engine, outcome["pid"])
        terminated.set()
        future.result(timeout=10)
    assert outcome["interrupted"] is True
    db = Session()
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run_id).count() == 0
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count() == 0
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run_id).count() == 0
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run_id).count() == 0
    assert db.get(models.SimulationMarketInput, market_id).status == "pending"
    db.close()


@pytest.mark.parametrize("operation", ["heartbeat", "command", "outbox"])
def test_postgres_database_interruption_does_not_commit_partial_control_or_delivery(operation):
    engine, Session, (user_id, username, run_id, _market_id, _event_at) = _seed(f"db-cut-{operation}")
    if operation == "outbox":
        setup = Session()
        event_id = setup.query(models.OutboxEvent).filter_by(aggregate_id=run_id).first().id
        setup.commit()
        setup.close()
    ready, terminated = Event(), Event()
    outcome = {}

    def worker():
        db = Session()
        try:
            outcome["pid"] = db.execute(text("select pg_backend_pid()")).scalar()
            tenant = TenantContext(user_id, username)
            if operation == "heartbeat":
                lease = db.get(models.SimulationLease, run_id)
                before = lease.renewed_at
                outcome["before"] = before
                renew_lease(db, tenant, run_id, lease.owner_id, lease.fencing_token)
            elif operation == "command":
                submit_command(
                    db,
                    tenant,
                    run_id,
                    idempotency_key=f"interrupted-command-{uuid4().hex}",
                    name="pause",
                )
            else:
                claimed = claim_outbox(db, owner_id="interrupted-consumer", limit=1)
                target = next((row for row in claimed if row.id == event_id), None)
                if target is None:
                    target = db.get(models.OutboxEvent, event_id)
                consume_outbox(db, tenant, target.id, "interrupted-consumer", lambda _row: None)
            ready.set()
            terminated.wait(10)
            db.commit()
        except DBAPIError:
            outcome["interrupted"] = True
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert ready.wait(10)
        _terminate(engine, outcome["pid"])
        terminated.set()
        future.result(timeout=10)
    assert outcome["interrupted"] is True
    db = Session()
    if operation == "heartbeat":
        assert db.get(models.SimulationLease, run_id).renewed_at == outcome["before"]
    elif operation == "command":
        assert db.query(models.SimulationCommand).filter(
            models.SimulationCommand.run_id == run_id,
            models.SimulationCommand.command == "pause",
        ).count() == 0
        assert db.get(models.SimulationRun, run_id).state == "running"
    else:
        assert db.query(models.OutboxDelivery).filter_by(
            event_id=event_id, consumer="interrupted-consumer"
        ).count() == 0
        assert db.get(models.OutboxEvent, event_id).status != "consumed"
    db.close()


def test_postgres_skip_locked_outbox_claims_are_disjoint():
    _, Session, (_user_id, _username, run_id, _market_id, _event_at) = _seed("skip-locked")
    claimed = []
    first_ready, release = Event(), Event()

    def first():
        db = Session()
        rows = claim_outbox(db, owner_id="claim-a", limit=1)
        claimed.append(("a", rows[0].id))
        first_ready.set()
        release.wait(10)
        db.rollback()
        db.close()

    def second():
        assert first_ready.wait(10)
        db = Session()
        rows = claim_outbox(db, owner_id="claim-b", limit=1)
        claimed.append(("b", rows[0].id))
        db.rollback()
        db.close()
        release.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (first, second)))
    assert len({event_id for _, event_id in claimed}) == 2


@pytest.mark.parametrize(
    "kill_boundary",
    [
        "after_fence",
        "after_market_classification",
        "after_evaluation",
        "before_order_intent",
        "after_order_intent",
        "after_fill",
        "after_ledger",
        "after_checkpoint",
    ],
)
def test_postgres_kill_serializes_with_atomic_evaluation_and_prevents_later_effects(kill_boundary):
    _, Session, (user_id, username, run_id, market_id, event_at) = _seed(
        f"kill-boundary-{kill_boundary}"
    )
    kill_future = None
    executor = ThreadPoolExecutor(max_workers=1)

    def kill():
        db = Session()
        try:
            submit_command(
                db,
                TenantContext(user_id, username),
                run_id,
                idempotency_key=f"kill-{kill_boundary}-{uuid4().hex}",
                name="kill",
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        lease = db.get(models.SimulationLease, run_id)

        def inject(stage):
            nonlocal kill_future
            if stage == kill_boundary and kill_future is None:
                kill_future = executor.submit(kill)

        process_market_input(
            db,
            TenantContext(user_id, username),
            run_id,
            market_id,
            owner_id=lease.owner_id,
            fence=lease.fencing_token,
            now=event_at,
            inject=inject,
        )
        db.commit()
        kill_future.result(timeout=10)
    finally:
        db.close()
        executor.shutdown(wait=True)
    verify = Session()
    assert verify.get(models.SimulationRun, run_id).state == "killed"
    assert verify.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count() == 1
    assert verify.query(models.PaperFill).filter_by(simulation_run_id=run_id).count() == 1
    assert verify.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run_id).count() == 1
    assert verify.get(models.SimulationRiskCounter, run_id).trade_count == 1
    verify.close()
