"""Claw durable drive-output shared test preparation (#8061).

Moved out of test_3929_claw_drive_output_registration so the test-to-test
import ratchet does not grow: the hub and its consumers all import these
names from here. The ports() fakes (Material/FolderProof/Approval/Provider)
are recording fakes: nothing here uploads to a provider.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256, md5

from kagent.artifact_registration import register_canonical_artifact
from kagent.connector_trust import ConnectorBindingProjection, ConnectorWriteIntent
from kagent.google_drive_scope import DriveResourceProof, DriveFileMetadata, DriveScopeProjection
from kagent.google_drive_artifact_upload import (
    GoogleDriveArtifactUploadAdapter, DRIVE_UPLOAD_CAPABILITY,
    upload_payload_fingerprint,
)
from _support.conversation_artifact_d1 import WORKSPACE, RUN

__all__ = [
    "ACTOR", "Approval", "ARTIFACT_ID", "BINDING", "FILE", "FOLDER",
    "FolderProof", "Material", "NOW", "PDF", "Provider", "SHA", "ports",
]

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
PDF = b"%PDF-1.4\napproved fake provider, real bytes check\n%%EOF\n"
ARTIFACT_ID = "artifact_drive_p01_3929"
BINDING = "binding_drive_p01_test"
ACTOR = "actor_3929"
FOLDER = "folder_3929"
FILE = "provider_file_3929"
SHA = sha256(PDF).hexdigest()


class Material:
    def __init__(self, record, data=PDF):
        self.record, self.data = record, data

    def resolve_artifact_material(self, ref, *, workspace_ref, run_ref):
        from kagent.google_drive_artifact_upload import DriveArtifactMaterial
        if (ref.artifact_id == self.record.artifact_id
                and ref.integrity_ref == self.record.integrity_ref
                and workspace_ref == WORKSPACE and run_ref == RUN):
            return DriveArtifactMaterial(self.record, self.data)
        return None


class FolderProof:
    def resolve_folder_proof(self, *, binding_ref, actor_ref, folder_ref):
        return DriveResourceProof(
            binding_ref=BINDING,
            metadata=DriveFileMetadata(
                file_id=FOLDER, name="Evidence", mime_type="application/vnd.google-apps.folder",
                version=1, trashed=False,
            )
        )


class Approval:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = 0

    def verify_write_approval(self, **kwargs):
        self.calls += 1
        return self.allowed


class Provider:
    def __init__(self, raise_error=False, *, data=PDF,
                 name="verified-result.pdf", mime="application/pdf",
                 uploaded_file_id=FILE):
        self.calls = 0
        self.raise_error = raise_error
        self.data, self.name, self.mime = data, name, mime
        self.uploaded_file_id = uploaded_file_id

    def create_file_multipart(self, **kwargs):
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("simulated OAuth/private provider failure")
        return {
            "id": self.uploaded_file_id, "name": self.name, "mimeType": self.mime,
            "parents": [FOLDER], "version": "1", "size": str(len(self.data)),
            "md5Checksum": md5(self.data, usedforsecurity=False).hexdigest(),
            "sha256Checksum": sha256(self.data).hexdigest(), "trashed": False,
        }


def ports(*, approval=None, provider=None, data=PDF,
          filename="verified-result.pdf", media_type="application/pdf",
          artifact_id=ARTIFACT_ID, file_ref=FILE):
    record = register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind="working.xlsx" if filename.endswith(".xlsx") else "output.pdf",
        filename=filename,
        media_type=media_type, size_bytes=len(data), integrity_ref=sha256(data).hexdigest(),
        workspace_ref=WORKSPACE, run_ref=RUN,
    )
    grant = ConnectorBindingProjection(
        binding_ref=BINDING, connector_id="google-drive", actor_ref=ACTOR,
        account_ref="account_3929", workspace_ref=WORKSPACE,
        granted_scopes=("https://www.googleapis.com/auth/drive.file",),
        granted_capabilities=(DRIVE_UPLOAD_CAPABILITY,),
        issued_at=NOW - timedelta(minutes=30),
        updated_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(minutes=30),
    )
    provider = provider or Provider(
        data=data, name=filename, mime=media_type, uploaded_file_id=file_ref
    )
    approval = approval or Approval()
    adapter = GoogleDriveArtifactUploadAdapter(
        binding=grant,
        scope=DriveScopeProjection(binding_ref=BINDING, allowed_folder_ids=(FOLDER,)),
        artifacts=Material(record, data), folders=FolderProof(),
        approval=approval, upload=provider,
    )
    intent = ConnectorWriteIntent(
        connector_id="google-drive", binding_ref=BINDING,
        actor_ref=ACTOR, tool_name="upload_file",
        target_ref=FOLDER,
        payload_fingerprint=upload_payload_fingerprint(artifact=record, folder_ref=FOLDER),
        idempotency_key="idem_3929_" + artifact_id,
        approval_ref="approval_3929",
        evidence_ref="evidence_3929",
        requested_at=NOW,
    )
    return adapter, intent, record, provider, approval


