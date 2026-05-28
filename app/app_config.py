from __future__ import annotations

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


def load_config() -> AppConfig:
    app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    database_url = os.getenv("DATABASE_URL", "")
    secret_key = os.getenv("SECRET_KEY", "")
    credentials_key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    cors_origins = _split_csv(os.getenv("CORS_ORIGINS"))
    allow_create_all = os.getenv("ALLOW_CREATE_ALL", "true").strip().lower() in {"1", "true", "yes"}
    rate_limit = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "300"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    config = AppConfig(
        app_env=app_env,
        database_url=database_url,
        secret_key=secret_key,
        credentials_encryption_key=credentials_key,
        cors_origins=cors_origins,
        allow_create_all=allow_create_all,
        rate_limit_requests_per_minute=rate_limit,
        log_level=log_level,
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

    if config.is_production:
        if not config.credentials_encryption_key:
            raise ConfigError("CREDENTIALS_ENCRYPTION_KEY is required in production.")
        if not config.cors_origins:
            raise ConfigError("CORS_ORIGINS is required in production.")
        if _contains_wildcard(config.cors_origins):
            raise ConfigError("CORS_ORIGINS cannot contain '*' in production.")
        if config.allow_create_all:
            raise ConfigError("ALLOW_CREATE_ALL must be false in production; run Alembic migrations instead.")


def default_cors_origins(config: AppConfig) -> list[str]:
    if config.cors_origins:
        return list(config.cors_origins)
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
