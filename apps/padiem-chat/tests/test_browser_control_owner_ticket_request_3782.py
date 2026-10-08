"""#3782 B54 signed owner to canonical Engine pending-ticket request (NO grant)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app import browser_control_owner_ticket_request as owner_route
from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import (
    ENGINE_BROWSER_CONTROL_OWNER_TICKET_PATH,
    ENGINE_INTERNAL_ORIGIN,
    EngineTransportResponse,
    PadiemAiEngineClient,
)
from starlette.routing import Route
from test_claw_approval_decision import OWNER, _client, _HandoffStore

PATH = owner_route.BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH
REF = "cont_3782canonical"


class _Transport:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply if reply is not None else {
            "ok": True,
            "ticket_ref": "ticket_engine_original_3782",
            "owner_approval_recorded": False,
            "browser_action_executed": False,
        }

    async def request(self, *, method, url, headers, body):
        self.calls.append((method, url, dict(headers), json.loads(body)))
        return EngineTransportResponse(
            status=200, body=json.dumps(self.reply).encode("utf-8"), headers={},
        )


def _setup(monkeypatch, *, signed_in=True, engine=True, cp=True, reply=None):
    client = _client(_HandoffStore(), signed_in=signed_in)
    client.app.router.routes.insert(
        0, Route(PATH, owner_route.browser_control_owner_ticket_request, methods=["POST"]),
    )
    transport = _Transport(reply)
    if engine:
        client.app.state.browser_control_owner_ticket_engine_client = PadiemAiEngineClient(
            transport=transport, app_id=P01_APP_ID,
            caller_id="b54.test.engine", credential="q" * 40,
        )
    if cp:
        client.app.state.identity_shadow_store = object()
        client.app.state.control_plane_identity_authority = object()

        async def current_session(*, authority, store, product_user_id):
            assert product_user_id == OWNER
            return SimpleNamespace(session_id="cp_session_server_only")
        monkeypatch.setattr(owner_route, "resolve_refreshed_session", current_session)
    else:
        client.app.state.identity_shadow_store = None
        client.app.state.control_plane_identity_authority = None
    return client, transport


def test_not_registered_in_product_app_factory():
    client = _client(_HandoffStore())
    assert owner_route.BROWSER_CONTROL_OWNER_TICKET_REQUEST_ROUTE_WIRED is False
    assert all(getattr(r, "path", None) != PATH for r in client.app.router.routes)


def test_signed_in_user_only_sends_own_cp_session_and_engine_bound_original(monkeypatch):
    client, transport = _setup(monkeypatch)
    response = client.post(PATH, json={"continuation_ref": REF})
    assert response.status_code == 200, response.json()
    assert response.json() == {
        "ok": True,
        "ticket_ref": "ticket_engine_original_3782",
        "owner_approval_recorded": False,
        "browser_action_executed": False,
    }
    assert response.headers["cache-control"].startswith("no-store")
    assert len(transport.calls) == 1
    method, url, headers, body = transport.calls[0]
    assert method == "POST"
    assert url == ENGINE_INTERNAL_ORIGIN + ENGINE_BROWSER_CONTROL_OWNER_TICKET_PATH
    assert body == {
        "app_id": P01_APP_ID,
        "continuation_ref": REF,
        "product_user_id": OWNER,
        "auth_session_ref": "cp_session_server_only",
    }
    assert headers["X-Padiem-Engine-Caller"] == "b54.test.engine"
    assert "q" * 40 not in response.text


@pytest.mark.parametrize("payload", [
    {"continuation_ref": REF, "approved": True},
    {"continuation_ref": REF, "product_user_id": OWNER},
    {"continuation_ref": REF, "auth_session_ref": "evil"},
    {"continuation_ref": REF, "workspace_ref": "evil"},
    {"continuation_ref": REF, "invocation_sha256": "f" * 64},
    {"continuation_ref": REF, "tool_id": "browser.control"},
    {"continuation_ref": "cont_other"},
    {"continuation_ref": REF, "action": {"click": True}},
    {}, [],
])
def test_browser_cannot_supply_auth_or_approval(monkeypatch, payload):
    client, transport = _setup(monkeypatch)
    response = client.post(PATH, json=payload)
    assert response.status_code == 422
    assert transport.calls == []


@pytest.mark.parametrize("config,code", [
    ({"signed_in": False}, 401),
    ({"engine": False}, 503),
    ({"cp": False}, 503),
])
def test_unavailable_auth_or_composition_fails_without_engine_call(monkeypatch, config, code):
    client, transport = _setup(monkeypatch, **config)
    response = client.post(PATH, json={"continuation_ref": REF})
    assert response.status_code == code
    assert transport.calls == []


@pytest.mark.parametrize("reply", [
    {"ok": True, "ticket_ref": "ticket_engine_original_3782",
     "owner_approval_recorded": True, "browser_action_executed": False},
    {"ok": True, "ticket_ref": "ticket_engine_original_3782",
     "owner_approval_recorded": False, "browser_action_executed": True},
    {"ok": True, "ticket_ref": "ticket_engine_original_3782",
     "owner_approval_recorded": False, "browser_action_executed": False, "extra": 1},
    {"ok": True, "ticket_ref": "bad ref",
     "owner_approval_recorded": False, "browser_action_executed": False},
])
def test_engine_cannot_upgrade_pending_ticket_to_approved(monkeypatch, reply):
    client, transport = _setup(monkeypatch, reply=reply)
    response = client.post(PATH, json={"continuation_ref": REF})
    assert response.status_code == 503
    assert len(transport.calls) == 1
    assert "ticket_ref" not in response.json()


def test_unavailable_cp_read_prevents_engine_request(monkeypatch):
    client, transport = _setup(monkeypatch)

    async def unavailable(**_kwargs):
        raise RuntimeError("Control Plane down")
    monkeypatch.setattr(owner_route, "resolve_refreshed_session", unavailable)
    response = client.post(PATH, json={"continuation_ref": REF})
    assert response.status_code == 503
    assert transport.calls == []
