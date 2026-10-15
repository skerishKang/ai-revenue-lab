"""#3580: authorized local XLSX bytes -> PDF -> canonical output/Drive material.

This is a trusted local-host *composition seam*, not an execution entrypoint.
#3650 owns the authenticated Desktop/Broker/Claw invocation; #2010 owns WRITE
authority; the renderer port is injected only by a trusted host after P01.
No local paths, raw file data, or provider secrets enter public projections.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Protocol

from .artifact_lineage import ArtifactLineage, LineageArtifactRef, declare_lineage
from .artifact_registration import (
    CanonicalArtifactRecord, MAX_ARTIFACT_SIZE_BYTES, register_canonical_artifact,
)
from .contracts import ContractError
from .google_drive_artifact_upload import DriveArtifactMaterial
from .local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from .xlsx_fidelity_route import XlsxRoute, classify_xlsx

PDF_MIME = "application/pdf"
PRODUCTION_OFFICE_RENDERER_COMPOSED = False
PRODUCTION_DRIVE_WRITE_AUTHORIZED = False


class TrustedLocalOfficePdfRenderer(Protocol):
    """Implemented ONLY inside an already-approved local execution host."""

    def render_xlsx_pdf(self, source_bytes: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class LocalXlsxPdfOutput:
    """A single canonical output record + original-preserving lineage + bytes."""

    source_record: CanonicalArtifactRecord
    record: CanonicalArtifactRecord
    lineage: ArtifactLineage
    content: bytes

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
            or self.lineage.source.artifact_id != self.source_record.artifact_id
            or self.lineage.source.integrity_ref != self.source_record.integrity_ref
            or len(self.content) != self.record.size_bytes
            or hashlib.sha256(self.content).hexdigest() != self.record.integrity_ref
        ):
            return None
        return DriveArtifactMaterial(self.record, self.content)

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-local-xlsx-pdf-output.v1",
            "source_artifact_id": self.source_record.artifact_id,
            "output": self.record.public_projection(),
            "lineage": self.lineage.public_projection(),
            "raw_local_path": False,
            "raw_pdf_bytes": False,
            "office_renderer_production_wired": False,
            "drive_write_authorized": False,
        }


def render_local_xlsx_pdf_output(
    *, source: LocalXlsxArtifactHandoff,
    renderer: TrustedLocalOfficePdfRenderer,
    workspace_ref: str, run_ref: str,
    artifact_id: str, lineage_id: str, now: datetime,
) -> LocalXlsxPdfOutput:
    """Create one PDF from a P01-read source without modifying the XLSX.

    A trusted caller must have independently authorized the renderer side effect.
    This seam does not elevate a simulated grant into a real P01 decision.
    Any corrupt/mismatched source refuses BEFORE invoking the Office renderer.
    """
    if not isinstance(source, LocalXlsxArtifactHandoff):
        raise ContractError("canonical locally captured XLSX required")
    if not callable(getattr(renderer, "render_xlsx_pdf", None)):
        raise ContractError("trusted Office renderer required")

    record, data = source.record, source.content
    if (
        record.artifact_kind != "source.xlsx"
        or record.media_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or not record.filename.lower().endswith(".xlsx")
        or record.workspace_ref != workspace_ref
        or record.run_ref != run_ref
        or not isinstance(data, bytes)
        or len(data) != record.size_bytes
        or hashlib.sha256(data).hexdigest() != record.integrity_ref
    ):
        raise ContractError("local source scope or original integrity mismatch")

    decision = classify_xlsx(data, local_only=True)
    if (
        decision != source.route
        or decision.route is XlsxRoute.REJECT
        or decision.execution_target != "padiem_desktop_local_runner"
    ):
        raise ContractError("source XLSX routing cannot be trusted")

    # Simple XLSX is a Google candidate, not auto-convertible. An explicit
    # trusted Office renderer can still preserve Excel-only layout.
    pdf = renderer.render_xlsx_pdf(data)
    if (
        type(pdf) is not bytes
        or not 0 < len(pdf) <= MAX_ARTIFACT_SIZE_BYTES
        or not pdf.startswith(b"%PDF-")
        or b"%%EOF" not in pdf[-1024:]
    ):
        raise ContractError("Office renderer produced invalid or oversized PDF")

    output = register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind="output.pdf",
        filename=record.filename[:-5] + ".pdf",
        media_type=PDF_MIME,
        size_bytes=len(pdf),
        integrity_ref=hashlib.sha256(pdf).hexdigest(),
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        source_ref="artifact/" + record.artifact_id,
    )
    lineage = declare_lineage(
        lineage_id=lineage_id, source=record, outputs=(output,),
        transformation_kind="xlsx.office_pdf",
        workspace_ref=workspace_ref, run_ref=run_ref, created_at=now,
    )
    return LocalXlsxPdfOutput(record, output, lineage, pdf)
