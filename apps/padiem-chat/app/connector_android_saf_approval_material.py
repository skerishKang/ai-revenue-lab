"""#5080 — mint approval material for one Android SAF TXT read.

The Android app is a device on the canonical Broker, exactly like the Windows
Resident. This module adds the one lane-specific constructor the phone needs:
an owner-confirmed read of a single ``.txt`` document inside a SAF folder the
phone itself declared through ``/android-profile``.

It reuses the Windows lane's canonical pieces instead of duplicating them:

* the same Engine shared-library approval object model
  (``padiem_ai_core.agent_approval``);
* the same command-material fingerprint implementation
  (``connector_txt_approval_material.command_material_fingerprint_for``), so
  the Broker sees one algorithm for the command it enqueues;
* the same atomic ``enqueue_command_with_material`` path, the same
  device-authenticated ``/text-result`` producer, and the same return leg that
  appends the verified text to the originating conversation.

What differs is only the execution intent: there is no executable, argv or
Windows path. The material carries an empty argv and a closed receipt whose
discriminator is ``claw-android-saf-txt-read-approval.v1``. The phone must
never interpret ``argv`` for this lane; it locates ``path_relative`` under the
declared ``root_ref`` document tree and reads it through SAF.

The receipt binds the exact read for the phone to verify:

```text
format · command_id · request_id · evidence_ref
approval_pause / approval_decision (Engine object model)
exact_tool_arguments{ action_id, run_id, device_id, root_ref, operation,
                      path_relative, requested_at, request_fingerprint,
                      content_bytes=0, content_sha256=null,
                      directory_enumeration=false, recursive_delete=false,
                      admin_elevation=false }
local_policy_ref · expires_at
```

``request_fingerprint`` is the SAF read digest defined below. It is a
deterministic SHA-256 over the sorted canonical JSON of the exact intent, so
the phone can recompute it from the values it received. The server never
accepts a path outside the declared root, a non-TXT file, a traversal segment,
a URI, or a folder the phone did not declare.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata
from typing import Any
from uuid import uuid4

from .connector_txt_approval_material import command_material_fingerprint_for

ANDROID_TXT_RECEIPT_FORMAT = "claw-android-saf-txt-read-approval.v1"
ANDROID_TXT_APPROVAL_AUTHORITY_REF = "claw_connector_android_txt_request_v1"
ANDROID_TXT_LOCAL_POLICY_REF = "padiem_android_saf_selected_root_read_policy_v1"
ANDROID_TXT_AGENT_RUNTIME_ID = "claw_android_saf_txt_v1"
ANDROID_TXT_PROFILE_REF = "profile.android.saf-txt.v1"
ANDROID_TXT_TOOL_ID = "local.filesystem.read"
ANDROID_TXT_APPROVAL_SCOPE = ("filesystem.read",)
ANDROID_TXT_READ_SUFFIX = ".txt"
ANDROID_SAF_READ_VERSION = 1

_APPROVAL_WINDOW = timedelta(minutes=5)
_MAX_REF_CHARS = 512
_MAX_ID_CHARS = 128
_MAX_RELATIVE_PATH_CHARS = 1024
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_EXACT_ARG_KEYS = frozenset({
    "action_id", "run_id", "device_id", "root_ref",
    "operation", "path_relative", "requested_at", "request_fingerprint",
    "content_bytes", "content_sha256", "directory_enumeration",
    "recursive_delete", "admin_elevation",
})


class AndroidTxtApprovalMaterialError(ValueError):
    """The owner request cannot become canonical Android TXT material."""


def _ref(value: Any, field_name: str) -> str:
    if type(value) is not str or not value or len(value) > _MAX_REF_CHARS or any(
        character.isspace() for character in value
    ):
        raise AndroidTxtApprovalMaterialError(
            f"{field_name} must be a bounded safe reference"
        )
    return value


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AndroidTxtApprovalMaterialError(
            f"{field_name} must be a bounded safe identifier"
        )
    return value


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AndroidTxtApprovalMaterialError(f"{field_name} must be timezone-aware")
    return value


def normalize_saf_relative_path(value: Any) -> str:
    """Normalize one relative document path under the declared SAF root.

    SAF exposes a document tree, not a filesystem. The value is a relative
    display path (segments joined by ``/``), NFC-normalized, with no absolute
    prefix, drive letter, URI scheme, traversal segment, control character or
    empty segment, and it must name an exact ``.txt`` document.
    """
    if type(value) is not str or not 1 <= len(value) <= _MAX_RELATIVE_PATH_CHARS:
        raise AndroidTxtApprovalMaterialError("path_relative must be a bounded relative path")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value or normalized.strip() != value:
        raise AndroidTxtApprovalMaterialError("path_relative must be NFC-normalized without surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise AndroidTxtApprovalMaterialError("path_relative must not carry a control character")
    if "://" in normalized or normalized.lower().startswith("content:"):
        raise AndroidTxtApprovalMaterialError("path_relative must not be a URI")
    parts = normalized.replace("\\", "/").split("/")
    if (
        normalized.startswith(("/", "\\"))
        or (len(normalized) >= 2 and normalized[1] == ":")
        or ":" in parts[0]
        or any(part in ("", ".", "..") for part in parts)
        or not normalized.lower().endswith(ANDROID_TXT_READ_SUFFIX)
    ):
        raise AndroidTxtApprovalMaterialError(
            "path_relative must name a TXT document inside the selected SAF root"
        )
    return normalized


def saf_read_fingerprint(
    *,
    action_id: str,
    run_id: str,
    device_id: str,
    root_ref: str,
    path_relative: str,
    requested_at: str,
) -> str:
    """The one deterministic digest the phone recomputes before it reads.

    Canonical JSON: UTF-8, keys sorted, no insignificant whitespace, the
    server-normalized NFC path. Pinned by a test vector in the contract doc.
    """
    payload = {
        "v": ANDROID_SAF_READ_VERSION,
        "action_id": action_id,
        "run_id": run_id,
        "device_id": device_id,
        "root_ref": root_ref,
        "operation": "read",
        "path_relative": path_relative,
        "requested_at": requested_at,
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mint_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


@dataclass(frozen=True, slots=True)
class AndroidOwnerTxtApprovalProof:
    """Server-authority attestation that the owner selected this phone folder.

    Built only by the authenticated trigger from the verified B54 session,
    memory workspace, Identity consent, canonical Broker binding AND the SAF
    folder set the phone itself declared. The browser cannot add a folder:
    ``root_ref`` must be one of ``allowed_root_refs`` from the Broker profile.
    """

    owner_id: str
    workspace_id: str
    device_id: str
    binding_ref: str
    credential_generation: int
    consent_id: str
    run_id: str
    profile_ref: str
    root_ref: str
    allowed_root_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("owner_id", "workspace_id", "device_id", "binding_ref", "consent_id"):
            _ref(getattr(self, field_name), f"approval proof {field_name}")
        if (
            isinstance(self.credential_generation, bool)
            or not isinstance(self.credential_generation, int)
            or self.credential_generation < 1
        ):
            raise AndroidTxtApprovalMaterialError("approval proof credential_generation invalid")
        _identifier(self.run_id, "approval proof run_id")
        if self.profile_ref != ANDROID_TXT_PROFILE_REF:
            raise AndroidTxtApprovalMaterialError("approval proof profile_ref unsupported")
        if not isinstance(self.allowed_root_refs, tuple) or not self.allowed_root_refs:
            raise AndroidTxtApprovalMaterialError("approval proof requires declared SAF roots")
        for root in self.allowed_root_refs:
            if not isinstance(root, str) or not _SAFE_REF_RE.fullmatch(root):
                raise AndroidTxtApprovalMaterialError("approval proof SAF root invalid")
        if self.root_ref not in self.allowed_root_refs:
            raise AndroidTxtApprovalMaterialError(
                "requested SAF folder was not declared by this phone"
            )


def mint_android_txt_read_receipt(
    *,
    approval: AndroidOwnerTxtApprovalProof,
    path_relative: str,
    command_id: str | None = None,
    request_id: str | None = None,
    action_id: str | None = None,
    tool_request_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mint the closed Android SAF receipt and its Broker material.

    The returned ``enqueue`` object is used verbatim for the atomic
    ``enqueue_command_with_material`` call. ``material["argv"]`` is empty by
    contract: this lane never executes a process.
    """
    if not isinstance(approval, AndroidOwnerTxtApprovalProof):
        raise AndroidTxtApprovalMaterialError(
            "Android TXT approval requires a verified owner approval proof"
        )
    path = normalize_saf_relative_path(path_relative)
    moment = _aware(now if now is not None else datetime.now(timezone.utc), "now").replace(microsecond=0)
    if moment.tzinfo is not timezone.utc:
        moment = moment.astimezone(timezone.utc)
    command_id = _identifier(command_id or _mint_id("andcmd"), "command_id")
    request_id = _ref(request_id or _mint_id("andreq"), "request_id")
    action_id = _ref(action_id or _mint_id("andact"), "action_id")
    tool_request_ref = _ref(tool_request_ref or _mint_id("andtool"), "tool_request_ref")
    requested_at = moment.isoformat().replace("+00:00", "Z")
    fingerprint = saf_read_fingerprint(
        action_id=action_id,
        run_id=approval.run_id,
        device_id=approval.device_id,
        root_ref=approval.root_ref,
        path_relative=path,
        requested_at=requested_at,
    )

    from padiem_ai_core.agent_approval import (
        ApprovalOutcome,
        ApprovalRequirement,
    )

    created_at = moment
    expires_at = moment + _APPROVAL_WINDOW
    pause_id = _identifier(_mint_id("andpause"), "pause_id")
    decision_id = _identifier(_mint_id("anddecision"), "decision_id")
    evidence_ref = _ref(_mint_id("andevidence"), "evidence_ref")
    pause = {
        "pause_id": pause_id,
        "run_id": approval.run_id,
        "agent_runtime_id": ANDROID_TXT_AGENT_RUNTIME_ID,
        "tool_id": ANDROID_TXT_TOOL_ID,
        "invocation_sha256": fingerprint,
        "requirement": ApprovalRequirement.USER_CONFIRMATION.value,
        "step_index": 1,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "approval_scope": list(ANDROID_TXT_APPROVAL_SCOPE),
    }
    decision = {
        "decision_id": decision_id,
        "pause_id": pause_id,
        "outcome": ApprovalOutcome.APPROVED.value,
        "authority_ref": ANDROID_TXT_APPROVAL_AUTHORITY_REF,
        "evidence_ref": evidence_ref,
        "decided_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    exact_args = {
        "action_id": action_id,
        "run_id": approval.run_id,
        "device_id": approval.device_id,
        "root_ref": approval.root_ref,
        "operation": "read",
        "path_relative": path,
        "requested_at": requested_at,
        "request_fingerprint": fingerprint,
        "content_bytes": 0,
        "content_sha256": None,
        "directory_enumeration": False,
        "recursive_delete": False,
        "admin_elevation": False,
    }
    if frozenset(exact_args) != _EXACT_ARG_KEYS:
        raise AndroidTxtApprovalMaterialError("Android TXT argument map drift")
    receipt = {
        "format": ANDROID_TXT_RECEIPT_FORMAT,
        "evidence_ref": evidence_ref,
        "command_id": command_id,
        "request_id": request_id,
        "approval_pause": pause,
        "approval_decision": decision,
        "exact_tool_arguments": exact_args,
        "local_policy_ref": ANDROID_TXT_LOCAL_POLICY_REF,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }
    material = {
        "request_id": request_id,
        "run_id": approval.run_id,
        "device_id": approval.device_id,
        "root_ref": approval.root_ref,
        "argv": [],
        "cwd_relative": ".",
        "requested_at": requested_at,
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": receipt,
    }
    command_fingerprint = command_material_fingerprint_for(
        request_id=request_id,
        run_id=approval.run_id,
        device_id=approval.device_id,
        root_ref=approval.root_ref,
        argv=[],
        cwd_relative=".",
        requested_at=moment,
        timeout_seconds=30,
    )
    enqueue = {
        "command_id": command_id,
        "binding_ref": approval.binding_ref,
        "run_id": approval.run_id,
        "tool_request_ref": tool_request_ref,
        "request_fingerprint": command_fingerprint,
        "ttl_seconds": 300,
    }
    return {
        "receipt": receipt,
        "material": material,
        "enqueue": enqueue,
        "owner_id": approval.owner_id,
        "workspace_id": approval.workspace_id,
        "action_id": action_id,
        "tool_request_ref": tool_request_ref,
        "saf_read_fingerprint": fingerprint,
    }
