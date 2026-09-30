from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Iterable

from cryptography.fernet import Fernet


PRODUCTION_ENVS = {"production", "prod"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    database_url: str
    secret_key: str
    credentials_encryption_key: str | None
    cors_origins: tuple[str, ...]
    allow_create_all: bool
    rate_limit_requests_per_minute: int
    log_level: str
    resend_api_key: str | None
    resend_from_email: str
    frontend_url: str
    sentry_dsn: str | None = None
    sentry_enabled: bool = False
    sentry_environment: str = "development"
    sentry_release: str | None = None
    analytics_enabled: bool = True
    analytics_provider: str = "local"
    analytics_retention_days: int = 365
    billing_enabled: bool = False
    stripe_publishable_key: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    session_cookie_name: str = "tradebot_session"
    csrf_cookie_name: str = "tradebot_csrf"
    session_lifetime_minutes: int = 30
    account_deletion_grace_days: int = 7
    account_retention_days: int = 30
    account_legal_hold: bool = False
    key_management_provider: str = "local-development"
    key_management_key_id: str | None = None
    local_key_versions_json: str | None = None
    key_management_active_version: str | None = None
    tpm_device_path: str = "/dev/tpmrm0"
    tpm_key_handles_json: str | None = None
    tpm_public_key_files_json: str | None = None
    tpm_key_fingerprints_json: str | None = None
    tpm_auth_file: str | None = None
    recovery_key_id: str | None = None
    recovery_public_key_file: str | None = None
    recovery_public_key_fingerprint: str | None = None
    recovery_private_key_file: str | None = None
    legacy_fernet_mode: str = "migration"
    deployment_profile: str = "development"
    railway_key_versions_json: str | None = None
    topstep_credential_fingerprint_key: str | None = None
    topstep_beta_cohort_id: str | None = None
    topstep_approved_tester_user_id: int | None = None
    hosted_security_epoch: int | None = None
    topstep_session_renewal_window_minutes: int = 120
    topstep_session_renewal_lease_seconds: int = 60

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in PRODUCTION_ENVS


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return tuple()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _validate_fernet_key(key: str) -> None:
    try:
        Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ConfigError("CREDENTIALS_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def _contains_wildcard(values: Iterable[str]) -> bool:
    return any(value == "*" for value in values)


def _validate_railway_keys(raw: str | None, active_version: str | None) -> None:
    try:
        payload = json.loads(raw or "")
        if not isinstance(payload, dict) or not payload or active_version not in payload:
            raise ValueError
        decoded = {
            version: base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            for version, value in payload.items()
            if isinstance(version, str) and version and isinstance(value, str)
        }
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigError("RAILWAY_ENVELOPE_KEY_VERSIONS_JSON must be a version-to-base64 object.") from exc
    if len(decoded) != len(payload) or any(len(value) != 32 for value in decoded.values()):
        raise ConfigError("Every Railway envelope key must decode to exactly 32 bytes.")


def load_config() -> AppConfig:
    app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    database_url = os.getenv("DATABASE_URL", "")
    secret_key = os.getenv("SECRET_KEY", "")
    credentials_key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    cors_origins = _split_csv(os.getenv("CORS_ORIGINS"))
    allow_create_all = os.getenv("ALLOW_CREATE_ALL", "true").strip().lower() in {"1", "true", "yes"}
    rate_limit = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "300"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    resend_api_key = os.getenv("RESEND_API_KEY")
    resend_from_email = os.getenv("RESEND_FROM_EMAIL", "noreply@localhost").strip()
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    sentry_dsn = os.getenv("SENTRY_DSN")
    sentry_enabled = os.getenv("SENTRY_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    sentry_environment = os.getenv("SENTRY_ENVIRONMENT", app_env).strip()
    sentry_release = os.getenv("SENTRY_RELEASE")
    analytics_enabled = os.getenv("ANALYTICS_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    analytics_provider = os.getenv("ANALYTICS_PROVIDER", "local").strip().lower()
    analytics_retention_days = int(os.getenv("ANALYTICS_RETENTION_DAYS", "365"))
    billing_enabled = os.getenv("BILLING_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    stripe_publishable_key = os.getenv("STRIPE_PUBLISHABLE_KEY")
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "tradebot_session").strip()
    csrf_cookie_name = os.getenv("CSRF_COOKIE_NAME", "tradebot_csrf").strip()
    session_lifetime_minutes = int(os.getenv("SESSION_LIFETIME_MINUTES", "30"))
    account_deletion_grace_days = int(os.getenv("ACCOUNT_DELETION_GRACE_DAYS", "7"))
    account_retention_days = int(os.getenv("ACCOUNT_RETENTION_DAYS", "30"))
    account_legal_hold = os.getenv("ACCOUNT_LEGAL_HOLD", "false").strip().lower() in {"1", "true", "yes"}
    key_management_provider = os.getenv("KEY_MANAGEMENT_PROVIDER", "local-development").strip().lower()
    key_management_key_id = os.getenv("KEY_MANAGEMENT_KEY_ID")
    local_key_versions_json = os.getenv("LOCAL_KEY_VERSIONS_JSON")
    key_management_active_version = os.getenv("KEY_MANAGEMENT_ACTIVE_VERSION")
    tpm_device_path = os.getenv("TPM_DEVICE_PATH", "/dev/tpmrm0")
    tpm_key_handles_json = os.getenv("TPM_KEY_HANDLES_JSON")
    tpm_public_key_files_json = os.getenv("TPM_PUBLIC_KEY_FILES_JSON")
    tpm_key_fingerprints_json = os.getenv("TPM_KEY_FINGERPRINTS_JSON")
    tpm_auth_file = os.getenv("TPM_AUTH_FILE")
    recovery_key_id = os.getenv("RECOVERY_KEY_ID")
    recovery_public_key_file = os.getenv("RECOVERY_PUBLIC_KEY_FILE")
    recovery_public_key_fingerprint = os.getenv("RECOVERY_PUBLIC_KEY_FINGERPRINT")
    recovery_private_key_file = os.getenv("RECOVERY_PRIVATE_KEY_FILE")
    legacy_fernet_mode = os.getenv("LEGACY_FERNET_MODE", "migration").strip().lower()
    deployment_profile = os.getenv("DEPLOYMENT_PROFILE", "development").strip().lower()
    railway_key_versions_json = os.getenv("RAILWAY_ENVELOPE_KEY_VERSIONS_JSON")
    topstep_credential_fingerprint_key = os.getenv("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY")
    topstep_beta_cohort_id = os.getenv("TOPSTEP_BETA_COHORT_ID")
    approved_tester = os.getenv("TOPSTEP_APPROVED_TESTER_USER_ID")
    hosted_epoch = os.getenv("HOSTED_SECURITY_EPOCH")
    config = AppConfig(
        app_env=app_env,
        database_url=database_url,
        secret_key=secret_key,
        credentials_encryption_key=credentials_key,
        cors_origins=cors_origins,
        allow_create_all=allow_create_all,
        rate_limit_requests_per_minute=rate_limit,
        log_level=log_level,
        resend_api_key=resend_api_key,
        resend_from_email=resend_from_email,
        frontend_url=frontend_url,
        sentry_dsn=sentry_dsn,
        sentry_enabled=sentry_enabled,
        sentry_environment=sentry_environment,
        sentry_release=sentry_release,
        analytics_enabled=analytics_enabled,
        analytics_provider=analytics_provider,
        analytics_retention_days=analytics_retention_days,
        billing_enabled=billing_enabled,
        stripe_publishable_key=stripe_publishable_key,
        stripe_secret_key=stripe_secret_key,
        stripe_webhook_secret=stripe_webhook_secret,
        session_cookie_name=session_cookie_name,
        csrf_cookie_name=csrf_cookie_name,
        session_lifetime_minutes=session_lifetime_minutes,
        account_deletion_grace_days=account_deletion_grace_days,
        account_retention_days=account_retention_days,
        account_legal_hold=account_legal_hold,
        key_management_provider=key_management_provider,
        key_management_key_id=key_management_key_id,
        local_key_versions_json=local_key_versions_json,
        key_management_active_version=key_management_active_version,
        tpm_device_path=tpm_device_path,
        tpm_key_handles_json=tpm_key_handles_json,
        tpm_public_key_files_json=tpm_public_key_files_json,
        tpm_key_fingerprints_json=tpm_key_fingerprints_json,
        tpm_auth_file=tpm_auth_file,
        recovery_key_id=recovery_key_id,
        recovery_public_key_file=recovery_public_key_file,
        recovery_public_key_fingerprint=recovery_public_key_fingerprint,
        recovery_private_key_file=recovery_private_key_file,
        legacy_fernet_mode=legacy_fernet_mode,
        deployment_profile=deployment_profile,
        railway_key_versions_json=railway_key_versions_json,
        topstep_credential_fingerprint_key=topstep_credential_fingerprint_key,
        topstep_beta_cohort_id=topstep_beta_cohort_id,
        topstep_approved_tester_user_id=int(approved_tester) if approved_tester else None,
        hosted_security_epoch=int(hosted_epoch) if hosted_epoch else None,
        topstep_session_renewal_window_minutes=int(os.getenv("TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES", "120")),
        topstep_session_renewal_lease_seconds=int(os.getenv("TOPSTEP_SESSION_RENEWAL_LEASE_SECONDS", "60")),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if not config.database_url:
        raise ConfigError("DATABASE_URL is required.")
    if not config.secret_key:
        raise ConfigError("SECRET_KEY is required.")
    if config.credentials_encryption_key:
        _validate_fernet_key(config.credentials_encryption_key)
    if config.session_lifetime_minutes < 5 or config.session_lifetime_minutes > 1440:
        raise ConfigError("SESSION_LIFETIME_MINUTES must be between 5 and 1440.")
    if config.account_deletion_grace_days < 0 or config.account_retention_days < 0:
        raise ConfigError("Account lifecycle retention values cannot be negative.")
    if config.key_management_provider == "railway-secret-envelope-v1":
        if config.deployment_profile != "hosted_topstep_combine_beta":
            raise ConfigError("The Railway envelope provider is restricted to hosted_topstep_combine_beta.")
        if not config.key_management_key_id:
            raise ConfigError("KEY_MANAGEMENT_KEY_ID is required for the Railway envelope provider.")
        _validate_railway_keys(config.railway_key_versions_json, config.key_management_active_version)
        try:
            fingerprint_key = base64.urlsafe_b64decode(
                (config.topstep_credential_fingerprint_key or "")
                + "=" * (-len(config.topstep_credential_fingerprint_key or "") % 4)
            )
        except Exception as exc:
            raise ConfigError("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY must be base64 encoded.") from exc
        if len(fingerprint_key) < 32:
            raise ConfigError("TOPSTEP_CREDENTIAL_FINGERPRINT_KEY must decode to at least 32 bytes.")
        if not config.topstep_beta_cohort_id or not config.topstep_approved_tester_user_id:
            raise ConfigError("The hosted beta requires one explicit cohort and approved tester user ID.")
        if config.hosted_security_epoch is None or config.hosted_security_epoch <= 0:
            raise ConfigError("HOSTED_SECURITY_EPOCH must be a positive monotonic integer in hosted beta mode.")
        if not 5 <= config.topstep_session_renewal_window_minutes <= 720:
            raise ConfigError("TOPSTEP_SESSION_RENEWAL_WINDOW_MINUTES must be between 5 and 720.")
        if not 15 <= config.topstep_session_renewal_lease_seconds <= 600:
            raise ConfigError("TOPSTEP_SESSION_RENEWAL_LEASE_SECONDS must be between 15 and 600.")

    if config.is_production:
        if not config.cors_origins:
            raise ConfigError("CORS_ORIGINS is required in production.")
        if _contains_wildcard(config.cors_origins):
            raise ConfigError("CORS_ORIGINS cannot contain '*' in production.")
        if config.allow_create_all:
            raise ConfigError("ALLOW_CREATE_ALL must be false in production; run Alembic migrations instead.")
        if not config.resend_api_key:
            raise ConfigError("RESEND_API_KEY is required in production for account lifecycle email delivery.")
        if not config.resend_from_email or config.resend_from_email == "noreply@localhost":
            raise ConfigError("RESEND_FROM_EMAIL must be configured in production.")
        if config.billing_enabled:
            raise ConfigError("BILLING_ENABLED must remain false during invite-only paper beta.")
        if config.key_management_provider == "local-development":
            raise ConfigError("The TPM2 or approved hosted-beta KEY_MANAGEMENT_PROVIDER is required in production.")
        if config.key_management_provider not in {"tpm2", "railway-secret-envelope-v1"}:
            raise ConfigError("KEY_MANAGEMENT_PROVIDER is not approved for production.")
        if not config.key_management_key_id:
            raise ConfigError("KEY_MANAGEMENT_KEY_ID is required in production.")
        if config.key_management_provider == "tpm2":
            if config.deployment_profile == "hosted_topstep_combine_beta":
                raise ConfigError("The hosted Combine profile must use its explicit Railway envelope provider.")
            required_tpm = (config.key_management_active_version, config.tpm_device_path,
                            config.tpm_key_handles_json, config.tpm_public_key_files_json,
                            config.tpm_key_fingerprints_json, config.tpm_auth_file,
                            config.recovery_key_id, config.recovery_public_key_file,
                            config.recovery_public_key_fingerprint)
            if not all(required_tpm):
                raise ConfigError("Complete TPM and offline recovery public configuration is required in production.")
        else:
            forbidden_matches = {
                value for value in (config.secret_key, config.credentials_encryption_key,
                                    config.stripe_secret_key, config.stripe_webhook_secret)
                if value
            }
            if any(value in forbidden_matches for value in json.loads(
                    config.railway_key_versions_json or "{}").values()):
                raise ConfigError("The Railway envelope key must be separate from application secrets.")
        if config.recovery_private_key_file:
            raise ConfigError("Recovery private material is forbidden on the production host.")
        if config.legacy_fernet_mode not in {"migration", "envelope-only"}:
            raise ConfigError("LEGACY_FERNET_MODE must be migration or envelope-only in production.")
        if config.legacy_fernet_mode == "migration" and not config.credentials_encryption_key:
            raise ConfigError("CREDENTIALS_ENCRYPTION_KEY is required only during production migration.")
        if config.legacy_fernet_mode == "envelope-only" and config.credentials_encryption_key:
            raise ConfigError("CREDENTIALS_ENCRYPTION_KEY must be absent after envelope-only cutover.")


def default_cors_origins(config: AppConfig) -> list[str]:
    if config.cors_origins:
        return list(config.cors_origins)
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
