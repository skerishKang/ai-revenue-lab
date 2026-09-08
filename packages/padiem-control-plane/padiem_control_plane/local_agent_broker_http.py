from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Protocol

from .local_agent_broker_rpc import LocalAgentBrokerRpcFacade

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_LOCAL_AGENT_HTTP_BODY_BYTES = 262_144
MAX_LOCAL_AGENT_HTTP_POLL_BATCH = 32

_ROUTE_SESSION = "/session"
_ROUTE_POLL = "/poll"
_ROUTE_MATERIAL = "/material"
_ROUTE_HEARTBEAT = "/heartbeat"
_ROUTE_ACKNOWLEDGE = "/acknowledge"
_ROUTES = frozenset({_ROUTE_SESSION, _ROUTE_POLL, _ROUTE_MATERIAL, _ROUTE_HEARTBEAT, _ROUTE_ACKNOWLEDGE})

_SESSION_REQUEST_KEYS = frozenset(
    {"session_id", "binding_ref", "credential_b64", "account_ref", "workspace_ref", "now", "ttl_seconds"}
)
_POLL_REQUEST_KEYS = frozenset(
    {"session_id", "binding_ref", "credential_b64", "after_sequence", "now", "limit"}
)
_MATERIAL_REQUEST_KEYS = frozenset(
    {"request_ref", "session_id", "binding_ref", "credential_b64", "command_id", "request_fingerprint", "now"}
)
_HEARTBEAT_REQUEST_KEYS = frozenset({"session_id", "binding_ref", "credential_b64", "now"})
_ACK_REQUEST_KEYS = frozenset(
    {"session_id", "binding_ref", "credential_b64", "command_id", "admission_ref", "evidence_ref", "now"}
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
_COMMAND_KEYS = frozenset(
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
_MATERIAL_WIRE_KEYS = frozenset(
    {"contract_version", "command_id", "binding_ref", "sequence", "request_fingerprint", "material"}
)
_HEARTBEAT_KEYS = frozenset(
    {
        "session_id",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "last_seen_at",
        "session_expires_at",
        "raw_device_credential",
    }
)


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _positive_int(value: Any, field_name: str, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer between {minimum} and {maximum} without coercion")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer without coercion")
    return value


def _closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def _json_content_type(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Local Agent HTTP content-type is required")
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ValueError("Local Agent HTTP content-type must be application/json")
    return media_type


@dataclass(frozen=True, slots=True)
class TrustedLocalAgentHttpAuthContext:
    """Deployment-attested caller identity. Raw headers/tokens are intentionally outside this contract."""

    principal_ref: str
    account_ref: str
    workspace_ref: str
    authenticated: bool
    tls_verified: bool

    def __post_init__(self) -> None:
        for field_name in ("principal_ref", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if type(self.authenticated) is not bool or type(self.tls_verified) is not bool:
            raise ValueError("authentication and TLS attestations must be booleans")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "principal_ref": self.principal_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "authenticated": self.authenticated,
            "tls_verified": self.tls_verified,
            "raw_bearer_token": False,
            "raw_device_credential": False,
        }


@dataclass(frozen=True, slots=True)
class DurableLocalAgentSessionRecord:
    session_id: str
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    issued_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("session_id", "binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "credential_generation",
            _positive_int(self.credential_generation, "credential_generation"),
        )
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("durable Local Agent session expiry must follow issuance")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if self.last_seen_at is not None:
            last_seen = _aware(self.last_seen_at, "last_seen_at")
            if not (issued <= last_seen < expires):
                raise ValueError("last_seen_at must remain inside the session lifetime")
            object.__setattr__(self, "last_seen_at", last_seen)

    def with_last_seen(self, value: datetime) -> "DurableLocalAgentSessionRecord":
        seen = _aware(value, "last_seen_at")
        if self.last_seen_at is not None and seen < self.last_seen_at:
            raise ValueError("Local Agent last-seen time cannot move backwards")
        return replace(self, last_seen_at=seen)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "issued_at": _iso(self.issued_at),
            "expires_at": _iso(self.expires_at),
            "last_seen_at": _iso(self.last_seen_at) if self.last_seen_at is not None else None,
            "raw_session_secret": False,
            "raw_device_credential": False,
        }


class DurableLocalAgentBrokerStatePort(Protocol):
    durable: bool

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        ...

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        ...

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        ...


class UnconfiguredDurableLocalAgentBrokerStatePort:
    durable = False

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        del record
        raise RuntimeError("durable Local Agent broker state is not configured")

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        del session_id
        raise RuntimeError("durable Local Agent broker state is not configured")

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        del session_id, seen_at
        raise RuntimeError("durable Local Agent broker state is not configured")


@dataclass(frozen=True, slots=True)
class LocalAgentMaterialResolutionRequest:
    request_ref: str
    session_id: str
    binding_ref: str
    command_id: str
    request_fingerprint: str
    server_requested_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("request_ref", "session_id", "binding_ref", "command_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        object.__setattr__(self, "server_requested_at", _aware(self.server_requested_at, "server_requested_at"))


class LocalAgentCommandMaterialResolverPort(Protocol):
    def resolve(self, request: LocalAgentMaterialResolutionRequest) -> dict[str, Any]:
        ...


class UnconfiguredLocalAgentCommandMaterialResolverPort:
    def resolve(self, request: LocalAgentMaterialResolutionRequest) -> dict[str, Any]:
        del request
        raise RuntimeError("Local Agent command material resolver is not configured")


@dataclass(frozen=True, slots=True)
class LocalAgentBrokerHttpResponse:
    status: int
    body: dict[str, Any]

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int) or not 100 <= self.status <= 599:
            raise ValueError("HTTP status must be an integer between 100 and 599")
        if type(self.body) is not dict:
            raise ValueError("HTTP response body must be a plain mapping")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "cache-control": "no-store",
            "content-type": "application/json",
        }


class LocalAgentBrokerHttpHandler:
    """Framework-neutral authenticated HTTP boundary over the canonical broker RPC facade.

    Deployment code must terminate/verify TLS and construct TrustedLocalAgentHttpAuthContext.
    This handler never parses bearer headers, opens sockets, or owns replay/sequence authority.
    Client-supplied `now` is parsed only as request evidence; all broker authority calls use
    the injected trusted server clock.
    """

    def __init__(
        self,
        *,
        rpc: LocalAgentBrokerRpcFacade,
        state: DurableLocalAgentBrokerStatePort,
        material_resolver: LocalAgentCommandMaterialResolverPort,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(rpc, LocalAgentBrokerRpcFacade):
            raise ValueError("rpc must be LocalAgentBrokerRpcFacade")
        if getattr(state, "durable", None) is not True:
            raise ValueError("deployable Local Agent HTTP handler requires an explicitly durable state port")
        for method_name in ("save_session", "load_session", "record_last_seen"):
            if not callable(getattr(state, method_name, None)):
                raise ValueError("durable state port is incomplete")
        if not callable(getattr(material_resolver, "resolve", None)):
            raise ValueError("material_resolver must implement resolve")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._rpc = rpc
        self._state = state
        self._material_resolver = material_resolver
        self._clock = clock

    def _error(self, status: int, code: str, message: str) -> LocalAgentBrokerHttpResponse:
        return LocalAgentBrokerHttpResponse(
            status=status,
            body={"ok": False, "error": {"code": _ref(code, "error_code"), "message": str(message)}},
        )

    def _server_now(self) -> datetime:
        return _aware(self._clock(), "server_now")

    def _decode(self, body: bytes) -> dict[str, Any]:
        if not isinstance(body, bytes) or not body or len(body) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            raise ValueError("Local Agent HTTP request body is empty or exceeds the size bound")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Local Agent HTTP request body must be valid UTF-8 JSON") from exc
        if type(decoded) is not dict:
            raise ValueError("Local Agent HTTP request body must be a JSON object")
        return decoded

    def _auth(self, auth: TrustedLocalAgentHttpAuthContext | None) -> LocalAgentBrokerHttpResponse | None:
        if auth is None or not isinstance(auth, TrustedLocalAgentHttpAuthContext) or auth.authenticated is not True:
            return self._error(401, "local_agent_http_auth_required", "authenticated Local Agent broker access is required")
        if auth.tls_verified is not True:
            return self._error(403, "local_agent_http_tls_required", "trusted TLS termination is required")
        return None

    def _rpc_result(self, result: Any, success_field: str) -> dict[str, Any]:
        if type(result) is not dict or type(result.get("ok")) is not bool:
            raise ValueError("Local Agent broker RPC returned an invalid response")
        if result["ok"] is True:
            if frozenset(result) != frozenset({"ok", success_field}):
                raise ValueError("Local Agent broker RPC success schema mismatch")
            return result
        if frozenset(result) != frozenset({"ok", "error"}):
            raise ValueError("Local Agent broker RPC error schema mismatch")
        error = _closed_mapping(result["error"], frozenset({"code", "message"}), "broker RPC error")
        _ref(error["code"], "broker_error_code")
        if not isinstance(error["message"], str):
            raise ValueError("broker RPC error message must be text")
        return result

    def _session_record(self, payload: dict[str, Any]) -> DurableLocalAgentSessionRecord:
        payload = _closed_mapping(payload, _SESSION_KEYS, "broker session")
        if payload["raw_session_secret"] is not False:
            raise ValueError("broker session must not expose a raw session secret")
        return DurableLocalAgentSessionRecord(
            session_id=_ref(payload["session_id"], "session_id"),
            binding_ref=_ref(payload["binding_ref"], "binding_ref"),
            device_id=_ref(payload["device_id"], "device_id"),
            account_ref=_ref(payload["account_ref"], "account_ref"),
            workspace_ref=_ref(payload["workspace_ref"], "workspace_ref"),
            credential_generation=_positive_int(payload["credential_generation"], "credential_generation"),
            issued_at=_timestamp(payload["issued_at"], "issued_at"),
            expires_at=_timestamp(payload["expires_at"], "expires_at"),
        )

    def _load_scoped_session(
        self,
        *,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        server_now: datetime,
    ) -> DurableLocalAgentSessionRecord:
        record = self._state.load_session(_ref(payload["session_id"], "session_id"))
        if not isinstance(record, DurableLocalAgentSessionRecord):
            raise ValueError("durable state returned an invalid Local Agent session record")
        if record.binding_ref != _ref(payload["binding_ref"], "binding_ref"):
            raise ValueError("durable Local Agent session binding mismatch")
        if record.account_ref != auth.account_ref or record.workspace_ref != auth.workspace_ref:
            raise PermissionError("durable Local Agent session is outside authenticated account/workspace scope")
        if not (record.issued_at <= server_now < record.expires_at):
            raise ValueError("durable Local Agent session is not current")
        return record

    def _server_rpc_payload(self, payload: dict[str, Any], server_now: datetime) -> dict[str, Any]:
        result = dict(payload)
        _timestamp(result["now"], "client_now")  # request evidence only; never broker time authority
        result["now"] = _iso(server_now)
        return result

    def _authenticate_session_via_rpc(
        self,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> dict[str, Any]:
        probe = {
            "session_id": payload["session_id"],
            "binding_ref": payload["binding_ref"],
            "credential_b64": payload["credential_b64"],
            "after_sequence": 0,
            "now": _iso(server_now),
            "limit": 1,
        }
        return self._rpc_result(self._rpc.poll(probe), "commands")

    def _handle_session(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _SESSION_REQUEST_KEYS, "session request")
        if _ref(payload["account_ref"], "account_ref") != auth.account_ref:
            raise PermissionError("session account does not match authenticated account")
        if _ref(payload["workspace_ref"], "workspace_ref") != auth.workspace_ref:
            raise PermissionError("session workspace does not match authenticated workspace")
        _positive_int(payload["ttl_seconds"], "ttl_seconds", minimum=60, maximum=3600)
        result = self._rpc_result(self._rpc.open_session(self._server_rpc_payload(payload, server_now)), "session")
        if result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, result)
        record = self._session_record(result["session"])
        if record.account_ref != auth.account_ref or record.workspace_ref != auth.workspace_ref:
            raise PermissionError("broker session escaped authenticated account/workspace scope")
        if record.binding_ref != _ref(payload["binding_ref"], "binding_ref"):
            raise ValueError("broker session binding mismatch")
        self._state.save_session(record)
        return LocalAgentBrokerHttpResponse(200, result)

    def _handle_poll(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _POLL_REQUEST_KEYS, "poll request")
        self._load_scoped_session(auth=auth, payload=payload, server_now=server_now)
        _non_negative_int(payload["after_sequence"], "after_sequence")
        _positive_int(payload["limit"], "limit", minimum=1, maximum=MAX_LOCAL_AGENT_HTTP_POLL_BATCH)
        result = self._rpc_result(self._rpc.poll(self._server_rpc_payload(payload, server_now)), "commands")
        if result["ok"] is True:
            commands = result["commands"]
            if type(commands) is not list or len(commands) > MAX_LOCAL_AGENT_HTTP_POLL_BATCH:
                raise ValueError("broker poll response commands must be a bounded list")
            for command in commands:
                command = _closed_mapping(command, _COMMAND_KEYS, "broker command")
                if command["raw_argv"] is not False or command["raw_file_content"] is not False:
                    raise ValueError("broker poll response attempted raw command content expansion")
                if command["raw_device_credential"] is not False or command["p01_approval_payload"] is not False:
                    raise ValueError("broker poll response attempted authority/credential expansion")
        return LocalAgentBrokerHttpResponse(200, result)

    def _handle_heartbeat(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _HEARTBEAT_REQUEST_KEYS, "heartbeat request")
        record = self._load_scoped_session(auth=auth, payload=payload, server_now=server_now)
        auth_result = self._authenticate_session_via_rpc(payload, server_now=server_now)
        if auth_result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, auth_result)
        updated = self._state.record_last_seen(record.session_id, seen_at=server_now)
        if not isinstance(updated, DurableLocalAgentSessionRecord):
            raise ValueError("durable state returned an invalid heartbeat record")
        if updated.last_seen_at != server_now:
            raise ValueError("durable state did not persist exact server-owned last-seen time")
        heartbeat = {
            "session_id": updated.session_id,
            "binding_ref": updated.binding_ref,
            "device_id": updated.device_id,
            "account_ref": updated.account_ref,
            "workspace_ref": updated.workspace_ref,
            "credential_generation": updated.credential_generation,
            "last_seen_at": _iso(server_now),
            "session_expires_at": _iso(updated.expires_at),
            "raw_device_credential": False,
        }
        _closed_mapping(heartbeat, _HEARTBEAT_KEYS, "heartbeat response")
        return LocalAgentBrokerHttpResponse(200, {"ok": True, "heartbeat": heartbeat})

    def _validate_material_wire(
        self,
        wire: Any,
        request: LocalAgentMaterialResolutionRequest,
    ) -> tuple[dict[str, Any], int]:
        wire = _closed_mapping(wire, _MATERIAL_WIRE_KEYS, "command material wire projection")
        if wire["contract_version"] != "claw-local-command-material.v1":
            raise ValueError("unsupported Local Agent command material contract version")
        if _ref(wire["command_id"], "command_id") != request.command_id:
            raise ValueError("command material command_id mismatch")
        if _ref(wire["binding_ref"], "binding_ref") != request.binding_ref:
            raise ValueError("command material binding_ref mismatch")
        if _digest(wire["request_fingerprint"], "request_fingerprint") != request.request_fingerprint:
            raise ValueError("command material request_fingerprint mismatch")
        sequence = _positive_int(wire["sequence"], "sequence")
        if type(wire["material"]) is not dict:
            raise ValueError("command material payload must be a plain mapping")
        encoded = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            raise ValueError("command material response exceeds the HTTP size bound")
        return wire, sequence

    def _handle_material(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _MATERIAL_REQUEST_KEYS, "material request")
        self._load_scoped_session(auth=auth, payload=payload, server_now=server_now)
        request = LocalAgentMaterialResolutionRequest(
            request_ref=payload["request_ref"],
            session_id=payload["session_id"],
            binding_ref=payload["binding_ref"],
            command_id=payload["command_id"],
            request_fingerprint=payload["request_fingerprint"],
            server_requested_at=server_now,
        )
        auth_result = self._authenticate_session_via_rpc(payload, server_now=server_now)
        if auth_result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, auth_result)
        wire, sequence = self._validate_material_wire(self._material_resolver.resolve(request), request)
        exact_probe = {
            "session_id": payload["session_id"],
            "binding_ref": payload["binding_ref"],
            "credential_b64": payload["credential_b64"],
            "after_sequence": sequence - 1,
            "now": _iso(server_now),
            "limit": 1,
        }
        broker_result = self._rpc_result(self._rpc.poll(exact_probe), "commands")
        if broker_result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, broker_result)
        commands = broker_result["commands"]
        if type(commands) is not list or len(commands) != 1:
            return self._error(409, "local_agent_material_command_not_current", "exact queued command is not available")
        command = _closed_mapping(commands[0], _COMMAND_KEYS, "material broker command")
        if (
            _ref(command["command_id"], "command_id") != request.command_id
            or _ref(command["binding_ref"], "binding_ref") != request.binding_ref
            or _positive_int(command["sequence"], "sequence") != sequence
            or _digest(command["request_fingerprint"], "request_fingerprint") != request.request_fingerprint
            or command["state"] != "queued"
        ):
            return self._error(409, "local_agent_material_command_mismatch", "command material does not match canonical queued command")
        return LocalAgentBrokerHttpResponse(200, {"ok": True, "material": wire})

    def _handle_acknowledge(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _ACK_REQUEST_KEYS, "acknowledge request")
        self._load_scoped_session(auth=auth, payload=payload, server_now=server_now)
        _ref(payload["admission_ref"], "admission_ref")
        _ref(payload["evidence_ref"], "evidence_ref")
        result = self._rpc_result(self._rpc.acknowledge(self._server_rpc_payload(payload, server_now)), "command")
        if result["ok"] is True:
            command = _closed_mapping(result["command"], _COMMAND_KEYS, "acknowledged broker command")
            if command["state"] != "acknowledged":
                raise ValueError("broker acknowledgement did not reach acknowledged state")
            if command["admission_ref"] != payload["admission_ref"] or command["evidence_ref"] != payload["evidence_ref"]:
                raise ValueError("broker acknowledgement admission/evidence correlation mismatch")
            if command["raw_device_credential"] is not False:
                raise ValueError("broker acknowledgement exposed device credential material")
        return LocalAgentBrokerHttpResponse(200, result)

    def handle(
        self,
        *,
        method: str,
        route: str,
        content_type: str,
        body: bytes,
        auth: TrustedLocalAgentHttpAuthContext | None,
    ) -> LocalAgentBrokerHttpResponse:
        denied = self._auth(auth)
        if denied is not None:
            return denied
        assert auth is not None
        if method != "POST":
            return self._error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only")
        if route not in _ROUTES:
            return self._error(404, "local_agent_http_route_not_found", "Local Agent broker route was not found")
        try:
            _json_content_type(content_type)
        except (TypeError, ValueError):
            return self._error(415, "local_agent_http_json_required", "Local Agent broker routes require application/json")
        if not isinstance(body, bytes) or not body:
            return self._error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid")
        if len(body) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            return self._error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound")
        try:
            payload = self._decode(body)
            server_now = self._server_now()
            if route == _ROUTE_SESSION:
                return self._handle_session(auth, payload, server_now=server_now)
            if route == _ROUTE_POLL:
                return self._handle_poll(auth, payload, server_now=server_now)
            if route == _ROUTE_MATERIAL:
                return self._handle_material(auth, payload, server_now=server_now)
            if route == _ROUTE_HEARTBEAT:
                return self._handle_heartbeat(auth, payload, server_now=server_now)
            return self._handle_acknowledge(auth, payload, server_now=server_now)
        except PermissionError:
            return self._error(403, "local_agent_http_scope_mismatch", "authenticated Local Agent scope does not match request")
        except (KeyError, TypeError, ValueError):
            return self._error(400, "local_agent_http_invalid_request", "Local Agent broker request is invalid")
        except RuntimeError:
            return self._error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "deployable_http_handler_boundary": True,
            "routes": sorted(_ROUTES),
            "post_only": True,
            "request_content_type": "application/json",
            "authenticated_context_required": True,
            "trusted_tls_attestation_required": True,
            "client_time_authority": False,
            "control_plane_rpc_reused": True,
            "replay_sequence_authority_duplicated": False,
            "durable_state_port_required": True,
            "material_resolver_port_required": True,
            "raw_device_credential_logged": False,
            "production_endpoint_configured": False,
            "production_ready": False,
        }


DEPLOYABLE_HTTP_HANDLER_BOUNDARY = True
PUBLIC_UNAUTHENTICATED_ACCESS = False
CONTROL_PLANE_BROKER_AUTHORITY_REUSED = True
REPLAY_SEQUENCE_AUTHORITY_DUPLICATED = False
BOUNDED_JSON = True
CLOSED_SCHEMA = True
REQUEST_CONTENT_TYPE_JSON_REQUIRED = True
HEARTBEAT_SERVER_LAST_SEEN = True
POLL_REQUEST_FINGERPRINT_PRESERVED = True
MATERIAL_FINGERPRINT_EXACT = True
ACK_ADMISSION_EVIDENCE_EXACT = True
DURABLE_STORE_PORT_DEFINED = True
IN_MEMORY_COUNTS_AS_DURABLE = False
RAW_DEVICE_CREDENTIAL_LOGGED = False
CLIENT_TIME_AUTHORITY = False
PRODUCTION_ENDPOINT_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
