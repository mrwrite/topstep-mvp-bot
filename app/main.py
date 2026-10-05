import hashlib
import asyncio
import time
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from . import auth_routes, integrations_routes, models, database, scheduler, contracts, launch_gate_routes, reconciliation_routes, risk_routes, legal_routes, beta_access_routes, onboarding_routes, analytics_routes, subscription_routes, account_lifecycle_routes, simulation_routes, topstep_onboarding_routes, hosted_combine_routes, device_telemetry_routes
from . import analysis_routes
from . import demo, crypto
from . import health
from .database import engine
from fastapi.middleware.cors import CORSMiddleware
from .trading_routes import router as trading_router
from .app_config import default_cors_origins
from .observability import log_event, safe_exception, setup_logging
from .rate_limit import RateLimitStoreUnavailable, consume
from .hosted_execution_boundary import enforce_hosted_execution_boundary
from .simulation_worker import periodic_recovery, recovery_cycle

setup_logging(database.APP_CONFIG.log_level)

if database.APP_CONFIG.allow_create_all and not database.APP_CONFIG.is_production:
    models.Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .providers.topstepx import TopStepXAdapter
    enforce_hosted_execution_boundary(TopStepXAdapter)
    worker_allowed = True
    if database.APP_CONFIG.is_production:
        key_health = await asyncio.to_thread(crypto.key_management_health)
        if not key_health["available"]:
            raise RuntimeError("Production key-management readiness failed closed.")
    if database.APP_CONFIG.deployment_profile == "hosted_topstep_combine_beta":
        from .topstep_session_security import security_epoch_status
        db = database.SessionLocal()
        try:
            epoch = security_epoch_status(db)
            if epoch.state == "uninitialized":
                from .topstep_session_security import bootstrap_security_epoch
                bootstrap_security_epoch(db)
                db.commit()
                epoch = security_epoch_status(db)
        finally:
            db.close()
        if epoch.state == "rollback_rejected":
            raise RuntimeError("Hosted security epoch rollback rejected.")
        worker_allowed = epoch.ready
    stop = asyncio.Event()
    worker_id = f"simulation-worker:{uuid4().hex}"
    service_role = os.getenv("SERVICE_ROLE", "combined").strip().lower()
    if database.APP_CONFIG.is_production and service_role not in {"api", "worker"}:
        raise RuntimeError("Production requires SERVICE_ROLE=api or SERVICE_ROLE=worker.")
    task = None
    if worker_allowed and service_role in {"combined", "worker"}:
        await asyncio.to_thread(recovery_cycle, worker_id=worker_id)
        task = asyncio.create_task(periodic_recovery(stop, worker_id=worker_id))
    try:
        yield
    finally:
        stop.set()
        if task is not None:
            await task


app = FastAPI(lifespan=lifespan)

app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(account_lifecycle_routes.router, prefix="/auth", tags=["account-lifecycle"])
app.include_router(topstep_onboarding_routes.router, tags=["topstep-onboarding"])
app.include_router(hosted_combine_routes.router, tags=["hosted-combine-dry-run"])
app.include_router(device_telemetry_routes.router)
app.include_router(integrations_routes.router, tags=["integrations"])
app.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
app.include_router(simulation_routes.router, prefix="/simulation-runs", tags=["simulation-runs"])
app.include_router(contracts.router, tags=["contracts"])
app.include_router(analysis_routes.router, prefix="/analysis", tags=["analysis"])
app.include_router(trading_router, prefix="/trading", tags=["trading"])
app.include_router(risk_routes.router, prefix="/risk", tags=["risk"])
app.include_router(reconciliation_routes.router, prefix="/reconciliation", tags=["reconciliation"])
app.include_router(launch_gate_routes.router, prefix="/launch-gate", tags=["launch-gate"])
app.include_router(legal_routes.router, prefix="/legal", tags=["legal"])
app.include_router(beta_access_routes.router, prefix="/beta", tags=["beta-access"])
app.include_router(onboarding_routes.router, prefix="/onboarding", tags=["onboarding-support"])
app.include_router(analytics_routes.router, prefix="/analytics", tags=["beta-monitoring-analytics"])
app.include_router(subscription_routes.router, prefix="/subscription", tags=["subscription-readiness"])
app.include_router(health.router, tags=["health"])
app.include_router(demo.router)

cors_origins = default_cors_origins(database.APP_CONFIG)
allowed_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
allowed_headers = ["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
)


class _RateLimitTestControl:
    """Compatibility test hook; production decisions still use the shared table."""

    def clear(self) -> None:
        db = database.SessionLocal()
        try:
            db.query(models.RateLimitBucket).delete()
            db.commit()
        finally:
            db.close()


_rate_limit_window = _RateLimitTestControl()


@app.middleware("http")
async def operational_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    client = request.client.host if request.client else "unknown"
    client_hash = hashlib.sha256(client.encode("utf-8")).hexdigest()
    key = f"{client_hash}:{request.url.path}"
    try:
        allowed = consume(key, database.APP_CONFIG.rate_limit_requests_per_minute)
    except RateLimitStoreUnavailable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Request protection is temporarily unavailable.", "request_id": request_id},
            headers={"X-Request-ID": request_id, "Retry-After": "60"},
        )
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event(
            "api",
            "request_failed",
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            error=safe_exception(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    duration_ms = round((time.monotonic() - start) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if database.APP_CONFIG.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    log_event(
        "api",
        "request_completed",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response
