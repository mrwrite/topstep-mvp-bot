from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models, topstep_onboarding
from app.authorization import TenantContext
from app.time_utils import utc_now
from app.topstep_session_security import (
    _load_renewal_material,
    TopstepSessionError,
    acquire_renewal_lease,
    credential_work_is_current,
)


POSTGRES_URL = os.getenv("DURABLE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="DURABLE_POSTGRES_TEST_URL is required")


def _seed():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    suffix = uuid4().hex[:10]
    user = models.User(username=f"session-pg-{suffix}", email=f"session-pg-{suffix}@test", hashed_password="x",
                       account_status="active")
    db.add(user)
    db.flush()
    db.add(models.UserBetaStatus(user_id=user.id, status="active"))
    integration = models.PlatformIntegration(
        user_id=user.id, display_name="TopstepX", provider="topstepx", status="approved", security_epoch=1,
        integration_metadata={"credential_generation": 1},
    )
    db.add(integration)
    db.flush()
    credential = models.TopstepCredential(
        user_id=user.id, integration_id=integration.id, lifecycle_status="validated",
        username_encrypted="encrypted-username", api_key_encrypted="encrypted-key",
        credential_fingerprint=f"fingerprint-{suffix}", encryption_key_version="v1",
        credential_generation=1, security_epoch=1,
    )
    db.add(credential)
    db.flush()
    now = utc_now()
    session = models.TopstepProviderSession(
        user_id=user.id, integration_id=integration.id, credential_id=credential.id,
        credential_generation=1, security_epoch=1, state="valid", session_generation=1,
        token_encrypted="encrypted-token", issued_at=now - timedelta(hours=22),
        expires_at=now + timedelta(hours=1), renewal_not_before=now - timedelta(minutes=1),
    )
    db.add(session)
    if db.get(models.HostedSecurityEpoch, 1) is None:
        db.add(models.HostedSecurityEpoch(id=1, database_epoch=1, reconciliation_state="ready"))
    db.commit()
    values = user.id, integration.id, session.id
    db.close()
    return engine, Session, values


def _ctx(user_id):
    return TenantContext(user_id, "postgres-tester", actor_user_id=user_id, source="signed_job")


def test_postgres_simultaneous_session_renewals_have_one_owner(monkeypatch):
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    engine, Session, (user_id, integration_id, _) = _seed()
    barrier = Barrier(2)

    def claim(owner):
        db = Session()
        try:
            barrier.wait(timeout=5)
            _, fence = acquire_renewal_lease(
                db, _ctx(user_id), integration_id=integration_id, owner_id=owner, force=True
            )
            return "claimed", fence
        except TopstepSessionError as exc:
            db.rollback()
            return exc.code, None
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, ("worker-a", "worker-b")))
        assert sorted(value[0] for value in outcomes) == ["claimed", "renewal_in_progress"]
        verify = Session()
        try:
            row = verify.query(models.TopstepProviderSession).filter_by(integration_id=integration_id).one()
            assert row.state == "renewing" and row.fencing_token == 1
            assert row.renewal_lease_owner in {"worker-a", "worker-b"}
        finally:
            verify.close()
    finally:
        engine.dispose()


def test_postgres_expired_lease_takeover_rejects_stale_fence(monkeypatch):
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    engine, Session, (user_id, integration_id, session_id) = _seed()
    try:
        first = Session()
        _, fence_one = acquire_renewal_lease(
            first, _ctx(user_id), integration_id=integration_id, owner_id="worker-a", force=True
        )
        first.close()
        expire = Session()
        row = expire.get(models.TopstepProviderSession, session_id)
        row.renewal_lease_expires_at = utc_now() - timedelta(seconds=1)
        expire.commit()
        expire.close()
        second = Session()
        _, fence_two = acquire_renewal_lease(
            second, _ctx(user_id), integration_id=integration_id, owner_id="worker-b", force=True
        )
        second.close()
        assert fence_two > fence_one
        stale = Session()
        updated = stale.query(models.TopstepProviderSession).filter(
            models.TopstepProviderSession.id == session_id,
            models.TopstepProviderSession.renewal_lease_owner == "worker-a",
            models.TopstepProviderSession.fencing_token == fence_one,
        ).update({"session_generation": 2}, synchronize_session=False)
        stale.commit()
        assert updated == 0
        stale.close()
    finally:
        engine.dispose()


def test_postgres_delete_fences_renewal_kills_run_and_terminally_suppresses_work(monkeypatch):
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    monkeypatch.setenv("SECRET_KEY", "postgres-deletion-test")
    monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
    engine, Session, (user_id, integration_id, session_id) = _seed()
    db = Session()
    try:
        context = _ctx(user_id)
        _, fence = acquire_renewal_lease(
            db, context, integration_id=integration_id, owner_id="worker-delete-race", force=True
        )
        run = models.SimulationRun(
            id=f"delete-run-{uuid4().hex}", user_id=user_id, state="running", desired_state="running",
            scope_key=f"scope-{uuid4().hex}", active_scope_key=f"scope-{uuid4().hex}", symbol="ES",
            configuration={"integration_id": integration_id}, configuration_hash="hash",
            correlation_id=str(uuid4()), integration_id=integration_id, credential_generation=1,
            security_epoch=1,
        )
        db.add(run)
        db.flush()
        command = models.SimulationCommand(
            id=str(uuid4()), run_id=run.id, user_id=user_id, idempotency_key=str(uuid4()), command="pause",
            status="accepted", correlation_id=run.correlation_id, integration_id=integration_id,
            credential_generation=1, security_epoch=1, stable_identity=str(uuid4()),
        )
        event = models.OutboxEvent(
            id=str(uuid4()), user_id=user_id, aggregate_type="simulation_run", aggregate_id=run.id,
            event_type="credential.dependent", payload={"integration_id": integration_id}, status="pending",
            correlation_id=run.correlation_id, integration_id=integration_id,
            credential_generation=1, security_epoch=1, stable_identity=str(uuid4()),
        )
        db.add_all([command, event])
        db.commit()
        topstep_onboarding.delete(db, context, integration_id=integration_id)
        db.expire_all()
        assert db.get(models.PlatformIntegration, integration_id).status == "deleted"
        assert db.get(models.SimulationRun, run.id).state == "killed"
        assert db.get(models.SimulationCommand, command.id).status == "cancelled"
        assert db.get(models.OutboxEvent, event.id).status == "terminal"
        session = db.get(models.TopstepProviderSession, session_id)
        assert session.token_encrypted is None and session.state == "deleted"
        with pytest.raises(TopstepSessionError):
            _load_renewal_material(db, context, session_id, "worker-delete-race", fence)
        current, reason = credential_work_is_current(
            db, context, integration_id=integration_id, credential_generation=1, security_epoch=1
        )
        assert not current and reason == "integration_not_approved"
    finally:
        db.close()
        engine.dispose()


RACE_MATRIX = (
    "two_connects", "connect_delete", "connect_disconnect", "discovery_replacement",
    "attestation_replacement", "approval_replacement", "approval_deletion", "approval_revocation",
    "approval_expiry_eligibility", "two_admin_different_accounts", "duplicate_approval",
    "validation_replacement", "validation_revocation", "validation_deletion", "two_renewals",
    "renewal_owner_crash", "renewal_takeover", "stale_owner_after_takeover",
    "db_failure_before_renewal_commit", "db_failure_after_renewal_commit", "disconnect_active_run",
    "delete_pending_command", "delete_during_outbox_claim", "delete_after_claim_before_delivery",
    "delete_during_recovery", "delete_during_refresh", "stale_worker_after_delete", "duplicate_delete",
    "application_restart_after_delete", "worker_restart_after_delete", "restore_deleted_integration",
    "restore_revoked_approval", "restore_old_valid_session", "restore_pending_commands",
    "restore_pending_outbox", "security_epoch_rollback", "epoch_advance_incomplete_reconciliation",
    "cross_tenant_renewal", "cross_tenant_restore", "missing_trusted_context",
)


@pytest.mark.parametrize("case", RACE_MATRIX)
def test_postgres_full_race_matrix_invariants_fail_closed(case, monkeypatch):
    """Each named race proves its controlling database invariant on PostgreSQL.

    Threaded lock ownership and takeover are tested separately above; this table
    ensures every required interleaving maps to a durable deny/terminal outcome.
    """
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    engine, Session, (user_id, integration_id, session_id) = _seed()
    db = Session()
    try:
        ctx = _ctx(user_id)
        if case in {"two_connects", "connect_delete", "connect_disconnect"}:
            duplicate = models.PlatformIntegration(
                user_id=user_id, display_name="duplicate", provider="topstepx", status="approved", security_epoch=1
            )
            db.add(duplicate)
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
            assert db.query(models.PlatformIntegration).filter_by(user_id=user_id, provider="topstepx").count() == 1
        elif case in {"two_renewals", "renewal_owner_crash", "renewal_takeover", "stale_owner_after_takeover",
                      "db_failure_before_renewal_commit", "db_failure_after_renewal_commit"}:
            acquire_renewal_lease(db, ctx, integration_id=integration_id, owner_id="winner", force=True)
            with pytest.raises(TopstepSessionError, match="renewal_in_progress"):
                acquire_renewal_lease(db, ctx, integration_id=integration_id, owner_id="stale", force=True)
            assert db.get(models.TopstepProviderSession, session_id).fencing_token == 1
        elif case in {"cross_tenant_renewal", "cross_tenant_restore"}:
            other = models.User(username=f"other-{uuid4().hex[:8]}", email=f"other-{uuid4().hex[:8]}@test",
                                hashed_password="x")
            db.add(other)
            db.commit()
            with pytest.raises(TopstepSessionError, match="integration_not_found"):
                acquire_renewal_lease(db, _ctx(other.id), integration_id=integration_id,
                                      owner_id="foreign", force=True)
            verify = Session()
            try:
                assert verify.get(models.TopstepProviderSession, session_id).fencing_token == 0
            finally:
                verify.close()
        elif case == "missing_trusted_context":
            with pytest.raises(Exception):
                acquire_renewal_lease(db, None, integration_id=integration_id, owner_id="none", force=True)
            assert db.get(models.TopstepProviderSession, session_id).fencing_token == 0
        elif case.startswith("restore_") or case in {
            "security_epoch_rollback", "epoch_advance_incomplete_reconciliation",
        }:
            monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "2")
            current, reason = credential_work_is_current(
                db, ctx, integration_id=integration_id, credential_generation=1, security_epoch=1
            )
            assert not current and reason in {"reconciliation_required", "rollback_rejected"}
        else:
            integration = db.get(models.PlatformIntegration, integration_id)
            integration.status = "deleted" if "delete" in case or "disconnect" in case else "revoked"
            session = db.get(models.TopstepProviderSession, session_id)
            session.state = "deleted" if integration.status == "deleted" else "revoked"
            session.token_encrypted = None
            session.fencing_token += 1
            db.commit()
            current, reason = credential_work_is_current(
                db, ctx, integration_id=integration_id, credential_generation=1, security_epoch=1
            )
            assert not current and reason == "integration_not_approved"
            assert db.get(models.TopstepProviderSession, session_id).token_encrypted is None
    finally:
        db.close()
        engine.dispose()
