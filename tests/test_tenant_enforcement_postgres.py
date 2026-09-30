from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.tenant_repository import TenantRepository
from app.time_utils import utc_now


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def _session():
    engine = create_engine(POSTGRES_URL)
    return engine, sessionmaker(bind=engine)()


def _users(db):
    suffix = uuid4().hex[:10]
    alice = models.User(username=f"pg-a-{suffix}", email=f"pg-a-{suffix}@test", hashed_password="x")
    bob = models.User(username=f"pg-b-{suffix}", email=f"pg-b-{suffix}@test", hashed_password="x")
    db.add_all([alice, bob])
    db.flush()
    return alice, bob


def test_postgres_tenant_repository_bulk_operations_cannot_cross_scope():
    engine, db = _session()
    try:
        alice, bob = _users(db)
        target = models.PlatformIntegration(
            user_id=bob.id, display_name="bob", provider="TRADINGVIEW", status="disabled"
        )
        db.add(target)
        db.commit()
        repository = TenantRepository(db, TenantContext(alice.id, alice.username))
        assert repository.update(models.PlatformIntegration, (), {"status": "active"}) == 0
        assert repository.delete(models.PlatformIntegration) == 0
        db.commit()
        verify = sessionmaker(bind=engine)()
        try:
            assert verify.query(models.PlatformIntegration).filter_by(id=target.id).one().status == "disabled"
        finally:
            verify.close()
    finally:
        db.close()
        engine.dispose()


def test_postgres_rejects_cross_tenant_outbox_delivery_relationship():
    engine, db = _session()
    try:
        alice, bob = _users(db)
        event = models.OutboxEvent(
            id=str(uuid4()), user_id=alice.id, aggregate_type="test", aggregate_id="run",
            event_type="test", payload={}, correlation_id=str(uuid4()),
        )
        db.add(event)
        db.flush()
        db.add(models.OutboxDelivery(
            user_id=bob.id, event_id=event.id, consumer="test", outcome="succeeded"
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(models.OutboxDelivery).filter_by(event_id=event.id).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_postgres_rejects_cross_tenant_provider_revocation_relationship():
    engine, db = _session()
    try:
        alice, bob = _users(db)
        now = utc_now().replace(tzinfo=None)
        request = models.AccountDeletionRequest(
            user_id=alice.id, status="pending", execute_after=now + timedelta(days=7),
            confirmation_hash="hash",
        )
        db.add(request)
        db.flush()
        db.add(models.ProviderRevocationAttempt(
            user_id=bob.id, deletion_request_id=request.id, provider="TRADINGVIEW", outcome="unconfirmed"
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(models.ProviderRevocationAttempt).filter_by(deletion_request_id=request.id).count() == 0
    finally:
        db.close()
        engine.dispose()
