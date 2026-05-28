from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.observability import log_event


NORMALIZED_PROVIDER_STATUSES = {
    "new": "submitted",
    "created": "submitted",
    "pending": "submitted",
    "submitted": "submitted",
    "accepted": "accepted",
    "working": "accepted",
    "open": "accepted",
    "partially_filled": "partially_filled",
    "partial_fill": "partially_filled",
    "partial": "partially_filled",
    "filled": "filled",
    "complete": "filled",
    "completed": "filled",
    "rejected": "rejected",
    "denied": "rejected",
    "cancelled": "canceled",
    "canceled": "canceled",
    "expired": "expired",
    "timeout": "timeout_unknown",
    "unknown": "timeout_unknown",
}

TERMINAL_NORMALIZED_STATUSES = {"filled", "rejected", "canceled", "expired"}
RETRYABLE_ERROR_TYPES = {"rate_limit", "provider_unavailable"}
RECONCILIATION_REQUIRED_ERROR_TYPES = {"timeout_unknown", "provider_unavailable", "unknown_state"}


@dataclass(frozen=True)
class ProviderErrorClassification:
    error_type: str
    retryable: bool
    requires_reconciliation: bool
    reason: str


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def normalize_provider_order_status(provider_status: str | None) -> str:
    if not provider_status:
        return "timeout_unknown"
    return NORMALIZED_PROVIDER_STATUSES.get(str(provider_status).strip().lower(), "timeout_unknown")


def classify_provider_error(error: Any) -> ProviderErrorClassification:
    text = str(error or "").lower()
    if "timeout" in text or "timed out" in text:
        return ProviderErrorClassification(
            error_type="timeout_unknown",
            retryable=False,
            requires_reconciliation=True,
            reason="Provider request timed out; reconciliation is required before retry.",
        )
    if "401" in text or "403" in text or "auth" in text or "credential" in text:
        return ProviderErrorClassification(
            error_type="auth_failure",
            retryable=False,
            requires_reconciliation=False,
            reason="Provider authentication failed; retry is blocked until credentials are fixed.",
        )
    if "429" in text or "rate" in text:
        return ProviderErrorClassification(
            error_type="rate_limit",
            retryable=True,
            requires_reconciliation=False,
            reason="Provider rate limit may be retried only by an explicit retry worker.",
        )
    if "unavailable" in text or "503" in text or "connection" in text:
        return ProviderErrorClassification(
            error_type="provider_unavailable",
            retryable=True,
            requires_reconciliation=True,
            reason="Provider state is unavailable; live orders must fail closed.",
        )
    if "validation" in text or "invalid" in text or "rejected" in text:
        return ProviderErrorClassification(
            error_type="validation_rejection",
            retryable=False,
            requires_reconciliation=False,
            reason="Provider rejected the request; retry is blocked.",
        )
    return ProviderErrorClassification(
        error_type="unknown_state",
        retryable=False,
        requires_reconciliation=True,
        reason="Provider state is unknown; reconciliation is required before retry.",
    )


def serialize_reconciliation_run(run: models.ProviderReconciliationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "user_id": run.user_id,
        "integration_id": run.integration_id,
        "account_id": run.account_id,
        "symbol": run.symbol,
        "provider_order_id": run.provider_order_id,
        "client_order_id": run.client_order_id,
        "status": run.status,
        "summary": run.summary or {},
        "started_at": _utc_iso(run.started_at),
        "completed_at": _utc_iso(run.completed_at),
        "created_at": _utc_iso(run.created_at),
    }


def serialize_reconciliation_event(event: models.ProviderReconciliationEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "event_type": event.event_type,
        "provider_status": event.provider_status,
        "normalized_status": event.normalized_status,
        "message": event.message,
        "provider_payload": event.provider_payload or {},
        "created_at": _utc_iso(event.created_at),
    }


def serialize_retry_decision(decision: models.ProviderRetryDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "user_id": decision.user_id,
        "integration_id": decision.integration_id,
        "account_id": decision.account_id,
        "paper_order_id": decision.paper_order_id,
        "provider_order_id": decision.provider_order_id,
        "client_order_id": decision.client_order_id,
        "error_type": decision.error_type,
        "retryable": bool(decision.retryable),
        "requires_reconciliation": bool(decision.requires_reconciliation),
        "decision": decision.decision,
        "reason": decision.reason,
        "metadata": decision.decision_metadata or {},
        "created_at": _utc_iso(decision.created_at),
    }


class ReconciliationService:
    def create_retry_decision(
        self,
        db: Session,
        *,
        user_id: int,
        error: Any,
        integration_id: int | None = None,
        account_id: str | None = None,
        paper_order_id: int | None = None,
        provider_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> models.ProviderRetryDecision:
        classification = classify_provider_error(error)
        decision_value = "retry_blocked_reconcile_first" if classification.requires_reconciliation else (
            "retry_allowed_manual_worker_only" if classification.retryable else "retry_blocked"
        )
        decision = models.ProviderRetryDecision(
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            paper_order_id=paper_order_id,
            provider_order_id=provider_order_id,
            client_order_id=client_order_id,
            error_type=classification.error_type,
            retryable=1 if classification.retryable else 0,
            requires_reconciliation=1 if classification.requires_reconciliation else 0,
            decision=decision_value,
            reason=classification.reason,
            decision_metadata={"raw_error": str(error)},
        )
        db.add(decision)
        db.flush()
        log_event(
            "reconciliation",
            "retry_decision_recorded",
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            error_type=classification.error_type,
            retryable=classification.retryable,
            requires_reconciliation=classification.requires_reconciliation,
            decision=decision_value,
        )
        return decision

    def mark_account_reconciliation_required(
        self,
        db: Session,
        *,
        run: models.ProviderReconciliationRun,
        reason: str,
    ) -> models.AccountReconciliationLock:
        lock = models.AccountReconciliationLock(
            user_id=run.user_id,
            integration_id=run.integration_id,
            account_id=run.account_id,
            active=1,
            reason=reason,
            run_id=run.id,
        )
        db.add(lock)
        db.flush()
        return lock

    def reconcile_order(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None,
        account_id: str | None,
        provider: Any,
        symbol: str | None = None,
        provider_order_id: str | None = None,
        client_order_id: str | None = None,
        expected_status: str | None = None,
    ) -> models.ProviderReconciliationRun:
        run = models.ProviderReconciliationRun(
            user_id=user_id,
            integration_id=integration_id,
            account_id=account_id,
            symbol=symbol,
            provider_order_id=provider_order_id,
            client_order_id=client_order_id,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.flush()
        try:
            if not hasattr(provider, "get_order_status"):
                raise RuntimeError("Provider does not support order status lookup.")
            payload = provider.get_order_status(
                provider_order_id=provider_order_id,
                client_order_id=client_order_id,
                account_id=account_id,
                symbol=symbol,
            )
            provider_status = payload.get("status") if isinstance(payload, dict) else str(payload)
            normalized = normalize_provider_order_status(provider_status)
            status_matches = expected_status is None or expected_status == normalized
            run.status = "succeeded" if status_matches else "mismatch"
            run.summary = {
                "provider_status": provider_status,
                "normalized_status": normalized,
                "expected_status": expected_status,
                "status_matches": status_matches,
                "terminal": normalized in TERMINAL_NORMALIZED_STATUSES,
            }
            db.add(
                models.ProviderReconciliationEvent(
                    run_id=run.id,
                    user_id=user_id,
                    event_type="provider_order_status",
                    provider_status=provider_status,
                    normalized_status=normalized,
                    message="Provider order status reconciled." if status_matches else "Provider order status mismatch.",
                    provider_payload=payload if isinstance(payload, dict) else {"value": str(payload)},
                )
            )
            if not status_matches:
                self.mark_account_reconciliation_required(
                    db,
                    run=run,
                    reason="Provider order status differs from app state.",
                )
        except Exception as exc:
            classification = classify_provider_error(exc)
            run.status = "failed"
            run.summary = {
                "error_type": classification.error_type,
                "requires_reconciliation": classification.requires_reconciliation,
                "reason": classification.reason,
            }
            db.add(
                models.ProviderReconciliationEvent(
                    run_id=run.id,
                    user_id=user_id,
                    event_type="provider_lookup_failed",
                    normalized_status="timeout_unknown",
                    message=classification.reason,
                    provider_payload={"error_type": classification.error_type},
                )
            )
            self.create_retry_decision(
                db,
                user_id=user_id,
                integration_id=integration_id,
                account_id=account_id,
                error=exc,
                provider_order_id=provider_order_id,
                client_order_id=client_order_id,
            )
            if classification.requires_reconciliation:
                self.mark_account_reconciliation_required(db, run=run, reason=classification.reason)
        finally:
            run.completed_at = datetime.utcnow()
            db.flush()
            log_event(
                "reconciliation",
                "reconciliation_run_completed",
                user_id=user_id,
                integration_id=integration_id,
                account_id=account_id,
                run_id=run.id,
                status=run.status,
            )
        return run

    def assert_no_reconciliation_lock(
        self,
        db: Session,
        *,
        user_id: int,
        integration_id: int | None = None,
        account_id: str | None = None,
    ) -> None:
        query = db.query(models.AccountReconciliationLock).filter(
            models.AccountReconciliationLock.user_id == user_id,
            models.AccountReconciliationLock.active == 1,
        )
        if integration_id is None:
            query = query.filter(models.AccountReconciliationLock.integration_id.is_(None))
        else:
            query = query.filter(models.AccountReconciliationLock.integration_id == integration_id)
        if account_id is None:
            query = query.filter(models.AccountReconciliationLock.account_id.is_(None))
        else:
            query = query.filter(models.AccountReconciliationLock.account_id == account_id)
        lock = query.first()
        if lock:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=lock.reason,
                headers={"X-Readiness-Blocker": "reconciliation_required"},
            )


reconciliation_service = ReconciliationService()
