"""Architecture checks for the hosted Combine read-only risk/dry-run boundary."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def violations() -> list[str]:
    errors: list[str] = []
    dry_run = (ROOT / "app/hosted_combine_dryrun.py").read_text(encoding="utf-8")
    route = (ROOT / "app/hosted_combine_routes.py").read_text(encoding="utf-8")
    adapter = (ROOT / "app/providers/topstepx.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/worker_entrypoint.py").read_text(encoding="utf-8")

    for forbidden in ("models.PaperOrder(", "models.PaperFill(", "models.PaperPosition(",
                      "models.PaperLedgerEntry(", "TopStepXAdapter", ".place_order(",
                      ".cancel_order(", ".modify_order(", ".close_position("):
        if forbidden in dry_run or forbidden in route:
            errors.append(f"hosted dry-run path references forbidden mutation/storage: {forbidden}")
    for required in ("provider_order_execution_enabled", "dry_run_only", "fencing_token",
                     "execution_eligibility", "security_epoch", "market_identity"):
        if required not in dry_run:
            errors.append(f"hosted dry-run boundary missing {required}")
    if "mutation_capabilities_enabled = False" not in adapter:
        errors.append("Topstep adapter must declare mutation capabilities disabled")
    topstep_decl = adapter.split("class TopStepXAdapter", 1)[1].split("def __init__", 1)[0]
    if "IntegrationCapability.BROKER_TRADING" in topstep_decl:
        errors.append("Topstep adapter class must not advertise broker-trading capability")
    if "PROVIDER_MUTATIONS_ENABLED" not in main or "PROVIDER_MUTATIONS_ENABLED" not in worker:
        errors.append("API and worker startup must reject provider mutation enablement")
    if "provider order submission is disabled" not in adapter:
        errors.append("Topstep place-order capability must remain fail-closed")
    return errors


if __name__ == "__main__":
    errors = violations()
    if errors:
        raise SystemExit("\n".join(errors))
    print("Hosted Combine dry-run architectural enforcement: PASS")
