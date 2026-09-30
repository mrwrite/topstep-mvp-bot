from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import (
    DurableRunError,
    acquire_lease,
    process_run,
    recover_expired_runs,
    submit_command,
    submit_start,
)
from app.simulation_evaluation import (
    evaluate_rsi_threshold,
    process_market_input,
    queue_market_input,
    reconcile_checkpoint,
)
from app.time_utils import utc_now


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _tenant(user):
    return TenantContext(user.id, user.username)


def _run(db, name="evaluation", **overrides):
    user = models.User(username=name, email=f"{name}@test", hashed_password="x")
    db.add(user)
    db.flush()
    configuration = {
        "environment": "simulation",
        "trading_mode": "paper",
        "account_id": f"SIM-{name}",
        "integration_id": None,
        "auto_trade": True,
        "quantity": 1,
        "buy_threshold": 30,
        "sell_threshold": 70,
        "min_bars": 30,
        "max_staleness_seconds": 300,
        "slippage_bps": 2,
        "fee_per_contract": 1.25,
        **overrides,
    }
    run, _, _ = submit_start(
        db,
        _tenant(user),
        symbol="ES",
        configuration=configuration,
        idempotency_key=f"start-{name}",
    )
    process_run(db, _tenant(user), run.id, "worker-a")
    db.commit()
    return user, run


def _bars(event_at, *, descending=True):
    prices = list(range(130, 90, -1)) if descending else [100.0] * 40
    return [
        {
            "timestamp": (event_at - timedelta(minutes=len(prices) - index - 1)).isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1,
        }
        for index, price in enumerate(prices)
    ]


def _queue(db, user, run, event_at, *, sequence="1", descending=True):
    row, duplicate = queue_market_input(
        db,
        _tenant(user),
        run.id,
        source="deterministic-test-feed",
        timeframe="1m",
        event_at=event_at,
        provider_sequence=sequence,
        payload={"bars": _bars(event_at, descending=descending)},
    )
    db.commit()
    return row, duplicate


def _process(db, user, run, market, *, now, inject=None):
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    return process_market_input(
        db,
        _tenant(user),
        run.id,
        market.id,
        owner_id=lease.owner_id,
        fence=lease.fencing_token,
        now=now,
        inject=inject,
    )


def test_fenced_evaluation_commits_distinct_order_fill_financial_state_and_checkpoint(db):
    now = utc_now()
    user, run = _run(db, "atomic")
    market, _ = _queue(db, user, run, now)

    evaluation = _process(db, user, run, market, now=now)
    db.commit()
    db.expire_all()

    assert evaluation.signal == "BUY"
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run.id).count() == 1
    order = db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).one()
    fill = db.query(models.PaperFill).filter_by(simulation_run_id=run.id).one()
    ledger = db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run.id).one()
    position = db.query(models.PaperPosition).filter_by(simulation_run_id=run.id).one()
    counter = db.get(models.SimulationRiskCounter, run.id)
    checkpoint = db.query(models.SimulationCheckpoint).filter_by(run_id=run.id).one()
    assert order.status == "filled" and fill.order_id == order.id
    assert order.created_at <= fill.created_at
    assert ledger.execution_identity == f"ledger:{fill.execution_identity}"
    assert position.quantity == 1
    assert counter.trade_count == 1 and counter.fees == pytest.approx(1.25)
    assert checkpoint.checkpoint_hash == db.get(models.SimulationRun, run.id).last_checkpoint_hash
    reconcile_checkpoint(db, db.get(models.SimulationRun, run.id))


def test_rsi_replay_is_deterministic_for_identical_versioned_input():
    event_at = utc_now()
    payload = {"bars": _bars(event_at)}
    parameters = {
        "buy_threshold": 30,
        "sell_threshold": 70,
        "min_bars": 30,
    }
    first = evaluate_rsi_threshold(payload, parameters)
    second = evaluate_rsi_threshold(payload, parameters)
    assert first == second


def test_duplicate_input_and_reprocessing_do_not_duplicate_economic_effects(db):
    now = utc_now()
    user, run = _run(db, "duplicate")
    market, duplicate = _queue(db, user, run, now)
    assert duplicate is False
    _process(db, user, run, market, now=now)
    db.commit()
    same, duplicate = _queue(db, user, run, now)
    assert duplicate and same.id == market.id
    _process(db, user, run, same, now=now)
    db.commit()
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run.id).count() == 1
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 1
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run.id).count() == 1
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run.id).count() == 1
    assert db.get(models.SimulationRiskCounter, run.id).trade_count == 1


def test_stale_input_is_checkpointed_without_strategy_execution_or_order(db):
    now = utc_now()
    user, run = _run(db, "stale", max_staleness_seconds=30)
    market, _ = _queue(db, user, run, now - timedelta(minutes=2))
    evaluation = _process(db, user, run, market, now=now)
    db.commit()
    assert evaluation.signal == "HOLD"
    assert evaluation.status == "suppressed"
    assert evaluation.freshness == "too_old"
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 0
    assert db.get(models.SimulationRun, run.id).degraded_reason == "market_data_too_old"


@pytest.mark.parametrize(
    "stage",
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
def test_crash_before_authoritative_commit_rolls_back_all_effects(db, stage):
    now = utc_now()
    user, run = _run(db, f"rollback-{stage}")
    market, _ = _queue(db, user, run, now)

    def inject(current):
        if current == stage:
            raise RuntimeError(f"crash:{stage}")

    with pytest.raises(RuntimeError, match="crash"):
        _process(db, user, run, market, now=now, inject=inject)
    db.rollback()
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run.id).count() == 0
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 0
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run.id).count() == 0
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run.id).count() == 0
    assert db.query(models.SimulationCheckpoint).filter_by(run_id=run.id).count() == 0
    assert db.get(models.SimulationMarketInput, market.id).status == "pending"


def test_kill_before_evaluation_and_returning_expired_owner_cannot_commit(db):
    now = utc_now()
    user, run = _run(db, "kill-boundary")
    market, _ = _queue(db, user, run, now)
    old_lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    old_owner, old_fence = old_lease.owner_id, old_lease.fencing_token
    submit_command(
        db,
        _tenant(user),
        run.id,
        idempotency_key="kill-before-evaluation",
        name="kill",
    )
    db.commit()
    with pytest.raises(DurableRunError, match="stale_owner"):
        process_market_input(
            db,
            _tenant(user),
            run.id,
            market.id,
            owner_id=old_owner,
            fence=old_fence,
            now=now,
        )
    assert db.get(models.SimulationRun, run.id).state == "killed"
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 0


def test_lease_takeover_rejects_old_worker_before_any_financial_mutation(db):
    now = utc_now()
    user, run = _run(db, "stale-workflow")
    market, _ = _queue(db, user, run, now)
    old_lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    old_owner, old_fence = old_lease.owner_id, old_lease.fencing_token
    old_lease.expires_at = now - timedelta(seconds=1)
    new_lease = acquire_lease(db, _tenant(user), run.id, "replacement-worker")
    assert new_lease.fencing_token > old_fence
    with pytest.raises(DurableRunError, match="stale_owner"):
        process_market_input(
            db,
            _tenant(user),
            run.id,
            market.id,
            owner_id=old_owner,
            fence=old_fence,
            now=now,
        )
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run.id).count() == 0
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 0
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run.id).count() == 0
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run.id).count() == 0


def test_checkpoint_or_financial_drift_fails_reconciliation(db):
    now = utc_now()
    user, run = _run(db, "drift")
    market, _ = _queue(db, user, run, now)
    _process(db, user, run, market, now=now)
    db.commit()
    position = db.query(models.PaperPosition).filter_by(simulation_run_id=run.id).one()
    position.quantity += 1
    db.commit()
    with pytest.raises(DurableRunError, match="position_state_mismatch"):
        reconcile_checkpoint(db, db.get(models.SimulationRun, run.id))


def test_market_queue_and_evaluation_hide_cross_tenant_run(db):
    now = utc_now()
    owner, run = _run(db, "market-owner")
    attacker = models.User(username="market-attacker", email="market-attacker@test", hashed_password="x")
    db.add(attacker)
    db.flush()
    market, _ = _queue(db, owner, run, now)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    with pytest.raises(DurableRunError, match="run_not_found"):
        queue_market_input(
            db,
            _tenant(attacker),
            run.id,
            source="attack",
            timeframe="1m",
            event_at=now,
            payload={"bars": _bars(now)},
        )
    with pytest.raises(DurableRunError, match="run_not_found"):
        process_market_input(
            db,
            _tenant(attacker),
            run.id,
            market.id,
            owner_id=lease.owner_id,
            fence=lease.fencing_token,
            now=now,
        )
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run.id).count() == 0


def test_architecture_forbids_request_owned_or_legacy_automated_execution():
    scheduler = open("app/scheduler.py", encoding="utf-8").read()
    routes = open("app/simulation_routes.py", encoding="utf-8").read()
    worker = open("app/simulation_worker.py", encoding="utf-8").read()
    evaluator = open("app/simulation_evaluation.py", encoding="utf-8").read()
    assert "process_run(" not in scheduler
    assert "process_run(" not in routes
    assert "execute_paper_order" not in worker
    assert "record_strategy_signal" not in worker
    assert "fetch_price_data" not in worker
    assert "BOT_STATES" not in worker
    assert "assert_fence(" in evaluator
    assert "source_identity" in evaluator
    assert "execution_identity" in evaluator
    assert "checkpoint(" in evaluator


@pytest.mark.parametrize(
    ("interrupted_state", "desired_state", "expected_state"),
    [
        ("running", "running", "running"),
        ("pausing", "paused", "paused"),
        ("stopping", "stopped", "stopped"),
        ("recovering", "running", "running"),
    ],
)
def test_recovery_from_each_interrupted_state_reconciles_before_transition(
    db, interrupted_state, desired_state, expected_state
):
    now = utc_now()
    user, run = _run(db, f"recover-{interrupted_state}")
    market, _ = _queue(db, user, run, now)
    _process(db, user, run, market, now=now)
    run.state = interrupted_state
    run.desired_state = desired_state
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    lease.expires_at = now - timedelta(seconds=1)
    db.commit()
    db.expire_all()
    assert recover_expired_runs(db, worker_id=f"replacement-{interrupted_state}") == [
        expected_state
    ]
    db.commit()
    assert db.get(models.SimulationRun, run.id).state == expected_state
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 1


def test_restart_while_starting_is_owned_by_worker_without_http_execution(db):
    user = models.User(username="starting", email="starting@test", hashed_password="x")
    db.add(user)
    db.flush()
    run, _, _ = submit_start(
        db,
        _tenant(user),
        symbol="ES",
        configuration={
            "environment": "simulation",
            "trading_mode": "paper",
            "account_id": "STARTING",
            "auto_trade": False,
        },
        idempotency_key="start-restart-starting",
    )
    db.commit()
    db.expire_all()
    assert recover_expired_runs(db, worker_id="replacement-starting") == ["running"]
    db.commit()
    assert db.get(models.SimulationRun, run.id).state == "running"


@pytest.mark.parametrize("interrupted_state", ["starting", "running", "pausing", "stopping", "recovering"])
def test_kill_precedes_recovery_for_every_interrupted_state(db, interrupted_state):
    user, run = _run(db, f"kill-recovery-{interrupted_state}")
    run.state = interrupted_state
    if interrupted_state == "pausing":
        run.desired_state = "paused"
    elif interrupted_state == "stopping":
        run.desired_state = "stopped"
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    lease.expires_at = utc_now() - timedelta(seconds=1)
    submit_command(
        db,
        _tenant(user),
        run.id,
        idempotency_key=f"kill-{interrupted_state}",
        name="kill",
    )
    db.commit()
    db.expire_all()
    assert recover_expired_runs(db, worker_id=f"replacement-killed-{interrupted_state}") == []
    assert db.get(models.SimulationRun, run.id).state == "killed"
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 0


def test_recovery_rejects_corrupt_checkpoint_and_stale_market_does_not_repeat_order(db):
    now = utc_now()
    user, run = _run(db, "corrupt-recovery")
    market, _ = _queue(db, user, run, now)
    _process(db, user, run, market, now=now)
    db.commit()
    checkpoint_row = db.query(models.SimulationCheckpoint).filter_by(run_id=run.id).one()
    checkpoint_row.checkpoint = {**checkpoint_row.checkpoint, "position": {"quantity": 99, "avg_price": 1.0}}
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    lease.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    assert recover_expired_runs(db, worker_id="corrupt-replacement") == ["failed"]
    db.commit()
    assert db.get(models.SimulationRun, run.id).failure_code == "unreconcilable_checkpoint"
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 1


def test_stale_and_duplicate_market_inputs_after_recovery_do_not_repeat_economic_effects(db):
    now = utc_now()
    user, run = _run(db, "post-recovery-market")
    first, _ = _queue(db, user, run, now, sequence="1")
    _process(db, user, run, first, now=now)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    lease.expires_at = now - timedelta(seconds=1)
    db.commit()
    assert recover_expired_runs(db, worker_id="post-recovery-worker") == ["running"]
    db.commit()

    same, duplicate = _queue(db, user, run, now, sequence="1")
    assert duplicate and same.id == first.id
    replacement = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    process_market_input(
        db,
        _tenant(user),
        run.id,
        same.id,
        owner_id=replacement.owner_id,
        fence=replacement.fencing_token,
        now=now,
    )
    stale_at = now - timedelta(minutes=1)
    stale, _ = _queue(db, user, run, stale_at, sequence="2")
    evaluation = process_market_input(
        db,
        _tenant(user),
        run.id,
        stale.id,
        owner_id=replacement.owner_id,
        fence=replacement.fencing_token,
        now=now,
    )
    db.commit()
    assert evaluation.freshness == "out_of_order"
    assert evaluation.status == "suppressed"
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run.id).count() == 1
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run.id).count() == 1
    assert db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run.id).count() == 1
    assert db.get(models.SimulationRiskCounter, run.id).trade_count == 1
