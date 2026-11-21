import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from starlette.responses import JSONResponse

from app import pc_helper_update_routes as routes
from app import pc_file_exchange_routes as files
from app import oracle_mesh_read_return_routes as mesh

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)
LINK = "link-a"
DEVICE = "node//pc-a"


class Store:
    def __init__(self):
        self.row = {"link_id": LINK, "mesh_node_id": DEVICE, "label": "Work PC",
                    "auto_helper_update": 1, "helper_update_dismissed_version": None}
        self.writes = []
        self.owners = ["alice"]

    async def list_helper_update_preferences(self, *, user_id):
        return [self.row] if user_id == "alice" else []

    async def device_scope(self, *, device_id):
        assert device_id == DEVICE
        return {"account_refs": self.owners}

    async def set_helper_update_preference(self, *, user_id, link_id, **kw):
        assert (user_id, link_id) == ("alice", LINK)
        self.writes.append(kw)
        if "auto" in kw:
            self.row["auto_helper_update"] = int(kw["auto"])
        else:
            self.row["helper_update_dismissed_version"] = kw["dismissed_version"]
        return True


def body(result):
    return json.loads(result.body)


@pytest.fixture
def setup(monkeypatch):
    store = Store()
    sent = []
    req = NS(app=NS(state=NS(pc_device_pairing_store=store)), path_params={"link_id": LINK},
             user="alice", payload={}, online=True, latest="0.4.0", required=False)
    monkeypatch.setattr(routes, "current_user_id", lambda r: r.user)
    monkeypatch.setattr(routes, "_now", lambda: NOW)

    async def get_body(r):
        return r.payload

    async def presence(_store, *, device_id, now):
        assert now == NOW and device_id == DEVICE
        return {"online": req.online}

    async def version(_state, *, device_id, now):
        assert now == NOW and device_id == DEVICE
        return {"helper_version": "0.3.0", "latest_version": req.latest,
                "update_available": True, "update_required": req.required}

    async def owner(r):
        return NS(tenant_id="tenant"), r.user, "workspace"

    async def target(*_args, **kwargs):
        assert kwargs["link"]["mesh_node_id"] == DEVICE
        return {"node_ref": DEVICE, "device_id": DEVICE}, None

    async def stage(*_args, **_kwargs):
        return ("run", "conversation")

    async def dispatch(_request, **kw):
        sent.append(kw)
        return JSONResponse({"ok": True})

    from app import pc_device_pairing_routes as pairing
    monkeypatch.setattr(routes, "_body", get_body)
    monkeypatch.setattr(pairing, "_presence_view", presence)
    monkeypatch.setattr(routes, "load_update_view", version)
    monkeypatch.setattr(files, "_owner", owner)
    monkeypatch.setattr(files, "_dispatch_target", target)
    monkeypatch.setattr(files, "_stage_run", stage)
    monkeypatch.setattr(mesh, "dispatch_oracle_mesh_command_intent", dispatch)
    return req, store, sent


def test_owner_default_off_notice_and_manual_task(setup):
    req, store, sent = setup
    run = asyncio.run
    initial = body(run(routes.list_updates(req)))["devices"][0]
    assert initial["auto_update"] and not initial["notice"]
    req.payload = {"action": "auto", "enabled": False}
    assert run(routes.change_update(req)).status_code == 200
    assert store.writes == [{"auto": False}]
    assert sent[-1]["command"] == routes.control_command(auto=False)
    disabled = body(run(routes.list_updates(req)))["devices"][0]
    assert not disabled["auto_update"] and disabled["notice"]
    req.payload = {"action": "update"}
    assert run(routes.change_update(req)).status_code == 200
    assert sent[-1]["command"] == routes.control_command(version="0.4.0")
    assert all(call["user_mode"] and call["helper_update_control"] for call in sent)
    assert all(call["wire"]["device_id"] == DEVICE for call in sent)
    req.payload = {"action": "dismiss", "version": "0.4.0"}
    assert run(routes.change_update(req)).status_code == 200
    assert not body(run(routes.list_updates(req)))["devices"][0]["notice"]
    req.latest = "0.5.0"
    assert body(run(routes.list_updates(req)))["devices"][0]["notice"]


def test_foreign_guest_offline_shared_and_closed_body_refused(setup):
    req, store, sent = setup
    run = asyncio.run
    req.payload = {"action": "update"}
    req.user = None
    assert run(routes.list_updates(req)).status_code == 401
    assert run(routes.change_update(req)).status_code == 401
    req.user = "bob"
    assert body(run(routes.list_updates(req)))["devices"] == []
    assert run(routes.change_update(req)).status_code == 404
    req.user = "alice"
    req.online = False
    assert run(routes.change_update(req)).status_code == 409
    req.online = True
    store.owners = ["alice", "bob"]
    assert run(routes.change_update(req)).status_code == 403
    req.payload = {"action": "update", "command": "other"}
    assert run(routes.change_update(req)).status_code == 400
    assert not sent and not store.writes


def test_minimum_blocks_commands_but_not_fixed_owner_update(setup):
    req, _, _ = setup
    def check(command, *, control=False, user_mode=True):
        return asyncio.run(routes.command_update_denial(
            req.app.state, device_id=DEVICE, command=command, user_mode=user_mode,
            helper_update_control=control, now=NOW))
    assert check("ordinary command") is None
    req.required = True
    assert check("ordinary command") == (409, "pc_helper_update_required", "업데이트 후 사용할 수 있어요")
    fixed = routes.control_command(version="0.4.0")
    assert check(fixed)[0] == 409
    assert check(fixed, control=True) is None
    assert check(fixed, control=True, user_mode=False)[0] == 403
    assert check("ordinary command", control=True)[0] == 403


def test_only_fixed_user_mode_control_commands_are_admitted():
    for command in (routes.control_command(auto=False), routes.control_command(auto=True),
                    routes.control_command(version="0.4.0")):
        assert routes.is_control_command(command)
        assert not routes.is_control_command(command + ";other")
        assert not routes.is_control_command(command.replace("PadiemUserHelperUpdater", "OtherTask"))
    with pytest.raises(ValueError):
        routes.control_command(version="0.4.0';other")

def test_persisted_preference_is_owner_and_link_scoped():
    from app.d1_sqlite import SqliteD1
    from app.pc_device_pairing_store import D1PcPairingStore
    from _support.ops_audit_helpers import OWNER, OTHER, database

    async def run():
        db, _ = database(full=True)
        try:
            store = D1PcPairingStore(SqliteD1(db))
            for uid, key, device in ((OWNER, "link-a", DEVICE), (OTHER, "link-b", "node//pc-b")):
                db.execute(
                    "INSERT INTO pc_device_links (link_id,user_id,mesh_node_id,label,state,roots_json,"
                    "pairing_code_id,created_at,updated_at,revoked_at) VALUES (?,?,?,?,?,'[]',NULL,?,?,NULL)",
                    (key, uid, device, "PC", "active", NOW.isoformat(), NOW.isoformat()),
                )
            assert (await store.list_helper_update_preferences(user_id=OWNER))[0]["auto_helper_update"] == 1
            assert not await store.set_helper_update_preference(user_id=OTHER, link_id="link-a", auto=False)
            assert await store.set_helper_update_preference(user_id=OWNER, link_id="link-a", auto=False)
            assert await store.set_helper_update_preference(user_id=OWNER, link_id="link-a", dismissed_version="0.4.0")
            row = (await store.list_helper_update_preferences(user_id=OWNER))[0]
            assert row["auto_helper_update"] == 0 and row["helper_update_dismissed_version"] == "0.4.0"
            other = (await store.list_helper_update_preferences(user_id=OTHER))[0]
            assert other["auto_helper_update"] == 1 and other["helper_update_dismissed_version"] is None
        finally:
            db.close()

    asyncio.run(run())


def test_guest_cannot_call_private_update_routes():
    from app.app_factory import create_app
    from starlette.testclient import TestClient
    from _support.ops_audit_helpers import SETTINGS

    with TestClient(create_app(settings=SETTINGS, history_store=object())) as client:
        assert client.get(routes.PATH).status_code == 401
        assert client.post(routes.PATH + "/link-a", json={"action": "update"}).status_code == 401
