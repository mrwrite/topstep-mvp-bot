from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import database, models
from .auth_routes import get_current_user_model
from .observability import log_event
from .time_utils import as_utc, utc_now


@dataclass(frozen=True)
class TenantContext:
    """Immutable trusted identity for one tenant-scoped operation."""

    user_id: int
    username: str
    actor_user_id: int | None = None
    session_id: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    source: str = "internal"
    request_id: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    integrity_verified: bool = True

    @property
    def tenant_id(self) -> int:
        return self.user_id

    @property
    def actor_id(self) -> int:
        return self.actor_user_id or self.user_id

    def assert_valid(self) -> "TenantContext":
        if self.user_id <= 0 or not self.integrity_verified:
            raise ValueError("validated_tenant_required")
        if self.expires_at is not None and as_utc(self.expires_at) <= utc_now():
            raise ValueError("tenant_context_expired")
        return self


@dataclass(frozen=True)
class OperatorContext:
    actor_user_id: int
    target_tenant_id: int
    purpose: str
    case_id: str
    action: str
    correlation_id: str
    created_at: datetime
    expires_at: datetime
    target_resource: str | None = None
    permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.actor_user_id <= 0 or self.target_tenant_id <= 0:
            raise ValueError("operator_identity_required")
        if len(self.purpose.strip()) < 8:
            raise ValueError("operator_purpose_required")
        if not self.case_id.strip():
            raise ValueError("operator_case_required")
        if as_utc(self.expires_at) <= as_utc(self.created_at):
            raise ValueError("operator_context_expired")

    def tenant_context(self, username: str) -> TenantContext:
        if as_utc(self.expires_at) <= utc_now():
            raise ValueError("operator_context_expired")
        return TenantContext(
            user_id=self.target_tenant_id,
            username=username,
            actor_user_id=self.actor_user_id,
            roles=("operator",),
            permissions=self.permissions,
            source="operator",
            correlation_id=self.correlation_id,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


def tenant_context(request: Request, current_user: models.User = Depends(get_current_user_model)) -> TenantContext:
    context = getattr(request.state, "tenant_context", None)
    if not isinstance(context, TenantContext) or context.user_id != current_user.id:
        raise HTTPException(status_code=401, detail="Validated tenant context is required.")
    try:
        return context.assert_valid()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Validated tenant context is required.") from exc


def owned_or_404(db: Session, model: type, resource_id: int, tenant: TenantContext):
    from .tenant_repository import TenantRepository

    row = TenantRepository(db, tenant).get(model, resource_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return row


def require_operator_user(
    request: Request,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
    reason: str | None = Header(default=None, alias="X-Operator-Reason"),
    case_id: str | None = Header(default=None, alias="X-Operator-Case-ID"),
    target_user_id: int | None = Header(default=None, alias="X-Operator-Target-User"),
    target_resource: str | None = Header(default=None, alias="X-Operator-Target-Resource"),
) -> models.User:
    outcome = "authorized"
    path_target = request.path_params.get("user_id")
    if not current_user.is_admin:
        outcome = "denied_not_operator"
    elif not reason or len(reason.strip()) < 8 or not case_id or target_user_id is None:
        outcome = "denied_missing_purpose"
    elif path_target is not None and int(path_target) != target_user_id:
        outcome = "denied_target_mismatch"

    correlation_id = request.headers.get("X-Request-ID") or str(uuid4())
    now = utc_now()
    operator = OperatorContext(
        actor_user_id=current_user.id,
        target_tenant_id=target_user_id or current_user.id,
        purpose=(reason or "denied access").strip(),
        case_id=(case_id or "missing").strip(),
        action=f"{request.method} {request.url.path}",
        correlation_id=correlation_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        target_resource=target_resource,
        permissions=(f"{request.method}:{request.url.path}",),
    )
    db.add(models.SecurityAuditEvent(
        actor_user_id=current_user.id, target_user_id=target_user_id,
        event_type="operator_access", action=operator.action, reason=reason,
        case_id=case_id, outcome=outcome,
        event_metadata={"correlation_id": correlation_id, "target_resource": target_resource,
                        "expires_at": operator.expires_at.isoformat()},
    ))
    db.commit()
    if outcome != "authorized":
        log_event("tenant_authorization", "operator_access_denied",
                  correlation_id=correlation_id, actor_user_id=current_user.id, outcome=outcome)
        raise HTTPException(status_code=403, detail="Purpose-bound operator authorization is required.")

    from .tenant_repository import bind_tenant_context

    scoped = operator.tenant_context(current_user.username)
    bind_tenant_context(db, scoped, replace_authenticated=True)
    request.state.tenant_context = scoped
    request.state.operator_context = operator
    db.info["operator_context"] = operator
    log_event("tenant_authorization", "operator_context_created",
              correlation_id=correlation_id, actor_user_id=current_user.id,
              tenant_id=target_user_id, expires_at=operator.expires_at.isoformat())
    return current_user
