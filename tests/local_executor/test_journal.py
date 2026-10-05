from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from local_executor.journal import (
    LOCAL_SCHEMA_REVISION,
    LocalJournal,
    LocalJournalError,
    apply_user_only_permissions,
    create_local_engine,
    upgrade_local_database,
    verify_local_database,
)
from local_executor.journal_models import (
    AccountBinding, Acknowledgement, AuditEvent, Consent, Installation,
    KillState, LifecycleTransition, MarketInput, OrderIntent, PolicyVersion,
    PositionSnapshot, ProviderOrder, QualificationEvidence, ReconciliationLock,
    ReconciliationRun, StrategyDecision, SubmissionAttempt, TelemetryOutbox, Trade,
)
from local_executor.journal_repository import enqueue_telemetry


def open_journal(tmp_path: Path) -> LocalJournal:
    return LocalJournal.open(tmp_path / "journal" / "local-executor.db", secure_permissions=False)


def seed_authority(session):
    now = datetime.now(timezone.utc)
    installation = Installation(software_version="fixture")
    session.add(installation)
    session.flush()
    binding = AccountBinding(
        installation_id=installation.id, credential_generation=1,
        provider_account_id="account-fixture", provider_account_hash="account-hash-fixture",
        account_attestation="practice", is_active=True,
    )
    policy = PolicyVersion(
        installation_id=installation.id, version=1, checksum="policy-checksum-fixture",
        policy={"quantity": 1}, is_active=True,
    )
    market = MarketInput(
        installation_id=installation.id, input_identity="input-fixture",
        contract_id="CON.F.US.MES.Z26", window_start=now - timedelta(minutes=5),
        window_end=now, payload_hash="market-hash-fixture",
    )
    session.add_all([binding, policy, market])
    session.flush()
    decision = StrategyDecision(
        installation_id=installation.id, market_input_id=market.id,
        strategy_version="strategy-v1", configuration_hash="configuration-hash-fixture",
        decision="BUY", rationale="fixture",
    )
    session.add(decision)
    session.flush()
    return installation, binding, policy, market, decision


def test_fresh_and_repeated_upgrade_create_supported_independent_schema(tmp_path):
    database = tmp_path / "fresh.db"
    upgrade_local_database(database)
    upgrade_local_database(database)
    engine = create_local_engine(database)
    try:
        status = verify_local_database(engine)
        assert status == {
            "integrity": "ok", "foreign_key_violations": 0,
            "revision": LOCAL_SCHEMA_REVISION, "journal_mode": "wal",
            "foreign_keys": 1, "busy_timeout": 5000,
        }
        with engine.connect() as connection:
            tables = {row[0] for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )}
        assert {
            "installations", "account_bindings", "policy_versions", "order_intents",
            "submission_attempts", "acknowledgements", "provider_orders", "trades",
            "position_snapshots", "reconciliation_locks", "reconciliation_runs",
            "audit_events", "telemetry_outbox",
        }.issubset(tables)
        assert "users" not in tables
        assert "topstep_credentials" not in tables
    finally:
        engine.dispose()


def test_authority_relationships_uniqueness_and_monotonic_sequences(tmp_path):
    journal = open_journal(tmp_path)
    try:
        with journal.session_factory.begin() as session:
            installation, binding, policy, _market, decision = seed_authority(session)
            consent = Consent(
                installation_id=installation.id, account_binding_id=binding.id,
                policy_version_id=policy.id, credential_generation=1,
                strategy_version="strategy-v1", configuration_hash="configuration-hash-fixture",
                consent_version="consent-v1",
            )
            intent = OrderIntent(
                installation_id=installation.id, account_binding_id=binding.id,
                strategy_decision_id=decision.id, policy_version_id=policy.id,
                custom_tag="local-fixture-tag", contract_id="CON.F.US.MES.Z26",
                side="BUY", order_type="market", quantity=1, risk_classification="allowed",
            )
            session.add_all([
                consent,
                LifecycleTransition(installation_id=installation.id, from_state="disabled",
                                    to_state="observe_only", reason="fixture"),
                QualificationEvidence(installation_id=installation.id, account_binding_id=binding.id,
                                      evidence_type="restart_drill", outcome="passed",
                                      evidence={"classification": "reconciled"}),
                KillState(installation_id=installation.id), intent,
            ])
            session.flush()
            attempt = SubmissionAttempt(intent_id=intent.id, attempt_number=1)
            session.add(attempt)
            session.flush()
            session.add_all([
                Acknowledgement(attempt_id=attempt.id, classification="accepted",
                                provider_order_id="provider-order-1",
                                response_hash="response-hash-fixture"),
                ProviderOrder(account_binding_id=binding.id, intent_id=intent.id,
                              provider_order_id="provider-order-1", custom_tag=intent.custom_tag,
                              status="open", contract_id=intent.contract_id, side="BUY", quantity=1),
                Trade(account_binding_id=binding.id, provider_trade_id="provider-trade-1",
                      provider_order_id="provider-order-1", contract_id=intent.contract_id,
                      side="BUY", quantity=1, price="5000.25", traded_at=datetime.now(timezone.utc)),
                PositionSnapshot(account_binding_id=binding.id, contract_id=intent.contract_id,
                                 quantity=1, average_price="5000.25"),
                ReconciliationRun(account_binding_id=binding.id, trigger="post_mutation"),
                ReconciliationLock(account_binding_id=binding.id, reason="fixture_ambiguity"),
                AuditEvent(installation_id=installation.id, classification="fixture",
                           correlation_id=str(uuid4()), payload={"safe": True}),
                AuditEvent(installation_id=installation.id, classification="fixture_two",
                           correlation_id=str(uuid4()), payload={"safe": True}),
                TelemetryOutbox(installation_id=installation.id, schema_version=1,
                                event_type="health", payload={"state": "observe_only"}),
            ])

        with journal.session_factory() as session:
            assert session.query(Consent).one().policy_version.checksum == policy.checksum
            assert session.query(OrderIntent).one().decision.id == decision.id
            assert [row.sequence for row in session.query(AuditEvent).order_by(AuditEvent.sequence)] == [1, 2]
            assert session.query(TelemetryOutbox).one().sequence == 1
    finally:
        journal.close()


def test_constraints_and_foreign_keys_fail_closed(tmp_path):
    journal = open_journal(tmp_path)
    try:
        with journal.session_factory() as session:
            installation, binding, policy, _market, decision = seed_authority(session)
            session.commit()
            session.add(OrderIntent(
                installation_id=installation.id, account_binding_id=binding.id,
                strategy_decision_id=decision.id, policy_version_id=policy.id,
                custom_tag="invalid-quantity", contract_id="contract", side="BUY",
                order_type="market", quantity=2, risk_classification="allowed",
            ))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            valid = OrderIntent(
                installation_id=installation.id, account_binding_id=binding.id,
                strategy_decision_id=decision.id, policy_version_id=policy.id,
                custom_tag="duplicate-tag", contract_id="contract", side="BUY",
                order_type="market", quantity=1, risk_classification="allowed",
            )
            session.add(valid)
            session.commit()
            session.add(OrderIntent(
                installation_id=installation.id, account_binding_id=binding.id,
                strategy_decision_id=decision.id, policy_version_id=policy.id,
                custom_tag="duplicate-tag", contract_id="contract", side="BUY",
                order_type="market", quantity=1, risk_classification="allowed",
            ))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            session.add(LifecycleTransition(
                installation_id=str(uuid4()), from_state="disabled",
                to_state="observe_only", reason="orphan",
            ))
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        journal.close()


def test_transaction_crash_boundary_rolls_back_uncommitted_intent(tmp_path):
    journal = open_journal(tmp_path)
    try:
        with journal.session_factory.begin() as session:
            installation, binding, policy, _market, decision = seed_authority(session)
        session = journal.session_factory()
        try:
            intent = OrderIntent(
                installation_id=installation.id, account_binding_id=binding.id,
                strategy_decision_id=decision.id, policy_version_id=policy.id,
                custom_tag="crash-before-commit", contract_id="contract", side="BUY",
                order_type="market", quantity=1, risk_classification="allowed",
            )
            session.add(intent)
            session.flush()
            session.add(SubmissionAttempt(intent_id=intent.id, attempt_number=1))
            session.flush()
            session.rollback()
        finally:
            session.close()
        with journal.session_factory() as check:
            assert check.query(OrderIntent).filter_by(custom_tag="crash-before-commit").count() == 0
            assert check.query(SubmissionAttempt).count() == 0
    finally:
        journal.close()


def test_schema_mismatch_and_corruption_fail_closed(tmp_path):
    journal = open_journal(tmp_path)
    journal.close()
    engine = create_local_engine(journal.path)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='unsupported'"))
        with pytest.raises(LocalJournalError, match="schema_revision_unsupported"):
            verify_local_database(engine)
    finally:
        engine.dispose()

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not-a-sqlite-database")
    corrupt_engine = create_local_engine(corrupt)
    try:
        with pytest.raises(LocalJournalError, match="integrity_check_failed"):
            verify_local_database(corrupt_engine)
    finally:
        corrupt_engine.dispose()


def test_backup_is_consistent_and_supported(tmp_path):
    journal = open_journal(tmp_path)
    try:
        with journal.session_factory.begin() as session:
            session.add(Installation(software_version="backup-fixture"))
        backup = journal.backup(tmp_path / "backup" / "journal-backup.db")
        backup_engine = create_local_engine(backup)
        try:
            assert verify_local_database(backup_engine)["integrity"] == "ok"
            with backup_engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM installations")).scalar_one() == 1
        finally:
            backup_engine.dispose()
    finally:
        journal.close()


def test_single_writer_and_append_only_audit_are_enforced(tmp_path):
    journal = open_journal(tmp_path)
    first = journal.engine.connect()
    second = journal.engine.connect()
    try:
        first.exec_driver_sql("BEGIN IMMEDIATE")
        second.exec_driver_sql("PRAGMA busy_timeout=20")
        with pytest.raises(OperationalError):
            second.exec_driver_sql("BEGIN IMMEDIATE")
        first.rollback()

        with journal.session_factory.begin() as session:
            installation = Installation(software_version="append-only-fixture")
            session.add(installation)
            session.flush()
            event = AuditEvent(
                installation_id=installation.id, classification="created",
                correlation_id=str(uuid4()), payload={"safe": True},
            )
            session.add(event)
        with journal.engine.begin() as connection:
            with pytest.raises(IntegrityError, match="append_only"):
                connection.execute(text("UPDATE audit_events SET classification='changed'"))
    finally:
        first.close()
        second.close()
        journal.close()


def test_bounded_outbox_preserves_pending_rows_and_monotonic_sequence(tmp_path):
    journal = open_journal(tmp_path)
    try:
        with journal.session_factory.begin() as session:
            installation = Installation(software_version="outbox-fixture")
            session.add(installation)
            session.flush()
            first = enqueue_telemetry(
                session, installation_id=installation.id, schema_version=1,
                event_type="health", payload={"safe": 1}, max_rows=2,
            )
            second = enqueue_telemetry(
                session, installation_id=installation.id, schema_version=1,
                event_type="health", payload={"safe": 2}, max_rows=2,
            )
            assert (first.sequence, second.sequence) == (1, 2)
        with journal.session_factory() as session:
            with pytest.raises(LocalJournalError, match="capacity_reached"):
                enqueue_telemetry(
                    session, installation_id=installation.id, schema_version=1,
                    event_type="health", payload={"safe": 3}, max_rows=2,
                )
            session.rollback()
            session.query(TelemetryOutbox).filter_by(sequence=1).one().status = "acknowledged"
            session.commit()
            third = enqueue_telemetry(
                session, installation_id=installation.id, schema_version=1,
                event_type="health", payload={"safe": 3}, max_rows=2,
            )
            session.commit()
            assert third.sequence == 3
            assert [row.sequence for row in session.query(TelemetryOutbox).order_by(
                TelemetryOutbox.sequence
            )] == [2, 3]
    finally:
        journal.close()


def test_permission_command_is_user_scoped(tmp_path, monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr("local_executor.journal.subprocess.run",
                        lambda args, **kwargs: calls.append(args) or Result())
    apply_user_only_permissions(tmp_path / "secure")
    if __import__("os").name == "nt":
        assert calls and calls[0][0] == "icacls"
        assert "/inheritance:r" in calls[0] and "/grant:r" in calls[0]
    else:
        assert not calls
