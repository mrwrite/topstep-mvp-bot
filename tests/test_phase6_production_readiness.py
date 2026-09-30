import os

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, create_mock_engine, inspect, text

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app.app_config import AppConfig, ConfigError, validate_config  # noqa: E402
from app import models  # noqa: E402
from app.main import app  # noqa: E402
from app.observability import redact  # noqa: E402


client = TestClient(app)


def test_postgres_metadata_ddl_breaks_user_integration_foreign_key_cycle():
    statements = []
    engine = create_mock_engine(
        "postgresql+psycopg2://",
        lambda sql, *args, **kwargs: statements.append(
            str(sql.compile(dialect=engine.dialect))
        ),
    )

    models.Base.metadata.create_all(engine)
    models.Base.metadata.drop_all(engine)

    ddl = "\n".join(statements)
    assert "ADD CONSTRAINT fk_users_active_integration_id" in ddl
    assert "DROP CONSTRAINT fk_users_active_integration_id" in ddl


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
    checklist = {item["code"]: item for item in status.json()["readiness_checklist"]}
    assert checklist["mode"]["passed"] is True
    assert checklist["order_lifecycle"]["passed"] is True
    assert "migrations" in checklist


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
        "resend_api_key": "re_test",
        "resend_from_email": "noreply@example.com",
        "frontend_url": "https://demo.example.com",
    }
    with pytest.raises(ConfigError, match="TPM2"):
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

    with pytest.raises(ConfigError, match="TPM2"):
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


def test_fresh_database_can_upgrade_to_alembic_head(monkeypatch, tmp_path):
    db_path = tmp_path / "fresh-live-readiness.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    cfg = Config("alembic.ini")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected_tables = {
        "users",
        "platform_integrations",
        "paper_orders",
        "paper_order_events",
        "risk_settings",
        "kill_switches",
        "paper_account_snapshots",
        "paper_ledger_entries",
        "provider_reconciliation_runs",
        "account_reconciliation_locks",
        "live_readiness_acknowledgements",
        "launch_gate_evaluations",
    }
    assert expected_tables.issubset(tables)
    paper_order_indexes = {index["name"] for index in inspector.get_indexes("paper_orders")}
    assert "ux_paper_orders_user_idempotency" in paper_order_indexes


def test_production_readiness_fails_when_database_revision_is_behind(monkeypatch, tmp_path):
    from app import database

    db_path = tmp_path / "behind-head.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('dcfa013ab9b1')"))
        connection.execute(text("SELECT 1"))

    original_env = database.APP_CONFIG.app_env
    object.__setattr__(database.APP_CONFIG, "app_env", "production")
    monkeypatch.setattr(database, "engine", engine)
    try:
        response = client.get("/health/ready")
    finally:
        object.__setattr__(database.APP_CONFIG, "app_env", original_env)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["checks"]["migrations"]["status"] == "error"
