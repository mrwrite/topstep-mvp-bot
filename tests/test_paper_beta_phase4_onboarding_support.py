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
    yield


def register_user(username: str, email: str, password: str = "StrongPass1"):
    response = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201
    return response


def login_user(username: str, password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser onboarding-suite"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "user-agent": "pytest-browser onboarding-suite",
            "X-Operator-Reason": "Automated authorization verification",
            "X-Operator-Case-ID": "TEST-SUPPORT", "X-Operator-Target-User": "1"}


def make_beta_ready_user(username: str = "alice", email: str = "alice@example.com") -> str:
    register_user(username, email)
    token = login_user(username)
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == username).one()
        user.email_verified_at = datetime.utcnow()
        beta_access_service.ensure_active_beta_status(db, user_id=user.id, source="test")
        db.commit()
    legal = client.post(
        "/legal/acceptances",
        headers=auth_headers(token),
        json={
            "accept_terms_of_service": True,
            "accept_privacy_policy": True,
            "accept_paper_trading_disclosure": True,
            "metadata": {"source": "phase4-test"},
        },
    )
    assert legal.status_code == 200
    return token


def test_onboarding_status_orders_prerequisites_and_gate_blocks_until_beta_ready():
    register_user("alice", "alice@example.com")
    token = login_user("alice")

    status_response = client.get("/onboarding/status", headers=auth_headers(token))
    assert status_response.status_code == 200
    checklist = {item["code"]: item for item in status_response.json()["checklist"]}
    assert list(checklist)[:4] == [
        "email_verified",
        "legal_acceptance",
        "beta_access",
        "paper_only_reviewed",
    ]
    assert checklist["email_verified"]["complete"] is False
    assert status_response.json()["live_trading_enabled"] is False

    blocked = client.get("/onboarding/gate", headers=auth_headers(token))
    assert blocked.status_code == 403
    assert blocked.headers["x-readiness-blocker"] == "email_verification_required"

    beta_token = make_beta_ready_user("bob", "bob@example.com")
    allowed = client.get("/onboarding/gate", headers=auth_headers(beta_token))
    assert allowed.status_code == 200
    assert allowed.json()["live_trading_enabled"] is False


def test_onboarding_milestones_are_persisted_and_user_scoped():
    alice = make_beta_ready_user("alice", "alice@example.com")
    bob = make_beta_ready_user("bob", "bob@example.com")

    marked = client.post("/onboarding/milestones", headers=auth_headers(alice), json={"code": "paper_only_reviewed"})
    assert marked.status_code == 200
    assert next(item for item in marked.json()["checklist"] if item["code"] == "paper_only_reviewed")["complete"] is True

    alice_status = client.get("/onboarding/status", headers=auth_headers(alice)).json()
    bob_status = client.get("/onboarding/status", headers=auth_headers(bob)).json()
    assert next(item for item in alice_status["checklist"] if item["code"] == "paper_only_reviewed")["complete"] is True
    assert next(item for item in bob_status["checklist"] if item["code"] == "paper_only_reviewed")["complete"] is False

    invalid = client.post("/onboarding/milestones", headers=auth_headers(alice), json={"code": "unknown"})
    assert invalid.status_code == 400


def test_onboarding_derives_integration_risk_strategy_and_order_progress():
    token = make_beta_ready_user()
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == "alice").one()
        integration = models.PlatformIntegration(
            user_id=user.id,
            display_name="Paper Broker",
            provider="TOPSTEPX",
            status="active",
            integration_metadata={"environment": "paper", "account_id": "SIM-1"},
        )
        db.add(integration)
        db.flush()
        db.add(models.RiskSettings(user_id=user.id, integration_id=integration.id, account_id="SIM-1"))
        db.add(
            models.StrategyConfig(
                user_id=user.id,
                integration_id=integration.id,
                account_id="SIM-1",
                symbol="ES",
                trading_mode="paper",
                parameters={"buy_threshold": 30, "sell_threshold": 70},
            )
        )
        db.add(
            models.PaperOrder(
                user_id=user.id,
                integration_id=integration.id,
                account_id="SIM-1",
                symbol="ES",
                side="BUY",
                quantity=1,
                trading_mode="paper",
                source="manual",
                idempotency_key="onboarding-order",
                status="filled",
            )
        )
        db.commit()

    payload = client.get("/onboarding/status", headers=auth_headers(token)).json()
    checklist = {item["code"]: item for item in payload["checklist"]}
    assert checklist["integration_created"]["complete"] is True
    assert checklist["account_contract_selected"]["complete"] is True
    assert checklist["risk_controls_reviewed"]["complete"] is True
    assert checklist["strategy_setup_reviewed"]["complete"] is True
    assert checklist["first_paper_session"]["complete"] is True


def test_support_request_creation_redacts_secrets_and_history_is_user_scoped():
    alice = make_beta_ready_user("alice", "alice@example.com")
    bob = make_beta_ready_user("bob", "bob@example.com")

    response = client.post(
        "/onboarding/support",
        headers=auth_headers(alice),
        json={
            "category": "paper_order",
            "severity": "high",
            "subject": "Need help with a paper order",
            "message": "Order issue. apiKey=secret-value password=hunter2",
            "bot_session_id": "bot-123",
            "diagnostics": {"api_token": "secret", "screen": "dashboard"},
        },
    )
    assert response.status_code == 200
    assert response.json()["reference_id"].startswith("sup_")

    with database.SessionLocal() as db:
        record = db.query(models.SupportRequest).one()
        assert record.user_id is not None
        assert "secret-value" not in record.sanitized_message
        assert "hunter2" not in record.sanitized_message
        assert record.diagnostics["api_token"] == "[REDACTED]"

    alice_history = client.get("/onboarding/support", headers=auth_headers(alice)).json()["support_requests"]
    bob_history = client.get("/onboarding/support", headers=auth_headers(bob)).json()["support_requests"]
    assert len(alice_history) == 1
    assert bob_history == []


def test_admin_support_visibility_and_status_update_is_admin_only():
    alice = make_beta_ready_user("alice", "alice@example.com")
    admin = make_beta_ready_user("admin", "admin@example.com")

    created = client.post(
        "/onboarding/support",
        headers=auth_headers(alice),
        json={
            "category": "setup",
            "severity": "normal",
            "subject": "Need setup help",
            "message": "The paper account setup checklist is confusing.",
        },
    )
    assert created.status_code == 200
    support_id = created.json()["id"]

    denied = client.get("/onboarding/admin/support", headers=auth_headers(alice))
    assert denied.status_code == 403

    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == "admin").one()
        user.is_admin = True
        db.commit()

    listing = client.get("/onboarding/admin/support", headers=auth_headers(admin))
    assert listing.status_code == 200
    assert len(listing.json()["support_requests"]) == 1

    updated = client.patch(
        f"/onboarding/admin/support/{support_id}",
        headers=auth_headers(admin),
        json={"status": "resolved"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"

    invalid = client.patch(
        f"/onboarding/admin/support/{support_id}",
        headers=auth_headers(admin),
        json={"status": "live_trading_enabled"},
    )
    assert invalid.status_code == 400


def test_help_topics_cover_beta_basics_and_live_remains_blocked():
    response = client.get("/onboarding/help")
    assert response.status_code == 200
    slugs = {topic["slug"] for topic in response.json()["topics"]}
    assert {
        "paper-only-status",
        "account-setup",
        "integrations",
        "risk-controls",
        "order-states",
        "strategy-assumptions",
        "support-escalation",
    }.issubset(slugs)
    assert response.json()["live_trading_enabled"] is False
    assert client.get("/health/live").json()["live_trading_enabled"] is False
