"""Hermetic #3580 Drive output-artifact multipart upload execution tests.

All Drive and approval dependencies are injected fakes; there are no network
calls, live Google OAuth grants, secret values, provider writes or D1 storage.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import (
    ArtifactLifecycle, register_canonical_artifact,
)
from kagent.connector_trust import (
    ConnectorBindingProjection, ConnectorBindingState, ConnectorWriteIntent,
)
from kagent.google_drive_scope import (
    DriveFileMetadata, DriveResourceProof, DriveScopeProjection,
)
from kagent.google_drive_artifact_upload import (
    AuthorizedDriveMultipartCreatePort, DRIVE_UPLOAD_CAPABILITY,
    DRIVE_UPLOAD_PATH, DRIVE_UPLOAD_QUERY, DRIVE_WRITE_SCOPES,
    DriveArtifactMaterial, DriveArtifactUploadError,
    GoogleDriveArtifactUploadAdapter, MAX_UPLOAD_BYTES,
    PRODUCTION_DRIVE_WRITE_ACTIVATED, upload_payload_fingerprint,
)

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
BINDING = "binding_google_1"
ACTOR = "actor_alpha"
ACCOUNT = "acct_alpha"
WORKSPACE = "workspace_alpha"
RUN = "run_alpha"
FOLDER = "folder_output"
DOC = b"%PDF-1.7\nnew estimate\n%%EOF"
SHA = hashlib.sha256(DOC).hexdigest()
MD5 = hashlib.md5(DOC, usedforsecurity=False).hexdigest()
DRIVE_WRITE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def record(**overrides):
    params = dict(
        artifact_id="artifact_pdf_1",
        artifact_kind="claw.document",
        filename="견적서 결과.pdf",
        media_type="application/pdf",
        size_bytes=len(DOC), integrity_ref=SHA,
        workspace_ref=WORKSPACE, run_ref=RUN,
    )
    params.update(overrides)
    return register_canonical_artifact(**params)


def artifact_ref(artifact=None):
    a = artifact or record()
    return LineageArtifactRef(artifact_id=a.artifact_id, integrity_ref=a.integrity_ref)


def binding(**overrides):
    params = dict(
        binding_ref=BINDING, connector_id="google-drive", actor_ref=ACTOR,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        granted_scopes=(DRIVE_WRITE_SCOPE,),
        granted_capabilities=(DRIVE_UPLOAD_CAPABILITY,),
        issued_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    params.update(overrides)
    return ConnectorBindingProjection(**params)


def intent(artifact=None, **overrides):
    a = artifact or record()
    params = dict(
        connector_id="google-drive", binding_ref=BINDING, actor_ref=ACTOR,
        tool_name="upload_file", target_ref=FOLDER,
        payload_fingerprint=upload_payload_fingerprint(
            artifact=a, folder_ref=FOLDER,
        ),
        idempotency_key="idem_upload_1", approval_ref="approval_1",
        evidence_ref="evidence_1", requested_at=NOW,
    )
    params.update(overrides)
    return ConnectorWriteIntent(**params)


class Material:
    def __init__(self, item=None):
        self.item = item if item is not None else DriveArtifactMaterial(record(), DOC)
        self.calls = []

    def resolve_artifact_material(self, artifact_ref, *, workspace_ref, run_ref):
        self.calls.append((artifact_ref, workspace_ref, run_ref))
        return self.item


class Folder:
    def __init__(self, *, folder_ref=FOLDER, mime="application/vnd.google-apps.folder",
                 trashed=False, proof_binding=BINDING):
        self.item = DriveResourceProof(
            binding_ref=proof_binding,
            metadata=DriveFileMetadata(
                file_id=folder_ref, name="Output", mime_type=mime,
                version=2, trashed=trashed,
            ),
        )
        self.calls = []

    def resolve_folder_proof(self, *, binding_ref, actor_ref, folder_ref):
        self.calls.append((binding_ref, actor_ref, folder_ref))
        return self.item


class Approval:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def verify_write_approval(self, *, intent, artifact_ref, workspace_ref, run_ref):
        self.calls.append((intent.idempotency_key, artifact_ref, workspace_ref, run_ref))
        return self.allowed


class Upload:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create_file_multipart(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return provider_result()


def provider_result(**overrides):
    params = dict(
        id="file_uploaded_123", name=record().filename, mimeType="application/pdf",
        parents=[FOLDER], version="1", size=str(len(DOC)),
        md5Checksum=MD5, sha256Checksum=SHA, trashed=False,
    )
    params.update(overrides)
    return params


def driver(*, b=None, scope=None, artifacts=None, folders=None,
           approval=None, upload=None):
    material = artifacts if artifacts is not None else Material()
    folder = folders if folders is not None else Folder()
    approve = approval if approval is not None else Approval()
    provider = upload if upload is not None else Upload()
    adapter = GoogleDriveArtifactUploadAdapter(
        binding=b if b is not None else binding(),
        scope=scope if scope is not None else DriveScopeProjection(
            binding_ref=BINDING, allowed_folder_ids=(FOLDER,),
        ),
        artifacts=material, folders=folder, approval=approve, upload=provider,
    )
    return adapter, material, folder, approve, provider


def deliver(adapter, **overrides):
    params = dict(
        artifact_ref=artifact_ref(), intent=intent(),
        workspace_ref=WORKSPACE, run_ref=RUN, now=NOW,
    )
    params.update(overrides)
    return adapter.create_output(**params)


class DriveArtifactUploadTests(unittest.TestCase):
    def test_source_is_disabled_until_existing_write_authority_composes_it(self):
        self.assertFalse(PRODUCTION_DRIVE_WRITE_ACTIVATED)
        self.assertIn(DRIVE_WRITE_SCOPE, DRIVE_WRITE_SCOPES)
        self.assertEqual(MAX_UPLOAD_BYTES, 8 * 1024 * 1024)
        self.assertEqual(DRIVE_UPLOAD_PATH, "/upload/drive/v3/files")
        self.assertEqual(DRIVE_UPLOAD_QUERY["uploadType"], "multipart")

    def test_success_binary_upload_returns_canonical_durable_artifact_and_receipt(self):
        adapter, material, folder, approve, provider = driver()
        result = deliver(adapter)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(result.artifact.durable_location.location_kind, "google_drive")
        self.assertEqual(result.artifact.durable_location.location_ref, "file_uploaded_123")
        self.assertEqual(result.artifact.integrity_ref, SHA)
        self.assertEqual(result.receipt.connector_id, "google-drive")
        self.assertEqual(result.receipt.target_ref, FOLDER)
        self.assertEqual(result.receipt.version_ref, "drive-version:1")
        self.assertEqual(material.calls[0][1:], (WORKSPACE, RUN))
        self.assertEqual(folder.calls, [(BINDING, ACTOR, FOLDER)])
        self.assertEqual(len(approve.calls), 1)
        projection = result.public_projection()
        self.assertNotIn("file_uploaded_123", str(projection))
        self.assertNotIn(FOLDER, str(projection))
        self.assertNotIn(DOC.decode(), str(projection))
        self.assertTrue(projection["file_id_present"])

    def test_official_multipart_related_has_two_parts_and_exact_original_bytes(self):
        adapter, _, _, _, port = driver()
        deliver(adapter)
        call = port.calls[0]
        self.assertEqual(call["path"], "/upload/drive/v3/files")
        self.assertEqual(call["query"]["uploadType"], "multipart")
        self.assertEqual(call["query"]["supportsAllDrives"], "true")
        self.assertEqual(call["binding_ref"], BINDING)
        self.assertEqual(call["actor_ref"], ACTOR)
        self.assertNotIn("token", str(call.keys()).lower())
        self.assertNotIn("authorization", str(call.keys()).lower())
        self.assertEqual(call["timeout_seconds"], 30)
        self.assertTrue(call["content_type"].startswith("multipart/related; boundary="))
        body = call["body"]
        boundary = call["content_type"].split("boundary=")[1].encode()
        self.assertTrue(body.startswith(b"--" + boundary + b"\r\n"))
        self.assertTrue(body.endswith(b"\r\n--" + boundary + b"--\r\n"))
        self.assertEqual(body.count(DOC), 1)
        self.assertIn(b"Content-Type: application/json; charset=UTF-8", body)
        self.assertIn(b"Content-Type: application/pdf\r\n\r\n" + DOC, body)
        metadata = body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0]
        self.assertEqual(json.loads(metadata), {
            "name": record().filename,
            "mimeType": "application/pdf",
            "parents": [FOLDER],
        })

    def test_source_record_remains_immutable_and_existing_file_not_updated(self):
        original = record()
        adapter, _, _, _, port = driver()
        result = deliver(adapter)
        self.assertEqual(original.lifecycle, ArtifactLifecycle.GENERATED)
        self.assertIsNone(original.durable_location)
        self.assertNotEqual(result.artifact, original)
        self.assertEqual(len(port.calls), 1)
        self.assertNotIn("fileId", port.calls[0]["query"])
        self.assertEqual(port.calls[0]["path"], DRIVE_UPLOAD_PATH)

    def test_readonly_grant_cannot_mint_upload(self):
        for b in (
            binding(granted_scopes=("https://www.googleapis.com/auth/drive.readonly",)),
            binding(granted_capabilities=("drive.files.get",)),
            binding(connector_id="gmail"),
            binding(state=ConnectorBindingState.REVOKED, revoked_at=NOW),
            binding(expires_at=NOW - timedelta(minutes=1)),
        ):
            adapter, _, _, _, port = driver(b=b)
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter)
            self.assertFalse(port.calls)

    def test_wrong_actor_workspace_binding_and_create_tool_refused(self):
        variants = [
            dict(intent=intent(actor_ref="actor_other")),
            dict(intent=intent(binding_ref="binding_other")),
            dict(intent=intent(tool_name="update_file")),
            dict(intent=intent(expected_version_ref="drive-version:1")),
            dict(workspace_ref="workspace_other"),
        ]
        for params in variants:
            adapter, _, _, _, port = driver()
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter, **params)
            self.assertFalse(port.calls)

    def test_folder_scope_requires_exact_current_trusted_proof(self):
        for folder in (
            Folder(folder_ref="folder_other"),
            Folder(mime="text/plain"),
            Folder(trashed=True),
            Folder(proof_binding="binding_other"),
        ):
            adapter, _, _, _, port = driver(folders=folder)
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter)
            self.assertFalse(port.calls)
        narrow_scope = DriveScopeProjection(
            binding_ref=BINDING, allowed_folder_ids=("another_allowed_folder",),
        )
        adapter, _, _, _, port = driver(scope=narrow_scope)
        with self.assertRaises(DriveArtifactUploadError):
            deliver(adapter)
        self.assertFalse(port.calls)

    def test_shared_drive_allowed_folder_preserves_supports_all_drives(self):
        folders = Folder()
        folders.item = DriveResourceProof(
            binding_ref=BINDING,
            metadata=DriveFileMetadata(
                file_id=FOLDER, name="Team output",
                mime_type="application/vnd.google-apps.folder",
                version=1, drive_id="shared_drive_one",
            ),
        )
        allowed = DriveScopeProjection(
            binding_ref=BINDING,
            allowed_shared_drive_ids=("shared_drive_one",),
        )
        adapter, _, _, _, port = driver(scope=allowed, folders=folders)
        deliver(adapter)
        self.assertEqual(port.calls[0]["query"]["supportsAllDrives"], "true")

    def test_no_approval_or_missing_material_fails_closed(self):
        for approved in (False, None):
            adapter, _, _, _, provider = driver(approval=Approval(approved))
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter)
            self.assertEqual(len(provider.calls), 0)
        adapter, _, _, _, provider = driver(artifacts=Material(item="not canonical material"))
        with self.assertRaises(DriveArtifactUploadError):
            deliver(adapter)
        self.assertFalse(provider.calls)

    def test_artifact_bytes_tamper_wrong_scope_or_run_refused(self):
        cases = (
            DriveArtifactMaterial(record(), DOC + b"tampered"),
            DriveArtifactMaterial(record(workspace_ref="workspace_other"), DOC),
            DriveArtifactMaterial(record(run_ref="run_other"), DOC),
            DriveArtifactMaterial(record(), b""),
            DriveArtifactMaterial(record(), "not bytes"),
            DriveArtifactMaterial(record(), b"x" * (MAX_UPLOAD_BYTES + 1)),
        )
        for case in cases:
            adapter, _, _, _, provider = driver(artifacts=Material(item=case))
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter)
            self.assertFalse(provider.calls)

    def test_payload_fingerprint_binds_exact_destination_and_artifact(self):
        adapter, _, _, _, provider = driver()
        bad = intent(payload_fingerprint="f" * 64)
        with self.assertRaises(DriveArtifactUploadError):
            deliver(adapter, intent=bad)
        self.assertFalse(provider.calls)
        other = record(filename="another.pdf")
        self.assertNotEqual(
            upload_payload_fingerprint(artifact=other, folder_ref=FOLDER),
            intent().payload_fingerprint,
        )

    def test_repeat_attempt_and_conflicting_idempotency_are_refused(self):
        adapter, _, _, _, port = driver()
        deliver(adapter)
        with self.assertRaisesRegex(DriveArtifactUploadError, "replay"):
            deliver(adapter)
        with self.assertRaisesRegex(DriveArtifactUploadError, "replay"):
            deliver(adapter, intent=intent(approval_ref="another_approval"))
        self.assertEqual(len(port.calls), 1)

    def test_provider_failure_message_and_sensitive_data_not_exposed(self):
        port = Upload(error=OSError("Authorization: Bearer PRIVATE and folder id"))
        adapter, _, _, _, _ = driver(upload=port)
        with self.assertRaises(DriveArtifactUploadError) as ctx:
            deliver(adapter)
        self.assertEqual(str(ctx.exception), "Drive upload provider unavailable or refused")
        self.assertNotIn("PRIVATE", str(ctx.exception))
        self.assertEqual(len(port.calls), 1)
        with self.assertRaisesRegex(DriveArtifactUploadError, "replay"):
            deliver(adapter)
        self.assertEqual(len(port.calls), 1)

    def test_provider_metadata_missing_checksum_wrong_parent_size_or_id_refused(self):
        responses = (
            provider_result(md5Checksum=None),
            provider_result(md5Checksum="f" * 32),
            provider_result(sha256Checksum="f" * 64),
            provider_result(parents=["folder_other"]),
            provider_result(parents=[FOLDER, "extra_folder"]),
            provider_result(mimeType="text/plain"),
            provider_result(name="incorrect.pdf"),
            provider_result(id=FOLDER),
            provider_result(size="999"),
            provider_result(size=None),
            provider_result(version=0),
            provider_result(trashed=True),
        )
        for response in responses:
            adapter, _, _, _, port = driver(upload=Upload(response=response))
            with self.assertRaises(DriveArtifactUploadError):
                deliver(adapter)
            self.assertEqual(len(port.calls), 1)

    def test_provider_response_without_binary_proof_never_claims_success(self):
        adapter, _, _, _, port = driver(upload=Upload(response={}))
        with self.assertRaises(DriveArtifactUploadError):
            deliver(adapter)
        self.assertEqual(len(port.calls), 1)

    def test_scope_and_ports_cannot_be_satisfied_by_untrusted_shape(self):
        with self.assertRaises(DriveArtifactUploadError):
            driver(b=binding(connector_id="other"))
        with self.assertRaises(DriveArtifactUploadError):
            driver(scope=DriveScopeProjection(
                binding_ref="binding_different",
                allowed_folder_ids=(FOLDER,),
            ))
        self.assertTrue(callable(getattr(Upload(), "create_file_multipart", None)))


if __name__ == "__main__":
    unittest.main()
