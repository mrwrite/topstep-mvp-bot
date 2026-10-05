from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from .credentials import CredentialEnrollment


MAX_REQUEST_BYTES = 16_384
SAFE_READ_OPERATIONS = frozenset({
    "health", "credential_status", "accounts", "policy", "qualification",
    "reconciliation", "uninstall_guidance", "contracts",
})
MUTATING_OPERATIONS = frozenset({
    "credentials_enroll", "account_attest", "consent_accept", "practice_arm",
    "combine_arm", "kill_activate", "reconcile_now", "backup_create",
    "first_order_authorize", "cancel_all", "flatten", "credentials_delete",
    "data_reset", "policy_save",
    "practice_run_once",
})
CONFIRMATIONS = {
    "first_order_authorize": "AUTHORIZE-FIRST-ORDER",
    "cancel_all": "CANCEL-ALL",
    "flatten": "FLATTEN",
    "credentials_delete": "DELETE-CREDENTIALS",
    "data_reset": "RESET-LOCAL-DATA",
    "practice_run_once": "RUN-PRACTICE-ONCE",
}
SENSITIVE_RESPONSE_KEYS = frozenset({
    "username", "api_key", "apikey", "token", "credential", "secret",
    "custom_tag", "raw_payload", "authorization",
})


class ControlSurfaceError(RuntimeError):
    def __init__(self, classification: str, *, status: int = 400) -> None:
        super().__init__(classification)
        self.classification = classification
        self.status = status


@dataclass(frozen=True)
class SafeAccountSummary:
    redacted_suffix: str
    can_trade: bool
    is_visible: bool


class LocalOperatorController:
    """Small adapter over local services; it never exposes stored secrets."""

    def __init__(
        self,
        credentials: CredentialEnrollment,
        *,
        reads: Mapping[str, Callable[[], dict[str, Any]]] | None = None,
        actions: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        on_credentials_changed: Callable[[], None] | None = None,
    ) -> None:
        self._credentials = credentials
        self._reads = dict(reads or {})
        self._actions = dict(actions or {})
        self._on_credentials_changed = on_credentials_changed or (lambda: None)

    def read(
        self, operation: str, query: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        if operation not in SAFE_READ_OPERATIONS:
            raise ControlSurfaceError("operation_not_found", status=404)
        callback = self._reads.get(operation)
        if callback is None:
            return {"classification": f"{operation}_unavailable"}
        return _safe_response(callback(dict(query or {})) if operation == "contracts" else callback())

    def mutate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in MUTATING_OPERATIONS:
            raise ControlSurfaceError("operation_not_found", status=404)
        expected = CONFIRMATIONS.get(operation)
        if expected is not None and payload.get("confirmation") != expected:
            raise ControlSurfaceError("immediate_confirmation_required", status=409)
        if operation == "credentials_enroll":
            username = payload.get("username")
            api_key = payload.get("api_key")
            if not isinstance(username, str) or not isinstance(api_key, str):
                raise ControlSurfaceError("credentials_required")
            self._credentials.enroll_topstep(username=username, api_key=api_key)
            self._on_credentials_changed()
            return {"classification": "credentials_enrolled", "secret_fields_cleared": True}
        if operation == "credentials_delete":
            deleted = self._credentials.delete_all()
            self._on_credentials_changed()
            return {
                "classification": "credentials_deleted",
                "deleted_slot_count": len(deleted),
                "secret_fields_cleared": True,
                "api_key_revocation_required": True,
            }
        callback = self._actions.get(operation)
        if callback is None:
            raise ControlSurfaceError(f"{operation}_unavailable", status=409)
        sanitized_input = {
            key: value for key, value in payload.items()
            if key not in {"username", "api_key", "token", "credential", "secret"}
        }
        return _safe_response(callback(sanitized_input))


class LocalControlSurface:
    def __init__(
        self,
        controller: LocalOperatorController,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        csrf_secret: str | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise ControlSurfaceError("loopback_binding_required")
        self._controller = controller
        self._host = host
        self._port = port
        self._csrf = csrf_secret or secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("control_surface_not_started")
        return int(self._server.server_address[1])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def launch_url(self) -> str:
        # URL fragments are not sent in HTTP requests or server logs. The pinned
        # local script moves this value into the CSRF header and clears the hash.
        return f"{self.origin}/#csrf={self._csrf}"

    def start(self) -> None:
        if self._server is not None:
            return
        controller = self._controller
        csrf = self._csrf

        class Handler(BaseHTTPRequestHandler):
            server_version = "LocalExecutor/1"
            sys_version = ""

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _allowed_host(self) -> bool:
                return self.headers.get("Host", "") == f"127.0.0.1:{self.server.server_port}"

            def _allowed_origin(self) -> bool:
                return self.headers.get("Origin", "") == (
                    f"http://127.0.0.1:{self.server.server_port}"
                )

            def _csrf_valid(self) -> bool:
                supplied = self.headers.get("X-Local-CSRF-Token", "")
                return bool(supplied) and secrets.compare_digest(supplied, csrf)

            def _send_json(self, status: int, value: dict[str, Any]) -> None:
                body = json.dumps(_safe_response(value), sort_keys=True).encode("utf-8")
                self.send_response(status)
                self._security_headers("application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _security_headers(self, content_type: str) -> None:
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; connect-src 'self'; "
                    "style-src 'self'; img-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                )

            def _reject_host(self) -> bool:
                if self._allowed_host():
                    return False
                self._send_json(403, {"classification": "host_rejected"})
                return True

            def do_GET(self) -> None:  # noqa: N802
                if self._reject_host():
                    return
                path = urlparse(self.path).path
                if path in {"/", "/index.html"}:
                    self._send_asset("text/html; charset=utf-8", _INDEX_HTML)
                    return
                if path == "/app.js":
                    self._send_asset("application/javascript; charset=utf-8", _APP_JS)
                    return
                if not path.startswith("/api/") or not self._csrf_valid():
                    self._send_json(403, {"classification": "csrf_required"})
                    return
                operation = path.removeprefix("/api/").replace("/", "_")
                query = {
                    key: values[-1] for key, values in __import__(
                        "urllib.parse", fromlist=["parse_qs"]
                    ).parse_qs(urlparse(self.path).query, keep_blank_values=True).items()
                    if values
                }
                try:
                    self._send_json(200, controller.read(operation, query))
                except ControlSurfaceError as exc:
                    self._send_json(exc.status, {"classification": exc.classification})

            def _send_asset(self, content_type: str, body: bytes) -> None:
                self.send_response(200)
                self._security_headers(content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                if self._reject_host():
                    return
                if not self._allowed_origin():
                    self._send_json(403, {"classification": "origin_rejected"})
                    return
                if not self._csrf_valid():
                    self._send_json(403, {"classification": "csrf_required"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._send_json(413, {"classification": "request_size_invalid"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send_json(400, {"classification": "malformed_json"})
                    return
                if not isinstance(payload, dict):
                    self._send_json(400, {"classification": "object_payload_required"})
                    return
                operation = urlparse(self.path).path.removeprefix("/api/").replace("/", "_")
                try:
                    self._send_json(200, controller.mutate(operation, payload))
                except ControlSurfaceError as exc:
                    self._send_json(exc.status, {"classification": exc.classification})
                except Exception:
                    self._send_json(500, {"classification": "local_operation_failed"})

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._thread = Thread(target=self._server.serve_forever, name="local-control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        self._server = None
        self._thread = None


def _safe_response(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ControlSurfaceError("unsafe_response_type", status=500)
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower().replace("-", "_")
        if normalized in SENSITIVE_RESPONSE_KEYS or any(
            marker in normalized for marker in ("password", "private_key", "session_token")
        ):
            raise ControlSurfaceError("unsafe_response_field", status=500)
        if isinstance(item, dict):
            sanitized[key] = _safe_response(item)
        elif isinstance(item, (str, int, float, bool)) or item is None:
            sanitized[key] = item
        elif isinstance(item, (list, tuple)):
            sanitized[key] = [
                _safe_response(entry) if isinstance(entry, dict) else entry
                for entry in item
                if isinstance(entry, (dict, str, int, float, bool)) or entry is None
            ]
        else:
            raise ControlSurfaceError("unsafe_response_value", status=500)
    return sanitized


_INDEX_HTML = b"""<!doctype html>
<html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>
<title>Local Combine Executor</title></head>
<body><main><h1>Local Combine Executor</h1><p id=status>Loading local health...</p>
<p>Trading controls and credentials remain on this personal device.</p>
<section id=credential-setup hidden>
<h2>Connect Topstep Practice</h2>
<p>Enter the API credentials on this local page. They are saved to your operating-system credential store and are never sent to Vercel or Railway.</p>
<form id=credential-form autocomplete=off>
<label>Username <input id=username name=username required autocomplete=off></label>
<label>API key <input id=api-key name=api_key type=password required autocomplete=new-password></label>
<button type=submit>Save locally</button>
</form><p id=credential-result aria-live=polite></p>
</section>
<section id=account-setup hidden>
<h2>Select a Topstep account</h2>
<p>Discover visible simulated accounts, choose the exact account, and attest its type. Account names are never used to infer account type.</p>
<button id=discover-accounts type=button>Discover accounts</button>
<form id=account-form hidden>
<label>Account <select id=account required></select></label>
<label>Account type <select id=account-kind required>
<option value=practice>Practice</option>
<option value=trading_combine>Trading Combine</option>
</select></label>
<label>Type the shown confirmation <input id=account-confirmation required autocomplete=off></label>
<button type=submit>Attest exact account</button>
</form><p id=account-result aria-live=polite></p>
</section>
<section id=policy-setup hidden>
<h2>Local Practice safety policy</h2>
<p>All fields are enforced on this device. No order can be sent until this policy, consent, signing, and reconciliation gates pass.</p>
<form id=contract-search-form><label>Contract search <input id=contract-search required autocomplete=off></label>
<button type=submit>Find simulated contracts</button></form>
<form id=policy-form hidden>
<label>Exact contract <select id=instrument required></select></label>
<fieldset><legend>RSI strategy</legend>
<label>Period <input id=rsi-period type=number min=2 required></label>
<label>Buy below <input id=rsi-buy type=number min=0.01 max=99 step=0.01 required></label>
<label>Sell above <input id=rsi-sell type=number min=0.01 max=99 step=0.01 required></label></fieldset>
<fieldset><legend>Risk limits</legend>
<label>Max position <input id=max-position type=number min=1 required></label>
<label>Max orders/session <input id=max-orders-session type=number min=1 required></label>
<label>Max orders/day <input id=max-orders-day type=number min=1 required></label>
<label>Max daily realized loss <input id=max-daily-loss type=number min=0.01 step=0.01 required></label>
<label>Max consecutive losses <input id=max-consecutive-losses type=number min=1 required></label></fieldset>
<fieldset><legend>Schedule and freshness</legend>
<label>IANA timezone <input id=timezone required placeholder=America/Chicago></label>
<label>Weekdays (0=Mon, comma-separated) <input id=weekdays required placeholder=0,1,2,3,4></label>
<label>Session start <input id=session-start type=time step=1 required></label>
<label>Session end <input id=session-end type=time step=1 required></label>
<label>Max data age seconds <input id=max-data-age type=number min=1 required></label>
<label>Max clock skew seconds <input id=max-clock-skew type=number min=1 required></label>
<label>Provider cooldown seconds <input id=provider-cooldown type=number min=1 required></label></fieldset>
<fieldset><legend>Telemetry and emergency behavior</legend>
<label>Telemetry outage <select id=telemetry-behavior><option value=halt>Halt entries</option><option value=bounded_buffer>Bounded offline buffer</option></select></label>
<label>Max telemetry offline seconds (0 for halt) <input id=telemetry-offline type=number min=0 required></label>
<label><input id=kill-cancel type=checkbox> Cancel open orders on local kill</label>
<label><input id=kill-flatten type=checkbox> Flatten positions on local kill</label></fieldset>
<button type=submit>Save local policy</button></form>
<p id=policy-result aria-live=polite></p>
</section>
<section id=consent-setup hidden>
<h2>Consent and Practice arming</h2>
<p>This account is simulated, but API orders can affect evaluation status, rule compliance, and subscription value. The key and session remain on this device.</p>
<label>Type I UNDERSTAND <input id=consent-confirmation autocomplete=off></label>
<button id=accept-consent type=button>Accept current policy</button>
<button id=arm-practice type=button disabled>Arm Practice locally</button>
<label>For one supervised strategy run, type RUN-PRACTICE-ONCE <input id=practice-run-confirmation autocomplete=off></label>
<button id=run-practice type=button disabled>Evaluate RSI and, only if allowed, submit one Practice order</button>
<p id=consent-result aria-live=polite></p>
</section>
</main><script src=/app.js></script></body></html>"""

_APP_JS = b"""'use strict';
const params = new URLSearchParams(location.hash.slice(1));
const csrf = params.get('csrf') || '';
history.replaceState(null, '', location.pathname);
const headers = {'X-Local-CSRF-Token': csrf};
const setup = document.getElementById('credential-setup');
const result = document.getElementById('credential-result');
const accountSetup = document.getElementById('account-setup');
const accountForm = document.getElementById('account-form');
const accountSelect = document.getElementById('account');
const accountResult = document.getElementById('account-result');
const policySetup = document.getElementById('policy-setup');
const policyForm = document.getElementById('policy-form');
const policyResult = document.getElementById('policy-result');
const consentSetup = document.getElementById('consent-setup');
let mutationCapable = false;
Promise.all([
  fetch('/api/health', {headers}).then(r => r.json()),
  fetch('/api/credential/status', {headers}).then(r => r.json()),
]).then(([health, credentials]) => {
  document.getElementById('status').textContent = health.classification || 'health unavailable';
  setup.hidden = credentials.enrolled === true;
  accountSetup.hidden = credentials.enrolled !== true || health.account_attested === true;
  policySetup.hidden = health.account_attested !== true;
  consentSetup.hidden = health.policy_configured !== true;
  mutationCapable = health.mutation_capable === true;
  document.getElementById('arm-practice').disabled = !mutationCapable;
}).catch(() => { document.getElementById('status').textContent = 'health unavailable'; });
document.getElementById('credential-form').addEventListener('submit', async event => {
  event.preventDefault();
  const username = document.getElementById('username');
  const apiKey = document.getElementById('api-key');
  try {
    const response = await fetch('/api/credentials/enroll', {
      method: 'POST',
      headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({username: username.value, api_key: apiKey.value}),
    });
    const value = await response.json();
    result.textContent = value.classification || 'credential enrollment failed';
    if (response.ok) {
      username.value = '';
      apiKey.value = '';
      setup.hidden = true;
      accountSetup.hidden = false;
    }
  } catch (_) {
    result.textContent = 'credential enrollment failed';
  } finally {
    apiKey.value = '';
  }
});
document.getElementById('discover-accounts').addEventListener('click', async () => {
  accountForm.hidden = true;
  accountSelect.replaceChildren();
  try {
    const response = await fetch('/api/accounts', {headers});
    const value = await response.json();
    if (!response.ok) throw new Error('discovery failed');
    for (const account of value.accounts || []) {
      const option = document.createElement('option');
      option.value = account.selection_handle;
      option.textContent = `${account.redacted_suffix} (${account.can_trade ? 'tradable' : 'not tradable'})`;
      option.dataset.suffix = account.redacted_suffix.slice(-4);
      accountSelect.appendChild(option);
    }
    accountForm.hidden = accountSelect.options.length === 0;
    accountResult.textContent = accountSelect.options.length ?
      `Type CONFIRM-${accountSelect.selectedOptions[0].dataset.suffix}` : 'No visible accounts found';
  } catch (_) {
    accountResult.textContent = 'Account discovery failed';
  }
});
accountSelect.addEventListener('change', () => {
  const selected = accountSelect.selectedOptions[0];
  if (selected) accountResult.textContent = `Type CONFIRM-${selected.dataset.suffix}`;
});
accountForm.addEventListener('submit', async event => {
  event.preventDefault();
  const confirmation = document.getElementById('account-confirmation');
  try {
    const response = await fetch('/api/account/attest', {
      method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({
        selection_handle: accountSelect.value,
        account_kind: document.getElementById('account-kind').value,
        typed_confirmation: confirmation.value,
      }),
    });
    const value = await response.json();
    accountResult.textContent = value.classification || 'Account attestation failed';
    if (response.ok) {
      accountForm.hidden = true;
      accountSetup.hidden = true;
      policySetup.hidden = false;
    }
  } catch (_) {
    accountResult.textContent = 'Account attestation failed';
  } finally {
    confirmation.value = '';
  }
});
document.getElementById('contract-search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const search = document.getElementById('contract-search').value;
  const instrument = document.getElementById('instrument');
  instrument.replaceChildren();
  try {
    const response = await fetch(`/api/contracts?search=${encodeURIComponent(search)}`, {headers});
    const value = await response.json();
    if (!response.ok) throw new Error('contract search failed');
    for (const contract of value.contracts || []) {
      const option = document.createElement('option');
      option.value = contract.contract_id;
      option.textContent = `${contract.name} (${contract.contract_id})`;
      instrument.appendChild(option);
    }
    policyForm.hidden = instrument.options.length === 0;
    policyResult.textContent = instrument.options.length ? 'Select the exact contract and enter your limits.' : 'No active simulated contracts found';
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (zone) document.getElementById('timezone').value = zone;
  } catch (_) {
    policyResult.textContent = 'Contract search failed';
  }
});
const numeric = id => Number(document.getElementById(id).value);
policyForm.addEventListener('submit', async event => {
  event.preventDefault();
  const weekdays = document.getElementById('weekdays').value.split(',').map(v => Number(v.trim()));
  const payload = {
    instrument: document.getElementById('instrument').value,
    rsi_period: numeric('rsi-period'), rsi_buy_below: numeric('rsi-buy'), rsi_sell_above: numeric('rsi-sell'),
    max_position: numeric('max-position'), max_orders_per_session: numeric('max-orders-session'),
    max_orders_per_day: numeric('max-orders-day'), max_daily_realized_loss: document.getElementById('max-daily-loss').value,
    max_consecutive_losses: numeric('max-consecutive-losses'), timezone: document.getElementById('timezone').value,
    weekdays, session_start: document.getElementById('session-start').value,
    session_end: document.getElementById('session-end').value, max_data_age_seconds: numeric('max-data-age'),
    max_clock_skew_seconds: numeric('max-clock-skew'), provider_error_cooldown_seconds: numeric('provider-cooldown'),
    telemetry_outage_behavior: document.getElementById('telemetry-behavior').value,
    telemetry_max_offline_seconds: numeric('telemetry-offline'),
    kill_cancel_open_orders: document.getElementById('kill-cancel').checked,
    kill_flatten_positions: document.getElementById('kill-flatten').checked,
  };
  try {
    const response = await fetch('/api/policy/save', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const value = await response.json();
    policyResult.textContent = value.classification || 'Policy save failed';
    if (response.ok) consentSetup.hidden = false;
  } catch (_) { policyResult.textContent = 'Policy save failed'; }
});
document.getElementById('accept-consent').addEventListener('click', async () => {
  const confirmation = document.getElementById('consent-confirmation');
  try {
    const response = await fetch('/api/consent/accept', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({typed_confirmation: confirmation.value})});
    const value = await response.json();
    document.getElementById('consent-result').textContent = value.classification || 'Consent failed';
    document.getElementById('arm-practice').disabled = !response.ok || !mutationCapable;
  } catch (_) { document.getElementById('consent-result').textContent = 'Consent failed'; }
  finally { confirmation.value = ''; }
});
document.getElementById('arm-practice').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/practice/arm', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: '{}'});
    const value = await response.json();
    document.getElementById('consent-result').textContent = value.classification || 'Practice arming failed';
    document.getElementById('run-practice').disabled = !response.ok;
  } catch (_) { document.getElementById('consent-result').textContent = 'Practice arming failed'; }
});
document.getElementById('run-practice').addEventListener('click', async () => {
  const confirmation = document.getElementById('practice-run-confirmation');
  try {
    const response = await fetch('/api/practice/run/once', {
      method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({
        confirmation: confirmation.value,
        rsi_period: numeric('rsi-period'),
        rsi_buy_below: numeric('rsi-buy'),
        rsi_sell_above: numeric('rsi-sell'),
      }),
    });
    const value = await response.json();
    document.getElementById('consent-result').textContent = value.classification || 'Practice run failed';
  } catch (_) { document.getElementById('consent-result').textContent = 'Practice run failed'; }
  finally { confirmation.value = ''; }
});
"""
