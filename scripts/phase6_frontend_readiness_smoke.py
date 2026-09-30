from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_contains(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    dashboard = read("frontend/src/pages/Dashboard.tsx")
    integrations = read("frontend/src/pages/Integrations.tsx")
    styles = read("frontend/src/styles.css")

    dashboard_expectations = {
        "live-disabled messaging": "Live order routing remains disabled",
        "readiness checklist accessible name": 'aria-label="Live-readiness checklist"',
        "emergency stop accessible name": 'aria-label="Activate emergency stop kill switch"',
        "launch gate visibility": "Live gate blocked",
        "risk settings visibility": "Risk policy",
        "kill switch visibility": "Kill switch",
        "paper ledger visibility": "Paper equity",
        "migration checklist visibility": "Migrations",
        "reconciliation checklist visibility": "Reconciliation",
    }
    for label, needle in dashboard_expectations.items():
        assert_contains(dashboard, needle, label)

    integration_expectations = {
        "broker-neutral setup copy": "Connect a broker or signal source",
        "live-disabled integration copy": "Live execution remains disabled",
        "provider labels": "Interactive Brokers",
    }
    for label, needle in integration_expectations.items():
        assert_contains(integrations, needle, label)

    style_expectations = {
        "mobile media query": "@media (max-width: 720px)",
        "mobile button stacking": ".button-row",
        "focus-visible styling": "button:focus-visible",
    }
    for label, needle in style_expectations.items():
        assert_contains(styles, needle, label)

    print("Phase 6 frontend readiness smoke checks passed.")


if __name__ == "__main__":
    main()
