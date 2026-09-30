import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import auth_routes, database, models  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    yield


def register_user(username: str = "alice", email: str = "alice@example.com", password: str = "StrongPass1"):
    return client.post("/auth/register", json={"username": username, "email": email, "password": password})


def login_user(username: str = "alice", password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_creates_unverified_user_and_verification_token(monkeypatch):
    monkeypatch.setattr(auth_routes, "_new_token", lambda: ("verify-token-1234567890", auth_routes._hash_value("verify-token-1234567890")))

    response = register_user()

    assert response.status_code == 201
    assert response.json()["email_verified_at"] is None
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == "alice").one()
        token = db.query(models.EmailVerificationToken).filter(models.EmailVerificationToken.user_id == user.id).one()
        assert user.email_verified_at is None
        assert token.email == "alice@example.com"
        assert token.consumed_at is None
        assert token.token_hash != "verify-token-1234567890"


def test_verify_email_consumes_token_and_beta_readiness_clears_blocker(monkeypatch):
    raw_token = "verify-token-abcdef1234567890"
    monkeypatch.setattr(auth_routes, "_new_token", lambda: (raw_token, auth_routes._hash_value(raw_token)))
    register_user()
    token = login_user()

    blocked = client.get("/auth/beta-readiness", headers=auth_headers(token))
    assert blocked.status_code == 200
    assert blocked.json()["email_verified"] is False
    assert blocked.json()["blockers"][0]["code"] == "email_verification_required"

    verified = client.post("/auth/verify-email", json={"token": raw_token})
    assert verified.status_code == 200

    ready = client.get("/auth/beta-readiness", headers=auth_headers(token))
    assert ready.json()["email_verified"] is True
    assert ready.json()["legal_acceptance_complete"] is False
    assert {blocker["code"] for blocker in ready.json()["blockers"]} == {
        "terms_acceptance_required",
        "privacy_acceptance_required",
        "paper_disclosure_required",
        "beta_access_required",
    }

    reused = client.post("/auth/verify-email", json={"token": raw_token})
    assert reused.status_code == 400


def test_expired_verification_token_fails_and_resend_is_rate_limited(monkeypatch):
    raw_token = "verify-token-expired1234567890"
    monkeypatch.setattr(auth_routes, "_new_token", lambda: (raw_token, auth_routes._hash_value(raw_token)))
    register_user()
    token = login_user()

    with database.SessionLocal() as db:
        record = db.query(models.EmailVerificationToken).one()
        record.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

    expired = client.post("/auth/verify-email", json={"token": raw_token})
    assert expired.status_code == 400

    limited = client.post("/auth/resend-verification", headers=auth_headers(token))
    assert limited.status_code == 429


def test_password_reset_does_not_enumerate_and_revokes_existing_sessions(monkeypatch):
    reset_token = "reset-token-abcdef1234567890"
    register_user()
    old_token = login_user()
    monkeypatch.setattr(auth_routes, "_new_token", lambda: (reset_token, auth_routes._hash_value(reset_token)))

    unknown = client.post("/auth/password-reset/request", json={"email": "missing@example.com"})
    known = client.post("/auth/password-reset/request", json={"email": "alice@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json() == {"status": "accepted"}

    confirmed = client.post("/auth/password-reset/confirm", json={"token": reset_token, "password": "NewStrongPass1"})
    assert confirmed.status_code == 200

    old_session = client.get("/auth/me", headers=auth_headers(old_token))
    assert old_session.status_code == 401

    new_token = login_user(password="NewStrongPass1")
    assert client.get("/auth/me", headers=auth_headers(new_token)).status_code == 200

    reused = client.post("/auth/password-reset/confirm", json={"token": reset_token, "password": "AnotherStrong1"})
    assert reused.status_code == 400


def test_profile_management_is_user_scoped_and_validated():
    register_user("alice", "alice@example.com", "StrongPass1")
    register_user("bob", "bob@example.com", "StrongPass1")
    alice = login_user("alice", "StrongPass1")
    bob = login_user("bob", "StrongPass1")

    updated = client.put(
        "/auth/profile",
        headers=auth_headers(alice),
        json={
            "display_name": "Alice Beta",
            "timezone": "America/Chicago",
            "preferred_contact_email": "alice-support@example.com",
            "trading_experience_level": "intermediate",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Alice Beta"

    bob_profile = client.get("/auth/profile", headers=auth_headers(bob))
    assert bob_profile.status_code == 200
    assert bob_profile.json()["display_name"] is None

    invalid = client.put("/auth/profile", headers=auth_headers(alice), json={"preferred_contact_email": "not-email"})
    assert invalid.status_code == 400


def test_sessions_can_be_listed_and_revoked_by_owner_only():
    register_user("alice", "alice@example.com", "StrongPass1")
    register_user("bob", "bob@example.com", "StrongPass1")
    alice_token = login_user("alice", "StrongPass1")
    bob_token = login_user("bob", "StrongPass1")

    sessions = client.get("/auth/sessions", headers=auth_headers(alice_token))
    assert sessions.status_code == 200
    session_id = sessions.json()[0]["session_id"]

    bob_revoke = client.post(f"/auth/sessions/{session_id}/revoke", headers=auth_headers(bob_token))
    assert bob_revoke.status_code == 404

    revoked = client.post(f"/auth/sessions/{session_id}/revoke", headers=auth_headers(alice_token))
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    after = client.get("/auth/me", headers=auth_headers(alice_token))
    assert after.status_code == 401


def test_account_recovery_records_sanitized_support_reference():
    register_user()
    token = login_user()
    response = client.post(
        "/auth/account-recovery",
        json={
            "contact_email": "alice@example.com",
            "category": "lost_access",
            "message": "I lost access. apiKey=secret-value",
        },
    )
    assert response.status_code == 200
    assert response.json()["reference_id"].startswith("rec_")

    with database.SessionLocal() as db:
        record = db.query(models.AccountRecoveryRequest).one()
        assert record.user_id is not None
        assert "secret-value" not in record.sanitized_message
        assert "[REDACTED]" in record.sanitized_message

    listing = client.get("/auth/account-recovery", headers=auth_headers(token))
    assert listing.status_code == 200
    assert listing.json()[0]["reference_id"] == response.json()["reference_id"]

    register_user("bob", "bob@example.com", "StrongPass1")
    bob = login_user("bob", "StrongPass1")
    assert client.get("/auth/account-recovery", headers=auth_headers(bob)).json() == []
