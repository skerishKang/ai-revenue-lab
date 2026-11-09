"""#7248: Calendar disconnect reuses the Drive disconnect path, one connector over.

The route takes an empty body and the origin-verified cookie only, resolves the
trusted workspace from the B62 shadow session, and forwards a workspace-only
private RPC. Callers get a bounded revocation count and no private reference.
"""
from __future__ import annotations

import httpx
import pytest

from app.auth import SESSION_COOKIE
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from test_google_connector_ticket_bridge import app_fixture, cookie_for

PATH = "/api/connectors/google/calendar/disconnect"
DRIVE_PATH = "/api/connectors/google/drive/disconnect"
ORIGIN = "https://chat.example.test"


class FakeWorkspaceIdentity:
    def __init__(self, workspace: str = "workspace_only_owner_a") -> None:
        self.workspace = workspace
        self.calls: list[str] = []

    async def resolve_connector_workspace(self, *, session_id):
        self.calls.append(session_id)
        assert session_id == "sess_test"
        return self.workspace


class FakeOAuthBinding:
    def __init__(self, result=None, *, error: str | None = None) -> None:
        self.result = {"ok": True, "revoked": 3} if result is None else result
        self.error = error
        self.calls: list[dict] = []

    async def disconnect_calendar(self, payload):
        self.calls.append(dict(payload))
        if self.error is not None:
            return {"ok": False, "error": {"code": self.error, "message": "denied"}}
        return self.result


def configured(*, with_shadow: bool = True, result=None, error: str | None = None):
    app, history, _, _, _ = app_fixture(with_shadow=with_shadow)
    identity = FakeWorkspaceIdentity()
    binding = FakeOAuthBinding(result, error=error)
    app.state.control_plane_identity_authority = identity
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(binding)
    return app, history, identity, binding


def _client(app, history):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
    return client


@pytest.mark.asyncio
async def test_calendar_disconnect_uses_only_the_resolved_workspace():
    app, history, identity, binding = configured()
    async with _client(app, history) as client:
        response = await client.post(
            PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "state": "off", "revoked": 3}
    assert identity.calls == ["sess_test"]
    assert binding.calls == [{"workspace_ref": "workspace_only_owner_a"}]
    for forbidden in ("workspace_only_owner_a", "binding_ref", "account_ref", "sess_test"):
        assert forbidden not in response.text
    assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_calendar_disconnect_rejects_client_supplied_authority():
    app, history, identity, binding = configured()
    async with _client(app, history) as client:
        query = await client.post(
            f"{PATH}?workspace_ref=workspace_attacker",
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        body = await client.post(
            PATH,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            content=b'{"workspace_ref": "workspace_attacker"}',
        )

    assert query.status_code == 400
    assert query.json()["error"]["code"] == "connector_disconnect_query_not_allowed"
    assert body.status_code == 400
    assert body.json()["error"]["code"] == "connector_disconnect_body_not_allowed"
    assert binding.calls == []


@pytest.mark.asyncio
async def test_calendar_disconnect_requires_an_same_origin_owner_session():
    app, history, identity, binding = configured()
    async with _client(app, history) as client:
        foreign = await client.post(
            PATH, headers={"Origin": "https://evil.example", "Content-Type": "application/json"}
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN
    ) as anonymous:
        signed_out = await anonymous.post(
            PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )

    assert foreign.status_code == 403
    assert signed_out.status_code == 401
    assert binding.calls == []


@pytest.mark.asyncio
async def test_calendar_disconnect_fails_closed_without_a_shadow_or_canonical_denial():
    app, history, identity, binding = configured(with_shadow=False)
    async with _client(app, history) as client:
        response = await client.post(
            PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )
    assert response.status_code == 503
    assert binding.calls == []

    app2, history2, identity2, binding2 = configured(error="invalid_google_oauth_binding")
    async with _client(app2, history2) as client2:
        denied = await client2.post(
            PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "calendar_disconnect_unavailable"
    assert binding2.calls == [{"workspace_ref": "workspace_only_owner_a"}]


@pytest.mark.asyncio
async def test_calendar_disconnect_rejects_a_malformed_rpc_result():
    app, history, identity, binding = configured(result={"ok": True, "revoked": "three"})
    async with _client(app, history) as client:
        response = await client.post(
            PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_drive_disconnect_still_answers_its_own_path():
    app, history, identity, binding = configured()

    async def _drive(payload):
        binding.calls.append(dict(payload))
        return {"ok": True, "revoked": True}

    binding.disconnect_drive = _drive  # type: ignore[attr-defined]
    async with _client(app, history) as client:
        response = await client.post(
            DRIVE_PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "state": "off", "revoked": True}
