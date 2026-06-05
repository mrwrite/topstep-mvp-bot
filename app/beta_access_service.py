from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import legal_service, models
from .observability import redact

BETA_STATUS_ACTIVE = "active"
BETA_STATUS_SUSPENDED = "suspended"
BETA_STATUS_EXITED = "exited"
BETA_STATUS_WAITLISTED = "waitlisted"
BETA_STATUS_NONE = "none"

INVITE_STATUS_ACTIVE = "active"
INVITE_STATUS_DISABLED = "disabled"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def new_invite_code() -> str:
    return f"BETA-{secrets.token_urlsafe(12).replace('-', '').replace('_', '').upper()[:16]}"


def serialize_invite(invite: models.BetaInviteCode, *, include_code: str | None = None) -> dict[str, Any]:
    payload = {
        "id": invite.id,
        "status": invite.status,
        "max_uses": invite.max_uses,
        "use_count": invite.use_count,
        "remaining_uses": max(invite.max_uses - invite.use_count, 0),
        "expires_at": invite.expires_at.isoformat() + "Z" if invite.expires_at else None,
        "email_restriction": invite.email_restriction,
        "campaign": invite.campaign,
        "source": invite.source,
        "notes": invite.notes,
        "created_at": invite.created_at.isoformat() + "Z" if invite.created_at else None,
        "disabled_at": invite.disabled_at.isoformat() + "Z" if invite.disabled_at else None,
    }
    if include_code:
        payload["code"] = include_code
    return payload


def serialize_waitlist(entry: models.BetaWaitlistEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "email": entry.email,
        "name": entry.name,
        "use_case": entry.use_case,
        "source": entry.source,
        "status": entry.status,
        "created_at": entry.created_at.isoformat() + "Z" if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() + "Z" if entry.updated_at else None,
        "approved_at": entry.approved_at.isoformat() + "Z" if entry.approved_at else None,
    }


def beta_status_record(db: Session, user_id: int) -> models.UserBetaStatus | None:
    return db.query(models.UserBetaStatus).filter(models.UserBetaStatus.user_id == user_id).first()


def beta_status_payload(db: Session, user: models.User) -> dict[str, Any]:
    record = beta_status_record(db, user.id)
    waitlist = (
        db.query(models.BetaWaitlistEntry)
        .filter(models.BetaWaitlistEntry.email == normalize_email(user.email))
        .first()
    )
    state = record.status if record else (BETA_STATUS_WAITLISTED if waitlist else BETA_STATUS_NONE)
    blockers = []
    if state != BETA_STATUS_ACTIVE:
        blockers.append(
            {
                "code": "beta_access_required",
                "detail": "Invite-only paper beta access is required.",
                "status": state,
            }
        )
    return {
        "status": state,
        "active": state == BETA_STATUS_ACTIVE,
        "source": record.source if record else ("waitlist" if waitlist else None),
        "activated_at": record.activated_at.isoformat() + "Z" if record and record.activated_at else None,
        "suspended_at": record.suspended_at.isoformat() + "Z" if record and record.suspended_at else None,
        "exited_at": record.exited_at.isoformat() + "Z" if record and record.exited_at else None,
        "waitlist": serialize_waitlist(waitlist) if waitlist else None,
        "blockers": blockers,
        "live_trading_enabled": False,
    }


def combined_beta_readiness(db: Session, user: models.User) -> dict[str, Any]:
    email_verified = user.email_verified_at is not None
    legal_status = legal_service.acceptance_status(db, user)
    beta_status = beta_status_payload(db, user)
    blockers = []
    if not email_verified:
        blockers.append({"code": "email_verification_required", "detail": "Verify your email before beta access."})
    blockers.extend(legal_status["blockers"])
    blockers.extend(beta_status["blockers"])
    return {
        "email_verified": email_verified,
        "legal_acceptance_complete": legal_status["all_required_accepted"],
        "beta_access": beta_status,
        "beta_access_active": beta_status["active"],
        "blockers": blockers,
        "ready": not blockers,
        "live_trading_enabled": False,
    }


def require_beta_access(db: Session, user: models.User) -> dict[str, Any]:
    readiness = combined_beta_readiness(db, user)
    if not readiness["ready"]:
        first = readiness["blockers"][0]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Paper beta access is not available.", "blockers": readiness["blockers"]},
            headers={"X-Readiness-Blocker": first["code"]},
        )
    return readiness


def create_invite(
    db: Session,
    *,
    issued_by_user_id: int,
    code: str | None,
    max_uses: int,
    expires_in_days: int | None,
    email_restriction: str | None,
    campaign: str | None,
    source: str | None,
    notes: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[models.BetaInviteCode, str]:
    if max_uses < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_uses must be at least 1.")
    raw_code = code.strip().upper() if code else new_invite_code()
    if len(raw_code) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code must be at least 8 characters.")
    code_hash = hash_invite_code(raw_code)
    existing = db.query(models.BetaInviteCode).filter(models.BetaInviteCode.code_hash == code_hash).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite code already exists.")
    invite = models.BetaInviteCode(
        code_hash=code_hash,
        status=INVITE_STATUS_ACTIVE,
        max_uses=max_uses,
        use_count=0,
        expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
        issued_by_user_id=issued_by_user_id,
        email_restriction=normalize_email(email_restriction) if email_restriction else None,
        campaign=campaign,
        source=source,
        notes=notes,
        invite_metadata=redact(metadata or {}),
    )
    db.add(invite)
    db.flush()
    return invite, raw_code


def redeem_invite(
    db: Session,
    *,
    user: models.User,
    code: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    invite = db.query(models.BetaInviteCode).filter(models.BetaInviteCode.code_hash == hash_invite_code(code)).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code is invalid or unavailable.")

    existing_redemption = (
        db.query(models.BetaInviteRedemption)
        .filter(
            models.BetaInviteRedemption.invite_code_id == invite.id,
            models.BetaInviteRedemption.user_id == user.id,
        )
        .first()
    )
    if existing_redemption:
        ensure_active_beta_status(db, user_id=user.id, source="invite", redemption_id=existing_redemption.id)
        return {"status": "already_redeemed", "beta_access": beta_status_payload(db, user)}

    now = datetime.utcnow()
    if invite.status != INVITE_STATUS_ACTIVE or invite.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code is disabled.")
    if invite.expires_at is not None and invite.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code is expired.")
    if invite.use_count >= invite.max_uses:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code is exhausted.")
    if invite.email_restriction and invite.email_restriction != normalize_email(user.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code is not valid for this email.")

    redemption = models.BetaInviteRedemption(
        invite_code_id=invite.id,
        user_id=user.id,
        email_at_redemption=normalize_email(user.email),
        redemption_metadata=redact(metadata or {}),
    )
    invite.use_count += 1
    db.add(redemption)
    db.flush()
    ensure_active_beta_status(db, user_id=user.id, source="invite", redemption_id=redemption.id)
    db.flush()
    return {"status": "redeemed", "beta_access": beta_status_payload(db, user)}


def ensure_active_beta_status(
    db: Session,
    *,
    user_id: int,
    source: str,
    redemption_id: int | None = None,
    approved_by_user_id: int | None = None,
    reason: str | None = None,
) -> models.UserBetaStatus:
    now = datetime.utcnow()
    record = beta_status_record(db, user_id)
    if record:
        record.status = BETA_STATUS_ACTIVE
        record.source = source
        record.invite_redemption_id = redemption_id or record.invite_redemption_id
        record.approved_by_user_id = approved_by_user_id or record.approved_by_user_id
        record.reason = reason or record.reason
        record.suspended_at = None
        record.exited_at = None
        record.updated_at = now
        return record
    record = models.UserBetaStatus(
        user_id=user_id,
        status=BETA_STATUS_ACTIVE,
        source=source,
        invite_redemption_id=redemption_id,
        approved_by_user_id=approved_by_user_id,
        reason=reason,
        activated_at=now,
    )
    db.add(record)
    return record


def upsert_waitlist(
    db: Session,
    *,
    email: str,
    user_id: int | None = None,
    name: str | None = None,
    use_case: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> models.BetaWaitlistEntry:
    normalized = normalize_email(email)
    if "@" not in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid email is required.")
    entry = db.query(models.BetaWaitlistEntry).filter(models.BetaWaitlistEntry.email == normalized).first()
    if entry:
        if user_id and not entry.user_id:
            entry.user_id = user_id
        if name is not None:
            entry.name = name.strip() or None
        if use_case is not None:
            entry.use_case = use_case.strip() or None
        if source is not None:
            entry.source = source.strip() or None
        entry.waitlist_metadata = redact(metadata or entry.waitlist_metadata or {})
        entry.updated_at = datetime.utcnow()
        return entry
    entry = models.BetaWaitlistEntry(
        email=normalized,
        user_id=user_id,
        name=name.strip() if name else None,
        use_case=use_case.strip() if use_case else None,
        source=source.strip() if source else None,
        status="pending",
        waitlist_metadata=redact(metadata or {}),
    )
    db.add(entry)
    return entry
