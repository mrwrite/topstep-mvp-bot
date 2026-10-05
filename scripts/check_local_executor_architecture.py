"""Mechanical trust-boundary checks for personal-device Combine execution."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MUTATION_METHODS = {
    "place_order", "cancel_order", "modify_order", "close_position",
    "partial_close_position",
}
MUTATION_CALLERS = {Path("local_executor/mutation.py")}
SECRET_FILE_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".kdbx"}
SECRET_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
)


def _imports_hosted_module(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        if any(module == "app" or module.startswith("app.") for module in modules):
            return True
    return False


def violations(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    local_root = root / "local_executor"
    for path in local_root.rglob("*.py"):
        relative = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            errors.append(f"local executor source is not parseable: {relative}")
            continue
        if _imports_hosted_module(path):
            errors.append(f"local executor imports hosted module: {relative}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in MUTATION_METHODS and relative not in MUTATION_CALLERS:
                errors.append(f"provider mutation call outside pipeline: {relative}:{node.lineno}")

    telemetry = (local_root / "telemetry.py").read_text(encoding="utf-8").lower()
    if ".post(" not in telemetry:
        errors.append("telemetry client must use outbound POST")
    for forbidden in (
        "_session.get(", "requests.get(", "websocket", "eventsource",
        "text/event-stream", "remote_command",
    ):
        if forbidden in telemetry:
            errors.append(f"outbound telemetry contains prohibited inbound channel: {forbidden}")

    control = (local_root / "control_surface.py").read_text(encoding="utf-8")
    if '"127.0.0.1"' not in control or "ThreadingHTTPServer" not in control:
        errors.append("control surface is not statically loopback-bound")

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8").lower()
    if "local_executor" in dockerfile:
        errors.append("hosted Docker image references local executor")

    for spec_name in ("windows_executor.spec", "macos_executor.spec"):
        spec = (local_root / spec_name).read_text(encoding="utf-8").lower()
        for forbidden in ('"app"', '"uvicorn"', '"fastapi"'):
            if forbidden not in spec:
                errors.append(f"{spec_name} does not exclude hosted dependency {forbidden}")

    scan_roots = [root / "local_executor", root / "tests" / "local_executor"]
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root)
            if path.suffix.lower() in SECRET_FILE_SUFFIXES:
                errors.append(f"secret-bearing file type in local build/test inputs: {relative}")
                continue
            if path.stat().st_size <= 2_000_000:
                raw = path.read_bytes()
                if any(marker in raw for marker in SECRET_MARKERS):
                    errors.append(f"private-key material in local build/test inputs: {relative}")
    return errors


if __name__ == "__main__":
    found = violations()
    if found:
        raise SystemExit("\n".join(found))
    print("Local executor architectural enforcement: PASS")
