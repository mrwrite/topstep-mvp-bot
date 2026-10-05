from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from local_executor.journal import LocalJournal
from local_executor.journal_models import (
    Installation, MarketInput, PolicyVersion, ProposedIntent, RiskDecision, StrategyDecision,
)
from local_executor.risk import LocalDecisionEngine, RiskSnapshot, evaluate_pretrade
from local_executor.safety import LocalRiskPolicy
from local_executor.strategy import (
    RsiThresholdConfig, StrategyInputError, calculate_rsi, evaluate_rsi_threshold,
)


CONFIG = RsiThresholdConfig(period=14, buy_below=30, sell_above=70)
NOW = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)


def policy(**overrides):
    values = {
        "allowed_account_ids": ("practice-1234", "combine-5678"),
        "allowed_instruments": ("CON.F.US.MES.Z26",),
        "strategy_version": "rsi-v1",
        "configuration_hash": CONFIG.hash(),
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
        "telemetry_outage_behavior": "bounded_buffer",
        "telemetry_max_offline_seconds": 60,
        "kill_cancel_open_orders": False,
        "kill_flatten_positions": False,
    }
    values.update(overrides)
    return LocalRiskPolicy(**values)


def snapshot(**overrides):
    values = {
        "account_id": "practice-1234",
        "instrument": "CON.F.US.MES.Z26",
        "strategy_version": "rsi-v1",
        "configuration_hash": CONFIG.hash(),
        "quantity": 1,
        "open_position": 0,
        "orders_this_session": 0,
        "orders_today": 0,
        "daily_realized_loss": "0",
        "consecutive_losses": 0,
        "now": NOW,
        "market_timestamp": NOW - timedelta(seconds=1),
        "clock_skew_seconds": 0.1,
        "cooldown_until": NOW - timedelta(seconds=1),
        "reconciliation_clean": True,
        "telemetry_last_success": NOW - timedelta(seconds=1),
        "active_kills": (),
        "lifecycle_state": "practice_armed",
    }
    values.update(overrides)
    return RiskSnapshot(**values)


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "risk.db", secure_permissions=False)
    yield value
    value.close()


def test_pure_rsi_strategy_has_no_hosted_runtime_dependency():
    assert calculate_rsi(list(range(1, 16)), period=14) == 100.0
    assert evaluate_rsi_threshold(list(range(15, 0, -1)), CONFIG).signal == "BUY"
    assert evaluate_rsi_threshold(list(range(1, 16)), CONFIG).signal == "SELL"
    with pytest.raises(StrategyInputError, match="insufficient_rsi_history"):
        calculate_rsi([1, 2], period=14)


def test_complete_consistent_snapshot_allows_locally():
    result = evaluate_pretrade(policy(), snapshot())
    assert result.allowed is True
    assert result.classifications == ()


@pytest.mark.parametrize(
    ("changes", "classification"),
    [
        ({"account_id": "other"}, "account_not_allowed"),
        ({"instrument": "other"}, "instrument_not_allowed"),
        ({"strategy_version": "other"}, "strategy_version_mismatch"),
        ({"configuration_hash": "other"}, "configuration_hash_mismatch"),
        ({"quantity": 2}, "quantity_must_equal_one"),
        ({"open_position": 1}, "position_limit"),
        ({"orders_this_session": 3}, "session_order_limit"),
        ({"orders_today": 6}, "daily_order_limit"),
        ({"daily_realized_loss": "-100"}, "daily_loss_limit"),
        ({"consecutive_losses": 2}, "consecutive_loss_limit"),
        ({"now": datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)}, "outside_schedule"),
        ({"market_timestamp": NOW - timedelta(seconds=31)}, "market_data_stale_or_future"),
        ({"clock_skew_seconds": 6}, "clock_skew"),
        ({"cooldown_until": NOW + timedelta(seconds=1)}, "provider_cooldown"),
        ({"reconciliation_clean": False}, "reconciliation_not_clean"),
        ({"active_kills": ("manual",)}, "active_kill"),
        ({"lifecycle_state": "observe_only"}, "lifecycle_not_armed"),
        ({"telemetry_last_success": NOW - timedelta(seconds=61)}, "telemetry_offline_limit"),
    ],
)
def test_each_relaxed_stale_or_inconsistent_input_denies(changes, classification):
    result = evaluate_pretrade(policy(), snapshot(**changes))
    assert result.allowed is False
    assert classification in result.classifications


@pytest.mark.parametrize("field_name", [field.name for field in fields(RiskSnapshot)])
def test_every_missing_risk_input_denies(field_name):
    result = evaluate_pretrade(policy(), snapshot(**{field_name: None}))
    assert result.allowed is False
    assert f"missing_{field_name}" in result.classifications


def test_hosted_signal_or_configuration_cannot_cause_local_decision(journal):
    with journal.session_factory.begin() as session:
        engine = LocalDecisionEngine(session)
        installation = Installation(software_version="fixture")
        session.add(installation)
        session.flush()
        active_policy = PolicyVersion(
            installation_id=installation.id, version=1, checksum=policy().checksum(),
            policy=policy().canonical(), is_active=True,
        )
        session.add(active_policy)
        session.flush()
        bars = [{"timestamp": (NOW - timedelta(minutes=15-index)).isoformat(),
                 "close": float(15-index)} for index in range(15)]
        with pytest.raises(ValueError, match="remote_strategy_causation_prohibited"):
            engine.evaluate_and_persist(
                installation_id=installation.id, account_id="practice-1234",
                instrument="CON.F.US.MES.Z26", bars=bars, market_timestamp=NOW,
                strategy_version="rsi-v1", strategy_config=CONFIG,
                policy_version=active_policy, risk_snapshot=snapshot(), origin="railway",
            )
        with pytest.raises(ValueError, match="remote_strategy_causation_prohibited"):
            engine.evaluate_and_persist(
                installation_id=installation.id, account_id="practice-1234",
                instrument="CON.F.US.MES.Z26", bars=bars, market_timestamp=NOW,
                strategy_version="rsi-v1", strategy_config=CONFIG,
                policy_version=active_policy, risk_snapshot=snapshot(),
                configuration_source="hosted",
            )
        assert session.query(MarketInput).count() == 0


def test_local_decision_and_denied_risk_inputs_are_reproducibly_persisted(journal):
    with journal.session_factory.begin() as session:
        installation = Installation(software_version="fixture")
        session.add(installation)
        session.flush()
        active_policy = PolicyVersion(
            installation_id=installation.id, version=1, checksum=policy().checksum(),
            policy=policy().canonical(), is_active=True,
        )
        session.add(active_policy)
        session.flush()
        bars = [{"timestamp": (NOW - timedelta(minutes=15-index)).isoformat(),
                 "close": float(15-index)} for index in range(15)]
        decision, proposal, risk = LocalDecisionEngine(session).evaluate_and_persist(
            installation_id=installation.id, account_id="practice-1234",
            instrument="CON.F.US.MES.Z26", bars=bars, market_timestamp=NOW,
            strategy_version="rsi-v1", strategy_config=CONFIG,
            policy_version=active_policy,
            risk_snapshot=snapshot(reconciliation_clean=False),
        )
        assert decision.decision == "BUY"
        assert proposal.side == "BUY" and proposal.quantity == 1
        assert risk.allowed is False
        assert risk.classifications == ["reconciliation_not_clean"]
        assert risk.input_snapshot["account_id"] == "practice-1234"
    with journal.session_factory() as session:
        assert session.query(MarketInput).count() == 1
        assert session.query(StrategyDecision).count() == 1
        assert session.query(ProposedIntent).count() == 1
        assert session.query(RiskDecision).count() == 1
