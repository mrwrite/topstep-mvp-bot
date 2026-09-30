import io
import json
import logging
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["SECRET_KEY"] = "p0-test-secret"

from app import database, models
from app.main import _rate_limit_window, app
from app.observability import JsonFormatter, redact, safe_exception

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    client.cookies.clear()
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    _rate_limit_window.clear()
    yield


def register_and_login(name: str, *, client_instance=client):
    password = "StrongPass1"
    response = client_instance.post(
        "/auth/register",
        json={"username": name, "email": f"{name}@example.com", "password": password},
    )
    assert response.status_code == 201
    login = client_instance.post(
        "/auth/token",
        data={"username": name, "password": password, "grant_type": "password"},
    )
    assert login.status_code == 200
    return password, login.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_structured_redaction_covers_nested_headers_urls_and_exceptions():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1In0.signature"
    value = {
        "nested": [{"Authorization": f"Bearer {jwt}", "safe": "visible"}],
        "url": "https://example.test/auth?token=abc&view=summary",
        "message": "api_key=super-secret password=hunter2",
    }
    cleaned = redact(value)
    rendered = json.dumps(cleaned)
    assert "super-secret" not in rendered
    assert "hunter2" not in rendered
    assert jwt not in rendered
    assert "visible" in rendered
    assert "view=summary" in rendered

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("redaction-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.error("request failed token=abc", exc_info=(RuntimeError, RuntimeError("Bearer secret"), None))
    output = stream.getvalue()
    assert "secret" not in output
    assert "abc" not in output
    assert safe_exception(RuntimeError("password=hunter2"))["message"].endswith("[REDACTED]")


def test_cookie_session_csrf_rotation_logout_expiry_and_revocation():
    password, bearer_token = register_and_login("cookie-user")
    csrf = client.cookies.get("tradebot_csrf")
    assert csrf
    assert client.cookies.get("tradebot_session")
    assert client.put("/auth/profile", json={"display_name": "blocked"}).status_code == 403
    assert client.put(
        "/auth/profile",
        json={"display_name": "allowed"},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200

    old_token = client.cookies.get("tradebot_session")
    rotated = client.post("/auth/sessions/rotate", headers={"X-CSRF-Token": csrf})
    assert rotated.status_code == 200
    assert client.cookies.get("tradebot_session") != old_token
    assert client.get("/auth/me", headers=bearer(old_token)).status_code == 401

    csrf = client.cookies.get("tradebot_csrf")
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/auth/me").status_code == 401

    _, token = register_and_login("expired-user")
    with database.SessionLocal() as db:
        session = db.query(models.UserSession).filter(models.UserSession.user_id == 2).first()
        session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_unavailable_provider_rejected_and_metadata_is_truthful():
    _, token = register_and_login("provider-user")
    providers = {item["provider"]: item for item in client.get("/integrations/providers").json()["providers"]}
    assert providers["TOPSTEPX"]["enabled"] is False
    assert providers["TOPSTEPX"]["accepts_credentials"] is False
    assert providers["TOPSTEPX"]["live_trading_enabled"] is False
    assert providers["TOPSTEPX"]["evidence_reviewed_at"] == "2026-07-26"
    assert providers["TRADINGVIEW"]["availability"] == "SIGNAL_ONLY"
    assert providers["TRADINGVIEW"]["capabilities"] == ["SIGNALS"]
    rejected = client.post(
        "/integrations",
        json={
            "display_name": "Not allowed",
            "provider": "TOPSTEPX",
            "credentials": {"apiKey": "must-not-save"},
        },
        headers=bearer(token),
    )
    assert rejected.status_code == 422
    with database.SessionLocal() as db:
        assert db.query(models.PlatformIntegration).count() == 0


def test_export_excludes_secrets_and_cross_tenant_resources():
    _, alice_token = register_and_login("export-alice")
    _, bob_token = register_and_login("export-bob")
    with database.SessionLocal() as db:
        alice = db.query(models.User).filter_by(username="export-alice").one()
        bob = db.query(models.User).filter_by(username="export-bob").one()
        db.add_all(
            [
                models.PlatformIntegration(
                    user_id=alice.id,
                    display_name="Alice signal",
                    provider="TRADINGVIEW",
                    status="active",
                    credentials_encrypted="encrypted-alice-secret",
                    integration_metadata={"token": "nested-secret"},
                ),
                models.PlatformIntegration(
                    user_id=bob.id,
                    display_name="Bob signal",
                    provider="TRADINGVIEW",
                    status="active",
                    credentials_encrypted="encrypted-bob-secret",
                ),
            ]
        )
        db.commit()
    exported = client.get("/auth/account/export", headers=bearer(alice_token))
    assert exported.status_code == 200
    body = exported.text
    assert "Alice signal" in body
    assert "Bob signal" not in body
    assert "encrypted-alice-secret" not in body
    assert "nested-secret" not in body
    assert "hashed_password" not in body


def test_account_deletion_revokes_sessions_and_reports_provider_gap():
    password, token = register_and_login("delete-user")
    original_grace = database.APP_CONFIG.account_deletion_grace_days
    object.__setattr__(database.APP_CONFIG, "account_deletion_grace_days", 0)
    try:
        payload = {"password": password, "confirmation": "DELETE MY ACCOUNT"}
        requested = client.post("/auth/account/deletion-requests", json=payload, headers=bearer(token))
        assert requested.status_code == 201
        executed = client.post(
            f"/auth/account/deletion-requests/{requested.json()['id']}/execute",
            json=payload,
            headers=bearer(token),
        )
        assert executed.status_code == 200
        assert executed.json()["status"] in {"completed", "completed_with_revocation_gaps"}
        assert client.get("/auth/me", headers=bearer(token)).status_code == 401
        with database.SessionLocal() as db:
            user = db.query(models.User).filter(models.User.id == 1).one()
            assert user.account_status == "deleted"
            assert db.query(models.UserSession).filter_by(user_id=1, revoked_at=None).count() == 0
    finally:
        object.__setattr__(database.APP_CONFIG, "account_deletion_grace_days", original_grace)


def test_cross_tenant_deletion_request_is_not_disclosed_or_mutated():
    alice_password, alice_token = register_and_login("delete-alice")
    bob_password, bob_token = register_and_login("delete-bob")
    payload = {"password": alice_password, "confirmation": "DELETE MY ACCOUNT"}
    requested = client.post("/auth/account/deletion-requests", json=payload, headers=bearer(alice_token))
    assert requested.status_code == 201
    request_id = requested.json()["id"]
    bob_execute = client.post(
        f"/auth/account/deletion-requests/{request_id}/execute",
        json={"password": bob_password, "confirmation": "DELETE MY ACCOUNT"},
        headers=bearer(bob_token),
    )
    bob_cancel = client.post(
        f"/auth/account/deletion-requests/{request_id}/cancel",
        json={"password": bob_password, "confirmation": "KEEP MY ACCOUNT"},
        headers=bearer(bob_token),
    )
    assert bob_execute.status_code == bob_cancel.status_code == 404
    assert bob_execute.json() == {"detail": "Deletion request not found."}
    assert bob_cancel.json() == {"detail": "Deletion request not found."}
    with database.SessionLocal() as db:
        record = db.query(models.AccountDeletionRequest).filter_by(id=request_id).one()
        assert record.status == "pending"
        assert db.query(models.DeletionTombstone).filter_by(deletion_request_id=request_id).count() == 0


def test_operator_access_is_purpose_bound_and_append_only_audited():
    _, token = register_and_login("operator")
    with database.SessionLocal() as db:
        user = db.query(models.User).filter_by(username="operator").one()
        user.is_admin = 1
        target = models.User(
            username="target",
            email="target@example.com",
            hashed_password="not-used",
        )
        db.add(target)
        db.commit()
        target_id = target.id
    assert client.get("/analytics/admin/events", headers=bearer(token)).status_code == 403
    headers = {
        **bearer(token),
        "X-Operator-Reason": "Investigate beta incident",
        "X-Operator-Case-ID": "INC-1001",
        "X-Operator-Target-User": str(target_id),
    }
    assert client.get("/analytics/admin/events", headers=headers).status_code == 200
    with database.SessionLocal() as db:
        events = db.query(models.SecurityAuditEvent).filter_by(actor_user_id=1).all()
        assert {event.outcome for event in events} >= {"denied_missing_purpose", "authorized"}
        authorized = next(event for event in events if event.outcome == "authorized")
        assert authorized.target_user_id == target_id
        assert authorized.reason == "Investigate beta incident"
        assert authorized.case_id == "INC-1001"


def test_shared_rate_limit_persists_outside_process_memory():
    original = database.APP_CONFIG.rate_limit_requests_per_minute
    object.__setattr__(database.APP_CONFIG, "rate_limit_requests_per_minute", 1)
    try:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/live").status_code == 429
        with database.SessionLocal() as db:
            assert db.query(models.RateLimitBucket).count() == 1
    finally:
        object.__setattr__(database.APP_CONFIG, "rate_limit_requests_per_minute", original)
