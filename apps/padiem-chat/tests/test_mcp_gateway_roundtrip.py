"""MCP HTTP -> real Chat bridge/SDK -> real Engine/Core -> signed fake PC.

Engine runs in an isolated interpreter because Chat and Engine both use the
``app`` package name. Only canonical identity/PC availability, admission and
the remote PC are fixtures. HTTP routing, credentials, approvals, delegation
storage, SDK wire construction and the common action harness execute normally.
No real provider, PC, token or deployed service is used.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app import mcp_gateway_execution as execution
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.pc_delegation_routes import load_pc_delegation
from test_5222_account_model_selection import BASE, client_for, session
from test_mcp_gateway_account import account_app, setup
from test_mcp_gateway_execution import DEVICE, harness


REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "apps" / "padiem-ai-engine"
PREFIX = "io.modelcontextprotocol/"
CHILD = r'''
import asyncio, contextlib, io, json, sys
from unittest.mock import patch
from tests.test_6460_pc_action_driver import _WritePcEndpoint, _service
from tests.test_5574_pc_read_boundary_end_to_end import _ScriptedModel, _instant_sleep
payload = json.loads(sys.stdin.buffer.read())
pc, model = _WritePcEndpoint(), _ScriptedModel([])
service = _service(model, pc)
with contextlib.redirect_stdout(io.StringIO()), patch.object(asyncio, "sleep", _instant_sleep):
    result = asyncio.run(service.orchestrate_payload(payload))
assert not model.prompts, "External tool execution cannot invoke model selection"
print(json.dumps({"status": result.status_code, "body": result.body, "ops": pc.ops}, ensure_ascii=False))
'''


class EngineProcessTransport:
    """Pass the SDK's exact bytes to the actual service, not a canned result."""

    def __init__(self):
        self.calls = []
        self.ops = []

    async def request(self, *, method, url, headers, body):
        assert method == "POST" and url.endswith("/internal/v1/orchestrate")
        self.calls.append(json.loads(body))
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(map(str, (
            ENGINE, ENGINE / "clients" / "python",
            REPO / "packages" / "padiem-ai-core",
            REPO / "packages" / "padiem-control-plane",
            REPO / "apps" / "korean-ai-code-agent" / "src",
        )))
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", CHILD, cwd=ENGINE, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await child.communicate(body)
        assert child.returncode == 0, err.decode()
        result = json.loads(out)
        self.ops.extend(result["ops"])
        return EngineTransportResponse(status=result["status"], headers={},
                                       body=json.dumps(result["body"]).encode())


def combined_app(monkeypatch):
    db, owner, other, store = setup()
    db.conn.executescript((REPO / "apps/padiem-chat/migrations/084_pc_delegations.sql").read_text())
    _, _, history, _ = harness(monkeypatch)
    # Keep server authorities synthetic, but load actual owner settings from
    # the shared DB. Do not replace the gateway executor with a stub.
    monkeypatch.setattr(execution, "load_pc_delegation", load_pc_delegation)
    app = account_app(db, owner, store)
    app.state.history_store = history
    transport = EngineProcessTransport()
    app.state.orchestration_bridge = B62EngineOrchestrationBridge(
        client=PadiemAiEngineClient(transport=transport, app_id="padiem-chat",
            caller_id="padiem-chat", credential="fixture" * 8), store=object())

    async def paired(*, user_id, mesh_node_id):
        if user_id == owner and mesh_node_id == DEVICE:
            return {"mesh_node_id": DEVICE, "roots": [{"path": "."}]}
        return None
    app.state.pc_device_pairing_store = SimpleNamespace(link_for=paired)
    return app, db, owner, other, transport


async def call(client, token, name, arguments, *, version):
    params = {"name": name, "arguments": arguments}
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": version}
    if version == "2026-07-28":
        params["_meta"] = {PREFIX + "protocolVersion": version,
                           PREFIX + "clientCapabilities": {}}
        headers.update({"Mcp-Method": "tools/call", "Mcp-Name": name})
    response = await client.post("/api/mcp", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["2026-07-28", "2025-11-25"])
async def test_real_gateway_roundtrip_and_first_party_approval(monkeypatch, version):
    app, db, owner, other, engine = combined_app(monkeypatch)
    async with client_for(app) as owner_ui, client_for(app) as external:
        owner_ui.cookies.update(session(app, owner))
        issued = await owner_ui.post("/api/account/mcp/tokens", headers={"Origin": BASE},
            json={"name": "MCP integration fixture", "device_id": DEVICE})
        assert issued.status_code == 201
        token = issued.json()["token"]
        token_id = issued.json()["id"]

        read = await call(external, token, "pc_read", {"path": "notes.txt"}, version=version)
        assert read["status"] == "completed", read
        assert engine.ops == ["read"]
        listed = await call(external, token, "pc_list", {"path": "."}, version=version)
        assert listed["status"] == "completed" and listed["output"]["entry_count"] == 2
        assert len(json.loads(listed["output"]["output"])["entries"]) == 2
        found = await call(external, token, "pc_search", {"path": ".", "query": "notes"}, version=version)
        assert found["status"] == "completed" and found["output"]["entry_count"] == 1
        entries = json.loads(found["output"]["output"])["entries"]
        assert len(entries) == 1 and entries[0]["relative_path"] == "notes"
        assert engine.ops == ["read", "list", "list"]

        for name, args in (("pc_write", {"path": "notes.txt", "content": "reviewed bytes"}),
                           ("pc_delete", {"path": "notes.txt"})):
            before = list(engine.ops)
            waiting = await call(external, token, name, args, version=version)
            assert waiting["status"] == "confirmation_required", waiting
            assert engine.ops == before
            pending = (await owner_ui.get("/api/account/mcp/approvals")).json()["approvals"]
            item = next(row for row in pending if row["id"] == waiting["approval_id"])
            assert item["arguments"] == args and item["token_id"] == token_id
            approved = await owner_ui.post("/api/account/mcp/approvals/" + item["id"],
                headers={"Origin": BASE}, json={"decision": "approve", "request_digest": item["request_digest"]})
            assert approved.status_code == 200
            # A normal MCP client cannot fabricate transport metadata. The
            # identical ordinary call must consume the user's exact receipt.
            result = await call(external, token, name, args, version=version)
            assert result["status"] == "completed", result
            assert result["output"]["action_verification"]["status"] == "verified"
            assert engine.ops == before + [name.removeprefix("pc_")]
            again = await call(external, token, name, args, version=version)
            assert again["status"] == "confirmation_required"
            assert engine.ops == before + [name.removeprefix("pc_")]

        policy = {"version": 1, "rules": [{"id": "mcp-rule", "device_id": DEVICE,
            "folder": ".", "actions": ["move"], "mode": "allow", "enabled": True}]}
        saved = await owner_ui.put("/api/account/pc-delegations", headers={"Origin": BASE}, json=policy)
        assert saved.status_code == 200
        moved = await call(external, token, "pc_move", {"path": "notes.txt", "destination": "new.txt"}, version=version)
        assert moved["status"] == "completed", moved
        assert moved["output"]["action_verification"]["status"] == "verified"
        assert engine.ops == ["read", "list", "list", "write", "delete", "move"]
        assert all(row["pc_action_context"] == [] for row in engine.calls)
        assert all(row["pc_gateway"]["token_id"] == token_id for row in engine.calls)
        assert all(row["messages"][0]["role"] == "assistant" for row in engine.calls)
        audit = [dict(row) for row in db.conn.execute("SELECT token_id,tool_name,status FROM padiem_mcp_audit")]
        assert any(row == {"token_id": token_id, "tool_name": "pc_delete", "status": "completed"} for row in audit)

        # Foreign accounts cannot issue a credential for this paired PC.
        owner_ui.cookies.update(session(app, other))
        foreign = await owner_ui.post("/api/account/mcp/tokens", headers={"Origin": BASE},
            json={"name": "Other account", "device_id": DEVICE})
        assert foreign.status_code == 403
        owner_ui.cookies.update(session(app, owner))
        assert (await owner_ui.delete("/api/account/mcp/tokens/" + token_id, headers={"Origin": BASE})).status_code == 200
        refused = await external.post("/api/mcp", headers={"Authorization": "Bearer " + token}, json={})
        assert refused.status_code == 401
        assert engine.ops == ["read", "list", "list", "write", "delete", "move"]
