from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .observability import redact

LEGAL_DOCUMENT_TERMS = "terms_of_service"
LEGAL_DOCUMENT_PRIVACY = "privacy_policy"
LEGAL_DOCUMENT_PAPER_RISK = "paper_trading_disclosure"

CURRENT_REQUIRED_LEGAL_DOCUMENTS = [
    {
        "document_type": LEGAL_DOCUMENT_TERMS,
        "version": "terms-v1",
        "title": "Terms of Service",
        "content_markdown": (
            "# Terms of Service\n\n"
            "This beta is provided for paper-trading evaluation only. Users are responsible "
            "for their account activity and must not treat paper results as guaranteed live outcomes."
        ),
        "content_url": "/legal/terms-v1",
    },
    {
        "document_type": LEGAL_DOCUMENT_PRIVACY,
        "version": "privacy-v1",
        "title": "Privacy Policy",
        "content_markdown": (
            "# Privacy Policy\n\n"
            "The beta stores account, support, integration, and paper-trading records needed "
            "to operate the service. Secrets and credentials must not be included in support messages."
        ),
        "content_url": "/legal/privacy-v1",
    },
    {
        "document_type": LEGAL_DOCUMENT_PAPER_RISK,
        "version": "paper-risk-v1",
        "title": "Paper-Trading Risk Disclosure",
        "content_markdown": (
            "# Paper-Trading Risk Disclosure\n\n"
            "Paper trading is simulated, may not match live-market execution, and does not "
            "guarantee profit or future performance. Live trading remains disabled."
        ),
        "content_url": "/legal/paper-risk-v1",
    },
]

BLOCKER_BY_DOCUMENT_TYPE = {
    LEGAL_DOCUMENT_TERMS: "terms_acceptance_required",
    LEGAL_DOCUMENT_PRIVACY: "privacy_acceptance_required",
    LEGAL_DOCUMENT_PAPER_RISK: "paper_disclosure_required",
}


def ensure_default_legal_documents(db: Session) -> None:
    for document in CURRENT_REQUIRED_LEGAL_DOCUMENTS:
        existing = (
            db.query(models.LegalDocument)
            .filter(
                models.LegalDocument.document_type == document["document_type"],
                models.LegalDocument.version == document["version"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            models.LegalDocument(
                document_type=document["document_type"],
                version=document["version"],
                title=document["title"],
                content_markdown=document["content_markdown"],
                content_url=document["content_url"],
                required=1,
                active=1,
                effective_at=datetime.utcnow(),
                document_metadata={"source": "paper-beta-readiness-phase-2", "placeholder": True},
            )
        )
    db.flush()


def current_required_documents(db: Session) -> list[models.LegalDocument]:
    ensure_default_legal_documents(db)
    documents = (
        db.query(models.LegalDocument)
        .filter(models.LegalDocument.required == 1, models.LegalDocument.active == 1)
        .order_by(
            models.LegalDocument.document_type.asc(),
            models.LegalDocument.effective_at.desc(),
            models.LegalDocument.id.desc(),
        )
        .all()
    )
    current_by_type: dict[str, models.LegalDocument] = {}
    for document in documents:
        current_by_type.setdefault(document.document_type, document)
    return [current_by_type[key] for key in sorted(current_by_type)]


def serialize_document(document: models.LegalDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "document_type": document.document_type,
        "version": document.version,
        "title": document.title,
        "content_markdown": document.content_markdown,
        "content_url": document.content_url,
        "required": bool(document.required),
        "active": bool(document.active),
        "effective_at": document.effective_at.isoformat() + "Z" if document.effective_at else None,
        "metadata": document.document_metadata or {},
    }


def serialize_acceptance(record: models.LegalAcceptance) -> dict[str, Any]:
    return {
        "id": record.id,
        "document_type": record.document_type,
        "version": record.version,
        "accepted_at": record.accepted_at.isoformat() + "Z" if record.accepted_at else None,
        "invalidated_at": record.invalidated_at.isoformat() + "Z" if record.invalidated_at else None,
        "metadata": record.acceptance_metadata or {},
    }


def acceptance_status(db: Session, user: models.User) -> dict[str, Any]:
    documents = current_required_documents(db)
    acceptances = (
        db.query(models.LegalAcceptance)
        .filter(
            models.LegalAcceptance.user_id == user.id,
            models.LegalAcceptance.invalidated_at.is_(None),
        )
        .all()
    )
    accepted_by_document_id = {record.legal_document_id: record for record in acceptances}
    blockers = []
    document_statuses = []
    for document in documents:
        acceptance = accepted_by_document_id.get(document.id)
        accepted = acceptance is not None
        if not accepted:
            blockers.append(
                {
                    "code": BLOCKER_BY_DOCUMENT_TYPE.get(document.document_type, "legal_acceptance_required"),
                    "document_type": document.document_type,
                    "version": document.version,
                    "detail": f"{document.title} {document.version} must be accepted before beta access.",
                }
            )
        document_statuses.append(
            {
                **serialize_document(document),
                "accepted": accepted,
                "accepted_at": acceptance.accepted_at.isoformat() + "Z" if acceptance and acceptance.accepted_at else None,
            }
        )
    return {
        "documents": document_statuses,
        "blockers": blockers,
        "all_required_accepted": not blockers,
        "live_trading_enabled": False,
    }


def acceptance_history(db: Session, user: models.User) -> list[dict[str, Any]]:
    records = (
        db.query(models.LegalAcceptance)
        .filter(models.LegalAcceptance.user_id == user.id)
        .order_by(models.LegalAcceptance.accepted_at.desc(), models.LegalAcceptance.id.desc())
        .all()
    )
    return [serialize_acceptance(record) for record in records]


def accept_required_documents(
    db: Session,
    user: models.User,
    *,
    ip_hash: str | None,
    user_agent_summary: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    documents = current_required_documents(db)
    safe_metadata = redact(metadata or {})
    now = datetime.utcnow()
    for document in documents:
        existing = (
            db.query(models.LegalAcceptance)
            .filter(
                models.LegalAcceptance.user_id == user.id,
                models.LegalAcceptance.legal_document_id == document.id,
            )
            .first()
        )
        if existing:
            continue
        db.add(
            models.LegalAcceptance(
                user_id=user.id,
                legal_document_id=document.id,
                document_type=document.document_type,
                version=document.version,
                accepted_at=now,
                ip_hash=ip_hash,
                user_agent_summary=user_agent_summary,
                acceptance_metadata=safe_metadata,
            )
        )
    db.flush()
    return acceptance_status(db, user)
