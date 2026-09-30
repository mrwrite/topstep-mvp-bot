import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import database, legal_service, models
from .auth_routes import get_current_user_model

router = APIRouter()


class LegalAcceptanceRequest(BaseModel):
    accept_terms_of_service: bool
    accept_privacy_policy: bool
    accept_paper_trading_disclosure: bool
    metadata: dict[str, Any] | None = None


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ip_hash(request: Request | None) -> str | None:
    if not request or not request.client:
        return None
    return _hash_value(request.client.host)


def _user_agent_summary(request: Request | None) -> str | None:
    if not request:
        return None
    user_agent = request.headers.get("user-agent")
    if not user_agent:
        return None
    return user_agent[:180]


def require_current_legal_acceptance(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
) -> models.User:
    status_payload = legal_service.acceptance_status(db, current_user)
    if not status_payload["all_required_accepted"]:
        first_blocker = status_payload["blockers"][0]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Current legal acceptance is required before beta access.",
                "blockers": status_payload["blockers"],
            },
            headers={"X-Readiness-Blocker": first_blocker["code"]},
        )
    return current_user


@router.get("/documents")
def get_required_documents(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return legal_service.acceptance_status(db, current_user)


@router.get("/acceptances")
def get_acceptance_history(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return {"acceptances": legal_service.acceptance_history(db, current_user)}


@router.post("/acceptances")
def accept_documents(
    request_body: LegalAcceptanceRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    missing_confirmations = []
    if not request_body.accept_terms_of_service:
        missing_confirmations.append("terms_of_service")
    if not request_body.accept_privacy_policy:
        missing_confirmations.append("privacy_policy")
    if not request_body.accept_paper_trading_disclosure:
        missing_confirmations.append("paper_trading_disclosure")
    if missing_confirmations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "All current required legal documents must be explicitly accepted.",
                "missing_confirmations": missing_confirmations,
            },
        )
    payload = legal_service.accept_required_documents(
        db,
        current_user,
        ip_hash=_ip_hash(request),
        user_agent_summary=_user_agent_summary(request),
        metadata=request_body.metadata,
    )
    db.commit()
    return payload


@router.get("/beta-access-check")
def beta_access_check(
    current_user: models.User = Depends(require_current_legal_acceptance),
):
    return {
        "legal_acceptance_complete": True,
        "user_id": current_user.id,
        "live_trading_enabled": False,
    }
