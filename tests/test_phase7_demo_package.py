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


def test_demo_seed_creates_only_paper_safe_records_and_live_remains_blocked():
    register_user("demo")
    token = login_user("demo")

    seeded = client.post("/demo/seed", headers=auth_headers(token))
    assert seeded.status_code == 200
    body = seeded.json()
    assert body["seeded"] is True
    assert body["paper_only"] is True
    assert body["live_trading_enabled"] is False
    assert body["demo_account_id"] == "DEMO-PAPER-001"
    assert body["counts"]["integrations"] == 1
    assert body["counts"]["paper_orders"] == 2
    assert body["counts"]["paper_positions"] == 2
    assert body["counts"]["strategy_signals"] == 1

    live = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "live",
            "idempotency_key": "demo-live-attempt",
        },
        headers=auth_headers(token),
    )
    assert live.status_code == 403
    assert "Live trading is disabled" in live.json()["detail"]


def test_demo_reset_removes_only_current_users_demo_data():
    register_user("alice")
    register_user("bob")
    alice = login_user("alice")
    bob = login_user("bob")

    assert client.post("/demo/seed", headers=auth_headers(alice)).status_code == 200
    assert client.post("/demo/seed", headers=auth_headers(bob)).status_code == 200

    reset = client.post("/demo/reset", headers=auth_headers(alice))
    assert reset.status_code == 200
    assert reset.json()["seeded"] is False

    bob_status = client.get("/demo/status", headers=auth_headers(bob))
    assert bob_status.status_code == 200
    assert bob_status.json()["seeded"] is True
    assert bob_status.json()["counts"]["paper_orders"] == 2
