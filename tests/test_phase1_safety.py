import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database  # noqa: E402
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


def create_integration(token: str, provider: str = "TOPSTEPX", credentials: dict | None = None):
    payload = {
        "display_name": f"{provider} Main",
        "provider": provider,
        "metadata": {"environment": "test"},
        "credentials": credentials if credentials is not None else {"userName": "user", "apiKey": "key"},
    }
    response = client.post("/integrations", json=payload, headers=auth_headers(token))
    assert response.status_code == 201
    return response.json()


def test_scheduler_control_routes_require_authentication():
    assert client.post("/scheduler/update-config", json={"auto_trade": False}).status_code == 401
    assert client.post("/scheduler/stop-bot").status_code == 401
    assert client.post("/scheduler/bot-sessions", json={"symbol": "ES"}).status_code == 401


def test_manual_trade_is_paper_only_and_live_is_blocked():
    register_user("alice")
    token = login_user("alice")

    paper = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "paper",
            "idempotency_key": "paper-1",
        },
        headers=auth_headers(token),
    )
    assert paper.status_code == 200
    assert paper.json()["paper"] is True
    assert paper.json()["live"] is False

    live = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "live",
            "idempotency_key": "live-1",
        },
        headers=auth_headers(token),
    )
    assert live.status_code == 403
    assert "Live trading is disabled" in live.json()["detail"]


def test_manual_trade_rejects_other_users_integration():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    alice_integration = create_integration(alice_token)

    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": alice_integration["id"],
            "trading_mode": "paper",
            "idempotency_key": "foreign-integration-1",
        },
        headers=auth_headers(bob_token),
    )
    assert response.status_code == 404


def test_bot_session_is_user_scoped_and_live_mode_is_blocked():
    register_user("alice")
    register_user("bob")
    token = login_user("alice")
    bob_token = login_user("bob")
    alice_integration = create_integration(token)

    live_session = client.post(
        "/scheduler/bot-sessions",
        json={"symbol": "ES", "trading_mode": "live"},
        headers=auth_headers(token),
    )
    assert live_session.status_code == 403

    foreign_integration = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "trading_mode": "paper",
            "integration_id": alice_integration["id"],
        },
        headers=auth_headers(bob_token),
    )
    assert foreign_integration.status_code == 404

    paper_session = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "trading_mode": "paper",
            "auto_trade": True,
            "integration_id": alice_integration["id"],
        },
        headers=auth_headers(token),
    )
    assert paper_session.status_code == 200
    assert paper_session.json()["trading_mode"] == "paper"
    assert paper_session.json()["session_id"] in BOT_SESSIONS


def test_webhook_requires_secret_and_idempotency_key():
    register_user("alice")
    token = login_user("alice")
    signal_integration = create_integration(token, provider="TRADINGVIEW", credentials=None)

    missing_secret = client.post(
        "/trading/webhook",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "signal_integration_id": signal_integration["id"],
            "idempotency_key": "signal-1",
        },
    )
    assert missing_secret.status_code == 401

    secret_integration = create_integration(
        token,
        provider="TRADINGVIEW",
        credentials={"webhookSecret": "expected"},
    )
    accepted = client.post(
        "/trading/webhook",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "signal_integration_id": secret_integration["id"],
            "secret": "expected",
            "idempotency_key": "signal-2",
            "trading_mode": "paper",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["result"]["paper"] is True

    duplicate = client.post(
        "/trading/webhook",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "signal_integration_id": secret_integration["id"],
            "secret": "expected",
            "idempotency_key": "signal-2",
            "trading_mode": "paper",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["result"]["duplicate"] is True
