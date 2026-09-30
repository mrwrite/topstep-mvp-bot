from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import models
from app.time_utils import utc_now


URL = os.getenv("HOSTED_POLICY_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="dedicated migrated PostgreSQL policy test DB is not configured")


def _policy(user_id: int, integration_id: int, version: int = 1):
    return models.HostedCombineRiskPolicy(
        id=str(uuid4()), user_id=user_id, cohort_id="pg-fixture-cohort", tester_user_id=user_id,
        integration_id=integration_id, provider_account_id="fixture-account", policy_version=version,
        state="active", policy={"fixture": True}, required_consent_version="fixture-consent-v1",
        effective_at=utc_now(), expires_at=utc_now() + timedelta(days=1),
        approved_by_operator_id=user_id, operator_context={"purpose": "postgres fixture", "case_id": "PG-TEST"},
    )


def test_postgres_enforces_single_active_policy_and_tenant_bound_references():
    engine = create_engine(URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        required = {"hosted_combine_risk_policies", "hosted_combine_consents", "hosted_combine_dry_runs"}
        assert required.issubset(set(inspect(engine).get_table_names()))
        suffix = uuid4().hex
        users = [
            models.User(username=f"hosted-risk-a-{suffix}", email=f"hosted-risk-a-{suffix}@test.invalid", hashed_password="x"),
            models.User(username=f"hosted-risk-b-{suffix}", email=f"hosted-risk-b-{suffix}@test.invalid", hashed_password="x"),
        ]
        db.add_all(users)
        db.flush()
        integrations = [
            models.PlatformIntegration(user_id=user.id, display_name="fixture", provider="TOPSTEPX", status="approved")
            for user in users
        ]
        db.add_all(integrations)
        db.flush()
        policies = [_policy(user.id, integration.id) for user, integration in zip(users, integrations)]
        db.add_all(policies)
        db.commit()

        db.add(_policy(users[0].id, integrations[0].id, 2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        consents = [models.HostedCombineConsent(
            id=str(uuid4()), user_id=user.id, integration_id=integration.id,
            credential_generation=1, provider_account_id="fixture-account", approval_id="fixture-approval",
            policy_version=1, consent_version="fixture-consent-v1", consent_text="fixture",
            accepted_at=utc_now(), correlation_id=str(uuid4()),
        ) for user, integration in zip(users, integrations)]
        db.add_all(consents)
        db.commit()
        dry_run = models.HostedCombineDryRun(
            id=str(uuid4()), user_id=users[1].id, integration_id=integrations[1].id,
            credential_generation=1, provider_account_id="fixture-account", approval_id="fixture-approval",
            approval_version=1, security_epoch=1, policy_id=policies[0].id, policy_version=1,
            consent_id=consents[1].id, strategy_name="rsi-threshold-v1", strategy_version="1.0.0",
            configuration_hash="cfg", instrument="MES", source_run_id="run", market_input_id="market",
            market_identity="market", state="requested", idempotency_key=str(uuid4()),
            stable_identity=str(uuid4()), correlation_id=str(uuid4()), requested_at=utc_now(),
        )
        db.add(dry_run)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
        engine.dispose()
