from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app import database
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
        checks["migrations"] = _migration_state()
        if checks["migrations"]["status"] == "error":
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    except Exception as exc:
        checks["migrations"] = {"status": "error", "message": str(exc)}
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
    return {
        "environment": database.APP_CONFIG.app_env,
        "live_trading_enabled": False,
        "execution_mode": "paper-only",
        "implemented_provider_capabilities": {
            provider.value: sorted(capability.value for capability in capabilities)
            for provider, capabilities in IMPLEMENTED_PROVIDER_CAPABILITIES.items()
        },
        "roadmap_provider_capabilities": {
            provider.value: sorted(capability.value for capability in capabilities)
            for provider, capabilities in ROADMAP_PROVIDER_CAPABILITIES.items()
        },
    }
