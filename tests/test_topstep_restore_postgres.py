from datetime import timedelta
from os import getenv
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import OperatorContext
from app.time_utils import utc_now
from app.topstep_session_security import reconcile_restored_database, security_epoch_status


POSTGRES_URL = getenv("HOSTED_RESTORE_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="HOSTED_RESTORE_POSTGRES_TEST_URL is required")


def test_postgres_restored_backup_revokes_access_and_suppresses_all_work(monkeypatch):
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "2")
    monkeypatch.setenv("TOPSTEP_PROVIDER_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("HOSTED_WORKER_PROCESSING_ENABLED", "false")
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    existing_tables = set(inspect(engine).get_table_names())
    if existing_tables:
        engine.dispose()
        pytest.fail("HOSTED_RESTORE_POSTGRES_TEST_URL must target an empty, dedicated database; refusing destructive reset")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    now = utc_now()
    suffix = uuid4().hex[:10]
    tester = models.User(username=f"restore-{suffix}", email=f"restore-{suffix}@test", hashed_password="x",
                         account_status="active")
    operator_user = models.User(username=f"restore-admin-{suffix}", email=f"restore-admin-{suffix}@test",
                                hashed_password="x", is_admin=1)
    db.add_all([tester, operator_user])
    db.flush()
    integration = models.PlatformIntegration(
        user_id=tester.id, display_name="Topstep", provider="topstepx", status="approved",
        security_epoch=1, integration_metadata={"credential_generation": 1},
    )
    db.add(integration)
    db.flush()
    credential = models.TopstepCredential(
        user_id=tester.id, integration_id=integration.id, lifecycle_status="validated",
        username_encrypted="encrypted-username", api_key_encrypted="encrypted-api-key",
        credential_fingerprint=f"fingerprint-{suffix}", encryption_key_version="v1",
        credential_generation=1, security_epoch=1,
    )
    db.add(credential)
    db.flush()
    provider_session = models.TopstepProviderSession(
        user_id=tester.id, integration_id=integration.id, credential_id=credential.id,
        credential_generation=1, security_epoch=1, state="valid", session_generation=3,
        token_encrypted="encrypted-session", issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=23), renewal_not_before=now + timedelta(hours=21),
    )
    db.add(provider_session)
    snapshot = models.TopstepDiscoverySnapshot(
        id=str(uuid4()), user_id=tester.id, integration_id=integration.id, credential_id=credential.id,
        credential_generation=1, security_epoch=1, discovered_at=now, expires_at=now + timedelta(hours=1),
        safe_response_hash="safe-hash", provider_status="success",
    )
    db.add(snapshot)
    db.flush()
    account = models.TopstepDiscoveredAccount(
        user_id=tester.id, integration_id=integration.id, snapshot_id=snapshot.id,
        provider_account_id="redacted-account", safe_display_label="Combine display",
        can_trade=1, is_visible=1, is_active=1, first_observed_at=now, last_observed_at=now,
    )
    db.add(account)
    db.flush()
    attestation = models.TopstepCombineAttestation(
        id=str(uuid4()), user_id=tester.id, integration_id=integration.id, discovered_account_id=account.id,
        credential_generation=1, security_epoch=1, provider_account_id=account.provider_account_id,
        attestation_version="topstep-combine-v1", attestation_text="attested", accepted_at=now,
        expires_at=now + timedelta(days=1), correlation_id=str(uuid4()),
    )
    db.add(attestation)
    db.flush()
    approval = models.TopstepAccountApproval(
        id=str(uuid4()), user_id=tester.id, integration_id=integration.id, discovered_account_id=account.id,
        attestation_id=attestation.id, credential_generation=1, security_epoch=1,
        provider_account_id=account.provider_account_id, cohort="restore-test", state="approved",
        approving_operator_id=operator_user.id, operator_context={"action": "approve"},
        purpose="restore test approval", case_reference="RESTORE-CASE", approved_at=now,
        expires_at=now + timedelta(days=1), correlation_id=str(uuid4()),
    )
    db.add(approval)
    run = models.SimulationRun(
        id=f"restore-run-{suffix}", user_id=tester.id, state="running", desired_state="running",
        scope_key=f"restore-scope-{suffix}", active_scope_key=f"restore-active-{suffix}", symbol="ES",
        configuration={"integration_id": integration.id}, configuration_hash="hash",
        correlation_id=str(uuid4()), integration_id=integration.id, credential_generation=1, security_epoch=1,
    )
    db.add(run)
    db.flush()
    command = models.SimulationCommand(
        id=str(uuid4()), run_id=run.id, user_id=tester.id, idempotency_key=str(uuid4()), command="start",
        status="accepted", correlation_id=run.correlation_id, integration_id=integration.id,
        credential_generation=1, security_epoch=1, stable_identity=str(uuid4()),
    )
    outbox = models.OutboxEvent(
        id=str(uuid4()), user_id=tester.id, aggregate_type="simulation_run", aggregate_id=run.id,
        event_type="credential-work", payload={"integration_id": integration.id}, status="pending",
        correlation_id=run.correlation_id, integration_id=integration.id, credential_generation=1,
        security_epoch=1, stable_identity=str(uuid4()),
    )
    db.add_all([command, outbox, models.HostedSecurityEpoch(id=1, database_epoch=1, reconciliation_state="ready")])
    db.commit()

    operator = OperatorContext(
        actor_user_id=operator_user.id, target_tenant_id=tester.id,
        purpose="Restore hosted Topstep database", case_id="RESTORE-CASE", action="restore-reconciliation",
        correlation_id=f"restore-{suffix}", created_at=now, expires_at=now + timedelta(minutes=10),
        permissions=("restore:reconcile",),
    )
    result = reconcile_restored_database(db, operator)
    db.expire_all()
    assert result.state == "completed"
    assert db.get(models.HostedSecurityEpoch, 1).database_epoch == 2
    assert db.get(models.PlatformIntegration, integration.id).status == "suspended"
    assert db.get(models.TopstepCredential, credential.id).api_key_encrypted is None
    assert db.get(models.TopstepProviderSession, provider_session.id).token_encrypted is None
    assert db.get(models.TopstepAccountApproval, approval.id).state == "revoked"
    assert db.get(models.TopstepCombineAttestation, attestation.id).revoked_at is not None
    assert db.get(models.TopstepDiscoverySnapshot, snapshot.id).is_current == 0
    assert db.get(models.SimulationRun, run.id).state == "killed"
    assert db.get(models.SimulationCommand, command.id).status == "cancelled"
    assert db.get(models.OutboxEvent, outbox.id).status == "terminal"
    assert security_epoch_status(db).ready  # epoch is reconciled; integration remains suspended and revoked

    retry = reconcile_restored_database(db, operator)
    assert retry.id == result.id and db.query(models.HostedRestoreReconciliation).count() == 1
    monkeypatch.setenv("HOSTED_SECURITY_EPOCH", "1")
    assert security_epoch_status(db).state == "rollback_rejected"
    db.close()
    engine.dispose()
