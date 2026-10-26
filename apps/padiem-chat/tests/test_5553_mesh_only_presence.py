"""Real poll/store/directory/UI projection with no Broker registration."""
import asyncio
import json
import logging
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import claw_device_directory_routes as directory
from app.claw_local_access_source import mesh_presence_online, CanonicalClawLocalAccessTruthSource, mesh_presence_facts
from app.mesh_device_presence_store import D1MeshDevicePresenceStore, MeshDevicePresenceStoreError
from app.oracle_mesh_read_return_routes import OracleMeshReturnSource, EXECUTION_MODE_MESH
from app.pc_work_context import PcConnectorScope
import test_5553_mesh_online_projection_261024 as existing

ROOT = Path(__file__).resolve().parents[3]


class D1:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        for name in ("067_mesh_device_presence.sql", "070_mesh_device_presence_source.sql"):
            self.db.executescript((ROOT / "apps/padiem-chat/migrations" / name).read_text())

    def prepare(self, sql):
        db = self.db
        class Statement:
            def bind(self, *values):
                self.values = values
                return self
            async def first(self):
                row = db.execute(sql, self.values).fetchone()
                return dict(row) if row else None
            async def run(self):
                db.execute(sql, self.values)
        return Statement()


def test_mesh_only_poll_persists_null_generation_and_info_log(caplog):
    store = D1MeshDevicePresenceStore(D1())
    state = existing._poll_state(store)
    state.mesh_presence_generation_resolver = None
    with caplog.at_level(logging.INFO):
        code, body = existing._poll(state, {"presence": [{"device_id": existing.NODE_ID, "connected": True}]})
    assert code == 200 and body == {"ok": True, "dispatch": None}
    row = asyncio.run(store.load(existing.DEVICE_ID))
    assert row["source"] == "mesh" and row["credential_generation"] is None
    assert row["connected"] is True
    assert mesh_presence_online(row, device_id=existing.DEVICE_ID, now=datetime.now(timezone.utc))
    record, = [r for r in caplog.records if "generation_unresolved" in r.message]
    assert record.levelno == logging.INFO
    assert existing.NODE_ID not in caplog.text
    assert existing.DEVICE_ID not in caplog.text
    # Channel proof and the deployment ownership map still precede writes.
    assert existing._poll(state, {"presence": [{"device_id": "foreign@pc+1", "connected": True}]})[0] == 200
    assert asyncio.run(store.load("foreign@pc+1")) is None


def test_broker_presence_compatibility_and_source_validation():
    store = D1MeshDevicePresenceStore(D1())
    now = datetime.now(timezone.utc)
    assert asyncio.run(store.upsert(device_id="old@pc+1", connected=True, received_at=now, credential_generation=3))
    assert asyncio.run(store.load("old@pc+1"))["source"] == "broker"
    with pytest.raises(MeshDevicePresenceStoreError):
        asyncio.run(store.upsert(device_id="old@pc+1", connected=True, received_at=now, credential_generation=None))


@pytest.mark.parametrize("age,connected,expected", [(0, True, True), (180, True, True), (181, True, False), (-1, True, False), (1, False, False)])
def test_mesh_freshness_is_exactly_180_seconds(age, connected, expected):
    now = datetime.now(timezone.utc)
    row = {"device_id": "pc@mesh+1", "connected": connected, "credential_generation": None,
           "source": "mesh", "received_at": (now-timedelta(seconds=age)).isoformat()}
    assert mesh_presence_online(row, device_id="pc@mesh+1", now=now) is expected
    assert not mesh_presence_online(row, device_id="foreign", now=now)


@pytest.mark.parametrize("blocked", ["revoked", "credential_expired"])
def test_mesh_receipt_joins_canonical_source_without_reviving_revoked_binding(blocked):
    now = existing.NOW
    facts = existing._facts()
    row = {"device_id": existing.DEVICE_ID, "connected": True, "credential_generation": None,
           "source": "mesh", "received_at": now.isoformat()}
    facts["mesh_presence"] = mesh_presence_facts(row, facts["binding"])
    assert CanonicalClawLocalAccessTruthSource._canonical_state(facts, now=now).value == "online"
    facts["canonical_state"] = blocked
    assert CanonicalClawLocalAccessTruthSource._canonical_state(facts, now=now).value == blocked


@pytest.mark.parametrize("age,expected", [(0, "connected"), (181, "unavailable")])
def test_multiple_mesh_only_cards_feed_the_shared_connected_chip(monkeypatch, age, expected):
    ids = ["pc@mesh+1", "pc@mesh+2"]
    rows = [{"account_ref": "acct_5553", "device_id": device, "node_ref": device,
             "root_ref": "root", "path_relative": "verify.txt", "file_path": "C:/verify.txt", "command_exec": True}
            for device in ids]
    rows.append({**rows[0], "device_id": "foreign@pc+3", "node_ref": "foreign@pc+3", "account_ref": "foreign"})
    source = OracleMeshReturnSource(rows, "synthetic-secret-5553-only", mode=EXECUTION_MODE_MESH)
    store = D1MeshDevicePresenceStore(D1())
    async def prepare():
        for device in ids + ["foreign@pc+3"]:
            await store.upsert(device_id=device, connected=True, received_at=datetime.now(timezone.utc)-timedelta(seconds=age), credential_generation=None, source="mesh")
    asyncio.run(prepare())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(oracle_mesh_return_source=source, mesh_device_presence_store=store)))
    async def scope(*args, **kwargs):
        return PcConnectorScope(status="ready", account_ref="acct_5553", workspace_ref="ws", session_id="session")
    monkeypatch.setattr(directory, "resolve_pc_connector_scope", scope)
    response = asyncio.run(directory._read_device_directory(request, uid="owner", workspace_id="ws"))
    payload = json.loads(response.body)
    assert [d["deviceId"] for d in payload["devices"]] == ids
    assert all(d["state"] == ("CONNECTED" if age == 0 else "ACTION_REQUIRED")
               and d["usable"] is (age == 0) and d["executable"] for d in payload["devices"])
    script = r'''
const fs=require('fs'); global.window={addEventListener(){},dispatchEvent(){}};
global.document={readyState:'complete'};global.CustomEvent=class {};
eval(fs.readFileSync(process.argv[1],'utf8'));eval(fs.readFileSync(process.argv[2],'utf8'));
const raw=JSON.parse(fs.readFileSync(0,'utf8'));
const projected=window.PadiemClawLocalHandoff.deriveDeviceDirectory(raw);
console.log(window.PadiemComputerConnectionState.classify({...projected,readCompleted:true,statusCode:'ok'}));
'''
    static = ROOT / "apps/padiem-chat/static"
    result = subprocess.run(["node", "-e", script, str(static/"claw-local-handoff.js"), str(static/"claw-connection-state.js")], input=json.dumps(payload), text=True, capture_output=True, check=True)
    assert result.stdout.strip() == expected
    async def no_scope(*args, **kwargs):
        return PcConnectorScope(status="owner_unavailable")
    monkeypatch.setattr(directory, "resolve_pc_connector_scope", no_scope)
    denied = asyncio.run(directory._read_device_directory(request, uid="foreign", workspace_id="ws"))
    assert json.loads(denied.body)["available"] is False


def test_panel_reuses_verified_mesh_directory_when_broker_is_absent(monkeypatch):
    from app import claw_local_access_routes as panel, claw_memory_routes as memory
    payload = {"available": True, "ownerScoped": True, "devices": [{
        "deviceId": "pc@mesh+1", "executable": True, "state": "CONNECTED",
        "usable": True, "revoked": False, "expired": False}]}
    from starlette.responses import JSONResponse
    calls = []
    async def read(request, **scope):
        calls.append(scope)
        return JSONResponse(payload)
    async def workspace(request, owner):
        assert owner == "owner"
        return "ws"
    monkeypatch.setattr(directory, "_read_device_directory", read)
    monkeypatch.setattr(memory, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(panel, "auth_ready", lambda request: True)
    monkeypatch.setattr(panel, "current_user_id", lambda request: "owner")
    request = SimpleNamespace(query_params={"conversationId": "conv_mesh_test"}, app=SimpleNamespace(state=SimpleNamespace()))
    response = asyncio.run(panel.claw_local_access(request))
    assert json.loads(response.body)["projection"]["device"]["state"] == "CONNECTED"
    assert calls == [{"uid": "owner", "workspace_id": "ws"}]
    payload["selectedDeviceId"] = "different-device"
    assert json.loads(asyncio.run(panel.claw_local_access(request)).body)["available"] is False
