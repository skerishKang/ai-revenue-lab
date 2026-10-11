"""#3580 Drive WRITE composition root tests.

Hermetic: the "real" Drive multipart port is driven by a fake token authority
and a fake HTTPS transport. No Google credential, network call or provider
mutation happens, and no Drive WRITE grant is claimed.
"""
from __future__ import annotations

import json
import unittest

import test_google_drive_artifact_upload as drive

from kagent.artifact_registration import ArtifactLifecycle
from kagent.google_drive_artifact_upload import DriveArtifactUploadError
from kagent.google_drive_multipart_transport import (
    StdlibGoogleDriveMultipartCreatePort, UnconfiguredDriveAuthorizedWriteTokenPort,
)
from kagent.google_drive_scope import DriveScopeProjection
from kagent.google_drive_upload_composition import (
    DRIVE_UPLOAD_COMPOSITION_CONTRACT_VERSION,
    DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS,
    DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS,
    DRIVE_UPLOAD_COMPOSITION_PARAMETERS, GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED,
    DriveUploadCompositionError, GoogleDriveUploadComposition,
    build_google_drive_upload_composition,
)
from kagent.google_oauth_authority import (
    GoogleProviderHttpResponse, StdlibGoogleProviderNetwork,
)

TEST_TOKEN = "ya29.local-composition-token-no-live-call"


class Authorized:
    def __init__(self, token=TEST_TOKEN, error=None):
        self.token, self.error, self.calls = token, error, []

    def resolve_write_access_token(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.token


class FakeNetwork:
    def __init__(self, status=200, body=None, error=None):
        self.status = status
        self.body = (
            json.dumps(drive.provider_result(), ensure_ascii=False).encode("utf-8")
            if body is None else body
        )
        self.error = error
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return GoogleProviderHttpResponse(self.status, self.body)


def composition(*, auth=None, network=None):
    """Build the composition root with the given doubles; both default to fakes."""
    return build_google_drive_upload_composition(
        authorization=auth if auth is not None else Authorized(),
        network=network if network is not None else FakeNetwork(),
    )


def scope():
    return DriveScopeProjection(binding_ref=drive.BINDING,
                                allowed_folder_ids=(drive.FOLDER,))


class DriveUploadCompositionTests(unittest.TestCase):
    def test_composition_root_is_wired_but_stays_unarmed(self):
        self.assertIs(GOOGLE_DRIVE_UPLOAD_COMPOSITION_ROOT_WIRED, True)
        built = composition()
        self.assertIs(built.armed, False)
        projection = built.safe_dict()
        self.assertEqual(projection["contract_version"],
                         DRIVE_UPLOAD_COMPOSITION_CONTRACT_VERSION)
        self.assertIs(projection["armed"], False)
        self.assertIs(projection["production_claim"], False)
        self.assertIs(projection["drive_write_grant_authorized"], False)
        self.assertIs(projection["live_drive_upload_canary"], False)
        self.assertEqual(projection["production_activation"], "BLOCKED")
        self.assertTrue(built.blocked_reasons)

    def test_blocked_reasons_name_the_actual_remaining_authority_gaps(self):
        built = composition()
        reasons = " ".join(built.blocked_reasons)
        self.assertIn("WRITE grant is not authorized", reasons)
        self.assertIn("canary", reasons)
        self.assertNotIn("token authority was supplied", reasons)

        unconfigured = build_google_drive_upload_composition(network=FakeNetwork())
        self.assertTrue(unconfigured.token_authority_unconfigured)
        self.assertIn("token authority was supplied",
                      " ".join(unconfigured.blocked_reasons))

    def test_construction_performs_no_provider_request_and_resolves_no_token(self):
        auth, network = Authorized(), FakeNetwork()
        build_google_drive_upload_composition(authorization=auth, network=network)
        self.assertEqual(network.calls, [])
        self.assertEqual(auth.calls, [])
        self.assertEqual(DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS, 0)
        self.assertEqual(DRIVE_UPLOAD_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS, 0)

    def test_default_network_is_the_canonical_stdlib_google_transport(self):
        built = build_google_drive_upload_composition()
        self.assertIsInstance(built.network, StdlibGoogleProviderNetwork)
        self.assertIsInstance(built.upload_port, StdlibGoogleDriveMultipartCreatePort)
        self.assertIsInstance(built.authorization,
                              UnconfiguredDriveAuthorizedWriteTokenPort)

    def test_composed_real_port_drives_existing_adapter_to_durable_artifact(self):
        auth, network = Authorized(), FakeNetwork()
        built = composition(auth=auth, network=network)
        adapter = built.uploader(
            binding=drive.binding(), scope=scope(),
            artifacts=drive.Material(), folders=drive.Folder(),
            approval=drive.Approval(),
        )
        result = drive.deliver(adapter)
        self.assertEqual(result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(result.artifact.durable_location.location_kind, "google_drive")
        self.assertEqual(result.artifact.integrity_ref, drive.SHA)
        # Exactly one physical provider attempt, to the pinned upload origin.
        self.assertEqual(len(network.calls), 1)
        call = network.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].startswith(
            "https://www.googleapis.com/upload/drive/v3/files?"))
        self.assertEqual(call["headers"]["authorization"], "Bearer " + TEST_TOKEN)
        self.assertEqual(auth.calls, [{
            "binding_ref": drive.BINDING,
            "actor_ref": drive.ACTOR,
            "capability": "drive.files.create",
        }])

    def test_uploader_binds_the_canonical_composed_port_only(self):
        built = composition()
        adapter = built.uploader(
            binding=drive.binding(), scope=scope(),
            artifacts=drive.Material(), folders=drive.Folder(),
            approval=drive.Approval(),
        )
        self.assertIs(adapter._upload, built.upload_port)
        with self.assertRaises(DriveUploadCompositionError):
            GoogleDriveUploadComposition(
                authorization=Authorized(), network=FakeNetwork(),
                upload_port=drive.Upload(),
            )

    def test_unconfigured_token_authority_fails_closed_before_any_socket(self):
        network = FakeNetwork()
        built = build_google_drive_upload_composition(network=network)
        adapter = built.uploader(
            binding=drive.binding(), scope=scope(),
            artifacts=drive.Material(), folders=drive.Folder(),
            approval=drive.Approval(),
        )
        with self.assertRaises(DriveArtifactUploadError):
            drive.deliver(adapter)
        self.assertEqual(network.calls, [])

    def test_look_alike_ports_are_refused(self):
        with self.assertRaises(DriveUploadCompositionError):
            build_google_drive_upload_composition(authorization=object())
        with self.assertRaises(DriveUploadCompositionError):
            build_google_drive_upload_composition(network=object())

    def test_projection_leaks_no_token_folder_or_artifact_bytes(self):
        built = composition()
        projection = built.safe_dict()
        rendered = json.dumps(projection, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TEST_TOKEN, rendered)
        self.assertNotIn(drive.FOLDER, rendered)
        self.assertNotIn(drive.DOC.decode(), rendered)
        self.assertEqual(projection["upload_endpoint_origin"],
                         "https://www.googleapis.com")
        self.assertEqual(projection["upload_port"],
                         "StdlibGoogleDriveMultipartCreatePort")

    def test_parameters_surface_is_pinned_as_data(self):
        self.assertEqual(DRIVE_UPLOAD_COMPOSITION_PARAMETERS,
                         ("authorization", "network"))


if __name__ == "__main__":
    unittest.main()
