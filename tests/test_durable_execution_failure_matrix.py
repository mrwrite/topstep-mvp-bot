from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import (
    DurableRunError, acquire_lease, checkpoint, claim_outbox, consume_outbox,
    create_simulated_order, process_run, record_outbox_failure, record_simulated_fill,
    recover_expired_runs, submit_command, submit_start,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db, name):
    row = models.User(username=name, email=f"{name}@test", hashed_password="x")
    db.add(row); db.flush()
    return row


def ctx(user):
    return TenantContext(user.id, user.username)


def start(db, user, key="start-1", symbol="ES"):
    run, command, duplicate = submit_start(
        db, ctx(user), symbol=symbol,
        configuration={"trading_mode": "paper", "account_id": "SIM", "integration_id": None},
        idempotency_key=key,
    )
    process_run(db, ctx(user), run.id, "worker-a")
    db.commit()
    return run, command, duplicate


def test_same_start_key_is_idempotent_and_different_key_same_scope_is_rejected(db):
    user = make_user(db, "start")
    run, command, _ = start(db, user)
    same_run, same_command, duplicate = submit_start(
        db, ctx(user), symbol="ES",
        configuration={"trading_mode": "paper", "account_id": "SIM", "integration_id": None},
        idempotency_key="start-1",
    )
    assert duplicate and same_run.id == run.id and same_command.id == command.id
    with pytest.raises(DurableRunError, match="active_scope_exists"):
        submit_start(
            db, ctx(user), symbol="ES",
            configuration={"trading_mode": "paper", "account_id": "SIM", "integration_id": None},
            idempotency_key="start-2",
        )


@pytest.mark.parametrize("name", ["pause", "resume", "stop"])
def test_duplicate_control_delivery_has_one_command(db, name):
    user = make_user(db, f"duplicate-{name}")
    run, _, _ = start(db, user)
    if name == "resume":
        submit_command(db, ctx(user), run.id, idempotency_key="prepare-pause", name="pause")
        process_run(db, ctx(user), run.id, "worker-a"); db.commit()
    run, first, _ = submit_command(db, ctx(user), run.id, idempotency_key=f"{name}-1", name=name)
    if first.status == "accepted":
        process_run(db, ctx(user), run.id, "worker-a")
    run, second, duplicate = submit_command(db, ctx(user), run.id, idempotency_key=f"{name}-1", name=name)
    assert duplicate and first.id == second.id
    assert db.query(models.SimulationCommand).filter_by(idempotency_key=f"{name}-1").count() == 1


def test_kill_is_durable_idempotent_and_overrides_recovery(db):
    user = make_user(db, "kill")
    run, _, _ = start(db, user)
    run.state = "recovering"; db.commit()
    killed, command, _ = submit_command(db, ctx(user), run.id, idempotency_key="kill-1", name="kill")
    db.commit(); db.expire_all()
    assert db.get(models.SimulationRun, run.id).state == "killed"
    again, same, duplicate = submit_command(db, ctx(user), run.id, idempotency_key="kill-1", name="kill")
    assert duplicate and same.id == command.id and again.state == "killed"
    with pytest.raises(DurableRunError, match="terminal_state"):
        acquire_lease(db, ctx(user), run.id, "returned-worker")


def test_lease_takeover_fences_state_checkpoint_order_and_fill_writes(db):
    user = make_user(db, "fence")
    run, _, _ = start(db, user)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    old_fence = lease.fencing_token
    lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
    new = acquire_lease(db, ctx(user), run.id, "worker-b")
    assert new.fencing_token > old_fence
    for operation in (
        lambda: checkpoint(db, ctx(user), run.id, owner_id="worker-a", fence=old_fence, sequence=1, value={}),
        lambda: create_simulated_order(
            db, ctx(user), run.id, owner_id="worker-a", fence=old_fence,
            execution_identity="order-stale", side="BUY", quantity=1, reference_price=100,
        ),
    ):
        with pytest.raises(DurableRunError, match="stale_owner"):
            operation()


def test_orders_and_fills_are_effectively_once_across_redelivery(db):
    user = make_user(db, "effects")
    run, _, _ = start(db, user)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    order, duplicate = create_simulated_order(
        db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token,
        execution_identity="market:1:signal:BUY", side="BUY", quantity=1, reference_price=100,
    )
    same_order, repeated = create_simulated_order(
        db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token,
        execution_identity="market:1:signal:BUY", side="BUY", quantity=1, reference_price=100,
    )
    assert not duplicate and repeated and same_order.id == order.id
    fill, _ = record_simulated_fill(
        db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token,
        order_id=order.id, execution_identity="fill:market:1", quantity=1, price=100,
    )
    same_fill, repeated_fill = record_simulated_fill(
        db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token,
        order_id=order.id, execution_identity="fill:market:1", quantity=1, price=100,
    )
    assert repeated_fill and same_fill.id == fill.id
    assert db.query(models.PaperOrder).count() == db.query(models.PaperFill).count() == 1


def test_recovery_uses_checkpoint_and_rejects_version_mismatch(db):
    user = make_user(db, "recovery")
    run, _, _ = start(db, user)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    checkpoint(db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token, sequence=1, value={
        "configuration_hash": run.configuration_hash, "strategy_version": run.strategy_version,
        "market_data_id": None,
        "data_freshness": "new",
        "risk_counters": {
            "trade_count": 0,
            "consecutive_losses": 0,
            "realized_pnl": 0.0,
            "fees": 0.0,
            "version": 0,
        },
        "position": {"quantity": 0, "avg_price": 0.0},
        "ledger_version": 0,
    })
    lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
    outcomes = recover_expired_runs(db, worker_id="recovery-worker")
    assert outcomes == ["running"]
    assert db.get(models.SimulationRun, run.id).last_checkpoint_sequence == 1


@pytest.mark.parametrize("field", ["configuration_hash", "strategy_version"])
def test_recovery_fails_closed_for_version_mismatch(db, field):
    user = make_user(db, f"mismatch-{field}")
    run, _, _ = start(db, user)
    lease = db.query(models.SimulationLease).filter_by(run_id=run.id).one()
    checkpoint(db, ctx(user), run.id, owner_id=lease.owner_id, fence=lease.fencing_token, sequence=1, value={
        "configuration_hash": run.configuration_hash, "strategy_version": run.strategy_version,
    })
    setattr(run, field, "changed")
    lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert recover_expired_runs(db, worker_id="recovery-worker") == ["failed"]
    assert run.failure_code == "unreconcilable_checkpoint"


def test_outbox_claim_expiry_redelivery_effect_then_ack_and_poison_limit(db):
    user = make_user(db, "outbox")
    run, _, _ = start(db, user)
    event = db.query(models.OutboxEvent).first()
    claimed = claim_outbox(db, owner_id="publisher-a", claim_seconds=5)
    assert event in claimed
    event.claim_expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert event in claim_outbox(db, owner_id="publisher-b", claim_seconds=5)
    effects = []
    assert consume_outbox(db, ctx(user), event.id, "consumer", lambda e: effects.append(e.id))
    assert not consume_outbox(db, ctx(user), event.id, "consumer", lambda e: effects.append(e.id))
    assert effects == [event.id]
    poison = db.query(models.OutboxEvent).filter(models.OutboxEvent.id != event.id).first()
    for _ in range(2):
        record_outbox_failure(db, poison, max_attempts=2, code="poison")
    assert poison.status == "terminal" and poison.terminal_reason == "poison"


def test_cross_tenant_controls_leases_checkpoints_outbox_and_kill_are_hidden(db):
    alice, bob = make_user(db, "alice"), make_user(db, "bob")
    run, _, _ = start(db, alice)
    event = db.query(models.OutboxEvent).filter_by(user_id=alice.id).first()
    operations = [
        lambda: submit_command(db, ctx(bob), run.id, idempotency_key="attack", name="stop"),
        lambda: acquire_lease(db, ctx(bob), run.id, "attacker"),
        lambda: checkpoint(db, ctx(bob), run.id, owner_id="attacker", fence=1, sequence=1, value={}),
        lambda: consume_outbox(db, ctx(bob), event.id, "attacker", lambda _: None),
        lambda: submit_command(db, ctx(bob), run.id, idempotency_key="kill-attack", name="kill"),
    ]
    for operation in operations:
        with pytest.raises(DurableRunError, match="(run|event)_not_found"):
            operation()


def test_architecture_has_no_process_local_execution_authority():
    source = open("app/scheduler.py", encoding="utf-8").read()
    run_route = source[source.index('@router.get("/run-bot")'):]
    assert "BOT_SESSIONS.get" not in run_route
    assert "get_bot_state" not in run_route
    assert "execute_paper_order" not in run_route
    assert "record_strategy_signal" not in run_route
