from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .journal_models import AuditEvent, TelemetryOutbox
from .journal_repository import enqueue_telemetry


TELEMETRY_SCHEMA_VERSION = 1
TELEMETRY_EVENT_FIELDS = frozenset({
    "schema_version", "event_id", "event_type", "occurred_at",
    "installation_hash", "account_hash", "software_version",
    "configuration_version", "payload",
})
EVENT_PAYLOAD_FIELDS = {
    "health": frozenset({"state", "provider_connectivity", "reconciliation", "telemetry"}),
    "lifecycle": frozenset({"state", "reason_classification"}),
    "order_lifecycle": frozenset({"action_classification", "outcome", "provider_order_hash"}),
    "fill": frozenset({"instrument_hash", "direction", "size", "price", "pnl"}),
    "position": frozenset({"instrument_hash", "direction", "size", "average_price", "unrealized_pnl"}),
    "pnl": frozenset({"realized", "unrealized"}),
    "risk": frozenset({"allowed", "classifications"}),
    "audit": frozenset({"classification"}),
}
FORBIDDEN_FIELD_MARKERS = (
    "username", "api_key", "apikey", "password", "token", "credential",
    "secret", "authorization", "account_id", "installation_id", "custom_tag",
    "raw", "request_body", "response_body", "database", "strategy_secret",
    "contract_id", "order_side", "order_quantity", "command", "trigger",
    "approval", "policy_update", "feature_flag",
)


class TelemetryError(RuntimeError):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification


@dataclass(frozen=True)
class TelemetryOutagePolicy:
    behavior: str
    max_offline_seconds: int
    max_outbox_rows: int

    def validate(self) -> None:
        if self.behavior not in {"halt", "bounded_buffer"}:
            raise TelemetryError("telemetry_outage_policy_invalid")
        if self.max_offline_seconds < 0 or self.max_outbox_rows <= 0:
            raise TelemetryError("telemetry_outage_policy_invalid")


@dataclass(frozen=True)
class DeliveryResult:
    classification: str
    event_id: str | None
    retry_after_seconds: int | None = None
    protocol_violation: bool = False


class TelemetrySerializer:
    @staticmethod
    def serialize(event: dict[str, Any]) -> bytes:
        if set(event) != TELEMETRY_EVENT_FIELDS:
            raise TelemetryError("telemetry_schema_fields_rejected")
        if event.get("schema_version") != TELEMETRY_SCHEMA_VERSION:
            raise TelemetryError("telemetry_schema_version_rejected")
        try:
            UUID(str(event.get("event_id")))
            datetime.fromisoformat(str(event.get("occurred_at")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise TelemetryError("telemetry_identity_or_time_invalid") from None
        event_type = event.get("event_type")
        if event_type not in EVENT_PAYLOAD_FIELDS:
            raise TelemetryError("telemetry_event_type_rejected")
        for key in ("installation_hash", "account_hash"):
            value = event.get(key)
            if key == "account_hash" and value is None:
                continue
            if not isinstance(value, str) or len(value) != 64 \
                    or any(character not in "0123456789abcdef" for character in value):
                raise TelemetryError("telemetry_correlation_hash_invalid")
        for key in ("software_version", "configuration_version"):
            value = event.get(key)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise TelemetryError("telemetry_version_invalid")
        payload = event.get("payload")
        if not isinstance(payload, dict) or not set(payload).issubset(
            EVENT_PAYLOAD_FIELDS[event_type]
        ):
            raise TelemetryError("telemetry_payload_fields_rejected")
        TelemetrySerializer._reject_forbidden(event)
        return json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _reject_forbidden(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).lower().replace("-", "_")
                if any(marker in normalized for marker in FORBIDDEN_FIELD_MARKERS):
                    raise TelemetryError("telemetry_forbidden_field")
                TelemetrySerializer._reject_forbidden(nested, f"{path}.{normalized}")
        elif isinstance(value, (list, tuple)):
            for nested in value:
                TelemetrySerializer._reject_forbidden(nested, path)
        elif isinstance(value, str):
            lowered = value.lower()
            if lowered.startswith("bearer ") or lowered.startswith("tb-") \
                    or "-----begin private key-----" in lowered:
                raise TelemetryError("telemetry_forbidden_value")
            if len(value) > 256:
                raise TelemetryError("telemetry_value_too_long")
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise TelemetryError("telemetry_value_type_rejected")


def build_event(
    *,
    event_type: str,
    installation_hash: str,
    account_hash: str | None,
    software_version: str,
    configuration_version: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    event_id: str | None = None,
) -> dict[str, Any]:
    if occurred_at.tzinfo is None:
        raise TelemetryError("telemetry_timestamp_timezone_required")
    event = {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "event_id": event_id or str(uuid4()),
        "event_type": event_type,
        "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
        "installation_hash": installation_hash,
        "account_hash": account_hash,
        "software_version": software_version,
        "configuration_version": configuration_version,
        "payload": payload,
    }
    TelemetrySerializer.serialize(event)
    return event


class LocalTelemetryDelivery:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        endpoint: str,
        credential_loader: Callable[[], str],
        policy: TelemetryOutagePolicy,
        http_session: Any | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise TelemetryError("telemetry_https_endpoint_required")
        policy.validate()
        self._sessions = session_factory
        self._endpoint = endpoint
        self._credential_loader = credential_loader
        self._policy = policy
        self._http = http_session or requests.Session()
        self._clock = clock

    def enqueue(self, *, installation_id: str, event: dict[str, Any]) -> int:
        TelemetrySerializer.serialize(event)
        with self._sessions.begin() as session:
            row = enqueue_telemetry(
                session,
                installation_id=installation_id,
                schema_version=TELEMETRY_SCHEMA_VERSION,
                event_type=str(event["event_type"]),
                payload=event,
                max_rows=self._policy.max_outbox_rows,
            )
            return row.sequence

    def deliver_once(self) -> DeliveryResult:
        with self._sessions.begin() as session:
            row = session.scalar(select(TelemetryOutbox).where(
                TelemetryOutbox.status == "pending"
            ).order_by(TelemetryOutbox.sequence))
            if row is None:
                return DeliveryResult("outbox_empty", None)
            row.status = "sending"
            row.attempt_count += 1
            event_id = row.event_id
            installation_id = row.installation_id
            payload = row.payload
        try:
            body = TelemetrySerializer.serialize(payload)
            credential = self._credential_loader()
            response = self._http.post(
                self._endpoint,
                data=body,
                headers={
                    "Authorization": f"Device {credential}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=15,
            )
        except (requests.RequestException, TelemetryError, Exception):
            self._return_pending(event_id)
            return DeliveryResult("telemetry_delivery_failed", event_id)

        if int(response.status_code) not in range(200, 300):
            self._return_pending(event_id)
            retry_after = _bounded_retry_after(response.headers.get("Retry-After"))
            return DeliveryResult("telemetry_rejected", event_id, retry_after)
        try:
            response_body = response.json()
        except (ValueError, TypeError):
            self._return_pending(event_id)
            return DeliveryResult("telemetry_ack_malformed", event_id)
        if not isinstance(response_body, dict) \
                or not isinstance(response_body.get("acknowledgement_id"), str):
            self._return_pending(event_id)
            return DeliveryResult("telemetry_ack_malformed", event_id)
        allowed = {"acknowledgement_id", "retry_after_seconds"}
        unexpected = sorted(set(response_body) - allowed)
        retry_after = _bounded_retry_after(response_body.get("retry_after_seconds"))
        with self._sessions.begin() as session:
            row = session.scalar(select(TelemetryOutbox).where(
                TelemetryOutbox.event_id == event_id
            ))
            row.status = "acknowledged"
            row.acknowledged_at = self._clock()
            if unexpected:
                session.add(AuditEvent(
                    installation_id=installation_id,
                    classification="telemetry_response_protocol_violation",
                    correlation_id=str(uuid4()),
                    payload={"unexpected_field_count": len(unexpected)},
                ))
        return DeliveryResult(
            "telemetry_acknowledged", event_id, retry_after,
            protocol_violation=bool(unexpected),
        )

    def new_entries_allowed(self, *, last_acknowledged_at: datetime | None) -> bool:
        if self._policy.behavior == "halt":
            return last_acknowledged_at is not None and _aware(last_acknowledged_at) >= _aware(
                self._clock()
            ) - timedelta(seconds=1)
        if last_acknowledged_at is None:
            return False
        if _aware(self._clock()) - _aware(last_acknowledged_at) > timedelta(
            seconds=self._policy.max_offline_seconds
        ):
            return False
        with self._sessions() as session:
            pending = session.scalar(select(func.count()).select_from(TelemetryOutbox).where(
                TelemetryOutbox.status.in_(("pending", "sending"))
            )) or 0
        return pending < self._policy.max_outbox_rows

    def _return_pending(self, event_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(select(TelemetryOutbox).where(
                TelemetryOutbox.event_id == event_id
            ))
            if row is not None:
                row.status = "pending"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _bounded_retry_after(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, min(int(value), 300))
    except (TypeError, ValueError):
        return None
