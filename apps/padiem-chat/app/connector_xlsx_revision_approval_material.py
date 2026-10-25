"""#4434 — mint the owner-approved XLSX revision envelope, and nothing more.

A revision is the one PC file operation in this product that *changes* a file, so
the authority boundary here is deliberately narrower than the TXT read lane it
mirrors:

* what is minted is the **READ** attestation of the approved workcopy plus the
  literal edit instruction the owner reviewed — worksheet, cells, the value the
  cell holds now, and the value it will hold. That is the entire content of the
  envelope (`claw-xlsx-revision-approval.v1`).
* what is never minted here is a WRITE approval, a result digest or a write
  request fingerprint. `file_request_fingerprint` and the tool-invocation digest
  bind `content_bytes`/`content_sha256`, so a result digest computed before the PC
  has read the workbook and applied the edits would be a number this server made
  up and asked the PC to treat as consent. The Resident computes the result,
  has it verified independently, and resolves the write approval through the
  existing authenticated ``/v1/broker/p01-evidence`` route.

Every material fact comes from server authorities: the verified owner session,
Identity consent, the Broker-confirmed device binding, the installed Resident
execution profile, and the stored conversation run. Format names, policy refs,
tool ids, the edit limit and the derived-name rule are imported from the Resident
and Broker implementations rather than restated here, so the three ends cannot
drift apart.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import PureWindowsPath
from typing import Any
from uuid import uuid4

from .connector_txt_approval_material import (
    OwnerTxtApprovalProof,
    TxtApprovalMaterialError,
    command_material_fingerprint_for,
    normalize_txt_relative_path,
)

#: The owner-facing review window. A preview that is not confirmed inside it is
#: gone, and the caller must ask again: an approval cannot age into execution.
PREVIEW_WINDOW = timedelta(minutes=5)
APPROVAL_WINDOW = timedelta(minutes=5)
MAX_EDITS_PER_REVISION = 64
XLSX_REVISION_SUFFIX = ".xlsx"
#: The runtime identity the owner-facing lane names on the pause it mints, beside
#: the TXT lane's ``claw_connector_txt_v1``. It identifies who asked, not what is
#: allowed: the Resident's own checks decide that.
XLSX_REVISION_AGENT_RUNTIME_ID = "claw_connector_xlsx_revision_v1"

_MATERIAL_KEYS = ("request_id", "run_id", "device_id", "root_ref", "argv",
                  "cwd_relative", "requested_at", "timeout_seconds",
                  "shell_authority", "admin_elevation", "environment_payload",
                  "provider_authority", "p01_approval_payload")


class XlsxRevisionMaterialError(ValueError):
    """One bounded refusal reason. No path, no value, no owner identity."""


def _canonical_names() -> dict[str, Any]:
    """Read the bilateral constants from the implementations that own them."""

    from kagent.local_agent_command_material import (
        XLSX_REVISION_AUTHORITY_REF, XLSX_REVISION_EDIT_LIMIT,
        XLSX_REVISION_OUTCOME, XLSX_REVISION_POLICY_REF, XLSX_REVISION_READ_REQUIREMENT,
        XLSX_REVISION_READ_SCOPE, XLSX_REVISION_READ_TOOL_ID,
        XLSX_REVISION_RECEIPT_FORMAT,
    )

    return {
        "format": XLSX_REVISION_RECEIPT_FORMAT,
        "tool_id": XLSX_REVISION_READ_TOOL_ID,
        "requirement": XLSX_REVISION_READ_REQUIREMENT,
        "outcome": XLSX_REVISION_OUTCOME,
        "scope": tuple(XLSX_REVISION_READ_SCOPE),
        "authority_ref": XLSX_REVISION_AUTHORITY_REF,
        "policy_ref": XLSX_REVISION_POLICY_REF,
        "edit_limit": XLSX_REVISION_EDIT_LIMIT,
    }


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise XlsxRevisionMaterialError(f"{field_name} must be a bounded identifier")
    return value


def _mint_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


def _installed_executable(executable_path: Any) -> str:
    """The same installed-profile rule the TXT lane enforces, reused verbatim."""

    if not isinstance(executable_path, str) or not executable_path:
        raise XlsxRevisionMaterialError("trusted installed executable profile unavailable")
    installed = PureWindowsPath(executable_path)
    if (not installed.is_absolute() or not _drive_is_letter(installed.drive)
            or installed.suffix.lower() != ".exe"
            or any(part in (".", "..") for part in executable_path.replace("/", "\\").split("\\"))
            or any(ord(ch) < 32 for ch in executable_path)):
        raise XlsxRevisionMaterialError("trusted installed executable profile invalid")
    return str(installed)


def _drive_is_letter(drive: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z]:", drive or ""))


def installed_executable_profile(executable_path: Any) -> str:
    """Public form of the executable check, so a preview refuses early too.

    The mint enforces this anyway; checking it at preview time means an owner is
    told before a reference exists, rather than approving something that can never
    be queued.
    """

    return _installed_executable(executable_path)


def normalize_revision_edits(sheet_name: Any, edits: Any) -> tuple[str, list[dict[str, Any]]]:
    """Validate the proposed edits with the Resident's own contract.

    The cell types, the literal-only rule and the worksheet name come from
    ``kagent.local_xlsx_revision_pdf.ReviewedCellRevision``, so an edit the PC
    would refuse cannot be previewed or approved here.
    """

    from kagent.local_xlsx_revision_pdf import ReviewedCellRevision

    if not isinstance(sheet_name, str) or not sheet_name or len(sheet_name) > 31:
        raise XlsxRevisionMaterialError("sheet_name must be a bounded worksheet name")
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS_PER_REVISION:
        raise XlsxRevisionMaterialError("edits must be a bounded non-empty list")
    validated = []
    seen: set[str] = set()
    for item in edits:
        if not isinstance(item, dict) or set(item) != {"cell", "previous_value",
                                                       "replacement_value"}:
            raise XlsxRevisionMaterialError("each edit names a cell, its value now, and its new value")
        cell = item["cell"]
        if not isinstance(cell, str) or cell in seen:
            raise XlsxRevisionMaterialError("edit cells must be distinct")
        seen.add(cell)
        try:
            revision = ReviewedCellRevision(
                sheet_name=sheet_name, cell=cell,
                previous_value=item["previous_value"],
                replacement_value=item["replacement_value"],
            )
        except Exception as exc:
            raise XlsxRevisionMaterialError("the proposed edit is outside the literal revision contract") from exc
        validated.append({
            "cell": revision.cell,
            "previous_value": revision.previous_value,
            "replacement_value": revision.replacement_value,
        })
    return sheet_name, validated


def normalize_revision_path(value: Any) -> str:
    r"""Owner-named workbook path, normalized by the Resident's own rule.

    The Resident's normalizer folds separators without calling a leading slash an
    escape, so `/srv/book.xlsx` would arrive there as `\srv\book.xlsx` and be
    refused at the file authority — a command minted for a path that can never
    run. Rejecting the absolute shapes here turns that into an owner-facing 400
    before anything is queued.
    """

    import re

    if not isinstance(value, str) or not value:
        raise XlsxRevisionMaterialError("path_relative must name a workbook")
    if (value.startswith("/") or value.startswith("\\")
            or re.match(r"^[A-Za-z]:", value)):
        raise XlsxRevisionMaterialError(
            "the selected workbook must be named inside the selected root")
    try:
        path = normalize_txt_relative_path(value)
    except TxtApprovalMaterialError as exc:
        raise XlsxRevisionMaterialError(
            "the selected workbook must be named inside the selected root") from exc
    if path.startswith("\\") or re.match(r"^[A-Za-z]:", path):
        raise XlsxRevisionMaterialError(
            "the selected workbook must be named inside the selected root")
    if not path.replace("/", "\\").lower().endswith(XLSX_REVISION_SUFFIX):
        raise XlsxRevisionMaterialError("only an exact XLSX selected file can be revised")
    return path


def derived_result_path(path_relative: str) -> str:
    from kagent.local_xlsx_workcopy_roundtrip import revised_path_for

    try:
        return revised_path_for(path_relative)
    except Exception as exc:
        raise XlsxRevisionMaterialError("the selected workbook has no derived result name") from exc


def mint_xlsx_revision_envelope(
    *,
    approval: OwnerTxtApprovalProof,
    root_ref: str,
    path_relative: str,
    sheet_name: str,
    edits: list[dict[str, Any]],
    executable_path: str,
    now: datetime | None = None,
    command_id: str | None = None,
    request_id: str | None = None,
    read_action_id: str | None = None,
    write_action_id: str | None = None,
    tool_request_ref: str | None = None,
) -> dict[str, Any]:
    """Build the closed revision envelope, its command material and the enqueue body.

    ``approval`` must be the trigger-built proof from the verified owner session,
    Identity consent, the Broker-confirmed binding and the stored run. The result
    is JSON-safe, fits the Broker material wire bound, and authorizes one command.
    """

    if not isinstance(approval, OwnerTxtApprovalProof):
        raise XlsxRevisionMaterialError("an owner approval proof is required")
    from kagent.windows_local_filesystem import (
        LocalFileOperation, LocalFileRequest, file_request_fingerprint,
        windows_file_tool_invocation,
    )
    from padiem_ai_core.agent_approval import (
        ApprovalOutcome, ApprovalRequirement, tool_invocation_digest,
    )

    names = _canonical_names()
    installed = _installed_executable(executable_path)
    argv = [installed, "-V"]

    moment = _aware(now if now is not None else datetime.now(timezone.utc))
    command_id = _identifier(command_id or _mint_id("xlsxrevcmd"), "command_id")
    request_id = _identifier(request_id or _mint_id("xlsxrevreq"), "request_id")
    read_action_id = _identifier(read_action_id or _mint_id("xlsxrevread"), "read_action_id")
    write_action_id = _identifier(write_action_id or _mint_id("xlsxrevwrite"), "write_action_id")
    tool_request_ref = _identifier(tool_request_ref or _mint_id("xlsxrevtool"), "tool_request_ref")
    if read_action_id == write_action_id:
        raise XlsxRevisionMaterialError("read and write actions must be distinct")

    try:
        read_request = LocalFileRequest(
            action_id=read_action_id, run_id=approval.run_id,
            device_id=approval.device_id, root_ref=root_ref,
            operation=LocalFileOperation.READ, path_relative=path_relative,
            requested_at=moment,
        )
    except Exception as exc:
        raise XlsxRevisionMaterialError("the selected workbook is not a canonical read intent") from exc
    if not read_request.path_relative.replace("/", "\\").lower().endswith(XLSX_REVISION_SUFFIX):
        raise XlsxRevisionMaterialError("only an exact XLSX selected file can be revised")

    validated_sheet, validated_edits = normalize_revision_edits(sheet_name, edits)
    derived = derived_result_path(read_request.path_relative)

    invocation = windows_file_tool_invocation(read_request)
    arguments = invocation.arguments_copy()
    invocation_sha256 = tool_invocation_digest(invocation)
    fingerprint = file_request_fingerprint(read_request)
    for key, expected in (("operation", "read"), ("content_bytes", 0), ("content_sha256", None)):
        if arguments.get(key) != expected:
            raise XlsxRevisionMaterialError("the read intent must bind no content")
    if arguments.get("request_fingerprint") != fingerprint:
        raise XlsxRevisionMaterialError("read fingerprint does not match the canonical request")

    expires_at = moment + APPROVAL_WINDOW
    pause_id = _identifier(_mint_id("xlsxrevpause"), "pause_id")
    evidence_ref = _identifier(_mint_id("xlsxrevevidence"), "evidence_ref")
    read_approval = {
        "approval_pause": {
            "pause_id": pause_id,
            "run_id": approval.run_id,
            "agent_runtime_id": XLSX_REVISION_AGENT_RUNTIME_ID,
            "tool_id": names["tool_id"],
            "invocation_sha256": invocation_sha256,
            "requirement": ApprovalRequirement.USER_CONFIRMATION.value,
            "step_index": 1,
            "created_at": _iso(moment),
            "expires_at": _iso(expires_at),
            "approval_scope": list(names["scope"]),
        },
        "approval_decision": {
            "decision_id": _identifier(_mint_id("xlsxrevdecision"), "decision_id"),
            "pause_id": pause_id,
            "outcome": ApprovalOutcome.APPROVED.value,
            "authority_ref": names["authority_ref"],
            "evidence_ref": evidence_ref,
            "decided_at": _iso(moment),
        },
        "exact_tool_arguments": {**arguments, "requested_at": _iso(moment)},
    }
    envelope = {
        "format": names["format"],
        "evidence_ref": evidence_ref,
        "command_id": command_id,
        "request_id": request_id,
        "local_policy_ref": names["policy_ref"],
        "expires_at": _iso(expires_at),
        "source_approval": read_approval,
        "revision": {
            "sheet_name": validated_sheet,
            "edits": validated_edits,
            "result_path_relative": derived,
            "write_action_id": write_action_id,
            "write_requested_at": _iso(moment),
        },
    }

    material = {
        "request_id": request_id,
        "run_id": approval.run_id,
        "device_id": approval.device_id,
        "root_ref": root_ref,
        "argv": argv,
        "cwd_relative": ".",
        "requested_at": _iso(moment),
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": envelope,
    }
    if set(material) != set(_MATERIAL_KEYS):
        raise XlsxRevisionMaterialError("command material keys drifted from the broker contract")

    enqueue = {
        "command_id": command_id,
        "binding_ref": approval.binding_ref,
        "run_id": approval.run_id,
        "tool_request_ref": tool_request_ref,
        # The same fingerprint the Resident recomputes from the material it
        # fetches; the Broker refuses a command whose material differs.
        "request_fingerprint": command_material_fingerprint_for(
            request_id=request_id, run_id=approval.run_id,
            device_id=approval.device_id, root_ref=root_ref, argv=argv,
            cwd_relative=".", requested_at=moment, timeout_seconds=30,
        ),
        "ttl_seconds": 300,
    }
    return {
        "envelope": envelope,
        "material": material,
        "enqueue": enqueue,
        "preview": {
            "sheet_name": validated_sheet,
            "edits": validated_edits,
            "result_path_relative": derived,
            "expires_at": _iso(expires_at),
        },
    }


def preview_digest(*, owner_id: str, run_id: str, device_id: str, root_ref: str,
                   path_relative: str, sheet_name: str,
                   edits: list[dict[str, Any]]) -> str:
    """Bind a preview to one owner, one run, one intent. Not an approval."""

    from hashlib import sha256
    from json import dumps

    payload = {
        "owner_id": owner_id, "run_id": run_id, "device_id": device_id,
        "root_ref": root_ref, "path_relative": path_relative,
        "sheet_name": sheet_name, "edits": edits,
    }
    return sha256(dumps(payload, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise XlsxRevisionMaterialError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "APPROVAL_WINDOW", "MAX_EDITS_PER_REVISION", "PREVIEW_WINDOW",
    "XlsxRevisionMaterialError", "derived_result_path", "mint_xlsx_revision_envelope",
    "normalize_revision_edits", "normalize_revision_path", "preview_digest",
]
