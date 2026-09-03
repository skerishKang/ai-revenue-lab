from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import os
import re
from typing import Any, Protocol

from .contracts import ContractError

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_MAX_SECRET_BYTES = 4096
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _secret(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("device credential must be text")
    encoded = value.encode("utf-8")
    if len(encoded) < 8 or len(encoded) > _MAX_SECRET_BYTES:
        raise ContractError("device credential must be between 8 and 4096 UTF-8 bytes")
    return value


def _target_name(binding_ref: str) -> str:
    binding_ref = _ref(binding_ref, "binding_ref")
    digest = hashlib.sha256(binding_ref.encode("utf-8")).hexdigest()
    return f"Padiem.LocalAgent/{digest}"


class DeviceCredentialStore(Protocol):
    def put(self, *, binding_ref: str, credential: str) -> None:
        ...

    def read(self, *, binding_ref: str) -> str:
        ...

    def delete(self, *, binding_ref: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class CredentialStoreReceipt:
    binding_ref: str
    target_ref: str
    operation: str
    os_user_scope: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "target_ref", _ref(self.target_ref, "target_ref"))
        if self.operation not in {"put", "read", "delete"}:
            raise ContractError("invalid credential store operation")
        if not isinstance(self.os_user_scope, bool):
            raise ContractError("os_user_scope must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "target_ref": self.target_ref,
            "operation": self.operation,
            "os_user_scope": self.os_user_scope,
            "raw_device_secret": False,
            "plaintext_file_storage": False,
            "admin_elevation": False,
        }


class DeterministicMemoryDeviceCredentialStore:
    """Repository-test fake only. Safe projections never expose the raw value."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self.operations: list[CredentialStoreReceipt] = []

    def put(self, *, binding_ref: str, credential: str) -> None:
        binding_ref = _ref(binding_ref, "binding_ref")
        self._values[binding_ref] = _secret(credential)
        self.operations.append(
            CredentialStoreReceipt(
                binding_ref=binding_ref,
                target_ref=f"fake:{hashlib.sha256(binding_ref.encode()).hexdigest()[:24]}",
                operation="put",
                os_user_scope=False,
            )
        )

    def read(self, *, binding_ref: str) -> str:
        binding_ref = _ref(binding_ref, "binding_ref")
        try:
            value = self._values[binding_ref]
        except KeyError as exc:
            raise ContractError("device credential is not available") from exc
        self.operations.append(
            CredentialStoreReceipt(
                binding_ref=binding_ref,
                target_ref=f"fake:{hashlib.sha256(binding_ref.encode()).hexdigest()[:24]}",
                operation="read",
                os_user_scope=False,
            )
        )
        return value

    def delete(self, *, binding_ref: str) -> None:
        binding_ref = _ref(binding_ref, "binding_ref")
        self._values.pop(binding_ref, None)
        self.operations.append(
            CredentialStoreReceipt(
                binding_ref=binding_ref,
                target_ref=f"fake:{hashlib.sha256(binding_ref.encode()).hexdigest()[:24]}",
                operation="delete",
                os_user_scope=False,
            )
        )

    def safe_state(self) -> dict[str, Any]:
        return {
            "stored_binding_count": len(self._values),
            "raw_device_secret": False,
            "production_store": False,
        }


class WindowsCredentialManagerDeviceStore:
    """Windows user-context generic credential storage for Local Agent device secrets.

    Credential Manager is invoked through the native Win32 credential API. The
    Padiem binding ref is hashed into the target name so the OS vault does not
    need to store product/account identifiers in plaintext target metadata.
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise ContractError("Windows Credential Manager device store is Windows-only")
        self._cred_write, self._cred_read, self._cred_delete, self._cred_free, self._credential_type = self._api()

    @staticmethod
    def _api() -> tuple[Any, Any, Any, Any, type[Any]]:
        from ctypes import wintypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", wintypes.LPVOID),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        pcredential = ctypes.POINTER(CREDENTIALW)
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        cred_write = advapi32.CredWriteW
        cred_write.argtypes = [pcredential, wintypes.DWORD]
        cred_write.restype = wintypes.BOOL
        cred_read = advapi32.CredReadW
        cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pcredential)]
        cred_read.restype = wintypes.BOOL
        cred_delete = advapi32.CredDeleteW
        cred_delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        cred_delete.restype = wintypes.BOOL
        cred_free = advapi32.CredFree
        cred_free.argtypes = [wintypes.LPVOID]
        cred_free.restype = None
        return cred_write, cred_read, cred_delete, cred_free, CREDENTIALW

    @staticmethod
    def _last_error(message: str) -> ContractError:
        code = ctypes.get_last_error()
        return ContractError(f"{message} (windows_error={code})")

    def put(self, *, binding_ref: str, credential: str) -> None:
        binding_ref = _ref(binding_ref, "binding_ref")
        credential = _secret(credential)
        raw = credential.encode("utf-8")
        blob = ctypes.create_string_buffer(raw)
        record = self._credential_type()
        record.Flags = 0
        record.Type = _CRED_TYPE_GENERIC
        record.TargetName = _target_name(binding_ref)
        record.Comment = "Padiem Local Agent device credential"
        record.CredentialBlobSize = len(raw)
        record.CredentialBlob = ctypes.cast(blob, type(record.CredentialBlob))
        record.Persist = _CRED_PERSIST_LOCAL_MACHINE
        record.AttributeCount = 0
        record.Attributes = None
        record.TargetAlias = None
        record.UserName = "Padiem Local Agent"
        if not self._cred_write(ctypes.byref(record), 0):
            raise self._last_error("failed to store Local Agent device credential")

    def read(self, *, binding_ref: str) -> str:
        binding_ref = _ref(binding_ref, "binding_ref")
        pointer = ctypes.POINTER(self._credential_type)()
        if not self._cred_read(_target_name(binding_ref), _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            raise self._last_error("device credential is not available")
        try:
            size = int(pointer.contents.CredentialBlobSize)
            if size < 8 or size > _MAX_SECRET_BYTES:
                raise ContractError("stored device credential has invalid size")
            raw = ctypes.string_at(pointer.contents.CredentialBlob, size)
            try:
                return _secret(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ContractError("stored device credential is not valid UTF-8") from exc
        finally:
            self._cred_free(pointer)

    def delete(self, *, binding_ref: str) -> None:
        binding_ref = _ref(binding_ref, "binding_ref")
        if self._cred_delete(_target_name(binding_ref), _CRED_TYPE_GENERIC, 0):
            return
        code = ctypes.get_last_error()
        if code == _ERROR_NOT_FOUND:
            return
        raise ContractError(f"failed to delete Local Agent device credential (windows_error={code})")

    def receipt(self, *, binding_ref: str, operation: str) -> CredentialStoreReceipt:
        binding_ref = _ref(binding_ref, "binding_ref")
        return CredentialStoreReceipt(
            binding_ref=binding_ref,
            target_ref=f"credman:{hashlib.sha256(binding_ref.encode()).hexdigest()[:24]}",
            operation=operation,
            os_user_scope=True,
        )


WINDOWS_CREDENTIAL_MANAGER_IMPLEMENTED = True
RAW_DEVICE_SECRET_IN_SAFE_STATE = False
PLAINTEXT_DEVICE_CREDENTIAL_FILE_SUPPORTED = False
ADMIN_ELEVATION_REQUIRED = False
