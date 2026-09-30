import os
from datetime import datetime

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import beta_access_service, database, models  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    object.__setattr__(database.APP_CONFIG, "billing_enabled", False)
    object.__setattr__(database.APP_CONFIG, "stripe_publishable_key", None)
    object.__setattr__(database.APP_CONFIG, "stripe_secret_key", None)
    object.__setattr__(database.APP_CONFIG, "stripe_webhook_secret", None)
    yield


def register_user(username: str, email: str, password: str = "StrongPass1") -> None:
    response = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201


def login_user(username: str, password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser subscription-suite"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str, target_user_id: int = 1) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "user-agent": "pytest-browser subscription-suite",
            "X-Operator-Reason": "Automated authorization verification",
            "X-Operator-Case-ID": "TEST-SUBSCRIPTION", "X-Operator-Target-User": str(target_user_id)}


def create_user(username: str, *, admin: bool = False, beta: bool = False) -> tuple[str, int]:
    register_user(username, f"{username}@example.com")
    token = login_user(username)
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == username).one()
        user.email_verified_at = datetime.utcnow()
        user.is_admin = 1 if admin else 0
        if beta:
            beta_access_service.ensure_active_beta_status(db, user_id=user.id, source="test")
        db.commit()
        return token, user.id


def test_plan_catalog_and_billing_are_available_without_checkout_or_payment():
    response = client.get("/subscription/plans")
    assert response.status_code == 200
    payload = response.json()
    codes = {plan["code"] for plan in payload["plans"]}
    assert {"beta", "free", "pro", "live_ready_future"}.issubset(codes)
    assert payload["billing"]["billing_enabled"] is False
    assert payload["billing"]["checkout_enabled"] is False
    assert payload["billing"]["payment_collection_enabled"] is False
    assert payload["live_trading_enabled"] is False
    assert all(plan["checkout_enabled"] is False for plan in payload["plans"])


def test_beta_user_gets_beta_entitlement_without_stripe_customer():
    token, _ = create_user("alice", beta=True)

    response = client.get("/subscription/status", headers=auth_headers(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["subscription"]["plan_code"] == "beta"
    assert payload["subscription"]["billing_status"] == "not_required"
    assert payload["subscription"]["stripe_customer_configured"] is False
    assert "paper_beta_access" in payload["entitlements"]
    assert payload["billing"]["checkout_enabled"] is False
    assert payload["live_trading_enabled"] is False

    gate = client.post(
        "/subscription/entitlements/check",
        headers=auth_headers(token),
        json={"feature_code": "paper_beta_access"},
    )
    assert gate.status_code == 200
    assert gate.json()["allowed"] is True


def test_non_beta_user_is_not_granted_beta_entitlement_and_users_are_isolated():
    alice, _ = create_user("alice", beta=True)
    bob, _ = create_user("bob", beta=False)

    alice_status = client.get("/subscription/status", headers=auth_headers(alice)).json()
    bob_status = client.get("/subscription/status", headers=auth_headers(bob)).json()

    assert alice_status["subscription"]["plan_code"] == "beta"
    assert "paper_beta_access" in alice_status["entitlements"]
    assert bob_status["subscription"]["plan_code"] == "free"
    assert "paper_beta_access" not in bob_status["entitlements"]

    denied = client.post(
        "/subscription/entitlements/check",
        headers=auth_headers(bob),
        json={"feature_code": "paper_beta_access"},
    )
    assert denied.status_code == 200
    assert denied.json()["allowed"] is False
    assert denied.json()["reason_code"] == "beta_access_required"


def test_admin_can_assign_status_and_grant_non_live_entitlement_only():
    admin, _ = create_user("admin", admin=True, beta=True)
    alice, alice_id = create_user("alice", beta=False)

    non_admin = client.put(
        f"/subscription/admin/users/{alice_id}/status",
        headers=auth_headers(alice, alice_id),
        json={"plan_code": "pro", "status": "pro", "reason": "test"},
    )
    assert non_admin.status_code == 403

    assigned = client.put(
        f"/subscription/admin/users/{alice_id}/status",
        headers=auth_headers(admin, alice_id),
        json={"plan_code": "pro", "status": "pro", "reason": "paper beta support test"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["subscription"]["plan_code"] == "pro"
    assert "advanced_paper_trading" in assigned.json()["entitlements"]
    assert assigned.json()["billing"]["checkout_enabled"] is False

    grant = client.post(
        f"/subscription/admin/users/{alice_id}/entitlements",
        headers=auth_headers(admin, alice_id),
        json={"feature_code": "beta_analytics", "reason": "test grant"},
    )
    assert grant.status_code == 200
    assert "beta_analytics" in grant.json()["entitlements"]

    live_grant = client.post(
        f"/subscription/admin/users/{alice_id}/entitlements",
        headers=auth_headers(admin, alice_id),
        json={"feature_code": "live_trading", "reason": "should fail"},
    )
    assert live_grant.status_code == 403


def test_checkout_disabled_and_live_trading_blocked_for_entitled_user():
    token, _ = create_user("alice", beta=True)

    checkout = client.post("/subscription/billing/checkout", headers=auth_headers(token))
    assert checkout.status_code == 403
    assert checkout.json()["detail"]["reason_code"] == "billing_disabled_for_invite_only_beta"
    assert checkout.json()["detail"]["live_trading_enabled"] is False

    live_gate = client.post(
        "/subscription/entitlements/check",
        headers=auth_headers(token),
        json={"feature_code": "live_trading"},
    )
    assert live_gate.status_code == 200
    assert live_gate.json()["allowed"] is False
    assert live_gate.json()["reason_code"] == "live_trading_disabled"
    assert live_gate.json()["live_trading_enabled"] is False

    live_config = client.post(
        "/scheduler/update-config",
        headers=auth_headers(token),
        json={"trading_mode": "live"},
    )
    assert live_config.status_code == 403
    assert client.get("/health/live").json()["live_trading_enabled"] is False
