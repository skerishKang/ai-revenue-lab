from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from .contracts import ControlPlaneContractError
from .local_agent_broker import (
    BrokerBindingState,
    BrokerCommandRecord,
    BrokerCommandState,
    BrokerDeviceBinding,
    BrokerDeviceSession,
)
from .local_agent_broker_state import (
    BROKER_STATE_SCHEMA_VERSION,
    LocalAgentBrokerStateSnapshot,
    VersionedLocalAgentBrokerState,
)

BROKER_STATE_WIRE_VERSION = "padiem.local-agent-broker-state-wire.v1"
MAX_BROKER_STATE_WIRE_BYTES = 8 * 1024 * 1024
MAX_BROKER_STATE_COLLECTION_ITEMS = 10_000

_TOP_KEYS = frozenset(
    {
        "wire_version",
        "snapshot_schema_version",
        "authority_ref",
        "bindings",
        "sessions",
        "commands",
        "last_sequence_by_binding",
    }
)
_BINDING_KEYS = frozenset(
    {
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "credential_digest",
        "issued_at",
        "credential_expires_at",
        "state",
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
    }
)
_SEQUENCE_KEYS = frozenset({"binding_ref", "sequence"})


def _wire_error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _closed(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} schema mismatch")
    return value


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} must be bounded non-empty text")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} must be a positive integer without coercion")
    return value


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} must be UTC ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} must be valid ISO-8601 text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise _wire_error("invalid_local_agent_broker_state_wire", f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def _optional_utc(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    return _utc(value, label)


def _iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _wire_error("invalid_local_agent_broker_state_wire", "snapshot timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _array(value: Any, label: str) -> list[Any]:
    if type(value) is not list or len(value) > MAX_BROKER_STATE_COLLECTION_ITEMS:
        raise _wire_error(
            "invalid_local_agent_broker_state_wire",
            f"{label} must be a bounded JSON array",
        )
    return value


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _wire_error("duplicate_local_agent_broker_state_wire_key", "duplicate JSON object key is forbidden")
        result[key] = value
    return result


def _binding_wire(value: BrokerDeviceBinding) -> dict[str, Any]:
    return {
        "binding_ref": value.binding_ref,
        "device_id": value.device_id,
        "account_ref": value.account_ref,
        "workspace_ref": value.workspace_ref,
        "credential_generation": value.credential_generation,
        "credential_digest": value.credential_digest,
        "issued_at": _iso(value.issued_at),
        "credential_expires_at": _iso(value.credential_expires_at),
        "state": value.state.value,
    }


def _session_wire(value: BrokerDeviceSession) -> dict[str, Any]:
    return {
        "session_id": value.session_id,
        "binding_ref": value.binding_ref,
        "device_id": value.device_id,
        "account_ref": value.account_ref,
        "workspace_ref": value.workspace_ref,
        "credential_generation": value.credential_generation,
        "issued_at": _iso(value.issued_at),
        "expires_at": _iso(value.expires_at),
    }


def _command_wire(value: BrokerCommandRecord) -> dict[str, Any]:
    return {
        "command_id": value.command_id,
        "run_id": value.run_id,
        "tool_request_ref": value.tool_request_ref,
        "binding_ref": value.binding_ref,
        "credential_generation": value.credential_generation,
        "sequence": value.sequence,
        "request_fingerprint": value.request_fingerprint,
        "issued_at": _iso(value.issued_at),
        "expires_at": _iso(value.expires_at),
        "state": value.state.value,
        "admission_ref": value.admission_ref,
        "evidence_ref": value.evidence_ref,
        "admitted_session_id": value.admitted_session_id,
        "admitted_at": _iso(value.admitted_at) if value.admitted_at is not None else None,
        "acknowledged_at": _iso(value.acknowledged_at) if value.acknowledged_at is not None else None,
    }


class LocalAgentBrokerStateJsonCodec:
    """Deterministic, closed JSON wire codec for trusted broker authority state."""

    def encode(self, snapshot: LocalAgentBrokerStateSnapshot) -> bytes:
        if not isinstance(snapshot, LocalAgentBrokerStateSnapshot):
            raise ValueError("snapshot must be LocalAgentBrokerStateSnapshot")
        for label, collection in (
            ("bindings", snapshot.bindings),
            ("sessions", snapshot.sessions),
            ("commands", snapshot.commands),
            ("last_sequence_by_binding", snapshot.last_sequence_by_binding),
        ):
            if len(collection) > MAX_BROKER_STATE_COLLECTION_ITEMS:
                raise _wire_error("local_agent_broker_state_wire_too_large", f"{label} exceeds collection bound")
        wire = {
            "wire_version": BROKER_STATE_WIRE_VERSION,
            "snapshot_schema_version": snapshot.schema_version,
            "authority_ref": snapshot.authority_ref,
            "bindings": [_binding_wire(item) for item in snapshot.bindings],
            "sessions": [_session_wire(item) for item in snapshot.sessions],
            "commands": [_command_wire(item) for item in snapshot.commands],
            "last_sequence_by_binding": [
                {"binding_ref": binding_ref, "sequence": sequence}
                for binding_ref, sequence in snapshot.last_sequence_by_binding
            ],
        }
        encoded = json.dumps(
            wire,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if not encoded or len(encoded) > MAX_BROKER_STATE_WIRE_BYTES:
            raise _wire_error("local_agent_broker_state_wire_too_large", "serialized broker state exceeds byte bound")
        return encoded

    def decode(self, payload: bytes) -> LocalAgentBrokerStateSnapshot:
        if not isinstance(payload, bytes) or not payload:
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized broker state must be non-empty bytes")
        if len(payload) > MAX_BROKER_STATE_WIRE_BYTES:
            raise _wire_error("local_agent_broker_state_wire_too_large", "serialized broker state exceeds byte bound")
        try:
            decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_no_duplicate_object)
        except UnicodeDecodeError as exc:
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized broker state must be UTF-8 JSON") from exc
        except json.JSONDecodeError as exc:
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized broker state must be valid JSON") from exc
        top = _closed(decoded, _TOP_KEYS, "broker state wire")
        if top["wire_version"] != BROKER_STATE_WIRE_VERSION:
            raise _wire_error("unsupported_local_agent_broker_state_wire", "unsupported broker state wire version")
        if top["snapshot_schema_version"] != BROKER_STATE_SCHEMA_VERSION:
            raise _wire_error("unsupported_local_agent_broker_state", "unsupported broker snapshot schema version")
        authority_ref = _text(top["authority_ref"], "authority_ref", maximum=256)

        bindings: list[BrokerDeviceBinding] = []
        for raw in _array(top["bindings"], "bindings"):
            item = _closed(raw, _BINDING_KEYS, "broker binding wire")
            try:
                state = BrokerBindingState(_text(item["state"], "binding state", maximum=32))
            except ValueError as exc:
                raise _wire_error("invalid_local_agent_broker_state_wire", "unknown broker binding state") from exc
            bindings.append(
                BrokerDeviceBinding(
                    binding_ref=_text(item["binding_ref"], "binding_ref"),
                    device_id=_text(item["device_id"], "device_id"),
                    account_ref=_text(item["account_ref"], "account_ref"),
                    workspace_ref=_text(item["workspace_ref"], "workspace_ref"),
                    credential_generation=_positive_int(item["credential_generation"], "credential_generation"),
                    credential_digest=_text(item["credential_digest"], "credential_digest", maximum=64),
                    issued_at=_utc(item["issued_at"], "binding issued_at"),
                    credential_expires_at=_utc(item["credential_expires_at"], "credential_expires_at"),
                    state=state,
                )
            )

        sessions: list[BrokerDeviceSession] = []
        for raw in _array(top["sessions"], "sessions"):
            item = _closed(raw, _SESSION_KEYS, "broker session wire")
            sessions.append(
                BrokerDeviceSession(
                    session_id=_text(item["session_id"], "session_id"),
                    binding_ref=_text(item["binding_ref"], "binding_ref"),
                    device_id=_text(item["device_id"], "device_id"),
                    account_ref=_text(item["account_ref"], "account_ref"),
                    workspace_ref=_text(item["workspace_ref"], "workspace_ref"),
                    credential_generation=_positive_int(item["credential_generation"], "credential_generation"),
                    issued_at=_utc(item["issued_at"], "session issued_at"),
                    expires_at=_utc(item["expires_at"], "session expires_at"),
                )
            )

        commands: list[BrokerCommandRecord] = []
        for raw in _array(top["commands"], "commands"):
            item = _closed(raw, _COMMAND_KEYS, "broker command wire")
            try:
                state = BrokerCommandState(_text(item["state"], "command state", maximum=32))
            except ValueError as exc:
                raise _wire_error("invalid_local_agent_broker_state_wire", "unknown broker command state") from exc
            commands.append(
                BrokerCommandRecord(
                    command_id=_text(item["command_id"], "command_id"),
                    run_id=_text(item["run_id"], "run_id"),
                    tool_request_ref=_text(item["tool_request_ref"], "tool_request_ref"),
                    binding_ref=_text(item["binding_ref"], "binding_ref"),
                    credential_generation=_positive_int(item["credential_generation"], "credential_generation"),
                    sequence=_positive_int(item["sequence"], "sequence"),
                    request_fingerprint=_text(item["request_fingerprint"], "request_fingerprint", maximum=64),
                    issued_at=_utc(item["issued_at"], "command issued_at"),
                    expires_at=_utc(item["expires_at"], "command expires_at"),
                    state=state,
                    admission_ref=_optional_text(item["admission_ref"], "admission_ref"),
                    evidence_ref=_optional_text(item["evidence_ref"], "evidence_ref"),
                    admitted_session_id=_optional_text(item["admitted_session_id"], "admitted_session_id"),
                    admitted_at=_optional_utc(item["admitted_at"], "admitted_at"),
                    acknowledged_at=_optional_utc(item["acknowledged_at"], "acknowledged_at"),
                )
            )

        sequence_entries: list[tuple[str, int]] = []
        for raw in _array(top["last_sequence_by_binding"], "last_sequence_by_binding"):
            item = _closed(raw, _SEQUENCE_KEYS, "broker sequence wire")
            sequence_entries.append(
                (
                    _text(item["binding_ref"], "sequence binding_ref"),
                    _positive_int(item["sequence"], "last sequence"),
                )
            )

        return LocalAgentBrokerStateSnapshot(
            authority_ref=authority_ref,
            bindings=tuple(bindings),
            sessions=tuple(sessions),
            commands=tuple(commands),
            last_sequence_by_binding=tuple(sequence_entries),
            schema_version=top["snapshot_schema_version"],
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "wire_version": BROKER_STATE_WIRE_VERSION,
            "deterministic_json": True,
            "closed_schema": True,
            "duplicate_json_key_rejected": True,
            "max_wire_bytes": MAX_BROKER_STATE_WIRE_BYTES,
            "max_collection_items": MAX_BROKER_STATE_COLLECTION_ITEMS,
            "raw_device_credential_serialized": False,
            "credential_digest_safe_projection": False,
            "pickle_or_arbitrary_object_deserialization": False,
        }


@dataclass(frozen=True, slots=True)
class SerializedLocalAgentBrokerStateRecord:
    version: int
    payload: bytes

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise ValueError("serialized broker state version must be a positive integer")
        if not isinstance(self.payload, bytes) or not self.payload or len(self.payload) > MAX_BROKER_STATE_WIRE_BYTES:
            raise ValueError("serialized broker state payload must be bounded non-empty bytes")


class AtomicSerializedLocalAgentBrokerStateBackend(Protocol):
    durable: bool

    def load(self, *, authority_ref: str) -> SerializedLocalAgentBrokerStateRecord | None:
        ...

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        payload: bytes,
    ) -> SerializedLocalAgentBrokerStateRecord:
        ...


class InMemorySerializedLocalAgentBrokerStateBackend:
    """Deterministic serialized CAS backend for tests. Explicitly not durable."""

    durable = False

    def __init__(self) -> None:
        self._rows: dict[str, SerializedLocalAgentBrokerStateRecord] = {}

    def load(self, *, authority_ref: str) -> SerializedLocalAgentBrokerStateRecord | None:
        _text(authority_ref, "authority_ref", maximum=256)
        return self._rows.get(authority_ref)

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        payload: bytes,
    ) -> SerializedLocalAgentBrokerStateRecord:
        _text(authority_ref, "authority_ref", maximum=256)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BROKER_STATE_WIRE_BYTES:
            raise ValueError("serialized broker state payload must be bounded non-empty bytes")
        current = self._rows.get(authority_ref)
        current_version = current.version if current is not None else 0
        if current_version != expected_version:
            raise _wire_error(
                "stale_local_agent_broker_state",
                "Local Agent broker serialized state changed concurrently; stale write refused",
            )
        stored = SerializedLocalAgentBrokerStateRecord(version=expected_version + 1, payload=payload)
        self._rows[authority_ref] = stored
        return stored

    def safe_dict(self) -> dict[str, Any]:
        return {
            "atomic_compare_and_swap": True,
            "serialized_backend": True,
            "durable": False,
            "production_store": False,
        }


class SerializedLocalAgentBrokerStatePort:
    """#1785 object-state port implemented over an atomic serialized backend."""

    def __init__(
        self,
        *,
        backend: AtomicSerializedLocalAgentBrokerStateBackend,
        codec: LocalAgentBrokerStateJsonCodec | None = None,
    ) -> None:
        for method_name in ("load", "compare_and_swap"):
            if not callable(getattr(backend, method_name, None)):
                raise ValueError("backend must implement serialized broker state operations")
        if type(getattr(backend, "durable", None)) is not bool:
            raise ValueError("backend must explicitly declare durable boolean")
        self._backend = backend
        self._codec = codec or LocalAgentBrokerStateJsonCodec()
        if not isinstance(self._codec, LocalAgentBrokerStateJsonCodec):
            raise ValueError("codec must be LocalAgentBrokerStateJsonCodec")
        self.durable = backend.durable

    def load(self, *, authority_ref: str) -> VersionedLocalAgentBrokerState:
        _text(authority_ref, "authority_ref", maximum=256)
        stored = self._backend.load(authority_ref=authority_ref)
        if stored is None:
            return VersionedLocalAgentBrokerState(
                version=0,
                snapshot=LocalAgentBrokerStateSnapshot.empty(authority_ref=authority_ref),
            )
        if not isinstance(stored, SerializedLocalAgentBrokerStateRecord):
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized backend returned invalid record")
        snapshot = self._codec.decode(stored.payload)
        if snapshot.authority_ref != authority_ref:
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized broker state authority mismatch")
        return VersionedLocalAgentBrokerState(version=stored.version, snapshot=snapshot)

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        snapshot: LocalAgentBrokerStateSnapshot,
    ) -> VersionedLocalAgentBrokerState:
        _text(authority_ref, "authority_ref", maximum=256)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(snapshot, LocalAgentBrokerStateSnapshot) or snapshot.authority_ref != authority_ref:
            raise ValueError("snapshot authority mismatch")
        encoded = self._codec.encode(snapshot)
        stored = self._backend.compare_and_swap(
            authority_ref=authority_ref,
            expected_version=expected_version,
            payload=encoded,
        )
        if not isinstance(stored, SerializedLocalAgentBrokerStateRecord):
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized backend returned invalid CAS record")
        if stored.version != expected_version + 1 or stored.payload != encoded:
            raise _wire_error("invalid_local_agent_broker_state_wire", "serialized backend violated exact CAS contract")
        return VersionedLocalAgentBrokerState(version=stored.version, snapshot=snapshot)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "serialized_state_adapter_to_m2f": True,
            "atomic_compare_and_swap": True,
            "backend_durable": self.durable,
            "canonical_snapshot_validation_reused": True,
            "raw_device_credential_serialized": False,
            "database_driver_selected": False,
            "provider_specific_sql": False,
            "production_store_configured": False,
            "production_ready": False,
        }


BROKER_STATE_JSON_CODEC = True
DETERMINISTIC_WIRE_ENCODING = True
CLOSED_WIRE_SCHEMA = True
DUPLICATE_JSON_KEY_REJECTED = True
BOUNDED_SERIALIZED_STATE = True
ATOMIC_SERIALIZED_BACKEND_PORT = True
SERIALIZED_STATE_ADAPTER_TO_M2F = True
CANONICAL_SNAPSHOT_VALIDATION_REUSED = True
RAW_DEVICE_CREDENTIAL_SERIALIZED = False
PICKLE_OR_ARBITRARY_OBJECT_DESERIALIZATION = False
IN_MEMORY_SERIALIZED_BACKEND_COUNTS_AS_DURABLE = False
DATABASE_DRIVER_SELECTED = False
PROVIDER_SPECIFIC_SQL = False
PRODUCTION_STORE_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
