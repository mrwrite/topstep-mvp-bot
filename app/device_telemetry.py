from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .time_utils import utc_now


SCHEMA_VERSION = 1
EVENT_FIELDS = frozenset({
    "schema_version", "event_id", "event_type", "occurred_at", "installation_hash",
    "account_hash", "software_version", "configuration_version", "payload",
})
PAYLOAD_FIELDS = {
    "health": frozenset({"state", "provider_connectivity", "reconciliation", "telemetry"}),
    "lifecycle": frozenset({"state", "reason_classification"}),
    "order_lifecycle": frozenset({"action_classification", "outcome", "provider_order_hash"}),
    "fill": frozenset({"instrument_hash", "direction", "size", "price", "pnl"}),
    "position": frozenset({"instrument_hash", "direction", "size", "average_price", "unrealized_pnl"}),
    "pnl": frozenset({"realized", "unrealized"}),
    "risk": frozenset({"allowed", "classifications"}),
    "audit": frozenset({"classification"}),
}
FORBIDDEN = (
    "username", "api_key", "apikey", "password", "token", "credential", "secret",
    "authorization", "account_id", "installation_id", "custom_tag", "raw",
    "request_body", "response_body", "database", "strategy_secret", "contract_id",
    "order_side", "order_quantity", "command", "trigger", "approval", "policy_update",
    "feature_flag",
)


class DeviceTelemetryError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


def issue_device_credential(
    db: Session, *, user_id: int, installation_hash: str
) -> str:
    _hash64(installation_hash, "installation_hash_invalid")
    credential_id = str(uuid4())
    secret = secrets.token_urlsafe(32)
    credential = f"{credential_id}.{secret}"
    db.add(models.DeviceTelemetryCredential(
        id=credential_id,
        user_id=user_id,
        installation_hash=installation_hash,
        credential_hash=sha256(credential.encode("utf-8")).hexdigest(),
        active=1,
        created_at=utc_now(),
    ))
    db.flush()
    return credential


def authenticate_device_credential(
    db: Session, authorization: str | None
) -> models.DeviceTelemetryCredential:
    if not authorization or not authorization.startswith("Device "):
        raise DeviceTelemetryError("device_credential_required")
    supplied = authorization.removeprefix("Device ").strip()
    credential_id, separator, secret = supplied.partition(".")
    if not separator or not secret:
        raise DeviceTelemetryError("device_credential_invalid")
    row = db.get(models.DeviceTelemetryCredential, credential_id)
    digest = sha256(supplied.encode("utf-8")).hexdigest()
    if row is None or row.active != 1 or row.revoked_at is not None \
            or not hmac.compare_digest(row.credential_hash, digest):
        raise DeviceTelemetryError("device_credential_invalid")
    row.last_used_at = utc_now()
    return row


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
        raise DeviceTelemetryError("telemetry_schema_fields_rejected")
    if event.get("schema_version") != SCHEMA_VERSION:
        raise DeviceTelemetryError("telemetry_schema_version_rejected")
    try:
        UUID(str(event.get("event_id")))
        occurred_at = datetime.fromisoformat(
            str(event.get("occurred_at")).replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        raise DeviceTelemetryError("telemetry_identity_or_time_invalid") from None
    if occurred_at.tzinfo is None:
        raise DeviceTelemetryError("telemetry_identity_or_time_invalid")
    now = utc_now()
    if occurred_at.astimezone(timezone.utc) > now + timedelta(minutes=5) \
            or occurred_at.astimezone(timezone.utc) < now - timedelta(days=7):
        raise DeviceTelemetryError("telemetry_timestamp_out_of_window")
    event_type = event.get("event_type")
    if event_type not in PAYLOAD_FIELDS:
        raise DeviceTelemetryError("telemetry_event_type_rejected")
    _hash64(event.get("installation_hash"), "telemetry_correlation_hash_invalid")
    if event.get("account_hash") is not None:
        _hash64(event.get("account_hash"), "telemetry_correlation_hash_invalid")
    for key in ("software_version", "configuration_version"):
        value = event.get(key)
        if not isinstance(value, str) or not value or len(value) > 128:
            raise DeviceTelemetryError("telemetry_version_invalid")
    payload = event.get("payload")
    if not isinstance(payload, dict) or not set(payload).issubset(PAYLOAD_FIELDS[event_type]):
        raise DeviceTelemetryError("telemetry_payload_fields_rejected")
    _reject_forbidden(event)
    return {**event, "occurred_at": occurred_at.astimezone(timezone.utc)}


def ingest_event(
    db: Session,
    credential: models.DeviceTelemetryCredential,
    event: dict[str, Any],
) -> tuple[str, bool]:
    validated = validate_event(event)
    if validated["installation_hash"] != credential.installation_hash:
        raise DeviceTelemetryError("telemetry_installation_scope_mismatch")
    existing = db.scalar(select(models.DeviceTelemetryEvent).where(
        models.DeviceTelemetryEvent.user_id == credential.user_id,
        models.DeviceTelemetryEvent.installation_hash == credential.installation_hash,
        models.DeviceTelemetryEvent.event_id == validated["event_id"],
    ))
    if existing is not None:
        return existing.event_id, True
    received = utc_now()
    row = models.DeviceTelemetryEvent(
        user_id=credential.user_id,
        installation_hash=credential.installation_hash,
        event_id=validated["event_id"],
        schema_version=validated["schema_version"],
        event_type=validated["event_type"],
        occurred_at=validated["occurred_at"],
        payload=event,
        received_at=received,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(models.DeviceTelemetryEvent).where(
            models.DeviceTelemetryEvent.user_id == credential.user_id,
            models.DeviceTelemetryEvent.installation_hash == credential.installation_hash,
            models.DeviceTelemetryEvent.event_id == validated["event_id"],
        ))
        if existing is None:
            raise
        return existing.event_id, True
    _project(db, credential.user_id, validated, received)
    return row.event_id, False


def projection_for_user(
    db: Session, *, user_id: int
) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(models.DeviceTelemetryProjection).where(
        models.DeviceTelemetryProjection.user_id == user_id
    ).order_by(models.DeviceTelemetryProjection.updated_at.desc())))
    now = utc_now()
    result = []
    for row in rows:
        age = max(0, int((now - _aware(row.last_received_at)).total_seconds()))
        result.append({
            "installation_hash": row.installation_hash,
            "last_event_id": row.last_event_id,
            "last_device_event_at": _aware(row.last_event_at).isoformat(),
            "last_received_at": _aware(row.last_received_at).isoformat(),
            "freshness_seconds": age,
            "freshness": "stale" if age > 120 else "delayed_read_only",
            "software_version": row.software_version,
            "configuration_version": row.configuration_version,
            "health": row.health,
            "lifecycle": row.lifecycle,
            "position": row.latest_position,
            "fill": row.latest_fill,
            "pnl": row.latest_pnl,
            "risk": row.latest_risk,
            "controls_available": False,
            "authority": "local_device_and_provider",
        })
    return result


def _project(db: Session, user_id: int, event: dict[str, Any], received: datetime) -> None:
    row = db.scalar(select(models.DeviceTelemetryProjection).where(
        models.DeviceTelemetryProjection.user_id == user_id,
        models.DeviceTelemetryProjection.installation_hash == event["installation_hash"],
    ))
    if row is None:
        row = models.DeviceTelemetryProjection(
            user_id=user_id,
            installation_hash=event["installation_hash"],
            last_event_id=event["event_id"],
            last_event_at=event["occurred_at"],
            last_received_at=received,
            software_version=event["software_version"],
            configuration_version=event["configuration_version"],
            health={}, lifecycle={}, updated_at=received,
        )
        db.add(row)
    elif _aware(event["occurred_at"]) < _aware(row.last_event_at):
        return
    row.last_event_id = event["event_id"]
    row.last_event_at = event["occurred_at"]
    row.last_received_at = received
    row.software_version = event["software_version"]
    row.configuration_version = event["configuration_version"]
    row.updated_at = received
    field = {
        "health": "health", "lifecycle": "lifecycle", "position": "latest_position",
        "fill": "latest_fill", "pnl": "latest_pnl", "risk": "latest_risk",
    }.get(event["event_type"])
    if field is not None:
        setattr(row, field, event["payload"])


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(marker in normalized for marker in FORBIDDEN):
                raise DeviceTelemetryError("telemetry_forbidden_field")
            _reject_forbidden(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_forbidden(nested)
    elif isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith("bearer ") or lowered.startswith("tb-") \
                or "-----begin private key-----" in lowered or len(value) > 256:
            raise DeviceTelemetryError("telemetry_forbidden_value")
    elif value is not None and not isinstance(value, (bool, int, float, datetime)):
        raise DeviceTelemetryError("telemetry_value_type_rejected")


def _hash64(value: Any, classification: str) -> None:
    if not isinstance(value, str) or len(value) != 64 \
            or any(character not in "0123456789abcdef" for character in value):
        raise DeviceTelemetryError(classification)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
