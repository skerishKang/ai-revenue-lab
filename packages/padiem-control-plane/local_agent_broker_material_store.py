from __future__ import annotations

import json
import re
from typing import Any

from padiem_control_plane.local_agent_broker_http import LocalAgentMaterialResolutionRequest
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort
from local_agent_broker_sql_state import iso, parse_iso, positive_int, row_value, rows, rows_written, safe_ref

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_DURABLE_COMMAND_MATERIAL_BYTES = 196_608
_MATERIAL_WIRE_KEYS = frozenset({"contract_version", "command_id", "binding_ref", "sequence", "request_fingerprint", "material"})
_MATERIAL_KEYS = frozenset({"request_id", "run_id", "device_id", "root_ref", "argv", "cwd_relative", "requested_at", "timeout_seconds", "shell_authority", "admin_elevation", "environment_payload", "provider_authority", "p01_approval_payload"})
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


def digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def canonical_json(value: dict[str, Any], *, maximum_bytes: int, label: str) -> tuple[str, bytes]:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be deterministic JSON") from exc
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > maximum_bytes:
        raise ValueError(f"{label} exceeds the serialized size bound")
    return text, encoded


class CloudflareDurableObjectCommandMaterialStore:
    """Durable exact-wire resolver for already-enqueued canonical broker commands."""

    durable = True

    def __init__(self, storage: Any, *, state_port: SerializedLocalAgentBrokerStatePort, authority_ref: str) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        if not isinstance(state_port, SerializedLocalAgentBrokerStatePort):
            raise ValueError("state_port must be SerializedLocalAgentBrokerStatePort")
        self._storage = storage
        self._sql = sql
        self._state_port = state_port
        self._authority_ref = safe_ref(authority_ref, "authority_ref")
        self._sql.exec(_COMMAND_MATERIAL_SCHEMA)

    def _command(self, command_id: str):
        command_id = safe_ref(command_id, "command_id")
        snapshot = self._state_port.load(authority_ref=self._authority_ref).snapshot
        matches = [item for item in snapshot.commands if item.command_id == command_id]
        if len(matches) != 1:
            raise ValueError("command material requires one canonical persisted broker command")
        return matches[0]

    def _validate_wire(self, wire: Any, *, command: Any) -> tuple[dict[str, Any], str]:
        wire = closed_mapping(wire, _MATERIAL_WIRE_KEYS, "command material wire")
        if wire["contract_version"] != "claw-local-command-material.v1":
            raise ValueError("unsupported Local Agent command material contract version")
        command_id = safe_ref(wire["command_id"], "command_id")
        binding_ref = safe_ref(wire["binding_ref"], "binding_ref")
        sequence = positive_int(wire["sequence"], "sequence")
        fingerprint = digest(wire["request_fingerprint"], "request_fingerprint")
        if command_id != command.command_id or binding_ref != command.binding_ref or sequence != command.sequence or fingerprint != command.request_fingerprint:
            raise ValueError("command material wire does not match canonical broker command")
        if command.state.value != "queued":
            raise ValueError("new command material requires a queued canonical broker command")
        material = closed_mapping(wire["material"], _MATERIAL_KEYS, "command material")
        if material["shell_authority"] is not False or material["admin_elevation"] is not False:
            raise ValueError("command material cannot grant shell or admin authority")
        for field_name in ("environment_payload", "provider_authority", "p01_approval_payload"):
            if material[field_name] is not None:
                raise ValueError(f"command material {field_name} must remain null")
        argv = material["argv"]
        if type(argv) is not list or not all(type(item) is str for item in argv):
            raise ValueError("command material argv must be a JSON text list")
        wire_text, _ = canonical_json(wire, maximum_bytes=MAX_DURABLE_COMMAND_MATERIAL_BYTES, label="command material wire")
        return wire, wire_text

    def store(self, wire: dict[str, Any]) -> dict[str, Any]:
        command_id = safe_ref(wire.get("command_id") if isinstance(wire, dict) else None, "command_id")
        command = self._command(command_id)
        wire, wire_text = self._validate_wire(wire, command=command)
        cursor = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_command_material (command_id, binding_ref, sequence, request_fingerprint, expires_at, wire_text) VALUES (?, ?, ?, ?, ?, ?)",
            command.command_id, command.binding_ref, command.sequence, command.request_fingerprint, iso(command.expires_at), wire_text,
        )
        if rows_written(cursor) != 1:
            raise ValueError("command material already exists or binding sequence was rebound")
        return {"stored": True, "command_id": command.command_id, "binding_ref": command.binding_ref, "sequence": command.sequence, "request_fingerprint": command.request_fingerprint, "expires_at": iso(command.expires_at), "raw_argv": False, "raw_device_credential": False, "execution_approval": False}

    def _load_row(self, command_id: str) -> Any | None:
        found = rows(self._sql.exec("SELECT command_id, binding_ref, sequence, request_fingerprint, expires_at, wire_text FROM local_agent_command_material WHERE command_id = ?", safe_ref(command_id, "command_id")))
        if len(found) > 1:
            raise RuntimeError("command material lookup was ambiguous")
        return found[0] if found else None

    def resolve(self, request: LocalAgentMaterialResolutionRequest) -> dict[str, Any]:
        if not isinstance(request, LocalAgentMaterialResolutionRequest):
            raise ValueError("request must be LocalAgentMaterialResolutionRequest")
        row = self._load_row(request.command_id)
        if row is None:
            raise RuntimeError("durable Local Agent command material is not available")
        expires_at = parse_iso(row_value(row, "expires_at"), "material.expires_at")
        if request.server_requested_at >= expires_at:
            self.purge_command(request.command_id)
            raise RuntimeError("durable Local Agent command material is expired")
        if safe_ref(row_value(row, "binding_ref"), "binding_ref") != request.binding_ref or digest(row_value(row, "request_fingerprint"), "request_fingerprint") != request.request_fingerprint:
            raise ValueError("command material resolution correlation mismatch")
        command = self._command(request.command_id)
        if command.state.value != "queued" or request.server_requested_at >= command.expires_at:
            self.purge_command(request.command_id)
            raise RuntimeError("canonical broker command is no longer material-resolvable")
        wire_text = row_value(row, "wire_text")
        if not isinstance(wire_text, str) or not wire_text:
            raise RuntimeError("stored command material wire is invalid")
        try:
            wire = json.loads(wire_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("stored command material wire is invalid") from exc
        wire, canonical_text = self._validate_wire(wire, command=command)
        if canonical_text != wire_text:
            raise RuntimeError("stored command material wire is not canonical")
        if positive_int(row_value(row, "sequence"), "sequence") != command.sequence:
            raise ValueError("stored command material sequence mismatch")
        return wire

    def purge_command(self, command_id: str) -> int:
        return rows_written(self._sql.exec("DELETE FROM local_agent_command_material WHERE command_id = ?", safe_ref(command_id, "command_id")))

    def purge_binding(self, binding_ref: str) -> int:
        return rows_written(self._sql.exec("DELETE FROM local_agent_command_material WHERE binding_ref = ?", safe_ref(binding_ref, "binding_ref")))

    def safe_dict(self) -> dict[str, Any]:
        return {"durable": True, "separate_material_table": True, "canonical_material_wire_reused": True, "second_fingerprint_algorithm": False, "broker_metadata_expanded_with_argv": False, "raw_device_credential_persisted": False, "execution_approval": False, "production_deployment": False}


COMMAND_MATERIAL_STORE_SEPARATED = True
CANONICAL_MATERIAL_WIRE_REUSED = True
FINGERPRINT_AUTHORITY_CHANGED = False
BROKER_MATERIAL_BOUNDARY_CHANGED = False
CLOUD_PLATFORM_IMPORT_REQUIRED = False
