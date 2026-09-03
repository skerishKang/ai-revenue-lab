from __future__ import annotations

import base64
import http.client
import json
import re
import ssl
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlsplit

from .contracts import ContractError
from .control_plane_broker_conformance import (
    ConformedControlPlaneBrokerCommand,
    parse_control_plane_broker_command,
)
from .local_agent_command_material import OutboundCommandMaterialRequest
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceSession
from .local_agent_secure_transport import (
    DeviceCredentialStore,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_HTTP_REQUEST_BYTES = 262_144
_MAX_POLLED_METADATA = 256
_MAX_POLL_BATCH = 32

_ACK_KEYS = frozenset(
    {
        "command_id",
        "run_id",
        "tool_request_ref",
        "binding_ref",
        "credential_generation",
        "sequence",
        "request_fingerprint",
        "issued_at",
        "expires_at",
        "state",
        "admission_ref",
        "evidence_ref",
        "admitted_session_id",
        "admitted_at",
        "acknowledged_at",
        "raw_argv",
        "raw_file_content",
        "raw_device_credential",
        "p01_approval_payload",
    }
)
_SESSION_KEYS = frozenset(
    {
        "session_id",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "issued_at",
        "expires_at",
        "raw_session_secret",
    }
)


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def _positive_int(value: Any, field_name: str, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be an integer between {minimum} and {maximum} without coercion")
    return value


def _closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractError(f"{label} must be a plain mapping")
    actual = frozenset(value)
    if actual != keys:
        raise ContractError(f"{label} schema mismatch")
    return value


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _binding_session_exact(binding: DeviceBinding, session: DeviceSession, *, now: datetime) -> None:
    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    if not isinstance(session, DeviceSession):
        raise ContractError("session must be DeviceSession")
    now = _aware(now, "now")
    if not (session.issued_at <= now < session.expires_at):
        raise ContractError("physical broker operation requires a current device session")
    expected = (binding.binding_ref, binding.device_id, binding.account_ref, binding.workspace_ref)
    actual = (session.binding_ref, session.device_id, session.account_ref, session.workspace_ref)
    if actual != expected:
        raise ContractError("physical broker session does not match device binding")


class ControlPlaneHttpsOperation(str, Enum):
    OPEN_SESSION = "session"
    POLL = "poll"
    MATERIAL = "material"
    ACKNOWLEDGE = "acknowledge"


class PinnedHttpsJsonRequestPort(Protocol):
    def post(
        self,
        *,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...


class StdlibPinnedHttpsJsonRequestPort:
    """TLS-verified, no-redirect stdlib HTTPS JSON source for the pinned broker host."""

    def _path(self, config: OutboundTransportConfig, operation: ControlPlaneHttpsOperation) -> tuple[str, int, str]:
        if not isinstance(config, OutboundTransportConfig):
            raise ContractError("config must be OutboundTransportConfig")
        if config.endpoint.mode is not OutboundTransportMode.HTTPS_LONG_POLL:
            raise ContractError("stdlib physical broker source requires HTTPS long-poll mode")
        if not isinstance(operation, ControlPlaneHttpsOperation):
            raise ContractError("operation must be ControlPlaneHttpsOperation")
        parsed = urlsplit(config.endpoint.url)
        if parsed.scheme != "https" or not parsed.hostname or (parsed.port or 443) != 443:
            raise ContractError("physical broker source requires exact pinned HTTPS/443 authority")
        base = (parsed.path or "/").rstrip("/")
        path = f"{base}/{operation.value}" if base else f"/{operation.value}"
        return parsed.hostname, 443, path

    def post(
        self,
        *,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if type(payload) is not dict:
            raise ContractError("physical broker JSON payload must be a plain mapping")
        timeout_seconds = _positive_int(timeout_seconds, "timeout_seconds", minimum=1, maximum=60)
        host, port, path = self._path(config, operation)
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if not encoded or len(encoded) > _MAX_HTTP_REQUEST_BYTES:
            raise ContractError("physical broker JSON request exceeds size bound")
        connection: http.client.HTTPSConnection | None = None
        try:
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(host, port=port, timeout=timeout_seconds, context=context)
            connection.request(
                "POST",
                path,
                body=encoded,
                headers={
                    "accept": "application/json",
                    "cache-control": "no-store",
                    "content-type": "application/json",
                    "user-agent": "padiem-claw-local-agent/0.2",
                },
            )
            response = connection.getresponse()
            body = response.read(config.max_response_bytes + 1)
            if len(body) > config.max_response_bytes:
                raise ContractError("physical broker response exceeds configured size bound")
            if 300 <= response.status < 400:
                raise ContractError("physical broker redirect is refused")
            if response.status != 200:
                raise ContractError(f"physical broker returned HTTP status {response.status}")
            content_type = (response.getheader("content-type") or "").lower()
            if not content_type.startswith("application/json"):
                raise ContractError("physical broker response must be application/json")
            try:
                decoded = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractError("physical broker response is invalid JSON") from exc
            if type(decoded) is not dict:
                raise ContractError("physical broker response must be a JSON object")
            return decoded
        except ContractError:
            raise
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ContractError("Local Agent outbound broker is disconnected") from exc
        finally:
            if connection is not None:
                connection.close()


class ControlPlaneHttpsLongPollTransport:
    """Physical B54 adapter for a future authenticated Padiem broker endpoint.

    It resolves the device credential only at request time, never persists raw
    command material, and keeps the exact request fingerprint obtained from the
    Control Plane queued-command projection.
    """

    def __init__(
        self,
        *,
        credential_store: DeviceCredentialStore,
        request_port: PinnedHttpsJsonRequestPort | None = None,
    ) -> None:
        if not hasattr(credential_store, "load"):
            raise ContractError("credential_store must implement load")
        self._credential_store = credential_store
        self._request_port = request_port or StdlibPinnedHttpsJsonRequestPort()
        if not hasattr(self._request_port, "post"):
            raise ContractError("request_port must implement post")
        self._polled: dict[str, tuple[str, ConformedControlPlaneBrokerCommand]] = {}

    def _credential_b64(self, binding: DeviceBinding, *, now: datetime) -> str:
        credential = self._credential_store.load(binding=binding, now=_aware(now, "now"))
        if not isinstance(credential, bytes) or not credential:
            raise ContractError("device credential store returned invalid material")
        return base64.b64encode(credential).decode("ascii")

    def _post(
        self,
        *,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        return self._request_port.post(
            config=config,
            operation=operation,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    def _success(self, response: dict[str, Any], field_name: str) -> Any:
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ContractError("physical broker RPC response is invalid")
        if response["ok"] is True:
            if frozenset(response) != frozenset({"ok", field_name}):
                raise ContractError("physical broker success response schema mismatch")
            return response[field_name]
        if frozenset(response) != frozenset({"ok", "error"}):
            raise ContractError("physical broker error response schema mismatch")
        error = _closed_mapping(response["error"], frozenset({"code", "message"}), "physical broker error")
        code = _ref(error["code"], "broker_error_code")
        raise ContractError(f"physical broker rejected request: {code}")

    def _prune(self, *, now: datetime) -> None:
        now = _aware(now, "now")
        for command_id in [
            key for key, (_, value) in self._polled.items() if now >= value.envelope.expires_at
        ]:
            del self._polled[command_id]

    def open_session(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session_id: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> DeviceSession:
        now = _aware(now, "now")
        session_id = _ref(session_id, "session_id")
        ttl_seconds = _positive_int(ttl_seconds, "ttl_seconds", minimum=60, maximum=3600)
        response = self._post(
            config=config,
            operation=ControlPlaneHttpsOperation.OPEN_SESSION,
            payload={
                "session_id": session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=now),
                "account_ref": binding.account_ref,
                "workspace_ref": binding.workspace_ref,
                "now": _iso(now),
                "ttl_seconds": ttl_seconds,
            },
            timeout_seconds=min(config.poll_timeout_seconds, 30),
        )
        payload = _closed_mapping(self._success(response, "session"), _SESSION_KEYS, "broker session")
        if payload["raw_session_secret"] is not False:
            raise ContractError("broker session must not expose raw session secret")
        if _positive_int(payload["credential_generation"], "credential_generation") != binding.credential_generation:
            raise ContractError("broker session credential generation mismatch")
        correlations = {
            "session_id": session_id,
            "binding_ref": binding.binding_ref,
            "device_id": binding.device_id,
            "account_ref": binding.account_ref,
            "workspace_ref": binding.workspace_ref,
        }
        for field_name, expected in correlations.items():
            if _ref(payload[field_name], field_name) != expected:
                raise ContractError(f"broker session {field_name} mismatch")
        session = DeviceSession(
            session_id=session_id,
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            issued_at=_timestamp(payload["issued_at"], "issued_at"),
            expires_at=_timestamp(payload["expires_at"], "expires_at"),
        )
        if not (session.issued_at <= now < session.expires_at):
            raise ContractError("broker returned a non-current device session")
        return session

    def poll(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        request: OutboundPollRequest,
    ) -> tuple[DeviceCommandEnvelope, ...]:
        if not isinstance(request, OutboundPollRequest):
            raise ContractError("request must be OutboundPollRequest")
        now = request.requested_at
        _binding_session_exact(binding, request.session, now=now)
        response = self._post(
            config=config,
            operation=ControlPlaneHttpsOperation.POLL,
            payload={
                "session_id": request.session.session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=now),
                "after_sequence": request.after_sequence,
                "now": _iso(now),
                "limit": _MAX_POLL_BATCH,
            },
            timeout_seconds=config.poll_timeout_seconds,
        )
        raw_commands = self._success(response, "commands")
        if type(raw_commands) is not list or len(raw_commands) > _MAX_POLL_BATCH:
            raise ContractError("physical broker poll commands must be a bounded JSON list")
        conformed: list[ConformedControlPlaneBrokerCommand] = []
        seen: set[str] = set()
        for raw in raw_commands:
            item = parse_control_plane_broker_command(
                raw,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=binding.credential_generation,
                now=now,
            )
            if item.envelope.command_id in seen:
                raise ContractError("physical broker poll returned duplicate command_id")
            seen.add(item.envelope.command_id)
            if item.envelope.sequence <= request.after_sequence:
                raise ContractError("physical broker command sequence did not advance poll cursor")
            conformed.append(item)
        self._prune(now=now)
        new_ids = sum(1 for item in conformed if item.envelope.command_id not in self._polled)
        if len(self._polled) + new_ids > _MAX_POLLED_METADATA:
            raise ContractError("physical broker polled metadata bound exceeded")
        for item in conformed:
            key = item.envelope.command_id
            current = (request.session.session_id, item)
            prior = self._polled.get(key)
            if prior is not None and prior != current:
                raise ContractError("physical broker rebound command_id to different trusted metadata")
            self._polled[key] = current
        return tuple(item.envelope for item in conformed)

    def request_fingerprint_for(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        now: datetime,
    ) -> str:
        del config
        now = _aware(now, "now")
        _binding_session_exact(binding, session, now=now)
        self._prune(now=now)
        try:
            observed_session_id, observed = self._polled[command.command_id]
        except KeyError as exc:
            raise ContractError("request fingerprint requires exact previously-polled broker metadata") from exc
        if observed_session_id != session.session_id or observed.envelope != command:
            raise ContractError("request fingerprint command/session correlation mismatch")
        if observed.credential_generation != binding.credential_generation:
            raise ContractError("request fingerprint belongs to stale credential generation")
        return observed.request_fingerprint

    def resolve_material(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        request: OutboundCommandMaterialRequest,
    ) -> dict[str, Any]:
        if not isinstance(request, OutboundCommandMaterialRequest):
            raise ContractError("request must be OutboundCommandMaterialRequest")
        expected = self.request_fingerprint_for(
            config=config,
            binding=binding,
            session=request.session,
            command=request.command,
            now=request.requested_at,
        )
        if request.request_fingerprint != expected:
            raise ContractError("command material fingerprint is not the exact polled broker fingerprint")
        response = self._post(
            config=config,
            operation=ControlPlaneHttpsOperation.MATERIAL,
            payload={
                "request_ref": request.request_ref,
                "session_id": request.session.session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=request.requested_at),
                "command_id": request.command.command_id,
                "request_fingerprint": expected,
                "now": _iso(request.requested_at),
            },
            timeout_seconds=min(config.poll_timeout_seconds, 30),
        )
        material = self._success(response, "material")
        if type(material) is not dict:
            raise ContractError("physical broker command material must be a JSON object")
        return material

    def acknowledge(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        now: datetime,
    ) -> None:
        now = _aware(now, "now")
        _binding_session_exact(binding, session, now=now)
        command_id = _ref(command_id, "command_id")
        admission_ref = _ref(admission_ref, "admission_ref")
        evidence_ref = _ref(evidence_ref, "evidence_ref")
        self._prune(now=now)
        try:
            observed_session_id, observed = self._polled[command_id]
        except KeyError as exc:
            raise ContractError("acknowledgement requires exact previously-polled broker metadata") from exc
        if observed_session_id != session.session_id:
            raise ContractError("acknowledgement session does not match polled broker metadata")
        response = self._post(
            config=config,
            operation=ControlPlaneHttpsOperation.ACKNOWLEDGE,
            payload={
                "session_id": session.session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=now),
                "command_id": command_id,
                "admission_ref": admission_ref,
                "evidence_ref": evidence_ref,
                "now": _iso(now),
            },
            timeout_seconds=min(config.poll_timeout_seconds, 30),
        )
        payload = _closed_mapping(self._success(response, "command"), _ACK_KEYS, "broker acknowledgement")
        for field_name in ("raw_argv", "raw_file_content", "raw_device_credential", "p01_approval_payload"):
            if payload[field_name] is not False:
                raise ContractError(f"broker acknowledgement {field_name} must remain false")
        envelope = observed.envelope
        expected_refs = {
            "command_id": envelope.command_id,
            "run_id": envelope.run_id,
            "tool_request_ref": envelope.tool_request_ref,
            "binding_ref": envelope.binding_ref,
            "admission_ref": admission_ref,
            "evidence_ref": evidence_ref,
            "admitted_session_id": session.session_id,
        }
        for field_name, expected in expected_refs.items():
            if _ref(payload[field_name], field_name) != expected:
                raise ContractError(f"broker acknowledgement {field_name} mismatch")
        if payload["state"] != "acknowledged":
            raise ContractError("broker acknowledgement state must be acknowledged")
        if _positive_int(payload["credential_generation"], "credential_generation") != binding.credential_generation:
            raise ContractError("broker acknowledgement credential generation mismatch")
        if _positive_int(payload["sequence"], "sequence") != envelope.sequence:
            raise ContractError("broker acknowledgement sequence mismatch")
        if _digest(payload["request_fingerprint"], "request_fingerprint") != observed.request_fingerprint:
            raise ContractError("broker acknowledgement request fingerprint mismatch")
        if _timestamp(payload["acknowledged_at"], "acknowledged_at") != now:
            raise ContractError("broker acknowledgement timestamp mismatch")
        admitted_at = _timestamp(payload["admitted_at"], "admitted_at")
        if admitted_at < envelope.issued_at or admitted_at > now:
            raise ContractError("broker acknowledgement admitted_at is outside command lifecycle")
        del self._polled[command_id]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "transport_source": "stdlib_https_long_poll",
            "tls_default_context": True,
            "redirect_auto_follow": False,
            "caller_endpoint_override": False,
            "raw_device_credential": False,
            "poll_fingerprint_from_control_plane": True,
            "material_resolution": True,
            "ack_admission_ref_required": True,
            "ack_evidence_ref_required": True,
            "production_broker_configured": False,
            "real_remote_execution": False,
        }


STDLIB_HTTPS_TRANSPORT_SOURCE = True
TLS_DEFAULT_CONTEXT = True
REDIRECT_AUTO_FOLLOW = False
CALLER_ENDPOINT_OVERRIDE = False
RAW_DEVICE_CREDENTIAL_IN_SAFE_STATE = False
POLL_FINGERPRINT_FROM_CONTROL_PLANE = True
ACK_ADMISSION_REF_REQUIRED = True
ACK_EVIDENCE_REF_REQUIRED = True
PUBLIC_INBOUND_PORT = False
PRODUCTION_BROKER_CONFIGURED = False
REAL_REMOTE_EXECUTION = False
PRODUCTION_READY = False
