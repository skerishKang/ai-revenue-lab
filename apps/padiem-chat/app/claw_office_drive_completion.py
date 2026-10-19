"""#3580/#3933: completed P01 Office XLSX+PDF -> approved Drive -> D1 index.

Host-only composition. An owner-reviewed local Office run must have produced
canonical bytes and two independent existing Control Plane WRITE approvals.
This module creates no auth, model execution, Drive transport or public route.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kagent.artifact_lineage import LineageArtifactRef
from kagent.connector_trust import ConnectorWriteIntent
from kagent.google_drive_artifact_upload import (
    DriveArtifactMaterial, DRIVE_UPLOAD_TOOL, upload_payload_fingerprint,
)
from kagent.local_xlsx_revision_pdf import LocalRevisedXlsxPdf

from .claw_durable_drive_output_pipeline import (
    ClawDurableDriveOutputPipeline,
    DurableArtifactCompletionError,
    DurableArtifactRegistration,
)


@dataclass(frozen=True, slots=True)
class CompletedOfficeDriveDelivery:
    """Two separately registered immutable artifacts, never a shared file ID."""

    xlsx: DurableArtifactRegistration
    pdf: DurableArtifactRegistration

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-office-drive-completion.v1",
            "xlsx": self.xlsx.public_projection(),
            "pdf": self.pdf.public_projection(),
            "both_indexed": (
                self.xlsx.stored_in_conversation_index
                and self.pdf.stored_in_conversation_index
            ),
            "pdf_fidelity_attested": False,
            "provider_file_ids_present": False,
            "oauth_or_drive_authority_created": False,
        }


class ClawOfficeDriveCompletion:
    """Explicit two-file handoff to the existing approved uploader.

    The first upload may have completed if the second operation fails.
    The host MUST NOT replay this pair; it requires a separately approved
    reconciliation based on the existing receipt/D1 index.
    """

    def __init__(self, *, pipeline: ClawDurableDriveOutputPipeline) -> None:
        if not isinstance(pipeline, ClawDurableDriveOutputPipeline):
            raise DurableArtifactCompletionError("approved Drive/D1 pipeline required")
        self._pipeline = pipeline

    async def upload_completed_revision(
        self, *, owner_id: str, conversation_id: str,
        workspace_ref: str, run_ref: str,
        outputs: LocalRevisedXlsxPdf,
        xlsx_intent: ConnectorWriteIntent,
        pdf_intent: ConnectorWriteIntent,
        now: datetime,
    ) -> CompletedOfficeDriveDelivery:
        """Check BOTH canonical materials and intent fingerprints before WRITE."""
        if (not isinstance(outputs, LocalRevisedXlsxPdf)
                or not isinstance(xlsx_intent, ConnectorWriteIntent)
                or not isinstance(pdf_intent, ConnectorWriteIntent)
                or not isinstance(now, datetime)
                or now.tzinfo is None or now.utcoffset() is None
                or not all(isinstance(x, str) and x for x in (
                    owner_id, conversation_id, workspace_ref, run_ref,
                ))):
            raise DurableArtifactCompletionError("trusted Office completion required")
        source = outputs.source.record
        xlsx, pdf = outputs.revised, outputs.pdf
        if (source.workspace_ref != workspace_ref
                or source.run_ref != run_ref
                or xlsx.workspace_ref != workspace_ref
                or xlsx.run_ref != run_ref
                or pdf.workspace_ref != workspace_ref
                or pdf.run_ref != run_ref
                or xlsx.artifact_id == pdf.artifact_id
                or source.artifact_id in (xlsx.artifact_id, pdf.artifact_id)
                or outputs.lineage.source.artifact_id != source.artifact_id
                or outputs.lineage.source.integrity_ref != source.integrity_ref
                or outputs.lineage.working_artifact_id != xlsx.artifact_id
                or outputs.lineage.working_integrity_ref != xlsx.integrity_ref
                or outputs.lineage.output_artifact_ids != (pdf.artifact_id,)
                or outputs.lineage.output_integrity_refs != (pdf.integrity_ref,)
                or xlsx.media_type != (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                or pdf.media_type != "application/pdf"):
            raise DurableArtifactCompletionError("Office lineage mismatch")
        if (xlsx_intent.idempotency_key == pdf_intent.idempotency_key
                or xlsx_intent.approval_ref == pdf_intent.approval_ref
                or xlsx_intent.binding_ref != pdf_intent.binding_ref
                or xlsx_intent.actor_ref != pdf_intent.actor_ref):
            raise DurableArtifactCompletionError("independent file approvals required")

        refs: list[LineageArtifactRef] = []
        for record, intent in ((xlsx, xlsx_intent), (pdf, pdf_intent)):
            ref = LineageArtifactRef(record.artifact_id, record.integrity_ref)
            material = outputs.resolve_artifact_material(
                ref, workspace_ref=workspace_ref, run_ref=run_ref,
            )
            if (not isinstance(material, DriveArtifactMaterial)
                    or material.record != record
                    or intent.connector_id != "google-drive"
                    or intent.tool_name != DRIVE_UPLOAD_TOOL
                    or intent.payload_fingerprint != upload_payload_fingerprint(
                        artifact=record, folder_ref=intent.target_ref,
                    )):
                raise DurableArtifactCompletionError(
                    "reviewed Office material and approved intent mismatch"
                )
            refs.append(ref)

        # The existing pipeline checks the CURRENT completed D1 run and live
        # approval through its uploader immediately before EACH provider call.
        xlsx_result = await self._pipeline.upload_completed_run_output(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref, run_ref=run_ref,
            artifact_ref=refs[0], source_record=xlsx,
            intent=xlsx_intent, now=now,
        )
        pdf_result = await self._pipeline.upload_completed_run_output(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref, run_ref=run_ref,
            artifact_ref=refs[1], source_record=pdf,
            intent=pdf_intent, now=now,
        )
        return CompletedOfficeDriveDelivery(xlsx=xlsx_result, pdf=pdf_result)


PRODUCTION_OFFICE_TO_DRIVE_COMPOSED = False
