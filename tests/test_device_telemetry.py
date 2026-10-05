from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.device_telemetry import (
    DeviceTelemetryError,
    authenticate_device_credential,
    ingest_event,
    issue_device_credential,
    projection_for_user,
    validate_event,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'device-telemetry.db'}")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def make_user(db, suffix):
    row = models.User(
        username=f"user-{suffix}", email=f"user-{suffix}@example.test", hashed_password="x"
    )
    db.add(row)
    db.flush()
    return row


def event(installation_hash, *, event_id=None, event_type="health", payload=None,
          occurred_at=None):
    return {
        "schema_version": 1,
        "event_id": event_id or str(uuid4()),
        "event_type": event_type,
        "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
        "installation_hash": installation_hash,
        "account_hash": "b" * 64,
        "software_version": "1.0.0",
        "configuration_version": "config-v1",
        "payload": payload or {
            "state": "observe_only", "provider_connectivity": "healthy",
            "reconciliation": "clean", "telemetry": "connected",
        },
    }


def test_scoped_device_credential_ingests_append_only_event_and_idempotent_replay(db):
    user = make_user(db, "one")
    installation_hash = "a" * 64
    supplied = issue_device_credential(
        db, user_id=user.id, installation_hash=installation_hash
    )
    db.commit()
    credential = authenticate_device_credential(db, f"Device {supplied}")
    payload = event(installation_hash)
    event_id, replay = ingest_event(db, credential, payload)
    db.commit()
    assert replay is False and event_id == payload["event_id"]
    same_id, replay = ingest_event(db, credential, payload)
    assert replay is True and same_id == event_id
    assert db.query(models.DeviceTelemetryEvent).count() == 1
    projection = projection_for_user(db, user_id=user.id)[0]
    assert projection["controls_available"] is False
    assert projection["authority"] == "local_device_and_provider"
    assert projection["freshness"] == "delayed_read_only"


def test_credentials_cannot_cross_installations_tenants_or_auth_schemes(db):
    first = make_user(db, "first")
    second = make_user(db, "second")
    first_hash, second_hash = "a" * 64, "c" * 64
    supplied = issue_device_credential(db, user_id=first.id, installation_hash=first_hash)
    issue_device_credential(db, user_id=second.id, installation_hash=second_hash)
    db.commit()
    credential = authenticate_device_credential(db, f"Device {supplied}")
    with pytest.raises(DeviceTelemetryError, match="scope_mismatch"):
        ingest_event(db, credential, event(second_hash))
    for authorization in ("Bearer admin-session", "Topstep provider-key", None):
        with pytest.raises(DeviceTelemetryError, match="device_credential_required"):
            authenticate_device_credential(db, authorization)
    assert projection_for_user(db, user_id=second.id) == []


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(username="owner"),
        lambda value: value["payload"].update(custom_tag="tb-secret"),
        lambda value: value["payload"].update(command="cancel_all"),
        lambda value: value.update(account_hash="full-account-id"),
        lambda value: value["payload"].update(raw_provider_payload={"token": "x"}),
    ],
)
def test_ingestion_revalidates_redaction_and_rejects_order_capable_content(change):
    value = event("a" * 64)
    change(value)
    with pytest.raises(DeviceTelemetryError):
        validate_event(value)


def test_projection_is_monotonic_and_stale_labeled_per_tenant(db, monkeypatch):
    user = make_user(db, "projection")
    installation_hash = "a" * 64
    supplied = issue_device_credential(db, user_id=user.id, installation_hash=installation_hash)
    db.commit()
    credential = authenticate_device_credential(db, f"Device {supplied}")
    now = datetime.now(timezone.utc)
    newest = event(
        installation_hash, event_type="lifecycle",
        payload={"state": "practice_armed", "reason_classification": "local_confirmed"},
        occurred_at=now,
    )
    older = event(
        installation_hash, event_type="lifecycle",
        payload={"state": "observe_only", "reason_classification": "older"},
        occurred_at=now - timedelta(minutes=1),
    )
    ingest_event(db, credential, newest)
    ingest_event(db, credential, older)
    db.commit()
    projection = db.query(models.DeviceTelemetryProjection).one()
    assert projection.lifecycle["state"] == "practice_armed"
    monkeypatch.setattr(
        "app.device_telemetry.utc_now", lambda: now + timedelta(minutes=3)
    )
    assert projection_for_user(db, user_id=user.id)[0]["freshness"] == "stale"


def test_timestamp_retention_window_rejects_old_or_future_events():
    installation_hash = "a" * 64
    now = datetime.now(timezone.utc)
    with pytest.raises(DeviceTelemetryError, match="timestamp_out_of_window"):
        validate_event(event(installation_hash, occurred_at=now - timedelta(days=8)))
    with pytest.raises(DeviceTelemetryError, match="timestamp_out_of_window"):
        validate_event(event(installation_hash, occurred_at=now + timedelta(minutes=6)))


def test_telemetry_transport_has_no_hosted_to_local_command_channel():
    root = Path(__file__).resolve().parents[1]
    local_source = (root / "local_executor" / "telemetry.py").read_text(encoding="utf-8")
    routes = (root / "app" / "device_telemetry_routes.py").read_text(encoding="utf-8")
    dashboard = (root / "frontend" / "src" / "pages" / "Dashboard.tsx").read_text(
        encoding="utf-8"
    )
    assert "self._http.post(" in local_source
    for forbidden in ("self._http.get(", "WebSocket", "EventSource", "callback_url"):
        assert forbidden not in local_source
    assert '@router.post("/v1/events"' in routes
    assert "@router.get(\"\")" in routes
    assert "@router.put" not in routes and "@router.delete" not in routes
    assert "api.get('/device-telemetry')" in dashboard
    assert "api.post('/device-telemetry" not in dashboard
