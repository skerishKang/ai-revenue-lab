"""The consent screen resolves the session to the owner id the PC links name.

The failing report (2026-11-04 22:59 KST) was an empty consent list while the
same owner's queue links existed: the screen looked the directory up under the
signed-in session's own id instead of the owner id the MCP lanes resolve from
that session's canonical subject. These tests pin that conversion, the owner id
the code/token carries, and the boundary that another owner's links stay
invisible.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_5222_account_model_selection import BASE, client_for, session
from test_mcp_gateway_account import account_app, setup
from test_mcp_oauth_261103 import _approve, _code_from, _exchange, _params, _pkce, _register

from app import chat_pc_drive

OTHER_OWNER = "usr_" + "c" * 32
PC_A = "node//owner-pc-a"
PC_B = "node//owner-pc-b"
PC_C = "node//owner-pc-c"
OTHER_PC = "node//other-owner-pc"


class QueuePairing:
    def __init__(self, links_by_owner):
        self.links_by_owner = links_by_owner
        self.fail = False

    async def links_for_owner(self, *, user_id):
        if self.fail:
            raise RuntimeError("queue unavailable")
        return [dict(link) for link in self.links_by_owner.get(user_id, [])]


class IdentityAuthority:
    """The canonical identity read the MCP lanes already make for a session."""

    def __init__(self, owner_subject_id):
        self.owner_subject_id = owner_subject_id
        self.session_ids = []

    async def resolve_connector_owner_scope(self, *, session_id):
        self.session_ids.append(session_id)
        return {"account_ref": "acct_fixture", "workspace_ref": "ws_fixture",
                "owner_subject_id": self.owner_subject_id}


@pytest.fixture
def owner_ctx(monkeypatch):
    db, link_owner, session_user, store = setup()
    app = account_app(db, link_owner, store)
    app.state.pc_device_pairing_store = QueuePairing({
        link_owner: [
            {"mesh_node_id": PC_A, "label": "PADIEM-COMMAND", "state": "active", "roots": []},
            {"mesh_node_id": PC_B, "label": "CGI-1", "state": "active", "roots": []},
            {"mesh_node_id": PC_C, "label": "K_lipvoice", "state": "active", "roots": []},
        ],
        OTHER_OWNER: [{"mesh_node_id": OTHER_PC, "label": "Other PC", "state": "active", "roots": []}],
    })
    # The canonical session's owner subject names the link owner, while the
    # browser's own product user is a different account — the reported mismatch.
    app.state.control_plane_identity_authority = IdentityAuthority(link_owner)

    async def fake_owner(request, uid):
        return SimpleNamespace(session_id="sess_fixture"), "sub_fixture", "ws_fixture"

    monkeypatch.setattr(chat_pc_drive, "_resolve_chat_owner", fake_owner)
    return app, db, link_owner, session_user


async def _consent_params(client):
    registered = await _register(client)
    verifier, _ = _pkce()
    return registered["client_id"], verifier, _params(registered["client_id"], verifier)


@pytest.mark.asyncio
async def test_list_and_choice_use_the_owner_id_of_the_session_subject(owner_ctx):
    app, db, link_owner, session_user = owner_ctx
    async with client_for(app) as external:
        client_id, verifier, params = await _consent_params(external)
        async with client_for(app) as ui:
            ui.cookies.update(session(app, session_user))
            info = await ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200, info.text
            pcs = info.json()["pcs"]
            assert [pc["name"] for pc in pcs] == ["PADIEM-COMMAND", "CGI-1", "K_lipvoice"]
            assert OTHER_PC not in [pc["device_id"] for pc in pcs]

            approved = await _approve(ui, params, device_id=PC_A)
            assert approved.status_code == 200, approved.text
            code, _ = _code_from(approved.json()["redirect_url"])
            assert (await _exchange(external, client_id, code, verifier)).status_code == 200

            denied = await _approve(ui, params, device_id=OTHER_PC)
            assert denied.status_code == 403
            assert denied.json()["error"] == "pc_device_unavailable"

    row = db.conn.execute(
        "SELECT user_id FROM padiem_mcp_tokens ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row[0] == link_owner


@pytest.mark.asyncio
async def test_both_scopes_are_written_for_the_converted_owner(owner_ctx):
    app, db, link_owner, session_user = owner_ctx
    async with client_for(app) as external:
        client_id, verifier, params = await _consent_params(external)
        async with client_for(app) as ui:
            ui.cookies.update(session(app, session_user))
            selected = await ui.post("/oauth/authorize", json={
                **params, "decision": "approve", "device_id": PC_A,
                "device_scope": "selected", "device_ids": [PC_B, PC_C],
            }, headers={"Origin": BASE})
            assert selected.status_code == 200, selected.text
            selected_code, _ = _code_from(selected.json()["redirect_url"])
            assert (await _exchange(external, client_id, selected_code, verifier)).status_code == 200
        async with client_for(app) as ui:
            ui.cookies.update(session(app, session_user))
            all_pcs = await _approve(ui, params, device_id=PC_B)
            assert all_pcs.status_code == 200, all_pcs.text
            all_code, _ = _code_from(all_pcs.json()["redirect_url"])
            assert (await _exchange(external, client_id, all_code, verifier)).status_code == 200

    rows = db.conn.execute(
        "SELECT user_id, device_scope, device_scope_json FROM padiem_mcp_tokens ORDER BY rowid"
    ).fetchall()
    assert [row[0] for row in rows] == [link_owner, link_owner]
    assert [row[1] for row in rows] == ["selected", "all"]
    assert json.loads(rows[0][2]) == [PC_B, PC_C, PC_A]  # default PC is always inside the set
    assert rows[1][2] is None


@pytest.mark.asyncio
async def test_without_the_conversion_the_session_own_id_is_never_widened(owner_ctx):
    app, _db, _link_owner, session_user = owner_ctx
    app.state.control_plane_identity_authority = None
    async with client_for(app) as external:
        _client_id, _verifier, params = await _consent_params(external)
        async with client_for(app) as ui:
            ui.cookies.update(session(app, session_user))
            info = await ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200
            assert info.json()["pcs"] == []
            denied = await _approve(ui, params, device_id=PC_A)
            assert denied.status_code == 403
