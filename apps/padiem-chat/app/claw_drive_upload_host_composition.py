"""#3580 host injection boundary for the Claw Drive WRITE uploader.

``create_app`` has always accepted ``claw_drive_artifact_uploader`` and defaulted
it to ``None``, and the deployed Worker never passed anything else. That is the
correct fail-closed state, but it was implicit: no single place said *which*
trusted inputs a host must supply, so a future host could inject a look-alike or
a READ-only grant by accident.

This module is that place. It is a boundary, not an authority:

```text
WHAT THIS FILE IS
  One fail-closed builder that assembles the canonical uploader from the
  already-composed Drive WRITE port plus the host's trusted binding, scope,
  artifact-material, folder-proof and approval ports.

WHAT IT IS NOT
  Not a grant, not an approval schema, not a Drive transport and not a second
  upload adapter. Every authority decision still belongs to
  ``GoogleDriveArtifactUploadAdapter``, which re-checks the binding, the scope,
  the folder proof, the exact artifact bytes, the WRITE approval and replay on
  every single call. This boundary only refuses to build an uploader when an
  input is missing or when the supplied grant is not a WRITE grant.
```

The READ-only case is the load-bearing one: #2010 keeps Google Drive at
``drive.readonly``, and a READ grant must never be reinterpreted as WRITE
authority. ``drive_write_grant_present`` states that rule once, and the builder
refuses to construct anything from a binding that fails it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kagent.connector_trust import ConnectorBindingProjection
from kagent.google_drive_artifact_upload import (
    DRIVE_UPLOAD_CAPABILITY, DRIVE_WRITE_SCOPES, GoogleDriveArtifactUploadAdapter,
)
from kagent.google_drive_scope import DriveScopeProjection
from kagent.google_drive_upload_composition import GoogleDriveUploadComposition

#: Static contract markers for this boundary.
HOST_INJECTION_BOUNDARY_IMPLEMENTED = True
PRODUCTION_DRIVE_UPLOADER_INJECTED = False
NEW_DRIVE_AUTHORITY = False
NEW_APPROVAL_AUTHORITY = False
SECOND_UPLOAD_ADAPTER = False
READ_SCOPE_IS_NOT_WRITE = True

#: The host ports the canonical upload adapter requires, and the exact method
#: each one must expose. Checked structurally so a look-alike cannot slip in.
_REQUIRED_HOST_PORTS = (
    ("artifacts", "resolve_artifact_material"),
    ("folders", "resolve_folder_proof"),
    ("approval", "verify_write_approval"),
)


class ClawDriveUploadHostError(ValueError):
    """Boundary error; never carries a credential, folder id or provider body."""


@dataclass(frozen=True, slots=True)
class ClawDriveUploadHostState:
    """The boundary's outcome. ``uploader is None`` is the fail-closed answer."""

    uploader: GoogleDriveArtifactUploadAdapter | None
    blocked_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.uploader is not None and not isinstance(
            self.uploader, GoogleDriveArtifactUploadAdapter
        ):
            raise ClawDriveUploadHostError(
                "the boundary yields the canonical upload adapter only"
            )
        if self.uploader is not None and self.blocked_reasons:
            raise ClawDriveUploadHostError(
                "an injected uploader cannot also report a blocking reason"
            )

    @property
    def injected(self) -> bool:
        return self.uploader is not None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-drive-upload-host-boundary.v1",
            "boundary_implemented": HOST_INJECTION_BOUNDARY_IMPLEMENTED,
            "uploader_injected": self.injected,
            "production_drive_uploader_injected": PRODUCTION_DRIVE_UPLOADER_INJECTED,
            "new_drive_authority": NEW_DRIVE_AUTHORITY,
            "new_approval_authority": NEW_APPROVAL_AUTHORITY,
            "second_upload_adapter": SECOND_UPLOAD_ADAPTER,
            "read_scope_is_not_write": READ_SCOPE_IS_NOT_WRITE,
            "blocked_reasons": list(self.blocked_reasons),
            "production_claim": False,
        }


def _carries_drive_write_authority(binding: ConnectorBindingProjection) -> bool:
    """Scope/capability half of the WRITE-grant rule, without a clock."""
    return (
        binding.connector_id == "google-drive"
        and bool(DRIVE_WRITE_SCOPES.intersection(binding.granted_scopes))
        and DRIVE_UPLOAD_CAPABILITY in binding.granted_capabilities
    )


def drive_write_grant_present(
    binding: ConnectorBindingProjection | None, *, now: datetime,
) -> bool:
    """True only for a *live* binding that really carries Drive WRITE authority.

    An existing READ-only grant (#2010) is not a WRITE grant, and neither is a
    revoked or expired one. Time-dependent revocation stays with the upload
    adapter, which re-checks ``usable_at`` on every call; this helper is the
    single statement of the rule for callers that hold a clock.
    """
    if not isinstance(binding, ConnectorBindingProjection):
        return False
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return False
    return _carries_drive_write_authority(binding) and binding.usable_at(now)


def build_claw_drive_upload_host_state(
    *,
    binding: ConnectorBindingProjection | None = None,
    scope: DriveScopeProjection | None = None,
    artifacts: Any = None,
    folders: Any = None,
    approval: Any = None,
    composition: GoogleDriveUploadComposition | None = None,
) -> ClawDriveUploadHostState:
    """Assemble the canonical uploader, or explain exactly what is missing.

    Every input must come from the trusted host. Nothing here reads an
    environment variable, a request body, a model answer or a browser cookie,
    and nothing mints a grant, an approval or a credential.
    """
    reasons: list[str] = []

    if not isinstance(binding, ConnectorBindingProjection):
        reasons.append("no trusted Control Plane connector binding was supplied")
    elif not _carries_drive_write_authority(binding):
        reasons.append(
            "the supplied binding carries no Google Drive WRITE authority "
            "(#2010 is READ-only); a READ grant is not a WRITE grant"
        )

    if not isinstance(scope, DriveScopeProjection):
        reasons.append("no trusted Drive scope was supplied")
    elif (
        isinstance(binding, ConnectorBindingProjection)
        and scope.binding_ref != binding.binding_ref
    ):
        reasons.append("the Drive scope does not belong to the trusted binding")

    supplied = {"artifacts": artifacts, "folders": folders, "approval": approval}
    for name, method in _REQUIRED_HOST_PORTS:
        if not callable(getattr(supplied[name], method, None)):
            reasons.append(f"no trusted Drive {name} port was supplied")

    if not isinstance(composition, GoogleDriveUploadComposition):
        reasons.append("no composed Google Drive WRITE port was supplied")

    if reasons:
        return ClawDriveUploadHostState(uploader=None, blocked_reasons=tuple(reasons))

    return ClawDriveUploadHostState(
        uploader=composition.uploader(
            binding=binding, scope=scope, artifacts=artifacts,
            folders=folders, approval=approval,
        ),
        blocked_reasons=(),
    )


def build_claw_drive_artifact_uploader(
    **kwargs: Any,
) -> GoogleDriveArtifactUploadAdapter | None:
    """The single value ``create_app(claw_drive_artifact_uploader=...)`` accepts."""
    return build_claw_drive_upload_host_state(**kwargs).uploader


__all__ = [
    "ClawDriveUploadHostError",
    "ClawDriveUploadHostState",
    "HOST_INJECTION_BOUNDARY_IMPLEMENTED",
    "PRODUCTION_DRIVE_UPLOADER_INJECTED",
    "READ_SCOPE_IS_NOT_WRITE",
    "build_claw_drive_artifact_uploader",
    "build_claw_drive_upload_host_state",
    "drive_write_grant_present",
]
