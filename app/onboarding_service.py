from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from . import analytics_service, beta_access_service, legal_service, models
from .observability import redact

MANUAL_MILESTONES = {
    "paper_only_reviewed",
    "integration_walkthrough_viewed",
    "risk_controls_reviewed",
    "strategy_setup_reviewed",
    "demo_reviewed",
}

HELP_TOPICS = [
    {
        "slug": "paper-only-status",
        "title": "Paper-only beta",
        "summary": "The beta uses simulated paper orders. Live trading and billing are disabled.",
    },
    {
        "slug": "account-setup",
        "title": "Account setup",
        "summary": "Verify email, accept required documents, and confirm invite-only beta access.",
    },
    {
        "slug": "integrations",
        "title": "Broker-neutral integrations",
        "summary": "Use integrations for paper context, account lookup, contract lookup, and signal intake.",
    },
    {
        "slug": "risk-controls",
        "title": "Risk controls",
        "summary": "Review quantity limits, kill switch state, and paper ledger status before sessions.",
    },
    {
        "slug": "order-states",
        "title": "Paper order states",
        "summary": "Paper orders are simulated and tracked for status, fills, positions, and ledger entries.",
    },
    {
        "slug": "strategy-assumptions",
        "title": "Strategy assumptions",
        "summary": "Strategy signals are paper-only and do not guarantee live performance.",
    },
    {
        "slug": "support-escalation",
        "title": "Support escalation",
        "summary": "Use the support form with relevant order, integration, or session context.",
    },
]


def _get_or_create_progress(db: Session, user_id: int) -> models.OnboardingProgress:
    progress = db.query(models.OnboardingProgress).filter(models.OnboardingProgress.user_id == user_id).first()
    if progress:
        return progress
    progress = models.OnboardingProgress(user_id=user_id, milestones={})
    db.add(progress)
    db.flush()
    return progress


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _manual_done(progress: models.OnboardingProgress, code: str) -> bool:
    milestones = progress.milestones or {}
    return bool(milestones.get(code, {}).get("completed_at"))


def mark_milestone(db: Session, *, user: models.User, code: str) -> dict[str, Any]:
    if code not in MANUAL_MILESTONES:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown onboarding milestone.")
    progress = _get_or_create_progress(db, user.id)
    milestones = dict(progress.milestones or {})
    milestones.setdefault(code, {"completed_at": _iso(datetime.utcnow()), "source": "user"})
    progress.milestones = milestones
    progress.updated_at = datetime.utcnow()
    db.flush()
    analytics_service.capture_event(
        db,
        event_name="onboarding_milestone_completed",
        user_id=user.id,
        metadata={"milestone": code},
        source="onboarding",
    )
    return onboarding_status(db, user)


def onboarding_status(db: Session, user: models.User) -> dict[str, Any]:
    progress = _get_or_create_progress(db, user.id)
    legal = legal_service.acceptance_status(db, user)
    beta = beta_access_service.beta_status_payload(db, user)
    integration = (
        db.query(models.PlatformIntegration)
        .filter(models.PlatformIntegration.user_id == user.id, models.PlatformIntegration.status == "active")
        .order_by(models.PlatformIntegration.updated_at.desc())
        .first()
    )
    has_account = bool(
        integration
        and integration.integration_metadata
        and (
            integration.integration_metadata.get("account_id")
            or integration.integration_metadata.get("accountId")
        )
    )
    has_risk_settings = db.query(models.RiskSettings).filter(models.RiskSettings.user_id == user.id).first() is not None
    has_strategy_config = db.query(models.StrategyConfig).filter(models.StrategyConfig.user_id == user.id).first() is not None
    has_paper_order = db.query(models.PaperOrder).filter(models.PaperOrder.user_id == user.id).first() is not None

    checklist = [
        {
            "code": "email_verified",
            "label": "Verify email",
            "complete": user.email_verified_at is not None,
            "required": True,
            "detail": "Verify your email before beta access.",
        },
        {
            "code": "legal_acceptance",
            "label": "Accept beta disclosures",
            "complete": legal["all_required_accepted"],
            "required": True,
            "detail": "Accept terms, privacy, and paper-trading disclosure.",
        },
        {
            "code": "beta_access",
            "label": "Confirm beta access",
            "complete": beta["active"],
            "required": True,
            "detail": "Redeem an invite or receive waitlist approval.",
        },
        {
            "code": "paper_only_reviewed",
            "label": "Review paper-only status",
            "complete": _manual_done(progress, "paper_only_reviewed"),
            "required": True,
            "detail": "Live trading remains disabled. Paper results are simulated.",
        },
        {
            "code": "integration_walkthrough_viewed",
            "label": "Review integration setup",
            "complete": _manual_done(progress, "integration_walkthrough_viewed"),
            "required": False,
            "detail": "Understand provider capabilities, credential safety, account and contract selection.",
        },
        {
            "code": "integration_created",
            "label": "Create or select integration",
            "complete": integration is not None,
            "required": True,
            "detail": "Add an active broker or signal integration for paper context.",
        },
        {
            "code": "account_contract_selected",
            "label": "Select account and contract",
            "complete": has_account,
            "required": True,
            "detail": "Select a paper account and provider-validated contract where available.",
        },
        {
            "code": "risk_controls_reviewed",
            "label": "Review risk controls",
            "complete": _manual_done(progress, "risk_controls_reviewed") or has_risk_settings,
            "required": True,
            "detail": "Review max quantity, kill switch, and paper ledger readiness.",
        },
        {
            "code": "strategy_setup_reviewed",
            "label": "Review strategy setup",
            "complete": _manual_done(progress, "strategy_setup_reviewed") or has_strategy_config,
            "required": False,
            "detail": "Review RSI thresholds, assumptions, and signal-only versus paper-auto mode.",
        },
        {
            "code": "first_paper_session",
            "label": "Start first paper session",
            "complete": has_paper_order,
            "required": False,
            "detail": "Start a paper session or load demo data to inspect simulated orders.",
        },
    ]
    required_complete = all(item["complete"] for item in checklist if item["required"])
    if required_complete and progress.completed_at is None:
        progress.completed_at = datetime.utcnow()
        progress.updated_at = progress.completed_at
        db.flush()
    return {
        "checklist": checklist,
        "required_complete": required_complete,
        "completed_at": _iso(progress.completed_at),
        "first_seen_at": _iso(progress.first_seen_at),
        "live_trading_enabled": False,
        "guidance": {
            "integration_walkthrough": [
                "Choose the provider that matches your paper workflow.",
                "Store only credentials required for paper context or signal intake.",
                "Set one integration active so account and contract lookup use the selected provider.",
                "Roadmap providers can be saved for planning but cannot execute trades.",
            ],
            "paper_trading_setup": [
                "Confirm paper-only mode.",
                "Select an active integration, paper account, and contract.",
                "Review risk settings and kill switch state.",
                "Start signal-only mode first, then paper-auto only when comfortable.",
            ],
            "strategy_setup": [
                "Review RSI buy/sell thresholds.",
                "Backtests and paper results are not predictive.",
                "Strategy output remains paper-only.",
            ],
        },
    }


def sanitize_support_message(message: str) -> str:
    sanitized = re.sub(
        r"(?i)\b(api[_-]?key|secret|token|password|credential)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        message,
    )
    return str(redact({"message": sanitized})["message"])


def create_support_request(
    db: Session,
    *,
    user: models.User,
    category: str,
    severity: str,
    subject: str,
    message: str,
    integration_id: int | None,
    paper_order_id: int | None,
    bot_session_id: str | None,
    diagnostics: dict[str, Any] | None,
) -> models.SupportRequest:
    reference = f"sup_{uuid4().hex[:12]}"
    record = models.SupportRequest(
        user_id=user.id,
        reference_id=reference,
        category=category,
        severity=severity,
        subject=subject.strip(),
        sanitized_message=sanitize_support_message(message),
        integration_id=integration_id,
        paper_order_id=paper_order_id,
        bot_session_id=bot_session_id,
        diagnostics=redact(diagnostics or {}),
    )
    db.add(record)
    db.flush()
    analytics_service.capture_event(
        db,
        event_name="support_request_submitted",
        user_id=user.id,
        metadata={"category": category, "severity": severity},
        source="onboarding",
    )
    return record


def serialize_support_request(record: models.SupportRequest) -> dict[str, Any]:
    return {
        "id": record.id,
        "reference_id": record.reference_id,
        "category": record.category,
        "severity": record.severity,
        "status": record.status,
        "subject": record.subject,
        "created_at": _iso(record.created_at),
        "integration_id": record.integration_id,
        "paper_order_id": record.paper_order_id,
        "bot_session_id": record.bot_session_id,
    }
