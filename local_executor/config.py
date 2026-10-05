from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import platform
from typing import Mapping

from .release import ReleaseVerification


class ExecutorMode(str, Enum):
    READ_ONLY = "read_only"
    FAKE_PROVIDER = "fake_provider"
    MUTATION = "mutation"


class ConfigurationError(ValueError):
    pass


_PROHIBITED_SECRET_VARIABLES = frozenset(
    {
        "TOPSTEP_API_KEY",
        "TOPSTEP_USERNAME",
        "TOPSTEP_SESSION_TOKEN",
        "LOCAL_EXECUTOR_TELEMETRY_CREDENTIAL",
    }
)


def default_data_directory(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    root = env.get("LOCALAPPDATA")
    if root:
        return Path(root) / "TopstepMvpBot" / "LocalExecutor"
    if platform.system().lower() == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "TopstepMvpBot"
            / "LocalExecutor"
        )
    # Linux remains a read-only development target.
    return Path.home() / ".topstep-mvp-bot" / "local-executor"


@dataclass(frozen=True)
class LocalExecutorConfig:
    mode: ExecutorMode = ExecutorMode.MUTATION
    bind_host: str = "127.0.0.1"
    data_directory: Path = Path(".")
    release_verification: ReleaseVerification | None = None

    @property
    def signed_release(self) -> bool:
        return bool(
            self.release_verification is not None
            and self.release_verification.accepted
            and self.release_verification.classification == "release_verified"
        )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "LocalExecutorConfig":
        env = os.environ if environment is None else environment
        prohibited = sorted(name for name in _PROHIBITED_SECRET_VARIABLES if env.get(name))
        if prohibited:
            raise ConfigurationError(
                "Provider and telemetry secrets must be enrolled through the local "
                "credential store, not environment variables."
            )
        # The signed interactive desktop build requests mutation capability by
        # default. Runtime, release, policy, consent, account, and reconciliation
        # gates still independently fail closed before any provider mutation.
        raw_mode = env.get("LOCAL_EXECUTOR_MODE", ExecutorMode.MUTATION.value)
        try:
            mode = ExecutorMode(raw_mode.strip().lower())
        except ValueError as exc:
            raise ConfigurationError("Unsupported local executor mode.") from exc
        data_directory = Path(
            env.get("LOCAL_EXECUTOR_DATA_DIR", str(default_data_directory(env)))
        ).expanduser()
        return cls(
            mode=mode,
            bind_host=env.get("LOCAL_EXECUTOR_BIND_HOST", "127.0.0.1").strip(),
            data_directory=data_directory,
            # A process environment value is not evidence of code signing.
            release_verification=None,
        )

    def with_verified_release(self, result: ReleaseVerification) -> "LocalExecutorConfig":
        if not result.accepted:
            raise ConfigurationError("A verified signed release is required.")
        return LocalExecutorConfig(
            mode=self.mode,
            bind_host=self.bind_host,
            data_directory=self.data_directory,
            release_verification=result,
        )

    def validate(self) -> None:
        if self.bind_host != "127.0.0.1":
            raise ConfigurationError("Local control binding must be exactly 127.0.0.1.")
        if not self.data_directory.is_absolute():
            raise ConfigurationError("Local executor data directory must be absolute.")
