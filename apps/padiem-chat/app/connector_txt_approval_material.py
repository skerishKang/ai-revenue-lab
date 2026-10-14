"""#4139: mint the actual TXT approval material for one registered-PC read.

The owner's authenticated Claw request names an exact ``.txt`` file under an
explicit ``root_ref``. This module turns that first-party approval act into
canonical Engine approval objects (pause + verified decision, USER_CONFIRMATION
over the exact ``local.filesystem.read`` invocation) and a closed receipt
envelope that travels inside the Broker command material's
``padiem_ai_core.agent_approval`` is authoritative for the Engine approval
model, and the file intent math (path normalization, file fingerprint, tool
invocation map) is imported from ``kagent.windows_local_filesystem`` itself —
the worker bundles that package, and those modules are pure stdlib plus
``padiem_ai_core``. No digest or normalization logic is copied: the Resident
recomputes both digests and refuses any mismatch, so drift can never become
a grant. The one remaining projection below
(``command_material_fingerprint_for``) mirrors
``kagent.windows_local_executor.command_request_fingerprint`` because that
module pulls a Windows-only job-object import the worker bundle cannot load;
a pinned cross-implementation test keeps it bit-identical.

The receipt is bound to one command: ``command_id``/``run_id``/``device_id``
are minted here and must be used for the atomic
``enqueue_command_with_material`` call that carries this material. The companion
argv execution (``["python", "-V"]``) is a correlation vehicle only: it must
exit 0 for the lane to proceed, but its stdout is never trusted as TXT content
(the lane reads the approved file itself). It requires a ``python`` executable
under one of the PC's allowlisted executable profiles.

Engine library vs Engine service: this module uses the Engine *shared library*
only (``padiem_ai_core.agent_approval`` object model, ``tool_runtime``
invocation + digests, plus kagent's own file-intent math). It makes NO Engine
service call (no continuation decide, no new Engine behavior or deploy): the
owner's explicit per-read confirmation described above is the approval act,
formalized here into canonical objects the Resident re-verifies.

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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from kagent.windows_local_filesystem import (
    LocalFileOperation,
    LocalFileRequest,
    file_request_fingerprint,
    windows_file_tool_invocation,
)

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
    """Normalize an owner-named path with the canonical Resident rule itself.

    Imported, never copied: the Resident re-normalizes on receipt and refuses
    any divergence, so issuance and Resident must agree bit-for-bit (pinned by
    cross-implementation tests). The TXT lane suffix is enforced separately by
    the minter, mirroring the plan source.
    """
    from kagent.windows_local_filesystem import _relative_file_path as resident_normalize

    try:
        return resident_normalize(value)
    except Exception as exc:
        raise TxtApprovalMaterialError("path_relative must be a bounded relative Windows file path") from exc


def _mint_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


@dataclass(frozen=True, slots=True)
class OwnerTxtApprovalProof:
    """The trigger's attestation that the owner approval act was verified.

    Constructed ONLY by the authenticated owner-session trigger from server
    authorities (verified B54 session, memory workspace, Broker enrollment
    binding, active Identity consent, stored conversation run) — never from
    browser-supplied authority. The minter re-validates every field and the
    cross-field coherence; a forged or partial proof fails closed here, and
    the Resident re-verifies the minted receipt independently.

    Realm note: ``workspace_id`` here is the Identity-verified *connector*
    workspace (the scope Broker calls use), NOT the Claw memory/tenant
    workspace. The two realms are never compared as strings: each is verified
    by its own authority, both anchored on the same verified session. The
    tenant-realm run-row check lives in the trigger, not in this proof.
    """

    owner_id: str
    workspace_id: str
    device_id: str
    binding_ref: str
    credential_generation: int
    consent_id: str
    run_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "owner_id", "workspace_id", "device_id", "binding_ref", "consent_id",
        ):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or not value
                or len(value) > _MAX_REF_CHARS
                or any(character.isspace() for character in value)
            ):
                raise TxtApprovalMaterialError(f"approval proof {field_name} invalid")
        if (
            isinstance(self.credential_generation, bool)
            or not isinstance(self.credential_generation, int)
            or self.credential_generation < 1
        ):
            raise TxtApprovalMaterialError("approval proof credential_generation invalid")
        _identifier(self.run_id, "approval proof run_id")


def mint_txt_read_receipt(
    *,
    approval: OwnerTxtApprovalProof,
    root_ref: str,
    path_relative: str,
    command_id: str | None = None,
    request_id: str | None = None,
    action_id: str | None = None,
    tool_request_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mint the closed TXT approval receipt for one owner-named read.

    ``approval`` must be the trigger-built proof above; ``run_id`` inside it
    must be the existing stored conversation run this read belongs to — never
    a detached mint. The returned envelope is JSON-safe and fits the Broker
    material wire bound. It authorizes exactly one command; reuse across
    commands is refused by correlation checks on the Resident.
    """
    if not isinstance(approval, OwnerTxtApprovalProof):
        raise TxtApprovalMaterialError("TXT approval requires a verified owner approval proof")
    owner_id = approval.owner_id
    workspace_id = approval.workspace_id
    device_id = approval.device_id
    binding_ref = approval.binding_ref
    run_id = approval.run_id
    _ref(root_ref, "root_ref")
    moment = _aware(now if now is not None else datetime.now(timezone.utc), "now").replace(microsecond=0)
    if moment.tzinfo is not timezone.utc:
        moment = moment.astimezone(timezone.utc)
    command_id = _identifier(command_id or _mint_id("txtcmd"), "command_id")
    request_id = _ref(request_id or _mint_id("txtreq"), "request_id")
    action_id = _ref(action_id or _mint_id("txtact"), "action_id")
    tool_request_ref = _ref(tool_request_ref or _mint_id("txttool"), "tool_request_ref")

    try:
        file_request = LocalFileRequest(
            action_id=action_id, run_id=run_id, device_id=device_id,
            root_ref=root_ref, operation=LocalFileOperation.READ,
            path_relative=path_relative, requested_at=moment,
        )
    except Exception as exc:
        raise TxtApprovalMaterialError("TXT file intent is not a canonical read") from exc
    if not file_request.path_relative.lower().endswith(TXT_READ_SUFFIX):
        raise TxtApprovalMaterialError("only exact TXT selected file can be read")
    fingerprint = file_request_fingerprint(file_request)
    invocation = windows_file_tool_invocation(file_request)
    arguments = invocation.arguments_copy()
    if set(arguments) != _EXACT_ARG_KEYS:
        raise TxtApprovalMaterialError("TXT invocation argument map drift")

    from padiem_ai_core.agent_approval import (
        ApprovalOutcome,
        ApprovalRequirement,
        tool_invocation_digest,
    )

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
