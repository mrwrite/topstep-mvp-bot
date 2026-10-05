from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest

from local_executor.__main__ import main
from local_executor.config import (
    ConfigurationError,
    ExecutorMode,
    LocalExecutorConfig,
)
from local_executor.lease import SingleInstanceLease
from local_executor.runtime import RuntimeFacts, evaluate_runtime
from local_executor.release import ReleaseVerification
from local_executor.safe_logging import LocalJsonFormatter, SecretRedactor
from local_executor.startup import prepare_startup


ROOT = Path(__file__).resolve().parents[2]


def config(tmp_path, *, mode=ExecutorMode.MUTATION, signed=True):
    return LocalExecutorConfig(
        mode=mode,
        bind_host="127.0.0.1",
        data_directory=tmp_path.resolve(),
        release_verification=(
            ReleaseVerification(True, "release_verified") if signed else None
        ),
    )


def facts(*, os_name="Windows", interactive=True, environment=None, container=False):
    return RuntimeFacts(
        operating_system=os_name,
        interactive=interactive,
        environment=environment or {},
        container_detected=container,
    )


def test_interactive_signed_windows_runtime_can_reach_mutation_gate(tmp_path):
    decision = evaluate_runtime(config(tmp_path), facts())
    assert decision.mutation_capable is True
    assert decision.classification == "personal_device_runtime_accepted"


def test_interactive_signed_macos_runtime_can_reach_mutation_gate(tmp_path):
    decision = evaluate_runtime(config(tmp_path), facts(os_name="Darwin"))
    assert decision.mutation_capable is True
    assert decision.classification == "personal_device_runtime_accepted"


@pytest.mark.parametrize(
    ("runtime_facts", "classification"),
    [
        (facts(environment={"CI": "true"}), "ci_environment"),
        (facts(environment={"GITHUB_ACTIONS": "1"}), "ci_environment"),
        (facts(environment={"RAILWAY_ENVIRONMENT": "production"}), "hosted_environment"),
        (facts(environment={"VERCEL": "1"}), "hosted_environment"),
        (facts(container=True), "container_environment"),
        (facts(environment={"SERVICE_ROLE": "worker"}), "hosted_service_role"),
        (facts(environment={"SERVICE_ROLE": "api"}), "hosted_service_role"),
        (facts(os_name="Linux"), "supported_desktop_os_required"),
        (facts(interactive=False), "interactive_session_required"),
    ],
)
def test_hosted_headless_and_non_windows_runtime_fail_closed(
    tmp_path, runtime_facts, classification
):
    decision = evaluate_runtime(config(tmp_path), runtime_facts)
    assert decision.mutation_capable is False
    assert decision.effective_mode is ExecutorMode.READ_ONLY
    assert decision.classification == classification


def test_unsigned_build_cannot_enable_mutations(tmp_path):
    decision = evaluate_runtime(config(tmp_path, signed=False), facts())
    assert decision.mutation_capable is False
    assert decision.classification == "signed_release_required"


def test_ci_can_use_deterministic_fake_provider_but_not_mutations(tmp_path):
    decision = evaluate_runtime(
        config(tmp_path, mode=ExecutorMode.FAKE_PROVIDER, signed=False),
        facts(environment={"CI": "true"}),
    )
    assert decision.effective_mode is ExecutorMode.FAKE_PROVIDER
    assert decision.mutation_capable is False
    assert "ci_environment" in decision.reasons


def test_non_loopback_configuration_rejected_before_startup(tmp_path):
    unsafe = LocalExecutorConfig(
        mode=ExecutorMode.READ_ONLY,
        bind_host="0.0.0.0",
        data_directory=tmp_path.resolve(),
    )
    with pytest.raises(ConfigurationError, match="127.0.0.1"):
        evaluate_runtime(unsafe, facts())


def test_configuration_rejects_environment_secret_custody(tmp_path):
    with pytest.raises(ConfigurationError, match="credential store"):
        LocalExecutorConfig.from_environment(
            {
                "LOCALAPPDATA": str(tmp_path),
                "TOPSTEP_API_KEY": "must-not-enter-config",
            }
        )


def test_packaged_status_mode_exits_without_starting_ui_or_loading_credentials(
    capsys,
):
    assert main(["--status-json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mutation_capable"] is False
    assert payload["effective_mode"] == "read_only"


def test_second_instance_is_read_only_and_never_loads_credentials(tmp_path):
    primary = SingleInstanceLease(tmp_path / "executor.lock")
    secondary = SingleInstanceLease(tmp_path / "executor.lock")
    assert primary.acquire() is True
    loaded = []
    try:
        result = prepare_startup(
            config(tmp_path),
            facts(),
            secondary,
            credential_loader=lambda: loaded.append(True),
        )
        assert result.classification == "secondary_instance_read_only"
        assert result.runtime.mutation_capable is False
        assert result.credentials_loaded is False
        assert loaded == []
    finally:
        primary.release()
        secondary.release()


def test_primary_loads_credentials_only_after_runtime_and_lease_gates(tmp_path):
    lease = SingleInstanceLease(tmp_path / "executor.lock")
    loaded = []
    try:
        result = prepare_startup(
            config(tmp_path),
            facts(),
            lease,
            credential_loader=lambda: loaded.append(True),
        )
        assert result.lease_owned is True
        assert result.credentials_loaded is True
        assert loaded == [True]
    finally:
        lease.release()


def test_rejected_runtime_does_not_create_lease_or_load_credentials(tmp_path):
    lease = SingleInstanceLease(tmp_path / "executor.lock")
    loaded = []
    result = prepare_startup(
        config(tmp_path),
        facts(environment={"RAILWAY_PROJECT_ID": "fixture"}),
        lease,
        credential_loader=lambda: loaded.append(True),
    )
    assert result.lease_owned is False
    assert result.credentials_loaded is False
    assert loaded == []
    assert not (tmp_path / "executor.lock").exists()


def test_structured_logging_redacts_at_serialization_time():
    formatter = LocalJsonFormatter(SecretRedactor(["raw-secret-value"]))
    record = logging.LogRecord(
        "local_executor",
        logging.ERROR,
        __file__,
        1,
        "provider failed token=raw-secret-value",
        (),
        None,
    )
    record.safe_fields = {
        "api_key": "raw-secret-value",
        "nested": {"authorization": "Bearer raw-secret-value"},
        "classification": "auth_failed",
    }
    serialized = formatter.format(record)
    payload = json.loads(serialized)
    assert "raw-secret-value" not in serialized
    assert payload["fields"]["api_key"] == "[REDACTED]"
    assert payload["fields"]["classification"] == "auth_failed"
    assert len(payload["correlation_id"]) == 32


def test_local_package_has_no_hosted_app_or_worker_imports():
    violations = []
    for path in (ROOT / "local_executor").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "app"
                or name.startswith("app.")
                or "worker_entrypoint" in name
                for name in names
            ):
                violations.append(f"{path.relative_to(ROOT)}: {names}")
    assert violations == []
