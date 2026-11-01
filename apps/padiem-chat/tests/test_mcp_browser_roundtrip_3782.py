"""Actual MCP -> Chat bridge/SDK -> Engine/harness -> signed fake browser.

Only server identity/availability and the PC boundary are synthetic. Each MCP
call starts a fresh Engine process, proving continuation is server storage,
not a Python global or externally supplied browser URL.
"""
import hashlib
import json

import pytest

from app.local_r2 import LocalDiskR2
from test_5222_account_model_selection import BASE, client_for, session
from test_mcp_gateway_execution import DEVICE
import test_mcp_gateway_roundtrip as roundtrip


PNG = b"\x89PNG\r\n\x1a\nsynthetic image bytes"
BROWSER_CHILD = r'''
import asyncio, contextlib, hashlib, hmac, io, json, sys
from unittest.mock import patch
from tests.test_6460_pc_action_driver import _service
from tests.test_5574_pc_read_boundary_end_to_end import _ScriptedModel, _instant_sleep, _Response, SIGNING_SECRET
PNG = b"\x89PNG\r\n\x1a\nsynthetic image bytes"
class PC:
    def __init__(self):
        self.ops, self.rows = [], {}
    async def fetch(self, request):
        assert request.url.endswith('/engine-pc-browser')
        p = json.loads(request.body)
        prefix = request.headers['X-Claw-Engine-Time'].encode() + b'.' + request.body.encode()
        assert request.headers['X-Claw-Engine-Proof'] == hmac.new(SIGNING_SECRET.encode(), prefix, hashlib.sha256).hexdigest()
        encoded = request.headers['X-Claw-PC-Scope']
        assert request.headers['X-Claw-PC-Scope-Proof'] == hmac.new(SIGNING_SECRET.encode(), prefix + b'.' + encoded.encode(), hashlib.sha256).hexdigest()
        assert json.loads(encoded)['admitted'] == 'browser'
        if p['mode'] == 'dispatch':
            self.ops.append(p)
            op = p['op']
            url = p['arguments']['url'] if op == 'browser_open' else p['page_url']
            assert url == 'https://example.com/'
            did = 'dsp_' + 'b' * 32
            row = {'dispatch_id': did, 'run_id': p['run_id'], 'kind': 'command', 'device_id': p['device_id']}
            result = {'state': {'browser_open':'opened', 'browser_read':'read', 'browser_screenshot':'captured', 'browser_act':'acted'}[op],
                      'url': url, 'title': 'Example Domain'}
            if op == 'browser_read':
                result.update(text='Example Domain', links=[], truncated='false')
            if op == 'browser_act':
                result.update(action=p['arguments']['action'], verified=True, observation={'url':url, 'title':'Example Domain'})
            if op == 'browser_screenshot':
                result['capture'] = {'url':'/api/claw/connector/browser-captures/' + did, 'mime_type':'image/png',
                                     'bytes':len(PNG), 'sha256':hashlib.sha256(PNG).hexdigest()}
            self.rows[did] = (row, result)
            return _Response({'ok':True, 'dispatch':row})
        row, result = self.rows[p['dispatch_id']]
        if p['mode'] == 'command_status':
            return _Response({'ok':True, 'dispatch':{**row, 'state':'done'}})
        assert p['mode'] == 'result'
        return _Response({'ok':True, 'dispatch':{**row, 'state':'done', 'exit_code':0, 'termination':'exited',
                           'output':json.dumps({'ok':True, 'result':result})}})
payload = json.loads(sys.stdin.buffer.read())
pc, model = PC(), _ScriptedModel([])
service = _service(model, pc)
with contextlib.redirect_stdout(io.StringIO()), patch.object(asyncio, 'sleep', _instant_sleep):
    result = asyncio.run(service.orchestrate_payload(payload))
assert not model.prompts, 'External browser calls must not invent user speech through a model'
print(json.dumps({'status':result.status_code, 'body':result.body, 'ops':pc.ops}, ensure_ascii=False))
'''


class History:
    def __init__(self, bucket):
        self.full_context_bucket, self.runs = bucket, []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return kwargs.get("conversation_id") or "chat_" + "a" * 32

    async def get_conversation(self, user_id, conversation_id, **kwargs):
        if any(row["user_id"] == user_id for row in self.runs):
            return {"id": conversation_id}
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["2026-07-28", "2025-11-25"])
async def test_browser_roundtrip_continuity_capture_and_sensitive_question(monkeypatch, tmp_path, version):
    monkeypatch.setattr(roundtrip, "CHILD", BROWSER_CHILD)
    app, db, owner, other, engine = roundtrip.combined_app(monkeypatch)
    history = History(LocalDiskR2(tmp_path))
    app.state.history_store = history
    captures = []
    async def stored_capture(store, *, user_id, dispatch_id, device_id):
        assert store is history
        captures.append((user_id, device_id, dispatch_id))
        return PNG, hashlib.sha256(PNG).hexdigest()
    monkeypatch.setattr("app.claw_pc_browser_routes.read_browser_capture", stored_capture)
    async with client_for(app) as owner_ui, client_for(app) as external:
        owner_ui.cookies.update(session(app, owner))
        issued = await owner_ui.post("/api/account/mcp/tokens", headers={"Origin": BASE},
            json={"name": "Browser integration fixture", "device_id": DEVICE})
        assert issued.status_code == 201
        token, token_id = issued.json()["token"], issued.json()["id"]
        async def call(name, args):
            return await roundtrip.call(external, token, name, args, version=version)

        missing = await call("pc_browser_read", {})
        assert missing["status"] == "confirmation_required" and not engine.calls
        opened = await call("pc_browser_open", {"url": "https://example.com/"})
        assert opened["status"] == "completed", opened
        assert opened["browser_context_saved"] is True
        read = await call("pc_browser_read", {})
        assert read["status"] == "completed", read
        assert read["output"]["title"] == "Example Domain"
        assert "Example Domain" in read["output"]["output"]
        screenshot = await call("pc_browser_screenshot", {})
        assert screenshot["status"] == "completed", screenshot
        assert "_browser_image" not in screenshot
        assert captures == [(owner, DEVICE, "dsp_" + "b" * 32)]
        safe = await call("pc_browser_act", {"action": "click", "text": "More information"})
        assert safe["status"] == "completed", safe

        for target in ("Sign in", "Pay now", "Publish", "Send"):
            count = len(engine.ops)
            asked = await call("pc_browser_act", {"action": "click", "name": target})
            assert asked["status"] == "confirmation_required", asked
            assert asked["confirmation_kind"] == "conversation"
            assert "approval_id" not in asked and len(engine.ops) == count
            assert asked["conversation_id"] == opened["conversation_id"]
        assert (await owner_ui.get("/api/account/mcp/approvals")).json()["approvals"] == []
        assert [p["op"] for p in engine.ops] == ["browser_open", "browser_read", "browser_screenshot", "browser_act"]
        assert [p["page_url"] for p in engine.ops] == [None] + ["https://example.com/"] * 3
        assert all(p["device_id"] == DEVICE for p in engine.ops)
        assert all(wire["pc_action_context"] == [] for wire in engine.calls)
        assert all(wire["pc_gateway"]["token_id"] == token_id for wire in engine.calls)
        assert all(wire["pc_gateway"]["browser_context"] == {"url": "https://example.com/"} for wire in engine.calls[1:])
        assert all(row["action"] == "pc_browser_query" for row in history.runs)
        assert all(row["conversation_id"] == opened["conversation_id"] for row in history.runs[1:])
        audit = [dict(row) for row in db.conn.execute("SELECT token_id, tool_name, status FROM padiem_mcp_audit")]
        assert any(row == {"token_id": token_id, "tool_name": "pc_browser_read", "status": "completed"} for row in audit)

        # Another verified token for the same device cannot borrow this page.
        newer = await owner_ui.post("/api/account/mcp/tokens", headers={"Origin": BASE},
            json={"name": "Separate browser client", "device_id": DEVICE})
        count = len(engine.calls)
        isolated = await roundtrip.call(external, newer.json()["token"], "pc_browser_read", {}, version=version)
        assert isolated["status"] == "confirmation_required" and len(engine.calls) == count
        assert (await owner_ui.delete("/api/account/mcp/tokens/" + token_id, headers={"Origin": BASE})).status_code == 200
        refused = await external.post("/api/mcp", headers={"Authorization": "Bearer " + token}, json={})
        assert refused.status_code == 401
