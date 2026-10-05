from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import sys
from typing import Mapping

from .config import ExecutorMode, LocalExecutorConfig


_CI_INDICATORS = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "TF_BUILD",
    "JENKINS_URL",
)
_HOSTED_INDICATORS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_PROJECT_ID",
    "VERCEL",
    "VERCEL_ENV",
    "K_SERVICE",
    "FLY_APP_NAME",
    "DYNO",
    "AWS_EXECUTION_ENV",
    "WEBSITE_INSTANCE_ID",
)
_CONTAINER_INDICATORS = (
    "KUBERNETES_SERVICE_HOST",
    "DOTNET_RUNNING_IN_CONTAINER",
    "container",
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SUPPORTED_PERSONAL_DEVICE_SYSTEMS = frozenset({"windows", "darwin"})


def _present(environment: Mapping[str, str], name: str) -> bool:
    value = environment.get(name)
    return value is not None and value.strip() != "" and value.strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@dataclass(frozen=True)
class RuntimeFacts:
    operating_system: str
    interactive: bool
    environment: Mapping[str, str]
    container_detected: bool = False

    @classmethod
    def collect(cls, environment: Mapping[str, str] | None = None) -> "RuntimeFacts":
        env = dict(os.environ if environment is None else environment)
        try:
            interactive = bool(sys.stdin.isatty() and sys.stdout.isatty())
        except (AttributeError, OSError, ValueError):
            interactive = False
        container_detected = Path("/.dockerenv").exists() or any(
            _present(env, name) for name in _CONTAINER_INDICATORS
        )
        return cls(
            operating_system=platform.system(),
            interactive=interactive,
            environment=env,
            container_detected=container_detected,
        )


@dataclass(frozen=True)
class RuntimeDecision:
    requested_mode: ExecutorMode
    effective_mode: ExecutorMode
    mutation_capable: bool
    classification: str
    reasons: tuple[str, ...]


def evaluate_runtime(
    config: LocalExecutorConfig,
    facts: RuntimeFacts,
) -> RuntimeDecision:
    config.validate()
    reasons: list[str] = []
    env = facts.environment
    if any(_present(env, name) for name in _CI_INDICATORS):
        reasons.append("ci_environment")
    if any(_present(env, name) for name in _HOSTED_INDICATORS):
        reasons.append("hosted_environment")
    if facts.container_detected:
        reasons.append("container_environment")
    if env.get("SERVICE_ROLE", "").strip().lower() in {"api", "worker"}:
        reasons.append("hosted_service_role")
    if facts.operating_system.lower() not in _SUPPORTED_PERSONAL_DEVICE_SYSTEMS:
        reasons.append("supported_desktop_os_required")
    if not facts.interactive:
        reasons.append("interactive_session_required")
    if not config.signed_release:
        reasons.append("signed_release_required")

    if config.mode is not ExecutorMode.MUTATION:
        return RuntimeDecision(
            requested_mode=config.mode,
            effective_mode=config.mode,
            mutation_capable=False,
            classification=f"{config.mode.value}_requested",
            reasons=tuple(reasons),
        )
    if reasons:
        return RuntimeDecision(
            requested_mode=config.mode,
            effective_mode=ExecutorMode.READ_ONLY,
            mutation_capable=False,
            classification=reasons[0],
            reasons=tuple(reasons),
        )
    return RuntimeDecision(
        requested_mode=config.mode,
        effective_mode=ExecutorMode.MUTATION,
        mutation_capable=True,
        classification="personal_device_runtime_accepted",
        reasons=(),
    )
