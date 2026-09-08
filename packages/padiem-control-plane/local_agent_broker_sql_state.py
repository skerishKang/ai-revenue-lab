from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord
from padiem_control_plane.local_agent_broker_state_wire import (
    MAX_BROKER_STATE_WIRE_BYTES,
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


def safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer without coercion")
    return value


def non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer without coercion")
    return value


def utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601 text") from exc
    return utc(parsed, field_name)


def row_value(row: Any, field_name: str) -> Any:
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def rows(cursor: Any) -> list[Any]:
    return list(cursor.toArray())


def rows_written(cursor: Any) -> int:
    value = getattr(cursor, "rowsWritten")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value < 0:
        raise RuntimeError("Durable Object SQL returned invalid rowsWritten")
    return int(value)


def stale_state_error() -> ControlPlaneContractError:
    return ControlPlaneContractError(
        "stale_local_agent_broker_state",
        "Local Agent broker serialized state changed concurrently; stale write refused",
    )


class CloudflareDurableObjectSerializedStateBackend:
    """M2g serialized CAS backend over attached SQLite storage."""

    durable = True

    def __init__(self, storage: Any) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        self._storage = storage
        self._sql = sql
        self._sql.exec(_BROKER_STATE_SCHEMA)

    def _singleton_row(self) -> Any | None:
        found = rows(
            self._sql.exec(
                "SELECT authority_ref, version, payload_text "
                "FROM local_agent_broker_state WHERE singleton = 1"
            )
        )
        if len(found) > 1:
            raise RuntimeError("Durable Object broker state contains multiple singleton rows")
        return found[0] if found else None

    def load(self, *, authority_ref: str) -> SerializedLocalAgentBrokerStateRecord | None:
        authority_ref = safe_ref(authority_ref, "authority_ref")
        row = self._singleton_row()
        if row is None:
            return None
        if row_value(row, "authority_ref") != authority_ref:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state_wire",
                "Durable Object broker state authority mismatch",
            )
        version = positive_int(row_value(row, "version"), "stored broker version")
        payload_text = row_value(row, "payload_text")
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
        authority_ref = safe_ref(authority_ref, "authority_ref")
        expected_version = non_negative_int(expected_version, "expected_version")
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
        if rows_written(cursor) != 1:
            row = self._singleton_row()
            if row is not None and row_value(row, "authority_ref") != authority_ref:
                raise ControlPlaneContractError(
                    "invalid_local_agent_broker_state_wire",
                    "Durable Object broker state authority mismatch",
                )
            raise stale_state_error()

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
    """M2e HTTP session and heartbeat state over attached SQLite storage."""

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
            iso(record.issued_at),
            iso(record.expires_at),
            iso(record.last_seen_at) if record.last_seen_at is not None else None,
        )
        if rows_written(cursor) != 1:
            raise ValueError("durable Local Agent HTTP session already exists")

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        session_id = safe_ref(session_id, "session_id")
        found = rows(
            self._sql.exec(
                "SELECT session_id, binding_ref, device_id, account_ref, workspace_ref, "
                "credential_generation, issued_at, expires_at, last_seen_at "
                "FROM local_agent_http_session WHERE session_id = ?",
                session_id,
            )
        )
        if not found:
            raise RuntimeError("durable Local Agent HTTP session was not found")
        if len(found) != 1:
            raise RuntimeError("durable Local Agent HTTP session lookup was ambiguous")
        row = found[0]
        last_seen = row_value(row, "last_seen_at")
        return DurableLocalAgentSessionRecord(
            session_id=safe_ref(row_value(row, "session_id"), "session_id"),
            binding_ref=safe_ref(row_value(row, "binding_ref"), "binding_ref"),
            device_id=safe_ref(row_value(row, "device_id"), "device_id"),
            account_ref=safe_ref(row_value(row, "account_ref"), "account_ref"),
            workspace_ref=safe_ref(row_value(row, "workspace_ref"), "workspace_ref"),
            credential_generation=positive_int(row_value(row, "credential_generation"), "credential_generation"),
            issued_at=parse_iso(row_value(row, "issued_at"), "issued_at"),
            expires_at=parse_iso(row_value(row, "expires_at"), "expires_at"),
            last_seen_at=parse_iso(last_seen, "last_seen_at") if last_seen is not None else None,
        )

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        session_id = safe_ref(session_id, "session_id")
        seen_at = utc(seen_at, "seen_at")

        def update() -> DurableLocalAgentSessionRecord:
            current = self.load_session(session_id)
            changed = current.with_last_seen(seen_at)
            cursor = self._sql.exec(
                "UPDATE local_agent_http_session SET last_seen_at = ? WHERE session_id = ?",
                iso(changed.last_seen_at),
                session_id,
            )
            if rows_written(cursor) != 1:
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


BROKER_SQL_STATE_MODULE_SEPARATED = True
HTTP_SESSION_STATE_SEPARATED = True
CLOUD_PLATFORM_IMPORT_REQUIRED = False
DB_SEMANTICS_INTENTIONALLY_CHANGED = False
