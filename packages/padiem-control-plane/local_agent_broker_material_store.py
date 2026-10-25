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
# #5080: the Android SAF lane carries the same canonical approval object model
# with its own bilateral constants. It is a distinct closed format, not a
# relaxation of the Windows one: a receipt is validated against exactly the
# authority/policy its own discriminator names.
ANDROID_TXT_RECEIPT_FORMAT = "claw-android-saf-txt-read-approval.v1"

#: #4434: the closed XLSX revision envelope. It attests the READ of a PC workcopy
#: and carries the reviewed literal edits; the WRITE is attested Resident-side only
#: after the result bytes exist, so nothing on this wire can approve a write.
#: These constants are bilateral with ``kagent.local_agent_command_material`` and
#: are pinned key for key by a cross-implementation test.
XLSX_REVISION_RECEIPT_FORMAT = "claw-xlsx-revision-approval.v1"
XLSX_REVISION_READ_TOOL_ID = "local.filesystem.read"
XLSX_REVISION_OUTCOME = "approved"
XLSX_REVISION_REQUIREMENT = "user_confirmation"
XLSX_REVISION_READ_SCOPE = ("filesystem.read",)
XLSX_REVISION_AUTHORITY_REF = "claw_connector_xlsx_revision_request_v1"
XLSX_REVISION_POLICY_REF = "padiem_xlsx_selected_root_revision_policy_v1"
XLSX_REVISION_SUFFIX = ".xlsx"
XLSX_REVISION_EDIT_LIMIT = 64
_XLSX_REVISION_CELL_RE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
_XLSX_REVISION_SHEET_RE = re.compile(r"^[^\\/:*?[\]]{1,31}$")
_XLSX_REVISION_KEYS = frozenset({
    "format", "evidence_ref", "command_id", "request_id", "local_policy_ref",
    "expires_at", "source_approval", "revision",
})
_XLSX_APPROVAL_KEYS = frozenset({
    "approval_pause", "approval_decision", "exact_tool_arguments",
})
_XLSX_REVISION_INSTRUCTION_KEYS = frozenset({
    "sheet_name", "edits", "result_path_relative", "write_action_id",
    "write_requested_at",
})
_XLSX_EDIT_KEYS = frozenset({"cell", "previous_value", "replacement_value"})
ANDROID_TXT_RECEIPT_AUTHORITY_REF = "claw_connector_android_txt_request_v1"
ANDROID_TXT_RECEIPT_POLICY_REF = "padiem_android_saf_selected_root_read_policy_v1"
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


def _validate_txt_receipt(value: Any, *, format: str, authority_ref: str,
                          policy_ref: str) -> dict[str, Any]:
    receipt = closed_mapping(value, _TXT_RECEIPT_KEYS, "TXT approval receipt")
    if receipt["format"] != format:
        raise ValueError("TXT approval receipt format mismatch")
    _bounded_ref(receipt["evidence_ref"], "receipt.evidence_ref")
    _bounded_ref(receipt["command_id"], "receipt.command_id")
    _bounded_ref(receipt["request_id"], "receipt.request_id")
    if receipt["local_policy_ref"] != policy_ref:
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
    if decision["authority_ref"] != authority_ref:
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


def validate_txt_approval_receipt(value: Any) -> dict[str, Any]:
    """Validate the closed Windows TXT approval envelope (grants nothing).

    Structural shape only: exact keys, bounded types, enum constants, digest
    shapes and parseable timestamps. Digest recomputation, expiry against now,
    command correlation and one-shot use are verified Resident-side by the
    plan source before any READ; this store only refuses malformed envelopes.
    """
    return _validate_txt_receipt(
        value, format=TXT_RECEIPT_FORMAT,
        authority_ref=TXT_RECEIPT_AUTHORITY_REF, policy_ref=TXT_RECEIPT_POLICY_REF,
    )


def validate_android_txt_approval_receipt(value: Any) -> dict[str, Any]:
    """Validate the closed Android SAF TXT approval envelope (grants nothing).

    The Android agent re-checks the exact command correlation, expiry and
    one-shot use before touching a SAF document; storing the envelope here is
    never an execution grant.
    """
    return _validate_txt_receipt(
        value, format=ANDROID_TXT_RECEIPT_FORMAT,
        authority_ref=ANDROID_TXT_RECEIPT_AUTHORITY_REF,
        policy_ref=ANDROID_TXT_RECEIPT_POLICY_REF,
    )


def validate_xlsx_revision_receipt(value: Any) -> dict[str, Any]:
    """Validate the closed XLSX revision envelope (grants nothing).

    Shape only, exactly as the TXT receipts here: exact keys, bounded types, enum
    constants, digest shapes and parseable timestamps. The Resident's plan source
    recomputes the digests, correlates the envelope to the admitted command and
    resolves the write approval separately; this store only refuses a malformed
    envelope, and it refuses any attempt to carry a write approval or a result
    digest on a wire that cannot honestly attest either.
    """
    if type(value) is not dict or frozenset(value) != _XLSX_REVISION_KEYS:
        raise ValueError("XLSX revision receipt schema mismatch")
    receipt = value
    if receipt["format"] != XLSX_REVISION_RECEIPT_FORMAT:
        raise ValueError("XLSX revision receipt format mismatch")
    safe_ref(receipt["evidence_ref"], "receipt.evidence_ref")
    safe_ref(receipt["command_id"], "receipt.command_id")
    safe_ref(receipt["request_id"], "receipt.request_id")
    if receipt["local_policy_ref"] != XLSX_REVISION_POLICY_REF:
        raise ValueError("XLSX revision receipt policy mismatch")
    parse_iso(receipt["expires_at"], "receipt.expires_at")

    approval = receipt["source_approval"]
    if type(approval) is not dict or frozenset(approval) != _XLSX_APPROVAL_KEYS:
        raise ValueError("XLSX revision source approval schema mismatch")
    pause = approval["approval_pause"]
    decision = approval["approval_decision"]
    args = approval["exact_tool_arguments"]
    if type(pause) is not dict or frozenset(pause) != _TXT_PAUSE_KEYS:
        raise ValueError("XLSX revision approval pause schema mismatch")
    if type(decision) is not dict or frozenset(decision) != _TXT_DECISION_KEYS:
        raise ValueError("XLSX revision approval decision schema mismatch")
    if type(args) is not dict or frozenset(args) != _TXT_ARG_KEYS:
        raise ValueError("XLSX revision approval arguments schema mismatch")
    for field_name in ("pause_id", "run_id", "agent_runtime_id"):
        safe_ref(pause[field_name], f"pause.{field_name}")
    if pause["tool_id"] != XLSX_REVISION_READ_TOOL_ID:
        raise ValueError("XLSX revision approval pause tool mismatch")
    if pause["requirement"] != XLSX_REVISION_REQUIREMENT:
        raise ValueError("XLSX revision approval pause requirement mismatch")
    if tuple(pause["approval_scope"]) != XLSX_REVISION_READ_SCOPE:
        raise ValueError("XLSX revision approval pause scope mismatch")
    digest(pause["invocation_sha256"], "pause.invocation_sha256")
    if decision["pause_id"] != pause["pause_id"]:
        raise ValueError("XLSX revision approval decision does not belong to the pause")
    if decision["outcome"] != XLSX_REVISION_OUTCOME:
        raise ValueError("XLSX revision approval decision outcome mismatch")
    if decision["authority_ref"] != XLSX_REVISION_AUTHORITY_REF:
        raise ValueError("XLSX revision approval decision authority mismatch")
    for field_name in ("action_id", "run_id", "device_id", "root_ref"):
        safe_ref(args[field_name], f"args.{field_name}")
    if args["operation"] != "read":
        raise ValueError("XLSX revision approval arguments operation mismatch")
    if args["content_bytes"] != 0 or args["content_sha256"] is not None:
        raise ValueError("XLSX revision approval arguments must describe a pre-read intent")
    digest(args["request_fingerprint"], "args.request_fingerprint")

    revision = receipt["revision"]
    if (type(revision) is not dict
            or frozenset(revision) != _XLSX_REVISION_INSTRUCTION_KEYS):
        raise ValueError("XLSX revision instruction schema mismatch")
    if not isinstance(revision["sheet_name"], str):
        raise ValueError("XLSX revision worksheet name must be text")
    if not _XLSX_REVISION_SHEET_RE.fullmatch(revision["sheet_name"]):
        raise ValueError("XLSX revision worksheet name is not bounded")
    result_path = revision["result_path_relative"]
    if not isinstance(result_path, str) or not result_path:
        raise ValueError("XLSX revision result path must be a relative file path")
    lowered = result_path.replace("/", "\\").casefold()
    if (lowered.startswith("\\") or (len(lowered) >= 2 and lowered[1] == ":")
            or ".." in lowered.replace("\\", "/").split("/")
            or not lowered.endswith(XLSX_REVISION_SUFFIX)):
        raise ValueError("XLSX revision result path must remain inside the selected root")
    safe_ref(revision["write_action_id"], "revision.write_action_id")
    if revision["write_action_id"] == args["action_id"]:
        raise ValueError("XLSX revision read and write must be distinct actions")
    parse_iso(revision["write_requested_at"], "revision.write_requested_at")
    edits = revision["edits"]
    if type(edits) is not list or not 1 <= len(edits) <= XLSX_REVISION_EDIT_LIMIT:
        raise ValueError("XLSX revision edits must be a bounded non-empty list")
    seen: set[str] = set()
    for item in edits:
        if type(item) is not dict or frozenset(item) != _XLSX_EDIT_KEYS:
            raise ValueError("XLSX revision edit schema mismatch")
        cell = item["cell"]
        if not isinstance(cell, str) or not _XLSX_REVISION_CELL_RE.fullmatch(cell):
            raise ValueError("XLSX revision edit cell is not an A1 reference")
        if cell in seen:
            raise ValueError("XLSX revision edit cell is repeated")
        seen.add(cell)
        for field_name in ("previous_value", "replacement_value"):
            literal = item[field_name]
            if isinstance(literal, bool) or not isinstance(literal, (str, int)):
                raise ValueError("XLSX revision edit value must be a literal")
            if isinstance(literal, str) and (not literal or len(literal) > 4096
                                             or literal.startswith("=")):
                raise ValueError("XLSX revision edit value is not a bounded literal")
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
            # #4139/#5080: one closed approval receipt may ride the material.
            # Storing it grants nothing; the executor verifies digests, expiry,
            # command correlation and one-shot use before any READ.
            if not isinstance(approval, dict):
                raise ValueError("command approval receipt must be a mapping")
            if approval.get("format") == TXT_RECEIPT_FORMAT:
                receipt = validate_txt_approval_receipt(approval)
                side = "TXT"
            elif approval.get("format") == ANDROID_TXT_RECEIPT_FORMAT:
                receipt = validate_android_txt_approval_receipt(approval)
                side = "Android TXT"
            elif approval.get("format") == XLSX_REVISION_RECEIPT_FORMAT:
                receipt = validate_xlsx_revision_receipt(approval)
                side = "XLSX revision"
            else:
                raise ValueError("unsupported command approval receipt format")
            if receipt["command_id"] != command_id:
                raise ValueError(f"{side} approval receipt does not belong to this command")
            read_args = (receipt["source_approval"]["exact_tool_arguments"]
                         if side == "XLSX revision"
                         else receipt["exact_tool_arguments"])
            if read_args["run_id"] != material["run_id"]:
                raise ValueError(f"{side} approval receipt run does not match the material")
            if read_args["device_id"] != material["device_id"]:
                raise ValueError(
                    f"{side} approval receipt device does not match the material")
            if read_args["root_ref"] != material["root_ref"]:
                raise ValueError(
                    f"{side} approval receipt root does not match the material")
            if receipt["request_id"] != material["request_id"]:
                raise ValueError(f"{side} approval receipt request does not match the material")
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
