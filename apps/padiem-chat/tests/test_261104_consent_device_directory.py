"""#6836 follow-up: the consent screen reads the same PC directory as ``pc_devices``.

The report (2026-11-04 22:25 KST) was a consent page that said "연결할 PC가
없습니다" while the MCP ``pc_devices`` tool listed three online PCs for the same
owner. The list and the tool now answer from one function on one store, and a
directory that cannot be read is an error instead of an empty list.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_5222_account_model_selection import BASE, client_for, session
from test_mcp_gateway_account import account_app, setup
from test_mcp_oauth_261103 import _approve, _code_from, _exchange, _params, _pkce, _register

from app.mcp_device_selection import device_id6

ROOT = Path(__file__).resolve().parents[1]

PC_A = "node//queue-owner-pc-a"
PC_B = "node//queue-owner-pc-b"
OTHER_DEVICE = "node//other-owner-pc"


class QueuePairing:
    """The queue-backed directory as the browser routes see it.

    One call per read, JSON rows, and a way to make the read fail: a failure is
    what the incident's silent empty list hid.
    """

    def __init__(self, links_by_owner):
        self.links_by_owner = links_by_owner
        self.fail = False
        self.calls = []

    async def links_for_owner(self, *, user_id):
        self.calls.append(user_id)
        if self.fail:
            raise RuntimeError("queue unavailable")
        return [dict(link) for link in self.links_by_owner.get(user_id, [])]


class Presence:
    """The presence receipt store: a loaded row, or nothing."""

    def __init__(self, online_ids):
        self.online_ids = set(online_ids)

    def load(self, *, device_id):
        if device_id not in self.online_ids:
            return None
        return {
            "source": "mesh",
            "device_id": device_id,
            "connected": True,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }


@pytest.fixture
def directory_ctx():
    db, owner, other, store = setup()
    app = account_app(db, owner, store)
    pairing = QueuePairing({
        owner: [
            {"mesh_node_id": PC_A, "label": "PADIEM-COMMAND", "state": "active", "roots": []},
            {"mesh_node_id": PC_B, "label": "K_lipvoice", "state": "active", "roots": []},
        ],
        other: [{"mesh_node_id": OTHER_DEVICE, "label": "Other PC", "state": "active", "roots": []}],
    })
    app.state.pc_device_pairing_store = pairing
    app.state.mesh_device_presence_store = Presence({PC_A})
    return app, owner, other, store, pairing, db


async def _params_for(client):
    registered = await _register(client)
    verifier, _ = _pkce()
    return registered["client_id"], verifier, _params(registered["client_id"], verifier)


@pytest.mark.asyncio
async def test_consent_lists_the_queue_links_with_pc_devices_display(directory_ctx):
    app, owner, _other, _store, _pairing, _db = directory_ctx
    async with client_for(app) as external:
        client_id, _verifier, params = await _params_for(external)
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))
            info = await owner_ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200, info.text
            pcs = info.json()["pcs"]
            assert [pc["device_id"] for pc in pcs] == [PC_A, PC_B]
            assert [pc["name"] for pc in pcs] == ["PADIEM-COMMAND", "K_lipvoice"]
            assert [pc["label"] for pc in pcs] == ["PADIEM-COMMAND", "K_lipvoice"]
            assert [pc["id6"] for pc in pcs] == [device_id6(PC_A), device_id6(PC_B)]
            assert [pc["online"] for pc in pcs] == [True, False]
            page = await owner_ui.get("/oauth/authorize", params=params)
            assert page.status_code == 200
            assert 'id="mcpOauthPc"' in page.text


@pytest.mark.asyncio
async def test_consent_never_shows_another_owners_links(directory_ctx):
    app, owner, other, _store, _pairing, _db = directory_ctx
    async with client_for(app) as external:
        _client_id, _verifier, params = await _params_for(external)
        async with client_for(app) as other_ui:
            other_ui.cookies.update(session(app, other))
            info = await other_ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200
            assert [pc["device_id"] for pc in info.json()["pcs"]] == [OTHER_DEVICE]
            denied = await _approve(other_ui, params, device_id=PC_A)
            assert denied.status_code == 403
            assert denied.json()["error"] == "pc_device_unavailable"
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))
            assert (await _approve(owner_ui, params, device_id=OTHER_DEVICE)).status_code == 403


@pytest.mark.asyncio
async def test_unreadable_directory_is_an_error_not_an_empty_list(directory_ctx):
    app, owner, _other, _store, pairing, _db = directory_ctx
    pairing.fail = True
    async with client_for(app) as external:
        _client_id, _verifier, params = await _params_for(external)
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))
            info = await owner_ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 503, info.text
            assert info.json()["error"] == "device_directory_unavailable"
            approved = await _approve(owner_ui, params, device_id=PC_A)
            assert approved.status_code == 503


@pytest.mark.asyncio
async def test_only_zero_links_answers_with_an_empty_pc_list(directory_ctx):
    app, owner, _other, _store, pairing, _db = directory_ctx
    pairing.links_by_owner[owner] = []
    async with client_for(app) as external:
        _client_id, _verifier, params = await _params_for(external)
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))
            info = await owner_ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200
            assert info.json()["pcs"] == []
            approved = await _approve(owner_ui, params, device_id=PC_A)
            assert approved.status_code == 403


@pytest.mark.asyncio
async def test_both_scopes_reach_the_token_through_the_same_directory(directory_ctx):
    app, owner, _other, _store, _pairing, db = directory_ctx
    async with client_for(app) as external:
        client_id, verifier, params = await _params_for(external)
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))

            all_pcs = await _approve(owner_ui, params, device_id=PC_A)
            assert all_pcs.status_code == 200, all_pcs.text
            code_all, _ = _code_from(all_pcs.json()["redirect_url"])
            assert (await _exchange(external, client_id, code_all, verifier)).status_code == 200

            selected = await owner_ui.post("/oauth/authorize", json={
                **params, "decision": "approve", "device_id": PC_A,
                "device_scope": "selected", "device_ids": [PC_B],
            }, headers={"Origin": BASE})
            assert selected.status_code == 200, selected.text
            code_selected, _ = _code_from(selected.json()["redirect_url"])
            assert (await _exchange(external, client_id, code_selected, verifier)).status_code == 200

            foreign = await owner_ui.post("/oauth/authorize", json={
                **params, "decision": "approve", "device_id": PC_A,
                "device_scope": "selected", "device_ids": [OTHER_DEVICE],
            }, headers={"Origin": BASE})
            assert foreign.status_code == 403
            assert foreign.json()["error"] == "pc_device_unavailable"

    rows = db.conn.execute(
        "SELECT device_id, device_scope, device_scope_json FROM padiem_mcp_tokens "
        "ORDER BY rowid"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        (PC_A, "all", None),
        (PC_A, "selected", json.dumps([PC_B, PC_A])),
    ]


def test_consent_script_shows_name_id6_and_online_together():
    static = ROOT / "static"
    script = (static / "mcp-oauth-consent.js").read_text(encoding="utf-8")
    locale = (static / "locale.js").read_text(encoding="utf-8")
    assert "pc.name" in script and "pc.id6" in script and "pc.online === true" in script
    assert locale.count('"mcp-oauth-pc-online"') == 2
