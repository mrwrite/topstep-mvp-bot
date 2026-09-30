from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault("APP_ENV", "test")
smoke_db = Path(tempfile.gettempdir()) / f"tradebot-demo-smoke-{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{smoke_db.as_posix()}"
os.environ.setdefault("SECRET_KEY", "demo-smoke-secret")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
os.environ["ALLOW_CREATE_ALL"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
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

    active = client.get("/integrations/active", headers=headers)
    assert active.status_code == 200 and active.json()["active"], active.text
    integration_id = active.json()["active"]["id"]
    account_id = seeded.json()["demo_account_id"]

    session = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": integration_id,
            "account_id": account_id,
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
            "account_id": account_id,
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

    print("Demo smoke passed: isolated paper-only seed/status/reset flow works; live trading is disabled.")
    database.engine.dispose()
    smoke_db.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
