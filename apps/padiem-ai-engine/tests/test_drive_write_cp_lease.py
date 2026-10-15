"""#4871 Engine full-Drive CP lease create, provider zero-call / one-call tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib

import httpx
import pytest

from app.drive_write_cp_lease import (
    ControlPlaneLeaseDriveCreatePort,
    DriveCreateReceipt,
    VerifiedDriveCreateApproval,
    MAX_UPLOAD_BYTES,
)
from app.google_oauth_access_lease import EngineGoogleOAuthAccessLease
from padiem_ai_core.drive_capability import DRIVE_FULL_SCOPE, DRIVE_READONLY_SCOPE
from padiem_ai_core.tool_runtime import ToolHandlerError


BINDING = "binding_1"
ACTOR = "actor_1"
WORKSPACE = "workspace_1"
FOLDER = "folder_1"
FILENAME = "report.pdf"
MIME = "application/pdf"
DATA = b"%PDF-1.7 test artifact"


def run(coro):
    return asyncio.run(coro)


class FakeCP:
    def __init__(self, scopes=(DRIVE_FULL_SCOPE,), *, actor=ACTOR, workspace=WORKSPACE, binding=BINDING):
        self.scopes = scopes
        self.actor = actor
        self.workspace = workspace
        self.binding = binding
        self.calls = []

    async def issue_access_lease(self, *, binding_ref, connector_id):
        self.calls.append((binding_ref, connector_id))
        return EngineGoogleOAuthAccessLease(
            access_token="test-server-issued-token",
            binding_ref=self.binding, connector_id="google-drive",
            actor_ref=self.actor, account_ref="account_1",
            workspace_ref=self.workspace, scopes=self.scopes,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )


class FakeAuthority:
    def __init__(self, *, mutate=None, denied=False):
        self.mutate = mutate
        self.denied = denied
        self.calls = []

    async def verify_create(self, **kw):
        self.calls.append(dict(kw))
        if self.denied:
            return None
        if self.mutate:
            kw.update(self.mutate)
        return VerifiedDriveCreateApproval(**kw)


def valid_provider(request):
    return httpx.Response(200, json={
        "id": "file_123", "name": FILENAME, "mimeType": MIME, "parents": [FOLDER]
    })


def construct(*, cp=None, auth=None, handler=valid_provider, calls=None):
    cp = cp if cp is not None else FakeCP()
    auth = auth if auth is not None else FakeAuthority()

    def provider(request):
        if calls is not None:
            calls.append(request)
        return handler(request)

    return ControlPlaneLeaseDriveCreatePort(
        lease_client=cp, authorization=auth,
        transport=httpx.MockTransport(provider),
    ), cp, auth


def create(port, **overrides):
    kw = {
        "binding_ref": BINDING, "actor_ref": ACTOR,
        "workspace_ref": WORKSPACE, "folder_id": FOLDER,
        "filename": FILENAME, "mime_type": MIME, "content": DATA,
    }
    kw.update(overrides)
    return run(port.create_file(**kw))


def code_of(port, **overrides):
    with pytest.raises(ToolHandlerError) as error:
        create(port, **overrides)
    return error.value.code


def test_full_cp_lease_and_exact_approval_produce_one_real_mock_drive_post():
    requests = []
    port, cp, auth = construct(calls=requests)
    receipt = create(port)
    assert isinstance(receipt, DriveCreateReceipt)
    assert receipt.file_id == "file_123"
    assert receipt.source_sha256 == hashlib.sha256(DATA).hexdigest()
    assert "test-server-issued-token" not in repr(receipt)
    assert "test-server-issued-token" not in repr(receipt.safe_dict())
    assert cp.calls == [(BINDING, "google-drive")]
    assert len(auth.calls) == len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.host == "www.googleapis.com"
    assert requests[0].url.path == "/upload/drive/v3/files"
    assert requests[0].url.params["uploadType"] == "multipart"
    assert requests[0].headers["Authorization"] == "Bearer test-server-issued-token"
    assert requests[0].headers["Content-Type"].startswith("multipart/related; boundary=padiem")
    assert DATA in requests[0].content
    assert b'"parents":["folder_1"]' in requests[0].content


def test_legacy_readonly_cp_lease_never_calls_google_provider():
    requests = []
    port, cp, auth = construct(cp=FakeCP(scopes=(DRIVE_READONLY_SCOPE,)), calls=requests)
    assert code_of(port) == "google_drive_write_lease_mismatch"
    assert len(auth.calls) == 1
    assert len(cp.calls) == 1
    assert requests == []


@pytest.mark.parametrize("changed", [
    {"actor": "actor_other"}, {"workspace": "workspace_other"},
    {"binding": "binding_other"},
])
def test_mismatched_cp_actor_workspace_or_binding_blocks_provider(changed):
    requests = []
    port, cp, _ = construct(cp=FakeCP(**changed), calls=requests)
    assert code_of(port) == "google_drive_write_lease_mismatch"
    assert len(cp.calls) == 1
    assert requests == []


def test_missing_approval_blocks_lease_and_provider():
    requests = []
    port, cp, auth = construct(auth=FakeAuthority(denied=True), calls=requests)
    assert code_of(port) == "google_drive_write_approval_mismatch"
    assert len(auth.calls) == 1
    assert cp.calls == requests == []


@pytest.mark.parametrize("mismatch", [
    {"actor_ref": "other_actor"},
    {"folder_id": "foreign_folder"},
    {"sha256": "0" * 64},
    {"capability": "drive.files.delete"},
])
def test_modified_host_approval_proof_blocks_lease_and_provider(mismatch):
    requests = []
    port, cp, _ = construct(auth=FakeAuthority(mutate=mismatch), calls=requests)
    assert code_of(port) == "google_drive_write_approval_mismatch"
    assert cp.calls == requests == []


@pytest.mark.parametrize("invalid", [
    {"content": b""},
    {"content": b"x" * (MAX_UPLOAD_BYTES + 1)},
    {"filename": "invalid\nname"},
    {"mime_type": "application/pdf\r\nAuthorization: fake"},
    {"folder_id": "bad folder"},
])
def test_bad_material_and_destination_block_before_approval_and_lease(invalid):
    calls = []
    port, cp, auth = construct(calls=calls)
    assert code_of(port, **invalid).startswith("google_drive_write_")
    assert cp.calls == auth.calls == calls == []


def test_no_authority_does_not_construct_transport():
    with pytest.raises(ValueError, match="authorization"):
        ControlPlaneLeaseDriveCreatePort(lease_client=FakeCP(), authorization=None)


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_non_success_is_single_provider_post_without_retry(status):
    requests = []
    port, cp, _ = construct(
        handler=lambda _: httpx.Response(status, headers={"Location": "https://evil.example/path"}),
        calls=requests,
    )
    assert code_of(port) == "google_drive_write_provider_rejected"
    assert len(requests) == len(cp.calls) == 1
    assert requests[0].url.host == "www.googleapis.com"


@pytest.mark.parametrize("payload", [
    {"id": "file_123", "name": FILENAME, "mimeType": MIME, "parents": ["foreign"]},
    {"id": "file_123", "name": "other.pdf", "mimeType": MIME, "parents": [FOLDER]},
    {"id": "file_123", "name": FILENAME, "mimeType": "text/plain", "parents": [FOLDER]},
    {"id": "", "name": FILENAME, "mimeType": MIME, "parents": [FOLDER]},
])
def test_mismatched_provider_receipt_never_claims_success(payload):
    requests = []
    port, _, _ = construct(handler=lambda _: httpx.Response(200, json=payload), calls=requests)
    assert code_of(port) == "google_drive_write_receipt_mismatch"
    assert len(requests) == 1


def test_provider_body_oversize_or_invalid_json_does_not_claim_success():
    for response in [httpx.Response(200, content=b"x" * 65_537), httpx.Response(200, content=b"not-json")]:
        requests = []
        port, _, _ = construct(handler=lambda _, response=response: response, calls=requests)
        assert code_of(port) == "google_drive_write_receipt_invalid"
        assert len(requests) == 1


def test_secret_provider_exception_is_not_returned_to_caller():
    def broken(request):
        raise httpx.ConnectError("secret provider internal network token", request=request)
    port, _, _ = construct(handler=broken)
    with pytest.raises(ToolHandlerError) as error:
        create(port)
    assert error.value.code == "google_drive_write_provider_unavailable"
    assert "secret" not in error.value.safe_message.lower()
