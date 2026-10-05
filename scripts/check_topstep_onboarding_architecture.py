"""Static guardrails for the durable Topstep onboarding trust boundary."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVED_CREDENTIAL_READERS = {
    "app/models.py", "app/topstep_onboarding.py", "app/topstep_session_security.py"
}
APPROVED_SESSION_WRITERS = {
    "app/models.py", "app/topstep_onboarding.py", "app/topstep_session_security.py",
    "app/topstep_onboarding_routes.py",
}


def scan_text(relative: str, text: str) -> list[str]:
    failures: list[str] = []
    if "/api/Order/place" in text:
        failures.append(f"{relative}: provider order submission exists before the execution gate")
    if "approvedAccountId" in text:
        failures.append(f"{relative}: process-local/configured account approval is prohibited")
    if relative.startswith("app/") and relative not in APPROVED_CREDENTIAL_READERS:
        if re.search(r"TopstepCredential\s*\.\s*(?:api_key_encrypted|username_encrypted)", text):
            failures.append(f"{relative}: credential read outside approved onboarding service")
    if relative.startswith("app/") and relative not in APPROVED_SESSION_WRITERS:
        if re.search(r"TopstepProviderSession\s*\.", text):
            failures.append(f"{relative}: provider session access outside durable session boundary")
    if relative.startswith("app/") and relative != "app/providers/topstepx.py":
        if "_session_token_cache" in text:
            failures.append(f"{relative}: authoritative in-memory Topstep session is prohibited")
    if re.search(r"(?i)(?:log(?:ger)?\.|\bprint\().*(?:api.?key|session.?token|token_encrypted|api_key_encrypted)", text):
        failures.append(f"{relative}: possible Topstep secret logging")
    if re.search(r"(?i)(?:combine|approved).*account.*name|account.*name.*(?:combine|approved)", text):
        failures.append(f"{relative}: account-name authorization is prohibited")
    return failures


def violations(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for folder in ("app", "frontend/src"):
        for path in (root / folder).rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            failures.extend(scan_text(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
    service = (root / "app/topstep_onboarding.py").read_text(encoding="utf-8")
    for required in (
        "def execution_eligibility(", "def replace_credentials(", "def disconnect(", "def delete(",
        "TopstepIntegrationTombstone", "credential_generation", "_suppress_execution",
        "onboarding_request_identity",
    ):
        if required not in service:
            failures.append(f"app/topstep_onboarding.py: missing authoritative boundary {required}")
    adapter = (root / "app/providers/topstepx.py").read_text(encoding="utf-8")
    if adapter.count('"live": False') < 2:
        failures.append("app/providers/topstepx.py: simulated market selection guard missing")
    if "local_executor_required" not in adapter:
        failures.append("app/providers/topstepx.py: order-submission fail-closed guard missing")
    session_security = (root / "app/topstep_session_security.py").read_text(encoding="utf-8")
    for required in (
        "def acquire_renewal_lease(", "fencing_token", "def require_current_epoch(",
        "def reconcile_restored_database(", "def credential_work_is_current(",
    ):
        if required not in session_security:
            failures.append(f"app/topstep_session_security.py: missing session/restore boundary {required}")
    durable = (root / "app/durable_simulation.py").read_text(encoding="utf-8")
    if durable.count("credential_work_is_current") < 2:
        failures.append("app/durable_simulation.py: commands and outbox must enforce credential epoch")
    return sorted(set(failures))


if __name__ == "__main__":
    found = violations()
    if found:
        raise SystemExit("\n".join(found))
    print("Topstep onboarding architectural enforcement: PASS")
