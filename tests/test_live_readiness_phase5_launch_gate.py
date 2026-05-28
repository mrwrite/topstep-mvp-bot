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
from app.scheduler import BOT_SESSIONS, BOT_STATES  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
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
    return {"Authorization": f"Bearer {token}"}


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


def create_ready_scope(token: str):
    integration = create_integration(token)
    settings = client.put(
        "/risk/settings",
        json={
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "max_quantity": 5,
            "max_contracts": 5,
            "max_daily_loss": 1000,
            "max_open_positions": 5,
        },
        headers=auth_headers(token),
    )
    assert settings.status_code == 200
    order = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "reference_price": 100,
            "idempotency_key": "paper-ledger-for-launch-gate",
        },
        headers=auth_headers(token),
    )
    assert order.status_code == 200
    return integration, settings.json()


def create_ack(token: str, integration_id: int):
    response = client.post(
        "/launch-gate/acknowledgements",
        json={
            "integration_id": integration_id,
            "account_id": "paper-account-1",
            "symbol": "ES",
            "confirm_no_profit_guarantee": True,
            "confirm_user_responsibility": True,
            "confirm_live_trading_still_disabled": True,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    return response.json()


def gate_codes(response_json: dict) -> dict[str, bool]:
    return {gate["code"]: gate["passed"] for gate in response_json["gates"]}


def test_launch_gate_schema_exists():
    inspector = inspect(database.engine)
    assert {"live_readiness_acknowledgements", "launch_gate_evaluations"}.issubset(
        set(inspector.get_table_names())
    )


def test_launch_gate_reports_failure_cases_before_acknowledgement():
    register_user("alice")
    token = login_user("alice")
    integration, _settings = create_ready_scope(token)

    response = client.get(
        "/launch-gate",
        params={"integration_id": integration["id"], "account_id": "paper-account-1", "symbol": "ES"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    codes = gate_codes(body)
    assert codes["global_live_disabled_by_default"] is True
    assert codes["trading_context_valid"] is True
    assert codes["risk_settings_exist"] is True
    assert codes["paper_ledger_exists"] is True
    assert codes["legal_risk_acknowledgement_current"] is False
    assert body["all_required_gates_passed"] is False
    assert body["live_trading_available"] is False


def test_acknowledgement_is_user_scoped_and_requires_all_confirmations():
    register_user("alice")
    register_user("bob")
    alice = login_user("alice")
    bob = login_user("bob")
    integration, _settings = create_ready_scope(alice)

    incomplete = client.post(
        "/launch-gate/acknowledgements",
        json={
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "symbol": "ES",
            "confirm_no_profit_guarantee": True,
            "confirm_user_responsibility": False,
            "confirm_live_trading_still_disabled": True,
        },
        headers=auth_headers(alice),
    )
    assert incomplete.status_code == 422

    foreign = client.post(
        "/launch-gate/acknowledgements",
        json={
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "symbol": "ES",
            "confirm_no_profit_guarantee": True,
            "confirm_user_responsibility": True,
            "confirm_live_trading_still_disabled": True,
        },
        headers=auth_headers(bob),
    )
    assert foreign.status_code == 404

    ack = create_ack(alice, integration["id"])
    assert ack["accepted"] is True
    assert ack["metadata"]["live_trading_still_disabled"] is True
    assert client.get("/launch-gate/acknowledgements", headers=auth_headers(bob)).json() == []


def test_launch_gate_can_pass_required_gates_but_live_trading_remains_unavailable():
    register_user("alice")
    token = login_user("alice")
    integration, _settings = create_ready_scope(token)
    create_ack(token, integration["id"])

    gate = client.get(
        "/launch-gate",
        params={"integration_id": integration["id"], "account_id": "paper-account-1", "symbol": "ES"},
        headers=auth_headers(token),
    )
    assert gate.status_code == 200
    body = gate.json()
    assert body["all_required_gates_passed"] is True
    assert body["live_feature_flag_enabled"] is False
    assert body["live_trading_available"] is False
    assert "feature flag" in body["live_trading_blocked_reason"]

    live = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "live",
            "idempotency_key": "ack-does-not-enable-live",
        },
        headers=auth_headers(token),
    )
    assert live.status_code == 403
    assert "Live trading is disabled" in live.json()["detail"]


def test_launch_gate_records_evaluations_and_is_user_scoped():
    register_user("alice")
    register_user("bob")
    alice = login_user("alice")
    bob = login_user("bob")
    integration, _settings = create_ready_scope(alice)

    evaluated = client.get(
        "/launch-gate",
        params={"integration_id": integration["id"], "account_id": "paper-account-1", "symbol": "ES"},
        headers=auth_headers(alice),
    )
    assert evaluated.status_code == 200

    alice_evaluations = client.get("/launch-gate/evaluations", headers=auth_headers(alice))
    bob_evaluations = client.get("/launch-gate/evaluations", headers=auth_headers(bob))
    assert alice_evaluations.status_code == 200
    assert alice_evaluations.json()[0]["id"] == evaluated.json()["evaluation_id"]
    assert bob_evaluations.status_code == 200
    assert bob_evaluations.json() == []


def test_reconciliation_lock_blocks_launch_gate():
    register_user("alice")
    token = login_user("alice")
    integration, _settings = create_ready_scope(token)
    create_ack(token, integration["id"])

    db = database.SessionLocal()
    try:
        db.add(
            models.AccountReconciliationLock(
                user_id=1,
                integration_id=integration["id"],
                account_id="paper-account-1",
                active=1,
                reason="Provider/app mismatch unresolved.",
            )
        )
        db.commit()
    finally:
        db.close()

    gate = client.get(
        "/launch-gate",
        params={"integration_id": integration["id"], "account_id": "paper-account-1", "symbol": "ES"},
        headers=auth_headers(token),
    )
    assert gate.status_code == 200
    codes = gate_codes(gate.json())
    assert codes["broker_reconciliation_clear"] is False
    assert gate.json()["all_required_gates_passed"] is False
