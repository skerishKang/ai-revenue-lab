"""B66 #4089 host wiring: signed owner, canonical context and private OAuth RPCs."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from app.auth import SESSION_COOKIE
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.main import create_app

from test_google_connector_ticket_bridge import (
    NOW,
    MemoryHistoryStore,
    MemoryShadowStore,
    cookie_for,
    settings,
    shadow,
)


OWNER = "usr_" + "a" * 32
CONNECTOR_ID = "b66-google-drive-file"


class FakeControlPlaneBinding:
    def __init__(self) -> None:
        self.ticket_calls: list[dict] = []

    async def resolve_auth_session(self, payload):
        from datetime import datetime, timedelta, timezone

        from padiem_control_plane import AuthSessionSnapshot, AuthSessionState, CanonicalSubjectRef, SubjectType

        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "ok": True,
            "session": {
                "session_id": payload["session_id"],
                "product_id": "b62",
                "subject": {"subject_type": "user", "subject_id": "sub_test"},
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "state": "active",
                "revision": 1,
            },
        }

    async def resolve_product_user_for_subject(self, payload):
        return {"ok": True, "product_user": {"product_user_id": OWNER}}

    async def resolve_connector_context(self, payload):
        return {
            "ok": True,
            "context": {
                "present": True,
                "product_id": "b62",
                "subject_id": "sub_test",
                "actor_ref": "actor_a",
                "workspace_ref": "workspace_a",
            },
        }

    async def issue_google_connect_ticket(self, payload):
        self.ticket_calls.append(dict(payload))
        if payload["connector_id"] != CONNECTOR_ID:
            return {"ok": False, "error": {"code": "connector_not_reviewed", "message": "rejected"}}
        return {
            "ok": True,
            "ticket": {
                "connect_ticket": "private-b66-connect-ticket",
                "connector_id": CONNECTOR_ID,
                "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
            },
        }


def connection_receipt(*, provider_subject="google-sub-12345678", provider_email="owner@drive.test"):
    return {
        "binding_ref": "binding_a",
        "connector_id": CONNECTOR_ID,
        "actor_ref": "actor_a",
        "account_ref": "account_a",
        "workspace_ref": "workspace_a",
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
        "connected_at": NOW.isoformat(),
        "expires_at": None,
        "refresh_token_persisted_sealed": True,
        "access_token_discarded": True,
        "raw_authorization_code": False,
        "raw_access_token": False,
        "raw_refresh_token": False,
        "raw_client_secret": False,
        "verified_destination_subject": provider_subject,
        "verified_destination_account": provider_email or provider_subject,
    }


class FakeGoogleOAuthBinding:
    def __init__(self) -> None:
        self.begin_calls: list[dict] = []
        self.callback_calls: list[dict] = []
        self.revoked: list[dict] = []
        self.status = "resolved"

    async def begin_connect(self, payload):
        self.begin_calls.append(dict(payload))
        return {
            "ok": True,
            "authorization": {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?state=state-a",
                "connector_id": CONNECTOR_ID,
                "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
            },
        }

    async def complete_callback(self, payload):
        self.callback_calls.append(dict(payload))
        return {"ok": True, "connection": connection_receipt()}

    async def select_b66_drive_binding(self, payload):
        del payload
        if self.status == "resolved":
            return {
                "ok": True,
                "selection": {
                    "status": "resolved",
                    "connector_id": CONNECTOR_ID,
                    "workspace_ref": "workspace_a",
                    "binding_ref": "binding_a",
                    "actor_ref": "actor_a",
                    "provider_subject": "google-sub-12345678",
                    "provider_email": "owner@drive.test",
                },
            }
        return {
            "ok": True,
            "selection": {
                "status": self.status,
                "connector_id": CONNECTOR_ID,
                "workspace_ref": "workspace_a",
            },
        }

    async def disconnect_b66_drive(self, payload):
        self.revoked.append(dict(payload))
        self.status = "not_connected"
        return {"ok": True, "revoked": True}


def app_fixture():
    history = MemoryHistoryStore()
    history.profile = replace(history.profile, id=OWNER)
    shadow_store = MemoryShadowStore(shadow(OWNER))
    binding = FakeControlPlaneBinding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    google_binding = FakeGoogleOAuthBinding()
    app = create_app(
        settings(),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow_store,
    )
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(google_binding)
    return app, history, binding, google_binding


@pytest.mark.asyncio
async def test_b66_drive_status_reads_only_signed_owners_verified_cp_binding():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.get(
            "/api/b66/drive/status",
            headers={"Origin": "https://chat.example.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"]["status"] == "connected"
    assert body["status"]["verified_store_owner"] == OWNER
    assert body["status"]["destination_account"] == "owner@drive.test"
    assert body["status"]["destination_sub"] == "google-sub-12345678"
    assert body["status"]["durable_credential_backend"] == "CP_SEALED_DURABLE_OAUTH"
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert google.begin_calls == []


@pytest.mark.asyncio
async def test_b66_drive_connect_uses_server_issued_b66_file_ticket_only():
    app, history, binding, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.post(
            "/api/b66/drive/connect",
            headers={"Origin": "https://chat.example.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["connect"]["status"] == "connect_started"
    assert body["connect"]["authorization"]["authorization_url"].startswith("https://accounts.google.com/")
    assert binding.ticket_calls == [{"session_id": "sess_test", "connector_id": CONNECTOR_ID}]
    assert google.begin_calls == [{"connect_ticket": "private-b66-connect-ticket"}]
    assert "private-b66-connect-ticket" not in response.text
    assert "sess_test" not in response.text


@pytest.mark.asyncio
async def test_b66_drive_callback_completes_and_maps_verified_destination_privately():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.post(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
            json={
                "state_ref": "state-a",
                "authorization_code": "authorization-code-private",
                "provider_error": None,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["status"] == "connected"
    assert body["status"]["destination_sub"] == "google-sub-12345678"
    assert google.callback_calls[0]["authorization_code"] == "authorization-code-private"
    assert "authorization-code-private" not in response.text


@pytest.mark.asyncio
async def test_b66_drive_disconnect_revokes_only_this_owner_and_returns_status():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.post(
            "/api/b66/drive/disconnect",
            headers={"Origin": "https://chat.example.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["disconnect"]["revoked"] is True
    assert body["disconnect"]["status"]["status"] == "not_connected"
    assert google.revoked == [{"workspace_ref": "workspace_a"}]


@pytest.mark.asyncio
async def test_b66_drive_status_rejects_unauthenticated_and_query_input():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        unauth = await client.get(
            "/api/b66/drive/status",
            headers={"Origin": "https://chat.example.test"},
        )
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        query = await client.get(
            "/api/b66/drive/status?workspace_ref=attacker",
            headers={"Origin": "https://chat.example.test"},
        )

    assert unauth.status_code == 401
    assert query.status_code == 400


@pytest.mark.asyncio
async def test_b66_drive_callback_state_replay_is_closed():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        first = await client.post(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
            json={"state_ref": "state-a", "authorization_code": "code", "provider_error": None},
        )
        assert first.status_code == 200

        google.callback_calls.clear()
        google.status = "not_connected"
        second = await client.post(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
            json={"state_ref": "state-a", "authorization_code": "code", "provider_error": None},
        )
    assert second.status_code == 503
    assert google.callback_calls
