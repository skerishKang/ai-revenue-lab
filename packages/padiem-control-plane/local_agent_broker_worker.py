from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, TypeVar

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    LocalAgentMaterialResolutionRequest,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    MAX_BROKER_STATE_WIRE_BYTES,
    SerializedLocalAgentBrokerStatePort,
    SerializedLocalAgentBrokerStateRecord,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")
MAX_DURABLE_COMMAND_MATERIAL_BYTES = 196_608

_MATERIAL_WIRE_KEYS = frozenset(
    {
        "contract_version",
        "command_id",
        "binding_ref",
        "sequence",
        "request_fingerprint",
        "material",
    }
)
_MATERIAL_KEYS = frozenset(
    {
        "request_id",
        "run_id",
        "device_id",
        "root_ref",
        "argv",
        "cwd_relative",
        "requested_at",
        "timeout_seconds",
        "shell_authority",
        "admin_elevation",
        "environment_payload",
        "provider_authority",
        "p01_approval_payload",
    }
)
_MATERIAL_RESOLVE_RPC_KEYS = frozenset(
    {
        "request_ref",
        "session_id",
        "binding_ref",
        "command_id",
        "request_fingerprint",
        "server_requested_at",
    }
)

_BROKER_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_broker_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    authority_ref TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL CHECK (version >= 1),
    payload_text TEXT NOT NULL CHECK (length(payload_text) > 0)
)
"""

_HTTP_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_http_session (
    session_id TEXT PRIMARY KEY,
    binding_ref TEXT NOT NULL,
    device_id TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    credential_generation INTEGER NOT NULL CHECK (credential_generation >= 1),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NULL
)
"""

_COMMAND_MATERIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_command_material (
    command_id TEXT PRIMARY KEY,
    binding_ref TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    request_fingerprint TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    wire_text TEXT NOT NULL CHECK (length(wire_text) > 0),
    UNIQUE(binding_ref, sequence)
)
"""


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer without coercion")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer without coercion")
    return value


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601 text") from exc
    return _utc(parsed, field_name)


def _closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def _canonical_json(value: dict[str, Any], *, maximum_bytes: int, label: str) -> tuple[str, bytes]:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be deterministic JSON") from exc
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > maximum_bytes:
        raise ValueError(f"{label} exceeds the serialized size bound")
    return text, encoded


def _row_value(row: Any, field_name: str) -> Any:
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _rows(cursor: Any) -> list[Any]:
    values = cursor.toArray()
    return list(values)


def _rows_written(cursor: Any) -> int:
    value = getattr(cursor, "rowsWritten")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value < 0:
        raise RuntimeError("Durable Object SQL returned invalid rowsWritten")
    return int(value)


def _stale_state() -> ControlPlaneContractError:
    return ControlPlaneContractError(
        "stale_local_agent_broker_state",
        "Local Agent broker serialized state changed concurrently; stale write refused",
    )


class CloudflareDurableObjectSerializedStateBackend:
    """M2g serialized CAS backend over one SQLite-backed Durable Object."""

    durable = True

    def __init__(self, storage: Any) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        self._storage = storage
        self._sql = sql
        self._sql.exec(_BROKER_STATE_SCHEMA)

    def _singleton_row(self) -> Any | None:
        rows = _rows(
            self._sql.exec(
                "SELECT authority_ref, version, payload_text "
                "FROM local_agent_broker_state WHERE singleton = 1"
            )
        )
        if len(rows) > 1:
            raise RuntimeError("Durable Object broker state contains multiple singleton rows")
        return rows[0] if rows else None

    def load(self, *, authority_ref: str) -> SerializedLocalAgentBrokerStateRecord | None:
        authority_ref = _safe_ref(authority_ref, "authority_ref")
        row = self._singleton_row()
        if row is None:
            return None
        if _row_value(row, "authority_ref") != authority_ref:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state_wire",
                "Durable Object broker state authority mismatch",
            )
        version = _positive_int(_row_value(row, "version"), "stored broker version")
        payload_text = _row_value(row, "payload_text")
        if not isinstance(payload_text, str) or not payload_text:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state_wire",
                "Durable Object broker state payload is invalid",
            )
        try:
            payload = payload_text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state_wire",
                "Durable Object broker state payload is not UTF-8",
            ) from exc
        if len(payload) > MAX_BROKER_STATE_WIRE_BYTES:
            raise ControlPlaneContractError(
                "local_agent_broker_state_wire_too_large",
                "Durable Object broker state payload exceeds the size bound",
            )
        return SerializedLocalAgentBrokerStateRecord(version=version, payload=payload)

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        payload: bytes,
    ) -> SerializedLocalAgentBrokerStateRecord:
        authority_ref = _safe_ref(authority_ref, "authority_ref")
        expected_version = _non_negative_int(expected_version, "expected_version")
        if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BROKER_STATE_WIRE_BYTES:
            raise ValueError("serialized broker state payload must be bounded non-empty bytes")
        try:
            payload_text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("serialized broker state payload must be UTF-8") from exc
        if payload_text.encode("utf-8") != payload:
            raise ValueError("serialized broker state payload must roundtrip exact UTF-8 bytes")

        if expected_version == 0:
            cursor = self._sql.exec(
                "INSERT OR IGNORE INTO local_agent_broker_state "
                "(singleton, authority_ref, version, payload_text) VALUES (1, ?, 1, ?)",
                authority_ref,
                payload_text,
            )
        else:
            cursor = self._sql.exec(
                "UPDATE local_agent_broker_state "
                "SET version = version + 1, payload_text = ? "
                "WHERE singleton = 1 AND authority_ref = ? AND version = ?",
                payload_text,
                authority_ref,
                expected_version,
            )
        if _rows_written(cursor) != 1:
            row = self._singleton_row()
            if row is not None and _row_value(row, "authority_ref") != authority_ref:
                raise ControlPlaneContractError(
                    "invalid_local_agent_broker_state_wire",
                    "Durable Object broker state authority mismatch",
                )
            raise _stale_state()

        stored = self.load(authority_ref=authority_ref)
        if stored is None or stored.version != expected_version + 1 or stored.payload != payload:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state_wire",
                "Durable Object backend violated the exact broker CAS contract",
            )
        return stored

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_durable_object": True,
            "sqlite_storage": True,
            "serialized_backend": True,
            "atomic_compare_and_swap": True,
            "durable": True,
            "raw_device_credential_persisted": False,
            "production_deployment": False,
            "production_ready": False,
        }


class CloudflareDurableObjectHttpSessionState:
    """M2e durable HTTP session/heartbeat state over the same Durable Object."""

    durable = True

    def __init__(self, storage: Any) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        self._storage = storage
        self._sql = sql
        self._sql.exec(_HTTP_SESSION_SCHEMA)

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        if not isinstance(record, DurableLocalAgentSessionRecord):
            raise ValueError("record must be DurableLocalAgentSessionRecord")
        cursor = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_http_session "
            "(session_id, binding_ref, device_id, account_ref, workspace_ref, "
            "credential_generation, issued_at, expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record.session_id,
            record.binding_ref,
            record.device_id,
            record.account_ref,
            record.workspace_ref,
            record.credential_generation,
            _iso(record.issued_at),
            _iso(record.expires_at),
            _iso(record.last_seen_at) if record.last_seen_at is not None else None,
        )
        if _rows_written(cursor) != 1:
            raise ValueError("durable Local Agent HTTP session already exists")

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        session_id = _safe_ref(session_id, "session_id")
        rows = _rows(
            self._sql.exec(
                "SELECT session_id, binding_ref, device_id, account_ref, workspace_ref, "
                "credential_generation, issued_at, expires_at, last_seen_at "
                "FROM local_agent_http_session WHERE session_id = ?",
                session_id,
            )
        )
        if not rows:
            raise RuntimeError("durable Local Agent HTTP session was not found")
        if len(rows) != 1:
            raise RuntimeError("durable Local Agent HTTP session lookup was ambiguous")
        row = rows[0]
        last_seen = _row_value(row, "last_seen_at")
        return DurableLocalAgentSessionRecord(
            session_id=_safe_ref(_row_value(row, "session_id"), "session_id"),
            binding_ref=_safe_ref(_row_value(row, "binding_ref"), "binding_ref"),
            device_id=_safe_ref(_row_value(row, "device_id"), "device_id"),
            account_ref=_safe_ref(_row_value(row, "account_ref"), "account_ref"),
            workspace_ref=_safe_ref(_row_value(row, "workspace_ref"), "workspace_ref"),
            credential_generation=_positive_int(
                _row_value(row, "credential_generation"), "credential_generation"
            ),
            issued_at=_parse_iso(_row_value(row, "issued_at"), "issued_at"),
            expires_at=_parse_iso(_row_value(row, "expires_at"), "expires_at"),
            last_seen_at=_parse_iso(last_seen, "last_seen_at") if last_seen is not None else None,
        )

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        session_id = _safe_ref(session_id, "session_id")
        seen_at = _utc(seen_at, "seen_at")

        def update() -> DurableLocalAgentSessionRecord:
            current = self.load_session(session_id)
            changed = current.with_last_seen(seen_at)
            cursor = self._sql.exec(
                "UPDATE local_agent_http_session SET last_seen_at = ? WHERE session_id = ?",
                _iso(changed.last_seen_at),
                session_id,
            )
            if _rows_written(cursor) != 1:
                raise RuntimeError("durable Local Agent HTTP session disappeared during heartbeat update")
            return changed

        transaction_sync = getattr(self._storage, "transactionSync", None)
        if not callable(transaction_sync):
            raise RuntimeError("SQLite-backed Durable Object transactionSync is required")
        return transaction_sync(update)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_durable_object": True,
            "durable": True,
            "http_session_state": True,
            "last_seen_monotonic": True,
            "raw_device_credential_persisted": False,
            "production_deployment": False,
        }


class CloudflareDurableObjectCommandMaterialStore:
    """Durable exact-wire resolver for already-enqueued canonical broker commands."""

    durable = True

    def __init__(
        self,
        storage: Any,
        *,
        state_port: SerializedLocalAgentBrokerStatePort,
        authority_ref: str,
    ) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        if not isinstance(state_port, SerializedLocalAgentBrokerStatePort):
            raise ValueError("state_port must be SerializedLocalAgentBrokerStatePort")
        self._storage = storage
        self._sql = sql
        self._state_port = state_port
        self._authority_ref = _safe_ref(authority_ref, "authority_ref")
        self._sql.exec(_COMMAND_MATERIAL_SCHEMA)

    def _command(self, command_id: str):
        command_id = _safe_ref(command_id, "command_id")
        snapshot = self._state_port.load(authority_ref=self._authority_ref).snapshot
        matches = [item for item in snapshot.commands if item.command_id == command_id]
        if len(matches) != 1:
            raise ValueError("command material requires one canonical persisted broker command")
        return matches[0]

    def _validate_wire(self, wire: Any, *, command: Any) -> tuple[dict[str, Any], str]:
        wire = _closed_mapping(wire, _MATERIAL_WIRE_KEYS, "command material wire")
        if wire["contract_version"] != "claw-local-command-material.v1":
            raise ValueError("unsupported Local Agent command material contract version")
        command_id = _safe_ref(wire["command_id"], "command_id")
        binding_ref = _safe_ref(wire["binding_ref"], "binding_ref")
        sequence = _positive_int(wire["sequence"], "sequence")
        fingerprint = _digest(wire["request_fingerprint"], "request_fingerprint")
        if (
            command_id != command.command_id
            or binding_ref != command.binding_ref
            or sequence != command.sequence
            or fingerprint != command.request_fingerprint
        ):
            raise ValueError("command material wire does not match canonical broker command")
        if command.state.value != "queued":
            raise ValueError("new command material requires a queued canonical broker command")

        material = _closed_mapping(wire["material"], _MATERIAL_KEYS, "command material")
        if material["shell_authority"] is not False or material["admin_elevation"] is not False:
            raise ValueError("command material cannot grant shell or admin authority")
        for field_name in ("environment_payload", "provider_authority", "p01_approval_payload"):
            if material[field_name] is not None:
                raise ValueError(f"command material {field_name} must remain null")
        argv = material["argv"]
        if type(argv) is not list or not all(type(item) is str for item in argv):
            raise ValueError("command material argv must be a JSON text list")

        wire_text, _ = _canonical_json(
            wire,
            maximum_bytes=MAX_DURABLE_COMMAND_MATERIAL_BYTES,
            label="command material wire",
        )
        return wire, wire_text

    def store(self, wire: dict[str, Any]) -> dict[str, Any]:
        command_id = _safe_ref(wire.get("command_id") if isinstance(wire, dict) else None, "command_id")
        command = self._command(command_id)
        wire, wire_text = self._validate_wire(wire, command=command)
        cursor = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_command_material "
            "(command_id, binding_ref, sequence, request_fingerprint, expires_at, wire_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            command.command_id,
            command.binding_ref,
            command.sequence,
            command.request_fingerprint,
            _iso(command.expires_at),
            wire_text,
        )
        if _rows_written(cursor) != 1:
            raise ValueError("command material already exists or binding sequence was rebound")
        return {
            "stored": True,
            "command_id": command.command_id,
            "binding_ref": command.binding_ref,
            "sequence": command.sequence,
            "request_fingerprint": command.request_fingerprint,
            "expires_at": _iso(command.expires_at),
            "raw_argv": False,
            "raw_device_credential": False,
            "execution_approval": False,
        }

    def _load_row(self, command_id: str) -> Any | None:
        rows = _rows(
            self._sql.exec(
                "SELECT command_id, binding_ref, sequence, request_fingerprint, expires_at, wire_text "
                "FROM local_agent_command_material WHERE command_id = ?",
                _safe_ref(command_id, "command_id"),
            )
        )
        if len(rows) > 1:
            raise RuntimeError("command material lookup was ambiguous")
        return rows[0] if rows else None

    def resolve(self, request: LocalAgentMaterialResolutionRequest) -> dict[str, Any]:
        if not isinstance(request, LocalAgentMaterialResolutionRequest):
            raise ValueError("request must be LocalAgentMaterialResolutionRequest")
        row = self._load_row(request.command_id)
        if row is None:
            raise RuntimeError("durable Local Agent command material is not available")
        expires_at = _parse_iso(_row_value(row, "expires_at"), "material.expires_at")
        if request.server_requested_at >= expires_at:
            self.purge_command(request.command_id)
            raise RuntimeError("durable Local Agent command material is expired")
        if (
            _safe_ref(_row_value(row, "binding_ref"), "binding_ref") != request.binding_ref
            or _digest(_row_value(row, "request_fingerprint"), "request_fingerprint")
            != request.request_fingerprint
        ):
            raise ValueError("command material resolution correlation mismatch")

        command = self._command(request.command_id)
        if command.state.value != "queued" or request.server_requested_at >= command.expires_at:
            self.purge_command(request.command_id)
            raise RuntimeError("canonical broker command is no longer material-resolvable")
        wire_text = _row_value(row, "wire_text")
        if not isinstance(wire_text, str) or not wire_text:
            raise RuntimeError("stored command material wire is invalid")
        try:
            wire = json.loads(wire_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("stored command material wire is invalid") from exc
        wire, canonical_text = self._validate_wire(wire, command=command)
        if canonical_text != wire_text:
            raise RuntimeError("stored command material wire is not canonical")
        if _positive_int(_row_value(row, "sequence"), "sequence") != command.sequence:
            raise ValueError("stored command material sequence mismatch")
        return wire

    def purge_command(self, command_id: str) -> int:
        cursor = self._sql.exec(
            "DELETE FROM local_agent_command_material WHERE command_id = ?",
            _safe_ref(command_id, "command_id"),
        )
        return _rows_written(cursor)

    def purge_binding(self, binding_ref: str) -> int:
        cursor = self._sql.exec(
            "DELETE FROM local_agent_command_material WHERE binding_ref = ?",
            _safe_ref(binding_ref, "binding_ref"),
        )
        return _rows_written(cursor)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "durable": True,
            "separate_material_table": True,
            "canonical_material_wire_reused": True,
            "second_fingerprint_algorithm": False,
            "broker_metadata_expanded_with_argv": False,
            "raw_device_credential_persisted": False,
            "execution_approval": False,
            "production_deployment": False,
        }


class LocalAgentBrokerDurableObject(DurableObject):
    """Server-selected durable host for canonical Local Agent broker authority."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self._storage = ctx.storage
        self._backend = CloudflareDurableObjectSerializedStateBackend(ctx.storage)
        self._state_port = SerializedLocalAgentBrokerStatePort(backend=self._backend)
        self.http_state = CloudflareDurableObjectHttpSessionState(ctx.storage)
        self.material_store = CloudflareDurableObjectCommandMaterialStore(
            ctx.storage,
            state_port=self._state_port,
            authority_ref=self._authority_ref(),
        )

    def _authority_ref(self) -> str:
        return _safe_ref(str(self.env.LOCAL_AGENT_BROKER_AUTHORITY_REF), "authority_ref")

    def _facade(self) -> LocalAgentBrokerRpcFacade:
        pepper = str(self.env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8")
        authority = StateBackedLocalAgentBrokerAuthority(
            pepper=pepper,
            authority_ref=self._authority_ref(),
            state_port=self._state_port,
        )
        return LocalAgentBrokerRpcFacade(authority=authority)

    def _transaction(self, operation: Callable[[], _T]) -> _T:
        transaction_sync = getattr(self._storage, "transactionSync", None)
        if not callable(transaction_sync):
            raise RuntimeError("SQLite-backed Durable Object transactionSync is required")
        return transaction_sync(operation)

    async def register_binding(self, payload: dict) -> dict:
        return self._facade().register_binding(payload)

    async def rotate_credential(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self._facade().rotate_credential(payload)
            if result.get("ok") is True:
                self.material_store.purge_binding(result["binding"]["binding_ref"])
            return result

        return self._transaction(operation)

    async def revoke_binding(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self._facade().revoke_binding(payload)
            if result.get("ok") is True:
                self.material_store.purge_binding(result["binding"]["binding_ref"])
            return result

        return self._transaction(operation)

    async def open_session(self, payload: dict) -> dict:
        return self._facade().open_session(payload)

    async def enqueue_command(self, payload: dict) -> dict:
        return self._facade().enqueue_command(payload)

    async def store_command_material(self, wire: dict) -> dict:
        return self._transaction(lambda: self.material_store.store(wire))

    async def resolve_command_material(self, payload: dict) -> dict:
        payload = _closed_mapping(payload, _MATERIAL_RESOLVE_RPC_KEYS, "material resolution RPC")
        request = LocalAgentMaterialResolutionRequest(
            request_ref=payload["request_ref"],
            session_id=payload["session_id"],
            binding_ref=payload["binding_ref"],
            command_id=payload["command_id"],
            request_fingerprint=payload["request_fingerprint"],
            server_requested_at=_parse_iso(payload["server_requested_at"], "server_requested_at"),
        )
        return {"ok": True, "material": self.material_store.resolve(request)}

    async def poll(self, payload: dict) -> dict:
        return self._facade().poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return self._facade().admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self._facade().acknowledge(payload)
            if result.get("ok") is True:
                self.material_store.purge_command(result["command"]["command_id"])
            return result

        return self._transaction(operation)

    async def fetch(self, request):
        del request
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )


class Default(WorkerEntrypoint):
    """Internal-only Service Binding gateway to the server-owned broker Durable Object."""

    def _authority_ref(self) -> str:
        return _safe_ref(str(self.env.LOCAL_AGENT_BROKER_AUTHORITY_REF), "authority_ref")

    def _stub(self):
        authority_ref = self._authority_ref()
        namespace = self.env.LOCAL_AGENT_BROKER_STATE
        object_id = namespace.idFromName(authority_ref)
        return namespace.get(object_id)

    async def register_binding(self, payload: dict) -> dict:
        return await self._stub().register_binding(payload)

    async def rotate_credential(self, payload: dict) -> dict:
        return await self._stub().rotate_credential(payload)

    async def revoke_binding(self, payload: dict) -> dict:
        return await self._stub().revoke_binding(payload)

    async def open_session(self, payload: dict) -> dict:
        return await self._stub().open_session(payload)

    async def enqueue_command(self, payload: dict) -> dict:
        return await self._stub().enqueue_command(payload)

    async def store_command_material(self, wire: dict) -> dict:
        return await self._stub().store_command_material(wire)

    async def resolve_command_material(self, payload: dict) -> dict:
        return await self._stub().resolve_command_material(payload)

    async def poll(self, payload: dict) -> dict:
        return await self._stub().poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return await self._stub().admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return await self._stub().acknowledge(payload)

    async def fetch(self, request):
        del request
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )


CLOUDFLARE_DO_ADAPTER = True
FOUNDATION_PACKAGE_SIDE_EFFECT_FREE = True
SQLITE_BACKED_DURABLE_OBJECT = True
SERVER_OWNED_AUTHORITY_ROUTING = True
M2G_SERIALIZED_STATE_REUSED = True
ATOMIC_VERSION_CAS = True
STALE_CAS_FAILS_CLOSED = True
M2E_HTTP_SESSION_STATE_DURABLE = True
LAST_SEEN_MONOTONIC = True
CANONICAL_BROKER_RPC_REUSED = True
SECOND_REPLAY_SEQUENCE_AUTHORITY = False
RAW_DEVICE_CREDENTIAL_PERSISTED = False
PUBLIC_FETCH = False
DURABLE_COMMAND_MATERIAL_STORE = True
CANONICAL_MATERIAL_WIRE_REUSED = True
SECOND_FINGERPRINT_ALGORITHM = False
BROKER_METADATA_EXPANDED_WITH_ARGV = False
EXACT_COMMAND_CORRELATION_ON_STORE = True
EXACT_RESOLUTION_CORRELATION = True
QUEUED_STATE_REQUIRED_FOR_STORE = True
MATERIAL_EXPIRY_BOUNDED = True
ACK_PURGES_MATERIAL = True
ROTATION_REVOCATION_PURGES_MATERIAL = True
M2E_RESOLVER_PORT_IMPLEMENTED = True
PRODUCTION_DEPLOYMENT = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
