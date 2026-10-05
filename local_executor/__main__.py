from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from threading import Event
import webbrowser

from .config import ConfigurationError, LocalExecutorConfig
from .application import LocalExecutorApplication
from .control_surface import LocalControlSurface, LocalOperatorController
from .credentials import CredentialEnrollment
from .lease import SingleInstanceLease
from .runtime import RuntimeFacts
from .release import load_and_verify_release
from .secret_store import SecretNotFound, personal_device_secret_store
from .startup import prepare_startup


def _status_payload(result) -> dict[str, object]:
    return {
        "classification": result.classification,
        "effective_mode": result.runtime.effective_mode.value,
        "mutation_capable": result.runtime.mutation_capable,
        "version": __import__("local_executor").__version__,
    }


def _installed_release(config: LocalExecutorConfig):
    executable = Path(sys.executable).resolve()
    candidates = [executable.with_name("release-manifest.json")]
    # A signed macOS bundle uses a detached manifest beside the .app so adding
    # the manifest does not invalidate the Apple code-signature seal.
    if sys.platform == "darwin" and len(executable.parents) >= 3:
        candidates.append(executable.parents[2] / "release-manifest.json")
    manifest = next((path for path in candidates if path.is_file()), None)
    if manifest is None:
        return None
    return load_and_verify_release(
        manifest,
        executable,
        expected_version=__import__("local_executor").__version__,
        policy_version=1,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="topstep-local-executor")
    parser.add_argument(
        "--status-json",
        action="store_true",
        help="Print fail-closed runtime status and exit without loading credentials.",
    )
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        config = LocalExecutorConfig.from_environment()
    except ConfigurationError:
        if args.status_json:
            print(json.dumps({
                "classification": "configuration_rejected",
                "effective_mode": "read_only",
                "mutation_capable": False,
                "version": __import__("local_executor").__version__,
            }, sort_keys=True))
            return 0
        raise
    release = _installed_release(config)
    if release is not None and release.accepted:
        config = config.with_verified_release(release)
    facts = RuntimeFacts.collect()
    lease = SingleInstanceLease(config.data_directory / "executor.lock")
    result = prepare_startup(config, facts, lease)
    if args.status_json:
        print(json.dumps(_status_payload(result), sort_keys=True))
        lease.release()
        return 0

    enrollment = CredentialEnrollment(personal_device_secret_store())

    def credential_status() -> dict[str, object]:
        try:
            enrollment.load_topstep()
        except SecretNotFound:
            return {"classification": "credentials_required", "enrolled": False}
        except Exception:
            return {"classification": "credential_store_unavailable", "enrolled": False}
        return {"classification": "credentials_enrolled", "enrolled": True}

    application = LocalExecutorApplication(
        data_directory=config.data_directory,
        enrollment=enrollment,
        runtime=result.runtime,
    )
    controller = LocalOperatorController(
        enrollment,
        reads={
            "health": application.health,
            "credential_status": credential_status,
            "accounts": application.discover_accounts,
            "policy": application.policy_status,
            "contracts": application.search_contracts,
            "qualification": application.qualification_status,
            "reconciliation": application.reconciliation_status,
        },
        actions={
            "account_attest": application.attest_account,
            "policy_save": application.save_policy,
            "consent_accept": application.accept_consent,
            "practice_arm": application.arm_practice,
            "practice_run_once": application.run_practice_once,
        },
        on_credentials_changed=application.credentials_changed,
    )
    surface = LocalControlSurface(controller)
    try:
        surface.start()
        if not args.no_browser:
            webbrowser.open(surface.launch_url, new=1, autoraise=True)
        Event().wait()
    except KeyboardInterrupt:
        return 0
    finally:
        surface.stop()
        application.close()
        lease.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
