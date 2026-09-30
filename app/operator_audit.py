from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from . import models
from .observability import redact


@dataclass(frozen=True)
class OperatorActionContext:
    actor_user_id: int
    target_user_id: int
    purpose: str
    case_id: str
    action: str
    correlation_id: str

    @classmethod
    def create(cls, *, actor_user_id: int, target_user_id: int, purpose: str, case_id: str, action: str):
        return cls(actor_user_id, target_user_id, purpose, case_id, action, str(uuid4()))


def append_operator_event(
    db: Session,
    context: OperatorActionContext,
    *,
    outcome: str,
    resource_references: dict | None = None,
    external_confirmation: str = "not_applicable",
    failure_class: str | None = None,
) -> models.SecurityAuditEvent:
    if outcome not in {"authorized", "denied", "started", "succeeded", "failed", "partial", "cancelled"}:
        raise ValueError("Unsupported operator outcome.")
    safe = redact({
        "correlation_id": context.correlation_id,
        "purpose": context.purpose,
        "resource_references": resource_references or {},
        "external_confirmation": external_confirmation,
        "failure_class": failure_class,
    })
    event = models.SecurityAuditEvent(
        actor_user_id=context.actor_user_id,
        target_user_id=context.target_user_id,
        event_type="operator_action",
        action=context.action,
        reason=context.purpose,
        case_id=context.case_id,
        outcome=outcome,
        event_metadata=safe,
    )
    db.add(event)
    db.flush()
    return event
