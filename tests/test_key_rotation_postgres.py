from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.key_management import EncryptionContext, EnvelopeEncryptionService, LocalDevelopmentKeyProvider
from app.key_rotation import claim_items, create_operation, process_item, reconcile, transition
from app.time_utils import utc_now


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def test_postgres_rotation_workers_are_disjoint_and_expired_claim_recovers():
    engine = create_engine(POSTGRES_URL)
    Session = sessionmaker(bind=engine)
    seed = Session()
    suffix = uuid4().hex[:10]
    user = models.User(username=f"key-pg-{suffix}", email=f"key-pg-{suffix}@test", hashed_password="x")
    seed.add(user)
    seed.flush()
    old_service = EnvelopeEncryptionService(LocalDevelopmentKeyProvider({"v1": b"1" * 32}, "v1"))
    integrations = []
    for index in range(3):
        integration = models.PlatformIntegration(user_id=user.id, display_name=f"pg-{index}",
                                                  provider="tradingview", status="active")
        seed.add(integration)
        seed.flush()
        context = EncryptionContext(str(user.id), "integration-credentials", "platform-integration",
                                    str(integration.id), "test", "1")
        integration.credentials_encrypted = old_service.encrypt(b'{"token":"value"}', context)
        integrations.append(integration)
    seed.commit()
    operation = create_operation(seed, operation_type="rotation", source_version="v1",
                                 target_version="v2", operation_id=f"rotation-{suffix}",
                                 backup_verified=True)
    transition(seed, operation.id, "active-write")
    transition(seed, operation.id, "rewrapping")

    def claim(worker):
        db = Session()
        try:
            return [item.id for item in claim_items(db, operation.id, worker, limit=1, lease_seconds=60)]
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("worker-a", "worker-b")))
    claimed_ids = [item for claim_set in claims for item in claim_set]
    assert len(claimed_ids) == 2 and len(set(claimed_ids)) == 2

    # Model a crash after claim commit but before processing; expiry makes the item reclaimable.
    crashed = seed.query(models.KeyManagementItem).filter_by(id=claimed_ids[0]).one()
    crashed.claim_expires_at = utc_now() - timedelta(seconds=1)
    seed.commit()
    reclaimed = claim_items(seed, operation.id, "worker-c", limit=1)
    assert [item.id for item in reclaimed] == [claimed_ids[0]]

    rotating = EnvelopeEncryptionService(LocalDevelopmentKeyProvider(
        {"v1": b"1" * 32, "v2": b"2" * 32}, "v2"))
    processing = seed.query(models.KeyManagementItem).filter_by(operation_id=operation.id, status="processing").all()
    for item in processing:
        process_item(seed, item.id, rotating)
    for item in claim_items(seed, operation.id, "worker-d", limit=10):
        process_item(seed, item.id, rotating)
    assert reconcile(seed, operation.id) == {
        "total": 3, "pending": 0, "processing": 0, "succeeded": 3, "failed": 0,
    }
    seed.close()
    engine.dispose()
