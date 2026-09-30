#!/usr/bin/env python3
"""Hosted-beta deployment preflight. Reports names and classifications, never values."""
from __future__ import annotations

import json
import os
import re
import sys
import base64
import ipaddress
from urllib.parse import urlparse
from sqlalchemy import create_engine, text
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


PUBLIC = ("VITE_API_URL",)
PRIVATE = (
    "DATABASE_URL", "REDIS_URL", "SECRET_KEY", "KEY_MANAGEMENT_PROVIDER",
    "KEY_MANAGEMENT_KEY_ID", "KEY_MANAGEMENT_ACTIVE_VERSION", "RAILWAY_ENVELOPE_KEY_VERSIONS_JSON",
    "TOPSTEP_CREDENTIAL_FINGERPRINT_KEY", "HOSTED_SECURITY_EPOCH", "DEPLOYMENT_PROFILE",
    "APP_ENV", "SERVICE_ROLE", "TOPSTEP_BETA_COHORT_ID", "TOPSTEP_APPROVED_TESTER_USER_ID",
    "TOPSTEP_BASE_URL", "LIVE_TRADING_ENABLED", "PROVIDER_MUTATIONS_ENABLED", "CORS_ORIGINS",
    "FRONTEND_URL", "TRUSTED_PROXY_CIDRS",
)
PLACEHOLDER_MARKERS = ("replace", "placeholder", "changeme", "change-me", "example", "your-")


def _valid_url(name: str, value: str | None, *, https: bool = False) -> bool:
    try:
        parsed = urlparse(value or "")
        return bool(parsed.scheme in ({"https"} if https else {"postgres", "postgresql", "redis", "rediss"})
                    and parsed.hostname and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                    and "*" not in (value or ""))
    except ValueError:
        return False


def check_environment(env: dict[str, str]) -> list[dict]:
    result = []

    def add(name: str, classification: str, passed: bool, reason: str):
        result.append({"name": name, "classification": classification,
                       "status": "pass" if passed else "fail", "reason": reason})

    for name in PUBLIC:
        value = env.get(name, "")
        add(name, "public_build_configuration", _valid_url(name, value, https=True)
            and not any(marker in value.lower() for marker in PLACEHOLDER_MARKERS),
            "exact non-placeholder HTTPS URL required")
    extra_public = sorted(name for name in env if name.startswith("VITE_") and name not in PUBLIC)
    add("VITE_PUBLIC_VARIABLE_ALLOWLIST", "public_build_configuration", not extra_public,
        "only VITE_API_URL may be exposed to the frontend")
    for name in PRIVATE:
        value = env.get(name, "")
        add(name, "private_application_configuration", bool(value)
            and not any(marker in value.lower() for marker in PLACEHOLDER_MARKERS),
            "required; value never displayed")
    db_url = env.get("DATABASE_URL", "")
    redis_url = env.get("REDIS_URL", "")
    db_host = urlparse(db_url).hostname or ""
    redis_host = urlparse(redis_url).hostname or ""
    add("DATABASE_URL", "database_connection", _valid_url("DATABASE_URL", db_url)
        and db_host.endswith(".railway.internal"), "private Railway PostgreSQL URL required")
    add("REDIS_URL", "redis_connection", _valid_url("REDIS_URL", redis_url)
        and redis_host.endswith(".railway.internal"), "private Railway Redis URL required")
    add("DEPLOYMENT_PROFILE", "deployment_control",
        env.get("DEPLOYMENT_PROFILE") == "hosted_topstep_combine_beta", "hosted beta profile required")
    add("APP_ENV", "deployment_control", env.get("APP_ENV", "").lower() in {"production", "prod"},
        "hosted release must run with the production environment")
    add("SERVICE_ROLE", "deployment_control", env.get("SERVICE_ROLE") in {"api", "worker"},
        "production role must be api or worker")
    add("KEY_MANAGEMENT_PROVIDER", "cryptographic_configuration",
        env.get("KEY_MANAGEMENT_PROVIDER") == "railway-secret-envelope-v1",
        "explicit hosted-beta envelope provider required")
    add("HOSTED_SECURITY_EPOCH", "deployment_control",
        bool(re.fullmatch(r"[1-9][0-9]*", env.get("HOSTED_SECURITY_EPOCH", ""))),
        "positive monotonic decimal epoch required")
    add("LIVE_TRADING_ENABLED", "execution_policy", env.get("LIVE_TRADING_ENABLED", "").lower() == "false",
        "must be false")
    add("PROVIDER_MUTATIONS_ENABLED", "execution_policy",
        env.get("PROVIDER_MUTATIONS_ENABLED", "").lower() == "false", "must be false")
    add("TOPSTEP_BASE_URL", "provider_configuration",
        env.get("TOPSTEP_BASE_URL", "").rstrip("/") == "https://api.topstepx.com",
        "official HTTPS API origin required")
    origins = [item.strip() for item in env.get("CORS_ORIGINS", "").split(",") if item.strip()]
    origin_ok = bool(origins) and all(_valid_url("CORS_ORIGINS", x, https=True)
                                     and not any(m in x.lower() for m in PLACEHOLDER_MARKERS)
                                     for x in origins)
    add("CORS_ORIGINS", "private_application_configuration", origin_ok,
        "exact approved HTTPS origins only; no wildcard, preview catch-all, or localhost")
    add("FRONTEND_URL", "private_application_configuration",
        env.get("FRONTEND_URL", "").rstrip("/") in origins,
        "frontend URL must exactly match one approved CORS origin")
    try:
        proxy_ranges = [ipaddress.ip_network(value.strip(), strict=False)
                        for value in env.get("TRUSTED_PROXY_CIDRS", "").split(",") if value.strip()]
        proxies_valid = bool(proxy_ranges)
    except ValueError:
        proxies_valid = False
    add("TRUSTED_PROXY_CIDRS", "private_application_configuration", proxies_valid,
        "one or more valid trusted proxy CIDRs are required")
    key_json_ok = False
    try:
        key_map = json.loads(env.get("RAILWAY_ENVELOPE_KEY_VERSIONS_JSON", ""))
        key_json_ok = (isinstance(key_map, dict) and bool(key_map)
                       and env.get("KEY_MANAGEMENT_ACTIVE_VERSION") in key_map)
    except (ValueError, TypeError):
        key_map = {}
    add("RAILWAY_ENVELOPE_KEY_VERSIONS_JSON", "cryptographic_secret", key_json_ok,
        "version map must contain active version; secret contents never displayed")
    separated = bool(env.get("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY")) and all(
        env.get("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY") != env.get(key)
        for key in ("SECRET_KEY", "RAILWAY_ENVELOPE_KEY_VERSIONS_JSON", "DATABASE_URL", "REDIS_URL")
    )
    add("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY", "cryptographic_secret", separated,
        "must be distinct from application, database, Redis, and envelope secrets")
    try:
        fingerprint = base64.urlsafe_b64decode(env["TOPSTEP_CREDENTIAL_FINGERPRINT_KEY"] +
                                                "=" * (-len(env["TOPSTEP_CREDENTIAL_FINGERPRINT_KEY"]) % 4))
        decoded_values = [base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
                          for value in key_map.values()]
        app_secret = env.get("SECRET_KEY", "").encode("utf-8")
        no_key_reuse = (bool(decoded_values) and all(fingerprint != value for value in decoded_values)
                        and all(app_secret != value for value in decoded_values))
    except Exception:
        no_key_reuse = False
    add("HOSTED_KEY_SEPARATION", "cryptographic_secret", no_key_reuse,
        "decoded fingerprint and wrapping keys must be distinct; values withheld")
    add("SECRET_KEY_STRENGTH", "cryptographic_secret", len(env.get("SECRET_KEY", "")) >= 32,
        "application signing secret must contain at least 32 characters; value withheld")
    fingerprint_ok = False
    try:
        fingerprint_ok = len(base64.urlsafe_b64decode(env["TOPSTEP_CREDENTIAL_FINGERPRINT_KEY"] +
                                                       "=" * (-len(env["TOPSTEP_CREDENTIAL_FINGERPRINT_KEY"]) % 4))) >= 32
    except Exception:
        pass
    add("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY_LENGTH", "cryptographic_secret", fingerprint_ok,
        "HMAC fingerprint key must decode to at least 32 bytes; value withheld")
    from scripts.check_frontend_secret_scan import scan_frontend
    bundle_ok, bundle_reason = scan_frontend(env)
    add("FRONTEND_BUNDLE_SECRET_SCAN", "secret_scan", bundle_ok, bundle_reason)
    return result


def main() -> int:
    env = dict(os.environ)
    checks = check_environment(env)
    policy_status, policy_reason = check_active_policy(env)
    checks.append({"name": "HOSTED_COMBINE_RISK_POLICY", "classification": "cohort_risk_policy",
                   "status": "pass" if policy_status else "fail", "reason": policy_reason})
    failed = [item for item in checks if item["status"] == "fail"]
    payload = {"status": "fail" if failed else "pass", "checks": checks,
               "risk_policy": "verified" if policy_status else "failed", "provider_readiness": "not_verified",
               "provider_order_execution_enabled": False}
    if os.getenv("PREFLIGHT_JSON", "").lower() in {"1", "true", "yes"}:
        print(json.dumps(payload, sort_keys=True))
    else:
        for item in checks:
            print(f"{item['status'].upper():4} {item['name']} [{item['classification']}]: {item['reason']}")
        print(f"Overall: {payload['status'].upper()}; failed checks: {len(failed)}")
        print("No environment values are emitted. Active risk-policy/database and real provider readiness need separate checks.")
    return 1 if failed else 0


def check_active_policy(env: dict[str, str]) -> tuple[bool, str]:
    url = env.get("DATABASE_URL", "")
    tester = env.get("TOPSTEP_APPROVED_TESTER_USER_ID", "")
    cohort = env.get("TOPSTEP_BETA_COHORT_ID", "")
    if not url or not tester or not cohort:
        return False, "database, approved tester, and cohort configuration are required"
    engine = None
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.policy FROM hosted_combine_risk_policies p "
                "JOIN platform_integrations i ON i.id=p.integration_id AND i.user_id=p.user_id "
                "JOIN topstep_account_approvals a ON a.user_id=p.user_id AND a.integration_id=p.integration_id "
                "AND a.provider_account_id=p.provider_account_id "
                "WHERE p.user_id=:tester AND p.tester_user_id=:tester AND p.cohort_id=:cohort "
                "AND p.state='active' AND i.status='approved' AND a.state='approved' "
                "AND a.revoked_at IS NULL AND p.provider_account_id<>'' "
                "AND p.effective_at<=CURRENT_TIMESTAMP "
                "AND (p.expires_at IS NULL OR p.expires_at>CURRENT_TIMESTAMP) "
                "AND a.expires_at>CURRENT_TIMESTAMP"
            ), {"tester": int(tester), "cohort": cohort}).all()
        for (policy,) in rows:
            if isinstance(policy, str):
                policy = json.loads(policy)
            if (isinstance(policy, dict) and policy.get("dry_run_enabled") is True
                    and policy.get("provider_order_execution_enabled") is False
                    and policy.get("allowed_strategies") and policy.get("allowed_instruments")
                    and policy.get("max_order_quantity") == 1):
                return True, "active exact-cohort policy and account approval found; values withheld"
        return False, "no active exact-cohort policy with non-empty allowlists and provider mutations disabled"
    except Exception:
        return False, "policy database check unavailable or schema not migrated; details withheld"
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
