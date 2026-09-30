import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402
from app.reconciliation_service import (  # noqa: E402
    classify_provider_error,
    normalize_provider_order_status,
    reconciliation_service,
)
from app.scheduler import BOT_SESSIONS, BOT_STATES  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    BOT_SESSIONS.clear()
    BOT_STATES.clear()
    yield


def register_user(username: str):
    return client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
        },
    )


def login_user(username: str) -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": "StrongPass1", "grant_type": "password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Internal-Paper-Fixture": "true"}


def create_integration(token: str):
    response = client.post(
        "/integrations",
        json={
            "display_name": "Paper Broker",
            "provider": "TOPSTEPX",
            "metadata": {"environment": "test", "account_id": "paper-account-1", "contracts": ["ES"]},
            "credentials": {"userName": "user", "apiKey": "key"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def widen_paper_risk(token: str, integration_id: int):
    response = client.put(
        "/risk/settings",
        json={
            "integration_id": integration_id,
            "account_id": "paper-account-1",
            "max_quantity": 5,
            "max_contracts": 5,
            "max_daily_loss": 1000,
            "max_open_positions": 5,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.place_order_calls = 0

    def get_order_status(self, **kwargs):
        return self.payload

    def place_order(self, order):
        self.place_order_calls += 1
        raise AssertionError("place_order must not be called by reconciliation")


class FailingProvider:
    def get_order_status(self, **kwargs):
        raise TimeoutError("provider request timed out after possible submit")

    def place_order(self, order):
        raise AssertionError("place_order must not be called by reconciliation")


def test_reconciliation_schema_exists():
    inspector = inspect(database.engine)
    assert {
        "provider_reconciliation_runs",
        "provider_reconciliation_events",
        "provider_retry_decisions",
        "account_reconciliation_locks",
    }.issubset(set(inspector.get_table_names()))


def test_provider_status_and_error_classification_are_fail_closed():
    assert normalize_provider_order_status("working") == "accepted"
    assert normalize_provider_order_status("partial_fill") == "partially_filled"
    assert normalize_provider_order_status("filled") == "filled"
    assert normalize_provider_order_status("vendor-weird-state") == "timeout_unknown"

    timeout = classify_provider_error("request timeout")
    assert timeout.error_type == "timeout_unknown"
    assert timeout.retryable is False
    assert timeout.requires_reconciliation is True

    rate_limit = classify_provider_error("429 rate limit")
    assert rate_limit.retryable is True
    assert rate_limit.requires_reconciliation is False


def test_reconcile_order_records_success_with_mocked_provider_and_never_places_order():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    provider = FakeProvider({"status": "filled", "id": "provider-1"})

    db = database.SessionLocal()
    try:
        run = reconciliation_service.reconcile_order(
            db,
            user_id=1,
            integration_id=integration["id"],
            account_id="paper-account-1",
            provider=provider,
            symbol="ES",
            provider_order_id="provider-1",
            expected_status="filled",
        )
        db.commit()
        assert run.status == "succeeded"
        assert run.summary["normalized_status"] == "filled"
        assert provider.place_order_calls == 0
        assert db.query(models.ProviderReconciliationEvent).filter_by(run_id=run.id).count() == 1
    finally:
        db.close()


def test_reconciliation_mismatch_creates_account_lock_and_blocks_new_paper_orders():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    widen_paper_risk(token, integration["id"])
    provider = FakeProvider({"status": "open", "id": "provider-1"})

    db = database.SessionLocal()
    try:
        run = reconciliation_service.reconcile_order(
            db,
            user_id=1,
            integration_id=integration["id"],
            account_id="paper-account-1",
            provider=provider,
            symbol="ES",
            provider_order_id="provider-1",
            expected_status="filled",
        )
        db.commit()
        assert run.status == "mismatch"
    finally:
        db.close()

    blocked = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "reference_price": 100,
            "idempotency_key": "blocked-by-reconciliation",
        },
        headers=auth_headers(token),
    )
    assert blocked.status_code == 403
    assert blocked.headers["X-Readiness-Blocker"] == "reconciliation_required"


def test_timeout_records_retry_decision_and_reconciliation_lock():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    db = database.SessionLocal()
    try:
        run = reconciliation_service.reconcile_order(
            db,
            user_id=1,
            integration_id=integration["id"],
            account_id="paper-account-1",
            provider=FailingProvider(),
            symbol="ES",
            provider_order_id="provider-timeout",
            expected_status="filled",
        )
        db.commit()
        assert run.status == "failed"
        decision = db.query(models.ProviderRetryDecision).filter_by(user_id=1).first()
        assert decision.error_type == "timeout_unknown"
        assert decision.retryable == 0
        assert decision.requires_reconciliation == 1
        assert db.query(models.AccountReconciliationLock).filter_by(user_id=1, active=1).count() == 1
    finally:
        db.close()


def test_reconciliation_api_is_user_scoped_and_records_retry_diagnostics():
    register_user("alice")
    register_user("bob")
    alice = login_user("alice")
    bob = login_user("bob")
    integration = create_integration(alice)

    foreign = client.post(
        "/reconciliation/retry-decisions",
        json={"integration_id": integration["id"], "error": "timeout"},
        headers=auth_headers(bob),
    )
    assert foreign.status_code == 404

    created = client.post(
        "/reconciliation/retry-decisions",
        json={"integration_id": integration["id"], "account_id": "paper-account-1", "error": "provider unavailable"},
        headers=auth_headers(alice),
    )
    assert created.status_code == 200
    assert created.json()["requires_reconciliation"] is True

    assert client.get("/reconciliation/retry-decisions", headers=auth_headers(alice)).json()
    assert client.get("/reconciliation/retry-decisions", headers=auth_headers(bob)).json() == []


def test_live_trading_remains_blocked_and_broker_place_order_is_not_called():
    register_user("alice")
    token = login_user("alice")
    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "live",
            "idempotency_key": "phase4-live-blocked",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 403
    assert "Live trading is disabled" in response.json()["detail"]
