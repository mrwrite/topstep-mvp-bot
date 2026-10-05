from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import database, models
from .auth_routes import get_current_user_model
from .device_telemetry import (
    DeviceTelemetryError,
    authenticate_device_credential,
    ingest_event,
    projection_for_user,
)


router = APIRouter(prefix="/device-telemetry", tags=["device-telemetry"])


@router.post("/v1/events", status_code=status.HTTP_202_ACCEPTED)
def ingest_device_event(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(database.get_db),
):
    try:
        credential = authenticate_device_credential(db, authorization)
        event_id, replayed = ingest_event(db, credential, payload)
        db.commit()
    except DeviceTelemetryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED
                            if exc.classification.startswith("device_credential")
                            else status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=exc.classification) from None
    return {
        "acknowledgement_id": event_id,
        "retry_after_seconds": 0,
        # This is observational metadata, never a command. The local client only
        # accepts the two fields above and treats any extension as a violation.
    }


@router.get("")
def read_device_telemetry(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return {
        "read_only": True,
        "execution_authority": "personal_device",
        "installations": projection_for_user(db, user_id=current_user.id),
    }
