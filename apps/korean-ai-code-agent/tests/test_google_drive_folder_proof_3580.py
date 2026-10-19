"""#3580 Drive folder-proof host port tests.

Hermetic: the "authorized Drive READ" seam is a fake in-memory object and the
upload transport is the existing hermetic double. No Google connection,
credential, provider write or scope grant is exercised.
"""
from __future__ import annotations

import json
import unittest

import test_google_drive_artifact_upload as drive

from kagent.artifact_registration import ArtifactLifecycle
from kagent.contracts import ContractError
from kagent.google_drive_artifact_upload import DriveArtifactUploadError
from kagent.google_drive_folder_proof import (
    AuthorizedDriveFolderProofPort, DRIVE_API_BASE_URL, DriveFolderProofError,
    FOLDER_PROOF_FIELDS, NEW_DRIVE_AUTHORITY, NEW_OAUTH_AUTHORITY,
    NEW_SCOPE_AUTHORITY, PRODUCTION_FOLDER_PROOF_COMPOSED, READ_ONLY_PORT,
)
from kagent.google_drive_scope import DriveScopeProjection

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
PROVIDER_SECRET = "ya29.provider-body-secret-must-not-surface"


def folder_payload(**overrides):
    params = dict(
        id=drive.FOLDER, name="Output", mimeType=FOLDER_MIME,
        version="2", parents=["root_parent"], trashed=False,
    )
    params.update(overrides)
    return params


class FakeDriveReadHttp:
    """Hermetic stand-in for the existing authorized Drive READ seam."""

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else folder_payload()
        self.error = error
        self.calls = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


def port(http=None):
    return AuthorizedDriveFolderProofPort(http=http if http is not None else FakeDriveReadHttp())


def proof(http=None, **overrides):
    params = dict(binding_ref=drive.BINDING, actor_ref=drive.ACTOR,
                  folder_ref=drive.FOLDER)
    params.update(overrides)
    return port(http).resolve_folder_proof(**params)


class DriveFolderProofPortTests(unittest.TestCase):
    def test_port_is_read_only_and_not_production_composed(self):
        self.assertIs(READ_ONLY_PORT, True)
        self.assertIs(NEW_DRIVE_AUTHORITY, False)
        self.assertIs(NEW_OAUTH_AUTHORITY, False)
        self.assertIs(NEW_SCOPE_AUTHORITY, False)
        self.assertIs(PRODUCTION_FOLDER_PROOF_COMPOSED, False)

    def test_constructor_requires_an_authorized_read_port(self):
        with self.assertRaises(DriveFolderProofError):
            AuthorizedDriveFolderProofPort(http=object())

    def test_returns_truthful_proof_for_an_exact_live_folder(self):
        http = FakeDriveReadHttp()
        result = proof(http)
        self.assertIsNotNone(result)
        self.assertEqual(result.binding_ref, drive.BINDING)
        self.assertEqual(result.metadata.file_id, drive.FOLDER)
        self.assertEqual(result.metadata.mime_type, FOLDER_MIME)
        self.assertEqual(result.metadata.version, 2)
        self.assertEqual(result.metadata.parents, ("root_parent",))
        self.assertFalse(result.metadata.trashed)
        # Exactly one bounded read, to the pinned Drive origin and path.
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["binding_ref"], drive.BINDING)
        self.assertEqual(call["actor_ref"], drive.ACTOR)
        self.assertEqual(call["base_url"], DRIVE_API_BASE_URL)
        self.assertEqual(call["path"], "/files/" + drive.FOLDER)
        self.assertEqual(call["query"]["fields"], FOLDER_PROOF_FIELDS)
        self.assertEqual(call["query"]["supportsAllDrives"], "true")
        self.assertEqual(call["timeout_seconds"], 30)

    def test_non_folder_mime_is_refused(self):
        self.assertIsNone(proof(FakeDriveReadHttp(folder_payload(mimeType="application/pdf"))))

    def test_shortcut_is_refused_even_when_it_points_at_a_folder(self):
        payload = folder_payload(
            mimeType=SHORTCUT_MIME,
            shortcutDetails={"targetId": "folder_target", "targetMimeType": FOLDER_MIME},
        )
        self.assertIsNone(proof(FakeDriveReadHttp(payload)))

    def test_trashed_folder_is_refused(self):
        self.assertIsNone(proof(FakeDriveReadHttp(folder_payload(trashed=True))))

    def test_id_mismatch_is_refused(self):
        self.assertIsNone(proof(FakeDriveReadHttp(folder_payload(id="some_other_folder"))))

    def test_provider_failure_returns_none_without_leaking_provider_text(self):
        result = proof(FakeDriveReadHttp(error=ContractError(PROVIDER_SECRET)))
        self.assertIsNone(result)
        self.assertNotIn(PROVIDER_SECRET, repr(result))

    def test_untrusted_references_are_refused_before_any_provider_call(self):
        for overrides in (
            {"binding_ref": ""},
            {"actor_ref": "  "},
            {"folder_ref": "folder/child"},
            {"folder_ref": "a" * 600},
        ):
            http = FakeDriveReadHttp()
            self.assertIsNone(proof(http, **overrides))
            self.assertEqual(http.calls, [])

    def test_real_port_drives_existing_adapter_to_durable_artifact(self):
        http = FakeDriveReadHttp()
        adapter, _, folders, approval, upload = drive.driver(
            folders=AuthorizedDriveFolderProofPort(http=http)
        )
        result = drive.deliver(adapter)
        self.assertEqual(result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(result.artifact.durable_location.location_ref, "file_uploaded_123")
        self.assertEqual(result.receipt.connector_id, "google-drive")
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(len(upload.calls), 1)
        self.assertEqual(len(approval.calls), 1)

    def test_truthful_proof_is_still_refused_when_out_of_scope(self):
        # The port proves the folder; it never authorizes it. The upload adapter
        # keeps the scope decision, so an allowed-but-other folder still fails.
        http = FakeDriveReadHttp()
        adapter, _, _, _, upload = drive.driver(
            folders=AuthorizedDriveFolderProofPort(http=http),
            scope=DriveScopeProjection(
                binding_ref=drive.BINDING, allowed_folder_ids=("folder_other",),
            ),
        )
        with self.assertRaises(DriveArtifactUploadError):
            drive.deliver(adapter)
        self.assertEqual(upload.calls, [])

    def test_projection_carries_no_provider_secret(self):
        result = proof()
        rendered = json.dumps(result.metadata.safe_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(PROVIDER_SECRET, rendered)
        self.assertFalse(result.metadata.safe_dict()["content_trusted"])


if __name__ == "__main__":
    unittest.main()
