from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import beta_access_service, database, models
from app.observability import redact


PLAN_BETA = "beta"
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_LIVE_READY = "live_ready_future"

FEATURE_PAPER_BETA = "paper_beta_access"
FEATURE_BASIC_PAPER = "basic_paper_trading"
FEATURE_ADVANCED_PAPER = "advanced_paper_trading"
FEATURE_STRATEGY_AUTOMATION = "strategy_automation"
FEATURE_ANALYTICS = "beta_analytics"
FEATURE_LIVE_TRADING = "live_trading"

BILLING_DISABLED_REASON = "billing_disabled_for_invite_only_beta"

PLAN_CATALOG = [
    {
        "code": PLAN_BETA,
        "name": "Invite-only Paper Beta",
        "description": "Free beta access for invited paper-trading users. Billing and live trading are disabled.",
        "status": "active",
        "billing_mode": "disabled",
        "monthly_price_cents": 0,
        "features": [FEATURE_PAPER_BETA, FEATURE_BASIC_PAPER, FEATURE_STRATEGY_AUTOMATION, FEATURE_ANALYTICS],
        "display_metadata": {"badge": "Beta", "requires_invite": True, "billing_required": False},
        "sort_order": 10,
    },
    {
        "code": PLAN_FREE,
        "name": "Free Paper",
        "description": "Future free paper-trading plan placeholder. Not required for beta access.",
        "status": "active",
        "billing_mode": "disabled",
        "monthly_price_cents": 0,
        "features": [FEATURE_BASIC_PAPER],
        "display_metadata": {"badge": "Free", "requires_invite": False, "billing_required": False},
        "sort_order": 20,
    },
    {
        "code": PLAN_PRO,
        "name": "Pro Paper",
        "description": "Future paid paper-trading plan placeholder. Checkout is not enabled during beta.",
        "status": "inactive",
        "billing_mode": "future_stripe",
        "monthly_price_cents": None,
        "features": [FEATURE_BASIC_PAPER, FEATURE_ADVANCED_PAPER, FEATURE_STRATEGY_AUTOMATION, FEATURE_ANALYTICS],
        "display_metadata": {"badge": "Future", "requires_invite": False, "billing_required": True},
        "sort_order": 30,
    },
    {
        "code": PLAN_LIVE_READY,
        "name": "Live-ready Future",
        "description": "Future packaging placeholder only. It does not make live trading available.",
        "status": "future",
        "billing_mode": "future_stripe",
        "monthly_price_cents": None,
        "features": [FEATURE_ADVANCED_PAPER],
        "display_metadata": {
            "badge": "Future",
            "requires_live_readiness": True,
            "billing_required": True,
            "live_trading_available": False,
        },
        "sort_order": 40,
    },
]

PLAN_FEATURES = {plan["code"]: set(plan["features"]) for plan in PLAN_CATALOG}
LIVE_DISABLED_RESPONSE = {
    "allowed": False,
    "reason_code": "live_trading_disabled",
    "detail": "Live trading remains disabled and cannot be enabled by any subscription or entitlement.",
}


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def billing_status() -> dict[str, Any]:
    return {
        "billing_enabled": False,
        "checkout_enabled": False,
        "payment_collection_enabled": False,
        "provider": "stripe",
        "provider_configured": bool(database.APP_CONFIG.stripe_publishable_key and database.APP_CONFIG.stripe_secret_key),
        "reason_code": BILLING_DISABLED_REASON,
        "live_trading_enabled": False,
    }


def ensure_default_plans(db: Session) -> None:
    now = datetime.utcnow()
    for plan in PLAN_CATALOG:
        record = db.query(models.PlanTier).filter(models.PlanTier.code == plan["code"]).first()
        if record:
            record.name = plan["name"]
            record.description = plan["description"]
            record.status = plan["status"]
            record.billing_mode = plan["billing_mode"]
            record.monthly_price_cents = plan["monthly_price_cents"]
            record.currency = "usd"
            record.features = list(plan["features"])
            record.display_metadata = dict(plan["display_metadata"])
            record.sort_order = plan["sort_order"]
            record.updated_at = now
            continue
        db.add(
            models.PlanTier(
                code=plan["code"],
                name=plan["name"],
                description=plan["description"],
                status=plan["status"],
                billing_mode=plan["billing_mode"],
                monthly_price_cents=plan["monthly_price_cents"],
                currency="usd",
                features=list(plan["features"]),
                display_metadata=dict(plan["display_metadata"]),
                sort_order=plan["sort_order"],
                created_at=now,
                updated_at=now,
            )
        )
    db.flush()


def serialize_plan(plan: models.PlanTier) -> dict[str, Any]:
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "billing_mode": plan.billing_mode,
        "monthly_price_cents": plan.monthly_price_cents,
        "currency": plan.currency,
        "features": plan.features or [],
        "display_metadata": plan.display_metadata or {},
        "sort_order": plan.sort_order,
        "checkout_enabled": False,
    }


def list_plans(db: Session) -> list[dict[str, Any]]:
    ensure_default_plans(db)
    plans = db.query(models.PlanTier).order_by(models.PlanTier.sort_order.asc()).all()
    return [serialize_plan(plan) for plan in plans]


def _subscription_for_user(db: Session, user_id: int) -> models.UserSubscriptionStatus | None:
    return db.query(models.UserSubscriptionStatus).filter(models.UserSubscriptionStatus.user_id == user_id).first()


def ensure_user_subscription_status(
    db: Session,
    *,
    user: models.User,
    plan_code: str | None = None,
    status_value: str | None = None,
    source: str | None = None,
    assigned_by_user_id: int | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> models.UserSubscriptionStatus:
    ensure_default_plans(db)
    beta_payload = beta_access_service.beta_status_payload(db, user)
    default_plan = PLAN_BETA if beta_payload["active"] else PLAN_FREE
    selected_plan = plan_code or default_plan
    if not db.query(models.PlanTier).filter(models.PlanTier.code == selected_plan).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown plan code.")
    selected_status = status_value or ("beta" if selected_plan == PLAN_BETA else "free")
    now = datetime.utcnow()
    record = _subscription_for_user(db, user.id)
    if record:
        if plan_code is not None:
            record.plan_code = selected_plan
        if status_value is not None:
            record.status = selected_status
        if source is not None:
            record.source = source
        if assigned_by_user_id is not None:
            record.assigned_by_user_id = assigned_by_user_id
        if reason is not None:
            record.reason = reason
        if metadata is not None:
            record.subscription_metadata = redact(metadata)
        record.billing_status = "not_required"
        record.updated_at = now
        return record
    record = models.UserSubscriptionStatus(
        user_id=user.id,
        plan_code=selected_plan,
        status=selected_status,
        billing_status="not_required",
        source=source or ("beta_invite" if selected_plan == PLAN_BETA else "default_free"),
        assigned_by_user_id=assigned_by_user_id,
        reason=reason,
        subscription_metadata=redact(metadata or {}),
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()
    return record


def serialize_subscription(record: models.UserSubscriptionStatus | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": record.id,
        "user_id": record.user_id,
        "plan_code": record.plan_code,
        "status": record.status,
        "billing_status": record.billing_status,
        "source": record.source,
        "stripe_customer_configured": bool(record.stripe_customer_id),
        "stripe_subscription_configured": bool(record.stripe_subscription_id),
        "reason": record.reason,
        "started_at": _utc_iso(record.started_at),
        "current_period_end": _utc_iso(record.current_period_end),
        "canceled_at": _utc_iso(record.canceled_at),
        "updated_at": _utc_iso(record.updated_at),
    }


def explicit_entitlements(db: Session, *, user_id: int) -> dict[str, models.UserEntitlement]:
    rows = (
        db.query(models.UserEntitlement)
        .filter(models.UserEntitlement.user_id == user_id)
        .filter(models.UserEntitlement.allowed == 1)
        .all()
    )
    now = datetime.utcnow()
    return {row.feature_code: row for row in rows if row.expires_at is None or row.expires_at > now}


def effective_feature_codes(db: Session, *, user: models.User) -> set[str]:
    subscription = ensure_user_subscription_status(db, user=user)
    features = set(PLAN_FEATURES.get(subscription.plan_code, set()))
    if not beta_access_service.beta_status_payload(db, user)["active"] and subscription.plan_code == PLAN_BETA:
        features.discard(FEATURE_PAPER_BETA)
    features.update(explicit_entitlements(db, user_id=user.id).keys())
    features.discard(FEATURE_LIVE_TRADING)
    return features


def evaluate_entitlement(db: Session, *, user: models.User, feature_code: str) -> dict[str, Any]:
    normalized = feature_code.strip().lower()
    if normalized == FEATURE_LIVE_TRADING:
        return {**LIVE_DISABLED_RESPONSE, "feature_code": normalized, "live_trading_enabled": False}
    features = effective_feature_codes(db, user=user)
    if normalized in features:
        return {
            "feature_code": normalized,
            "allowed": True,
            "reason_code": "entitled",
            "detail": "Feature is available for the current beta subscription state.",
            "live_trading_enabled": False,
        }
    beta_payload = beta_access_service.beta_status_payload(db, user)
    reason = "beta_access_required" if normalized == FEATURE_PAPER_BETA and not beta_payload["active"] else "entitlement_required"
    return {
        "feature_code": normalized,
        "allowed": False,
        "reason_code": reason,
        "detail": "Feature is unavailable for the current subscription or beta access state.",
        "live_trading_enabled": False,
    }


def status_payload(db: Session, *, user: models.User) -> dict[str, Any]:
    subscription = ensure_user_subscription_status(db, user=user)
    features = sorted(effective_feature_codes(db, user=user))
    checks = [
        evaluate_entitlement(db, user=user, feature_code=FEATURE_PAPER_BETA),
        evaluate_entitlement(db, user=user, feature_code=FEATURE_BASIC_PAPER),
        evaluate_entitlement(db, user=user, feature_code=FEATURE_STRATEGY_AUTOMATION),
        evaluate_entitlement(db, user=user, feature_code=FEATURE_LIVE_TRADING),
    ]
    return {
        "subscription": serialize_subscription(subscription),
        "entitlements": features,
        "feature_gates": checks,
        "billing": billing_status(),
        "plans": list_plans(db),
        "live_trading_enabled": False,
    }


def assign_subscription_status(
    db: Session,
    *,
    target_user: models.User,
    admin_user: models.User,
    plan_code: str,
    status_value: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if status_value not in {"beta", "free", "pro", "suspended"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported subscription status.")
    record = ensure_user_subscription_status(
        db,
        user=target_user,
        plan_code=plan_code,
        status_value=status_value,
        source="admin_assignment",
        assigned_by_user_id=admin_user.id,
        reason=reason,
        metadata={"admin_assignment": True},
    )
    db.flush()
    return status_payload(db, user=target_user)


def grant_entitlement(
    db: Session,
    *,
    target_user: models.User,
    feature_code: str,
    admin_user: models.User,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized = feature_code.strip().lower()
    if normalized == FEATURE_LIVE_TRADING:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=LIVE_DISABLED_RESPONSE["detail"])
    existing = (
        db.query(models.UserEntitlement)
        .filter(
            models.UserEntitlement.user_id == target_user.id,
            models.UserEntitlement.feature_code == normalized,
            models.UserEntitlement.source == "admin_assignment",
        )
        .first()
    )
    now = datetime.utcnow()
    if existing:
        existing.allowed = 1
        existing.reason = reason
        existing.updated_at = now
    else:
        db.add(
            models.UserEntitlement(
                user_id=target_user.id,
                feature_code=normalized,
                source="admin_assignment",
                allowed=1,
                reason=reason,
                entitlement_metadata={"assigned_by_user_id": admin_user.id},
                created_at=now,
                updated_at=now,
            )
        )
    db.flush()
    return status_payload(db, user=target_user)
