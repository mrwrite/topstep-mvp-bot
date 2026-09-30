from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import (
    DurableRunError, acquire_lease, checkpoint, command, consume_once, create_run,
    record_outbox_failure, transition,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def tenant(user_id):
    return TenantContext(user_id=user_id, username=f"u{user_id}")


def user(db_session, suffix):
    row = models.User(username=f"durable-{suffix}", email=f"durable-{suffix}@test", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def test_fenced_transitions_takeover_and_stale_owner(db_session):
    owner = user(db_session, "owner")
    run = create_run(db_session, tenant(owner.id), symbol="ES", configuration={"mode": "simulation"})
    lease1 = acquire_lease(db_session, tenant(owner.id), run.id, "worker-a")
    old_fence = lease1.fencing_token
    transition(db_session, tenant(owner.id), run.id, expected_version=1, fence=old_fence, target="starting")
    lease1.expires_at = datetime.utcnow() - timedelta(seconds=1)
    lease2 = acquire_lease(db_session, tenant(owner.id), run.id, "worker-b")
    assert lease2.fencing_token > old_fence
    with pytest.raises(DurableRunError, match="stale_owner"):
        checkpoint(db_session, tenant(owner.id), run.id, fence=1, sequence=1, value={})
    transition(db_session, tenant(owner.id), run.id, expected_version=2, fence=lease2.fencing_token, target="running")
    with pytest.raises(DurableRunError, match="invalid_transition"):
        transition(db_session, tenant(owner.id), run.id, expected_version=3, fence=lease2.fencing_token, target="stopped")


def test_tenant_commands_and_outbox_are_idempotent(db_session):
    alice, bob = user(db_session, "alice"), user(db_session, "bob")
    run = create_run(db_session, tenant(alice.id), symbol="ES", configuration={})
    first = command(db_session, tenant(alice.id), run.id, idempotency_key="start-1", name="start")
    assert command(db_session, tenant(alice.id), run.id, idempotency_key="start-1", name="start").id == first.id
    with pytest.raises(DurableRunError, match="run_not_found"):
        command(db_session, tenant(bob.id), run.id, idempotency_key="x", name="stop")
    event = db_session.query(models.OutboxEvent).filter_by(event_type="simulation.run.requested").one()
    assert consume_once(db_session, tenant(alice.id), event.id, "worker") is True
    assert consume_once(db_session, tenant(alice.id), event.id, "worker") is False


def test_outbox_bounded_failure_is_terminal(db_session):
    owner = user(db_session, "retry")
    run = create_run(db_session, tenant(owner.id), symbol="ES", configuration={})
    event = db_session.query(models.OutboxEvent).filter_by(aggregate_id=run.id).one()
    record_outbox_failure(event, max_attempts=2)
    assert event.status == "pending"
    record_outbox_failure(event, max_attempts=2)
    assert (event.status, event.terminal_reason) == ("terminal", "retry_exhausted")
