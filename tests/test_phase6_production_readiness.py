import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app.app_config import AppConfig, ConfigError, validate_config  # noqa: E402
from app.main import app  # noqa: E402
from app.observability import redact  # noqa: E402


client = TestClient(app)


def test_health_and_operational_status_are_paper_only():
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert live.json()["live_trading_enabled"] is False

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["live_trading"]["status"] == "disabled"

    status = client.get("/ops/status")
    assert status.status_code == 200
    assert status.json()["live_trading_enabled"] is False
    assert status.json()["execution_mode"] == "paper-only"


def test_security_headers_and_request_id_are_present():
    response = client.get("/health/live", headers={"X-Request-ID": "req-test"})
    assert response.headers["X-Request-ID"] == "req-test"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_rate_limit_returns_429_when_window_exceeded(monkeypatch):
    from app import database
    from app.main import _rate_limit_window

    original = database.APP_CONFIG.rate_limit_requests_per_minute
    object.__setattr__(database.APP_CONFIG, "rate_limit_requests_per_minute", 1)
    _rate_limit_window.clear()
    try:
        assert client.get("/health/live").status_code == 200
        limited = client.get("/health/live")
        assert limited.status_code == 429
        assert limited.json()["detail"] == "Rate limit exceeded."
    finally:
        object.__setattr__(database.APP_CONFIG, "rate_limit_requests_per_minute", original)
        _rate_limit_window.clear()


def test_production_config_requires_explicit_encryption_key_and_no_create_all():
    base = {
        "app_env": "production",
        "database_url": "postgresql://user:pass@example/db",
        "secret_key": "secret",
        "credentials_encryption_key": None,
        "cors_origins": ("https://demo.example.com",),
        "allow_create_all": False,
        "rate_limit_requests_per_minute": 120,
        "log_level": "INFO",
    }
    with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
        validate_config(AppConfig(**base))

    with pytest.raises(ConfigError, match="ALLOW_CREATE_ALL"):
        validate_config(
            AppConfig(
                **{
                    **base,
                    "credentials_encryption_key": Fernet.generate_key().decode("utf-8"),
                    "allow_create_all": True,
                }
            )
        )

    validate_config(
        AppConfig(
            **{
                **base,
                "credentials_encryption_key": Fernet.generate_key().decode("utf-8"),
            }
        )
    )


def test_redaction_removes_secret_values():
    payload = {
        "apiKey": "should-not-appear",
        "nested": {"refreshToken": "hidden", "symbol": "ES"},
    }
    redacted = redact(payload)
    assert redacted["apiKey"] == "[REDACTED]"
    assert redacted["nested"]["refreshToken"] == "[REDACTED]"
    assert redacted["nested"]["symbol"] == "ES"
