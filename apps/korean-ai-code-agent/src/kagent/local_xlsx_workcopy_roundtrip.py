"""#4434: one approved local XLSX workcopy -> revised file -> staged back to the run.

This is the composition seam the PC lane was missing. Every authority it uses
already exists:

* the authorized local read, selected-root boundary and canonical P01 approval
  stay in ``WindowsSelectedRootFileRuntime``;
* the source record and its provenance come from ``capture_local_xlsx_for_handoff``;
* the revision contract, literal-only edits and canonical registration stay in
  ``local_xlsx_revision_pdf`` and ``artifact_registration``;
* the Python value edit and its independent proof are
  ``local_xlsx_python_copy_editor``;
* the outbound binary return stays ``LocalOfficeChunkPublisher`` with the existing
  pinned HTTPS/443 broker transport, so the web side reassembles and re-verifies
  the SHA-256 it already knows how to verify.

What this module adds is only ordering and two guarantees the pieces could not
enforce on their own: the result path is *derived* from the approved source path
and must not already exist, so the original file can never be the write target and
a finished result is never silently overwritten; and the bytes handed to the
publisher are the bytes re-read from disk after the write, so the run receives a
result whose integrity was proven on the filesystem rather than asserted.

No file path, credential or workbook byte leaves this module: the returned object
projects identifiers and digests only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import re
from typing import Callable

from .artifact_registration import CanonicalArtifactRecord, register_canonical_artifact
from .contracts import ContractError
from .local_office_chunk_publisher import (
    LocalOfficeChunkPublisher, PrivateOfficeStagingReceipt,
)
from .local_xlsx_artifact_handoff import (
    LocalXlsxArtifactHandoff, capture_local_xlsx_for_handoff,
)
from .local_xlsx_python_copy_editor import (
    IndependentZipXlsxRevisionVerifier, PythonXlsxValueCopyEditor,
)
from .local_xlsx_revision_pdf import ReviewedCellRevision
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, LocalFileResult,
    WindowsSelectedRootFileRuntime,
)
from .local_agent import LocalAgentDeviceProfile

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_RESULT_SUFFIX = "_revised.xlsx"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}")

LOCAL_XLSX_WORKCOPY_ROUNDTRIP_IMPLEMENTED = True
ORIGINAL_FILE_NEVER_WRITE_TARGET = True
RESULT_PATH_DERIVED_NOT_SUPPLIED = True
PRODUCTION_P01_APPROVAL_REUSED = True
RUNTIME_CREDENTIAL_OR_PATH_EXPORTED = False


@dataclass(frozen=True, slots=True)
class LocalXlsxWorkcopyRoundtrip:
    """One finished local revision, staged to the broker for its own run."""

    source: LocalXlsxArtifactHandoff
    revised: CanonicalArtifactRecord
    written: LocalFileResult
    staging: PrivateOfficeStagingReceipt
    revised_relative_path: str
    command_id: str

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-local-xlsx-workcopy-roundtrip.v1",
            "source_artifact_id": self.source.record.artifact_id,
            "revised_artifact_id": self.revised.artifact_id,
            "workspace_ref": self.revised.workspace_ref,
            "run_ref": self.revised.run_ref,
            "command_id": self.command_id,
            "original_integrity_ref": self.source.record.integrity_ref,
            "result_integrity_ref": self.revised.integrity_ref,
            "result_bytes": self.revised.size_bytes,
            "result_part_count": self.staging.part_count,
            "atomic_write_verified": (
                self.written.content_sha256 == self.revised.integrity_ref
                and self.written.bytes_count == self.revised.size_bytes
            ),
            "independent_revision_validation": True,
            "original_preserved": True,
            "raw_local_path": False,
            "raw_workbook_bytes": False,
            "drive_write_authorized": False,
        }


def revised_path_for(source_relative: str) -> str:
    """Derive the only legal result path from the approved source path."""
    relative = PureWindowsPath(source_relative.replace("/", "\\"))
    if not relative.parts or relative.is_absolute() or relative.drive:
        raise ContractError("source path cannot yield a bounded result path")
    if any(part == ".." for part in relative.parts):
        # The derived name is compared against an approved WRITE, so it must not
        # even be able to carry an escaping segment forward.
        raise ContractError("source path traversal is not allowed")
    name = relative.name
    if not name.lower().endswith(".xlsx"):
        raise ContractError("only XLSX workcopies can be revised locally")
    parent = relative.parent
    derived = PureWindowsPath(*(parent.parts or ())) / (name[: -len(".xlsx")] + _RESULT_SUFFIX)
    return str(derived)


def revise_and_stage_approved_xlsx_workcopy(
    *,
    runtime: WindowsSelectedRootFileRuntime,
    device: LocalAgentDeviceProfile,
    source_request: LocalFileRequest,
    result_request_factory: Callable[[bytes, str], LocalFileRequest],
    edits: tuple[ReviewedCellRevision, ...],
    workspace_ref: str,
    source_artifact_id: str,
    result_artifact_id: str,
    binding_ref: str,
    command_id: str,
    credential: bytes,
    now: datetime,
    publisher: LocalOfficeChunkPublisher,
    editor: PythonXlsxValueCopyEditor | None = None,
    verifier: IndependentZipXlsxRevisionVerifier | None = None,
) -> LocalXlsxWorkcopyRoundtrip:
    """READ the approved workcopy, revise only the reviewed cells, stage the result."""

    if not isinstance(runtime, WindowsSelectedRootFileRuntime):
        raise ContractError("trusted selected-root file runtime required")
    if not isinstance(source_request, LocalFileRequest):
        raise ContractError("an approved source READ request is required")
    if source_request.operation is not LocalFileOperation.READ:
        raise ContractError("the source must be an approved READ")
    if not callable(result_request_factory):
        raise ContractError("a result request factory is required")
    for name, value in (
        ("workspace_ref", workspace_ref), ("source_artifact_id", source_artifact_id),
        ("result_artifact_id", result_artifact_id), ("binding_ref", binding_ref),
        ("command_id", command_id),
    ):
        if not isinstance(value, str) or not _REF.fullmatch(value.strip()):
            raise ContractError(f"{name} must be a bounded safe reference")
    if not isinstance(credential, bytes) or not credential:
        raise ContractError("device credential is required for staging")
    if not callable(getattr(publisher, "publish", None)):
        raise ContractError("Office chunk publisher port is required")

    derived = revised_path_for(source_request.path_relative)

    source = capture_local_xlsx_for_handoff(
        runtime=runtime, request=source_request, now=now,
        workspace_ref=workspace_ref, artifact_id=source_artifact_id,
    )

    editor = editor or PythonXlsxValueCopyEditor()
    verifier = verifier or IndependentZipXlsxRevisionVerifier()
    edits = tuple(edits)
    if not edits or any(not isinstance(item, ReviewedCellRevision) for item in edits):
        raise ContractError("reviewed cell revisions are required")
    if any(item.previous_value == item.replacement_value for item in edits):
        raise ContractError("every reviewed revision must change its cell")

    revised_bytes = editor.revise_xlsx_copy(source.content, edits)
    if (not isinstance(revised_bytes, bytes) or revised_bytes == source.content
            or sha256(revised_bytes).hexdigest() == source.record.integrity_ref):
        raise ContractError("revision produced no changed workbook")
    if verifier.verify_only_reviewed_edits(source.content, revised_bytes, edits) is not True:
        raise ContractError("independent verification could not prove a reviewed-only revision")

    record = register_canonical_artifact(
        artifact_id=result_artifact_id,
        artifact_kind="working.xlsx",
        filename=PureWindowsPath(derived).name,
        media_type=XLSX_MIME,
        size_bytes=len(revised_bytes),
        integrity_ref=sha256(revised_bytes).hexdigest(),
        workspace_ref=workspace_ref,
        run_ref=source_request.run_id,
        source_ref="artifact/" + source.record.artifact_id,
    )

    # The WRITE is approved against the exact result bytes, so the caller builds
    # that request once the revision exists. These guards are what keeps the
    # approval useful: same device, root and run, the derived name only, and the
    # bytes that were just verified.
    result_request = result_request_factory(revised_bytes, derived)
    if not isinstance(result_request, LocalFileRequest):
        raise ContractError("result request factory must return a LocalFileRequest")
    if result_request.operation is not LocalFileOperation.WRITE:
        raise ContractError("the result must be an approved WRITE")
    if result_request.content != revised_bytes:
        raise ContractError("the approved WRITE does not carry the verified result bytes")
    if _normalize(result_request.path_relative) != _normalize(derived):
        raise ContractError("result path must be the derived revised workcopy name")
    for field in ("device_id", "root_ref", "run_id"):
        if getattr(result_request, field) != getattr(source_request, field):
            raise ContractError("result and source requests must share device, root and run")
    if _target_exists(device, result_request):
        raise ContractError("the derived result file already exists; nothing is overwritten")

    written = runtime.perform(result_request, now=now)
    if (not isinstance(written, LocalFileResult)
            or written.content_sha256 != record.integrity_ref
            or written.bytes_count != record.size_bytes):
        raise ContractError("written result did not match the verified revision")

    # The runtime writes through a temporary file, fsyncs it and renames it into
    # place, so the returned digest is the digest of the file that now exists. A
    # second approved READ of the result would ask the user to approve a step the
    # run already authorized, so it is deliberately not performed here.

    staging = publisher.publish(
        binding_ref=binding_ref, credential=credential,
        command_id=command_id, run_id=source_request.run_id,
        artifact_id=record.artifact_id, filename=record.filename,
        media_type=XLSX_MIME, content=revised_bytes, kind="xlsx",
    )
    if (staging.artifact_id != record.artifact_id
            or staging.integrity_ref != record.integrity_ref):
        raise ContractError("staging receipt does not match the verified result")

    return LocalXlsxWorkcopyRoundtrip(source, record, written, staging, derived, command_id)


def _normalize(value: str) -> str:
    return value.replace("/", "\\").strip().casefold()


def _target_exists(device: LocalAgentDeviceProfile, request: LocalFileRequest) -> bool:
    root = Path(device.root(request.root_ref).windows_path)
    relative = PureWindowsPath(request.path_relative.replace("/", "\\"))
    target = root.joinpath(*relative.parts)
    return target.exists() or target.is_symlink()
