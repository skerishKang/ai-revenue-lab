"""#3580 real Google HTTPS WRITE port with hermetic network and CP lease doubles.

No Google connection or credential is activated in these tests.
"""
from __future__ import annotations

import json
import unittest

import test_google_drive_artifact_upload as drive

from kagent.contracts import ContractError
from kagent.google_drive_artifact_upload import DRIVE_UPLOAD_QUERY, DRIVE_UPLOAD_PATH
from kagent.google_drive_multipart_transport import (
    StdlibGoogleDriveMultipartCreatePort, PRODUCTION_DRIVE_WRITE_PORT_COMPOSED,
    NEW_GOOGLE_OAUTH_AUTHORITY, LIVE_PROVIDER_CANARY, AUTO_RETRY,
    MAX_DRIVE_RECEIPT_BYTES, UnconfiguredDriveAuthorizedWriteTokenPort,
)
from kagent.google_oauth_authority import GoogleProviderHttpResponse

TEST_TOKEN = "ya29.local-test-token-no-live-call"


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


def service(*, auth=None, network=None):
    authorization = auth if auth is not None else Authorized()
    transport = network if network is not None else FakeNetwork()
    return (
        StdlibGoogleDriveMultipartCreatePort(
            authorization=authorization, network=transport,
        ),
        authorization,
        transport,
    )


def valid_call(port):
    return dict(
        binding_ref=drive.BINDING, actor_ref=drive.ACTOR,
        path=DRIVE_UPLOAD_PATH, query=dict(DRIVE_UPLOAD_QUERY),
        body=b"--padiem" + b"a" * 32
             + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{}\r\n"
             + b"--padiem" + b"a" * 32 + b"--\r\n",
        content_type="multipart/related; boundary=padiem" + "a" * 32,
        timeout_seconds=30,
    )


class GoogleDriveMultipartTransportTests(unittest.TestCase):
    def test_source_only_no_connector_write_activation(self):
        self.assertFalse(PRODUCTION_DRIVE_WRITE_PORT_COMPOSED)
        self.assertFalse(NEW_GOOGLE_OAUTH_AUTHORITY)
        self.assertFalse(LIVE_PROVIDER_CANARY)
        self.assertFalse(AUTO_RETRY)

    def test_full_artifact_to_real_http_port_fake_network_with_exact_checksum(self):
        port, authority, network = service()
        adapter, _, _, approval, _ = drive.driver(upload=port)
        result = drive.deliver(adapter)
        self.assertEqual(result.artifact.integrity_ref, drive.SHA)
        self.assertEqual(len(approval.calls), 1)
        self.assertEqual(authority.calls, [{
            "binding_ref": drive.BINDING,
            "actor_ref": drive.ACTOR,
            "capability": "drive.files.create",
        }])
        self.assertEqual(len(network.calls), 1)
        call = network.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].startswith("https://www.googleapis.com/upload/drive/v3/files?"))
        self.assertIn("supportsAllDrives=true", call["url"])
        self.assertIn("uploadType=multipart", call["url"])
        self.assertEqual(call["headers"]["authorization"], "Bearer " + TEST_TOKEN)
        self.assertEqual(call["headers"]["content-length"], str(len(call["body"])))
        self.assertEqual(call["max_response_bytes"], MAX_DRIVE_RECEIPT_BYTES)
        self.assertEqual(call["body"].count(drive.DOC), 1)
        self.assertNotIn(TEST_TOKEN, str(result.public_projection()))
        self.assertNotIn(drive.FOLDER, str(result.public_projection()))

    def test_unconfigured_port_fails_closed_without_network_request(self):
        network = FakeNetwork()
        port = StdlibGoogleDriveMultipartCreatePort(network=network)
        self.assertIsInstance(port._authorization, UnconfiguredDriveAuthorizedWriteTokenPort)
        with self.assertRaisesRegex(ContractError, "WRITE access unavailable"):
            port.create_file_multipart(**valid_call(port))
        self.assertEqual(network.calls, [])

    def test_read_grant_revoked_approval_denied_before_token(self):
        for options in (
            {"b": drive.binding(granted_scopes=("https://www.googleapis.com/auth/drive.readonly",))},
            {"b": drive.binding(granted_capabilities=("drive.files.get",))},
            {"approval": drive.Approval(False)},
        ):
            with self.subTest(options=tuple(options)):
                port, auth, net = service()
                adapter, *_ = drive.driver(upload=port, **options)
                with self.assertRaises(ContractError):
                    drive.deliver(adapter)
                self.assertEqual(auth.calls, [])
                self.assertEqual(net.calls, [])

    def test_arbitrary_url_query_extra_fields_and_timeout_refused_pre_auth(self):
        variants = [
            {"path": "/upload/drive/v3/files/other"},
            {"query": {**DRIVE_UPLOAD_QUERY, "fileId": "overwrite"}},
            {"query": {**DRIVE_UPLOAD_QUERY, "uploadType": "resumable"}},
            {"timeout_seconds": 60},
            {"timeout_seconds": True},
            {"content_type": "multipart/related; boundary=evil"},
            {"body": b"wrong"},
            {"binding_ref": ""},
            {"actor_ref": "bad newline\n"},
        ]
        for variant in variants:
            with self.subTest(variant=tuple(variant)):
                port, auth, net = service()
                call = valid_call(port)
                call.update(variant)
                with self.assertRaises(ContractError):
                    port.create_file_multipart(**call)
                self.assertEqual(auth.calls, [])
                self.assertEqual(net.calls, [])

    def test_broken_write_lease_token_never_becomes_network_call(self):
        for token in ("", "short", "bearer\nsecret-leak-value", "x" * 9000, 42, None):
            port, auth, network = service(auth=Authorized(token=token))
            with self.subTest(kind=type(token).__name__), self.assertRaises(ContractError):
                port.create_file_multipart(**valid_call(port))
            self.assertEqual(network.calls, [])

    def test_credential_resolver_error_sanitized(self):
        port, _, network = service(auth=Authorized(error=RuntimeError("SUPER_SECRET_CANARY")))
        with self.assertRaises(ContractError) as caught:
            port.create_file_multipart(**valid_call(port))
        self.assertNotIn("SUPER_SECRET_CANARY", str(caught.exception))
        self.assertEqual(network.calls, [])

    def test_network_errors_are_secret_free_and_never_retried(self):
        port, _, network = service(network=FakeNetwork(error=OSError(TEST_TOKEN + " leaked?")))
        with self.assertRaises(ContractError) as caught:
            port.create_file_multipart(**valid_call(port))
        self.assertNotIn(TEST_TOKEN, str(caught.exception))
        self.assertEqual(len(network.calls), 1)

    def test_redirect_authentication_fail_and_malformed_provider_receipt_denied(self):
        cases = [
            (302, b'{"id":"MALICIOUS"}'),
            (401, b'{"token":"SUPER_SECRET_CANARY"}'),
            (200, b"not JSON"),
            (200, b"[]"),
            (200, b"{}" + b"x" * MAX_DRIVE_RECEIPT_BYTES),
        ]
        for status, body in cases:
            port, _, network = service(network=FakeNetwork(status=status, body=body))
            with self.subTest(status=status, bytes=len(body)), self.assertRaises(ContractError) as caught:
                port.create_file_multipart(**valid_call(port))
            self.assertNotIn("SUPER_SECRET_CANARY", str(caught.exception))
            self.assertEqual(len(network.calls), 1)

    def test_success_http_receipt_without_checksum_is_rejected_by_existing_adapter(self):
        fake = FakeNetwork(body=json.dumps({"id": "file_uploaded_123"}).encode("utf-8"))
        port, _, _ = service(network=fake)
        adapter, *_ = drive.driver(upload=port)
        with self.assertRaises(ContractError):
            drive.deliver(adapter)
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
