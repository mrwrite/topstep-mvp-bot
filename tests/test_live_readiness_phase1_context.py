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
from app.providers.types import IntegrationCapability  # noqa: E402
import app.scheduler as scheduler_module  # noqa: E402
from app.scheduler import BOT_SESSIONS, BOT_STATES  # noqa: E402
from app.trading_context import TradingContextError, trading_context_service  # noqa: E402


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


def create_integration(
    token: str,
    provider: str = "TOPSTEPX",
    *,
    metadata: dict | None = None,
    credentials: dict | None = None,
    status: str = "active",
):
    response = client.post(
        "/integrations",
        json={
            "display_name": f"{provider} Main",
            "provider": provider,
            "status": status,
            "metadata": metadata or {"environment": "test", "account_id": "paper-account-1", "contracts": ["ES"]},
            "credentials": credentials if credentials is not None else {"userName": "user", "apiKey": "key"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def test_trading_context_service_enforces_owner_status_capability_account_contract_and_live_block():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    alice_integration = create_integration(alice_token)
    inactive = create_integration(alice_token, status="inactive")
    bob_token = bob_token

    # Use API-level assertions for cross-user and inactive failures because user ids are scoped internally.
    foreign = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": alice_integration["id"],
            "trading_mode": "paper",
            "idempotency_key": "foreign-context",
        },
        headers=auth_headers(bob_token),
    )
    assert foreign.status_code == 404
    assert foreign.headers["X-Readiness-Blocker"] == "integration_not_found"

    inactive_response = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": inactive["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
        },
        headers=auth_headers(alice_token),
    )
    assert inactive_response.status_code == 400
    assert inactive_response.headers["X-Readiness-Blocker"] == "integration_inactive"

    wrong_account = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": alice_integration["id"],
            "account_id": "other-account",
            "trading_mode": "paper",
        },
        headers=auth_headers(alice_token),
    )
    assert wrong_account.status_code == 422
    assert wrong_account.headers["X-Readiness-Blocker"] == "account_not_selected_for_integration"

    live = client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": alice_integration["id"],
            "trading_mode": "live",
            "idempotency_key": "live-context",
        },
        headers=auth_headers(alice_token),
    )
    assert live.status_code == 403
    assert live.headers["X-Readiness-Blocker"] == "live_disabled"


def test_context_readiness_shape_reports_stable_blocker_codes():
    register_user("alice")
    token = login_user("alice")
    integration = create_integration(token)

    db = database.SessionLocal()
    try:
        user_id = db.query(models.User).filter(models.User.username == "alice").first().id
        context = trading_context_service.resolve(
            db,
            user_id=user_id,
            trading_mode="paper",
            integration_id=integration["id"],
            account_id="paper-account-1",
            symbol="ES",
            required_capabilities={IntegrationCapability.BROKER_TRADING},
            require_integration=True,
            require_account=True,
            require_contract=True,
        )
        assert context.readiness()["ready"] is True

        with pytest.raises(TradingContextError) as exc_info:
            trading_context_service.resolve(
                db,
                user_id=user_id,
                trading_mode="paper",
                integration_id=integration["id"],
                required_capabilities={IntegrationCapability.BROKER_TRADING},
                require_integration=True,
                require_account=True,
            )
        assert exc_info.value.code == "missing_account"
        assert exc_info.value.blockers[0].code == "missing_account"
    finally:
        db.close()


def test_trading_sensitive_routes_use_trading_context_service(monkeypatch):
    calls: list[tuple[IntegrationCapability, ...]] = []
    original = trading_context_service.resolve

    def spy(*args, **kwargs):
        calls.append(tuple(kwargs.get("required_capabilities") or ()))
        return original(*args, **kwargs)

    monkeypatch.setattr(trading_context_service, "resolve", spy)

    register_user("alice")
    token = login_user("alice")
    topstepx = create_integration(token)
    tradovate = create_integration(token, "TRADOVATE")
    tradingview = create_integration(
        token,
        "TRADINGVIEW",
        credentials={"webhookSecret": "expected"},
        metadata={"environment": "test", "contracts": ["ES"]},
    )
    client.put(f"/integrations/{topstepx['id']}/activate", headers=auth_headers(token))

    assert client.get("/contracts", params={"integration_id": tradovate["id"]}, headers=auth_headers(token)).status_code == 400
    assert client.get(f"/integrations/{tradovate['id']}/accounts", headers=auth_headers(token)).status_code == 400
    session_response = client.post(
        "/scheduler/bot-sessions",
        json={
            "symbol": "ES",
            "integration_id": topstepx["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
        },
        headers=auth_headers(token),
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["session_id"]
    assert client.post(
        "/scheduler/strategy-configs",
        json={
            "symbol": "ES",
            "integration_id": topstepx["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
        },
        headers=auth_headers(token),
    ).status_code == 200
    assert client.post(
        "/scheduler/execute-trade",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "integration_id": topstepx["id"],
            "account_id": "paper-account-1",
            "trading_mode": "paper",
            "idempotency_key": "manual-context-route",
        },
        headers=auth_headers(token),
    ).status_code == 200
    assert client.get("/trading/test-trade", headers=auth_headers(token)).status_code == 200
    assert client.post(
        "/trading/webhook",
        json={
            "symbol": "ES",
            "side": "BUY",
            "quantity": 1,
            "signal_integration_id": tradingview["id"],
            "broker_integration_id": topstepx["id"],
            "secret": "expected",
            "trading_mode": "paper",
            "idempotency_key": "webhook-context-route",
        },
    ).status_code == 200

    class DummyAdapter:
        pass

    monkeypatch.setattr(scheduler_module, "get_adapter", lambda integration: DummyAdapter())
    with client.stream(
        "GET",
        f"/scheduler/run-bot?session_id={session_id}&symbol=ES&integration_id={topstepx['id']}",
        headers=auth_headers(token),
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert '"type": "run_status"' in body
    assert '"simulation": true' in body

    assert len(calls) >= 7
    flattened = {capability for call in calls for capability in call}
    assert IntegrationCapability.MARKET_DATA in flattened
    assert IntegrationCapability.ACCOUNT_INFO in flattened
    assert IntegrationCapability.BROKER_TRADING in flattened
    assert IntegrationCapability.SIGNALS in flattened
