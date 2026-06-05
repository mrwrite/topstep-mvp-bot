from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import database, models
from app.observability import redact


SCHEMA_VERSION = "beta-analytics-v1"

EVENT_CATEGORIES = {
    "registration_started": "onboarding",
    "registration_completed": "onboarding",
    "email_verification_sent": "onboarding",
    "email_verification_completed": "onboarding",
    "legal_acceptance_completed": "onboarding",
    "invite_redeemed": "onboarding",
    "waitlist_joined": "onboarding",
    "onboarding_milestone_completed": "onboarding",
    "integration_created": "activation",
    "integration_activated": "activation",
    "account_contract_selected": "activation",
    "paper_session_started": "paper_trading",
    "paper_session_stopped": "paper_trading",
    "paper_order_created": "paper_trading",
    "paper_order_blocked": "paper_trading",
    "paper_order_filled": "paper_trading",
    "kill_switch_activated": "safety",
    "support_request_submitted": "support",
    "strategy_config_created": "strategy",
    "strategy_signal_created": "strategy",
    "beta_launch_gate_evaluated": "launch_gate",
}

FUNNEL_STEPS = [
    ("registration_completed", "Registered"),
    ("email_verification_completed", "Email verified"),
    ("legal_acceptance_completed", "Legal accepted"),
    ("invite_redeemed", "Beta activated"),
    ("integration_created", "Integration setup"),
    ("account_contract_selected", "Account and contract selected"),
    ("paper_session_started", "First paper session"),
]


def user_safe_id(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    raw = f"{database.APP_CONFIG.secret_key}:{user_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _normalize_event_name(event_name: str) -> tuple[str, str]:
    normalized = event_name.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in EVENT_CATEGORIES:
        return normalized, EVENT_CATEGORIES[normalized]
    return "unknown_event", "quarantine"


def _parse_date(value: str | None, *, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        parsed = date.fromisoformat(value)
        return datetime.combine(parsed, datetime.min.time())


def date_window(start: str | None = None, end: str | None = None) -> tuple[datetime, datetime]:
    end_dt = _parse_date(end, default=datetime.utcnow())
    start_dt = _parse_date(start, default=end_dt - timedelta(days=30))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    return start_dt, end_dt


def sentry_status() -> dict[str, Any]:
    dsn = database.APP_CONFIG.sentry_dsn
    enabled = database.APP_CONFIG.sentry_enabled
    if not enabled:
        return {
            "provider": "sentry",
            "enabled": False,
            "status": "disabled",
            "reason": "SENTRY_ENABLED is false.",
            "environment": database.APP_CONFIG.sentry_environment,
            "release": database.APP_CONFIG.sentry_release,
        }
    if not dsn:
        return {
            "provider": "sentry",
            "enabled": False,
            "status": "disabled",
            "reason": "SENTRY_DSN is not configured.",
            "environment": database.APP_CONFIG.sentry_environment,
            "release": database.APP_CONFIG.sentry_release,
        }
    parsed = urlparse(dsn)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "provider": "sentry",
            "enabled": False,
            "status": "invalid_config",
            "reason": "SENTRY_DSN is invalid; remote error tracking is disabled.",
            "environment": database.APP_CONFIG.sentry_environment,
            "release": database.APP_CONFIG.sentry_release,
        }
    return {
        "provider": "sentry",
        "enabled": True,
        "status": "configured",
        "environment": database.APP_CONFIG.sentry_environment,
        "release": database.APP_CONFIG.sentry_release,
    }


def analytics_status() -> dict[str, Any]:
    return {
        "provider": database.APP_CONFIG.analytics_provider,
        "enabled": database.APP_CONFIG.analytics_enabled,
        "status": "enabled" if database.APP_CONFIG.analytics_enabled else "disabled",
        "environment": database.APP_CONFIG.app_env,
        "schema_version": SCHEMA_VERSION,
        "external_provider_required": False,
        "retention_days": database.APP_CONFIG.analytics_retention_days,
    }


def capture_event(
    db: Session,
    *,
    event_name: str,
    user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "api",
) -> models.AnalyticsEvent | None:
    if not database.APP_CONFIG.analytics_enabled:
        return None
    normalized, category = _normalize_event_name(event_name)
    safe_metadata = redact(metadata or {})
    if normalized == "unknown_event":
        safe_metadata = {"original_event_name": event_name, "metadata": safe_metadata}
    event = models.AnalyticsEvent(
        user_id=user_id,
        user_safe_id=user_safe_id(user_id),
        event_name=normalized,
        event_category=category,
        schema_version=SCHEMA_VERSION,
        environment=database.APP_CONFIG.app_env,
        source=source,
        provider="local",
        event_metadata=safe_metadata,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def serialize_event(event: models.AnalyticsEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_name": event.event_name,
        "event_category": event.event_category,
        "schema_version": event.schema_version,
        "environment": event.environment,
        "source": event.source,
        "provider": event.provider,
        "user_safe_id": event.user_safe_id,
        "metadata": event.event_metadata or {},
        "created_at": event.created_at.isoformat() + "Z" if event.created_at else None,
    }


def event_counts(db: Session, *, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        db.query(models.AnalyticsEvent.event_name, func.count(models.AnalyticsEvent.id))
        .filter(models.AnalyticsEvent.created_at >= start, models.AnalyticsEvent.created_at <= end)
        .group_by(models.AnalyticsEvent.event_name)
        .all()
    )
    return {name: int(count) for name, count in rows}


def distinct_event_users(db: Session, *, event_name: str, start: datetime, end: datetime) -> int:
    return int(
        db.query(func.count(func.distinct(models.AnalyticsEvent.user_safe_id)))
        .filter(
            models.AnalyticsEvent.event_name == event_name,
            models.AnalyticsEvent.user_safe_id.isnot(None),
            models.AnalyticsEvent.created_at >= start,
            models.AnalyticsEvent.created_at <= end,
        )
        .scalar()
        or 0
    )


def _conversion(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def onboarding_funnel(db: Session, *, start: datetime, end: datetime) -> dict[str, Any]:
    counts = event_counts(db, start=start, end=end)
    steps = []
    prior = None
    first = counts.get(FUNNEL_STEPS[0][0], 0)
    for code, label in FUNNEL_STEPS:
        count = counts.get(code, 0)
        steps.append(
            {
                "code": code,
                "label": label,
                "count": count,
                "conversion_from_previous": 1.0 if prior is None and count else _conversion(count, prior or 0),
                "conversion_from_registration": _conversion(count, first),
            }
        )
        prior = count
    return {
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "steps": steps,
        "privacy": {"aggregated": True, "user_level_data": False},
    }


def activation_retention(db: Session, *, start: datetime, end: datetime) -> dict[str, Any]:
    paper_orders = (
        db.query(models.PaperOrder.user_id, models.PaperOrder.created_at)
        .filter(models.PaperOrder.created_at >= start, models.PaperOrder.created_at <= end)
        .all()
    )
    user_days: dict[int, set[str]] = defaultdict(set)
    for user_id, created_at in paper_orders:
        user_days[user_id].add(created_at.date().isoformat())
    activated_users = len(user_days)
    returning_users = sum(1 for days in user_days.values() if len(days) >= 2)
    active_event_users = distinct_event_users(db, event_name="paper_session_started", start=start, end=end)
    cohort = {
        "window": "selected_range",
        "activated_users": activated_users,
        "returning_users": returning_users,
        "retention_rate": _conversion(returning_users, activated_users),
    }
    return {
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "activated_users": activated_users,
        "returning_users": returning_users,
        "active_paper_users": max(activated_users, active_event_users),
        "retention_cohorts": [cohort] if activated_users else [],
        "privacy": {"aggregated": True, "minimum_group_size": 1, "user_level_data": False},
    }


def _count_between(db: Session, model: type, field: Any, *, start: datetime, end: datetime) -> int:
    return int(db.query(func.count(model.id)).filter(field >= start, field <= end).scalar() or 0)


def _top_readiness_blockers(db: Session, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = (
        db.query(models.LaunchGateEvaluation.gate_results)
        .filter(models.LaunchGateEvaluation.created_at >= start, models.LaunchGateEvaluation.created_at <= end)
        .all()
    )
    counter: Counter[str] = Counter()
    for (gate_results,) in rows:
        if isinstance(gate_results, list):
            iterable = gate_results
        elif isinstance(gate_results, dict):
            iterable = gate_results.get("gates") or gate_results.get("results") or []
        else:
            iterable = []
        for item in iterable:
            if not isinstance(item, dict):
                continue
            passed = item.get("passed")
            if passed is False:
                counter[str(item.get("code") or "unknown")] += 1
    return [{"code": code, "count": count} for code, count in counter.most_common(10)]


def engagement_metrics(db: Session, *, start: datetime, end: datetime) -> dict[str, Any]:
    counts = event_counts(db, start=start, end=end)
    paper_orders = (
        db.query(models.PaperOrder)
        .filter(models.PaperOrder.created_at >= start, models.PaperOrder.created_at <= end)
        .all()
    )
    blocked_statuses = {"risk_blocked", "rejected", "failed", "reconciliation_required"}
    blocked_orders = sum(1 for order in paper_orders if order.status in blocked_statuses)
    risk_blocks = int(
        db.query(func.count(models.RiskDecision.id))
        .filter(
            models.RiskDecision.allowed == 0,
            models.RiskDecision.created_at >= start,
            models.RiskDecision.created_at <= end,
        )
        .scalar()
        or 0
    )
    return {
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "paper_sessions": counts.get("paper_session_started", 0),
        "paper_orders": len(paper_orders),
        "blocked_orders": blocked_orders + risk_blocks + counts.get("paper_order_blocked", 0),
        "filled_orders": sum(1 for order in paper_orders if order.status == "filled"),
        "kill_switch_activations": _count_between(db, models.KillSwitch, models.KillSwitch.created_at, start=start, end=end),
        "strategy_signals": _count_between(db, models.StrategySignal, models.StrategySignal.created_at, start=start, end=end),
        "support_requests": _count_between(db, models.SupportRequest, models.SupportRequest.created_at, start=start, end=end),
        "top_readiness_blockers": _top_readiness_blockers(db, start=start, end=end),
        "profitability_claims": False,
        "live_trading_enabled": False,
        "privacy": {"aggregated": True, "user_level_data": False},
    }


def analytics_summary(db: Session, *, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "status": {
            "analytics": analytics_status(),
            "error_tracking": sentry_status(),
            "live_trading_enabled": False,
        },
        "onboarding_funnel": onboarding_funnel(db, start=start, end=end),
        "activation_retention": activation_retention(db, start=start, end=end),
        "engagement": engagement_metrics(db, start=start, end=end),
    }
