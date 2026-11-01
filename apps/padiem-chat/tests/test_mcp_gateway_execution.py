"""The MCP adapter emits the real SDK wire after the existing owner gates."""
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


@pytest.mark.parametrize("tool,args", [
    ("pc_list", {"path": "."}), ("pc_search", {"query": "notes"}),
    ("pc_read", {"path": "notes.txt"}),
    ("pc_write", {"path": "notes.txt", "content": "hello"}),
    ("pc_move", {"path": "notes.txt", "destination": "new.txt"}),
    ("pc_delete", {"path": "notes.txt"}),
])
def test_actual_bridge_and_sdk_keep_server_provenance_separate(monkeypatch, tool, args):
    request, transport, history, calls = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, tool, args))
    assert result["status"] == "completed"
    assert len(transport.calls) == 1
    sent = json.loads(transport.calls[0]["body"])
    assert sent["app_id"] == "padiem-chat"
    assert sent["subject_id"] == "sub_" + "a" * 32
    assert sent["pc_action_context"] == []
    assert sent["messages"][0]["role"] == "assistant"
    assert sent["pc_gateway"]["source"] == "mcp"
    assert sent["pc_gateway"]["token_id"] == PRINCIPAL["token_id"]
    assert "approval_id" not in sent["pc_gateway"]
    assert all(item["device_id"] == DEVICE for item in sent["tool_arguments"].values())
    assert sent["pc_delegation"] == {"version": 1, "rules": []}
    assert [call[0] for call in calls[:3]] == ["identity", "context", "grant"]
    assert history.runs[0]["user_id"] == UID
    assert history.runs[0]["user_text"].startswith("외부 AI 도구 요청:")


def test_foreign_device_stops_before_engine_or_history(monkeypatch):
    request, transport, history, _ = harness(monkeypatch, matching=False)
    with pytest.raises(execution.ChatPCDriveError):
        asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_read", {"path": "notes.txt"}))
    assert not transport.calls and not history.runs


def test_exact_store_approval_receipt_only(monkeypatch):
    from app.mcp_gateway_store import mcp_request_digest
    request, transport, _, _ = harness(monkeypatch)
    arguments = {"path": "notes.txt", "content": "hello"}
    approval = {"approval_id": "approval_fixture", "request_digest": mcp_request_digest("pc_write", arguments)}
    asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_write", arguments, approval=approval))
    assert json.loads(transport.calls[-1]["body"])["pc_gateway"]["approval_id"] == "approval_fixture"
    for forged in (True, {"approved": True}, {**approval, "request_digest": "wrong"}):
        with pytest.raises(ValueError):
            asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_write", arguments, approval=forged))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("field", ["device_id", "owner_id", "approved", "pc_gateway", "user_intent"])
def test_client_authority_arguments_rejected(monkeypatch, field):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_delete", {"path": "notes.txt", field: "fake"}))
    assert not transport.calls
