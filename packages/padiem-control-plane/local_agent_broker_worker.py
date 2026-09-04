from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    MAX_BROKER_STATE_WIRE_BYTES,
    SerializedLocalAgentBrokerStatePort,
    SerializedLocalAgentBrokerStateRecord,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")

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


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
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
    """M2g serialized CAS backend over one SQLite-backed Durable Object.

    One Durable Object is selected by the deployment-owned authority ref. The
    table therefore contains exactly one authority row, and every load/CAS
    verifies that row still belongs to the expected authority.
    """

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


class LocalAgentBrokerDurableObject(DurableObject):
    """Server-selected durable host for canonical Local Agent broker authority."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self._backend = CloudflareDurableObjectSerializedStateBackend(ctx.storage)
        self.http_state = CloudflareDurableObjectHttpSessionState(ctx.storage)

    def _authority_ref(self) -> str:
        return _safe_ref(str(self.env.LOCAL_AGENT_BROKER_AUTHORITY_REF), "authority_ref")

    def _facade(self) -> LocalAgentBrokerRpcFacade:
        pepper = str(self.env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8")
        state_port = SerializedLocalAgentBrokerStatePort(backend=self._backend)
        authority = StateBackedLocalAgentBrokerAuthority(
            pepper=pepper,
            authority_ref=self._authority_ref(),
            state_port=state_port,
        )
        return LocalAgentBrokerRpcFacade(authority=authority)

    async def register_binding(self, payload: dict) -> dict:
        return self._facade().register_binding(payload)

    async def rotate_credential(self, payload: dict) -> dict:
        return self._facade().rotate_credential(payload)

    async def revoke_binding(self, payload: dict) -> dict:
        return self._facade().revoke_binding(payload)

    async def open_session(self, payload: dict) -> dict:
        return self._facade().open_session(payload)

    async def enqueue_command(self, payload: dict) -> dict:
        return self._facade().enqueue_command(payload)

    async def poll(self, payload: dict) -> dict:
        return self._facade().poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return self._facade().admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return self._facade().acknowledge(payload)

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
DURABLE_COMMAND_MATERIAL_STORE = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
