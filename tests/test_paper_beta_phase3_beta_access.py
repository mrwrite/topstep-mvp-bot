import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    yield


def register_user(username: str, email: str, password: str = "StrongPass1"):
    response = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201
    return response


def login_user(username: str, password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser beta-suite"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str, target_user_id: int = 1) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "user-agent": "pytest-browser beta-suite",
            "X-Operator-Reason": "Automated authorization verification",
            "X-Operator-Case-ID": "TEST-BETA", "X-Operator-Target-User": str(target_user_id)}


def mark_verified_and_admin(username: str, *, is_admin: bool = False):
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == username).one()
        user.email_verified_at = datetime.utcnow()
        user.is_admin = 1 if is_admin else 0
        db.commit()


def accept_legal(token: str):
    response = client.post(
        "/legal/acceptances",
        headers=auth_headers(token),
        json={
            "accept_terms_of_service": True,
            "accept_privacy_policy": True,
            "accept_paper_trading_disclosure": True,
            "metadata": {"source": "phase3-test"},
        },
    )
    assert response.status_code == 200


def create_admin_and_invite(code: str = "BETA-CODE-123", **payload):
    register_user("admin", "admin@example.com")
    mark_verified_and_admin("admin", is_admin=True)
    admin_token = login_user("admin")
    return admin_token, create_invite(admin_token, code, **payload)


def create_invite(admin_token: str, code: str = "BETA-CODE-123", **payload):
    request = {
        "code": code,
        "max_uses": payload.pop("max_uses", 1),
        "expires_in_days": payload.pop("expires_in_days", 30),
        "campaign": "pytest",
        **payload,
    }
    response = client.post("/beta/admin/invites", headers=auth_headers(admin_token), json=request)
    assert response.status_code == 200
    return response.json()


def test_invite_redemption_grants_user_scoped_active_beta_status_and_live_stays_blocked():
    _, invite = create_admin_and_invite("BETA-VALID-123")
    register_user("alice", "alice@example.com")
    token = login_user("alice")

    before = client.get("/beta/access-check", headers=auth_headers(token))
    assert before.status_code == 403
    assert before.headers["x-readiness-blocker"] == "email_verification_required"

    mark_verified_and_admin("alice")
    accept_legal(token)
    redeemed = client.post("/beta/invites/redeem", headers=auth_headers(token), json={"code": invite["code"]})

    assert redeemed.status_code == 200
    assert redeemed.json()["status"] == "redeemed"
    status_response = client.get("/beta/status", headers=auth_headers(token))
    assert status_response.status_code == 200
    assert status_response.json()["beta_access_active"] is True

    access = client.get("/beta/access-check", headers=auth_headers(token))
    assert access.status_code == 200
    assert access.json()["ready"] is True
    assert access.json()["live_trading_enabled"] is False

    live = client.get("/health/live")
    assert live.json()["live_trading_enabled"] is False


def test_invite_redemption_rejects_expired_disabled_exhausted_and_email_mismatch():
    admin_token, expired = create_admin_and_invite("BETA-EXPIRED", expires_in_days=1)
    disabled = create_invite(admin_token, "BETA-DISABLED")
    exhausted = create_invite(admin_token, "BETA-EXHAUST", max_uses=1)
    restricted = create_invite(admin_token, "BETA-EMAILONLY", email_restriction="allowed@example.com")

    with database.SessionLocal() as db:
        expired_record = db.query(models.BetaInviteCode).filter(models.BetaInviteCode.id == expired["id"]).one()
        expired_record.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

    disable_response = client.post(f"/beta/admin/invites/{disabled['id']}/disable", headers=auth_headers(admin_token))
    assert disable_response.status_code == 200

    register_user("alice", "alice@example.com")
    alice = login_user("alice")
    register_user("bob", "bob@example.com")
    bob = login_user("bob")

    assert client.post("/beta/invites/redeem", headers=auth_headers(alice), json={"code": expired["code"]}).status_code == 400
    assert client.post("/beta/invites/redeem", headers=auth_headers(alice), json={"code": disabled["code"]}).status_code == 400
    assert client.post("/beta/invites/redeem", headers=auth_headers(alice), json={"code": restricted["code"]}).status_code == 400

    first = client.post("/beta/invites/redeem", headers=auth_headers(alice), json={"code": exhausted["code"]})
    second = client.post("/beta/invites/redeem", headers=auth_headers(bob), json={"code": exhausted["code"]})
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "Invite code is exhausted."


def test_duplicate_redemption_is_idempotent_for_same_user():
    _, invite = create_admin_and_invite("BETA-IDEMPOTENT")
    register_user("alice", "alice@example.com")
    token = login_user("alice")

    first = client.post("/beta/invites/redeem", headers=auth_headers(token), json={"code": invite["code"]})
    second = client.post("/beta/invites/redeem", headers=auth_headers(token), json={"code": invite["code"]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "already_redeemed"
    with database.SessionLocal() as db:
        invite_record = db.query(models.BetaInviteCode).filter(models.BetaInviteCode.id == invite["id"]).one()
        assert invite_record.use_count == 1
        assert db.query(models.BetaInviteRedemption).count() == 1


def test_admin_invite_management_is_admin_only_and_can_suspend_access():
    register_user("admin", "admin@example.com")
    mark_verified_and_admin("admin", is_admin=True)
    admin = login_user("admin")
    register_user("alice", "alice@example.com")
    alice = login_user("alice")

    non_admin_create = client.post("/beta/admin/invites", headers=auth_headers(alice), json={"code": "BETA-NOPE"})
    assert non_admin_create.status_code == 403

    invite = client.post("/beta/admin/invites", headers=auth_headers(admin), json={"code": "BETA-SUSPEND"}).json()
    assert client.post("/beta/invites/redeem", headers=auth_headers(alice), json={"code": invite["code"]}).status_code == 200
    mark_verified_and_admin("alice")
    accept_legal(alice)
    with database.SessionLocal() as db:
        alice_user = db.query(models.User).filter(models.User.username == "alice").one()
        alice_id = alice_user.id

    suspended = client.post(
        f"/beta/admin/users/{alice_id}/suspend",
        headers=auth_headers(admin, alice_id),
        json={"reason": "policy review"},
    )
    assert suspended.status_code == 200

    status_response = client.get("/beta/status", headers=auth_headers(alice))
    assert status_response.json()["beta_access"]["status"] == "suspended"
    assert status_response.json()["beta_access_active"] is False
    blocked = client.get("/beta/access-check", headers=auth_headers(alice))
    assert blocked.status_code == 403
    assert blocked.headers["x-readiness-blocker"] == "beta_access_required"


def test_waitlist_flow_deduplicates_and_admin_can_approve_authenticated_entry():
    first = client.post(
        "/beta/waitlist",
        json={"email": "Wait@Example.com", "name": "Wait User", "use_case": "paper trading", "source": "landing"},
    )
    duplicate = client.post(
        "/beta/waitlist",
        json={"email": "wait@example.com", "name": "Updated", "use_case": "updated", "source": "landing"},
    )
    assert first.status_code == 200
    assert duplicate.status_code == 200

    register_user("admin", "admin@example.com")
    mark_verified_and_admin("admin", is_admin=True)
    admin = login_user("admin")
    register_user("alice", "wait@example.com")
    alice = login_user("alice")

    authenticated = client.post(
        "/beta/waitlist/me",
        headers=auth_headers(alice),
        json={"email": "wait@example.com", "name": "Alice", "use_case": "beta paper", "source": "app"},
    )
    assert authenticated.status_code == 200

    waitlist = client.get("/beta/admin/waitlist", headers=auth_headers(admin))
    assert waitlist.status_code == 200
    assert len(waitlist.json()["waitlist"]) == 1
    entry_id = waitlist.json()["waitlist"][0]["id"]

    approved = client.post(f"/beta/admin/waitlist/{entry_id}/approve", headers=auth_headers(admin))
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    status_response = client.get("/beta/status", headers=auth_headers(alice))
    assert status_response.json()["beta_access"]["status"] == "active"
    assert status_response.json()["beta_access"]["source"] == "waitlist"
