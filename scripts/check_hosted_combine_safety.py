"""Architecture checks for the hosted Combine read-only risk/dry-run boundary."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports_local_executor(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "local_executor" or alias.name.startswith("local_executor.")
                   for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "local_executor" or module.startswith("local_executor."):
                return True
    return False


def violations() -> list[str]:
    errors: list[str] = []
    dry_run = (ROOT / "app/hosted_combine_dryrun.py").read_text(encoding="utf-8")
    route = (ROOT / "app/hosted_combine_routes.py").read_text(encoding="utf-8")
    adapter = (ROOT / "app/providers/topstepx.py").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/worker_entrypoint.py").read_text(encoding="utf-8")
    boundary = (ROOT / "app/hosted_execution_boundary.py").read_text(encoding="utf-8")

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
    if "enforce_hosted_execution_boundary" not in main or "enforce_hosted_execution_boundary" not in worker:
        errors.append("API and worker startup must enforce the hosted execution boundary")
    for required in ("PROVIDER_MUTATIONS_ENABLED", "TOPSTEP_PROVIDER_EXECUTION_ENABLED",
                     "HOSTED_PROVIDER_EXECUTION_ENABLED", "LIVE_TRADING_ENABLED",
                     "local_executor_required"):
        if required not in boundary:
            errors.append(f"hosted execution boundary missing {required}")
    if "LOCAL_EXECUTOR_REQUIRED" not in adapter or "_local_executor_required(\"order submission\")" not in adapter:
        errors.append("Topstep place-order capability must return local_executor_required")

    for path in (ROOT / "app").rglob("*.py"):
        if _imports_local_executor(path):
            errors.append(f"hosted module imports local executor package: {path.relative_to(ROOT)}")
        source = path.read_text(encoding="utf-8")
        for forbidden in ("LocalTopstepMutationClient", "LocalMutationClient"):
            if forbidden in source:
                errors.append(
                    f"hosted module references local mutation client {forbidden}: {path.relative_to(ROOT)}"
                )

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    for forbidden in ("copy local_executor", "add local_executor"):
        if forbidden in dockerfile:
            errors.append(f"hosted Docker artifact packages local executor: {forbidden}")

    frontend_root = ROOT / "frontend" / "src"
    if frontend_root.exists():
        for path in frontend_root.rglob("*"):
            if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8")
            for forbidden in ("LocalTopstepMutationClient", "LocalMutationClient",
                              "local_executor.mutation", "/local-executor/mutate"):
                if forbidden in source:
                    errors.append(
                        f"hosted frontend references local mutation client {forbidden}: "
                        f"{path.relative_to(ROOT)}"
                    )
    return errors


if __name__ == "__main__":
    errors = violations()
    if errors:
        raise SystemExit("\n".join(errors))
    print("Hosted Combine dry-run architectural enforcement: PASS")
