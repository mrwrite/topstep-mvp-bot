from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app import database, models
from app.crypto import key_management_health
from app.providers.types import IMPLEMENTED_PROVIDER_CAPABILITIES, ROADMAP_PROVIDER_CAPABILITIES


router = APIRouter()


def _migration_state() -> dict:
    if not database.APP_CONFIG.is_production:
        return {"status": "skipped", "reason": "migration readiness is enforced in production mode"}
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    expected_heads = set(script.get_heads())
    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_heads = set(context.get_current_heads())
    ok = bool(current_heads) and current_heads == expected_heads
    return {
        "status": "ok" if ok else "error",
        "current_heads": sorted(current_heads),
        "expected_heads": sorted(expected_heads),
    }


def _readiness_checklist(migration_state: dict | None = None) -> list[dict]:
    migrations = migration_state or _migration_state()
    migrations_ok = migrations["status"] in {"ok", "skipped"}
    return [
        {
            "code": "mode",
            "label": "Execution mode",
            "passed": True,
            "detail": "Paper-only execution is enforced; live order routing is disabled.",
            "priority": "P0",
        },
        {
            "code": "provider_capabilities",
            "label": "Provider capabilities",
            "passed": True,
            "detail": "Implemented and roadmap provider capabilities are exposed for UI checks.",
            "priority": "P1",
        },
        {
            "code": "order_lifecycle",
            "label": "Order lifecycle",
            "passed": True,
            "detail": "Paper orders use durable lifecycle, event, duplicate, and ledger records.",
            "priority": "P0",
        },
        {
            "code": "migrations",
            "label": "Migration baseline",
            "passed": migrations_ok,
            "detail": "Alembic schema state is current or explicitly skipped outside production."
            if migrations_ok
            else "Database migration state is behind Alembic head.",
            "priority": "P0",
            "metadata": migrations,
        },
        {
            "code": "observability",
            "label": "Operational diagnostics",
            "passed": True,
            "detail": "Health, launch gate, risk, paper ledger, and reconciliation diagnostics are available.",
            "priority": "P1",
        },
    ]


def _key_operation_state() -> dict:
    try:
        with database.SessionLocal() as db:
            operation = (db.query(models.KeyManagementOperation)
                         .order_by(models.KeyManagementOperation.created_at.desc()).first())
    except Exception:
        return {"rotation_state": "unavailable", "migration_state": "unavailable"}
    if operation is None:
        return {"rotation_state": "idle", "migration_state": "not-started"}
    key = "migration_state" if operation.operation_type == "fernet-migration" else "rotation_state"
    result = {"rotation_state": "idle", "migration_state": "not-started"}
    result[key] = operation.state
    return result


@router.get("/health/live")
def live():
    return {
        "status": "ok",
        "service": "trading-bot-api",
        "live_trading_enabled": False,
    }


@router.get("/health/ready")
def ready():
    checks = {
        "database": {"status": "unknown"},
        "config": {"status": "ok", "environment": database.APP_CONFIG.app_env},
        "migrations": {"status": "unknown"},
        "live_trading": {"status": "disabled"},
        "key_management": {"status": "unknown"},
        "hosted_security_epoch": {"status": "not_applicable"},
    }
    http_status = status.HTTP_200_OK
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "message": str(exc)}
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    try:
        key_health = key_management_health()
        key_health.update(_key_operation_state())
        checks["key_management"] = {
            "status": "ok" if key_health["available"] else "error",
            **key_health,
        }
        if database.APP_CONFIG.is_production and not key_health["available"]:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    except Exception:
        checks["key_management"] = {"status": "error", "classification": "failed"}
        if database.APP_CONFIG.is_production:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    try:
        checks["migrations"] = _migration_state()
        if checks["migrations"]["status"] == "error":
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    except Exception as exc:
        checks["migrations"] = {"status": "error", "message": str(exc)}
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    if database.APP_CONFIG.deployment_profile == "hosted_topstep_combine_beta":
        try:
            from .topstep_session_security import security_epoch_status
            db = database.SessionLocal()
            try:
                epoch = security_epoch_status(db)
            finally:
                db.close()
            checks["hosted_security_epoch"] = {
                "status": "ok" if epoch.ready else "error",
                "classification": epoch.state,
                "environment_epoch": epoch.environment_epoch,
                "database_epoch": epoch.database_epoch,
                "restore_reconciliation_required": not epoch.ready,
            }
            if not epoch.ready:
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        except Exception:
            checks["hosted_security_epoch"] = {"status": "error", "classification": "failed"}
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == status.HTTP_200_OK else "error",
            "checks": checks,
        },
    )


@router.get("/ops/status")
def operational_status():
    migration_state = _migration_state()
    return {
        "environment": database.APP_CONFIG.app_env,
        "live_trading_enabled": False,
        "execution_mode": "paper-only",
        "readiness_checklist": _readiness_checklist(migration_state),
        "implemented_provider_capabilities": {
            provider.value: sorted(capability.value for capability in capabilities)
            for provider, capabilities in IMPLEMENTED_PROVIDER_CAPABILITIES.items()
        },
        "roadmap_provider_capabilities": {
            provider.value: sorted(capability.value for capability in capabilities)
            for provider, capabilities in ROADMAP_PROVIDER_CAPABILITIES.items()
        },
    }
