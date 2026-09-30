from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, topstep_onboarding
from app.authorization import OperatorContext, TenantContext
from app.providers.base import ProviderError
from app.durable_simulation import create_run
from app.time_utils import utc_now
from app.topstep_session_security import (
    TopstepSessionError,
    _load_renewal_material,
    acquire_renewal_lease,
    credential_work_is_current,
    heartbeat_renewal_lease,
    reconcile_restored_database,
    renew_session,
    security_epoch_status,
)


class OnboardingProvider:
    def __init__(self, credentials):
        self.credentials = credentials

    def authenticate_session(self):
        return "initial-provider-token", utc_now() + timedelta(hours=23)

    def safe_accounts_for_session(self, token):
        assert token == "initial-provider-token"
        return [{"id": "account-1", "name": "Safe label", "canTrade": True, "isVisible": True}]


class RenewalProvider:
    calls = 0

    def __init__(self, credentials):
        self.credentials = credentials

    def validate_session(self, token):
        assert token == "initial-provider-token"
        type(self).calls += 1
        return "renewed-provider-token", utc_now() + timedelta(hours=23)


class ReauthenticationProvider(RenewalProvider):
    def validate_session(self, token):
        raise ProviderError("safe", code="auth_invalid_session")

    def authenticate_session(self):
        assert self.credentials == {"userName": "platform-user", "apiKey": "api-secret-123"}
        return "reauthenticated-token", utc_now() + timedelta(hours=23)


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "session-security-test")
    monkeypatch.setenv("KEY_MANAGEMENT_PROVIDER", "local-development")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    monkeypatch.setenv("TOPSTEP_BETA_COHORT_ENABLED", "true")
    monkeypatch.setenv("TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES", "120")
    engine = create_engine(f"sqlite:///{tmp_path / 'session-security.db'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tester = models.User(username="tester", email="tester@session.test", hashed_password="x", account_status="active")
    admin = models.User(username="admin", email="admin@session.test", hashed_password="x", is_admin=1)
    db.add_all([tester, admin])
    db.flush()
    db.add(models.UserBetaStatus(user_id=tester.id, status="active"))
    db.commit()
    ctx = TenantContext(tester.id, "tester", actor_user_id=tester.id, source="session")
    integration = topstep_onboarding.connect(
        db, ctx, username="platform-user", api_key="api-secret-123", provider_factory=OnboardingProvider
    )
    yield engine, Session, db, ctx, tester.id, admin.id, integration.id
    db.close()
    engine.dispose()


def _operator(tenant_id, admin_id, correlation="restore-1"):
    now = utc_now()
    return OperatorContext(
        actor_user_id=admin_id, target_tenant_id=tenant_id,
        purpose="Reconcile restored hosted database", case_id="RESTORE-1", action="restore",
        correlation_id=correlation, created_at=now, expires_at=now + timedelta(minutes=10),
        permissions=("restore:reconcile",),
    )


def test_session_renewal_is_database_authoritative_and_advances_generation(state):
    _, _, db, ctx, _, _, integration_id = state
    RenewalProvider.calls = 0
    before = db.query(models.TopstepProviderSession).one()
    original_ciphertext = before.token_encrypted
    renewed = renew_session(
        db, ctx, integration_id=integration_id, owner_id="worker-a",
        provider_factory=RenewalProvider, force=True,
    )
    assert RenewalProvider.calls == 1
    assert renewed.state == "valid" and renewed.session_generation == 2 and renewed.fencing_token == 1
    assert renewed.token_encrypted != original_ciphertext
    assert "renewed-provider-token" not in renewed.token_encrypted
    assert renewed.renewal_lease_owner is None


def test_invalid_session_may_reauthenticate_only_current_generation(state):
    _, _, db, ctx, _, _, integration_id = state
    renewed = renew_session(
        db, ctx, integration_id=integration_id, owner_id="worker-a",
        provider_factory=ReauthenticationProvider, force=True,
    )
    assert renewed.session_generation == 2 and renewed.state == "valid"
    credential = db.query(models.TopstepCredential).filter_by(is_current=1).one()
    assert credential.last_auth_succeeded_at is not None


def test_simulation_run_binds_topstep_generation_and_epoch_from_database(state):
    _, _, db, ctx, _, _, integration_id = state
    run = create_run(
        db, ctx, symbol="ES",
        configuration={"integration_id": integration_id, "credential_generation": 999, "security_epoch": 999},
    )
    assert run.integration_id == integration_id
    assert run.credential_generation == 1 and run.security_epoch == 1
    assert run.configuration["credential_generation"] == 1
    assert run.configuration["security_epoch"] == 1


def test_concurrent_lease_is_single_flight_and_expired_lease_can_be_taken_over(state):
    _, _, db, ctx, _, _, integration_id = state
    session_id, first_fence = acquire_renewal_lease(
        db, ctx, integration_id=integration_id, owner_id="worker-a", force=True
    )
    with pytest.raises(TopstepSessionError, match="renewal_in_progress"):
        acquire_renewal_lease(db, ctx, integration_id=integration_id, owner_id="worker-b", force=True)
    row = db.get(models.TopstepProviderSession, session_id)
    row.renewal_lease_expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    _, second_fence = acquire_renewal_lease(
        db, ctx, integration_id=integration_id, owner_id="worker-b", force=True
    )
    assert second_fence > first_fence
    with pytest.raises(TopstepSessionError, match="stale_renewal_fence"):
        _load_renewal_material(db, ctx, session_id, "worker-a", first_fence)


def test_renewal_owner_cannot_commit_after_lease_expiry_without_takeover(state):
    _, _, db, ctx, _, _, integration_id = state
    session_id, fence = acquire_renewal_lease(
        db, ctx, integration_id=integration_id, owner_id="worker-a", force=True
    )
    row = db.get(models.TopstepProviderSession, session_id)
    row.renewal_lease_expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(TopstepSessionError, match="stale_renewal_fence"):
        _load_renewal_material(db, ctx, session_id, "worker-a", fence)


def test_replacement_and_deletion_win_over_stale_renewal(state):
    _, _, db, ctx, _, _, integration_id = state
    session_id, fence = acquire_renewal_lease(
        db, ctx, integration_id=integration_id, owner_id="worker-a", force=True
    )
    topstep_onboarding.replace_credentials(
        db, ctx, integration_id=integration_id, username="platform-user",
        api_key="replacement-api-key", provider_factory=OnboardingProvider,
    )
    with pytest.raises(TopstepSessionError, match="stale_renewal_fence"):
        _load_renewal_material(db, ctx, session_id, "worker-a", fence)
    topstep_onboarding.delete(db, ctx, integration_id=integration_id)
    sessions = db.query(models.TopstepProviderSession).all()
    assert all(row.token_encrypted is None and row.state == "deleted" for row in sessions)


def test_failure_before_commit_never_advances_session_generation(state):
    _, _, db, ctx, _, _, integration_id = state

    def fail(point):
        if point == "after_encryption":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        renew_session(
            db, ctx, integration_id=integration_id, owner_id="worker-a",
            provider_factory=RenewalProvider, force=True, failure_injector=fail,
        )
    row = db.query(models.TopstepProviderSession).one()
    assert row.session_generation == 1 and row.state in {"failed", "expired"}
    assert "renewed-provider-token" not in (row.token_encrypted or "")


@pytest.mark.parametrize("point", (
    "before_provider_validation", "after_provider_response", "after_encryption",
    "during_audit_persistence", "before_session_commit", "after_session_commit",
))
def test_renewal_failure_injection_is_fail_closed(state, point):
    _, _, db, ctx, _, _, integration_id = state

    def fail(actual):
        if actual == point:
            raise RuntimeError(f"injected:{point}")

    with pytest.raises(RuntimeError, match="injected"):
        renew_session(
            db, ctx, integration_id=integration_id, owner_id="worker-a",
            provider_factory=RenewalProvider, force=True, failure_injector=fail,
        )
    row = db.query(models.TopstepProviderSession).one()
    if point == "after_session_commit":
        assert row.state == "valid" and row.session_generation == 2
    else:
        assert row.state in {"failed", "expired"} and row.session_generation == 1


def test_lease_heartbeat_requires_current_fence(state):
    _, _, db, ctx, _, _, integration_id = state
    session_id, fence = acquire_renewal_lease(
        db, ctx, integration_id=integration_id, owner_id="worker-a", force=True
    )
    heartbeat_renewal_lease(db, ctx, session_id=session_id, owner_id="worker-a", fence=fence)
    with pytest.raises(TopstepSessionError, match="stale_renewal_fence"):
        heartbeat_renewal_lease(db, ctx, session_id=session_id, owner_id="worker-a", fence=fence - 1)


@pytest.mark.parametrize("operation,point", (
    ("replace", "during_replacement"),
    ("revoke", "during_revocation"),
    ("delete", "during_deletion"),
))
def test_lifecycle_failure_injection_rolls_back_without_renewal(operation, point, state):
    _, _, db, ctx, tenant_id, admin_id, integration_id = state

    def fail(actual):
        if actual == point:
            raise RuntimeError(f"injected:{point}")

    if operation == "revoke":
        db.get(models.PlatformIntegration, integration_id).status = "approved"
        db.commit()
    before = db.query(models.TopstepProviderSession).one()
    before_fence = before.fencing_token
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "replace":
            topstep_onboarding.replace_credentials(
                db, ctx, integration_id=integration_id, username="replacement",
                api_key="replacement-key", provider_factory=OnboardingProvider,
                failure_injector=fail,
            )
        elif operation == "revoke":
            topstep_onboarding.revoke(
                db, _operator(tenant_id, admin_id), integration_id=integration_id,
                classification="test", failure_injector=fail,
            )
        else:
            topstep_onboarding.delete(db, ctx, integration_id=integration_id, failure_injector=fail)
    db.rollback()
    session = db.query(models.TopstepProviderSession).one()
    assert session.state == "valid" and session.fencing_token == before_fence


def test_security_epoch_mismatch_denies_work_and_eligibility(state, monkeypatch):
    _, _, db, ctx, _, _, integration_id = state
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "2")
    status = security_epoch_status(db)
    assert status.state == "reconciliation_required" and not status.ready
    current, reason = credential_work_is_current(
        db, ctx, integration_id=integration_id, credential_generation=1, security_epoch=1
    )
    assert not current and reason == "reconciliation_required"
    decision = topstep_onboarding.execution_eligibility(
        db, ctx, integration_id=integration_id, provider_account_id="account-1"
    )
    assert not decision.allowed and decision.reason == "reconciliation_required"


def test_restore_reconciliation_erases_secrets_and_suppresses_stale_work(state, monkeypatch):
    _, _, db, ctx, tenant_id, admin_id, integration_id = state
    integration = db.get(models.PlatformIntegration, integration_id)
    integration.status = "approved"
    run = models.SimulationRun(
        id="restore-run", user_id=tenant_id, state="running", desired_state="running",
        scope_key="restore", active_scope_key="restore", symbol="ES", configuration={"integration_id": integration_id},
        configuration_hash="hash", correlation_id="corr", integration_id=integration_id,
        credential_generation=1, security_epoch=1,
    )
    db.add(run)
    db.add(models.SimulationCommand(
        id="restore-command", run_id=run.id, user_id=tenant_id, idempotency_key="restore-command",
        command="start", status="accepted", correlation_id="corr", integration_id=integration_id,
        credential_generation=1, security_epoch=1, stable_identity="restore-command",
    ))
    db.add(models.OutboxEvent(
        id="restore-outbox", user_id=tenant_id, aggregate_type="simulation_run", aggregate_id=run.id,
        event_type="credential.work", payload={"integration_id": integration_id}, correlation_id="corr",
        integration_id=integration_id, credential_generation=1, security_epoch=1, stable_identity="restore-outbox",
    ))
    db.commit()
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "2")
    result = reconcile_restored_database(db, _operator(tenant_id, admin_id))
    assert result.state == "completed" and result.integrations_suppressed == 1
    assert db.get(models.HostedSecurityEpoch, 1).database_epoch == 2
    assert db.get(models.PlatformIntegration, integration_id).status == "suspended"
    assert db.query(models.TopstepCredential).one().api_key_encrypted is None
    assert db.query(models.TopstepProviderSession).one().token_encrypted is None
    assert db.get(models.SimulationRun, "restore-run").state == "killed"
    assert db.get(models.SimulationCommand, "restore-command").status == "cancelled"
    assert db.get(models.OutboxEvent, "restore-outbox").status == "terminal"
    decision = topstep_onboarding.execution_eligibility(
        db, ctx, integration_id=integration_id, provider_account_id="account-1"
    )
    assert not decision.allowed


def test_epoch_rollback_and_incomplete_reconciliation_fail_closed(state, monkeypatch):
    _, _, db, ctx, tenant_id, admin_id, integration_id = state
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "2")

    def fail(point):
        if point == "before_epoch_advance":
            raise RuntimeError("restore interrupted")

    with pytest.raises(RuntimeError, match="restore interrupted"):
        reconcile_restored_database(db, _operator(tenant_id, admin_id), failure_injector=fail)
    db.rollback()
    assert not security_epoch_status(db).ready
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    row = db.get(models.HostedSecurityEpoch, 1)
    row.database_epoch = 2
    db.commit()
    assert security_epoch_status(db).state == "rollback_rejected"
    current, _ = credential_work_is_current(
        db, ctx, integration_id=integration_id, credential_generation=1, security_epoch=1
    )
    assert not current


def test_restore_reconciliation_rejects_expired_operator_context(state):
    _, _, db, _, tenant_id, admin_id, _ = state
    op = _operator(tenant_id, admin_id)
    expired = OperatorContext(
        actor_user_id=op.actor_user_id, target_tenant_id=op.target_tenant_id,
        purpose=op.purpose, case_id=op.case_id, action=op.action,
        correlation_id=op.correlation_id, created_at=op.created_at,
        expires_at=utc_now() + timedelta(minutes=5), permissions=op.permissions,
    )
    object.__setattr__(expired, "expires_at", utc_now() - timedelta(seconds=1))
    with pytest.raises(TopstepSessionError, match="restore_operator_context_expired"):
        reconcile_restored_database(db, expired)
