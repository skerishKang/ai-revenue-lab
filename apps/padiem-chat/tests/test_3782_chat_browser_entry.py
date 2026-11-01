"""Chat's browser entry uses the existing owner/device grant and engine bridge."""
import asyncio
from types import SimpleNamespace

import pytest

from app import chat_pc_drive as lane
from app.orchestration_bridge import B62EngineOrchestrationBridge
import test_5573_pc_context_entry as entry
import test_5573_pc_http_boundary as boundary


def test_browser_plan_is_closed_and_model_cannot_widen_it():
    plan = lane.chat_pc_plan_for_tool("browser")
    assert plan["agent_id"] == lane.CHAT_PC_QUERY_AGENT_ID
    assert [step["tool_id"] for step in plan["steps"]] == [
        "claw.pc.browser_open", "claw.pc.browser_read",
        "claw.pc.browser_screenshot", "claw.pc.browser_act",
    ]
    assert lane._tool_arguments_for_plan(plan, entry.DEVICE) == {
        "browser": {"device_id": entry.DEVICE},
    }
    assert lane._declared_plan_for_tool("browser", lane.chat_pc_plan_for_tool("files_write")) == plan
    assert "browser" in {tool.name for tool in lane.pc_tools_for_turn("example.com 열어서 제목 알려 줘")}
    assert "files_write" not in {tool.name for tool in lane.pc_tools_for_turn("example.com 열어서 제목 알려 줘")}


def test_browser_coarse_tool_stages_multi_command_run_and_preserves_provenance(monkeypatch):
    request, b14, bridge, store = entry._wire(monkeypatch)
    text = "example.com 열어서 제목 알려 줘"
    assert entry._run(request, text, selected_tool="browser") == ("ok", entry.CONVERSATION)
    sent = bridge.requests[0]
    assert sent["tool_arguments"] == {"browser": {"device_id": entry.DEVICE}}
    assert sent["agent_plan"] == lane.chat_pc_plan_for_tool("browser")
    assert sent["pc_action_context"][-1] == {"role": "user", "content": text}
    assert store.staged[0]["action"] == "pc_browser_query"
    assert b14.calls == []


@pytest.mark.parametrize("root_state", ["none", "unavailable"])
async def test_native_browser_scope_needs_device_grant_but_no_folder(monkeypatch, root_state):
    app, bridge, store = boundary._wire(monkeypatch)
    async def files_target(*args, **kwargs):
        if root_state == "unavailable":
            raise RuntimeError("file root is unavailable")
        return None, object()
    monkeypatch.setattr("app.oracle_mesh_read_return_routes._engine_pc_files_target", files_target)
    response = await boundary._post(app, "example.com 열어서 제목 알려 줘", pc_run_id=boundary.PC_RUN)
    assert response.status_code == 200, response.text
    assert bridge.requests[0]["pc_tools"] == {
        "device_id": boundary.DEVICE, "allowed_scopes": ["query_drives", "browser"],
    }
    assert store.staged == []  # Only the signed tool callback may promote it.


async def test_wrong_device_still_withholds_browser_authority(monkeypatch):
    app, bridge, _ = boundary._wire(monkeypatch)
    response = await boundary._post(app, "example.com 열어 줘", device_id=boundary.OTHER_DEVICE)
    assert response.status_code == 200
    assert bridge.requests[0].get("pc_tools") is None


def test_real_bridge_accepts_native_browser_scope_and_keeps_subject_device():
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_chat_3782", messages=({"role": "user", "content": "example.com 열어 줘"},),
        skill=SimpleNamespace(id="auto", title="Chat", description="Chat", system_instruction=None,
                              task_type="general", optimize_for="balanced", max_tokens=None),
        model_id="fixture/model", conversation_id=None,
        subject_id="sub_" + "a" * 32, session_id=boundary.PC_RUN,
        pc_tools={"device_id": entry.DEVICE, "allowed_scopes": ["browser"]},
    )
    assert request["subject_id"] == "sub_" + "a" * 32
    assert request["pc_tools"] == {"device_id": entry.DEVICE, "allowed_scopes": ["browser"]}


def test_file_lane_ops_are_unchanged_and_exclude_browser():
    from app.oracle_mesh_read_return_routes import _PC_FILES_OPS
    assert not any("browser" in op for op in _PC_FILES_OPS)
    from app.history import is_multi_command_action
    assert is_multi_command_action("pc_browser_query")
