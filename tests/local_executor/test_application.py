from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from local_executor.application import LocalExecutorApplication
from local_executor.config import ExecutorMode
from local_executor.control_surface import ControlSurfaceError
from local_executor.credentials import CredentialEnrollment
from local_executor.journal import LocalJournal
from local_executor.journal_models import AccountBinding, Installation
from local_executor.runtime import RuntimeDecision
from local_executor.secret_store import MemorySecretStore
from local_executor.session import SessionToken
from local_executor.topstep_client import LocalAccount, LocalBar, LocalContract, MutationResult


class FakeReadOnlyClient:
    clock_skew_seconds = 0.0

    def authenticate(self, credentials):
        assert credentials.username == "local-user"
        assert credentials.api_key == "local-api-key"
        return SessionToken(
            "memory-only-token", datetime.now(timezone.utc) + timedelta(hours=1)
        )

    def validate_session(self, token):
        return SessionToken(token, datetime.now(timezone.utc) + timedelta(hours=1))

    def search_active_accounts(self, token):
        assert token == "memory-only-token"
        return (
            LocalAccount(id=12345678, can_trade=True, is_visible=True),
            LocalAccount(id=99990000, can_trade=True, is_visible=False),
        )

    def select_exact_account(self, token, account_id):
        assert token == "memory-only-token"
        if account_id != 12345678:
            raise AssertionError("unexpected account")
        return LocalAccount(id=account_id, can_trade=True, is_visible=True)

    def search_contracts(self, token, search_text, *, live=False):
        assert live is False
        return (LocalContract(
            id="CON.F.US.MNQ.Z26", name="MNQ Dec 2026", symbol_id="MNQ",
            tick_size="0.25", tick_value="0.50", active=True,
        ),)


class FakePracticeClient(FakeReadOnlyClient):
    def retrieve_bars(self, token, **kwargs):
        assert kwargs["live"] is False
        end = kwargs["end"]
        return tuple(LocalBar(
            timestamp=(end - timedelta(minutes=5 * (20 - index))).isoformat(),
            open=str(200 - index), high=str(201 - index), low=str(198 - index),
            close=str(199 - index), volume=100,
        ) for index in range(20))

    def search_open_positions(self, token, *, account_id):
        return ()

    def search_trades(self, token, *, account_id, start, end):
        return ()

    def search_open_orders(self, token, *, account_id):
        return ()

    def place_order(self, token, **kwargs):
        assert kwargs["quantity"] == 1
        assert kwargs["side"] == "BUY"
        return MutationResult("accepted", 0, 445566)


@pytest.fixture()
def application(tmp_path):
    journal = LocalJournal.open(tmp_path / "application.db", secure_permissions=False)
    enrollment = CredentialEnrollment(MemorySecretStore())
    enrollment.enroll_topstep(username="local-user", api_key="local-api-key")
    runtime = RuntimeDecision(
        requested_mode=ExecutorMode.READ_ONLY,
        effective_mode=ExecutorMode.READ_ONLY,
        mutation_capable=False,
        classification="read_only_requested",
        reasons=("signed_release_required",),
    )
    value = LocalExecutorApplication(
        data_directory=tmp_path,
        enrollment=enrollment,
        runtime=runtime,
        client=FakeReadOnlyClient(),
        journal=journal,
    )
    yield value
    value.close()


def test_application_bootstraps_observe_only_journal(application):
    status = application.health()
    assert status["lifecycle_state"] == "observe_only"
    assert status["mutation_capable"] is False
    with application.journal.session_factory() as session:
        installation = session.scalar(select(Installation))
        assert installation is not None
        assert installation.lifecycle_state == "observe_only"


def test_account_discovery_uses_ephemeral_handle_and_redacts_id(application):
    result = application.discover_accounts()
    serialized = str(result)
    assert result["classification"] == "accounts_discovered"
    assert len(result["accounts"]) == 1
    assert result["accounts"][0]["redacted_suffix"] == "****5678"
    assert "12345678" not in serialized

    handle = result["accounts"][0]["selection_handle"]
    attested = application.attest_account({
        "selection_handle": handle,
        "account_kind": "practice",
        "typed_confirmation": "CONFIRM-5678",
    })
    assert attested == {
        "classification": "practice_account_attested",
        "redacted_suffix": "****5678",
    }
    with application.journal.session_factory() as session:
        binding = session.scalar(select(AccountBinding))
        assert binding.provider_account_id == "12345678"
        assert binding.account_attestation == "practice"

    with pytest.raises(ControlSurfaceError, match="account_selection_expired"):
        application.attest_account({
            "selection_handle": handle,
            "account_kind": "practice",
            "typed_confirmation": "CONFIRM-5678",
        })


def test_bad_confirmation_does_not_leak_account_id(application):
    handle = application.discover_accounts()["accounts"][0]["selection_handle"]
    with pytest.raises(ControlSurfaceError) as error:
        application.attest_account({
            "selection_handle": handle,
            "account_kind": "practice",
            "typed_confirmation": "CONFIRM-0000",
        })
    assert error.value.classification == "account_suffix_confirmation_failed"
    assert "12345678" not in str(error.value)


def test_signed_application_runs_one_guarded_practice_strategy(tmp_path):
    journal = LocalJournal.open(tmp_path / "practice.db", secure_permissions=False)
    enrollment = CredentialEnrollment(MemorySecretStore())
    enrollment.enroll_topstep(username="local-user", api_key="local-api-key")
    runtime = RuntimeDecision(
        requested_mode=ExecutorMode.MUTATION,
        effective_mode=ExecutorMode.MUTATION,
        mutation_capable=True,
        classification="personal_device_runtime_accepted",
        reasons=(),
    )
    app = LocalExecutorApplication(
        data_directory=tmp_path, enrollment=enrollment, runtime=runtime,
        client=FakePracticeClient(), journal=journal,
    )
    try:
        account = app.discover_accounts()["accounts"][0]
        app.attest_account({
            "selection_handle": account["selection_handle"],
            "account_kind": "practice",
            "typed_confirmation": "CONFIRM-5678",
        })
        now = datetime.now(timezone.utc)
        policy = {
            "instrument": "CON.F.US.MNQ.Z26",
            "rsi_period": 14,
            "rsi_buy_below": 30,
            "rsi_sell_above": 70,
            "max_position": 1,
            "max_orders_per_session": 2,
            "max_orders_per_day": 2,
            "max_daily_realized_loss": "50.00",
            "max_consecutive_losses": 2,
            "timezone": "UTC",
            "weekdays": list(range(7)),
            "session_start": "00:00:00",
            "session_end": "23:59:59",
            "max_data_age_seconds": 600,
            "max_clock_skew_seconds": 30,
            "provider_error_cooldown_seconds": 30,
            "telemetry_outage_behavior": "bounded_buffer",
            "telemetry_max_offline_seconds": 3600,
            "kill_cancel_open_orders": False,
            "kill_flatten_positions": False,
        }
        app.save_policy(policy)
        app.accept_consent({"typed_confirmation": "I UNDERSTAND"})
        assert app.arm_practice({})["classification"] == "practice_armed"
        outcome = app.run_practice_once({
            "rsi_period": 14, "rsi_buy_below": 30, "rsi_sell_above": 70,
        })
        assert outcome == {
            "classification": "practice_order_accepted",
            "signal": "BUY",
            "ambiguous": False,
            "direct_topstep_verification_required": False,
        }
    finally:
        app.close()
