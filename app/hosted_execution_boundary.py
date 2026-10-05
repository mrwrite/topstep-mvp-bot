"""Permanent fail-closed boundary for hosted Topstep execution.

Railway, Vercel, API, and worker processes may expose read-only telemetry and
account diagnostics. Provider mutations belong exclusively to the separately
packaged personal-device executor and cannot be enabled with configuration.
"""
from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any


LOCAL_EXECUTOR_REQUIRED = "local_executor_required"
HOSTED_MUTATION_FLAGS = (
    "PROVIDER_MUTATIONS_ENABLED",
    "TOPSTEP_PROVIDER_EXECUTION_ENABLED",
    "HOSTED_PROVIDER_EXECUTION_ENABLED",
    "LIVE_TRADING_ENABLED",
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _enabled(environment: Mapping[str, str], name: str) -> bool:
    return environment.get(name, "false").strip().lower() in _TRUTHY


def enforce_hosted_execution_boundary(
    adapter_type: type[Any],
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reject every attempt to make a hosted process order-capable."""
    env = os.environ if environment is None else environment
    if getattr(adapter_type, "mutation_capabilities_enabled", None) is not False:
        raise RuntimeError(
            f"{LOCAL_EXECUTOR_REQUIRED}: hosted Topstep adapter must remain read-only."
        )
    enabled_flags = [name for name in HOSTED_MUTATION_FLAGS if _enabled(env, name)]
    if enabled_flags:
        raise RuntimeError(
            f"{LOCAL_EXECUTOR_REQUIRED}: hosted Topstep execution cannot be enabled "
            f"by {', '.join(enabled_flags)}."
        )
    return {
        "classification": LOCAL_EXECUTOR_REQUIRED,
        "mutation_capable": False,
    }
