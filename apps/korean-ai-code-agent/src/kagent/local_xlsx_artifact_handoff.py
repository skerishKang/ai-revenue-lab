"""#3580: trusted local XLSX read -> immutable canonical material for Drive.

This seam does NOT authorize a Desktop session, Google WRITE, or channel SEND.
It reuses WindowsSelectedRootFileRuntime's selected-root/P01/local-permission
checks, and supplies only an exact-bound in-memory material port to the
existing GoogleDriveArtifactUploadAdapter. No local path enters an artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import PureWindowsPath

from .artifact_lineage import LineageArtifactRef
from .artifact_registration import CanonicalArtifactRecord, register_canonical_artifact
from .contracts import ContractError
from .google_drive_artifact_upload import DriveArtifactMaterial
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, LocalFileResult,
    WindowsSelectedRootFileRuntime,
)
from .xlsx_fidelity_route import XlsxRoute, XlsxRouteDecision, classify_xlsx


@dataclass(frozen=True, slots=True)
class LocalXlsxArtifactHandoff:
    """In-memory, exact-scope material port; never a second durable store."""

    record: CanonicalArtifactRecord
    content: bytes
    route: XlsxRouteDecision

    def resolve_artifact_material(
        self, artifact_ref: LineageArtifactRef, *,
        workspace_ref: str, run_ref: str,
    ) -> DriveArtifactMaterial | None:
        if (
            not isinstance(artifact_ref, LineageArtifactRef)
            or artifact_ref.artifact_id != self.record.artifact_id
            or artifact_ref.integrity_ref != self.record.integrity_ref
            or workspace_ref != self.record.workspace_ref
            or run_ref != self.record.run_ref
            or hashlib.sha256(self.content).hexdigest() != self.record.integrity_ref
        ):
            return None
        return DriveArtifactMaterial(self.record, self.content)

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-local-xlsx-artifact-handoff.v1",
            "artifact": self.record.public_projection(),
            "route": self.route.public_projection(),
            "raw_local_path": False,
            "raw_file_content": False,
            "drive_write_authorized": False,
            "desktop_runtime_delivery_verified": False,
        }


def capture_local_xlsx_for_handoff(
    *, runtime: WindowsSelectedRootFileRuntime,
    request: LocalFileRequest,
    now: datetime,
    workspace_ref: str,
    artifact_id: str,
) -> LocalXlsxArtifactHandoff:
    """Perform ONE authorized local read and prepare a verified source artifact.

    The caller must be the trusted local host, not a model or the Web frontend.
    A separate Control Plane-approved Drive adapter performs any subsequent
    network upload. The raw local path never becomes a remote file reference.
    """
    if not isinstance(runtime, WindowsSelectedRootFileRuntime):
        raise ContractError("trusted Windows selected-root file runtime required")
    if not isinstance(request, LocalFileRequest) or request.operation is not LocalFileOperation.READ:
        raise ContractError("local handoff requires an exact READ request")
    name = PureWindowsPath(request.path_relative).name
    if not name.lower().endswith(".xlsx"):
        raise ContractError("local handoff currently accepts XLSX source files only")

    result = runtime.perform(request, now=now)  # existing P01/grant + path boundary
    if not isinstance(result, LocalFileResult):
        raise ContractError("trusted local read produced no canonical result")
    if (
        result.operation is not LocalFileOperation.READ
        or result.action_id != request.action_id
        or result.run_id != request.run_id
        or result.device_id != request.device_id
        or result.root_ref != request.root_ref
        or result.path_relative != request.path_relative
        or not isinstance(result.content, bytes)
        or len(result.content) != result.bytes_count
        or hashlib.sha256(result.content).hexdigest() != result.content_sha256
    ):
        raise ContractError("local file result did not match the authorized read")

    decision = classify_xlsx(result.content, local_only=True)
    if decision.route is XlsxRoute.REJECT or decision.execution_target != "padiem_desktop_local_runner":
        raise ContractError("untrusted or unsupported local XLSX cannot be handed off")

    # Private path/device references are reduced to a one-way provenance token.
    source_digest = hashlib.sha256(
        "|".join((
            request.device_id, request.root_ref, request.path_relative,
            request.action_id, result.content_sha256,
        )).encode("utf-8")
    ).hexdigest()
    record = register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind="source.xlsx",
        filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=result.bytes_count,
        integrity_ref=result.content_sha256,
        workspace_ref=workspace_ref,
        run_ref=request.run_id,
        source_ref="local-read/" + source_digest,
    )
    return LocalXlsxArtifactHandoff(record, result.content, decision)


PRODUCTION_DESKTOP_MATERIAL_HANDOFF_WIRED = False
PRODUCTION_DRIVE_WRITE_AUTHORIZED_BY_THIS_MODULE = False
