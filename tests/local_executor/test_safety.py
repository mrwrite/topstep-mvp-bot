from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from local_executor.journal import LocalJournal
from local_executor.journal_models import Consent, Installation, QualificationEvidence
from local_executor.safety import (
    REQUIRED_PRACTICE_EVIDENCE,
    LocalRiskPolicy,
    SafetyError,
    SafetyService,
)


def policy(**overrides):
    values = {
        "allowed_account_ids": ("practice-1234", "combine-5678"),
        "allowed_instruments": ("CON.F.US.MES.Z26",),
        "strategy_version": "rsi-v1",
        "configuration_hash": "configuration-hash",
        "quantity": 1,
        "max_position": 1,
        "max_orders_per_session": 3,
        "max_orders_per_day": 6,
        "max_daily_realized_loss": "100.00",
        "max_consecutive_losses": 2,
        "timezone": "America/Chicago",
        "weekdays": (0, 1, 2, 3, 4),
        "session_start": "08:30:00",
        "session_end": "11:00:00",
        "max_data_age_seconds": 30,
        "max_clock_skew_seconds": 5,
        "provider_error_cooldown_seconds": 60,
        "telemetry_outage_behavior": "halt",
        "telemetry_max_offline_seconds": 0,
        "kill_cancel_open_orders": False,
        "kill_flatten_positions": False,
    }
    values.update(overrides)
    return LocalRiskPolicy(**values)


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "safety.db", secure_permissions=False)
    yield value
    value.close()


def create_installation(session):
    installation = Installation(software_version="fixture")
    session.add(installation)
    session.flush()
    return installation


def test_policy_is_complete_canonical_and_checksum_bound():
    first = policy(allowed_instruments=("B", "A"), weekdays=(4, 0, 1))
    second = policy(allowed_instruments=("A", "B"), weekdays=(1, 4, 0))
    assert first.checksum() == second.checksum()
    with pytest.raises(SafetyError, match="quantity_must_equal_one"):
        policy(quantity=2).validate()
    with pytest.raises(SafetyError, match="exact_allowlists_required"):
        policy(allowed_account_ids=()).validate()
    with pytest.raises(SafetyError, match="schedule_required"):
        policy(timezone="Not/AZone").validate()
    with pytest.raises(SafetyError, match="telemetry_behavior_required"):
        policy(telemetry_outage_behavior="ignore").validate()


def test_remote_policy_source_is_rejected(journal):
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=str(uuid4()))
        with pytest.raises(SafetyError, match="remote_policy_prohibited"):
            service.activate_policy(installation, policy(), source="railway")


def test_exact_attestation_rejects_funded_live_and_bad_suffix(journal):
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=str(uuid4()))
        service.transition(installation, "observe_only", "local_start")
        for account_kind in ("express_funded", "live_funded", "live_brokerage"):
            with pytest.raises(SafetyError, match="funded_or_live_account_prohibited"):
                service.attest_account(
                    installation, provider_account_id="account-1234",
                    credential_generation=1, account_kind=account_kind,
                    typed_confirmation="CONFIRM-1234",
                )
        with pytest.raises(SafetyError, match="suffix_confirmation_failed"):
            service.attest_account(
                installation, provider_account_id="practice-1234", credential_generation=1,
                account_kind="practice", typed_confirmation="CONFIRM-9999",
            )
        binding = service.attest_account(
            installation, provider_account_id="practice-1234", credential_generation=1,
            account_kind="practice", typed_confirmation="CONFIRM-1234",
        )
        assert binding.provider_account_id == "practice-1234"
        assert service.redacted_account_suffix(binding.provider_account_id) == "••••1234"


def test_complete_practice_to_combine_first_order_flow(journal):
    now = [datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)]
    boot_id = str(uuid4())
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=boot_id, clock=lambda: now[0])
        service.transition(installation, "observe_only", "local_start")
        active_policy = service.activate_policy(installation, policy())
        practice = service.attest_account(
            installation, provider_account_id="practice-1234", credential_generation=1,
            account_kind="practice", typed_confirmation="CONFIRM-1234",
        )
        practice_consent = service.accept_consent(
            installation, practice, active_policy, strategy_version="rsi-v1",
            configuration_hash="configuration-hash", consent_version="local-v1",
        )
        service.arm_practice(installation, practice, active_policy, practice_consent)
        with pytest.raises(SafetyError, match="qualification_incomplete"):
            service.mark_practice_qualified(installation, practice, active_policy)
        for evidence_type in REQUIRED_PRACTICE_EVIDENCE:
            service.record_practice_evidence(
                installation, practice, active_policy, evidence_type, outcome="passed",
                strategy_version="rsi-v1", configuration_hash="configuration-hash",
            )
        service.mark_practice_qualified(installation, practice, active_policy)
        assert installation.lifecycle_state == "practice_qualified"

        combine = service.attest_account(
            installation, provider_account_id="combine-5678", credential_generation=1,
            account_kind="trading_combine", typed_confirmation="CONFIRM-5678",
        )
        combine_consent = service.accept_consent(
            installation, combine, active_policy, strategy_version="rsi-v1",
            configuration_hash="configuration-hash", consent_version="local-v1",
        )
        service.prepare_combine(installation)
        grant = service.arm_combine(
            installation, combine, active_policy, combine_consent, ttl_seconds=300
        )
        assert installation.lifecycle_state == "combine_armed"
        with pytest.raises(SafetyError, match="first_order_confirmation_failed"):
            service.authorize_first_order(
                installation, grant, intent_fingerprint="intent-one",
                typed_confirmation="AUTHORIZE-0000",
            )
        service.authorize_first_order(
            installation, grant, intent_fingerprint="intent-one",
            typed_confirmation="AUTHORIZE-5678",
        )
        with pytest.raises(SafetyError, match="intent_mismatch"):
            service.consume_first_order(
                installation, grant, intent_fingerprint="different-intent"
            )
        service.consume_first_order(installation, grant, intent_fingerprint="intent-one")
        with pytest.raises(SafetyError, match="combine_arm_invalid|authorization_consumed"):
            service.consume_first_order(installation, grant, intent_fingerprint="intent-one")
        with pytest.raises(SafetyError, match="first_order_review_required"):
            service.approve_automated_sessions(installation, grant)
        service.reconcile_first_order(grant, authoritative=True)
        service.approve_automated_sessions(installation, grant)
        assert installation.lifecycle_state == "running"
        assert grant.automated_sessions_approved_at == now[0]


def test_restart_expiry_policy_and_account_drift_disarm(journal):
    now = [datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)]
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=str(uuid4()), clock=lambda: now[0])
        service.transition(installation, "observe_only", "local_start")
        active_policy = service.activate_policy(installation, policy())
        combine = service.attest_account(
            installation, provider_account_id="combine-5678", credential_generation=1,
            account_kind="trading_combine", typed_confirmation="CONFIRM-5678",
        )
        consent = service.accept_consent(
            installation, combine, active_policy, strategy_version="rsi-v1",
            configuration_hash="configuration-hash", consent_version="local-v1",
        )
        # Enter the pending state only after recording prior Practice qualification.
        installation.lifecycle_state = "practice_qualified"
        service.prepare_combine(installation)
        grant = service.arm_combine(installation, combine, active_policy, consent, ttl_seconds=1)
        now[0] += timedelta(seconds=2)
        with pytest.raises(SafetyError, match="combine_arm_expired"):
            service.authorize_first_order(
                installation, grant, intent_fingerprint="intent",
                typed_confirmation="AUTHORIZE-5678",
            )

        installation.lifecycle_state = "combine_armed"
        grant.state = "armed"
        grant.expires_at = now[0] + timedelta(minutes=5)
        replacement_service = SafetyService(
            session, boot_id=str(uuid4()), clock=lambda: now[0]
        )
        replacement_service.invalidate_for_restart(installation)
        assert installation.lifecycle_state == "observe_only"
        assert grant.state == "invalidated"

        prior_evidence = QualificationEvidence(
            installation_id=installation.id, account_binding_id=combine.id,
            evidence_type="risk_rejection", outcome="passed", evidence={},
        )
        session.add(prior_evidence)
        replacement_service.activate_policy(
            installation,
            replace(policy(), max_daily_realized_loss="75.00"),
        )
        assert prior_evidence.invalidated_at is not None
        assert session.get(Consent, consent.id).revoked_at is not None


def test_kill_and_consent_mismatch_block_arming(journal):
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=str(uuid4()))
        service.transition(installation, "observe_only", "local_start")
        active_policy = service.activate_policy(installation, policy())
        practice = service.attest_account(
            installation, provider_account_id="practice-1234", credential_generation=1,
            account_kind="practice", typed_confirmation="CONFIRM-1234",
        )
        consent = service.accept_consent(
            installation, practice, active_policy, strategy_version="rsi-v1",
            configuration_hash="configuration-hash", consent_version="local-v1",
        )
        service.set_kill(installation, scope="manual", scope_key="self",
                         active=True, reason="operator_stop")
        assert installation.lifecycle_state == "halted"
        service.set_kill(installation, scope="manual", scope_key="self",
                         active=False, reason="operator_cleared")
        service.transition(installation, "observe_only", "local_recovery")
        consent.revoked_at = datetime.now(timezone.utc)
        with pytest.raises(SafetyError, match="current_consent_required"):
            service.arm_practice(installation, practice, active_policy, consent)


def test_same_kind_account_switch_invalidates_consent_and_qualification(journal):
    with journal.session_factory.begin() as session:
        installation = create_installation(session)
        service = SafetyService(session, boot_id=str(uuid4()))
        service.transition(installation, "observe_only", "local_start")
        active_policy = service.activate_policy(
            installation,
            replace(policy(), allowed_account_ids=("practice-1234", "practice-9999")),
        )
        first = service.attest_account(
            installation, provider_account_id="practice-1234", credential_generation=1,
            account_kind="practice", typed_confirmation="CONFIRM-1234",
        )
        consent = service.accept_consent(
            installation, first, active_policy, strategy_version="rsi-v1",
            configuration_hash="configuration-hash", consent_version="local-v1",
        )
        evidence = service.record_practice_evidence(
            installation, first, active_policy, "risk_rejection", outcome="passed",
            strategy_version="rsi-v1", configuration_hash="configuration-hash",
        )
        second = service.attest_account(
            installation, provider_account_id="practice-9999", credential_generation=1,
            account_kind="practice", typed_confirmation="CONFIRM-9999",
        )
        assert first.is_active is False and second.is_active is True
        assert consent.revoked_at is not None
        assert evidence.invalidated_at is not None
