from __future__ import annotations

import http.client
import json
from urllib.parse import parse_qs, urlparse

import pytest

from local_executor.control_surface import (
    ControlSurfaceError,
    LocalControlSurface,
    LocalOperatorController,
)
from local_executor.credentials import CredentialEnrollment
from local_executor.preflight import REQUIRED_PREFLIGHT_CHECKS, StartupPreflight
from local_executor.secret_store import MemorySecretStore


@pytest.fixture()
def surface():
    store = MemorySecretStore()
    calls = []
    controller = LocalOperatorController(
        CredentialEnrollment(store),
        reads={
            "health": lambda: {"classification": "observe_only", "mutation_ready": False},
            "accounts": lambda: {
                "classification": "accounts_discovered",
                "accounts": [{"redacted_suffix": "***1234", "can_trade": True}],
            },
            "policy": lambda: {"classification": "policy_review_required"},
            "qualification": lambda: {"classification": "practice_incomplete"},
            "reconciliation": lambda: {"classification": "clean"},
            "uninstall_guidance": lambda: {
                "classification": "verify_topstep_then_revoke_key"
            },
        },
        actions={name: (lambda payload, operation=name: calls.append((operation, payload)) or {
            "classification": f"{operation}_accepted"
        }) for name in (
            "account_attest", "consent_accept", "practice_arm", "combine_arm",
            "kill_activate", "reconcile_now", "backup_create", "first_order_authorize",
            "cancel_all", "flatten", "data_reset",
        )},
    )
    value = LocalControlSurface(controller, csrf_secret="fixture-csrf-secret")
    value.start()
    yield value, store, calls
    value.stop()


def request(surface, method, path, *, body=None, host=None, origin=None, csrf=None):
    connection = http.client.HTTPConnection("127.0.0.1", surface.port, timeout=3)
    headers = {"Host": host or f"127.0.0.1:{surface.port}"}
    if origin is not None:
        headers["Origin"] = origin
    if csrf is not None:
        headers["X-Local-CSRF-Token"] = csrf
    raw = None
    if body is not None:
        raw = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=raw, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, response_headers, payload


def test_loopback_binding_pinned_assets_and_fragment_csrf(surface):
    value, _store, _calls = surface
    assert value.origin.startswith("http://127.0.0.1:")
    parsed = urlparse(value.launch_url)
    assert parse_qs(parsed.fragment)["csrf"] == ["fixture-csrf-secret"]
    status, headers, body = request(value, "GET", "/")
    assert status == 200 and b"Local Combine Executor" in body
    assert b"https://" not in body and b"http://" not in body
    assert b"credential-form" in body and b"autocomplete=new-password" in body
    assert headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    status, _, script = request(value, "GET", "/app.js")
    assert status == 200
    assert b"/api/credentials/enroll" in script
    assert b"localStorage" not in script and b"sessionStorage" not in script
    with pytest.raises(ControlSurfaceError, match="loopback_binding_required"):
        LocalControlSurface(value._controller, host="0.0.0.0")


def test_host_origin_and_csrf_are_all_required(surface):
    value, _store, _calls = surface
    status, _, _ = request(value, "GET", "/api/health", host="evil.example")
    assert status == 403
    status, _, _ = request(value, "GET", "/api/health")
    assert status == 403
    status, _, _ = request(
        value, "POST", "/api/kill/activate", body={}, csrf="fixture-csrf-secret",
        origin="https://evil.example",
    )
    assert status == 403
    status, _, body = request(
        value, "POST", "/api/kill/activate", body={}, csrf="fixture-csrf-secret",
        origin=value.origin,
    )
    assert status == 200 and json.loads(body)["classification"] == "kill_activate_accepted"


def test_credentials_are_write_only_and_secret_fields_are_cleared(surface):
    value, store, _calls = surface
    status, _, body = request(
        value, "POST", "/api/credentials/enroll",
        body={"username": "local-user", "api_key": "never-return-this"},
        csrf="fixture-csrf-secret", origin=value.origin,
    )
    response = json.loads(body)
    assert status == 200 and response == {
        "classification": "credentials_enrolled", "secret_fields_cleared": True
    }
    assert b"local-user" not in body and b"never-return-this" not in body
    assert store.slot_names == {"topstep_username", "topstep_api_key"}
    status, _, _ = request(
        value, "GET", "/api/credentials/enroll", csrf="fixture-csrf-secret"
    )
    assert status == 404


@pytest.mark.parametrize(
    ("path", "confirmation"),
    [
        ("/api/first/order/authorize", "AUTHORIZE-FIRST-ORDER"),
        ("/api/cancel/all", "CANCEL-ALL"),
        ("/api/flatten", "FLATTEN"),
        ("/api/credentials/delete", "DELETE-CREDENTIALS"),
        ("/api/data/reset", "RESET-LOCAL-DATA"),
    ],
)
def test_sensitive_operations_require_immediate_exact_confirmation(
    surface, path, confirmation
):
    value, _store, calls = surface
    status, _, _ = request(
        value, "POST", path, body={"confirmation": "wrong"},
        csrf="fixture-csrf-secret", origin=value.origin,
    )
    assert status == 409
    status, _, body = request(
        value, "POST", path, body={"confirmation": confirmation},
        csrf="fixture-csrf-secret", origin=value.origin,
    )
    assert status == 200
    assert b"never-return-this" not in body and b"local-user" not in body
    if path != "/api/credentials/delete":
        assert calls


def test_local_interfaces_are_explicit_and_unknown_commands_are_absent(surface):
    value, _store, _calls = surface
    for endpoint in (
        "health", "accounts", "policy", "qualification", "reconciliation",
        "uninstall/guidance",
    ):
        status, _, body = request(
            value, "GET", f"/api/{endpoint}", csrf="fixture-csrf-secret"
        )
        assert status == 200 and "classification" in json.loads(body)
    status, _, _ = request(
        value, "POST", "/api/remote/command", body={},
        csrf="fixture-csrf-secret", origin=value.origin,
    )
    assert status == 404


def test_preflight_is_complete_ordered_and_redacts_exceptions():
    checks = {name: (lambda: True) for name in REQUIRED_PREFLIGHT_CHECKS}
    report = StartupPreflight(checks).run()
    assert report.mutation_ready and report.classification == "preflight_passed"
    assert tuple(check.name for check in report.checks) == REQUIRED_PREFLIGHT_CHECKS

    checks["provider_connectivity"] = lambda: (_ for _ in ()).throw(
        RuntimeError("Bearer secret-token account-123")
    )
    failed = StartupPreflight(checks).run().to_dict()
    serialized = json.dumps(failed)
    assert failed["classification"] == "provider_connectivity_check_error"
    assert "secret-token" not in serialized and "account-123" not in serialized


def test_preflight_refuses_missing_or_extra_gates():
    incomplete = {name: (lambda: True) for name in REQUIRED_PREFLIGHT_CHECKS[:-1]}
    with pytest.raises(ValueError, match="preflight_check_set_incomplete"):
        StartupPreflight(incomplete)
