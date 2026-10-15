from __future__ import annotations

import json
import re
from typing import Any

from padiem_control_plane.local_agent_broker_http import LocalAgentMaterialResolutionRequest
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort
from local_agent_broker_sql_state import iso, parse_iso, positive_int, row_value, rows, rows_written, safe_ref

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_DURABLE_COMMAND_MATERIAL_BYTES = 196_608
# #4139: the closed TXT approval receipt envelope (claw-txt-read-approval.v1).
# The Chat worker mints it from the authenticated owner request; this store
# only persists it. Storing grants nothing: the Resident verifies digests,
# expiry, correlation and one-shot use before any READ. The bilateral
# constants must match the issuance module and the Resident parser verbatim.
TXT_RECEIPT_FORMAT = "claw-txt-read-approval.v1"
TXT_RECEIPT_TOOL_ID = "local.filesystem.read"
TXT_RECEIPT_REQUIREMENT = "user_confirmation"
TXT_RECEIPT_OUTCOME = "approved"
TXT_RECEIPT_SCOPE = ("filesystem.read",)
TXT_RECEIPT_OPERATION = "read"
TXT_RECEIPT_AUTHORITY_REF = "claw_connector_txt_request_v1"
TXT_RECEIPT_POLICY_REF = "padiem_txt_selected_root_read_policy_v1"
TXT_RECEIPT_SUFFIX = ".txt"
_TXT_RECEIPT_KEYS = frozenset({
    "format", "evidence_ref", "command_id", "request_id",
    "approval_pause", "approval_decision", "exact_tool_arguments",
    "local_policy_ref", "expires_at",
})
_TXT_PAUSE_KEYS = frozenset({
    "pause_id", "run_id", "agent_runtime_id", "tool_id",
    "invocation_sha256", "requirement", "step_index",
    "created_at", "expires_at", "approval_scope",
})
_TXT_DECISION_KEYS = frozenset({
    "decision_id", "pause_id", "outcome",
    "authority_ref", "evidence_ref", "decided_at",
})
_TXT_ARG_KEYS = frozenset({
    "action_id", "run_id", "device_id", "root_ref",
    "operation", "path_relative", "requested_at", "request_fingerprint",
    "content_bytes", "content_sha256", "directory_enumeration",
    "recursive_delete", "admin_elevation",
})
_MATERIAL_WIRE_KEYS = frozenset({"contract_version", "command_id", "binding_ref", "sequence", "request_fingerprint", "revision_ref", "material"})
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
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def _bounded_ref(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 512
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def _bounded_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe identifier")
    return value


def _iso_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = parse_iso(value, field_name)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601 text") from exc
    return value


def _relative_txt_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(f"{field_name} must be a bounded relative Windows file path")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not carry surrounding whitespace")
    lowered = value.replace("/", "\\")
    if lowered.startswith("\\") or (len(lowered) >= 2 and lowered[1] == ":"):
        raise ValueError(f"{field_name} must remain inside the selected root")
    if any(part == ".." for part in re.split(r"[\\/]", lowered)):
        raise ValueError(f"{field_name} traversal is not allowed")
    if not lowered.lower().endswith(TXT_RECEIPT_SUFFIX):
        raise ValueError(f"{field_name} must name an exact TXT file")
    return value


def validate_txt_approval_receipt(value: Any) -> dict[str, Any]:
    """Validate the closed TXT approval envelope shape (no approval granted).

    Structural shape only: exact keys, bounded types, enum constants, digest
    shapes and parseable timestamps. Digest recomputation, expiry against now,
    command correlation and one-shot use are verified Resident-side by the
    plan source before any READ; this store only refuses malformed envelopes.
    """
    receipt = closed_mapping(value, _TXT_RECEIPT_KEYS, "TXT approval receipt")
    if receipt["format"] != TXT_RECEIPT_FORMAT:
        raise ValueError("TXT approval receipt format mismatch")
    _bounded_ref(receipt["evidence_ref"], "receipt.evidence_ref")
    _bounded_ref(receipt["command_id"], "receipt.command_id")
    _bounded_ref(receipt["request_id"], "receipt.request_id")
    if receipt["local_policy_ref"] != TXT_RECEIPT_POLICY_REF:
        raise ValueError("TXT approval receipt policy mismatch")
    _iso_text(receipt["expires_at"], "receipt.expires_at")
    pause = closed_mapping(receipt["approval_pause"], _TXT_PAUSE_KEYS, "TXT approval pause")
    _bounded_id(pause["pause_id"], "pause.pause_id")
    _bounded_id(pause["run_id"], "pause.run_id")
    _bounded_id(pause["agent_runtime_id"], "pause.agent_runtime_id")
    if pause["tool_id"] != TXT_RECEIPT_TOOL_ID:
        raise ValueError("TXT approval pause tool mismatch")
    digest(pause["invocation_sha256"], "pause.invocation_sha256")
    if pause["requirement"] != TXT_RECEIPT_REQUIREMENT:
        raise ValueError("TXT approval pause requirement mismatch")
    if isinstance(pause["step_index"], bool) or not isinstance(pause["step_index"], int):
        raise ValueError("TXT approval pause step_index must be an integer")
    if not 1 <= pause["step_index"] <= 64:
        raise ValueError("TXT approval pause step_index out of range")
    _iso_text(pause["created_at"], "pause.created_at")
    _iso_text(pause["expires_at"], "pause.expires_at")
    if not isinstance(pause["approval_scope"], list) or pause["approval_scope"] != list(TXT_RECEIPT_SCOPE):
        raise ValueError("TXT approval pause scope mismatch")
    decision = closed_mapping(receipt["approval_decision"], _TXT_DECISION_KEYS, "TXT approval decision")
    _bounded_id(decision["decision_id"], "decision.decision_id")
    if decision["pause_id"] != pause["pause_id"]:
        raise ValueError("TXT approval decision does not belong to the pause")
    if decision["outcome"] != TXT_RECEIPT_OUTCOME:
        raise ValueError("TXT approval decision outcome mismatch")
    if decision["authority_ref"] != TXT_RECEIPT_AUTHORITY_REF:
        raise ValueError("TXT approval decision authority mismatch")
    _bounded_ref(decision["evidence_ref"], "decision.evidence_ref")
    if decision["evidence_ref"] != receipt["evidence_ref"]:
        raise ValueError("TXT approval decision evidence_ref mismatch")
    _iso_text(decision["decided_at"], "decision.decided_at")
    args = closed_mapping(receipt["exact_tool_arguments"], _TXT_ARG_KEYS, "TXT approval arguments")
    _bounded_ref(args["action_id"], "args.action_id")
    _bounded_ref(args["run_id"], "args.run_id")
    _bounded_ref(args["device_id"], "args.device_id")
    _bounded_ref(args["root_ref"], "args.root_ref")
    if args["operation"] != TXT_RECEIPT_OPERATION:
        raise ValueError("TXT approval arguments operation mismatch")
    _relative_txt_path(args["path_relative"], "args.path_relative")
    _iso_text(args["requested_at"], "args.requested_at")
    digest(args["request_fingerprint"], "args.request_fingerprint")
    if type(args["content_bytes"]) is not int or args["content_bytes"] != 0:
        raise ValueError("TXT approval arguments must describe a pre-read intent")
    if args["content_sha256"] is not None:
        raise ValueError("TXT approval arguments must describe a pre-read intent")
    for flag in ("directory_enumeration", "recursive_delete", "admin_elevation"):
        if args[flag] is not False:
            raise ValueError(f"TXT approval arguments {flag} must be false")
    return receipt


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
        if wire["contract_version"] != "claw-local-command-material.v2":
            raise ValueError("unsupported Local Agent command material contract version")
        command_id = safe_ref(wire["command_id"], "command_id")
        binding_ref = safe_ref(wire["binding_ref"], "binding_ref")
        sequence = positive_int(wire["sequence"], "sequence")
        fingerprint = digest(wire["request_fingerprint"], "request_fingerprint")
        revision_ref = safe_ref(wire["revision_ref"], "revision_ref")
        if command_id != command.command_id or binding_ref != command.binding_ref or sequence != command.sequence or fingerprint != command.request_fingerprint:
            raise ValueError("command material wire does not match canonical broker command")
        if revision_ref != command.revision_ref:
            raise ValueError("command material wire does not match the canonical broker revision_ref")
        if command.state.value != "queued":
            raise ValueError("new command material requires a queued canonical broker command")
        material = closed_mapping(wire["material"], _MATERIAL_KEYS, "command material")
        if material["shell_authority"] is not False or material["admin_elevation"] is not False:
            raise ValueError("command material cannot grant shell or admin authority")
        for field_name in ("environment_payload", "provider_authority"):
            if material[field_name] is not None:
                raise ValueError(f"command material {field_name} must remain null")
        approval = material["p01_approval_payload"]
        if approval is not None:
            # #4139: a closed TXT approval receipt may ride the material.
            # Storing it grants nothing; the Resident verifies digests, expiry,
            # command correlation and one-shot use before any READ.
            receipt = validate_txt_approval_receipt(approval)
            if receipt["command_id"] != command_id:
                raise ValueError("TXT approval receipt does not belong to this command")
            if receipt["exact_tool_arguments"]["run_id"] != material["run_id"]:
                raise ValueError("TXT approval receipt run does not match the material")
            if receipt["exact_tool_arguments"]["device_id"] != material["device_id"]:
                raise ValueError("TXT approval receipt device does not match the material")
            if receipt["exact_tool_arguments"]["root_ref"] != material["root_ref"]:
                raise ValueError("TXT approval receipt root does not match the material")
            if receipt["request_id"] != material["request_id"]:
                raise ValueError("TXT approval receipt request does not match the material")
        argv = material["argv"]
        if type(argv) is not list or not all(type(item) is str for item in argv):
            raise ValueError("command material argv must be a JSON text list")
        wire_text, _ = canonical_json(wire, maximum_bytes=MAX_DURABLE_COMMAND_MATERIAL_BYTES, label="command material wire")
        return wire, wire_text

    def _projection(self, command: Any) -> dict[str, Any]:
        return {"stored": True, "command_id": command.command_id, "binding_ref": command.binding_ref, "sequence": command.sequence, "request_fingerprint": command.request_fingerprint, "expires_at": iso(command.expires_at), "raw_argv": False, "raw_device_credential": False, "execution_approval": False}

    def store(self, wire: dict[str, Any]) -> dict[str, Any]:
        """Persist one command's material, reusing an identical earlier write.

        #3127 — the write is idempotent for an *exact* retry and fails closed on
        any other difference. The previous behaviour refused every repeat, which
        turned a lost `store_command_material` response into an unrecoverable
        state: the caller could not tell a persisted material from a failed one,
        and the only way to "retry" was an error. Reuse returns the existing
        projection unchanged, so a lost response is recoverable without minting a
        second material row, a second sequence or a second revision.
        """

        command_id = safe_ref(wire.get("command_id") if isinstance(wire, dict) else None, "command_id")
        command = self._command(command_id)
        wire, wire_text = self._validate_wire(wire, command=command)
        cursor = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_command_material (command_id, binding_ref, sequence, request_fingerprint, expires_at, wire_text) VALUES (?, ?, ?, ?, ?, ?)",
            command.command_id, command.binding_ref, command.sequence, command.request_fingerprint, iso(command.expires_at), wire_text,
        )
        if rows_written(cursor) == 1:
            return self._projection(command)
        existing = self._load_row(command_id)
        if existing is None or row_value(existing, "wire_text") != wire_text:
            # Either a different material already occupies this command, or the
            # binding/sequence pair is held by another command. Both are conflicts
            # a retry must never paper over.
            raise ValueError("command material already exists or binding sequence was rebound")
        return {**self._projection(command), "reused": True}

    def has_persisted_material(self, command_id: str) -> bool:
        """True only when this command's exact material row is durable.

        Presence is deliberately lifecycle-independent: admission checks it while
        the command is still queued and acknowledgement checks it after the
        command is terminal, so the answer must come from the material row alone
        and never from a lifecycle state this store does not own.
        """

        command_id = safe_ref(command_id, "command_id")
        return self._load_row(command_id) is not None

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
