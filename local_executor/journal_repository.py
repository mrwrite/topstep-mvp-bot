from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .journal import LocalJournalError
from .journal_models import TelemetryOutbox


def enqueue_telemetry(
    session: Session,
    *,
    installation_id: str,
    schema_version: int,
    event_type: str,
    payload: dict[str, Any],
    max_rows: int,
) -> TelemetryOutbox:
    if max_rows <= 0:
        raise ValueError("telemetry_outbox_limit_required")
    count = session.scalar(select(func.count()).select_from(TelemetryOutbox)) or 0
    if count >= max_rows:
        removable = list(
            session.scalars(
                select(TelemetryOutbox.sequence)
                .where(TelemetryOutbox.status.in_(("acknowledged", "terminal")))
                .order_by(TelemetryOutbox.sequence)
                .limit(count - max_rows + 1)
            )
        )
        if removable:
            session.execute(delete(TelemetryOutbox).where(TelemetryOutbox.sequence.in_(removable)))
            count -= len(removable)
    if count >= max_rows:
        raise LocalJournalError("telemetry_outbox_capacity_reached")
    row = TelemetryOutbox(
        installation_id=installation_id,
        schema_version=schema_version,
        event_type=event_type,
        payload=payload,
    )
    session.add(row)
    session.flush()
    return row
