from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Any, Iterable, Sequence
from uuid import uuid4

from sqlalchemy import event, or_, inspect
from sqlalchemy.orm import Session, with_loader_criteria

from . import models
from .authorization import TenantContext
from .observability import log_event
from .time_utils import as_utc, utc_now


class TenantScopeError(RuntimeError):
    def __init__(self, code: str = "validated_tenant_required"):
        self.code = code
        super().__init__(code)


def require_tenant(tenant: TenantContext) -> TenantContext:
    if not isinstance(tenant, TenantContext):
        raise TenantScopeError()
    try:
        return tenant.assert_valid()
    except ValueError as exc:
        raise TenantScopeError(str(exc) or "validated_tenant_required") from exc


def bind_tenant_context(db: Session, tenant: TenantContext, *, replace_authenticated: bool = False) -> TenantContext:
    tenant = require_tenant(tenant)
    current = db.info.get("tenant_context")
    if current is not None and current.user_id != tenant.user_id:
        allowed = replace_authenticated and tenant.source == "operator" and current.source == "session"
        allowed = allowed or (
            tenant.source == "signed_job"
            and current.source == "signed_job"
            and tenant.request_id != current.request_id
        )
        if not allowed:
            log_event("tenant_authorization", "tenant_context_conflict",
                      correlation_id=tenant.correlation_id, actor_user_id=tenant.actor_id)
            raise TenantScopeError("tenant_context_conflict")
    db.info["tenant_context"] = tenant
    db.info["tenant_enforcement"] = True
    return tenant


SYSTEM_MAINTENANCE_PURPOSES = frozenset({
    "durable-recovery-discovery",
    "durable-command-discovery",
    "durable-market-discovery",
    "outbox-claim-discovery",
    "topstep-restore-reconciliation",
    "hosted-security-epoch-bootstrap",
})


@contextmanager
def operator_aggregate_scope(db: Session, purpose: str):
    """Explicit read-only aggregate port for audited operator metrics."""
    operator = db.info.get("operator_context")
    if operator is None or purpose != "analytics-aggregate":
        raise TenantScopeError("operator_aggregate_scope_required")
    previous_enforcement = db.info.pop("tenant_enforcement", None)
    try:
        yield
    finally:
        if previous_enforcement is not None:
            db.info["tenant_enforcement"] = previous_enforcement


@contextmanager
def operator_global_scope(db: Session, purpose: str):
    """Explicit audited operator port for approved global metadata mutations."""
    operator = db.info.get("operator_context")
    if operator is None or purpose != "beta-waitlist-administration":
        raise TenantScopeError("operator_global_scope_required")
    previous_enforcement = db.info.pop("tenant_enforcement", None)
    try:
        yield
    finally:
        if previous_enforcement is not None:
            db.info["tenant_enforcement"] = previous_enforcement


@contextmanager
def system_maintenance_scope(db: Session, purpose: str):
    """Visibly named worker-only discovery scope; never use from request code."""
    if purpose not in SYSTEM_MAINTENANCE_PURPOSES:
        raise TenantScopeError("unapproved_system_scope")
    previous_context = db.info.pop("tenant_context", None)
    previous_enforcement = db.info.pop("tenant_enforcement", None)
    try:
        yield
    finally:
        if previous_context is not None:
            db.info["tenant_context"] = previous_context
        if previous_enforcement is not None:
            db.info["tenant_enforcement"] = previous_enforcement


def _tenant_models() -> tuple[type, ...]:
    return tuple(mapper.class_ for mapper in models.Base.registry.mappers if "user_id" in mapper.local_table.c)


@event.listens_for(Session, "do_orm_execute")
def _enforce_bound_tenant(execute_state):
    """Defense in depth for legacy service queries on an authenticated session."""
    db = execute_state.session
    if not db.info.get("tenant_enforcement") or not (
        execute_state.is_select or execute_state.is_update or execute_state.is_delete
    ):
        return
    tenant = require_tenant(db.info.get("tenant_context"))
    tenant_id = tenant.user_id
    statement = execute_state.statement
    for model in _tenant_models():
        if model is models.BetaWaitlistEntry:
            # Public waitlist entries may exist before they are linked to a
            # user; those rows are claimable by normalized email only.
            statement = statement.options(with_loader_criteria(
                model, lambda cls: or_(cls.user_id == tenant_id, cls.user_id.is_(None)),
                include_aliases=True,
            ))
        else:
            statement = statement.options(with_loader_criteria(
                model, lambda cls: cls.user_id == tenant_id, include_aliases=True
            ))
    execute_state.statement = statement


@event.listens_for(Session, "before_flush")
def _reject_cross_tenant_flush(db: Session, _flush_context, _instances):
    if not db.info.get("tenant_enforcement"):
        return
    tenant = require_tenant(db.info.get("tenant_context"))
    for instance in tuple(db.new) + tuple(db.dirty) + tuple(db.deleted):
        table = getattr(instance, "__table__", None)
        if table is None or "user_id" not in table.c:
            continue
        value = getattr(instance, "user_id", None)
        if value != tenant.user_id:
            log_event("tenant_authorization", "cross_tenant_flush_rejected",
                      correlation_id=tenant.correlation_id, actor_user_id=tenant.actor_id,
                      resource_type=table.name)
            raise TenantScopeError("cross_tenant_mutation")


class TenantRepository:
    """Tenant-owned persistence port. It never returns a raw Query or Session."""

    def __init__(self, db: Session, tenant: TenantContext):
        self.__db = db
        self.tenant = bind_tenant_context(db, tenant)

    def lock_tenant_owner(self):
        """Lock only the authenticated tenant's principal for onboarding serialization."""
        return self.__db.query(models.User).filter(
            models.User.id == self.tenant.user_id
        ).with_for_update().first()

    @staticmethod
    def _tenant_column(model):
        if "user_id" not in model.__table__.c:
            raise TenantScopeError("model_is_not_tenant_owned")
        return model.user_id

    def _scoped(self, model, criteria: Sequence[Any] = ()):
        return self.__db.query(model).filter(
            self._tenant_column(model) == self.tenant.user_id, *criteria
        )

    def get(self, model, resource_id, *, lock: bool = False):
        primary_keys = inspect(model).primary_key
        if len(primary_keys) != 1:
            raise TenantScopeError("composite_key_requires_explicit_criteria")
        query = self._scoped(model, (primary_keys[0] == resource_id,))
        return (query.with_for_update() if lock else query).first()

    def first(self, model, *criteria, lock: bool = False):
        query = self._scoped(model, criteria)
        return (query.with_for_update() if lock else query).first()

    def list(self, model, *criteria, order_by: Iterable[Any] = (), limit: int | None = None,
             offset: int | None = None, lock: bool = False, skip_locked: bool = False) -> list[Any]:
        query = self._scoped(model, criteria)
        if order_by:
            query = query.order_by(*tuple(order_by))
        if lock:
            query = query.with_for_update(skip_locked=skip_locked)
        if offset is not None:
            query = query.offset(max(0, offset))
        if limit is not None:
            query = query.limit(max(0, limit))
        return list(query.all())

    def count(self, model, *criteria) -> int:
        return int(self._scoped(model, criteria).count())

    def exists(self, model, *criteria) -> bool:
        return self._scoped(model, criteria).first() is not None

    def add(self, instance):
        self._tenant_column(type(instance))
        value = getattr(instance, "user_id", None)
        if value is None:
            instance.user_id = self.tenant.user_id
        elif value != self.tenant.user_id:
            raise TenantScopeError("cross_tenant_mutation")
        self.__db.add(instance)
        return instance

    def update(self, model, criteria: Sequence[Any], values: dict[str, Any]) -> int:
        if "user_id" in values and values["user_id"] != self.tenant.user_id:
            raise TenantScopeError("cross_tenant_mutation")
        return int(self._scoped(model, criteria).update(values, synchronize_session=False))

    def delete(self, model, *criteria) -> int:
        return int(self._scoped(model, criteria).delete(synchronize_session=False))

    def aggregate_count(self, model, *criteria) -> int:
        return self.count(model, *criteria)

    def audit_history(self, *, limit: int | None = None) -> list[models.SecurityAuditEvent]:
        query = self.__db.query(models.SecurityAuditEvent).filter(or_(
            models.SecurityAuditEvent.actor_user_id == self.tenant.user_id,
            models.SecurityAuditEvent.target_user_id == self.tenant.user_id,
        )).order_by(models.SecurityAuditEvent.created_at.asc())
        if limit is not None:
            query = query.limit(limit)
        return list(query.all())

    def tenant_user(self) -> models.User | None:
        return self.__db.query(models.User).filter(models.User.id == self.tenant.user_id).first()

    def add_security_event(self, event_row: models.SecurityAuditEvent):
        if self.tenant.user_id not in {event_row.actor_user_id, event_row.target_user_id}:
            raise TenantScopeError("cross_tenant_audit_write")
        self.__db.add(event_row)
        return event_row

    def flush(self) -> None:
        self.__db.flush()

    def refresh(self, instance) -> None:
        if getattr(instance, "user_id", None) != self.tenant.user_id:
            raise TenantScopeError("cross_tenant_read")
        self.__db.refresh(instance)


class OperatorRepository:
    """Narrow global metadata port; tenant data still delegates to TenantRepository."""

    GLOBAL_MODELS = frozenset({
        models.BetaInviteCode,
        models.BetaWaitlistEntry,
        models.PlanTier,
        models.LegalDocument,
    })

    def __init__(self, db: Session):
        context = require_tenant(db.info.get("tenant_context"))
        if context.source != "operator" or "operator" not in context.roles:
            raise TenantScopeError("operator_context_required")
        self.__db = db
        self.context = context
        self.tenant = TenantRepository(db, context)

    def _approved(self, model) -> None:
        if model not in self.GLOBAL_MODELS:
            raise TenantScopeError("operator_global_model_not_allowed")

    def global_get(self, model, resource_id):
        self._approved(model)
        previous = self.__db.info.pop("tenant_enforcement", None)
        try:
            return self.__db.query(model).filter(model.id == resource_id).first()
        finally:
            if previous is not None:
                self.__db.info["tenant_enforcement"] = previous

    def global_list(self, model, *, order_by: Iterable[Any] = (), limit: int = 100):
        self._approved(model)
        previous = self.__db.info.pop("tenant_enforcement", None)
        try:
            query = self.__db.query(model)
            if order_by:
                query = query.order_by(*tuple(order_by))
            return list(query.limit(limit).all())
        finally:
            if previous is not None:
                self.__db.info["tenant_enforcement"] = previous


@dataclass(frozen=True)
class VerifiedTenantJob:
    tenant_id: int
    actor_id: int
    job_id: str
    job_type: str
    purpose: str
    issuer: str
    environment: str
    issued_at: str
    expires_at: str
    correlation_id: str
    causation_id: str | None
    payload_hash: str
    nonce: str
    version: int
    signature: str

    def _unsigned(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("signature", None)
        return value

    @classmethod
    def issue(cls, tenant: TenantContext, command_id: str, secret: str, *,
              job_type: str = "durable-simulation", purpose: str = "tenant-background-work",
              issuer: str = "simulation-worker", environment: str = "test",
              payload: dict[str, Any] | None = None, lifetime_seconds: int = 300):
        tenant = require_tenant(tenant)
        now = utc_now()
        payload_hash = hashlib.sha256(json.dumps(
            payload or {}, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        unsigned = {
            "tenant_id": tenant.user_id, "actor_id": tenant.actor_id,
            "job_id": str(command_id), "job_type": job_type, "purpose": purpose,
            "issuer": issuer, "environment": environment, "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=lifetime_seconds)).isoformat(),
            "correlation_id": tenant.correlation_id, "causation_id": tenant.causation_id,
            "payload_hash": payload_hash, "nonce": uuid4().hex, "version": 2,
        }
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        return cls(**unsigned, signature=signature)

    def validate(self, secret: str, *, expected_tenant: int, expected_command: str,
                 expected_job_type: str | None = None, expected_purpose: str | None = None,
                 expected_issuer: str = "simulation-worker", expected_environment: str | None = None,
                 expected_actor: int | None = None, payload: dict[str, Any] | None = None,
                 max_age_seconds: int = 300):
        canonical = json.dumps(self._unsigned(), sort_keys=True, separators=(",", ":"))
        expected_signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        try:
            issued = as_utc(datetime.fromisoformat(self.issued_at))
            expires = as_utc(datetime.fromisoformat(self.expires_at))
        except (TypeError, ValueError) as exc:
            raise TenantScopeError("invalid_job_context") from exc
        payload_hash = hashlib.sha256(json.dumps(
            payload or {}, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        invalid = (
            self.version != 2 or self.tenant_id != expected_tenant
            or (expected_actor is not None and self.actor_id != expected_actor)
            or self.job_id != str(expected_command) or self.issuer != expected_issuer
            or (expected_job_type is not None and self.job_type != expected_job_type)
            or (expected_purpose is not None and self.purpose != expected_purpose)
            or (expected_environment is not None and self.environment != expected_environment)
            or self.payload_hash != payload_hash
            or not hmac.compare_digest(expected_signature, self.signature)
            or issued > utc_now() + timedelta(seconds=30)
            or utc_now() - issued > timedelta(seconds=max_age_seconds)
            or expires <= utc_now()
        )
        if invalid:
            log_event("tenant_authorization", "job_context_rejected",
                      correlation_id=self.correlation_id, job_type=self.job_type)
            raise TenantScopeError("invalid_job_tenant")
        return TenantContext(
            user_id=self.tenant_id, username="verified-job", actor_user_id=self.actor_id,
            source="signed_job", request_id=self.job_id, correlation_id=self.correlation_id,
            causation_id=self.causation_id, created_at=issued, expires_at=expires,
            integrity_verified=True,
        )
