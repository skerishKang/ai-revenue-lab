from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .contracts import ContractError
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle, DeviceSession
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_MAX_CREDENTIAL_BYTES = 16_384
_MAX_PROTECTED_BYTES = 65_536
_MAX_RECORD_BYTES = 131_072
CRYPTPROTECT_UI_FORBIDDEN = 0x00000001
CRYPTPROTECT_LOCAL_MACHINE = 0x00000004


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    normalized = value.strip()
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_int(value: int, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _binding_context(binding: DeviceBinding) -> dict[str, Any]:
    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    return {
        "binding_ref": binding.binding_ref,
        "device_id": binding.device_id,
        "account_ref": binding.account_ref,
        "workspace_ref": binding.workspace_ref,
        "credential_generation": binding.credential_generation,
        "credential_ref_fingerprint": _sha256_text(binding.credential_ref),
        "credential_expires_at": binding.credential_expires_at.isoformat().replace("+00:00", "Z"),
    }


def _binding_entropy(binding: DeviceBinding) -> bytes:
    canonical = json.dumps(_binding_context(binding), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _binding_is_usable(binding: DeviceBinding, *, now: datetime) -> None:
    now = _aware(now, "now")
    if binding.state in {DeviceLifecycle.REVOKED, DeviceLifecycle.CREDENTIAL_EXPIRED, DeviceLifecycle.UNPAIRED}:
        raise ContractError("device credential binding is not usable")
    if now >= binding.credential_expires_at:
        raise ContractError("device credential binding is expired")


class ProtectedDataPort(Protocol):
    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        ...

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        ...


class WindowsDpapiProtectedDataPort:
    """Current-user Windows DPAPI adapter. It intentionally never uses LOCAL_MACHINE scope."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise ContractError("Windows DPAPI is available only on Windows")
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        self._ctypes = ctypes
        self._DataBlob = DataBlob
        self._crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def _input_blob(self, data: bytes):
        if not isinstance(data, bytes) or not data:
            raise ContractError("DPAPI input must be non-empty bytes")
        ctypes = self._ctypes
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = self._DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        return blob, buffer

    def _output_bytes(self, blob) -> bytes:
        ctypes = self._ctypes
        try:
            if not blob.pbData or blob.cbData <= 0:
                raise ContractError("Windows DPAPI returned an empty protected payload")
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            if blob.pbData:
                self._kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        if len(plaintext) > _MAX_CREDENTIAL_BYTES:
            raise ContractError("device credential exceeds protected-data bound")
        if not isinstance(entropy, bytes) or not entropy:
            raise ContractError("DPAPI entropy must be non-empty bytes")
        in_blob, in_buffer = self._input_blob(plaintext)
        entropy_blob, entropy_buffer = self._input_blob(entropy)
        out_blob = self._DataBlob()
        del in_buffer, entropy_buffer
        ok = self._crypt32.CryptProtectData(
            self._ctypes.byref(in_blob),
            None,
            self._ctypes.byref(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            self._ctypes.byref(out_blob),
        )
        if not ok:
            raise ContractError(f"Windows DPAPI protect failed with system error {self._ctypes.get_last_error()}")
        return self._output_bytes(out_blob)

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        if not isinstance(protected, bytes) or not protected or len(protected) > _MAX_PROTECTED_BYTES:
            raise ContractError("protected device credential is invalid or too large")
        if not isinstance(entropy, bytes) or not entropy:
            raise ContractError("DPAPI entropy must be non-empty bytes")
        in_blob, in_buffer = self._input_blob(protected)
        entropy_blob, entropy_buffer = self._input_blob(entropy)
        out_blob = self._DataBlob()
        del in_buffer, entropy_buffer
        ok = self._crypt32.CryptUnprotectData(
            self._ctypes.byref(in_blob),
            None,
            self._ctypes.byref(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            self._ctypes.byref(out_blob),
        )
        if not ok:
            raise ContractError(f"Windows DPAPI unprotect failed with system error {self._ctypes.get_last_error()}")
        plaintext = self._output_bytes(out_blob)
        if not plaintext or len(plaintext) > _MAX_CREDENTIAL_BYTES:
            raise ContractError("unprotected device credential is invalid or too large")
        return plaintext


@dataclass(frozen=True, slots=True)
class StoredDeviceCredentialProjection:
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_ref_fingerprint: str
    stored_at: datetime
    credential_expires_at: datetime
    protection: str = "windows_dpapi_current_user"

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "credential_generation", _positive_int(
            self.credential_generation, "credential_generation", 1, 1_000_000
        ))
        fingerprint = self.credential_ref_fingerprint.strip().lower() if isinstance(self.credential_ref_fingerprint, str) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ContractError("credential_ref_fingerprint must be SHA-256")
        object.__setattr__(self, "credential_ref_fingerprint", fingerprint)
        stored = _aware(self.stored_at, "stored_at")
        expires = _aware(self.credential_expires_at, "credential_expires_at")
        if expires <= stored:
            raise ContractError("stored credential expiry must be after stored_at")
        object.__setattr__(self, "stored_at", stored)
        object.__setattr__(self, "credential_expires_at", expires)
        if self.protection != "windows_dpapi_current_user":
            raise ContractError("unsupported device credential protection mode")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "credential_ref_fingerprint": self.credential_ref_fingerprint,
            "stored_at": self.stored_at.isoformat().replace("+00:00", "Z"),
            "credential_expires_at": self.credential_expires_at.isoformat().replace("+00:00", "Z"),
            "protection": self.protection,
            "credential_ref_present": False,
            "protected_blob_present": False,
            "plaintext_credential_present": False,
            "local_machine_scope": False,
        }


class DeviceCredentialStore(Protocol):
    def save(self, *, binding: DeviceBinding, credential: bytes, now: datetime) -> StoredDeviceCredentialProjection:
        ...

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        ...

    def delete(self, binding_ref: str) -> None:
        ...


class ProtectedFileDeviceCredentialStore:
    """Persists only protected credential bytes; raw credential material is never written to disk."""

    def __init__(self, *, base_dir: str | os.PathLike[str], protected_data: ProtectedDataPort) -> None:
        path = Path(base_dir).expanduser()
        if not path.is_absolute():
            raise ContractError("device credential base_dir must be absolute")
        if not hasattr(protected_data, "protect") or not hasattr(protected_data, "unprotect"):
            raise ContractError("protected_data must implement protect/unprotect")
        path.mkdir(parents=True, exist_ok=True)
        self._base_dir = path.resolve()
        self._protected_data = protected_data

    def _path(self, binding_ref: str) -> Path:
        binding_ref = _ref(binding_ref, "binding_ref")
        filename = f"{hashlib.sha256(binding_ref.encode('utf-8')).hexdigest()}.credential.json"
        candidate = (self._base_dir / filename).resolve()
        if candidate.parent != self._base_dir:
            raise ContractError("device credential path escaped configured directory")
        return candidate

    def save(self, *, binding: DeviceBinding, credential: bytes, now: datetime) -> StoredDeviceCredentialProjection:
        now = _aware(now, "now")
        _binding_is_usable(binding, now=now)
        if not isinstance(credential, bytes) or not credential or len(credential) > _MAX_CREDENTIAL_BYTES:
            raise ContractError("device credential must be non-empty bounded bytes")
        protected = self._protected_data.protect(credential, entropy=_binding_entropy(binding))
        if not isinstance(protected, bytes) or not protected or len(protected) > _MAX_PROTECTED_BYTES:
            raise ContractError("protected-data adapter returned an invalid payload")
        context = _binding_context(binding)
        record = {
            "version": 1,
            **context,
            "stored_at": now.isoformat().replace("+00:00", "Z"),
            "protection": "windows_dpapi_current_user",
            "protected_blob_b64": base64.b64encode(protected).decode("ascii"),
        }
        encoded = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ContractError("protected credential record exceeds repository bound")
        destination = self._path(binding.binding_ref)
        fd, temp_name = tempfile.mkstemp(prefix=".pending-", suffix=".credential", dir=self._base_dir)
        try:
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return StoredDeviceCredentialProjection(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            credential_ref_fingerprint=context["credential_ref_fingerprint"],
            stored_at=now,
            credential_expires_at=binding.credential_expires_at,
        )

    def _read_record(self, binding_ref: str) -> dict[str, Any]:
        path = self._path(binding_ref)
        try:
            with path.open("rb") as handle:
                encoded = handle.read(_MAX_RECORD_BYTES + 1)
        except FileNotFoundError as exc:
            raise ContractError("protected device credential is not stored") from exc
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ContractError("protected device credential record is too large")
        try:
            record = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("protected device credential record is invalid") from exc
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ContractError("unsupported protected device credential record")
        return record

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        now = _aware(now, "now")
        _binding_is_usable(binding, now=now)
        record = self._read_record(binding.binding_ref)
        expected = _binding_context(binding)
        for key, value in expected.items():
            if record.get(key) != value:
                raise ContractError("stored device credential does not match current binding context")
        if record.get("protection") != "windows_dpapi_current_user":
            raise ContractError("stored device credential protection mode is invalid")
        try:
            protected = base64.b64decode(record["protected_blob_b64"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("stored device credential protected payload is invalid") from exc
        if not protected or len(protected) > _MAX_PROTECTED_BYTES:
            raise ContractError("stored device credential protected payload is invalid")
        plaintext = self._protected_data.unprotect(protected, entropy=_binding_entropy(binding))
        if not isinstance(plaintext, bytes) or not plaintext or len(plaintext) > _MAX_CREDENTIAL_BYTES:
            raise ContractError("protected-data adapter returned invalid credential material")
        return plaintext

    def delete(self, binding_ref: str) -> None:
        path = self._path(binding_ref)
        try:
            path.unlink()
        except FileNotFoundError:
            return


class OutboundTransportMode(str, Enum):
    HTTPS_LONG_POLL = "https_long_poll"
    WSS = "wss"


@dataclass(frozen=True, slots=True)
class OutboundBrokerEndpoint:
    endpoint_ref: str
    url: str
    mode: OutboundTransportMode

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint_ref", _ref(self.endpoint_ref, "endpoint_ref"))
        if not isinstance(self.mode, OutboundTransportMode):
            try:
                object.__setattr__(self, "mode", OutboundTransportMode(self.mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid outbound transport mode") from exc
        if not isinstance(self.url, str):
            raise ContractError("broker URL must be text")
        parsed = urlsplit(self.url.strip())
        expected_scheme = "https" if self.mode is OutboundTransportMode.HTTPS_LONG_POLL else "wss"
        if parsed.scheme.lower() != expected_scheme:
            raise ContractError("Local Agent broker transport must use the TLS scheme for its configured mode")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ContractError("broker endpoint must have an exact host and no URL credentials")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ContractError("broker endpoint port is invalid") from exc
        if port not in {None, 443}:
            raise ContractError("Local Agent M2a broker endpoint is restricted to port 443")
        if parsed.query or parsed.fragment:
            raise ContractError("broker endpoint authority must not use query or fragment data")
        path = parsed.path or "/"
        if not path.startswith("/") or ".." in path.split("/"):
            raise ContractError("broker endpoint path is invalid")
        host = parsed.hostname.lower()
        if ":" in host and not host.startswith("["):
            host_for_url = f"[{host}]"
        else:
            host_for_url = host
        netloc = host_for_url if port is None else f"{host_for_url}:{port}"
        object.__setattr__(self, "url", urlunsplit((expected_scheme, netloc, path, "", "")))

    def safe_dict(self) -> dict[str, Any]:
        parsed = urlsplit(self.url)
        return {
            "endpoint_ref": self.endpoint_ref,
            "mode": self.mode.value,
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port or 443,
            "path": parsed.path,
            "tls_required": True,
            "public_inbound_port": False,
            "caller_endpoint_override": False,
            "url_credentials": False,
        }


@dataclass(frozen=True, slots=True)
class OutboundTransportConfig:
    endpoint: OutboundBrokerEndpoint
    heartbeat_seconds: int = 30
    poll_timeout_seconds: int = 30
    max_response_bytes: int = 262_144
    tls_required: bool = True
    public_inbound_port: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, OutboundBrokerEndpoint):
            raise ContractError("endpoint must be OutboundBrokerEndpoint")
        object.__setattr__(self, "heartbeat_seconds", _positive_int(
            self.heartbeat_seconds, "heartbeat_seconds", 5, 300
        ))
        object.__setattr__(self, "poll_timeout_seconds", _positive_int(
            self.poll_timeout_seconds, "poll_timeout_seconds", 1, 60
        ))
        object.__setattr__(self, "max_response_bytes", _positive_int(
            self.max_response_bytes, "max_response_bytes", 1_024, 1_048_576
        ))
        if self.tls_required is not True:
            raise ContractError("Local Agent outbound transport requires TLS")
        if self.public_inbound_port is not False:
            raise ContractError("Local Agent must not require a public inbound port")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint.safe_dict(),
            "heartbeat_seconds": self.heartbeat_seconds,
            "poll_timeout_seconds": self.poll_timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "tls_required": True,
            "public_inbound_port": False,
            "caller_endpoint_override": False,
            "raw_device_credential": False,
        }


@dataclass(frozen=True, slots=True)
class OutboundPollRequest:
    request_ref: str
    session: DeviceSession
    after_sequence: int
    requested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_ref", _ref(self.request_ref, "request_ref"))
        if not isinstance(self.session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        if isinstance(self.after_sequence, bool) or not isinstance(self.after_sequence, int) or self.after_sequence < 0:
            raise ContractError("after_sequence must be a non-negative integer")
        requested = _aware(self.requested_at, "requested_at")
        if not (self.session.issued_at <= requested < self.session.expires_at):
            raise ContractError("outbound poll requires a current device session")
        object.__setattr__(self, "requested_at", requested)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_ref": self.request_ref,
            "session": self.session.safe_dict(),
            "after_sequence": self.after_sequence,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "outbound_only": True,
            "caller_endpoint_override": False,
            "raw_device_credential": False,
        }


class OutboundLocalAgentTransportPort(Protocol):
    def poll(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        request: OutboundPollRequest,
    ) -> tuple[DeviceCommandEnvelope, ...]:
        ...

    def acknowledge(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        evidence_ref: str,
        now: datetime,
    ) -> None:
        ...


class UnconfiguredOutboundLocalAgentTransportPort:
    def poll(self, **_: Any) -> tuple[DeviceCommandEnvelope, ...]:
        raise ContractError("real Local Agent outbound broker transport is not configured")

    def acknowledge(self, **_: Any) -> None:
        raise ContractError("real Local Agent outbound broker transport is not configured")


WINDOWS_DPAPI_CURRENT_USER = True
LOCAL_MACHINE_DPAPI_SCOPE = False
DPAPI_UI_FORBIDDEN = True
PLAINTEXT_CREDENTIAL_PERSISTED = False
ATOMIC_CREDENTIAL_REPLACEMENT = True
OUTBOUND_TLS_ONLY = True
PUBLIC_INBOUND_PORT_REQUIRED = False
CALLER_ENDPOINT_OVERRIDE = False
REAL_LOCAL_AGENT_BROKER_CONFIGURED = False
REAL_REMOTE_CONTROL_CONFIGURED = False
