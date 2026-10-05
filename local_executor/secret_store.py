from __future__ import annotations

from abc import ABC, abstractmethod
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import platform
from typing import Final


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretNotFound(KeyError):
    pass


class SecretStore(ABC):
    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_secret(self, name: str, value: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_secret(self, name: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def delete_secret(self, name: str) -> bool:
        raise NotImplementedError


_CRED_TYPE_GENERIC: Final = 1
_CRED_PERSIST_LOCAL_MACHINE: Final = 2
_ERROR_NOT_FOUND: Final = 1168


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


@dataclass(frozen=True)
class WindowsCredentialManager(SecretStore):
    target_prefix: str = "TopstepMvpBot/LocalExecutor"

    @property
    def available(self) -> bool:
        return os.name == "nt" and hasattr(ctypes, "WinDLL")

    def _api(self):
        if not self.available:
            raise SecretStoreUnavailable("windows_credential_manager_unavailable")
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(_PCREDENTIALW)]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def _target(self, name: str) -> str:
        if not name or any(char in name for char in "\\/:\0"):
            raise ValueError("invalid_secret_slot")
        return f"{self.target_prefix}/{name}"

    def set_secret(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("secret_value_required")
        api = self._api()
        blob = value.encode("utf-16-le")
        blob_buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIALW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = self._target(name)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "LocalExecutor"
        if not api.CredWriteW(ctypes.byref(credential), 0):
            raise SecretStoreUnavailable("credential_write_failed")

    def get_secret(self, name: str) -> str:
        api = self._api()
        pointer = _PCREDENTIALW()
        if not api.CredReadW(self._target(name), _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == _ERROR_NOT_FOUND:
                raise SecretNotFound(name)
            raise SecretStoreUnavailable("credential_read_failed")
        try:
            credential = pointer.contents
            blob = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return blob.decode("utf-16-le")
        finally:
            api.CredFree(pointer)

    def delete_secret(self, name: str) -> bool:
        api = self._api()
        if api.CredDeleteW(self._target(name), _CRED_TYPE_GENERIC, 0):
            return True
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return False
        raise SecretStoreUnavailable("credential_delete_failed")


_ERR_SEC_ITEM_NOT_FOUND: Final = -25300
_ERR_SEC_SUCCESS: Final = 0


@dataclass(frozen=True)
class MacOSKeychain(SecretStore):
    """Store executor secrets in the current user's login Keychain.

    The Security framework is called in-process so secret values never appear
    in command arguments, environment variables, or child-process output.
    """

    service_prefix: str = "com.topstep-mvp-bot.local-executor"
    account: str = "LocalExecutor"

    @property
    def available(self) -> bool:
        return platform.system().lower() == "darwin"

    def _api(self):
        if not self.available:
            raise SecretStoreUnavailable("macos_keychain_unavailable")
        try:
            api = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/Security.framework/Security"
            )
        except OSError as exc:
            raise SecretStoreUnavailable("macos_keychain_unavailable") from exc
        api.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        api.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        api.SecKeychainItemDelete.restype = ctypes.c_int32
        api.SecKeychainItemFreeContent.restype = ctypes.c_int32
        return api

    def _service(self, name: str) -> bytes:
        if not name or any(char in name for char in "\\/:\0"):
            raise ValueError("invalid_secret_slot")
        return f"{self.service_prefix}.{name}".encode("utf-8")

    def _find(self, name: str):
        api = self._api()
        service = self._service(name)
        account = self.account.encode("utf-8")
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = api.SecKeychainFindGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            ctypes.byref(length),
            ctypes.byref(data),
            ctypes.byref(item),
        )
        return api, status, length, data, item

    def set_secret(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("secret_value_required")
        self.delete_secret(name)
        api = self._api()
        service = self._service(name)
        account = self.account.encode("utf-8")
        secret = value.encode("utf-8")
        status = api.SecKeychainAddGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            len(secret),
            secret,
            None,
        )
        if status != _ERR_SEC_SUCCESS:
            raise SecretStoreUnavailable("credential_write_failed")

    def get_secret(self, name: str) -> str:
        api, status, length, data, item = self._find(name)
        if status == _ERR_SEC_ITEM_NOT_FOUND:
            raise SecretNotFound(name)
        if status != _ERR_SEC_SUCCESS:
            raise SecretStoreUnavailable("credential_read_failed")
        try:
            return ctypes.string_at(data, length.value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretStoreUnavailable("credential_read_failed") from exc
        finally:
            api.SecKeychainItemFreeContent(None, data)
            if item:
                ctypes.cdll.LoadLibrary(
                    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
                ).CFRelease(item)

    def delete_secret(self, name: str) -> bool:
        api, status, _length, data, item = self._find(name)
        if status == _ERR_SEC_ITEM_NOT_FOUND:
            return False
        if status != _ERR_SEC_SUCCESS:
            raise SecretStoreUnavailable("credential_delete_failed")
        try:
            delete_status = api.SecKeychainItemDelete(item)
            if delete_status != _ERR_SEC_SUCCESS:
                raise SecretStoreUnavailable("credential_delete_failed")
            return True
        finally:
            api.SecKeychainItemFreeContent(None, data)
            if item:
                ctypes.cdll.LoadLibrary(
                    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
                ).CFRelease(item)


def personal_device_secret_store() -> SecretStore:
    system = platform.system().lower()
    if system == "windows":
        return WindowsCredentialManager()
    if system == "darwin":
        return MacOSKeychain()
    raise SecretStoreUnavailable("supported_credential_store_unavailable")


class MemorySecretStore(SecretStore):
    """Deterministic fake for tests; never selected by the production entrypoint."""

    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self._values: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_available(self) -> None:
        if not self.available:
            raise SecretStoreUnavailable("credential_store_unavailable")

    def set_secret(self, name: str, value: str) -> None:
        self._ensure_available()
        if not value:
            raise ValueError("secret_value_required")
        self._values[name] = value

    def get_secret(self, name: str) -> str:
        self._ensure_available()
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFound(name) from exc

    def delete_secret(self, name: str) -> bool:
        self._ensure_available()
        return self._values.pop(name, None) is not None

    @property
    def slot_names(self) -> frozenset[str]:
        return frozenset(self._values)
