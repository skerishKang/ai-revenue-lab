"""#4139: mint the actual TXT approval material for one registered-PC read.

The owner's authenticated Claw request names an exact ``.txt`` file under an
explicit ``root_ref``. This module turns that first-party approval act into
canonical Engine approval objects (pause + verified decision, USER_CONFIRMATION
over the exact ``local.filesystem.read`` invocation) and a closed receipt
envelope that travels inside the Broker command material's
``padiem_ai_core.agent_approval`` is authoritative for the Engine approval
model; the invocation digest is computed with its shared implementation, never
a copy. The two remaining projections below are exact ports of the
Resident-side canonical algorithms
(``kagent.windows_local_filesystem.file_request_fingerprint`` and the
``windows_file_tool_invocation`` argument map). A pinned cross-implementation
test keeps them bit-identical; the Resident recomputes both digests and
refuses any mismatch, so drift can never become a grant.

The receipt is bound to one command: ``command_id``/``run_id``/``device_id``
are minted here and must be used for the atomic
``enqueue_command_with_material`` call that carries this material. The companion
argv execution (``["python", "-V"]``) is a correlation vehicle only: it must
exit 0 for the lane to proceed, but its stdout is never trusted as TXT content
(the lane reads the approved file itself). It requires a ``python`` executable
under one of the PC's allowlisted executable profiles.

Bilateral constants (must match the Resident factory and the Broker validator
verbatim; pinned by contract tests, never renamed silently):

- ``TXT_READ_RECEIPT_FORMAT`` — the closed envelope discriminator.
- ``TXT_READ_APPROVAL_AUTHORITY_REF`` — who minted this approval act.
- ``TXT_READ_LOCAL_POLICY_REF`` — the local policy that re-checks at READ time.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import PureWindowsPath
from typing import Any
from uuid import uuid4

TXT_READ_RECEIPT_FORMAT = "claw-txt-read-approval.v1"
TXT_READ_APPROVAL_AUTHORITY_REF = "claw_connector_txt_request_v1"
TXT_READ_LOCAL_POLICY_REF = "padiem_txt_selected_root_read_policy_v1"
TXT_READ_TOOL_ID = "local.filesystem.read"
TXT_READ_APPROVAL_SCOPE = ("filesystem.read",)
TXT_READ_AGENT_RUNTIME_ID = "claw_connector_txt_v1"
TXT_READ_SUFFIX = ".txt"
TXT_READ_VEHICULAR_ARGV: tuple[str, ...] = ("python", "-V")

_APPROVAL_WINDOW = timedelta(minutes=5)
_MAX_REF_CHARS = 512
_MAX_ID_CHARS = 128
_MAX_RELATIVE_PATH_CHARS = 1024
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_EXACT_ARG_KEYS = frozenset({
    "action_id", "run_id", "device_id", "root_ref",
    "operation", "path_relative", "requested_at", "request_fingerprint",
    "content_bytes", "content_sha256", "directory_enumeration",
    "recursive_delete", "admin_elevation",
})


class TxtApprovalMaterialError(ValueError):
    """The owner request cannot become canonical TXT approval material."""


def _ref(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_REF_CHARS
        or any(character.isspace() for character in value)
    ):
        raise TxtApprovalMaterialError(f"{field_name} must be a bounded safe reference")
    return value


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise TxtApprovalMaterialError(f"{field_name} must be a bounded safe identifier")
    return value


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TxtApprovalMaterialError(f"{field_name} must be timezone-aware")
    return value


def normalize_txt_relative_path(value: Any) -> str:
    """Exact port of the Resident-side relative Windows path rule.

    Pinned bit-identical by cross-implementation tests; the Resident
    re-normalizes and refuses any divergence.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_RELATIVE_PATH_CHARS:
        raise TxtApprovalMaterialError("path_relative must be a bounded relative Windows file path")
    raw = value.strip().replace("/", "\\")
    path = PureWindowsPath(raw)
    if path.is_absolute() or path.drive:
        raise TxtApprovalMaterialError("path_relative must remain inside the selected root")
    if any(part == ".." for part in path.parts):
        raise TxtApprovalMaterialError("path_relative traversal is not allowed")
    normalized_parts = tuple(part for part in path.parts if part not in {".", ""})
    if not normalized_parts:
        raise TxtApprovalMaterialError("path_relative must name a file")
    normalized = PureWindowsPath(*normalized_parts)
    if normalized.name in {"", ".", ".."}:
        raise TxtApprovalMaterialError("path_relative must name a file")
    return str(normalized)


def file_request_fingerprint_for(
    *,
    action_id: str,
    run_id: str,
    device_id: str,
    root_ref: str,
    path_relative: str,
    requested_at: datetime,
) -> str:
    """Exact port of the Resident-side file request fingerprint.

    ``requested_at`` must carry +00:00 (``datetime.isoformat()`` raw form);
    the wire may render the Z form, but the digest input is the raw form.
    """
    payload = {
        "action_id": action_id,
        "run_id": run_id,
        "device_id": device_id,
        "root_ref": root_ref,
        "operation": "read",
        "path_relative": path_relative,
        "requested_at": requested_at.isoformat(),
        "content_bytes": 0,
        "content_sha256": None,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_tool_invocation_arguments(
    *,
    action_id: str,
    run_id: str,
    device_id: str,
    root_ref: str,
    path_relative: str,
    requested_at: datetime,
    request_fingerprint: str,
) -> dict[str, Any]:
    """Exact port of the Resident-side file tool invocation argument map."""
    return {
        "action_id": action_id,
        "run_id": run_id,
        "device_id": device_id,
        "root_ref": root_ref,
        "operation": "read",
        "path_relative": path_relative,
        "requested_at": requested_at.isoformat(),
        "request_fingerprint": request_fingerprint,
        "content_bytes": 0,
        "content_sha256": None,
        "directory_enumeration": False,
        "recursive_delete": False,
        "admin_elevation": False,
    }


def _mint_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


def mint_txt_read_receipt(
    *,
    owner_id: str,
    workspace_id: str,
    device_id: str,
    binding_ref: str,
    root_ref: str,
    path_relative: str,
    command_id: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    action_id: str | None = None,
    tool_request_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mint the closed TXT approval receipt for one owner-named read.

    The caller must be the authenticated owner session path: ``owner_id`` /
    ``workspace_id`` / ``device_id`` / ``binding_ref`` come from the verified
    session + enrollment binding, never from browser-supplied authority. The
    returned envelope is JSON-safe and fits the Broker material wire bound.
    It authorizes exactly one command; reuse across commands is refused by
    correlation checks on the Resident.
    """
    _ref(owner_id, "owner_id")
    _ref(workspace_id, "workspace_id")
    _ref(device_id, "device_id")
    _ref(binding_ref, "binding_ref")
    _ref(root_ref, "root_ref")
    moment = _aware(now if now is not None else datetime.now(timezone.utc), "now").replace(microsecond=0)
    if moment.tzinfo is not timezone.utc:
        moment = moment.astimezone(timezone.utc)
    normalized_path = normalize_txt_relative_path(path_relative)
    if not normalized_path.lower().endswith(TXT_READ_SUFFIX):
        raise TxtApprovalMaterialError("only exact TXT selected file can be read")
    command_id = _identifier(command_id or _mint_id("txtcmd"), "command_id")
    run_id = _identifier(run_id or _mint_id("txtrun"), "run_id")
    request_id = _ref(request_id or _mint_id("txtreq"), "request_id")
    action_id = _ref(action_id or _mint_id("txtact"), "action_id")
    tool_request_ref = _ref(tool_request_ref or _mint_id("txttool"), "tool_request_ref")

    fingerprint = file_request_fingerprint_for(
        action_id=action_id, run_id=run_id, device_id=device_id,
        root_ref=root_ref, path_relative=normalized_path, requested_at=moment,
    )
    arguments = file_tool_invocation_arguments(
        action_id=action_id, run_id=run_id, device_id=device_id,
        root_ref=root_ref, path_relative=normalized_path, requested_at=moment,
        request_fingerprint=fingerprint,
    )
    if set(arguments) != _EXACT_ARG_KEYS:
        raise TxtApprovalMaterialError("TXT invocation argument map drift")

    from padiem_ai_core.agent_approval import (
        ApprovalOutcome,
        ApprovalRequirement,
        tool_invocation_digest,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation

    invocation = ToolInvocation(tool_id=TXT_READ_TOOL_ID, arguments=dict(arguments))
    invocation_sha256 = tool_invocation_digest(invocation)

    created_at = moment
    expires_at = moment + _APPROVAL_WINDOW
    pause_id = _identifier(_mint_id("txtpause"), "pause_id")
    decision_id = _identifier(_mint_id("txtdecision"), "decision_id")
    evidence_ref = _ref(_mint_id("txtevidence"), "evidence_ref")
    pause = {
        "pause_id": pause_id,
        "run_id": run_id,
        "agent_runtime_id": TXT_READ_AGENT_RUNTIME_ID,
        "tool_id": TXT_READ_TOOL_ID,
        "invocation_sha256": invocation_sha256,
        "requirement": ApprovalRequirement.USER_CONFIRMATION.value,
        "step_index": 1,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "approval_scope": list(TXT_READ_APPROVAL_SCOPE),
    }
    decision = {
        "decision_id": decision_id,
        "pause_id": pause_id,
        "outcome": ApprovalOutcome.APPROVED.value,
        "authority_ref": TXT_READ_APPROVAL_AUTHORITY_REF,
        "evidence_ref": evidence_ref,
        "decided_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    exact_args = dict(arguments)
    exact_args["requested_at"] = moment.isoformat().replace("+00:00", "Z")
    receipt = {
        "format": TXT_READ_RECEIPT_FORMAT,
        "evidence_ref": evidence_ref,
        "command_id": command_id,
        "request_id": request_id,
        "approval_pause": pause,
        "approval_decision": decision,
        "exact_tool_arguments": exact_args,
        "local_policy_ref": TXT_READ_LOCAL_POLICY_REF,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }
    material = {
        "request_id": request_id,
        "run_id": run_id,
        "device_id": device_id,
        "root_ref": root_ref,
        "argv": list(TXT_READ_VEHICULAR_ARGV),
        "cwd_relative": ".",
        "requested_at": moment.isoformat().replace("+00:00", "Z"),
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": receipt,
    }
    enqueue = {
        "command_id": command_id,
        "binding_ref": binding_ref,
        "run_id": run_id,
        "tool_request_ref": tool_request_ref,
        "request_fingerprint": command_material_fingerprint_for(
            request_id=request_id, run_id=run_id, device_id=device_id,
            root_ref=root_ref, argv=list(TXT_READ_VEHICULAR_ARGV),
            cwd_relative=".", requested_at=moment, timeout_seconds=30,
        ),
        "ttl_seconds": 300,
    }
    return {
        "receipt": receipt,
        "material": material,
        "enqueue": enqueue,
        "owner_id": owner_id,
        "workspace_id": workspace_id,
        "action_id": action_id,
        "tool_request_ref": tool_request_ref,
        "request_fingerprint": fingerprint,
    }


def command_material_fingerprint_for(
    *,
    request_id: str,
    run_id: str,
    device_id: str,
    root_ref: str,
    argv: list[str],
    cwd_relative: str,
    requested_at: datetime,
    timeout_seconds: int,
) -> str:
    """Exact port of the Resident-side command material fingerprint."""
    payload = {
        "request_id": request_id,
        "run_id": run_id,
        "device_id": device_id,
        "root_ref": root_ref,
        "argv": list(argv),
        "cwd_relative": cwd_relative,
        "requested_at": requested_at.isoformat(),
        "timeout_seconds": timeout_seconds,
        "shell": False,
        "admin_elevation": False,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
