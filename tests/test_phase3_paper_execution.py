import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402
from app.scheduler import BOT_SESSIONS, BOT_STATES  # noqa: E402
from app.providers.topstepx import TopStepXAdapter  # noqa: E402


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
    response = client.post(
        "/integrations",
        json={
            "display_name": f"{provider} Main",
            "provider": provider,
            "metadata": {"environment": "test"},
            "credentials": credentials if credentials is not None else {"userName": "user", "apiKey": "key"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def test_manual_paper_order_has_lifecycle_idempotency_fill_and_position():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    payload = {
        "symbol": "ES",
        "side": "BUY",
        "quantity": 1,
        "integration_id": integration["id"],
        "trading_mode": "paper",
        "idempotency_key": "manual-1",
    }

    first = client.post("/scheduler/execute-trade", json=payload, headers=auth_headers(token))
    assert first.status_code == 200
    body = first.json()
    assert body["paper"] is True
    assert body["live"] is False
    assert body["duplicate"] is False
    assert body["status"] == "filled"
    assert body["order"]["status"] == "filled"
    assert body["order"]["idempotency_key"] == "manual-1"
    assert [event["event_type"] for event in body["events"]] == [
        "created",
        "pending_submit",
        "submitted",
        "accepted",
        "filled",
    ]
    assert body["fills"][0]["quantity"] == 1
    assert body["position"]["quantity"] == 1

    duplicate = client.post("/scheduler/execute-trade", json=payload, headers=auth_headers(token))
    assert duplicate.status_code == 200
    duplicate_body = duplicate.json()
    assert duplicate_body["duplicate"] is True
    assert duplicate_body["order"]["id"] == body["order"]["id"]

    db = database.SessionLocal()
    try:
        assert db.query(models.PaperOrder).count() == 1
        assert db.query(models.PaperFill).count() == 1
    finally:
        db.close()


def test_idempotency_key_conflict_rejects_different_order():
    register_user("alice")
    token = login_user("alice")
    payload = {
        "symbol": "ES",
        "side": "BUY",
        "quantity": 1,
        "trading_mode": "paper",
        "idempotency_key": "manual-1",
    }
    assert client.post("/scheduler/execute-trade", json=payload, headers=auth_headers(token)).status_code == 200

    changed = {**payload, "side": "SELL"}
    conflict = client.post("/scheduler/execute-trade", json=changed, headers=auth_headers(token))
    assert conflict.status_code == 409


def test_manual_order_requires_idempotency_key_and_live_remains_blocked():
    register_user("alice")
    token = login_user("alice")

    missing_key = client.post(
        "/scheduler/execute-trade",
        json={"symbol": "ES", "side": "BUY", "quantity": 1, "trading_mode": "paper"},
        headers=auth_headers(token),
    )
    assert missing_key.status_code == 422

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


def test_paper_execution_does_not_call_broker_place_order(monkeypatch):
    calls = {"count": 0}

    async def fail_if_called(self, order):
        calls["count"] += 1
        raise AssertionError("broker place_order must not be called for paper execution")

    monkeypatch.setattr(TopStepXAdapter, "place_order", fail_if_called)

    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "trading_mode": "paper",
            "idempotency_key": "manual-1",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert calls["count"] == 0


def test_webhook_duplicate_uses_db_idempotency():
    register_user("alice")
    token = login_user("alice")
    signal_integration = create_integration(
        token,
        provider="TRADINGVIEW",
        credentials={"webhookSecret": "expected"},
    )
    payload = {
        "symbol": "ES",
        "side": "BUY",
        "quantity": 1,
        "signal_integration_id": signal_integration["id"],
        "secret": "expected",
        "idempotency_key": "signal-1",
        "trading_mode": "paper",
    }

    first = client.post("/trading/webhook", json=payload)
    assert first.status_code == 200
    assert first.json()["status"] == "received"

    second = client.post("/trading/webhook", json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["result"]["duplicate"] is True
    assert second.json()["result"]["order"]["id"] == first.json()["result"]["order"]["id"]


def test_order_status_and_positions_are_user_scoped():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    order = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "paper",
            "idempotency_key": "manual-1",
        },
        headers=auth_headers(alice_token),
    )
    assert order.status_code == 200
    order_id = order.json()["order"]["id"]

    alice_status = client.get(f"/scheduler/orders/{order_id}", headers=auth_headers(alice_token))
    assert alice_status.status_code == 200
    assert alice_status.json()["order"]["id"] == order_id

    bob_status = client.get(f"/scheduler/orders/{order_id}", headers=auth_headers(bob_token))
    assert bob_status.status_code == 404

    alice_positions = client.get("/scheduler/positions", headers=auth_headers(alice_token))
    bob_positions = client.get("/scheduler/positions", headers=auth_headers(bob_token))
    assert alice_positions.status_code == 200
    assert alice_positions.json()[0]["quantity"] == 1
    assert bob_positions.status_code == 200
    assert bob_positions.json() == []

    open_orders = client.get("/scheduler/open-orders", headers=auth_headers(alice_token))
    assert open_orders.status_code == 200
    assert open_orders.json() == []
