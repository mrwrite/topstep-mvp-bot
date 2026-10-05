from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


REQUIRED_PREFLIGHT_CHECKS = (
    "runtime_origin",
    "signed_version",
    "clock",
    "credential_store",
    "database",
    "single_instance_lease",
    "policy",
    "consent",
    "exact_account",
    "rate_budget",
    "provider_connectivity",
    "telemetry_policy",
    "reconciliation",
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    classification: str


@dataclass(frozen=True)
class PreflightReport:
    mutation_ready: bool
    classification: str
    checks: tuple[PreflightCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mutation_ready": self.mutation_ready,
            "classification": self.classification,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "classification": check.classification,
                }
                for check in self.checks
            ],
        }


class StartupPreflight:
    """Runs a fixed, redacted set of mutation-readiness checks."""

    def __init__(self, checks: Mapping[str, Callable[[], bool | str]]) -> None:
        missing = [name for name in REQUIRED_PREFLIGHT_CHECKS if name not in checks]
        extra = [name for name in checks if name not in REQUIRED_PREFLIGHT_CHECKS]
        if missing or extra:
            raise ValueError("preflight_check_set_incomplete")
        self._checks = dict(checks)

    def run(self) -> PreflightReport:
        results: list[PreflightCheck] = []
        for name in REQUIRED_PREFLIGHT_CHECKS:
            try:
                value = self._checks[name]()
                if value is True:
                    result = PreflightCheck(name, True, "ok")
                elif value is False:
                    result = PreflightCheck(name, False, f"{name}_failed")
                elif isinstance(value, str) and value and _safe_classification(value):
                    result = PreflightCheck(name, value == "ok", value)
                else:
                    result = PreflightCheck(name, False, f"{name}_invalid_result")
            except Exception:
                # Exception strings can include credentials, URLs, account IDs, or
                # provider payloads. They never cross the preflight boundary.
                result = PreflightCheck(name, False, f"{name}_check_error")
            results.append(result)
        failed = next((check for check in results if not check.passed), None)
        return PreflightReport(
            mutation_ready=failed is None,
            classification="preflight_passed" if failed is None else failed.classification,
            checks=tuple(results),
        )


def _safe_classification(value: str) -> bool:
    return len(value) <= 64 and all(character.islower() or character.isdigit()
                                    or character == "_" for character in value)
