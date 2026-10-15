"""B66 #4089 full-Drive host wiring: signed owner, CP context, private OAuth."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE
from app.b66_drive_routes import b66_drive_status
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
OTHER = "usr_" + "b" * 32
FILE_CONNECTOR_ID = "b66-google-drive-file"
FULL_CONNECTOR_ID = "b66-google-drive-full"
FULL_SCOPE = "https://www.googleapis.com/auth/drive"
OIDC_SCOPES = ("openid", "profile", "email")
FULL_AUTH_SCOPES = (FULL_SCOPE,) + OIDC_SCOPES
FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class FakeControlPlaneBinding:
    def __init__(self) -> None:
        self.ticket_calls: list[dict] = []
        self.issued_ticket = "private-b66-connect-ticket"

    async def resolve_auth_session(self, payload):
        from datetime import datetime, timezone

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
        if payload["connector_id"] != FULL_CONNECTOR_ID:
            return {"ok": False, "error": {"code": "connector_not_reviewed", "message": "rejected"}}
        return {
            "ok": True,
            "ticket": {
                "connect_ticket": self.issued_ticket,
                "connector_id": FULL_CONNECTOR_ID,
                "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
            },
        }


def connection_receipt(*, scope: str = FULL_SCOPE, connector_id: str = FULL_CONNECTOR_ID):
    return {
        "binding_ref": "binding_a",
        "connector_id": connector_id,
        "actor_ref": "actor_a",
        "account_ref": "account_a",
        "workspace_ref": "workspace_a",
        "scopes": list(FULL_AUTH_SCOPES),
        "connected_at": NOW.isoformat(),
        "expires_at": None,
        "refresh_token_persisted_sealed": True,
        "access_token_discarded": True,
        "raw_authorization_code": False,
        "raw_access_token": False,
        "raw_refresh_token": False,
        "raw_client_secret": False,
        "verified_destination_subject": "google-sub-12345678",
        "verified_destination_account": "owner@drive.test",
    }


class FakeGoogleOAuthBinding:
    def __init__(self) -> None:
        self.begin_calls: list[dict] = []
        self.complete_calls: list[dict] = []
        self.revoked: list[dict] = []
        self.full_status = "resolved"
        self.file_status = "not_connected"

    async def begin_connect(self, payload):
        self.begin_calls.append(dict(payload))
        return {
            "ok": True,
            "authorization": {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?state=state-a",
                "connector_id": FULL_CONNECTOR_ID,
                "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
            },
        }

    async def complete_callback(self, payload):
        self.complete_calls.append(dict(payload))
        return {"ok": True, "connection": connection_receipt()}

    async def select_b66_drive_full_binding(self, payload):
        del payload
        if self.full_status == "resolved":
            return {
                "ok": True,
                "selection": {
                    "status": "resolved",
                    "connector_id": FULL_CONNECTOR_ID,
                    "workspace_ref": "workspace_a",
                    "binding_ref": "binding_full",
                    "actor_ref": "actor_a",
                    "provider_subject": "google-sub-12345678",
                    "provider_email": "owner@drive.test",
                },
            }
        return {
            "ok": True,
            "selection": {
                "status": self.full_status,
                "connector_id": FULL_CONNECTOR_ID,
                "workspace_ref": (
                    "workspace_attacker"
                    if self.full_status == "not_connected_wrong_workspace"
                    else "workspace_a"
                ),
            },
        }

    async def select_b66_drive_binding(self, payload):
        del payload
        if self.file_status == "resolved":
            return {
                "ok": True,
                "selection": {
                    "status": "resolved",
                    "connector_id": FILE_CONNECTOR_ID,
                    "workspace_ref": "workspace_a",
                    "binding_ref": "binding_file",
                    "actor_ref": "actor_a",
                    "provider_subject": "google-sub-12345678",
                    "provider_email": "owner@drive.test",
                },
            }
        return {
            "ok": True,
            "selection": {
                "status": self.file_status,
                "connector_id": FILE_CONNECTOR_ID,
                "workspace_ref": "workspace_a",
            },
        }

    async def disconnect_b66_drive_full(self, payload):
        self.revoked.append({"full": dict(payload)})
        self.full_status = "not_connected"
        return {"ok": True, "revoked": True}

    async def disconnect_b66_drive(self, payload):
        self.revoked.append({"file": dict(payload)})
        self.file_status = "not_connected"
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
async def test_b66_status_reads_only_signed_owners_verified_full_drive_binding():
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
    assert body["status"]["scope"] == FULL_SCOPE
    assert body["status"]["destination_account"] == "owner@drive.test"
    assert body["status"]["destination_sub"] == "google-sub-12345678"
    assert body["status"]["durable_credential_backend"] == "CP_SEALED_DURABLE_OAUTH"
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert google.begin_calls == []


@pytest.mark.asyncio
async def test_b66_connect_issues_full_drive_ticket_only():
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
    assert body["connect"]["authorization"]["connector_id"] == FULL_CONNECTOR_ID
    assert binding.ticket_calls == [{"session_id": "sess_test", "connector_id": FULL_CONNECTOR_ID}]
    assert google.begin_calls == [{"connect_ticket": "private-b66-connect-ticket"}]
    assert "private-b66-connect-ticket" not in response.text
    assert "sess_test" not in response.text


@pytest.mark.asyncio
async def test_b66_old_file_only_grant_is_not_reported_as_full_connected():
    app, history, _, google = app_fixture()
    google.full_status = "not_connected"
    google.file_status = "resolved"
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
    assert body["status"]["status"] == "reconnect_required"
    assert body["status"]["scope"] == FULL_SCOPE
    assert body["status"]["reconnect_reason"] == "scope_changed"
    assert body["status"]["destination_sub"] == "google-sub-12345678"


@pytest.mark.asyncio
async def test_b66_not_connected_selection_requires_exact_canonical_workspace():
    app, history, _, google = app_fixture()
    google.full_status = "not_connected_wrong_workspace"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.get(
            "/api/b66/drive/status",
            headers={"Origin": "https://chat.example.test"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "b66_drive_unavailable"


@pytest.mark.asyncio
async def test_b62_route_does_not_accept_provider_callback_state_or_code():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OTHER), domain="chat.example.test", path="/")
        rejected_foreign = await client.post(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
            json={
                "state_ref": "state-a",
                "authorization_code": "authorization-code-private",
                "provider_error": None,
            },
        )
        client.cookies.set(
            SESSION_COOKIE,
            cookie_for(OTHER),
            domain="chat.example.test",
            path="/",
        )
        rejected = await client.post(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
            json={
                "state_ref": "state-a",
                "authorization_code": "authorization-code-private",
                "provider_error": None,
            },
        )

    assert rejected_foreign.status_code == 405
    assert rejected.status_code == 405
    assert google.complete_calls == []
    assert google.begin_calls == []


@pytest.mark.asyncio
async def test_b62_callback_return_is_status_only_get_without_state_or_code():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        response = await client.get(
            "/api/b66/drive/connect/callback",
            headers={"Origin": "https://chat.example.test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["status"] == "connected"
    assert body["status"]["scope"] == FULL_SCOPE
    assert google.complete_calls == []


@pytest.mark.asyncio
async def test_b66_disconnect_revokes_full_and_precursor_file_grants():
    app, history, _, google = app_fixture()
    google.file_status = "resolved"
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
    assert body["disconnect"]["status"]["scope"] == FULL_SCOPE
    assert google.revoked == [
        {"full": {"workspace_ref": "workspace_a"}},
        {"file": {"workspace_ref": "workspace_a"}},
    ]


@pytest.mark.asyncio
async def test_read_only_status_get_rejects_foreign_origin():
    app, history, _, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        foreign_origin = await client.get(
            "/api/b66/drive/status",
            headers={"Origin": "https://attacker.example.test"},
        )

    assert foreign_origin.status_code == 403


@pytest.mark.asyncio
async def test_status_route_accepts_absent_origin_for_signed_owner_get():
    app, history, _, google = app_fixture()
    cookie = cookie_for(OWNER)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/b66/drive/status",
        "raw_path": b"/api/b66/drive/status",
        "query_string": b"",
        "headers": [(b"cookie", f"{SESSION_COOKIE}={cookie}".encode())],
        "client": ("browser", 12345),
        "server": ("chat.example.test", 443),
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    response = await b66_drive_status(Request(scope, receive))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mutating_connect_post_requires_matching_origin():
    app, history, binding, google = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(OWNER), domain="chat.example.test", path="/")
        client.headers["origin"] = ""
        missing_origin = await client.post("/api/b66/drive/connect")
    assert missing_origin.status_code == 403
    assert binding.ticket_calls == []
    assert google.begin_calls == []


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
