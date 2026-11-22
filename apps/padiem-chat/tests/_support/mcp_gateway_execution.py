"""#8061 25차: shared setup for the MCP gateway execution tests."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app import mcp_gateway_execution as execution
from app.orchestration_bridge import B62EngineOrchestrationBridge


UID = "usr_" + "a" * 32

DEVICE = "dev_" + "c" * 32

PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_token_fixture"}

class RecordingTransport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({"ok": True,
            "orchestration": {"events": [{"event_id": "event_fixture", "run_id": "run_fixture",
                "trace_id": "trace_fixture", "app_id": "padiem-chat", "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": json.dumps({"status": "completed", "answer": "확인했습니다."})}}}).encode())

class History:
    def __init__(self):
        self.runs = []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return "conv_fixture"

def harness(monkeypatch, *, matching=True):
    calls = []
    async def owner(request, uid):
        calls.append(("identity", uid))
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, "workspace_fixture"
    async def context(request, **kwargs):
        calls.append(("context", kwargs))
        return SimpleNamespace(selected_confirmed=matching, tool_available=True,
            selection_offline=False, selected_device_id=DEVICE,
            execution_device_id=DEVICE if matching else "dev_" + "d" * 32)
    async def grant(request, session, **kwargs):
        calls.append(("grant", kwargs))
        return True
    async def delegation(request, uid):
        calls.append(("delegation", uid))
        return {"version": 1, "rules": []}
    async def notice(*args, **kwargs):
        calls.append(("notice", kwargs))
        return True
    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    transport, history = RecordingTransport(), History()
    bridge = B62EngineOrchestrationBridge(client=PadiemAiEngineClient(transport=transport,
        app_id="padiem-chat", caller_id="padiem-chat", credential="fixture" * 8), store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history)))
    return request, transport, history, calls
