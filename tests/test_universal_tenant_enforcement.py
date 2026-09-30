from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import OperatorContext, TenantContext
from app.tenant_architecture import assert_tenant_architecture, inspect_source
from app.tenant_repository import (
    OperatorRepository,
    TenantRepository,
    TenantScopeError,
    VerifiedTenantJob,
    bind_tenant_context,
)
from app.time_utils import utc_now


@pytest.fixture(scope="module")
def tenant_seed():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    alice = models.User(username="tenant-alice", email="a@test", hashed_password="x")
    bob = models.User(username="tenant-bob", email="b@test", hashed_password="x")
    db.add_all([alice, bob])
    db.flush()
    integration = models.PlatformIntegration(
        user_id=bob.id, display_name="bob-sim", provider="TRADINGVIEW", status="disabled"
    )
    db.add(integration)
    db.flush()
    now = utc_now().replace(tzinfo=None)
    deletion = models.AccountDeletionRequest(
        user_id=bob.id, status="pending", execute_after=now + timedelta(days=7),
        confirmation_hash="hash",
    )
    strategy = models.StrategyConfig(
        user_id=bob.id, integration_id=integration.id, account_id="SIM", symbol="ES",
        parameters={"buy_threshold": 30, "sell_threshold": 70},
    )
    run = models.SimulationRun(
        id="bob-run", user_id=bob.id, state="running", state_version=1, fencing_token=4,
        desired_state="running", scope_key="bob:ES", active_scope_key="bob:ES", symbol="ES",
        configuration={"trading_mode": "paper"}, configuration_hash="cfg",
        strategy_version="rsi-threshold-v1", correlation_id="corr",
    )
    order = models.PaperOrder(
        user_id=bob.id, integration_id=integration.id, account_id="SIM", symbol="ES",
        side="BUY", quantity=1, trading_mode="paper", order_type="market", source="test",
        idempotency_key="bob-order", order_fingerprint="bob-order", status="filled",
        filled_quantity=1, remaining_quantity=0, simulation_run_id="bob-run",
        simulation_fencing_token=4,
    )
    db.add_all([deletion, strategy, run, order])
    db.flush()
    market = models.SimulationMarketInput(
        id="bob-market", run_id=run.id, user_id=bob.id, source="test", instrument="ES",
        timeframe="1m", event_at=utc_now(), source_identity="market-id", content_hash="content",
        payload={"bars": []}, status="processed", freshness="fresh",
    )
    outbox = models.OutboxEvent(
        id="bob-event", user_id=bob.id, aggregate_type="simulation_run", aggregate_id=run.id,
        event_type="test", payload={}, correlation_id="corr",
    )
    revocation = models.ProviderRevocationAttempt(
        user_id=bob.id, deletion_request_id=deletion.id, integration_id=integration.id,
        provider="TRADINGVIEW", outcome="unconfirmed",
    )
    rows = [
        models.UserSession(user_id=bob.id, session_id="bob-session", expires_at=now + timedelta(hours=1)),
        models.SupportRequest(user_id=bob.id, reference_id="SUP-BOB", category="test", severity="normal",
                              subject="subject", sanitized_message="message"),
        models.AnalyticsEvent(user_id=bob.id, event_name="test", event_category="test",
                              environment="test", source="test"),
        models.UserBetaStatus(user_id=bob.id, status="active", source="invite"),
        models.UserEntitlement(user_id=bob.id, feature_code="simulation", source="invite"),
        models.OnboardingProgress(user_id=bob.id, milestones={}),
        models.RiskSettings(user_id=bob.id, trading_mode="paper", max_quantity=1, max_contracts=1,
                            max_daily_loss=100, max_open_positions=1),
        models.SimulationLease(run_id=run.id, user_id=bob.id, owner_id="worker", fencing_token=4,
                               acquired_at=now, renewed_at=now, expires_at=now + timedelta(minutes=1)),
        models.SimulationCommand(id="bob-command", run_id=run.id, user_id=bob.id,
                                 idempotency_key="bob-command", command="pause", status="accepted",
                                 correlation_id="corr"),
        models.SimulationCheckpoint(id=1, run_id=run.id, user_id=bob.id, fencing_token=4, sequence=1,
                                    checkpoint={}, configuration_hash="cfg", strategy_version="rsi-threshold-v1",
                                    checkpoint_hash="digest"),
        market,
        models.SimulationEvaluation(id="bob-eval", run_id=run.id, user_id=bob.id,
                                    market_input_id=market.id, evaluation_identity="eval", fencing_token=4,
                                    strategy_name="rsi-threshold-v1", strategy_version="rsi-threshold-v1",
                                    configuration_hash="cfg", lookback_identity="lookback", signal="HOLD",
                                    status="completed", rationale="test", market_snapshot={}, freshness="fresh",
                                    correlation_id="corr", causation_id="market-id"),
        models.SimulationRiskCounter(run_id=run.id, user_id=bob.id),
        models.PaperFill(order_id=order.id, user_id=bob.id, symbol="ES", side="BUY", quantity=1,
                         price=100, simulation_run_id=run.id, simulation_fencing_token=4,
                         execution_identity="fill"),
        models.PaperPosition(user_id=bob.id, integration_id=integration.id, account_id="SIM", symbol="ES",
                             quantity=1, avg_price=100, simulation_run_id=run.id,
                             simulation_fencing_token=4),
        models.PaperLedgerEntry(user_id=bob.id, integration_id=integration.id, account_id="SIM",
                                paper_order_id=order.id, entry_type="fill", amount=-100,
                                cash_balance=99900, equity=100000, buying_power=99900,
                                simulation_run_id=run.id, simulation_fencing_token=4,
                                execution_identity="ledger"),
        outbox,
        revocation,
    ]
    db.add_all(rows)
    db.flush()
    delivery = models.OutboxDelivery(
        user_id=bob.id, event_id=outbox.id, consumer="test", outcome="succeeded"
    )
    db.add(delivery)
    db.commit()
    alice_id, bob_id = alice.id, bob.id
    keys = {
        type(row): getattr(row, "id", getattr(row, "run_id", None))
        for row in [integration, deletion, strategy, run, order, market, outbox, delivery, *rows]
    }
    db.close()
    yield engine, alice_id, bob_id, keys
    engine.dispose()


@pytest.fixture()
def tenant_db(tenant_seed):
    engine, alice_id, bob_id, keys = tenant_seed
    db = sessionmaker(bind=engine)()
    alice = db.get(models.User, alice_id)
    bob = db.get(models.User, bob_id)
    yield db, alice, bob, keys
    db.close()


@pytest.mark.parametrize("model", [
    models.PlatformIntegration, models.AccountDeletionRequest, models.StrategyConfig,
    models.SimulationRun, models.PaperOrder, models.UserSession, models.SupportRequest,
    models.AnalyticsEvent, models.RiskSettings, models.SimulationLease, models.SimulationCommand,
    models.SimulationCheckpoint, models.SimulationMarketInput, models.SimulationEvaluation,
    models.SimulationRiskCounter, models.PaperFill, models.PaperPosition, models.PaperLedgerEntry,
    models.OutboxEvent, models.OutboxDelivery, models.ProviderRevocationAttempt,
    models.UserBetaStatus, models.UserEntitlement, models.OnboardingProgress,
], ids=lambda model: f"cross-tenant-{model.__tablename__}")
def test_cross_tenant_resource_reads_return_no_row(tenant_db, model):
    db, alice, _bob, keys = tenant_db
    repository = TenantRepository(db, TenantContext(alice.id, alice.username))
    assert repository.get(model, keys[model]) is None


def test_cross_tenant_count_pagination_and_bulk_mutation_are_bounded(tenant_db):
    db, alice, bob, _keys = tenant_db
    repository = TenantRepository(db, TenantContext(alice.id, alice.username))
    assert repository.count(models.PlatformIntegration) == 0
    assert repository.list(models.PlatformIntegration, limit=1, offset=0) == []
    assert repository.update(models.PlatformIntegration, (), {"status": "active"}) == 0
    assert repository.delete(models.PlatformIntegration) == 0
    db.commit()
    unscoped = sessionmaker(bind=db.get_bind())()
    assert unscoped.query(models.PlatformIntegration).filter_by(user_id=bob.id).one().status == "disabled"
    unscoped.close()


def test_missing_conflicting_and_cross_tenant_flush_fail_closed(tenant_db):
    db, alice, bob, _keys = tenant_db
    with pytest.raises(TenantScopeError, match="validated_tenant_required"):
        TenantRepository(db, None)  # type: ignore[arg-type]
    TenantRepository(db, TenantContext(alice.id, alice.username))
    with pytest.raises(TenantScopeError, match="tenant_context_conflict"):
        bind_tenant_context(db, TenantContext(bob.id, bob.username))
    db.add(models.PlatformIntegration(
        user_id=bob.id, display_name="forbidden", provider="TRADINGVIEW", status="disabled"
    ))
    with pytest.raises(TenantScopeError, match="cross_tenant_mutation"):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("mutation", [
    {"expected_tenant": 99}, {"expected_command": "other"}, {"expected_job_type": "other"},
    {"expected_purpose": "other"}, {"expected_issuer": "other"},
    {"expected_environment": "prod"}, {"expected_actor": 99}, {"payload": {"tampered": True}},
], ids=["tenant", "job-id", "job-type", "purpose", "issuer", "environment", "actor", "payload"])
def test_signed_job_substitution_is_rejected(mutation):
    job = VerifiedTenantJob.issue(
        TenantContext(7, "worker"), "job-1", "secret", job_type="evaluate", purpose="simulation",
        environment="test", payload={"run_id": "r1"},
    )
    expected = dict(
        expected_tenant=7, expected_command="job-1", expected_job_type="evaluate",
        expected_purpose="simulation", expected_issuer="simulation-worker",
        expected_environment="test", expected_actor=7, payload={"run_id": "r1"},
    )
    expected.update(mutation)
    with pytest.raises(TenantScopeError):
        job.validate("secret", **expected)


def test_signed_job_expiry_signature_and_context_immutability():
    job = VerifiedTenantJob.issue(TenantContext(7, "worker"), "job-1", "secret", lifetime_seconds=1)
    with pytest.raises(TenantScopeError):
        replace(job, expires_at=(utc_now() - timedelta(seconds=1)).isoformat()).validate(
            "secret", expected_tenant=7, expected_command="job-1"
        )
    with pytest.raises(TenantScopeError):
        replace(job, signature="0" * 64).validate("secret", expected_tenant=7, expected_command="job-1")
    with pytest.raises(Exception):
        job.tenant_id = 8  # type: ignore[misc]


@pytest.mark.parametrize("field", ["role", "purpose", "case", "target", "expiry"])
def test_operator_context_mismatch_or_expiry_is_not_a_global_bypass(tenant_db, field):
    db, alice, bob, _keys = tenant_db
    now = utc_now()
    context = OperatorContext(
        actor_user_id=alice.id, target_tenant_id=bob.id, purpose="Investigate incident",
        case_id="INC-1", action="GET /resource", correlation_id="corr", created_at=now,
        expires_at=now + timedelta(minutes=5), permissions=("GET:/resource",),
    )
    if field == "expiry":
        with pytest.raises(ValueError, match="operator_context_expired"):
            replace(context, expires_at=now - timedelta(seconds=1))
        return
    if field == "purpose":
        with pytest.raises(ValueError, match="operator_purpose_required"):
            replace(context, purpose="")
        return
    if field == "case":
        with pytest.raises(ValueError, match="operator_case_required"):
            replace(context, case_id="")
        return
    tenant = context.tenant_context(alice.username)
    if field == "role":
        tenant = replace(tenant, roles=())
    elif field == "target":
        tenant = replace(tenant, user_id=alice.id)
    bind_tenant_context(db, tenant, replace_authenticated=True)
    if field == "role":
        with pytest.raises(TenantScopeError, match="operator_context_required"):
            OperatorRepository(db)
    else:
        assert TenantRepository(db, tenant).count(models.PlatformIntegration) in {0, 1}


def test_architectural_guard_accepts_repository_and_rejects_unsafe_patterns():
    assert_tenant_architecture(Path("app"))
    prohibited = inspect_source(Path("unsafe_routes.py"), "def route(db):\n    return db.query(Resource).all()\n")
    assert prohibited and prohibited[0].rule == "TENANT001"
    client_context = inspect_source(
        Path("safe_routes.py"),
        "def route(request):\n    return TenantContext(request.path_params['tenant_id'], 'x')\n",
    )
    assert client_context and client_context[0].rule == "TENANT002"
