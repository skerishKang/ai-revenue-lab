"""#4647 Drive upload-session adapter: the seam a real CP/Engine producer plugs into.

Proves three things without any provider call: the unconfigured state still answers the
documented fail-closed 503, a properly configured producer answers 200 through the real
route, and no provider error text, token or grant material can cross the boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import meeting_drive_upload_routes as route
from app.meeting_drive_session_adapter import (
    MeetingDriveSessionAdapter, MeetingDriveSessionUnavailable,
)

ORIGIN = "https://chat.example.test"
SESSION = ("https://www.googleapis.com/upload/drive/v3/files"
           "?uploadType=resumable&upload_id=adaptersession000001")


class RecordingClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = SESSION if result is None else result
        self.error = error

    def start_resumable_session(self, **scope):
        self.calls.append(scope)
        if self.error is not None:
            raise self.error
        if isinstance(self.result, str) and self.result == SESSION:
            return {"session_uri": self.result}
        return self.result


def make_request(port, *, payload=None):
    raw = json.dumps(payload or {"mime_type": "audio/webm", "byte_size": 52}).encode()
    state = SimpleNamespace(
        settings=SimpleNamespace(public_base_url=ORIGIN),
        history_store=SimpleNamespace(get_user=lambda user: {"id": user}),
        identity_shadow_store=SimpleNamespace(
            load_projection=lambda user: SimpleNamespace(auth_session_id="canonical-session")),
        control_plane_identity_authority=SimpleNamespace(
            resolve_connector_workspace=lambda **_: "workspace_own"),
        meeting_drive_upload_session_port=port,
    )
    scope = {"type": "http", "method": "POST", "path": route.MEETING_DRIVE_SESSION_PATH,
             "query_string": b"", "app": SimpleNamespace(state=state),
             "headers": [(b"origin", ORIGIN.encode()),
                         (b"content-type", b"application/json")]}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request(scope, receive=receive)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    monkeypatch.setattr(route, "current_user_id", lambda _: "owner_a")


def test_adapter_requires_the_documented_client_method():
    for unusable in (None, object(), SimpleNamespace(),
                     SimpleNamespace(start_resumable_session="not-callable")):
        with pytest.raises((ValueError, TypeError)):
            MeetingDriveSessionAdapter(unusable)


@pytest.mark.asyncio
async def test_configured_producer_answers_through_the_real_route():
    client = RecordingClient()
    response = await route.meeting_drive_upload_session(
        make_request(MeetingDriveSessionAdapter(client)))
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["session_uri"] == SESSION
    assert len(client.calls) == 1
    assert client.calls[0]["owner_id"] == "owner_a"
    assert client.calls[0]["workspace_ref"] == "workspace_own"
    assert client.calls[0]["mime_type"] == "audio/webm"
    assert client.calls[0]["byte_size"] == 52
    assert client.calls[0]["filename"].startswith("padiem-meeting-")
    assert not any(word in key.lower() for key in client.calls[0]
                   for word in ("token", "scope", "credential", "refresh"))
    assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_unconfigured_and_refusing_producers_stay_fail_closed_503():
    assert (await route.meeting_drive_upload_session(
        make_request(None))).status_code == 503
    refused = RecordingClient(error=RuntimeError(
        "REFRESH_TOKEN=secret-value quota exceeded for project-123"))
    response = await route.meeting_drive_upload_session(
        make_request(MeetingDriveSessionAdapter(refused)))
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "meeting_drive_write_unavailable"
    assert "secret-value" not in response.body.decode()
    assert "project-123" not in response.body.decode()
    assert "REFRESH_TOKEN" not in response.body.decode()


@pytest.mark.asyncio
async def test_adapter_never_calls_the_producer_for_inputs_it_cannot_trust():
    for payload in ({"mime_type": "image/jpeg", "byte_size": 52},
                    {"mime_type": "audio/webm", "byte_size": 0},
                    {"mime_type": "audio/webm", "byte_size": 188743681}):
        client = RecordingClient()
        response = await route.meeting_drive_upload_session(
            make_request(MeetingDriveSessionAdapter(client), payload=payload))
        assert response.status_code == 400, payload
        assert client.calls == []


class MalformedClient:
    """A producer that answers with something other than the one required field."""

    def __init__(self, value):
        self.value = value

    def start_resumable_session(self, **scope):
        return self.value


@pytest.mark.asyncio
async def test_adapter_accepts_only_the_single_session_field_from_the_producer():
    for unusable in ({}, {"session_uri": ""}, {"session_uri": None},
                     {"upload_url": SESSION}, "not-a-dict", None, 7):
        with pytest.raises(MeetingDriveSessionUnavailable):
            await MeetingDriveSessionAdapter(MalformedClient(unusable)).begin_authorized_upload(
                owner_id="owner_a", workspace_ref="workspace_own",
                filename="padiem-meeting.webm", mime_type="audio/webm", byte_size=52)
        response = await route.meeting_drive_upload_session(
            make_request(MeetingDriveSessionAdapter(MalformedClient(unusable))))
        assert response.status_code == 503


@pytest.mark.asyncio
async def test_adapter_rejects_a_path_shaped_or_foreign_scope_before_dispatch():
    adapter = MeetingDriveSessionAdapter(RecordingClient())
    for bad in ({"owner_id": "", "workspace_ref": "ws", "filename": "a.webm"},
                {"owner_id": "owner_a", "workspace_ref": "", "filename": "a.webm"},
                {"owner_id": "owner_a", "workspace_ref": "ws", "filename": "../secret"},
                {"owner_id": "owner_a", "workspace_ref": "ws", "filename": "a\\\\b.webm"}):
        with pytest.raises(MeetingDriveSessionUnavailable):
            await adapter.begin_authorized_upload(
                mime_type="audio/webm", byte_size=52, **bad)


def test_adapter_module_does_not_hold_credentials_or_a_second_media_table():
    source = (Path(__file__).resolve().parents[1] / "app"
              / "meeting_drive_session_adapter.py").read_text(encoding="utf-8")
    assert "_MEDIA_TYPES" in source  # reuses the route's single vocabulary
    assert "from .meeting_drive_upload_routes import _MEDIA_TYPES" in source
    for secret_word in ("refresh_token", "client_secret", "Bearer ", "API_KEY"):
        assert secret_word not in source
