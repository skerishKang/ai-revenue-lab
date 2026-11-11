"""#7088 Chat 층 시험: /api/connectors/google/gmail/disconnect 및 create_app workspace_truth 배선."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import chat_connector_tools as tools_module
from app.app_factory import create_app
from app.auth import SESSION_COOKIE
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from test_google_connector_ticket_bridge import (
    MemoryHistoryStore,
    MemoryShadowStore,
    cookie_for,
    settings,
    shadow,
)

PATH = "/api/connectors/google/gmail/disconnect"
ORIGIN = "https://chat.example.test"


def _canonical_session(*, session_id: str = "sess_test") -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, "sub_test"),
        issued_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


class _FakeWorkspaceIdentity:
    def __init__(self, workspace: str = "workspace_gmail_owner_a") -> None:
        self.workspace = workspace
        self.calls: list[str] = []

    async def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot:
        return _canonical_session(session_id=session_id)

    async def resolve_connector_workspace(self, *, session_id: str) -> str:
        self.calls.append(session_id)
        assert session_id == "sess_test"
        return self.workspace


class _FakeOAuthBinding:
    def __init__(self, result=None, *, error: str | None = None) -> None:
        self.result = {"ok": True, "revoked": 2} if result is None else result
        self.error = error
        self.calls: list[dict] = []

    async def disconnect_gmail(self, payload: dict) -> dict:
        self.calls.append(dict(payload))
        if self.error is not None:
            return {"ok": False, "error": {"code": self.error, "message": "denied"}}
        return self.result


def _configured(*, with_shadow: bool = True, with_truth: bool = True, result=None, error: str | None = None):
    history = MemoryHistoryStore()
    shadow_store = MemoryShadowStore(shadow(history.profile.id) if with_shadow else None)
    identity = _FakeWorkspaceIdentity()
    binding = _FakeOAuthBinding(result, error=error)
    truth = CloudflareGoogleOAuthWorkspaceTruth(binding) if with_truth else None
    app = create_app(
        settings=settings(),
        history_store=history,
        control_plane_identity_authority=identity,
        identity_shadow_store=shadow_store,
        google_oauth_workspace_truth=truth,
    )
    return app, history, identity, binding


def _client(app, history):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
    return client


@pytest.mark.asyncio
async def test_7088_gmail_disconnect_wires_through_create_app_and_invalidates_grant_cache() -> None:
    app, history, identity, binding = _configured()
    tools_module.seed_connector_grant_cache(
        history.profile.id,
        tools_module.ConnectorToolGrant(
            reason=tools_module.GRANT_REASON_GRANTED,
            drive=False,
            calendar=False,
            gmail=True,
        ),
    )
    assert history.profile.id in tools_module._GRANT_CACHE

    async with _client(app, history) as client:
        response = await client.post(
            PATH,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "state": "off", "revoked": 2}
    assert identity.calls == ["sess_test"]
    assert binding.calls == [{"workspace_ref": "workspace_gmail_owner_a"}]
    assert history.profile.id not in tools_module._GRANT_CACHE
    for forbidden in ("workspace_gmail_owner_a", "binding_ref", "account_ref", "sess_test"):
        assert forbidden not in response.text
    assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_7088_gmail_disconnect_rejects_client_authority_foreign_origin_and_anonymous() -> None:
    app, history, _identity, binding = _configured()
    async with _client(app, history) as client:
        query_resp = await client.post(
            f"{PATH}?workspace_ref=attacker_ws",
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        body_resp = await client.post(
            PATH,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            content=b'{"workspace_ref":"attacker_ws"}',
        )
        foreign_resp = await client.post(
            PATH,
            headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as anon:
        anon_resp = await anon.post(
            PATH,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )

    assert query_resp.status_code == 400
    assert query_resp.json()["error"]["code"] == "connector_disconnect_query_not_allowed"
    assert body_resp.status_code == 400
    assert body_resp.json()["error"]["code"] == "connector_disconnect_body_not_allowed"
    assert foreign_resp.status_code == 403
    assert anon_resp.status_code == 401
    assert binding.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_result",
    [
        {"ok": True, "revoked": True},
        {"ok": True, "revoked": "2"},
        {"ok": True, "revoked": -1},
        {"ok": True, "revoked": 33},
    ],
)
async def test_7088_gmail_disconnect_fails_closed_on_missing_truth_shadow_error_or_bad_rpc(
    bad_result: dict,
) -> None:
    app_no_truth, history_nt, _id_nt, binding_nt = _configured(with_truth=False)
    async with _client(app_no_truth, history_nt) as client:
        no_truth = await client.post(PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert no_truth.status_code == 503
    assert no_truth.json()["error"]["code"] == "gmail_disconnect_unavailable"
    assert binding_nt.calls == []

    app_err, history_err, _id_err, _b_err = _configured(error="invalid_google_oauth_binding")
    async with _client(app_err, history_err) as client2:
        denied = await client2.post(PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "gmail_disconnect_unavailable"

    app_bad, history_bad, _id_bad, _b_bad = _configured(result=bad_result)
    async with _client(app_bad, history_bad) as client3:
        malformed = await client3.post(PATH, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert malformed.status_code == 503
    assert malformed.json()["error"]["code"] == "gmail_disconnect_unavailable"
