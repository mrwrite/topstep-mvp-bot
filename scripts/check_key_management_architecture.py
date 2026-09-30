"""Fail CI when production key-management boundaries regress."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".lock", ".json"}
ACTIVE_ROOTS = ("app", "scripts", "infra", "docs", ".github")
AWS_PATTERN = re.compile(r"(?i)\b(aws|boto3|botocore|roles.?anywhere|cloudformation)\b")
CLOUD_KMS_PATTERN = re.compile(r"(?i)\b(azure.?key.?vault|google.?cloud.?kms|gcp.?kms|hosted.?vault)\b")
DIRECT_TPM_PATTERN = re.compile(r"tpm2_(?:rsa|read|create|evict|getcap|selftest)")
SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)(?:log(?:ger)?\.|\bprint\().*(?:data_key|plaintext|recovery_private|tpm_auth|credentials_encrypted|api_key|session_token|root_key)"
)
HOSTED_KEY_VARIABLE = "RAILWAY_ENVELOPE_KEY_VERSIONS_JSON"
HOSTED_KEY_READERS = {"app/app_config.py", "app/crypto.py", "scripts/hosted_beta_preflight.py"}


def _files():
    for root_name in ACTIVE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path
    for name in ("requirements.txt", "requirements.lock", "requirements-dev.lock"):
        yield ROOT / name


def violations() -> list[str]:
    found: list[str] = []
    boundary = (ROOT / "app" / "key_management.py").resolve()
    checker = Path(__file__).resolve()
    for path in _files():
        if path.resolve() == checker:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(ROOT).as_posix()
        if AWS_PATTERN.search(text):
            found.append(f"{relative}: prohibited AWS artifact")
        if CLOUD_KMS_PATTERN.search(text):
            found.append(f"{relative}: prohibited hosted/cloud key service")
        if path.suffix == ".py" and path.resolve() != boundary and DIRECT_TPM_PATTERN.search(text):
            found.append(f"{relative}: direct TPM command outside provider boundary")
        if SENSITIVE_LOG_PATTERN.search(text):
            found.append(f"{relative}: possible sensitive key-management logging")
        if (HOSTED_KEY_VARIABLE in text and path.suffix == ".py"
                and relative not in HOSTED_KEY_READERS):
            found.append(f"{relative}: hosted root-key variable read outside approved configuration boundary")
    app_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore")
                         for path in (ROOT / "app").glob("*.py"))
    if "AwsKmsKeyProvider" in app_text:
        found.append("app: prohibited cloud provider implementation")
    if 'KEY_MANAGEMENT_PROVIDER", "local-development"' not in app_text:
        found.append("app: visibly named development provider guard missing")
    if "envelope:v2:" not in app_text:
        found.append("app: versioned envelope prefix missing")
    if "class RailwaySecretEnvelopeProvider" not in app_text:
        found.append("app: explicit hosted-beta provider missing")
    if 'provider_id = "railway-secret-envelope-v1"' not in app_text:
        found.append("app: explicit hosted-beta provider identity missing")
    if 'deployment_profile != "hosted_topstep_combine_beta"' not in app_text:
        found.append("app: hosted-beta deployment-profile guard missing")
    return sorted(set(found))


if __name__ == "__main__":
    problems = violations()
    if problems:
        raise SystemExit("\n".join(problems))
    print("key-management architectural enforcement: PASS")
