from collections import defaultdict, deque
import time
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from . import auth_routes, integrations_routes, models, database, scheduler, contracts, launch_gate_routes, reconciliation_routes, risk_routes
from . import analysis_routes
from . import demo
from . import health
from .database import engine
from fastapi.middleware.cors import CORSMiddleware
from .trading_routes import router as trading_router
from .app_config import default_cors_origins
from .observability import log_event, setup_logging

setup_logging(database.APP_CONFIG.log_level)

if database.APP_CONFIG.allow_create_all and not database.APP_CONFIG.is_production:
    models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(integrations_routes.router, tags=["integrations"])
app.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
app.include_router(contracts.router, tags=["contracts"])
app.include_router(analysis_routes.router, prefix="/analysis", tags=["analysis"])
app.include_router(trading_router, prefix="/trading", tags=["trading"])
app.include_router(risk_routes.router, prefix="/risk", tags=["risk"])
app.include_router(reconciliation_routes.router, prefix="/reconciliation", tags=["reconciliation"])
app.include_router(launch_gate_routes.router, prefix="/launch-gate", tags=["launch-gate"])
app.include_router(health.router, tags=["health"])
app.include_router(demo.router)

cors_origins = default_cors_origins(database.APP_CONFIG)
allowed_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
allowed_headers = ["Authorization", "Content-Type", "X-Request-ID"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
)


_rate_limit_window: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def operational_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    now = time.monotonic()
    bucket = _rate_limit_window[key]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= database.APP_CONFIG.rate_limit_requests_per_minute:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    bucket.append(now)

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
            error=str(exc),
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
