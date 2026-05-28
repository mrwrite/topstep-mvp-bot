import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def _derive_key_from_secret(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    if not key:
        app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()
        if app_env in {"production", "prod"}:
            raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY must be set explicitly in production.")
        secret = os.getenv("SECRET_KEY")
        if not secret:
            raise RuntimeError("SECRET_KEY must be set to derive the credentials encryption key.")
        key = _derive_key_from_secret(secret).decode("utf-8")
    return Fernet(key.encode("utf-8"))


def encrypt_credentials(payload: dict[str, Any]) -> str:
    fernet = _get_fernet()
    serialized = json.dumps(payload).encode("utf-8")
    return fernet.encrypt(serialized).decode("utf-8")


def decrypt_credentials(blob: str) -> dict[str, Any]:
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(blob.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Invalid credentials payload.") from exc
    return json.loads(decrypted.decode("utf-8"))
