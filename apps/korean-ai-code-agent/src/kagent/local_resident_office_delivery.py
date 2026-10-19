"""#3580: post-ACK-only trusted Office pair -> existing Broker byte publisher.

No unsolicited file enumeration, Windows server, Google Drive grant, Office
execution, or public upload route. Only a host-injected P01-approved pair may
cross this boundary after the canonical Broker acknowledged a successful run.
"""
from __future__ import annotations

import hashlib
from typing import Any, Protocol

from .artifact_lineage import LineageArtifactRef
from .contracts import ContractError
from .local_agent_command_admission import AdmittedLocalCommandExecutionReceipt
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_office_chunk_publisher import LocalOfficeChunkPublisher
from .local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from .local_xlsx_pdf_output import LocalXlsxPdfOutput
from .windows_local_executor import WindowsExecutionTermination

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"


class TrustedApprovedOfficePairPort(Protocol):
    """Trusted P01 file-read/Excel renderer host; not a browser/LLM input.

    Returns None for non-Office commands. Its implementation must have
    independently enforced the local selected-root READ and Office conversion
    permissions. The resident does not choose a file by walking a directory.
    """

    def completed_pair(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> tuple[LocalXlsxArtifactHandoff, LocalXlsxPdfOutput] | None: ...


class ResidentOfficePairPublisher:
    """Real post-ACK sender, with canonical immutable original and PDF checks."""

    def __init__(self, *, approved_pairs: TrustedApprovedOfficePairPort,
                 publisher: LocalOfficeChunkPublisher) -> None:
        if not callable(getattr(approved_pairs, "completed_pair", None)):
            raise ContractError("trusted P01-approved Office pair source is required")
        if not isinstance(publisher, LocalOfficeChunkPublisher):
            raise ContractError("canonical pinned HTTPS Office byte publisher required")
        self._approved_pairs = approved_pairs
        self._publisher = publisher

    def on_acknowledged(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt, credential: bytes,
    ) -> tuple[object, object] | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)
                or type(credential) is not bytes or not credential):
            raise ContractError("canonical broker receipt/binding required before Office staging")
        fact: AdmittedLocalCommandExecutionReceipt = receipt.execution
        if (fact.command_id != command.command_id or fact.run_id != command.run_id
                or fact.binding_ref != binding.binding_ref
                or len(fact.request_fingerprint) != 64
                or fact.revision_ref != command.revision_ref
                or fact.tool_request_ref != command.tool_request_ref
                or fact.sequence != command.sequence
                or fact.termination is not WindowsExecutionTermination.EXITED
                or fact.exit_code != 0
                or not receipt.evidence_ref
                or not fact.admission_ref):
            # Refusal precedes even looking for an Office output.
            raise ContractError("exact acknowledged successful Office command is required")
        pair = self._approved_pairs.completed_pair(
            binding=binding, command=command, receipt=receipt,
        )
        if pair is None:
            return None
        if (type(pair) is not tuple or len(pair) != 2
                or not isinstance(pair[0], LocalXlsxArtifactHandoff)
                or not isinstance(pair[1], LocalXlsxPdfOutput)):
            raise ContractError("trusted Office producer did not return a canonical pair")
        source, output = pair
        source_record, pdf_record = source.record, output.record
        xlsx_ref = LineageArtifactRef(
            artifact_id=source_record.artifact_id,
            integrity_ref=source_record.integrity_ref,
        )
        pdf_ref = LineageArtifactRef(
            artifact_id=pdf_record.artifact_id,
            integrity_ref=pdf_record.integrity_ref,
        )
        if (source_record.workspace_ref != binding.workspace_ref
                or pdf_record.workspace_ref != binding.workspace_ref
                or source_record.run_ref != command.run_id
                or pdf_record.run_ref != command.run_id
                or output.source_record != source_record
                or source_record.media_type != XLSX_MIME
                or pdf_record.media_type != PDF_MIME
                or source_record.artifact_kind != "source.xlsx"
                or pdf_record.artifact_kind != "output.pdf"
                or output.lineage.workspace_ref != binding.workspace_ref
                or output.lineage.run_ref != command.run_id
                or source.resolve_artifact_material(
                    xlsx_ref, workspace_ref=binding.workspace_ref, run_ref=command.run_id
                ) is None
                or output.resolve_artifact_material(
                    pdf_ref, workspace_ref=binding.workspace_ref, run_ref=command.run_id
                ) is None
                or hashlib.sha256(source.content).hexdigest() != source_record.integrity_ref
                or hashlib.sha256(output.content).hexdigest() != pdf_record.integrity_ref):
            raise ContractError("Office pair scope, origin or bytes mismatch")
        # The broker validates all of this AGAIN against the canonical
        # acknowledged command and device authority, then validates whole bytes.
        xlsx = self._publisher.publish(
            binding_ref=binding.binding_ref, credential=credential,
            command_id=command.command_id, run_id=command.run_id,
            artifact_id=source_record.artifact_id,
            filename=source_record.filename, media_type=XLSX_MIME,
            content=source.content, kind="xlsx",
        )
        pdf = self._publisher.publish(
            binding_ref=binding.binding_ref, credential=credential,
            command_id=command.command_id, run_id=command.run_id,
            artifact_id=pdf_record.artifact_id,
            filename=pdf_record.filename, media_type=PDF_MIME,
            content=output.content, kind="pdf",
        )
        return xlsx, pdf


RESIDENT_OFFICE_PAIR_PROVIDER_PRODUCTION_CONFIGURED = False
GOOGLE_DRIVE_WRITE_GRANTED_BY_STAGING = False
