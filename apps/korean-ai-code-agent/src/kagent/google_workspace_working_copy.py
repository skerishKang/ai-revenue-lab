"""Native Docs/Sheets working-copy edit -> PDF export (#3580 / #3908).

Source-only adapter. Provider calls, READ evidence, exclusive edit lease, OAuth
WRITE authorization and approvals belong to injected existing trusted ports.
Not composed in Production; never runs directly from model instructions.
Only native Google Docs/Sheets inputs. XLSX fidelity conversion is NOT claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Protocol

from .artifact_lineage import ArtifactLineage, declare_lineage
from .artifact_registration import (
    ArtifactLifecycle, CanonicalArtifactRecord, MAX_ARTIFACT_SIZE_BYTES,
    register_canonical_artifact,
)
from .connector_trust import (
    ConnectorBindingProjection, ConnectorWriteIntent, ConnectorWriteReceipt,
    IdempotencyDisposition, InMemoryWriteIdempotencyRegistry,
)
from .contracts import ContractError
from .google_drive_scope import (
    DriveFileMetadata, DriveResourceProof, DriveScopeDecision,
    DriveScopeProjection, authorize_drive_resource,
)

DOCS_MIME = "application/vnd.google-apps.document"
SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
DRIVE_WRITE_SCOPES = frozenset({"https://www.googleapis.com/auth/drive.file",
                               "https://www.googleapis.com/auth/drive"})
DOCS_CAPABILITY = "workspace.docs.replace"
SHEETS_CAPABILITY = "workspace.sheets.values.write"
COMMON_CAPABILITIES = frozenset({"drive.files.copy", "drive.files.export"})
COPY_PATH = "/drive/v3/files/{fileId}/copy"
EXPORT_PATH = "/drive/v3/files/{fileId}/export"
SHEETS_A1 = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]{0,69}|'[^'!/\r\n]{1,70}')![A-Z]{1,3}[1-9][0-9]{0,5}$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SOURCE_ONLY = True
PRODUCTION_WORKSPACE_WRITE_ACTIVATED = False
GOOGLE_WORKSPACE_NATIVE_ONLY = True
XLSX_TO_SHEETS_FIDELITY_PROVEN = False
AUTOMATIC_RETRY = False


class WorkspaceCopyError(ContractError):
    """Fixed error vocabulary; provider exception and body never surfaced."""


@dataclass(frozen=True, slots=True)
class NativeEdit:
    """One bounded Docs exact-text substitution or Sheets RAW cells write."""
    kind: str
    find_text: str = ""
    replace_text: str = ""
    range_a1: str = ""
    values: tuple[tuple[Any, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "docs":
            if (not isinstance(self.find_text, str) or not self.find_text
                    or len(self.find_text) > 500 or "\x00" in self.find_text
                    or not isinstance(self.replace_text, str)
                    or len(self.replace_text) > 2000 or "\x00" in self.replace_text
                    or self.range_a1 or self.values):
                raise WorkspaceCopyError("invalid bounded Docs replacement")
        elif self.kind == "sheets":
            if (not isinstance(self.range_a1, str) or not SHEETS_A1.fullmatch(self.range_a1)
                    or self.find_text or self.replace_text
                    or not isinstance(self.values, tuple)
                    or not 1 <= len(self.values) <= 32):
                raise WorkspaceCopyError("invalid Sheets range or data")
            width = None
            count = 0
            for row in self.values:
                if not isinstance(row, tuple) or not 1 <= len(row) <= 20:
                    raise WorkspaceCopyError("invalid Sheets row")
                width = len(row) if width is None else width
                if len(row) != width:
                    raise WorkspaceCopyError("Sheets data must be rectangular")
                count += len(row)
                for item in row:
                    if type(item) not in (str, int, float, bool):
                        raise WorkspaceCopyError("unsupported Sheets cell")
                    if type(item) is str and (len(item) > 1000 or "\x00" in item):
                        raise WorkspaceCopyError("Sheets cell text exceeds bound")
                    if type(item) is float and not math.isfinite(item):
                        raise WorkspaceCopyError("nonfinite Sheets number")
            if count > 256:
                raise WorkspaceCopyError("Sheets cell budget exceeded")
        else:
            raise WorkspaceCopyError("only native Docs and Sheets edits supported")

    def fingerprint_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "find_text": self.find_text,
                "replace_text": self.replace_text, "range_a1": self.range_a1,
                "values": self.values}


class WorkspaceProofPort(Protocol):
    def resolve(self, *, binding_ref: str, actor_ref: str,
                source_id: str, folder_id: str) -> tuple[DriveResourceProof, DriveResourceProof]: ...


class WorkspaceApprovalPort(Protocol):
    def verify(self, *, intent: ConnectorWriteIntent,
               workspace_ref: str, run_ref: str) -> bool: ...


class ExclusiveWorkingCopyLeasePort(Protocol):
    def verify(self, *, intent: ConnectorWriteIntent, workspace_ref: str,
               run_ref: str, copied_file_id: str) -> bool: ...


class WorkspaceProviderPort(Protocol):
    """Trusted host owns credentials, scope, HTTP, safe logging and WRITE lease."""
    def copy_file(self, *, file_id: str, body: dict[str, Any],
                  query: dict[str, str]) -> dict[str, Any]: ...
    def docs_revision(self, *, file_id: str) -> str: ...
    def docs_batch_update(self, *, file_id: str,
                          body: dict[str, Any]) -> dict[str, Any]: ...
    def sheets_values_batch_update(self, *, file_id: str,
                                   body: dict[str, Any]) -> dict[str, Any]: ...
    def export_file(self, *, file_id: str, mime_type: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class WorkingCopyExportResult:
    output: CanonicalArtifactRecord
    pdf_bytes: bytes  # trusted internal transport handoff only
    lineage: ArtifactLineage
    copy_receipt: ConnectorWriteReceipt

    def public_projection(self) -> dict[str, Any]:
        return {"contract_version": "claw-google-workspace-working-copy.v1",
                "output": self.output.public_projection(),
                "lineage": self.lineage.public_projection(),
                "working_copy_present": True,
                "source_preserved": True,
                "raw_working_file_id": False,
                "raw_pdf_bytes": False,
                "real_write_activated": False}


def edit_fingerprint(*, source: CanonicalArtifactRecord, folder_id: str,
                     new_name: str, edit: NativeEdit, pdf_filename: str) -> str:
    if not isinstance(source, CanonicalArtifactRecord) or not isinstance(edit, NativeEdit):
        raise WorkspaceCopyError("canonical source and edit required")
    if not isinstance(folder_id, str) or not REF.fullmatch(folder_id):
        raise WorkspaceCopyError("opaque destination folder required")
    if not isinstance(new_name, str) or not 1 <= len(new_name) <= 150 or any(
        ch in new_name for ch in ('/', '\\', '\r', '\n', '\x00')
    ):
        raise WorkspaceCopyError("bounded working name required")
    if not isinstance(pdf_filename, str) or not pdf_filename.lower().endswith(".pdf"):
        raise WorkspaceCopyError("PDF output filename required")
    data = {"source": source.artifact_id, "sha256": source.integrity_ref,
            "folder": folder_id, "name": new_name, "edit": edit.fingerprint_dict(),
            "pdf_filename": pdf_filename}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class GoogleWorkspaceWorkingCopyAdapter:
    def __init__(self, *, binding: ConnectorBindingProjection,
                 scope: DriveScopeProjection, proofs: WorkspaceProofPort,
                 approval: WorkspaceApprovalPort, lease: ExclusiveWorkingCopyLeasePort,
                 provider: WorkspaceProviderPort,
                 attempts: InMemoryWriteIdempotencyRegistry | None = None) -> None:
        if (not isinstance(binding, ConnectorBindingProjection)
                or binding.connector_id != "google-drive"
                or not isinstance(scope, DriveScopeProjection)
                or scope.binding_ref != binding.binding_ref):
            raise WorkspaceCopyError("canonical Drive binding and scope required")
        for obj, method in ((proofs, "resolve"), (approval, "verify"),
                            (lease, "verify"), (provider, "copy_file"),
                            (provider, "docs_revision"), (provider, "docs_batch_update"),
                            (provider, "sheets_values_batch_update"), (provider, "export_file")):
            if not callable(getattr(obj, method, None)):
                raise WorkspaceCopyError("trusted Workspace port missing")
        self.binding, self.scope, self.proofs = binding, scope, proofs
        self.approval, self.lease, self.provider = approval, lease, provider
        self.attempts = attempts if attempts is not None else InMemoryWriteIdempotencyRegistry()

    def copy_edit_export(self, *, source: CanonicalArtifactRecord,
                         intent: ConnectorWriteIntent, edit: NativeEdit,
                         new_name: str, pdf_filename: str, output_artifact_id: str,
                         workspace_ref: str, run_ref: str, now: datetime) -> WorkingCopyExportResult:
        if not isinstance(source, CanonicalArtifactRecord) or not isinstance(intent, ConnectorWriteIntent):
            raise WorkspaceCopyError("trusted canonical source and intent required")
        if not isinstance(edit, NativeEdit) or not isinstance(now, datetime) or now.tzinfo is None:
            raise WorkspaceCopyError("bounded edit and trusted time required")
        required = DOCS_CAPABILITY if edit.kind == "docs" else SHEETS_CAPABILITY
        mime = DOCS_MIME if edit.kind == "docs" else SHEETS_MIME
        if (intent.connector_id != "google-drive"
                or intent.binding_ref != self.binding.binding_ref
                or intent.actor_ref != self.binding.actor_ref
                or intent.tool_name != "workspace_copy_edit_export"
                or intent.expected_version_ref is not None
                or workspace_ref != self.binding.workspace_ref
                or source.workspace_ref != workspace_ref
                or source.run_ref != run_ref
                or not self.binding.usable_at(now)
                or not DRIVE_WRITE_SCOPES.intersection(self.binding.granted_scopes)
                or not COMMON_CAPABILITIES.issubset(self.binding.granted_capabilities)
                or required not in self.binding.granted_capabilities):
            raise WorkspaceCopyError("Workspace WRITE scope/identity unavailable")
        if (source.lifecycle is not ArtifactLifecycle.DURABLE
                or source.durable_location is None
                or source.durable_location.location_kind != "google_drive"
                or source.artifact_id == output_artifact_id
                or intent.target_ref == source.durable_location.location_ref):
            raise WorkspaceCopyError("immutable Drive source and distinct destination required")
        if intent.payload_fingerprint != edit_fingerprint(
                source=source, folder_id=intent.target_ref, new_name=new_name,
                edit=edit, pdf_filename=pdf_filename):
            raise WorkspaceCopyError("unbound edit/destination fingerprint")
        try:
            src_proof, folder_proof = self.proofs.resolve(
                binding_ref=intent.binding_ref, actor_ref=intent.actor_ref,
                source_id=source.durable_location.location_ref,
                folder_id=intent.target_ref)
        except Exception:
            raise WorkspaceCopyError("trusted Drive evidence unavailable") from None
        if (not isinstance(src_proof, DriveResourceProof)
                or not isinstance(folder_proof, DriveResourceProof)
                or src_proof.metadata.file_id != source.durable_location.location_ref
                or src_proof.metadata.mime_type != mime
                or folder_proof.metadata.file_id != intent.target_ref
                or folder_proof.metadata.mime_type != FOLDER_MIME
                or authorize_drive_resource(self.scope, src_proof) is not DriveScopeDecision.ALLOW
                or authorize_drive_resource(self.scope, folder_proof) is not DriveScopeDecision.ALLOW):
            raise WorkspaceCopyError("source/folder proof refused")
        try:
            approved = self.approval.verify(intent=intent, workspace_ref=workspace_ref,
                                            run_ref=run_ref)
        except Exception:
            raise WorkspaceCopyError("Workspace approval unavailable") from None
        if approved is not True:
            raise WorkspaceCopyError("Workspace approval refused")
        if self.attempts.observe(intent) is not IdempotencyDisposition.NEW:
            raise WorkspaceCopyError("uncertain prior write or replay refused")

        # No subsequent write targets the source id. No automatic provider retry
        # even if copy succeeded but edit/export then fails.
        try:
            raw_copy = self.provider.copy_file(
                file_id=src_proof.metadata.file_id,
                body={"name": new_name, "parents": [intent.target_ref]},
                query={"supportsAllDrives": "true",
                       "fields": "id,name,mimeType,parents,version,trashed,driveId"})
            copy = DriveFileMetadata.from_provider(raw_copy)
            if (copy.file_id in (src_proof.metadata.file_id, intent.target_ref)
                    or copy.name != new_name or copy.mime_type != mime
                    or copy.parents != (intent.target_ref,) or copy.trashed
                    or copy.is_shortcut):
                raise WorkspaceCopyError("working copy identity invalid")
            copy_id = copy.file_id
            if self.lease.verify(intent=intent, workspace_ref=workspace_ref,
                                 run_ref=run_ref, copied_file_id=copy_id) is not True:
                raise WorkspaceCopyError("exclusive working edit lease unavailable")
            if edit.kind == "docs":
                revision = self.provider.docs_revision(file_id=copy_id)
                if not isinstance(revision, str) or not REF.fullmatch(revision):
                    raise WorkspaceCopyError("Docs revision unverified")
                reply = self.provider.docs_batch_update(
                    file_id=copy_id,
                    body={"requests": [{"replaceAllText": {
                        "containsText": {"text": edit.find_text, "matchCase": True},
                        "replaceText": edit.replace_text}}],
                        "writeControl": {"requiredRevisionId": revision}})
                if (not isinstance(reply, dict)
                        or len(reply.get("replies", [])) != 1
                        or not isinstance(reply["replies"][0], dict)
                        or type(reply["replies"][0].get("replaceAllText", {}).get("occurrencesChanged")) is not int
                        or reply["replies"][0]["replaceAllText"]["occurrencesChanged"] < 1):
                    raise WorkspaceCopyError("Docs edit not verified")
            else:
                count = sum(map(len, edit.values))
                reply = self.provider.sheets_values_batch_update(
                    file_id=copy_id,
                    body={"valueInputOption": "RAW", "data": [{
                        "range": edit.range_a1,
                        "values": [list(row) for row in edit.values]}]})
                if (not isinstance(reply, dict)
                        or reply.get("spreadsheetId") != copy_id
                        or type(reply.get("totalUpdatedCells")) is not int
                        or reply["totalUpdatedCells"] != count
                        or not isinstance(reply.get("responses"), list)
                        or len(reply["responses"]) != 1):
                    raise WorkspaceCopyError("Sheets edit not verified")
            pdf = self.provider.export_file(file_id=copy_id, mime_type=PDF_MIME)
        except WorkspaceCopyError:
            raise
        except Exception:
            raise WorkspaceCopyError("trusted Workspace provider unavailable") from None
        if (not isinstance(pdf, bytes) or not 0 < len(pdf) <= MAX_ARTIFACT_SIZE_BYTES
                or not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]):
            raise WorkspaceCopyError("PDF export evidence invalid")
        result = register_canonical_artifact(
            artifact_id=output_artifact_id, artifact_kind="workspace.pdf",
            filename=pdf_filename, media_type=PDF_MIME,
            size_bytes=len(pdf), integrity_ref=hashlib.sha256(pdf).hexdigest(),
            lifecycle=ArtifactLifecycle.REGISTERED,
            workspace_ref=workspace_ref, run_ref=run_ref)
        key = hashlib.sha256(intent.idempotency_key.encode()).hexdigest()[:24]
        lineage = declare_lineage(
            lineage_id="workspace-lineage-"+key, source=source,
            transformation_kind="native_workspace_edit_pdf",
            workspace_ref=workspace_ref, run_ref=run_ref, created_at=now,
            outputs=(result,), working_representation_ref="working-"+key,
            operation_ref="workspace-op-"+key)
        receipt = ConnectorWriteReceipt(
            receipt_ref="workspace-copy-"+key,
            connector_id="google-drive", binding_ref=intent.binding_ref,
            idempotency_key=intent.idempotency_key,
            provider_operation_ref=copy_id, target_ref=intent.target_ref,
            committed_at=now.astimezone(timezone.utc),
            evidence_ref=intent.evidence_ref,
            version_ref="drive-version:"+str(copy.version))
        return WorkingCopyExportResult(
            output=result, pdf_bytes=pdf, lineage=lineage, copy_receipt=receipt)
