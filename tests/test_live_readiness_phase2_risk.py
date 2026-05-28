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
    return {"Authorization": f"Bearer {token}"}


def create_integration(token: str, provider: str = "TOPSTEPX", metadata: dict | None = None):
    response = client.post(
        "/integrations",
        json={
            "display_name": f"{provider} Main",
            "provider": provider,
            "metadata": metadata or {"environment": "test", "account_id": "paper-account-1", "contracts": ["ES", "NQ"]},
            "credentials": {"userName": "user", "apiKey": "key"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def test_risk_schema_tables_and_indexes_exist():
    inspector = inspect(database.engine)
    table_names = set(inspector.get_table_names())
    assert {
        "risk_settings",
        "daily_risk_states",
        "kill_switches",
        "risk_lockout_events",
        "risk_decisions",
    }.issubset(table_names)

    risk_columns = {column["name"] for column in inspector.get_columns("risk_settings")}
    assert {"max_daily_loss", "max_quantity", "max_contracts", "max_open_positions", "live_trading_enabled"}.issubset(
        risk_columns
    )
    decision_columns = {column["name"] for column in inspector.get_columns("risk_decisions")}
    assert {"allowed", "reason_code", "decision_metadata"}.issubset(decision_columns)


def test_risk_settings_default_conservative_and_user_isolated():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")

    alice_default = client.get("/risk/settings", headers=auth_headers(alice_token))
    assert alice_default.status_code == 200
    assert alice_default.json()["max_quantity"] == 1
    assert alice_default.json()["max_contracts"] == 1
    assert alice_default.json()["max_open_positions"] == 1
    assert alice_default.json()["live_trading_enabled"] is False

    updated = client.put(
        "/risk/settings",
        json={
            "max_quantity": 3,
            "max_contracts": 3,
            "max_daily_loss": 250.0,
            "max_open_positions": 2,
            "live_trading_enabled": False,
        },
        headers=auth_headers(alice_token),
    )
    assert updated.status_code == 200
    assert updated.json()["max_quantity"] == 3

    bob_default = client.get("/risk/settings", headers=auth_headers(bob_token))
    assert bob_default.status_code == 200
    assert bob_default.json()["max_quantity"] == 1
    assert bob_default.json()["max_open_positions"] == 1


def test_risk_settings_validation_and_live_enable_rejected():
    register_user("alice")
    token = login_user("alice")

    invalid = client.put(
        "/risk/settings",
        json={
            "max_quantity": 0,
            "max_contracts": 1,
            "max_daily_loss": 0,
            "max_open_positions": 1,
        },
        headers=auth_headers(token),
    )
    assert invalid.status_code == 422

    live_enable = client.put(
        "/risk/settings",
        json={
            "max_quantity": 1,
            "max_contracts": 1,
            "max_daily_loss": 0,
            "max_open_positions": 1,
            "live_trading_enabled": True,
        },
        headers=auth_headers(token),
    )
    assert live_enable.status_code == 403
    assert live_enable.headers["X-Readiness-Blocker"] == "live_disabled"


def test_persisted_risk_settings_block_paper_order_and_audit_decision():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    updated = client.put(
        "/risk/settings",
        json={
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "max_quantity": 1,
            "max_contracts": 1,
            "max_daily_loss": 0,
            "max_open_positions": 0,
        },
        headers=auth_headers(token),
    )
    assert updated.status_code == 200

    blocked = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "idempotency_key": "risk-blocked-1",
        },
        headers=auth_headers(token),
    )
    assert blocked.status_code == 403
    assert blocked.headers["X-Readiness-Blocker"] == "max_open_positions_exceeded"

    decisions = client.get("/risk/decisions", headers=auth_headers(token))
    assert decisions.status_code == 200
    assert decisions.json()[0]["allowed"] is False
    assert decisions.json()[0]["reason_code"] == "max_open_positions_exceeded"


def test_kill_switch_blocks_orders_and_bot_sessions_until_deactivated():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    kill_switch = client.post(
        "/risk/kill-switches",
        json={
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "reason": "Emergency stop for test.",
        },
        headers=auth_headers(token),
    )
    assert kill_switch.status_code == 200
    switch_id = kill_switch.json()["id"]

    blocked_order = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "idempotency_key": "kill-switch-1",
        },
        headers=auth_headers(token),
    )
    assert blocked_order.status_code == 403
    assert blocked_order.headers["X-Readiness-Blocker"] == "kill_switch_active"

    blocked_session = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
        },
        headers=auth_headers(token),
    )
    assert blocked_session.status_code == 403
    assert blocked_session.headers["X-Readiness-Blocker"] == "kill_switch_active"

    deactivated = client.post(f"/risk/kill-switches/{switch_id}/deactivate", headers=auth_headers(token))
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False

    allowed_order = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "idempotency_key": "kill-switch-cleared-1",
        },
        headers=auth_headers(token),
    )
    assert allowed_order.status_code == 200


def test_kill_switch_and_settings_ownership_are_user_scoped():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    alice_integration = create_integration(alice_token)

    foreign_settings = client.get(
        "/risk/settings",
        params={"integration_id": alice_integration["id"]},
        headers=auth_headers(bob_token),
    )
    assert foreign_settings.status_code == 404

    foreign_switch = client.post(
        "/risk/kill-switches",
        json={"integration_id": alice_integration["id"], "reason": "not mine"},
        headers=auth_headers(bob_token),
    )
    assert foreign_switch.status_code == 404

    alice_switch = client.post(
        "/risk/kill-switches",
        json={"integration_id": alice_integration["id"], "reason": "owned"},
        headers=auth_headers(alice_token),
    )
    assert alice_switch.status_code == 200
    bob_deactivate = client.post(
        f"/risk/kill-switches/{alice_switch.json()['id']}/deactivate",
        headers=auth_headers(bob_token),
    )
    assert bob_deactivate.status_code == 404


def test_live_trading_remains_blocked_and_no_paper_order_is_created():
    register_user("alice")
    token = login_user("alice")

    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "live",
            "idempotency_key": "live-still-blocked",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 403
    assert "Live trading is disabled" in response.json()["detail"]

    db = database.SessionLocal()
    try:
        assert db.query(models.PaperOrder).count() == 0
    finally:
        db.close()
