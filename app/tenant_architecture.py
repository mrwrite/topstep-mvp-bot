from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchitecturalViolation:
    path: str
    line: int
    rule: str
    detail: str


# These are pre-authentication or development-only identity bootstrap paths.
# They cannot serve authenticated beta tenant data and are covered by token
# secrecy, uniform error, or APP_ENV=test restrictions.
DIRECT_QUERY_ALLOWLIST: dict[str, frozenset[str]] = {
    "auth_routes.py": frozenset({
        "get_user_by_username", "_assert_session_active", "register", "verify_email",
        "request_password_reset", "confirm_password_reset", "account_recovery",
    }),
    "trading_routes.py": frozenset({"receive_signal"}),
}

REQUEST_MODULES = frozenset({
    "account_lifecycle_routes.py", "analytics_routes.py", "auth_routes.py",
    "beta_access_routes.py", "integrations_routes.py", "launch_gate_routes.py",
    "onboarding_routes.py", "reconciliation_routes.py", "risk_routes.py",
    "scheduler.py", "simulation_routes.py", "subscription_routes.py", "trading_routes.py",
})


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.functions: list[str] = []
        self.violations: list[ArchitecturalViolation] = []

    @property
    def function(self) -> str:
        return self.functions[-1] if self.functions else "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "query":
            allowed = DIRECT_QUERY_ALLOWLIST.get(self.path.name, frozenset())
            if self.function not in allowed:
                self.violations.append(ArchitecturalViolation(
                    str(self.path), node.lineno, "TENANT001",
                    f"direct ORM query in beta request function {self.function}",
                ))
        if isinstance(node.func, ast.Name) and node.func.id == "TenantContext":
            rendered = ast.unparse(node)
            if any(marker in rendered for marker in ("request.path_params", "request.query_params", "payload.tenant", "body.tenant")):
                self.violations.append(ArchitecturalViolation(
                    str(self.path), node.lineno, "TENANT002", "client-derived tenant context",
                ))
        self.generic_visit(node)


def inspect_source(path: Path, source: str | None = None) -> list[ArchitecturalViolation]:
    tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _Visitor(path)
    visitor.visit(tree)
    return visitor.violations


def inspect_beta_request_modules(app_root: Path) -> list[ArchitecturalViolation]:
    violations: list[ArchitecturalViolation] = []
    for name in sorted(REQUEST_MODULES):
        path = app_root / name
        violations.extend(inspect_source(path))
    return violations


def assert_tenant_architecture(app_root: Path) -> None:
    violations = inspect_beta_request_modules(app_root)
    if violations:
        detail = "\n".join(f"{item.path}:{item.line} {item.rule} {item.detail}" for item in violations)
        raise AssertionError(detail)
