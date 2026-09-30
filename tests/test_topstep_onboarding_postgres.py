from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models
from app.time_utils import utc_now


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def _seed():
    engine = create_engine(POSTGRES_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    suffix = uuid4().hex[:10]
    user = models.User(username=f"topstep-pg-{suffix}", email=f"topstep-pg-{suffix}@test", hashed_password="x")
    admin = models.User(username=f"admin-pg-{suffix}", email=f"admin-pg-{suffix}@test", hashed_password="x", is_admin=1)
    db.add_all([user, admin])
    db.flush()
    integration = models.PlatformIntegration(user_id=user.id, display_name="TopstepX", provider="topstepx",
                                             status="awaiting_approval")
    db.add(integration)
    db.flush()
    credential = models.TopstepCredential(user_id=user.id, integration_id=integration.id,
        credential_fingerprint="fingerprint", encryption_key_version="v1", credential_generation=1,
        lifecycle_status="validated", username_encrypted="envelope", api_key_encrypted="envelope")
    db.add(credential)
    db.flush()
    now = utc_now()
    snapshot = models.TopstepDiscoverySnapshot(id=str(uuid4()), user_id=user.id, integration_id=integration.id,
        credential_id=credential.id, credential_generation=1, discovered_at=now,
        expires_at=now + timedelta(hours=1), safe_response_hash="safe", provider_status="success")
    db.add(snapshot)
    db.flush()
    accounts = []
    attestations = []
    for number in (1, 2):
        account = models.TopstepDiscoveredAccount(user_id=user.id, integration_id=integration.id,
            snapshot_id=snapshot.id, provider_account_id=f"account-{number}", safe_display_label=f"Account {number}",
            can_trade=1, is_visible=1, first_observed_at=now, last_observed_at=now)
        db.add(account)
        db.flush()
        attestation = models.TopstepCombineAttestation(id=str(uuid4()), user_id=user.id,
            integration_id=integration.id, discovered_account_id=account.id, credential_generation=1,
            provider_account_id=account.provider_account_id, attestation_version="topstep-combine-v1",
            attestation_text="accepted", accepted_at=now, expires_at=now + timedelta(hours=1),
            correlation_id=str(uuid4()))
        db.add(attestation)
        accounts.append(account)
        attestations.append(attestation)
    db.commit()
    values = user.id, admin.id, integration.id, [(a.id, a.provider_account_id, t.id) for a, t in zip(accounts, attestations)]
    db.close()
    return engine, Session, values


def test_postgres_rejects_cross_tenant_credential_relationship():
    engine, Session, (user_id, _, integration_id, _) = _seed()
    db = Session()
    try:
        suffix = uuid4().hex[:8]
        other = models.User(username=f"other-{suffix}", email=f"other-{suffix}@test", hashed_password="x")
        db.add(other)
        db.flush()
        db.add(models.TopstepCredential(user_id=other.id, integration_id=integration_id,
            credential_fingerprint="x", encryption_key_version="v1", credential_generation=1,
            lifecycle_status="validated"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(models.TopstepCredential).filter_by(user_id=user_id, integration_id=integration_id).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_postgres_concurrent_different_account_approvals_allow_exactly_one():
    engine, Session, (user_id, admin_id, integration_id, candidates) = _seed()
    barrier = Barrier(2)

    def approve(candidate):
        db = Session()
        account_id, provider_id, attestation_id = candidate
        now = utc_now()
        try:
            db.add(models.TopstepAccountApproval(id=str(uuid4()), user_id=user_id,
                integration_id=integration_id, discovered_account_id=account_id,
                attestation_id=attestation_id, credential_generation=1, provider_account_id=provider_id,
                cohort="initial-tester", approving_operator_id=admin_id,
                operator_context={"purpose": "test"}, purpose="concurrent approval test",
                case_reference="CASE-PG", approved_at=now, expires_at=now + timedelta(hours=1),
                correlation_id=str(uuid4())))
            barrier.wait(timeout=5)
            db.commit()
            return "committed"
        except IntegrityError:
            db.rollback()
            return "rejected"
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(approve, candidates))
        assert sorted(outcomes) == ["committed", "rejected"]
        verify = Session()
        try:
            rows = verify.query(models.TopstepAccountApproval).filter_by(
                user_id=user_id, integration_id=integration_id, state="approved").all()
            assert len(rows) == 1
        finally:
            verify.close()
    finally:
        engine.dispose()
