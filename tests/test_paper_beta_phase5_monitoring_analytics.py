import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import analytics_service, database, models  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    object.__setattr__(database.APP_CONFIG, "analytics_enabled", True)
    object.__setattr__(database.APP_CONFIG, "sentry_enabled", False)
    object.__setattr__(database.APP_CONFIG, "sentry_dsn", None)
    yield


def register_user(username: str, email: str, password: str = "StrongPass1") -> None:
    response = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201


def login_user(username: str, password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser analytics-suite"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "user-agent": "pytest-browser analytics-suite",
            "X-Operator-Reason": "Automated authorization verification",
            "X-Operator-Case-ID": "TEST-ANALYTICS", "X-Operator-Target-User": "1"}


def create_user(username: str, *, admin: bool = False) -> str:
    register_user(username, f"{username}@example.com")
    token = login_user(username)
    with database.SessionLocal() as db:
        user = db.query(models.User).filter(models.User.username == username).one()
        user.email_verified_at = datetime.utcnow()
        user.is_admin = 1 if admin else 0
        db.commit()
    return token


def test_analytics_event_capture_redacts_secrets_and_quarantines_unknown_events():
    user = create_user("alice")
    admin = create_user("admin", admin=True)

    response = client.post(
        "/analytics/events",
        headers=auth_headers(user),
        json={
            "event_name": "paper-session-started",
            "metadata": {
                "apiKey": "secret-value",
                "nested": {"refreshToken": "token-value", "symbol": "ES"},
                "account_id": "SIM-1",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["captured"] is True
    assert payload["event_name"] == "paper_session_started"
    assert payload["metadata"]["apiKey"] == "[REDACTED]"
    assert payload["metadata"]["nested"]["refreshToken"] == "[REDACTED]"
    assert payload["metadata"]["nested"]["symbol"] == "ES"
    assert "user_id" not in payload
    assert payload["user_safe_id"]

    unknown = client.post(
        "/analytics/events",
        headers=auth_headers(user),
        json={"event_name": "send_me_raw_credentials", "metadata": {"password": "nope"}},
    )
    assert unknown.status_code == 200
    assert unknown.json()["event_name"] == "unknown_event"
    assert unknown.json()["event_category"] == "quarantine"
    assert unknown.json()["metadata"]["metadata"]["password"] == "[REDACTED]"

    denied = client.get("/analytics/admin/events", headers=auth_headers(user))
    assert denied.status_code == 403

    listed = client.get("/analytics/admin/events", headers=auth_headers(admin))
    assert listed.status_code == 200
    assert listed.json()["privacy"]["raw_user_ids_returned"] is False
    names = [event["event_name"] for event in listed.json()["events"]]
    assert "paper_session_started" in names
    assert "unknown_event" in names


def test_analytics_disabled_still_allows_app_and_skips_event_persistence():
    token = create_user("alice")
    object.__setattr__(database.APP_CONFIG, "analytics_enabled", False)

    response = client.post(
        "/analytics/events",
        headers=auth_headers(token),
        json={"event_name": "paper_order_created", "metadata": {"symbol": "ES"}},
    )
    assert response.status_code == 200
    assert response.json()["captured"] is False
    assert response.json()["reason"] == "analytics_disabled"

    with database.SessionLocal() as db:
        assert db.query(models.AnalyticsEvent).count() == 2  # registration + verification email events


def test_sentry_status_fails_safely_when_disabled_or_invalid():
    status_response = client.get("/analytics/status")
    assert status_response.status_code == 200
    assert status_response.json()["error_tracking"]["status"] == "disabled"
    assert status_response.json()["live_trading_enabled"] is False

    object.__setattr__(database.APP_CONFIG, "sentry_enabled", True)
    object.__setattr__(database.APP_CONFIG, "sentry_dsn", "not-a-dsn")
    invalid = client.get("/analytics/status")
    assert invalid.status_code == 200
    assert invalid.json()["error_tracking"]["status"] == "invalid_config"


def test_admin_onboarding_funnel_metrics_are_aggregated_and_privacy_safe():
    token = create_user("alice")
    admin = create_user("admin", admin=True)
    for event_name in [
        "email_verification_completed",
        "legal_acceptance_completed",
        "invite_redeemed",
        "integration_created",
        "account_contract_selected",
        "paper_session_started",
    ]:
        response = client.post("/analytics/events", headers=auth_headers(token), json={"event_name": event_name})
        assert response.status_code == 200

    report = client.get("/analytics/admin/onboarding-funnel", headers=auth_headers(admin))
    assert report.status_code == 200
    steps = {step["code"]: step for step in report.json()["steps"]}
    assert steps["registration_completed"]["count"] >= 1
    assert steps["email_verification_completed"]["count"] >= 1
    assert steps["legal_acceptance_completed"]["count"] == 1
    assert steps["invite_redeemed"]["count"] == 1
    assert steps["integration_created"]["count"] == 1
    assert steps["paper_session_started"]["conversion_from_registration"] > 0
    assert report.json()["privacy"]["user_level_data"] is False


def test_admin_activation_retention_and_engagement_metrics_use_existing_records():
    admin = create_user("admin", admin=True)
    create_user("alice")
    create_user("bob")
    now = datetime.utcnow()
    with database.SessionLocal() as db:
        alice = db.query(models.User).filter(models.User.username == "alice").one()
        bob = db.query(models.User).filter(models.User.username == "bob").one()
        integration = models.PlatformIntegration(
            user_id=alice.id,
            display_name="Paper Broker",
            provider="TOPSTEPX",
            status="active",
        )
        db.add(integration)
        db.flush()
        config = models.StrategyConfig(
            user_id=alice.id,
            integration_id=integration.id,
            account_id="SIM-1",
            symbol="ES",
            trading_mode="paper",
            parameters={"buy_threshold": 30, "sell_threshold": 70},
        )
        db.add(config)
        db.flush()
        db.add_all(
            [
                models.PaperOrder(
                    user_id=alice.id,
                    integration_id=integration.id,
                    account_id="SIM-1",
                    symbol="ES",
                    side="BUY",
                    quantity=1,
                    trading_mode="paper",
                    source="manual",
                    idempotency_key="order-1",
                    status="filled",
                    created_at=now - timedelta(days=1),
                ),
                models.PaperOrder(
                    user_id=alice.id,
                    integration_id=integration.id,
                    account_id="SIM-1",
                    symbol="ES",
                    side="SELL",
                    quantity=1,
                    trading_mode="paper",
                    source="manual",
                    idempotency_key="order-2",
                    status="risk_blocked",
                    created_at=now,
                ),
                models.PaperOrder(
                    user_id=bob.id,
                    symbol="NQ",
                    side="BUY",
                    quantity=1,
                    trading_mode="paper",
                    source="manual",
                    idempotency_key="order-3",
                    status="filled",
                    created_at=now,
                ),
                models.KillSwitch(user_id=alice.id, integration_id=integration.id, account_id="SIM-1", reason="test"),
                models.StrategySignal(
                    user_id=alice.id,
                    strategy_config_id=config.id,
                    integration_id=integration.id,
                    account_id="SIM-1",
                    symbol="ES",
                    signal="BUY",
                    status="emitted",
                    created_at=now,
                ),
                models.SupportRequest(
                    user_id=alice.id,
                    reference_id="sup_test",
                    category="paper_order",
                    severity="normal",
                    subject="Paper order help",
                    sanitized_message="Help with paper order.",
                    created_at=now,
                ),
            ]
        )
        analytics_service.capture_event(db, event_name="paper_session_started", user_id=alice.id)
        db.commit()

    activation = client.get("/analytics/admin/activation-retention", headers=auth_headers(admin))
    assert activation.status_code == 200
    assert activation.json()["activated_users"] == 2
    assert activation.json()["returning_users"] == 1
    assert activation.json()["privacy"]["user_level_data"] is False

    engagement = client.get("/analytics/admin/engagement", headers=auth_headers(admin))
    assert engagement.status_code == 200
    payload = engagement.json()
    assert payload["paper_sessions"] == 1
    assert payload["paper_orders"] == 3
    assert payload["blocked_orders"] >= 1
    assert payload["kill_switch_activations"] == 1
    assert payload["strategy_signals"] == 1
    assert payload["support_requests"] == 1
    assert payload["live_trading_enabled"] is False

    summary = client.get("/analytics/admin/summary", headers=auth_headers(admin))
    assert summary.status_code == 200
    assert summary.json()["status"]["live_trading_enabled"] is False
    assert client.get("/health/live").json()["live_trading_enabled"] is False
