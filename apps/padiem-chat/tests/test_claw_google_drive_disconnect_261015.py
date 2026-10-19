"""Drive disconnect: authentic owner session, server-derived scope, fail-closed write."""
from __future__ import annotations

from types import SimpleNamespace
import httpx
import pytest

from app.auth import SESSION_COOKIE
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from test_google_connector_ticket_bridge import app_fixture, cookie_for

PATH = "/api/connectors/google/drive/disconnect"
ORIGIN = "https://chat.example.test"


class FakeWorkspaceIdentity:
    def __init__(self, workspace="workspace_only_owner_a"):
        self.workspace = workspace
        self.calls = []

    async def resolve_connector_workspace(self, *, session_id):
        self.calls.append(session_id)
        assert session_id == "sess_test"
        return self.workspace


class FakeOAuthBinding:
    def __init__(self, revoked=True, *, malformed=False):
        self.revoked = revoked
        self.malformed = malformed
        self.calls = []

    async def disconnect_drive(self, payload):
        self.calls.append(dict(payload))
        if self.malformed:
            return {"ok": True, "revoked": "yes"}
        return {"ok": True, "revoked": self.revoked}


def configured(*, with_shadow=True, malformed=False):
    app, history, _, _, _ = app_fixture(with_shadow=with_shadow)
    identity, binding = FakeWorkspaceIdentity(), FakeOAuthBinding(malformed=malformed)
    app.state.control_plane_identity_authority = identity
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(binding)
    return app, history, identity, binding


@pytest.mark.asyncio
async def test_owner_disconnect_uses_only_resolved_workspace_and_private_rpc():
    app, history, identity, binding = configured()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
        response = await client.post(PATH, headers={"Origin": ORIGIN, "Content-Type":"application/json"})
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "state": "off", "revoked": True}
    assert identity.calls == ["sess_test"]
    assert binding.calls == [{"workspace_ref": "workspace_only_owner_a"}]
    assert "workspace" not in response.text
    assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_no_cookie_or_forged_scope_can_never_revoke():
    app, history, identity, binding = configured()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.post(PATH, headers={"Origin": ORIGIN, "Content-Type":"application/json"})
        assert response.status_code == 401
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
        forged = await client.post(PATH, json={"workspace_ref": "other"}, headers={"Origin": ORIGIN})
        assert forged.status_code == 400
        query = await client.post(PATH+"?workspace_ref=other", headers={"Origin": ORIGIN, "Content-Type":"application/json"})
        assert query.status_code == 400
        foreign = await client.post(PATH, headers={"Origin": "https://evil.example", "Content-Type":"application/json"})
        assert foreign.status_code == 403
    assert identity.calls == []
    assert binding.calls == []


@pytest.mark.asyncio
async def test_unlinked_canonical_identity_and_invalid_rpc_remain_closed():
    app, history, identity, binding = configured(with_shadow=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
        response = await client.post(PATH, headers={"Origin": ORIGIN, "Content-Type":"application/json"})
    assert response.status_code == 503 and binding.calls == [] and identity.calls == []

    app, history, identity, binding = configured(malformed=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
        response = await client.post(PATH, headers={"Origin": ORIGIN, "Content-Type":"application/json"})
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert binding.calls == [{"workspace_ref": "workspace_only_owner_a"}]
