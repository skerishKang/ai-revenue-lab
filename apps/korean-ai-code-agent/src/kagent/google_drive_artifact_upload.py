"""Source-only Google Drive output artifact creation via an approved upload port.

Parent #3580 / #3904. Creates a *new* Drive file via the official v3
multipart/related files.create payload. The Drive WRITE HTTP/OAuth connector
and approval authority are NOT implemented or enabled here: they are injected
by a separately authorized trusted host. Existing #2010 READ grants cannot
authorize writes, and no new identity/secret/store authority is created.

No network at import or construction. No implicit root, overwrite, retry or
automatic external upload. Canonical artifact bytes and workspace/run scope
must match an existing #3594 record before a provider call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any, Protocol

from .artifact_lineage import LineageArtifactRef
from .artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, CanonicalArtifactRecord,
    MAX_ARTIFACT_SIZE_BYTES,
)
from .connector_trust import (
    ConnectorBindingProjection, ConnectorWriteIntent, ConnectorWriteReceipt,
    IdempotencyDisposition, InMemoryWriteIdempotencyRegistry,
)
from .contracts import ContractError
from .google_drive_scope import (
    DriveResourceProof, DriveScopeDecision, DriveScopeProjection,
    DriveFileMetadata, authorize_drive_resource,
)

DRIVE_UPLOAD_PATH = "/upload/drive/v3/files"
DRIVE_UPLOAD_QUERY = {"uploadType": "multipart", "supportsAllDrives": "true",
                      "fields": "id,name,mimeType,parents,version,size,md5Checksum,sha256Checksum,driveId,trashed"}
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_WRITE_SCOPES = frozenset({
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
})
DRIVE_UPLOAD_CAPABILITY = "drive.files.create"
DRIVE_UPLOAD_TOOL = "upload_file"
TIMEOUT_SECONDS = 30
MAX_UPLOAD_BYTES = MAX_ARTIFACT_SIZE_BYTES
MULTIPART_OVERHEAD_MAX = 2048
SOURCE_ONLY = True
PRODUCTION_DRIVE_WRITE_ACTIVATED = False
NEW_CONNECTOR_AUTHORITY = False
NEW_APPROVAL_AUTHORITY = False
NEW_DURABLE_STORE = False
AUTO_RETRY = False


class DriveArtifactUploadError(ContractError):
    """Fail-closed Drive artifact upload error, without provider body."""


@dataclass(frozen=True, slots=True)
class DriveArtifactMaterial:
    record: CanonicalArtifactRecord
    content: bytes


class DriveArtifactMaterialPort(Protocol):
    def resolve_artifact_material(
        self, artifact_ref: LineageArtifactRef, *,
        workspace_ref: str, run_ref: str,
    ) -> DriveArtifactMaterial | None: ...


class DriveFolderProofPort(Protocol):
    def resolve_folder_proof(
        self, *, binding_ref: str, actor_ref: str,
        folder_ref: str,
    ) -> DriveResourceProof | None: ...


class DriveWriteApprovalPort(Protocol):
    def verify_write_approval(
        self, *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
        workspace_ref: str, run_ref: str,
    ) -> bool: ...


class AuthorizedDriveMultipartCreatePort(Protocol):
    """The *existing* connector/CP WRITE authority must implement this seam.

    No token, refresh secret, account path, URL, or model-generated destination
    is accepted. Trusted grant and short-lived WRITE lease checks belong to the
    eventual host composition, not this product-local source module.
    """
    def create_file_multipart(
        self, *, binding_ref: str, actor_ref: str, path: str,
        query: dict[str, str], body: bytes,
        content_type: str, timeout_seconds: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DriveUploadResult:
    """Internal exact provider receipt + immutable canonical durable artifact."""
    receipt: ConnectorWriteReceipt
    artifact: CanonicalArtifactRecord

    def public_projection(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-drive-artifact-upload.v1",
            "artifact_id": self.artifact.artifact_id,
            "integrity_ref": self.artifact.integrity_ref,
            "lifecycle": self.artifact.lifecycle.value,
            "location_kind": self.artifact.durable_location.location_kind,
            "file_id_present": True,
            "receipt_ref": self.receipt.receipt_ref,
            "raw_provider_file_id": False,
            "raw_folder_id": False,
            "raw_artifact_bytes": False,
            "raw_oauth_credential": False,
            "production_write_activated": False,
        }


def upload_payload_fingerprint(
    *, artifact: CanonicalArtifactRecord, folder_ref: str,
) -> str:
    if not isinstance(artifact, CanonicalArtifactRecord):
        raise DriveArtifactUploadError("canonical artifact required")
    if not isinstance(folder_ref, str) or not folder_ref or "/" in folder_ref:
        raise DriveArtifactUploadError("bounded opaque folder reference required")
    data = json.dumps({
        "artifact_id": artifact.artifact_id,
        "sha256": artifact.integrity_ref,
        "size": artifact.size_bytes,
        "name": artifact.filename,
        "mime": artifact.media_type,
        "folder_ref": folder_ref,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _multipart(
    *, artifact: CanonicalArtifactRecord, folder_ref: str,
    content: bytes,
) -> tuple[bytes, str]:
    # JSON encodes arbitrary Unicode file names safely. MIME comes from the
    # validated #3594 artifact record and cannot inject multipart headers.
    boundary = "padiem" + secrets.token_hex(16)
    sep = boundary.encode("ascii")
    metadata = json.dumps({
        "name": artifact.filename,
        "mimeType": artifact.media_type,
        "parents": [folder_ref],
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = (
        b"--" + sep + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        + metadata + b"\r\n"
        + b"--" + sep + b"\r\nContent-Type: "
        + artifact.media_type.encode("ascii") + b"\r\n\r\n"
        + content + b"\r\n--" + sep + b"--\r\n"
    )
    if len(body) > len(content) + len(metadata) + MULTIPART_OVERHEAD_MAX:
        raise DriveArtifactUploadError("multipart metadata overhead exceeds bound")
    return body, f"multipart/related; boundary={boundary}"


def _returned_metadata(
    raw: dict[str, Any], *, artifact: CanonicalArtifactRecord,
    folder_ref: str, content: bytes,
) -> DriveFileMetadata:
    if type(raw) is not dict:
        raise DriveArtifactUploadError("Drive provider response must be an object")
    # Never trust a result with absent integrity. Neither provider metadata
    # presence nor a 2xx HTTP code alone proves output durability.
    if type(raw.get("trashed")) is not bool or raw["trashed"]:
        raise DriveArtifactUploadError("Drive returned trashed/unknown file")
    size = raw.get("size")
    if isinstance(size, bool) or not isinstance(size, (int, str)):
        raise DriveArtifactUploadError("Drive output size not attested")
    try:
        actual_size = int(size)
    except ValueError:
        raise DriveArtifactUploadError("Drive output size invalid") from None
    if str(actual_size) != str(size) or actual_size != len(content):
        raise DriveArtifactUploadError("Drive output size mismatch")
    try:
        metadata = DriveFileMetadata.from_provider(raw)
    except ContractError:
        raise DriveArtifactUploadError("Drive output metadata invalid") from None
    if (
        metadata.file_id == folder_ref
        or metadata.name != artifact.filename
        or metadata.mime_type != artifact.media_type
        or metadata.parents != (folder_ref,)
        or metadata.is_shortcut
    ):
        raise DriveArtifactUploadError("Drive output identity/parent mismatch")
    # Drive returns MD5 for stored binary content; an absent/mismatched digest
    # is fail-closed, never projected as a verified file.
    if metadata.md5_checksum != hashlib.md5(content, usedforsecurity=False).hexdigest():
        raise DriveArtifactUploadError("Drive output binary checksum missing/mismatched")
    if metadata.sha256_checksum is not None and metadata.sha256_checksum != artifact.integrity_ref:
        raise DriveArtifactUploadError("Drive output SHA256 mismatch")
    return metadata


class GoogleDriveArtifactUploadAdapter:
    """An inert until composed, single-attempt new-file upload executor."""

    def __init__(
        self, *, binding: ConnectorBindingProjection, scope: DriveScopeProjection,
        artifacts: DriveArtifactMaterialPort, folders: DriveFolderProofPort,
        approval: DriveWriteApprovalPort, upload: AuthorizedDriveMultipartCreatePort,
        attempts: InMemoryWriteIdempotencyRegistry | None = None,
    ) -> None:
        if not isinstance(binding, ConnectorBindingProjection) or not isinstance(scope, DriveScopeProjection):
            raise DriveArtifactUploadError("trusted Drive connector binding and scope required")
        if binding.connector_id != "google-drive" or scope.binding_ref != binding.binding_ref:
            raise DriveArtifactUploadError("Drive binding and scope mismatch")
        for obj, method in (
            (artifacts, "resolve_artifact_material"),
            (folders, "resolve_folder_proof"),
            (approval, "verify_write_approval"),
            (upload, "create_file_multipart"),
        ):
            if not callable(getattr(obj, method, None)):
                raise DriveArtifactUploadError("required trusted connector port is missing")
        self._binding, self._scope = binding, scope
        self._artifacts, self._folders = artifacts, folders
        self._approval, self._upload = approval, upload
        self._attempts = attempts if attempts is not None else InMemoryWriteIdempotencyRegistry()

    def create_output(
        self, *, artifact_ref: LineageArtifactRef, intent: ConnectorWriteIntent,
        workspace_ref: str, run_ref: str, now: datetime,
    ) -> DriveUploadResult:
        if not isinstance(artifact_ref, LineageArtifactRef) or not isinstance(intent, ConnectorWriteIntent):
            raise DriveArtifactUploadError("canonical artifact ref and write intent required")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise DriveArtifactUploadError("trusted aware time required")
        if not isinstance(workspace_ref, str) or not isinstance(run_ref, str):
            raise DriveArtifactUploadError("trusted workspace/run references required")
        if (
            intent.connector_id != "google-drive"
            or intent.tool_name != DRIVE_UPLOAD_TOOL
            or intent.binding_ref != self._binding.binding_ref
            or intent.actor_ref != self._binding.actor_ref
            or workspace_ref != self._binding.workspace_ref
            or not self._binding.usable_at(now)
            or not DRIVE_WRITE_SCOPES.intersection(self._binding.granted_scopes)
            or DRIVE_UPLOAD_CAPABILITY not in self._binding.granted_capabilities
            or intent.expected_version_ref is not None
        ):
            raise DriveArtifactUploadError("Drive WRITE grant, scope or create intent is unauthorized")

        material = self._artifacts.resolve_artifact_material(
            artifact_ref, workspace_ref=workspace_ref, run_ref=run_ref,
        )
        if not isinstance(material, DriveArtifactMaterial):
            raise DriveArtifactUploadError("canonical artifact material unavailable")
        artifact, content = material.record, material.content
        if (
            not isinstance(artifact, CanonicalArtifactRecord)
            or artifact.artifact_id != artifact_ref.artifact_id
            or artifact.integrity_ref != artifact_ref.integrity_ref
            or artifact.workspace_ref != workspace_ref
            or artifact.run_ref != run_ref
            or artifact.lifecycle is ArtifactLifecycle.DURABLE
            or not isinstance(content, bytes)
            or not content or len(content) > MAX_UPLOAD_BYTES
            or len(content) != artifact.size_bytes
            or hashlib.sha256(content).hexdigest() != artifact.integrity_ref
        ):
            raise DriveArtifactUploadError("artifact provenance, bytes or integrity mismatch")

        proof = self._folders.resolve_folder_proof(
            binding_ref=intent.binding_ref, actor_ref=intent.actor_ref,
            folder_ref=intent.target_ref,
        )
        if not isinstance(proof, DriveResourceProof):
            raise DriveArtifactUploadError("trusted Drive folder proof required")
        if (
            proof.metadata.file_id != intent.target_ref
            or proof.metadata.mime_type != DRIVE_FOLDER_MIME
            or authorize_drive_resource(self._scope, proof) is not DriveScopeDecision.ALLOW
        ):
            raise DriveArtifactUploadError("Drive folder is untrusted or outside scope")
        if intent.payload_fingerprint != upload_payload_fingerprint(
            artifact=artifact, folder_ref=intent.target_ref,
        ):
            raise DriveArtifactUploadError("Drive upload intent is not bound to these bytes/folder")
        # Existing approval authority decides; caller cannot supply a boolean
        # approval on the request or mint one from a model output.
        if self._approval.verify_write_approval(
            intent=intent, artifact_ref=artifact_ref,
            workspace_ref=workspace_ref, run_ref=run_ref,
        ) is not True:
            raise DriveArtifactUploadError("Drive upload approval unavailable")

        # Reservation before provider interaction: no automatic replay after
        # an uncertain network outcome. Durable cross-worker replay belongs to
        # the separately authorized platform store/host composition.
        if self._attempts.observe(intent) is not IdempotencyDisposition.NEW:
            raise DriveArtifactUploadError("Drive upload replay/conflict refused")

        body, content_type = _multipart(
            artifact=artifact, folder_ref=intent.target_ref, content=content,
        )
        try:
            raw = self._upload.create_file_multipart(
                binding_ref=intent.binding_ref, actor_ref=intent.actor_ref,
                path=DRIVE_UPLOAD_PATH, query=dict(DRIVE_UPLOAD_QUERY),
                body=body, content_type=content_type,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except Exception:
            # OAuth, HTTP and provider failures can contain private headers,
            # Drive ids and body text. Never forward exception details.
            raise DriveArtifactUploadError("Drive upload provider unavailable or refused") from None

        metadata = _returned_metadata(
            raw, artifact=artifact, folder_ref=intent.target_ref, content=content,
        )
        output = replace(
            artifact,
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="google_drive", location_ref=metadata.file_id),
        )
        receipt = ConnectorWriteReceipt(
            receipt_ref="drive-upload-" + hashlib.sha256(intent.idempotency_key.encode()).hexdigest()[:24],
            connector_id="google-drive",
            binding_ref=intent.binding_ref,
            idempotency_key=intent.idempotency_key,
            provider_operation_ref=metadata.file_id,
            target_ref=intent.target_ref,
            committed_at=now.astimezone(timezone.utc),
            evidence_ref=intent.evidence_ref,
            version_ref=f"drive-version:{metadata.version}",
        )
        return DriveUploadResult(receipt=receipt, artifact=output)
