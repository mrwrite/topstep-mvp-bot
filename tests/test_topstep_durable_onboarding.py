from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import OperatorContext, TenantContext
from app.time_utils import utc_now
from app import topstep_onboarding as service


class FakeTopstep:
    def __init__(self, credentials):
        if credentials["apiKey"] == "rejected-key":
            raise service.TopstepWorkflowError("provider_auth_failed")
        self.credentials = credentials

    def authenticate_session(self):
        return "provider-session-secret", utc_now() + timedelta(hours=2)

    def safe_accounts_for_session(self, token):
        assert token == "provider-session-secret"
        return [
            {"id": "combine-123", "name": "Safe label", "canTrade": True, "isVisible": True},
            {"id": "not-approved", "name": "Other", "canTrade": True, "isVisible": True},
        ]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("KEY_MANAGEMENT_PROVIDER", "local-development")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TOPSTEP_BETA_COHORT_ENABLED", "true")
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.db'}")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tester = models.User(username="tester", email="tester@example.test", hashed_password="x", account_status="active")
    operator = models.User(username="operator", email="operator@example.test", hashed_password="x", is_admin=1)
    session.add_all([tester, operator])
    session.flush()
    session.add(models.UserBetaStatus(user_id=tester.id, status="active"))
    session.commit()
    yield session, tester.id, operator.id
    session.close()


def tenant(user_id):
    return TenantContext(user_id=user_id, username="tester", actor_user_id=user_id, source="session")


def operator(user_id, operator_id):
    now = utc_now()
    return OperatorContext(actor_user_id=operator_id, target_tenant_id=user_id,
                           purpose="Approve one Combine account", case_id="CASE-1",
                           action="approve", correlation_id="corr-operator", created_at=now,
                           expires_at=now + timedelta(minutes=5), permissions=("approve",))


def onboard_attest_approve(db, user_id, operator_id):
    ctx = tenant(user_id)
    integration = service.connect(db, ctx, username="platform-user", api_key="api-secret-123",
                                  provider_factory=FakeTopstep)
    attestation = service.attest(db, ctx, integration_id=integration.id,
                                 provider_account_id="combine-123", accepted=True,
                                 attestation_version=service.ATTESTATION_VERSION)
    approval = service.approve(db, operator(user_id, operator_id), integration_id=integration.id,
                               provider_account_id="combine-123", attestation_id=attestation.id,
                               expires_at=utc_now() + timedelta(hours=1), cohort="initial-tester")
    return ctx, integration, approval


def test_connect_persists_encrypted_generation_session_and_safe_snapshot(db):
    session, user_id, _ = db
    ctx = tenant(user_id)
    integration = service.connect(session, ctx, username="platform-user", api_key="api-secret-123",
                                  provider_factory=FakeTopstep)
    credential = session.query(models.TopstepCredential).one()
    provider_session = session.query(models.TopstepProviderSession).one()
    assert integration.status == "awaiting_attestation"
    assert credential.credential_generation == 1 and credential.is_current == 1
    assert "platform-user" not in credential.username_encrypted
    assert "api-secret-123" not in credential.api_key_encrypted
    assert "provider-session-secret" not in provider_session.token_encrypted
    assert {x.provider_account_id for x in service.accounts(session, ctx, integration.id)} == {
        "combine-123", "not-approved"
    }
    audit_text = repr(session.query(models.SecurityAuditEvent).all())
    assert "api-secret-123" not in audit_text and "provider-session-secret" not in audit_text


def test_attestation_requires_current_discovery_and_does_not_approve(db):
    session, user_id, _ = db
    ctx = tenant(user_id)
    integration = service.connect(session, ctx, username="u", api_key="api-secret-123",
                                  provider_factory=FakeTopstep)
    with pytest.raises(service.TopstepWorkflowError, match="discovered_account_not_found"):
        service.attest(session, ctx, integration_id=integration.id, provider_account_id="client-injected",
                       accepted=True, attestation_version=service.ATTESTATION_VERSION)
    row = service.attest(session, ctx, integration_id=integration.id, provider_account_id="combine-123",
                         accepted=True, attestation_version=service.ATTESTATION_VERSION)
    assert row.attestation_text == service.ATTESTATION_TEXT
    assert integration.status == "awaiting_approval"


def test_exact_operator_approval_drives_one_authoritative_eligibility_decision(db):
    session, user_id, operator_id = db
    ctx, integration, approval = onboard_attest_approve(session, user_id, operator_id)
    assert approval.credential_generation == 1
    assert service.execution_eligibility(session, ctx, integration_id=integration.id,
                                         provider_account_id="combine-123").allowed
    denied = service.execution_eligibility(session, ctx, integration_id=integration.id,
                                           provider_account_id="not-approved")
    assert not denied.allowed and denied.reason == "attestation_not_current"
    assert session.query(models.TopstepAccountApproval).filter_by(state="approved").count() == 1


def test_replacement_failure_preserves_old_then_success_invalidates_authorization(db):
    session, user_id, operator_id = db
    ctx, integration, _ = onboard_attest_approve(session, user_id, operator_id)
    with pytest.raises(service.TopstepWorkflowError, match="provider_auth_failed"):
        service.replace_credentials(session, ctx, integration_id=integration.id, username="u",
                                    api_key="rejected-key", provider_factory=FakeTopstep)
    assert session.query(models.TopstepCredential).filter_by(is_current=1).one().credential_generation == 1
    service.replace_credentials(session, ctx, integration_id=integration.id, username="u2",
                                api_key="new-api-secret", provider_factory=FakeTopstep)
    assert integration.status == "awaiting_attestation"
    assert session.query(models.TopstepCredential).filter_by(is_current=1).one().credential_generation == 2
    assert session.query(models.TopstepAccountApproval).filter_by(state="approved").count() == 0
    assert not service.execution_eligibility(session, ctx, integration_id=integration.id,
                                             provider_account_id="combine-123").allowed


def test_delete_is_idempotent_erases_secrets_and_suppresses_work(db):
    session, user_id, operator_id = db
    ctx, integration, _ = onboard_attest_approve(session, user_id, operator_id)
    run = models.SimulationRun(id="run-delete", user_id=user_id, state="running", desired_state="running",
        scope_key="s", active_scope_key="s", symbol="ES", configuration={"integration_id": integration.id},
        configuration_hash="h", correlation_id="c")
    session.add(run)
    session.add(models.OutboxEvent(id="event-delete", user_id=user_id, aggregate_type="simulation-run",
        aggregate_id=run.id, event_type="continue", payload={"integration_id": integration.id},
        correlation_id="c"))
    session.commit()
    service.delete(session, ctx, integration_id=integration.id)
    service.delete(session, ctx, integration_id=integration.id)
    credential = session.query(models.TopstepCredential).filter_by(user_id=user_id).one()
    assert integration.status == "deleted"
    assert credential.api_key_encrypted is None and credential.username_encrypted is None
    assert session.query(models.TopstepProviderSession).one().token_encrypted is None
    assert session.query(models.TopstepIntegrationTombstone).count() == 1
    assert run.state == "killed"
    assert session.query(models.OutboxEvent).one().status == "terminal"
    assert not service.execution_eligibility(session, ctx, integration_id=integration.id,
                                             provider_account_id="combine-123").allowed


def test_new_onboarding_after_deletion_requires_a_new_idempotency_identity(db):
    session, user_id, _ = db
    ctx = tenant(user_id)
    first = service.connect(session, ctx, username="u", api_key="api-secret-123",
                             provider_factory=FakeTopstep, idempotency_key="connect-request-1")
    service.delete(session, ctx, integration_id=first.id)
    with pytest.raises(service.TopstepWorkflowError, match="deleted_integration_terminal"):
        service.connect(session, ctx, username="u", api_key="api-secret-123",
                         provider_factory=FakeTopstep, idempotency_key="connect-request-1")
    second = service.connect(session, ctx, username="u", api_key="new-api-secret-456",
                             provider_factory=FakeTopstep, idempotency_key="connect-request-2")
    assert second.id != first.id and second.status == "awaiting_attestation"
    assert session.query(models.PlatformIntegration).filter_by(user_id=user_id, provider="topstepx").count() == 2


def test_cross_tenant_lookup_is_not_found(db):
    session, user_id, _ = db
    integration = service.connect(session, tenant(user_id), username="u", api_key="api-secret-123",
                                  provider_factory=FakeTopstep)
    other = models.User(username="other", email="other@example.test", hashed_password="x")
    session.info.clear()
    session.add(other)
    session.commit()
    with pytest.raises(service.TopstepWorkflowError, match="integration_not_found"):
        service.accounts(session, tenant(other.id), integration.id)


def test_stale_lifecycle_version_is_rejected_and_disconnect_is_terminal(db):
    session, user_id, _ = db
    ctx = tenant(user_id)
    integration = service.connect(session, ctx, username="u", api_key="api-secret-123",
                                  provider_factory=FakeTopstep)
    with pytest.raises(service.TopstepWorkflowError, match="stale_lifecycle_version"):
        service.attest(session, ctx, integration_id=integration.id, provider_account_id="combine-123",
                       accepted=True, attestation_version=service.ATTESTATION_VERSION,
                       expected_version=integration.lifecycle_version - 1)
    service.disconnect(session, ctx, integration_id=integration.id,
                       expected_version=integration.lifecycle_version)
    assert integration.status == "deleted"
    assert session.query(models.TopstepIntegrationTombstone).count() == 1


def test_operator_emergency_suspension_revokes_approval_and_denies_eligibility(db):
    session, user_id, operator_id = db
    ctx, integration, _ = onboard_attest_approve(session, user_id, operator_id)
    service.deny_or_suspend(session, operator(user_id, operator_id), integration_id=integration.id,
                            classification="operator_emergency", action="integration_emergency_suspended",
                            expected_version=integration.lifecycle_version)
    assert integration.status == "suspended"
    assert session.query(models.TopstepAccountApproval).filter_by(state="approved").count() == 0
    assert not service.execution_eligibility(session, ctx, integration_id=integration.id,
                                             provider_account_id="combine-123").allowed
