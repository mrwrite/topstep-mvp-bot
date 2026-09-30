import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import DurableRunError, process_run, submit_command, submit_start


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def test_postgres_concurrent_scope_has_one_authoritative_run():
    engine = create_engine(POSTGRES_URL)
    Session = sessionmaker(bind=engine)
    seed = Session()
    suffix = uuid4().hex
    user = models.User(username=f"pg-{suffix}", email=f"pg-{suffix}@test", hashed_password="x")
    seed.add(user); seed.commit()
    user_id = user.id
    seed.close()

    def attempt(key):
        db = Session()
        try:
            tenant = TenantContext(user_id, "pg")
            run, command, duplicate = submit_start(
                db, tenant, symbol="ES",
                configuration={"trading_mode": "paper", "account_id": suffix, "integration_id": None},
                idempotency_key=key,
            )
            db.commit()
            return ("created", run.id)
        except DurableRunError as exc:
            return (exc.code, None)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ("concurrent-a", "concurrent-b")))
    assert sorted(item[0] for item in outcomes) == ["active_scope_exists", "created"]
    verify = Session()
    assert verify.query(models.SimulationRun).filter_by(user_id=user_id, active_scope_key=f"{user_id}:None:{suffix}:ES").count() == 1
    verify.close()


def test_postgres_same_start_key_returns_one_run_and_command():
    engine = create_engine(POSTGRES_URL)
    Session = sessionmaker(bind=engine)
    seed = Session()
    suffix = uuid4().hex
    user = models.User(username=f"pg-same-{suffix}", email=f"pg-same-{suffix}@test", hashed_password="x")
    seed.add(user); seed.commit(); user_id = user.id; seed.close()

    def attempt(_):
        db = Session()
        try:
            run, command, duplicate = submit_start(
                db, TenantContext(user_id, "pg"), symbol="NQ",
                configuration={"trading_mode": "paper", "account_id": suffix, "integration_id": None},
                idempotency_key="same-concurrent-key",
            )
            db.commit()
            return run.id, command.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert len(set(outcomes)) == 1


def test_postgres_duplicate_pause_race_has_one_command():
    engine = create_engine(POSTGRES_URL)
    Session = sessionmaker(bind=engine)
    seed = Session()
    suffix = uuid4().hex
    user = models.User(username=f"pg-pause-{suffix}", email=f"pg-pause-{suffix}@test", hashed_password="x")
    seed.add(user); seed.commit()
    tenant = TenantContext(user.id, "pg")
    run, _, _ = submit_start(
        seed, tenant, symbol="YM",
        configuration={"trading_mode": "paper", "account_id": suffix, "integration_id": None},
        idempotency_key="start-pause-race",
    )
    process_run(seed, tenant, run.id, "pg-worker"); seed.commit()
    user_id, run_id = user.id, run.id
    seed.close()

    def attempt(_):
        db = Session()
        try:
            _, command, duplicate = submit_command(
                db, TenantContext(user_id, "pg"), run_id,
                idempotency_key="pause-race", name="pause",
            )
            db.commit()
            return command.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(attempt, range(2)))
    assert len(set(ids)) == 1
