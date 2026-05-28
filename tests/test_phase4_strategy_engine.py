import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pandas as pd
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402
from app.paper_execution import execute_paper_order  # noqa: E402
from app.providers.topstepx import TopStepXAdapter  # noqa: E402
from app.scheduler import BOT_SESSIONS, BOT_STATES  # noqa: E402
from app.strategy import STRATEGY_DESCRIPTION, STRATEGY_NAME  # noqa: E402
from app.strategy_engine import (  # noqa: E402
    create_strategy_config,
    mark_signal_executed,
    paper_performance_metrics,
    record_strategy_signal,
)
from app.trading_safety import build_order_intent  # noqa: E402


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
            "metadata": metadata or {"environment": "test", "account_id": "paper-account-1"},
            "credentials": {"userName": "user", "apiKey": "key"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def indicator_frame(rsi: float = 20, bars: int = 40, stale: bool = False):
    end = datetime.utcnow() - (timedelta(minutes=30) if stale else timedelta(seconds=30))
    index = pd.date_range(end=end, periods=bars, freq="min")
    close = [100.0 + i for i in range(bars)]
    return pd.DataFrame(
        {
            "close": close,
            "rsi": [rsi] * bars,
            "ma_fast": close,
            "ma_slow": close,
            "macd": [0.1] * bars,
            "macd_signal": [0.05] * bars,
        },
        index=index,
    )


def test_strategy_config_is_versioned_paper_only_and_truthful():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    live = client.post(
        "/scheduler/strategy-configs",
        json={
            "symbol": "ES",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "live",
        },
        headers=auth_headers(token),
    )
    assert live.status_code == 403

    unsupported_confirmation = client.post(
        "/scheduler/strategy-configs",
        json={
            "symbol": "ES",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "parameters": {"use_moving_average_confirmation": True},
        },
        headers=auth_headers(token),
    )
    assert unsupported_confirmation.status_code == 422

    created = client.post(
        "/scheduler/strategy-configs",
        json={
            "symbol": "ES",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "parameters": {"buy_threshold": 25, "sell_threshold": 75},
        },
        headers=auth_headers(token),
    )
    assert created.status_code == 200
    body = created.json()
    assert body["strategy_name"] == STRATEGY_NAME
    assert body["strategy_version"] == "1.0.0"
    assert "Moving averages" in body["description"]
    assert "not confirmation signals" in STRATEGY_DESCRIPTION


def test_bot_session_requires_integration_account_contract_and_paper_mode():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    missing_account = client.post(
        "/scheduler/bot-sessions",
        json={"symbol": "ES", "trading_mode": "paper", "integration_id": integration["id"]},
        headers=auth_headers(token),
    )
    assert missing_account.status_code == 422

    live = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "trading_mode": "live",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
        },
        headers=auth_headers(token),
    )
    assert live.status_code == 403

    paper = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "trading_mode": "paper",
            "integration_id": integration["id"],
            "account_id": "paper-account-1",
        },
        headers=auth_headers(token),
    )
    assert paper.status_code == 200
    assert paper.json()["strategy_config"]["strategy_name"] == STRATEGY_NAME
    assert paper.json()["session_id"] in BOT_SESSIONS


def test_strategy_signal_links_to_paper_order_and_metrics_without_broker_call(monkeypatch):
    calls = {"count": 0}

    async def fail_if_called(self, order):
        calls["count"] += 1
        raise AssertionError("broker place_order must not be called by paper strategy execution")

    monkeypatch.setattr(TopStepXAdapter, "place_order", fail_if_called)

    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    db = database.SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "alice").first()
        config = create_strategy_config(
            db,
            user_id=user.id,
            integration_id=integration["id"],
            account_id="paper-account-1",
            symbol="ES",
            trading_mode="paper",
            parameters={"buy_threshold": 25, "sell_threshold": 75},
        )
        signal = record_strategy_signal(db, config=config, indicators=indicator_frame(rsi=20))
        assert signal.signal == "BUY"
        assert signal.status == "emitted"

        intent = build_order_intent(
            user_id=user.id,
            symbol="ES",
            side=signal.signal,
            quantity=1,
            trading_mode="paper",
            integration_id=integration["id"],
            account_id="paper-account-1",
            idempotency_key=f"strategy:{signal.id}",
            source="bot",
            reference_price=139.25,
        )
        order = execute_paper_order(db, intent)
        mark_signal_executed(db, signal_id=signal.id, paper_order_id=order["order"]["id"])

        linked = db.query(models.StrategySignal).filter(models.StrategySignal.id == signal.id).first()
        assert linked.status == "executed"
        assert linked.paper_order_id == order["order"]["id"]
        assert db.query(models.PaperFill).first().price == 139.25
        metrics = paper_performance_metrics(db, user_id=user.id)
        assert metrics["paper_only"] is True
        assert metrics["orders"] == 1
        assert metrics["executed_signals"] == 1
        assert metrics["assumptions"]
    finally:
        db.close()
    assert calls["count"] == 0


def test_strategy_data_quality_and_cooldown_suppress_signals():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    db = database.SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "alice").first()
        stale_config = create_strategy_config(
            db,
            user_id=user.id,
            integration_id=integration["id"],
            account_id="paper-account-1",
            symbol="ES",
            trading_mode="paper",
            parameters={"min_bars": 30, "max_staleness_seconds": 60},
        )
        stale = record_strategy_signal(db, config=stale_config, indicators=indicator_frame(rsi=20, bars=10, stale=True))
        assert stale.status == "suppressed"
        assert stale.guardrail_decision["reason"] == "data_quality"
        assert "insufficient_bars" in stale.guardrail_decision["warnings"]
        assert "latest_bar_stale" in stale.guardrail_decision["warnings"]

        cooldown_config = create_strategy_config(
            db,
            user_id=user.id,
            integration_id=integration["id"],
            account_id="paper-account-1",
            symbol="NQ",
            trading_mode="paper",
            parameters={"buy_threshold": 25, "sell_threshold": 75, "cooldown_seconds": 300},
        )
        first = record_strategy_signal(db, config=cooldown_config, indicators=indicator_frame(rsi=20))
        second = record_strategy_signal(db, config=cooldown_config, indicators=indicator_frame(rsi=20))
        assert first.status == "emitted"
        assert second.status == "suppressed"
        assert second.guardrail_decision["reason"] == "cooldown_active"
    finally:
        db.close()
