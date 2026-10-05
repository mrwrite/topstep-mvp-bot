from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from .config import ExecutorMode, LocalExecutorConfig
from .lease import SingleInstanceLease
from .runtime import RuntimeDecision, RuntimeFacts, evaluate_runtime


@dataclass(frozen=True)
class StartupResult:
    runtime: RuntimeDecision
    lease_owned: bool
    credentials_loaded: bool
    classification: str


def prepare_startup(
    config: LocalExecutorConfig,
    facts: RuntimeFacts,
    lease: SingleInstanceLease,
    credential_loader: Callable[[], Any] | None = None,
) -> StartupResult:
    """Resolve all fail-closed gates before credential-store access."""
    decision = evaluate_runtime(config, facts)
    if not decision.mutation_capable:
        return StartupResult(decision, False, False, decision.classification)
    if not lease.acquire():
        downgraded = replace(
            decision,
            effective_mode=ExecutorMode.READ_ONLY,
            mutation_capable=False,
            classification="secondary_instance_read_only",
            reasons=("single_instance_lease_unavailable",),
        )
        return StartupResult(downgraded, False, False, downgraded.classification)
    if credential_loader is not None:
        credential_loader()
        loaded = True
    else:
        loaded = False
    return StartupResult(decision, True, loaded, decision.classification)
