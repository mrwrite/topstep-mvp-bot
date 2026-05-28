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
from app.providers.topstepx import TopStepXAdapter  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
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


def create_integration(
    token: str,
    provider: str,
    credentials: dict | None = None,
    status: str = "active",
):
    response = client.post(
        "/integrations",
        json={
            "display_name": f"{provider} Main",
            "provider": provider,
            "status": status,
            "metadata": {"environment": "test"},
            "credentials": credentials if credentials is not None else {"apiKey": "key", "apiSecret": "secret"},
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def test_provider_metadata_splits_implemented_and_roadmap_capabilities():
    response = client.get("/integrations/providers")
    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()["providers"]}

    assert "MARKET_DATA" in providers["TOPSTEPX"]["implemented_capabilities"]
    assert "ACCOUNT_INFO" in providers["TOPSTEPX"]["implemented_capabilities"]
    assert providers["TRADOVATE"]["implemented_capabilities"] == []
    assert "BROKER_TRADING" in providers["TRADOVATE"]["roadmap_capabilities"]
    assert providers["IBKR"]["implemented_capabilities"] == []
    assert "SIGNALS" in providers["TRADINGVIEW"]["implemented_capabilities"]


def test_contract_fetch_requires_selected_user_owned_implemented_market_data():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    tradovate = create_integration(alice_token, "TRADOVATE")

    unsupported = client.get(
        "/contracts",
        params={"integration_id": tradovate["id"]},
        headers=auth_headers(alice_token),
    )
    assert unsupported.status_code == 400
    assert "market data" in unsupported.json()["detail"].lower()

    foreign = client.get(
        "/contracts",
        params={"integration_id": tradovate["id"]},
        headers=auth_headers(bob_token),
    )
    assert foreign.status_code == 404


def test_account_fetch_is_user_scoped_and_fails_closed_for_roadmap_provider():
    register_user("alice")
    register_user("bob")
    alice_token = login_user("alice")
    bob_token = login_user("bob")
    tradovate = create_integration(alice_token, "TRADOVATE")

    unsupported = client.get(
        f"/integrations/{tradovate['id']}/accounts",
        headers=auth_headers(alice_token),
    )
    assert unsupported.status_code == 400
    assert "account" in unsupported.json()["detail"].lower()

    foreign = client.get(
        f"/integrations/{tradovate['id']}/accounts",
        headers=auth_headers(bob_token),
    )
    assert foreign.status_code == 404


def test_topstepx_session_token_is_cached(monkeypatch):
    calls = {"count": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "token": "cached-token"}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr("app.providers.topstepx.requests.post", fake_post)
    adapter = TopStepXAdapter({"userName": "user", "apiKey": "key"}, {})

    assert adapter._get_session_token() == "cached-token"
    assert adapter._get_session_token() == "cached-token"
    assert calls["count"] == 1
