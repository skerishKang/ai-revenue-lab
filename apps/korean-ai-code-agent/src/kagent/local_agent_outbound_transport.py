from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import ssl
import tempfile
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle, DeviceSession

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_MAX_SECRET_BYTES = 4096
_MIN_SECRET_BYTES = 16
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_HEARTBEAT_INTERVAL_SECONDS = 300
_MAX_LONG_POLL_SECONDS = 60
_DPAPI_UI_FORBIDDEN = 0x1


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_int(value: int, field_name: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ContractError(f"{field_name} must be between {low} and {high}")
    return value


def _secret_bytes(value: bytes) -> bytes:
    if not isinstance(value, bytes) or not _MIN_SECRET_BYTES <= len(value) <= _MAX_SECRET_BYTES:
        raise ContractError("device credential material must be bounded bytes")
    return bytes(value)


def _json_bytes(value: dict[str, Any], *, limit: int, field_name: str) -> bytes:
    if not isinstance(value, dict):
        raise ContractError(f"{field_name} must be a JSON object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must contain JSON-compatible values") from exc
    if len(encoded) > limit:
        raise ContractError(f"{field_name} exceeds bounded transport size")
    return encoded


def _json_object(data: bytes, *, field_name: str) -> dict[str, Any]:
    if not isinstance(data, bytes) or len(data) > _MAX_RESPONSE_BYTES:
        raise ContractError(f"{field_name} exceeds bounded transport size")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{field_name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{field_name} must be a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class LocalAgentBrokerEndpoint:
    base_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.strip() or len(self.base_url) > 1024:
            raise ContractError("broker base_url must be bounded text")
        parsed = urlsplit(self.base_url.strip())
        if parsed.scheme.lower() != "https":
            raise ContractError("Local Agent broker endpoint must use https")
        if not parsed.hostname:
            raise ContractError("Local Agent broker endpoint requires a host")
        if parsed.username is not None or parsed.password is not None:
            raise ContractError("Local Agent broker endpoint must not contain userinfo")
        if parsed.query or parsed.fragment:
            raise ContractError("Local Agent broker endpoint must not contain query or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ContractError("Local Agent broker endpoint port is invalid") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ContractError("Local Agent broker endpoint port is invalid")
        path = parsed.path or "/"
        pure = PurePosixPath(path)
        if any(part in {".", ".."} for part in pure.parts):
            raise ContractError("Local Agent broker endpoint path traversal is prohibited")
        normalized_path = "/" + "/".join(part for part in pure.parts if part != "/")
        if normalized_path != "/":
            normalized_path = normalized_path.rstrip("/")
        host = parsed.hostname.lower()
        if ":" in host and not host.startswith("["):
            host_for_url = f"[{host}]"
        else:
            host_for_url = host
        authority = host_for_url if port is None else f"{host_for_url}:{port}"
        object.__setattr__(self, "base_url", f"https://{authority}{normalized_path}")

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def port(self) -> int:
        return urlsplit(self.base_url).port or 443

    @property
    def base_path(self) -> str:
        return urlsplit(self.base_url).path.rstrip("/")

    def path(self, relative: str) -> str:
        if not isinstance(relative, str) or not relative.startswith("/") or len(relative) > 512:
            raise ContractError("broker relative path must be a bounded absolute path")
        pure = PurePosixPath(relative)
        if any(part in {".", ".."} for part in pure.parts):
            raise ContractError("broker relative path traversal is prohibited")
        suffix = "/" + "/".join(part for part in pure.parts if part != "/")
        return f"{self.base_path}{suffix}" if self.base_path else suffix

    def safe_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "https_only": True,
            "tls_verify_default": True,
            "auto_redirect": False,
            "public_inbound_port": False,
            "url_credentials": False,
        }


class DeviceCredentialMaterial:
    __slots__ = ("credential_ref", "generation", "_secret")

    def __init__(self, *, credential_ref: str, generation: int, secret: bytes) -> None:
        self.credential_ref = _ref(credential_ref, "credential_ref")
        self.generation = _positive_int(generation, "generation", low=1, high=2_147_483_647)
        self._secret = _secret_bytes(secret)

    def secret_for_transport(self) -> bytes:
        return bytes(self._secret)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "credential_ref": self.credential_ref,
            "generation": self.generation,
            "raw_secret": False,
        }

    def __repr__(self) -> str:
        return f"DeviceCredentialMaterial(credential_ref={self.credential_ref!r}, generation={self.generation}, secret=<redacted>)"


class DeviceCredentialStore(Protocol):
    def store(self, *, credential_ref: str, generation: int, secret: bytes) -> None:
        ...

    def load(self, *, credential_ref: str, generation: int) -> DeviceCredentialMaterial:
        ...

    def delete(self, *, credential_ref: str) -> None:
        ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array[Any]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi_entropy(credential_ref: str) -> bytes:
    return hashlib.sha256(f"padiem-local-agent:{credential_ref}".encode("utf-8")).digest()


def _dpapi_protect(secret: bytes, *, credential_ref: str) -> bytes:
    if os.name != "nt":
        raise ContractError("Windows DPAPI credential protection is available only on Windows")
    secret = _secret_bytes(secret)
    in_blob, in_buffer = _blob_from_bytes(secret)
    entropy_blob, entropy_buffer = _blob_from_bytes(_dpapi_entropy(credential_ref))
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        _DPAPI_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    _ = in_buffer, entropy_buffer
    if not ok:
        raise ContractError("Windows DPAPI failed to protect Local Agent credential")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(protected: bytes, *, credential_ref: str) -> bytes:
    if os.name != "nt":
        raise ContractError("Windows DPAPI credential protection is available only on Windows")
    if not isinstance(protected, bytes) or not protected:
        raise ContractError("protected Local Agent credential blob is invalid")
    in_blob, in_buffer = _blob_from_bytes(protected)
    entropy_blob, entropy_buffer = _blob_from_bytes(_dpapi_entropy(credential_ref))
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        _DPAPI_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    _ = in_buffer, entropy_buffer
    if not ok:
        raise ContractError("Windows DPAPI failed to unprotect Local Agent credential")
    try:
        return _secret_bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    finally:
        kernel32.LocalFree(out_blob.pbData)


class WindowsDpapiDeviceCredentialStore:
    """Persist only user-scope DPAPI-protected device material on Windows."""

    def __init__(self, root_dir: str | os.PathLike[str]) -> None:
        if not isinstance(root_dir, (str, os.PathLike)):
            raise ContractError("credential store root_dir must be a path")
        self._root = Path(root_dir).expanduser()
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise ContractError("credential store root_dir must not be a symlink")
        self._root = self._root.resolve(strict=True)

    def _path(self, credential_ref: str) -> Path:
        credential_ref = _ref(credential_ref, "credential_ref")
        digest = hashlib.sha256(credential_ref.encode("utf-8")).hexdigest()
        path = (self._root / f"{digest}.dpapi.json").resolve(strict=False)
        try:
            common = os.path.commonpath((str(self._root), str(path)))
        except ValueError as exc:
            raise ContractError("credential store path escaped configured root") from exc
        if os.path.normcase(common) != os.path.normcase(str(self._root)):
            raise ContractError("credential store path escaped configured root")
        return path

    def store(self, *, credential_ref: str, generation: int, secret: bytes) -> None:
        credential_ref = _ref(credential_ref, "credential_ref")
        generation = _positive_int(generation, "generation", low=1, high=2_147_483_647)
        protected = _dpapi_protect(secret, credential_ref=credential_ref)
        payload = {
            "contract_version": "claw-local-agent-dpapi.v1",
            "credential_ref": credential_ref,
            "generation": generation,
            "protected_b64": base64.b64encode(protected).decode("ascii"),
        }
        encoded = _json_bytes(payload, limit=16 * 1024, field_name="credential store payload")
        destination = self._path(credential_ref)
        fd, temp_name = tempfile.mkstemp(prefix=".padiem-credential-", suffix=".tmp", dir=self._root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, destination)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def load(self, *, credential_ref: str, generation: int) -> DeviceCredentialMaterial:
        credential_ref = _ref(credential_ref, "credential_ref")
        generation = _positive_int(generation, "generation", low=1, high=2_147_483_647)
        path = self._path(credential_ref)
        if not path.is_file() or path.is_symlink():
            raise ContractError("Local Agent device credential is not available in secure storage")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ContractError("Local Agent device credential could not be read from secure storage") from exc
        payload = _json_object(raw, field_name="credential store payload")
        if payload.get("contract_version") != "claw-local-agent-dpapi.v1":
            raise ContractError("Local Agent secure credential record version is unsupported")
        if payload.get("credential_ref") != credential_ref or payload.get("generation") != generation:
            raise ContractError("Local Agent secure credential ref/generation mismatch")
        try:
            protected = base64.b64decode(payload["protected_b64"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("Local Agent protected credential payload is invalid") from exc
        secret = _dpapi_unprotect(protected, credential_ref=credential_ref)
        return DeviceCredentialMaterial(credential_ref=credential_ref, generation=generation, secret=secret)

    def delete(self, *, credential_ref: str) -> None:
        path = self._path(credential_ref)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ContractError("Local Agent device credential could not be deleted from secure storage") from exc


class DeterministicDeviceCredentialStore:
    """Network-free in-memory store for conformance tests only."""

    def __init__(self) -> None:
        self._values: dict[str, DeviceCredentialMaterial] = {}

    def store(self, *, credential_ref: str, generation: int, secret: bytes) -> None:
        material = DeviceCredentialMaterial(credential_ref=credential_ref, generation=generation, secret=secret)
        self._values[material.credential_ref] = material

    def load(self, *, credential_ref: str, generation: int) -> DeviceCredentialMaterial:
        credential_ref = _ref(credential_ref, "credential_ref")
        try:
            value = self._values[credential_ref]
        except KeyError as exc:
            raise ContractError("Local Agent device credential is not available") from exc
        if value.generation != generation:
            raise ContractError("Local Agent device credential generation mismatch")
        return DeviceCredentialMaterial(
            credential_ref=value.credential_ref,
            generation=value.generation,
            secret=value.secret_for_transport(),
        )

    def delete(self, *, credential_ref: str) -> None:
        self._values.pop(_ref(credential_ref, "credential_ref"), None)


class BrokerJsonHttpClient(Protocol):
    def request_json(
        self,
        *,
        endpoint: LocalAgentBrokerEndpoint,
        method: str,
        relative_path: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...


class StdlibHttpsJsonClient:
    """Small HTTPS JSON client with default certificate validation and no redirects."""

    def __init__(
        self,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._connection_factory = connection_factory

    def request_json(
        self,
        *,
        endpoint: LocalAgentBrokerEndpoint,
        method: str,
        relative_path: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not isinstance(endpoint, LocalAgentBrokerEndpoint):
            raise ContractError("endpoint must be LocalAgentBrokerEndpoint")
        if method not in {"POST"}:
            raise ContractError("Local Agent broker transport supports POST only")
        timeout_seconds = _positive_int(timeout_seconds, "timeout_seconds", low=1, high=120)
        body = _json_bytes(payload, limit=_MAX_REQUEST_BYTES, field_name="broker request")
        safe_headers = {"accept": "application/json", "content-type": "application/json", "user-agent": "padiem-local-agent/1"}
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str) or "\r" in name + value or "\n" in name + value:
                raise ContractError("broker HTTP headers are invalid")
            safe_headers[name] = value
        context = ssl.create_default_context()
        factory = self._connection_factory
        connection = (
            factory(endpoint.host, endpoint.port, timeout_seconds, context)
            if factory is not None
            else http.client.HTTPSConnection(endpoint.host, endpoint.port, timeout=timeout_seconds, context=context)
        )
        try:
            connection.request(method, endpoint.path(relative_path), body=body, headers=safe_headers)
            response = connection.getresponse()
            data = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise ContractError("Local Agent broker response exceeded bounded size")
            if 300 <= response.status < 400:
                raise ContractError("Local Agent broker redirects are not followed")
            if response.status < 200 or response.status >= 300:
                raise ContractError(f"Local Agent broker returned HTTP {response.status}")
            return _json_object(data, field_name="broker response")
        except ContractError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ContractError("Local Agent broker is unavailable") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass


class DeviceCommandAcceptancePort(Protocol):
    def accept_command(self, session_id: str, command: DeviceCommandEnvelope, *, now: datetime) -> None:
        ...


@dataclass(frozen=True, slots=True)
class LocalAgentHeartbeatReceipt:
    session_id: str
    device_id: str
    state: DeviceLifecycle
    observed_at: datetime
    next_heartbeat_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _ref(self.session_id, "session_id"))
        object.__setattr__(self, "device_id", _ref(self.device_id, "device_id"))
        if not isinstance(self.state, DeviceLifecycle):
            try:
                object.__setattr__(self, "state", DeviceLifecycle(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid heartbeat device lifecycle state") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(
            self,
            "next_heartbeat_seconds",
            _positive_int(
                self.next_heartbeat_seconds,
                "next_heartbeat_seconds",
                low=5,
                high=_MAX_HEARTBEAT_INTERVAL_SECONDS,
            ),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "state": self.state.value,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "next_heartbeat_seconds": self.next_heartbeat_seconds,
            "raw_device_secret": False,
        }


class OutboundLocalAgentBrokerTransport:
    def __init__(
        self,
        *,
        endpoint: LocalAgentBrokerEndpoint,
        credential_store: DeviceCredentialStore,
        command_authority: DeviceCommandAcceptancePort,
        http_client: BrokerJsonHttpClient | None = None,
    ) -> None:
        if not isinstance(endpoint, LocalAgentBrokerEndpoint):
            raise ContractError("endpoint must be LocalAgentBrokerEndpoint")
        if credential_store is None or command_authority is None:
            raise ContractError("credential store and command authority are required")
        self._endpoint = endpoint
        self._credentials = credential_store
        self._commands = command_authority
        self._http = http_client or StdlibHttpsJsonClient()
        self._sessions: dict[str, DeviceBinding] = {}

    @staticmethod
    def _binding_ready(binding: DeviceBinding, *, account_ref: str, workspace_ref: str, now: datetime) -> None:
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        now = _aware(now, "now")
        if binding.account_ref != _ref(account_ref, "account_ref") or binding.workspace_ref != _ref(workspace_ref, "workspace_ref"):
            raise ContractError("Local Agent binding account/workspace mismatch")
        if binding.state is DeviceLifecycle.REVOKED:
            raise ContractError("revoked Local Agent device cannot connect")
        if now >= binding.credential_expires_at or binding.state is DeviceLifecycle.CREDENTIAL_EXPIRED:
            raise ContractError("Local Agent device credential has expired")
        if binding.state is DeviceLifecycle.UPDATE_REQUIRED:
            raise ContractError("Local Agent update is required before reconnect")

    @staticmethod
    def _authorization_header(material: DeviceCredentialMaterial) -> str:
        secret = base64.urlsafe_b64encode(material.secret_for_transport()).rstrip(b"=").decode("ascii")
        return f"Device {secret}"

    def _headers(self, binding: DeviceBinding) -> dict[str, str]:
        material = self._credentials.load(
            credential_ref=binding.credential_ref,
            generation=binding.credential_generation,
        )
        return {
            "authorization": self._authorization_header(material),
            "x-padiem-device-id": binding.device_id,
            "x-padiem-credential-generation": str(binding.credential_generation),
        }

    def connect(
        self,
        *,
        binding: DeviceBinding,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        timeout_seconds: int = 20,
    ) -> DeviceSession:
        now = _aware(now, "now")
        self._binding_ready(binding, account_ref=account_ref, workspace_ref=workspace_ref, now=now)
        payload = {
            "device_id": binding.device_id,
            "binding_ref": binding.binding_ref,
            "account_ref": binding.account_ref,
            "workspace_ref": binding.workspace_ref,
            "credential_generation": binding.credential_generation,
            "connected_at": now.isoformat().replace("+00:00", "Z"),
        }
        response = self._http.request_json(
            endpoint=self._endpoint,
            method="POST",
            relative_path="/v1/device/session/connect",
            headers=self._headers(binding),
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        try:
            session = DeviceSession(
                session_id=response["session_id"],
                device_id=response["device_id"],
                binding_ref=response["binding_ref"],
                account_ref=response["account_ref"],
                workspace_ref=response["workspace_ref"],
                issued_at=datetime.fromisoformat(response["issued_at"].replace("Z", "+00:00")),
                expires_at=datetime.fromisoformat(response["expires_at"].replace("Z", "+00:00")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("Local Agent broker returned invalid device session") from exc
        if (
            session.device_id != binding.device_id
            or session.binding_ref != binding.binding_ref
            or session.account_ref != binding.account_ref
            or session.workspace_ref != binding.workspace_ref
        ):
            raise ContractError("Local Agent broker session correlation mismatch")
        if not (session.issued_at <= now < session.expires_at):
            raise ContractError("Local Agent broker session is not current at connect time")
        self._sessions[session.session_id] = binding
        return session

    def _binding_for_session(self, session: DeviceSession, *, now: datetime) -> DeviceBinding:
        if not isinstance(session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        now = _aware(now, "now")
        if not (session.issued_at <= now < session.expires_at):
            raise ContractError("Local Agent device session is expired")
        try:
            binding = self._sessions[session.session_id]
        except KeyError as exc:
            raise ContractError("Local Agent device session is not attached to this outbound transport") from exc
        if binding.device_id != session.device_id or binding.binding_ref != session.binding_ref:
            raise ContractError("Local Agent attached session correlation mismatch")
        self._binding_ready(binding, account_ref=session.account_ref, workspace_ref=session.workspace_ref, now=now)
        return binding

    def heartbeat(
        self,
        *,
        session: DeviceSession,
        now: datetime,
        timeout_seconds: int = 15,
    ) -> LocalAgentHeartbeatReceipt:
        now = _aware(now, "now")
        binding = self._binding_for_session(session, now=now)
        response = self._http.request_json(
            endpoint=self._endpoint,
            method="POST",
            relative_path="/v1/device/session/heartbeat",
            headers=self._headers(binding),
            payload={
                "session_id": session.session_id,
                "device_id": session.device_id,
                "binding_ref": session.binding_ref,
                "observed_at": now.isoformat().replace("+00:00", "Z"),
            },
            timeout_seconds=timeout_seconds,
        )
        try:
            receipt = LocalAgentHeartbeatReceipt(
                session_id=response["session_id"],
                device_id=response["device_id"],
                state=DeviceLifecycle(response["state"]),
                observed_at=datetime.fromisoformat(response["observed_at"].replace("Z", "+00:00")),
                next_heartbeat_seconds=int(response["next_heartbeat_seconds"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("Local Agent broker returned invalid heartbeat") from exc
        if receipt.session_id != session.session_id or receipt.device_id != session.device_id:
            raise ContractError("Local Agent heartbeat correlation mismatch")
        if receipt.state in {DeviceLifecycle.REVOKED, DeviceLifecycle.CREDENTIAL_EXPIRED, DeviceLifecycle.UPDATE_REQUIRED}:
            self._sessions.pop(session.session_id, None)
        return receipt

    def poll_command(
        self,
        *,
        session: DeviceSession,
        last_sequence: int,
        now: datetime,
        wait_seconds: int = 25,
    ) -> DeviceCommandEnvelope | None:
        now = _aware(now, "now")
        binding = self._binding_for_session(session, now=now)
        if isinstance(last_sequence, bool) or not isinstance(last_sequence, int) or last_sequence < 0:
            raise ContractError("last_sequence must be a non-negative integer")
        wait_seconds = _positive_int(wait_seconds, "wait_seconds", low=1, high=_MAX_LONG_POLL_SECONDS)
        response = self._http.request_json(
            endpoint=self._endpoint,
            method="POST",
            relative_path="/v1/device/session/poll",
            headers=self._headers(binding),
            payload={
                "session_id": session.session_id,
                "device_id": session.device_id,
                "binding_ref": session.binding_ref,
                "last_sequence": last_sequence,
                "wait_seconds": wait_seconds,
                "polled_at": now.isoformat().replace("+00:00", "Z"),
            },
            timeout_seconds=min(120, wait_seconds + 10),
        )
        command_payload = response.get("command")
        if command_payload is None:
            return None
        if not isinstance(command_payload, dict):
            raise ContractError("Local Agent broker command envelope is invalid")
        try:
            command = DeviceCommandEnvelope(
                command_id=command_payload["command_id"],
                run_id=command_payload["run_id"],
                tool_request_ref=command_payload["tool_request_ref"],
                binding_ref=command_payload["binding_ref"],
                sequence=int(command_payload["sequence"]),
                issued_at=datetime.fromisoformat(command_payload["issued_at"].replace("Z", "+00:00")),
                expires_at=datetime.fromisoformat(command_payload["expires_at"].replace("Z", "+00:00")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("Local Agent broker command envelope is invalid") from exc
        if command.binding_ref != session.binding_ref:
            raise ContractError("Local Agent broker command binding mismatch")
        self._commands.accept_command(session.session_id, command, now=now)
        return command

    def disconnect(self, session_id: str) -> None:
        self._sessions.pop(_ref(session_id, "session_id"), None)


WINDOWS_DPAPI_SECURE_STORE_IMPLEMENTED = True
OUTBOUND_HTTPS_CLIENT_IMPLEMENTED = True
TLS_VERIFY_DEFAULT = True
HTTPS_ONLY = True
REDIRECT_AUTO_FOLLOW = False
PUBLIC_INBOUND_PORT_REQUIRED = False
UPNP_PORT_FORWARD_SUPPORTED = False
REPLAY_AUTHORITY_DUPLICATED = False
RAW_DEVICE_SECRET_IN_TASK_STATE = False
LIVE_BROKER_CONFIGURED = False
PRODUCTION_REMOTE_CONTROL_CLAIMED = False
