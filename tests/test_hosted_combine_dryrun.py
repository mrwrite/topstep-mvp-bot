from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.hosted_combine_dryrun import (
    HostedDryRunError, process_pending_dry_runs, validate_policy,
)
from app.providers.base import ProviderCapabilityError
from app.providers.topstepx import TopStepXAdapter
from app.tenant_repository import TenantRepository
from app.time_utils import utc_now
from app import topstep_onboarding
from scripts.hosted_beta_preflight import check_environment
from scripts.check_hosted_combine_safety import violations as architecture_violations


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'hosted-dry-run.db'}")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def fixture_policy(**overrides):
    policy = {
        "allowed_strategies": ["rsi-threshold-v1@1.0.0"],
        "allowed_instruments": ["MES"],
        "max_order_quantity": 1,
        "max_open_position": 1,
        "max_orders_per_session": 4,
        "max_orders_per_day": 8,
        "max_consecutive_losses": 2,
        "max_daily_realized_loss": 100.0,
        "max_session_loss": 50.0,
        "max_stale_data_seconds": 60,
        "schedule": {"timezone": "UTC", "weekdays": [0, 1, 2, 3, 4], "start": "00:00", "end": "23:59"},
        "cooldown_seconds": 300,
        "dry_run_enabled": True,
        "provider_order_execution_enabled": False,
    }
    policy.update(overrides)
    return policy


def test_server_owned_risk_policy_requires_complete_nonempty_limits():
    validate_policy(fixture_policy())
    with pytest.raises(HostedDryRunError, match="risk_policy_empty_allowlist"):
        validate_policy(fixture_policy(allowed_instruments=[]))
    with pytest.raises(HostedDryRunError, match="provider_mutation_must_remain_disabled"):
        validate_policy(fixture_policy(provider_order_execution_enabled=True))
    with pytest.raises(HostedDryRunError, match="hosted_beta_quantity_must_equal_one"):
        validate_policy(fixture_policy(max_order_quantity=2))
    with pytest.raises(HostedDryRunError, match="risk_policy_incomplete"):
        validate_policy({"allowed_instruments": ["MES"]})


def test_hosted_dry_run_queue_is_durable_and_noop_when_empty(db):
    assert process_pending_dry_runs(db, worker_id="worker-fixture") == 0
    assert db.query(models.PaperOrder).count() == 0
    assert db.query(models.PaperOrder).count() == 0
    assert db.query(models.PaperFill).count() == 0


def test_credential_lifecycle_suppression_fences_dry_run_and_expires_proposal(db, monkeypatch):
    monkeypatch.setenv("TOPSTEP_BETA_COHORT_ID", "cohort-fixture")
    user = models.User(username="dryrun-owner", email="dryrun-owner@example.test", hashed_password="x")
    db.add(user)
    db.flush()
    integration = models.PlatformIntegration(user_id=user.id, display_name="fixture", provider="TOPSTEPX",
                                             status="approved")
    db.add(integration)
    db.flush()
    policy = models.HostedCombineRiskPolicy(
        id="policy-fixture", user_id=user.id, cohort_id="cohort-fixture", tester_user_id=user.id,
        integration_id=integration.id, provider_account_id="acct-fixture", policy_version=1,
        state="active", policy=fixture_policy(), required_consent_version="hosted-combine-dry-run-v1",
        effective_at=utc_now(), approved_by_operator_id=user.id, operator_context={"case_id": "fixture"},
    )
    consent = models.HostedCombineConsent(
        id="consent-fixture", user_id=user.id, integration_id=integration.id,
        credential_generation=1, provider_account_id="acct-fixture", approval_id="approval-fixture",
        policy_version=1, consent_version="hosted-combine-dry-run-v1", consent_text="fixture consent",
        accepted_at=utc_now(), correlation_id="corr-fixture",
    )
    db.add_all([policy, consent])
    db.flush()
    dry_run = models.HostedCombineDryRun(
        id="dryrun-fixture", user_id=user.id, integration_id=integration.id,
        credential_generation=1, provider_account_id="acct-fixture", approval_id="approval-fixture",
        approval_version=1, security_epoch=1, policy_id=policy.id, policy_version=1, consent_id=consent.id,
        strategy_name="rsi-threshold-v1", strategy_version="1.0.0", configuration_hash="cfg-fixture",
        instrument="MES", source_run_id="run-fixture", market_input_id="market-fixture",
        market_identity="market-identity-fixture", state="evaluating", idempotency_key="idem-fixture",
        stable_identity="stable-fixture", correlation_id="corr-fixture", lease_owner="worker-old",
        lease_expires_at=utc_now(), fencing_token=3, requested_at=utc_now(),
    )
    db.add(dry_run)
    db.flush()
    proposal = models.HostedCombineProposal(
        id="proposal-fixture", user_id=user.id, dry_run_id=dry_run.id,
        evaluation_identity="evaluation-fixture", strategy_signal="BUY", rationale="fixture",
        instrument="MES", side="BUY", quantity=1, order_type="market", policy_version=1,
        risk_checks=[], data_freshness_seconds=1, schedule_allowed=1, status="dry_run_only",
        created_at=utc_now(), expires_at=utc_now(),
    )
    db.add(proposal)
    dry_run.proposal_id = proposal.id
    db.commit()

    repo = TenantRepository(db, TenantContext(user.id, user.username))
    topstep_onboarding._suppress_execution(repo, integration, "credential_replaced")
    db.commit()
    db.refresh(dry_run)
    db.refresh(proposal)
    assert dry_run.state == "canceled"
    assert dry_run.lease_owner is None and dry_run.lease_expires_at is None
    assert dry_run.fencing_token == 4
    assert dry_run.result_classification == "credential_replaced"
    assert (
        proposal.expires_at.replace(tzinfo=utc_now().tzinfo)
        if proposal.expires_at.tzinfo is None
        else proposal.expires_at
    ) <= utc_now()


def test_topstep_mutation_capabilities_fail_closed():
    adapter = TopStepXAdapter({})
    assert adapter.mutation_capabilities_enabled is False
    for method, args in (
        (adapter.place_order, ({"quantity": 1},)),
        (adapter.cancel_order, ("provider-order-fixture",)),
        (adapter.modify_order, ("provider-order-fixture", {})),
        (adapter.close_position, ("account-fixture", "contract-fixture")),
    ):
        with pytest.raises(ProviderCapabilityError):
            asyncio.run(method(*args))


def test_preflight_rejects_production_placeholders_without_echoing_values():
    result = check_environment({
        "VITE_API_URL": "https://api.replace-with-approved-host.example",
        "DATABASE_URL": "postgresql://user:secret@db.railway.internal/app",
        "REDIS_URL": "redis://redis.railway.internal:6379",
        "SECRET_KEY": "private-fixture",
        "KEY_MANAGEMENT_PROVIDER": "railway-secret-envelope-v1",
        "KEY_MANAGEMENT_KEY_ID": "wrap-v1",
        "KEY_MANAGEMENT_ACTIVE_VERSION": "v1",
        "RAILWAY_ENVELOPE_KEY_VERSIONS_JSON": json.dumps({"v1": "hidden"}),
        "TOPSTEP_CREDENTIAL_FINGERPRINT_KEY": "separate-hidden-key",
        "HOSTED_SECURITY_EPOCH": "4",
        "DEPLOYMENT_PROFILE": "hosted_topstep_combine_beta",
        "APP_ENV": "production",
        "SERVICE_ROLE": "api",
        "TOPSTEP_BETA_COHORT_ID": "fixture-cohort",
        "TOPSTEP_APPROVED_TESTER_USER_ID": "99",
        "TOPSTEP_BASE_URL": "https://api.topstepx.com",
        "LIVE_TRADING_ENABLED": "false",
        "PROVIDER_MUTATIONS_ENABLED": "false",
        "CORS_ORIGINS": "https://beta.example.com",
        "FRONTEND_URL": "https://beta.example.com",
        "TRUSTED_PROXY_CIDRS": "10.0.0.0/8",
    })
    assert any(item["name"] == "VITE_API_URL" and item["status"] == "fail" for item in result)
    output = json.dumps(result).lower()
    assert "user:secret@" not in output
    assert "hidden" not in output
    assert "private-fixture" not in output
    assert "separate-hidden-key" not in output


def test_hosted_combine_architecture_prohibits_provider_mutation_paths():
    assert architecture_violations() == []
