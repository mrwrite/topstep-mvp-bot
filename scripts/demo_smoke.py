from __future__ import annotations

import os
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "demo-smoke-secret")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    database.Base.metadata.create_all(bind=database.engine)
    client = TestClient(app)
    username = f"demo_{uuid.uuid4().hex[:8]}"
    password = "StrongPass1"

    register = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert register.status_code == 201, register.text

    login = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    seeded = client.post("/demo/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["paper_only"] is True
    assert seeded.json()["live_trading_enabled"] is False

    integration = client.post(
        "/integrations",
        json={
            "display_name": "Smoke Paper Broker",
            "provider": "TOPSTEPX",
            "metadata": {"environment": "demo", "account_id": "SMOKE-PAPER-001"},
            "credentials": {
                "userName": "smoke-paper-user",
                "apiKey": "smoke-paper-key-not-live",
                "baseUrl": "https://demo.invalid",
            },
        },
        headers=headers,
    )
    assert integration.status_code == 201, integration.text
    integration_id = integration.json()["id"]

    activate = client.put(f"/integrations/{integration_id}/activate", headers=headers)
    assert activate.status_code == 200, activate.text

    session = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": integration_id,
            "account_id": "SMOKE-PAPER-001",
            "trading_mode": "paper",
            "auto_trade": False,
        },
        headers=headers,
    )
    assert session.status_code == 200, session.text

    order = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": integration_id,
            "account_id": "SMOKE-PAPER-001",
            "trading_mode": "paper",
            "idempotency_key": f"smoke:{uuid.uuid4().hex}",
        },
        headers=headers,
    )
    assert order.status_code == 200, order.text
    assert order.json()["live"] is False

    order_status = client.get(f"/scheduler/orders/{order.json()['order']['id']}", headers=headers)
    assert order_status.status_code == 200, order_status.text
    assert order_status.json()["events"], order_status.text

    stop = client.post("/scheduler/stop-bot", headers=headers)
    assert stop.status_code == 200, stop.text

    orders = client.get("/scheduler/open-orders", headers=headers)
    assert orders.status_code == 200, orders.text

    status = client.get("/ops/status")
    assert status.status_code == 200, status.text
    assert status.json()["live_trading_enabled"] is False

    reset = client.post("/demo/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["seeded"] is False

    print("Demo smoke passed: paper-only seed/status/reset flow works and live trading is disabled.")


if __name__ == "__main__":
    main()
