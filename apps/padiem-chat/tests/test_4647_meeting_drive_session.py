"""Focused owner-scoped Drive upload-session boundary; no provider calls."""
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import meeting_drive_upload_routes as route

ORIGIN = "https://chat.example.test"
SESSION = ("https://www.googleapis.com/upload/drive/v3/files"
           "?uploadType=resumable&upload_id=testsessionABC012345")


def make_request(payload=None, *, origin=ORIGIN, port=None):
    if payload is None:
        payload = {"mime_type": "audio/webm", "byte_size": 52}
    raw = json.dumps(payload).encode()
    state = SimpleNamespace(
        settings=SimpleNamespace(public_base_url=ORIGIN),
        history_store=SimpleNamespace(get_user=lambda user: {"id": user}),
        identity_shadow_store=SimpleNamespace(load_projection=lambda user: SimpleNamespace(auth_session_id="canonical-session")),
        control_plane_identity_authority=SimpleNamespace(resolve_connector_workspace=lambda **_: "workspace_own"),
        meeting_drive_upload_session_port=port,
    )
    scope = {
        "type": "http", "method": "POST", "path": route.MEETING_DRIVE_SESSION_PATH,
        "query_string": b"", "headers": [(b"origin", origin.encode()),
        (b"content-type", b"application/json")],
        "app": SimpleNamespace(state=state),
    }
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request(scope, receive=receive)


@pytest.mark.asyncio
async def test_write_grant_port_absent_is_503_and_never_creates_provider_session(monkeypatch):
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    monkeypatch.setattr(route, "current_user_id", lambda _: "owner_a")
    response = await route.meeting_drive_upload_session(make_request())
    assert response.status_code == 503
    assert b"meeting_drive_write_unavailable" in response.body


@pytest.mark.asyncio
async def test_authenticated_canonical_owner_trusts_host_port_not_browser_scope(monkeypatch):
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    monkeypatch.setattr(route, "current_user_id", lambda _: "owner_a")
    calls = []
    class TrustedPort:
        def begin_authorized_upload(self, **kwargs):
            calls.append(kwargs)
            return {"session_uri": SESSION}
    response = await route.meeting_drive_upload_session(make_request(port=TrustedPort()))
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["session_uri"] == SESSION
    assert len(calls) == 1
    assert calls[0]["owner_id"] == "owner_a"
    assert calls[0]["workspace_ref"] == "workspace_own"
    assert calls[0]["byte_size"] == 52
    assert calls[0]["filename"].startswith("padiem-meeting-")
    assert not any("token" in key or "scope" in key for key in calls[0])
    assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_forbidden_origin_login_and_user_supplied_workspace_rejected(monkeypatch):
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    monkeypatch.setattr(route, "current_user_id", lambda _: "owner_a")
    assert (await route.meeting_drive_upload_session(make_request(origin="https://evil.example"))).status_code == 403
    monkeypatch.setattr(route, "auth_ready", lambda _: False)
    assert (await route.meeting_drive_upload_session(make_request())).status_code == 401
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    illegal = {"mime_type": "audio/webm", "byte_size": 52, "workspace_ref": "other"}
    assert (await route.meeting_drive_upload_session(make_request(payload=illegal))).status_code == 400


@pytest.mark.asyncio
async def test_media_size_and_provider_url_are_bounded(monkeypatch):
    monkeypatch.setattr(route, "auth_ready", lambda _: True)
    monkeypatch.setattr(route, "current_user_id", lambda _: "owner_a")
    class BadPort:
        def begin_authorized_upload(self, **kwargs):
            return {"session_uri": "https://www.googleapis.com.evil.net/upload/drive/v3/files?uploadType=resumable&upload_id=x"}
    request = make_request(port=BadPort())
    assert (await route.meeting_drive_upload_session(request)).status_code == 503
    for payload in ({"mime_type": "audio/webm", "byte_size": -1},
                    {"mime_type": "audio/webm", "byte_size": True},
                    {"mime_type": "audio/webm", "byte_size": 9999999999},
                    {"mime_type": "image/jpeg", "byte_size": 20}):
        assert (await route.meeting_drive_upload_session(make_request(payload=payload))).status_code == 400
