"""#3933: authorized Claw local XLSX revision -> PDF canonical output composition.

Trusted local-host seam only. No natural-language planner, model-controlled
filesystem, Google Drive WRITE, Telegram SEND, or production P01 activation.
A separate prior authorization must supply the exact source and reviewed edits.
An independent verifier must prove only the approved workbook edits were made
BEFORE any renderer or artifact is allowed to run. No source file is overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from typing import Protocol

from .artifact_lineage import ArtifactLineage, LineageArtifactRef, declare_lineage
from .artifact_registration import (
    CanonicalArtifactRecord, MAX_ARTIFACT_SIZE_BYTES, register_canonical_artifact,
)
from .contracts import ContractError
from .google_drive_artifact_upload import DriveArtifactMaterial
from .local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from .local_xlsx_pdf_output import TrustedLocalOfficePdfRenderer
from .xlsx_fidelity_route import XlsxRoute, classify_xlsx

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"
_CELL = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,5}$")
_SHEET_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_REVISIONS = 16

PRODUCTION_REVISION_HOST_COMPOSED = False
PRODUCTION_DRIVE_WRITE_AUTHORIZED = False


@dataclass(frozen=True, slots=True)
class ReviewedCellRevision:
    """One exact, owner-reviewed literal replacement, not arbitrary code.

    The host must resolve the sheet/cell from an already-authorized workbook,
    review the previous value and explicitly approve the replacement. Formula
    cells, extra edits and formula-like string injection are always excluded.
    """

    sheet_name: str
    cell: str
    previous_value: str | int
    replacement_value: str | int

    def __post_init__(self) -> None:
        if (not isinstance(self.sheet_name, str)
                or not 1 <= len(self.sheet_name) <= 31
                or self.sheet_name.strip() != self.sheet_name
                or _SHEET_CONTROL.search(self.sheet_name)
                or any(c in self.sheet_name for c in "[]:*?/\\")
                or not _CELL.fullmatch(self.cell)):
            raise ContractError("bounded sheet name and uppercase cell reference required")
        for value in (self.previous_value, self.replacement_value):
            if type(value) not in (str, int):
                raise ContractError("revision values must be literal text or integer")
            if type(value) is str and (
                not value or len(value) > 200 or _SHEET_CONTROL.search(value)
                or value[0] in "=+-@"
            ):
                raise ContractError("formula-like or unbounded text revision refused")
        if self.previous_value == self.replacement_value:
            raise ContractError("revision must actually change the expected cell")


class TrustedXlsxCopyEditor(Protocol):
    """An approved resident Office/OOXML host, never a model/browser hook."""

    def revise_xlsx_copy(
        self, source_bytes: bytes, edits: tuple[ReviewedCellRevision, ...]
    ) -> bytes: ...


class IndependentXlsxRevisionVerifier(Protocol):
    """Compare pre/post workbooks independently of the editor.

    Implementations must check exact requested changes, non-requested values,
    formulas, merged ranges, print settings, formatting and relevant assets,
    rejecting fidelity-sensitive inputs they cannot compare.
    """

    def verify_only_reviewed_edits(
        self, source_bytes: bytes, revised_bytes: bytes,
        edits: tuple[ReviewedCellRevision, ...]
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class LocalRevisedXlsxPdf:
    """Immutable source + changed XLSX + PDF with existing canonical lineage."""

    source: LocalXlsxArtifactHandoff
    revised: CanonicalArtifactRecord
    pdf: CanonicalArtifactRecord
    lineage: ArtifactLineage
    revised_bytes: bytes
    pdf_bytes: bytes

    def resolve_artifact_material(
        self, artifact_ref: LineageArtifactRef, *,
        workspace_ref: str, run_ref: str,
    ) -> DriveArtifactMaterial | None:
        if (not isinstance(artifact_ref, LineageArtifactRef)
                or workspace_ref != self.revised.workspace_ref
                or run_ref != self.revised.run_ref
                or self.source.record.integrity_ref != sha256(self.source.content).hexdigest()
                or self.source.record.workspace_ref != workspace_ref
                or self.source.record.run_ref != run_ref
                or self.pdf.workspace_ref != workspace_ref
                or self.pdf.run_ref != run_ref
                or self.lineage.workspace_ref != workspace_ref
                or self.lineage.run_ref != run_ref
                or self.lineage.source.artifact_id != self.source.record.artifact_id
                or self.lineage.source.integrity_ref != self.source.record.integrity_ref
                or self.lineage.working_artifact_id != self.revised.artifact_id
                or self.lineage.working_integrity_ref != self.revised.integrity_ref
                or self.lineage.output_artifact_ids != (self.pdf.artifact_id,)
                or self.lineage.output_integrity_refs != (self.pdf.integrity_ref,)):
            return None
        for record, data in (
            (self.revised, self.revised_bytes), (self.pdf, self.pdf_bytes)
        ):
            if (artifact_ref.artifact_id == record.artifact_id
                    and artifact_ref.integrity_ref == record.integrity_ref
                    and len(data) == record.size_bytes
                    and sha256(data).hexdigest() == record.integrity_ref):
                return DriveArtifactMaterial(record, data)
        return None

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-local-revised-xlsx-pdf.v1",
            "source_artifact_id": self.source.record.artifact_id,
            "revised": self.revised.public_projection(),
            "pdf": self.pdf.public_projection(),
            "lineage": self.lineage.public_projection(),
            "original_preserved": True,
            "independent_revision_validation": True,
            "pdf_fidelity_attested": False,
            "drive_write_authorized": False,
            "desktop_runtime_invocation_verified": False,
            "raw_document_bytes": False,
            "raw_local_path": False,
        }


def revise_and_render_local_xlsx_pdf(
    *, source: LocalXlsxArtifactHandoff,
    edits: tuple[ReviewedCellRevision, ...],
    editor: TrustedXlsxCopyEditor,
    verifier: IndependentXlsxRevisionVerifier,
    renderer: TrustedLocalOfficePdfRenderer,
    workspace_ref: str, run_ref: str,
    revised_artifact_id: str, pdf_artifact_id: str,
    lineage_id: str, now: datetime,
) -> LocalRevisedXlsxPdf:
    """One authorized, reviewed local operation; NO model/provider side effects.

    Current source is pinned to this exact run. Same-conversation cross-run
    source selection (#3929) must provide a separate proven authority first;
    a filename or a free-form model description is never such proof.
    """
    if not isinstance(source, LocalXlsxArtifactHandoff):
        raise ContractError("authorized canonical source handoff required")
    original = source.record
    data = source.content
    if (original.artifact_kind != "source.xlsx"
            or original.media_type != XLSX_MIME
            or not original.filename.lower().endswith(".xlsx")
            or not isinstance(data, bytes)
            or not 0 < len(data) <= MAX_ARTIFACT_SIZE_BYTES
            or original.size_bytes != len(data)
            or original.integrity_ref != sha256(data).hexdigest()
            or original.workspace_ref != workspace_ref
            or original.run_ref != run_ref
            or classify_xlsx(data, local_only=True) != source.route
            or source.route.route is XlsxRoute.REJECT
            or source.route.execution_target != "padiem_desktop_local_runner"):
        raise ContractError("source integrity, locality or authority mismatch")
    if (type(edits) is not tuple or not 1 <= len(edits) <= MAX_REVISIONS
            or any(not isinstance(edit, ReviewedCellRevision) for edit in edits)
            or len({(e.sheet_name, e.cell) for e in edits}) != len(edits)):
        raise ContractError("distinct reviewed revisions required")
    if len({original.artifact_id, revised_artifact_id, pdf_artifact_id}) != 3:
        raise ContractError("source, revised workbook and PDF identities must differ")
    if not callable(getattr(editor, "revise_xlsx_copy", None)):
        raise ContractError("trusted copy editor required")
    if not callable(getattr(verifier, "verify_only_reviewed_edits", None)):
        raise ContractError("independent revision verifier required")
    if not callable(getattr(renderer, "render_xlsx_pdf", None)):
        raise ContractError("trusted Office PDF renderer required")

    try:
        revised_bytes = editor.revise_xlsx_copy(data, edits)
    except Exception:
        raise ContractError("trusted workbook copy edit failed") from None
    if (type(revised_bytes) is not bytes
            or not 0 < len(revised_bytes) <= MAX_ARTIFACT_SIZE_BYTES
            or revised_bytes == data
            or classify_xlsx(revised_bytes, local_only=True).route is XlsxRoute.REJECT):
        raise ContractError("copy editor returned invalid or unchanged workbook")
    try:
        verified = verifier.verify_only_reviewed_edits(data, revised_bytes, edits)
    except Exception:
        raise ContractError("independent revision verification failed") from None
    if verified is not True:
        raise ContractError("requested-only workbook revision not proven")
    try:
        pdf_bytes = renderer.render_xlsx_pdf(revised_bytes)
    except Exception:
        raise ContractError("approved Office PDF rendering failed") from None
    if (type(pdf_bytes) is not bytes
            or not 0 < len(pdf_bytes) <= MAX_ARTIFACT_SIZE_BYTES
            or not pdf_bytes.startswith(b"%PDF-")
            or b"%%EOF" not in pdf_bytes[-1024:]):
        raise ContractError("Office output was not a bounded PDF")

    # Both outputs use the EXISTING canonical register/lineage authorities.
    base = original.filename[:-5]
    revised = register_canonical_artifact(
        artifact_id=revised_artifact_id, artifact_kind="working.xlsx",
        filename=base + "_revised.xlsx", media_type=XLSX_MIME,
        size_bytes=len(revised_bytes), integrity_ref=sha256(revised_bytes).hexdigest(),
        workspace_ref=workspace_ref, run_ref=run_ref,
        source_ref="artifact/" + original.artifact_id,
    )
    pdf = register_canonical_artifact(
        artifact_id=pdf_artifact_id, artifact_kind="output.pdf",
        filename=base + "_revised.pdf", media_type=PDF_MIME,
        size_bytes=len(pdf_bytes), integrity_ref=sha256(pdf_bytes).hexdigest(),
        workspace_ref=workspace_ref, run_ref=run_ref,
        source_ref="artifact/" + revised.artifact_id,
    )
    lineage = declare_lineage(
        lineage_id=lineage_id, source=original, working=revised,
        outputs=(pdf,), transformation_kind="xlsx.revise.office_pdf",
        workspace_ref=workspace_ref, run_ref=run_ref, created_at=now,
    )
    return LocalRevisedXlsxPdf(source, revised, pdf, lineage, revised_bytes, pdf_bytes)
