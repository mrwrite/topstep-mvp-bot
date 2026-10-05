from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from local_executor.journal import LocalJournal, LocalJournalError
from local_executor.journal_models import AuditEvent, Installation, TelemetryOutbox
from local_executor.telemetry import (
    LocalTelemetryDelivery,
    TelemetryError,
    TelemetryOutagePolicy,
    TelemetrySerializer,
    build_event,
)


class FakeResponse:
    def __init__(self, body, *, status=202, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "telemetry.db", secure_permissions=False)
    with value.session_factory.begin() as session:
        installation = Installation(software_version="fixture")
        session.add(installation)
        session.flush()
        installation_id = installation.id
    yield value, installation_id
    value.close()


def event(now, **changes):
    values = dict(
        event_type="health", installation_hash="a" * 64, account_hash="b" * 64,
        software_version="1.0.0", configuration_version="config-v1",
        payload={"state": "observe_only", "reconciliation": "clean"}, occurred_at=now,
    )
    values.update(changes)
    return build_event(**values)


def delivery(journal, http, now, *, policy=None):
    return LocalTelemetryDelivery(
        journal.session_factory, endpoint="https://telemetry.example.test/device-telemetry/v1/events",
        credential_loader=lambda: "credential-id.device-secret",
        policy=policy or TelemetryOutagePolicy("bounded_buffer", 300, 2),
        http_session=http, clock=lambda: now,
    )


def test_versioned_allowlist_accepts_only_sanitized_observations():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert json.loads(TelemetrySerializer.serialize(event(now)))["schema_version"] == 1
    for event_type, payload in {
        "lifecycle": {"state": "practice_armed", "reason_classification": "local_confirmed"},
        "order_lifecycle": {"action_classification": "place", "outcome": "accepted",
                            "provider_order_hash": "c" * 64},
        "fill": {"instrument_hash": "d" * 64, "direction": "long", "size": 1,
                 "price": 5000.25, "pnl": 0.0},
        "position": {"instrument_hash": "d" * 64, "direction": "long", "size": 1,
                     "average_price": 5000.25, "unrealized_pnl": 2.0},
        "pnl": {"realized": 1.0, "unrealized": 2.0},
        "risk": {"allowed": False, "classifications": ["daily_limit"]},
        "audit": {"classification": "local_kill_activated"},
    }.items():
        TelemetrySerializer.serialize(event(now, event_type=event_type, payload=payload))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(username="owner"),
        lambda value: value["payload"].update(api_key="secret"),
        lambda value: value["payload"].update(custom_tag="tb-123"),
        lambda value: value["payload"].update(command="flatten"),
        lambda value: value.update(installation_hash="full-installation-id"),
        lambda value: value["payload"].update(raw_response={"success": True}),
    ],
)
def test_secrets_identifiers_raw_payloads_and_order_capable_fields_are_rejected(mutation):
    value = event(datetime(2026, 10, 5, tzinfo=timezone.utc))
    mutation(value)
    with pytest.raises(TelemetryError):
        TelemetrySerializer.serialize(value)


def test_delivery_is_https_outbound_only_and_ack_response_is_non_authoritative(journal):
    local, installation_id = journal
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    http = FakeHttp(FakeResponse({
        "acknowledgement_id": "ack-1", "retry_after_seconds": 3,
        "command": {"action": "place", "quantity": 1},
    }))
    service = delivery(local, http, now)
    service.enqueue(installation_id=installation_id, event=event(now))
    result = service.deliver_once()
    assert result.classification == "telemetry_acknowledged"
    assert result.protocol_violation is True and result.retry_after_seconds == 3
    assert len(http.calls) == 1
    assert http.calls[0][0].startswith("https://")
    assert http.calls[0][1]["headers"]["Authorization"].startswith("Device ")
    sent = json.loads(http.calls[0][1]["data"])
    assert "command" not in sent and "api_key" not in sent
    with local.session_factory() as session:
        assert session.query(TelemetryOutbox).one().status == "acknowledged"
        assert session.query(AuditEvent).one().classification == (
            "telemetry_response_protocol_violation"
        )


def test_outage_backpressure_and_replay_preserve_pending_events(journal):
    local, installation_id = journal
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    http = FakeHttp(requests.ConnectionError("offline"))
    service = delivery(local, http, now)
    first_event = event(now)
    service.enqueue(installation_id=installation_id, event=first_event)
    result = service.deliver_once()
    assert result.classification == "telemetry_delivery_failed"
    with local.session_factory() as session:
        row = session.query(TelemetryOutbox).one()
        assert row.status == "pending" and row.attempt_count == 1
    service.enqueue(
        installation_id=installation_id,
        event=event(now, payload={"state": "observe_only", "telemetry": "buffering"}),
    )
    with pytest.raises(LocalJournalError, match="capacity_reached"):
        service.enqueue(installation_id=installation_id, event=event(now))
    assert service.new_entries_allowed(last_acknowledged_at=now - timedelta(seconds=301)) is False


def test_halt_policy_and_non_https_configuration_fail_closed(journal):
    local, _installation_id = journal
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with pytest.raises(TelemetryError, match="https_endpoint_required"):
        LocalTelemetryDelivery(
            local.session_factory, endpoint="http://railway.example.test/events",
            credential_loader=lambda: "secret",
            policy=TelemetryOutagePolicy("halt", 0, 2),
        )
    service = delivery(
        local, FakeHttp(), now, policy=TelemetryOutagePolicy("halt", 0, 2)
    )
    assert service.new_entries_allowed(last_acknowledged_at=None) is False
    assert service.new_entries_allowed(last_acknowledged_at=now) is True
