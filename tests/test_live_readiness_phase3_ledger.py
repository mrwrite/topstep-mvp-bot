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
from app.paper_execution import ORDER_STATUS_ACCEPTED, ORDER_STATUS_FILLED, _transition_order  # noqa: E402
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


def test_paper_ledger_schema_exists():
    inspector = inspect(database.engine)
    assert {"paper_account_snapshots", "paper_ledger_entries"}.issubset(set(inspector.get_table_names()))
    order_columns = {column["name"] for column in inspector.get_columns("paper_orders")}
    assert {"order_fingerprint", "limit_price", "stop_price", "filled_quantity", "remaining_quantity"}.issubset(
        order_columns
    )
    position_columns = {column["name"] for column in inspector.get_columns("paper_positions")}
    assert "avg_price" in position_columns


def test_paper_order_updates_ledger_snapshot_position_and_pnl():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    widen_paper_risk(token, integration["id"])

    buy = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "reference_price": 100.0,
            "idempotency_key": "ledger-buy",
        },
        headers=auth_headers(token),
    )
    assert buy.status_code == 200
    assert buy.json()["status"] == "filled"
    assert buy.json()["order"]["filled_quantity"] == 1
    assert buy.json()["account"]["cash_balance"] == 99900.0
    assert buy.json()["position"]["avg_price"] == 100.0

    sell = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "SELL",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "reference_price": 110.0,
            "idempotency_key": "ledger-sell",
        },
        headers=auth_headers(token),
    )
    assert sell.status_code == 200
    assert sell.json()["account"]["realized_pnl"] == 10.0
    assert sell.json()["position"]["quantity"] == 0

    accounts = client.get("/scheduler/paper-accounts", headers=auth_headers(token))
    assert accounts.status_code == 200
    assert accounts.json()[0]["realized_pnl"] == 10.0

    ledger = client.get("/scheduler/paper-ledger", headers=auth_headers(token))
    assert ledger.status_code == 200
    assert [entry["entry_type"] for entry in ledger.json()].count("fill") == 2
    assert any(entry["entry_type"] == "starting_balance" for entry in ledger.json())


def test_duplicate_fingerprint_suppresses_new_order_with_different_key():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    widen_paper_risk(token, integration["id"])
    payload = {
        "symbol": "ES",
        "side": "BUY",
        "quantity": 1,
        "integration_id": integration["id"],
        "account_id": "paper-account-1",
        "trading_mode": "paper",
        "reference_price": 100.0,
    }

    first = client.post("/scheduler/execute-trade", json={**payload, "idempotency_key": "duplicate-a"}, headers=auth_headers(token))
    assert first.status_code == 200
    second = client.post("/scheduler/execute-trade", json={**payload, "idempotency_key": "duplicate-b"}, headers=auth_headers(token))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["order"]["id"] == first.json()["order"]["id"]

    db = database.SessionLocal()
    try:
        assert db.query(models.PaperOrder).count() == 1
        events = db.query(models.PaperOrderEvent).filter(models.PaperOrderEvent.event_type == "duplicate_suppressed").all()
        assert len(events) == 1
    finally:
        db.close()


def test_limit_order_rejection_records_lifecycle_without_fill_or_ledger_fill():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    widen_paper_risk(token, integration["id"])

    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "order_type": "limit",
            "limit_price": 90.0,
            "reference_price": 100.0,
            "idempotency_key": "limit-reject",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["success"] is False
    assert body["fills"] == []
    assert [event["event_type"] for event in body["events"]] == ["created", "pending_submit", "submitted", "rejected"]


def test_invalid_state_transition_is_rejected_and_audited():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)
    widen_paper_risk(token, integration["id"])
    order_response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "reference_price": 100.0,
            "idempotency_key": "invalid-transition",
        },
        headers=auth_headers(token),
    )
    assert order_response.status_code == 200

    db = database.SessionLocal()
    try:
        order = db.query(models.PaperOrder).filter(models.PaperOrder.id == order_response.json()["order"]["id"]).first()
        with pytest.raises(Exception):
            _transition_order(
                db,
                order=order,
                new_status=ORDER_STATUS_ACCEPTED,
                event_type="accepted",
                message="invalid",
            )
        assert order.status == ORDER_STATUS_FILLED
    finally:
        db.close()


def test_paper_ledger_and_risk_blocked_orders_are_user_scoped():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    integration = create_integration(alice_token)
    widen_paper_risk(alice_token, integration["id"])

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
            "idempotency_key": "alice-ledger",
        },
        headers=auth_headers(alice_token),
    )
    assert order.status_code == 200
    assert client.get("/scheduler/paper-ledger", headers=auth_headers(alice_token)).json()
    assert client.get("/scheduler/paper-ledger", headers=auth_headers(bob_token)).json() == []

    blocked = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "NQ",
            "side": "BUY",
            "quantity": 2,
            "trading_mode": "paper",
            "idempotency_key": "risk-blocked-state",
        },
        headers=auth_headers(bob_token),
    )
    assert blocked.status_code == 403
    db = database.SessionLocal()
    try:
        risk_blocked = (
            db.query(models.PaperOrder)
            .filter(models.PaperOrder.user_id == 2, models.PaperOrder.status == "risk_blocked")
            .first()
        )
        assert risk_blocked is not None
    finally:
        db.close()


def test_live_trading_remains_blocked_with_phase3_changes():
    register_user("alice")
    token = login_user("alice")
    response = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "trading_mode": "live",
            "idempotency_key": "phase3-live-blocked",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 403
    assert "Live trading is disabled" in response.json()["detail"]
