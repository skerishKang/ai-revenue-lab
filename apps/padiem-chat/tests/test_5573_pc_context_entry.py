"""#5573 interim entry: Mesh-only PC requests run; ordinary turns fall through."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.chat_pc_drive as lane
import app.pc_work_context as pc_work_context
from app.orchestration_bridge import B62EngineOrchestrationBridge

DEVICE = "node/meshdomain1/owner-pc"
CONVERSATION = "chat_" + "c" * 32


class _Bridge(B62EngineOrchestrationBridge):
    def __init__(self):
        super().__init__(client=object(), store=object())
        self.requests = []

    async def start(self, **fields):
        self.requests.append(fields)
        return SimpleNamespace(answer="ok")


class _B14:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, skill=None, additional_system_context=None):
        self.calls.append(additional_system_context)
        return {"answer": "unused"}


class _Store:
    async def record_chat_pc_drive_run(self, **fields):
        return CONVERSATION


async def _always_true(*args, **kwargs):
    return True


async def _save_pair(store, *, uid, conversation_id, user_text, answer):
    return CONVERSATION


def _selection(selected):
    if selected is True:
        status, device_id = pc_work_context.SAVED_SELECTION_SELECTED, DEVICE
    elif selected is False:
        status, device_id = pc_work_context.SAVED_SELECTION_UNAVAILABLE, None
    else:
        status, device_id = pc_work_context.SAVED_SELECTION_NONE, None

    async def _read(request, *, owner_id, workspace_id):
        return SimpleNamespace(status=status, device_id=device_id)

    return _read


def _wire(monkeypatch, *, selected=True, devices=True, mesh_ready=True):
    context = pc_work_context.PcWorkContext(
        broker_status="ready" if devices else "no_device",
        devices=(
            pc_work_context.PcWorkDevice(DEVICE, None, "CONNECTED", True),
        ) if devices else (),
        execution=pc_work_context.PcExecutionTarget(
            status="ready" if mesh_ready else "no_target",
            device_id=DEVICE if mesh_ready else None,
        ),
        mapping="confirmed" if mesh_ready else "unknown",
        selected_device_id=DEVICE if selected is True else None,
    )

    async def _resolve_context(request, **kwargs):
        return context

    b14 = _B14()
    bridge = _Bridge()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            b14_client=b14, orchestration_bridge=bridge, history_store=_Store(),
        )),
        cookies={},
    )
    monkeypatch.setattr(lane, "auth_ready", lambda req: True)
    monkeypatch.setattr(lane, "current_user_id", lambda req: "usr_5573")
    monkeypatch.setattr(lane, "_append_lane_answer", _always_true)
    monkeypatch.setattr(lane, "_save_pair", _save_pair)

    async def _owner(request, uid):
        return SimpleNamespace(session_id="sess_5573"), "usr_5573", "tenant-1"

    async def _grant(request, session, *, device_id=None):
        return True

    monkeypatch.setattr(lane, "_resolve_chat_owner", _owner)
    monkeypatch.setattr(lane, "_check_mesh_grant", _grant)
    monkeypatch.setattr(pc_work_context, "read_saved_device_selection", _selection(selected))
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", _resolve_context)
    monkeypatch.setattr(pc_work_context, "render_pc_work_context", lambda ctx: "selected PC: " + DEVICE)
    return request, b14, bridge


def _run(request, text, messages=None):
    return asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=text, skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None, tier="free",
        conversation_messages=messages,
    ))


def test_one_engine_call_with_the_files_plan(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    result = _run(request, "\ub0b4 PC\uc758 5015-conditions-20261022 \ud3f4\ub354 \ubaa9\ub85d")
    assert result == ("ok", CONVERSATION)
    assert len(bridge.requests) == 1
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_explicit_pc_follow_up_carries_the_prior_turns(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    history = [
        {"role": "user", "content": "5015-conditions-20261022 \ud3f4\ub354\ub97c \ubd24\uc5b4"},
        {"role": "assistant", "content": "\ubaa9\ub85d\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4."},
        {"role": "user", "content": "\ub0b4 PC\uc758 \uadf8 \ud3f4\ub354 \ud30c\uc77c \ubaa9\ub85d \ubcf4\uc5ec\uc918"},
    ]
    result = _run(request, history[-1]["content"], messages=history)
    assert result == ("ok", CONVERSATION)
    context = bridge.requests[0]["additional_system_context"]
    assert history[0]["content"] in context
    assert history[1]["content"] in context
    assert b14.calls == []


def test_unclassified_followup_keeps_ordinary_lane(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    assert _run(request, "\uadf8 \ud3f4\ub354 \uc548\uc5d0 \ubb50 \uc788\uc5b4?") is None
    assert bridge.requests == []
    assert b14.calls == []


def test_unreadable_selection_fails_closed_before_any_call(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, selected=False)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "\ub0b4 PC \ud30c\uc77c \ubaa9\ub85d")
    assert excinfo.value.code == "chat_pc_selection_unavailable"
    assert bridge.requests == []
    assert b14.calls == []


def test_authority_failure_falls_through_without_a_call(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    assert _run(request, "\ub0b4 PC\uc758 \ud3f4\ub354 \ud30c\uc77c \ubaa9\ub85d \ubcf4\uc5ec\uc918") is None
    assert bridge.requests == []
    assert b14.calls == []



def test_browser_supplied_target_is_refused_when_it_mismatches(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        asyncio.run(lane.execute_chat_pc_drive_lane(
            request, user_text="\ub0b4 PC\uc758 \ud3f4\ub354 \ubaa9\ub85d", skill=SimpleNamespace(id="auto"),
            model_id="m", conversation_id=None, tier="free",
            device_id="node/meshdomain1/other-pc",
        ))
    assert excinfo.value.code == "chat_pc_selection_stale"
    assert bridge.requests == []


def test_mesh_only_pc_list_request_enters_files_lane(monkeypatch):
    """(a) An empty Broker directory never hides a usable Mesh target."""
    request, b14, bridge = _wire(monkeypatch, devices=False)
    calls = []
    execute = lane._execute_chat_pc_files_lane

    async def _record(request, **kwargs):
        calls.append(kwargs)
        return await execute(request, **kwargs)

    monkeypatch.setattr(lane, "_execute_chat_pc_files_lane", _record)
    result = _run(request, "\ub0b4 PC\uc758 sample \ud3f4\ub354 \ud30c\uc77c \ubaa9\ub85d \ubcf4\uc5ec\uc918")
    assert result == ("ok", CONVERSATION)
    assert len(calls) == len(bridge.requests) == 1
    assert calls[0]["device_id"] == DEVICE
    assert bridge.requests[0]["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_general_question_with_verified_pc_keeps_ordinary_lane(monkeypatch):
    """(b) A verified PC does not route a weather question to Engine."""
    request, b14, bridge = _wire(monkeypatch)

    async def _unexpected(*args, **kwargs):
        pytest.fail("ordinary turn must not enter the PC files lane")

    monkeypatch.setattr(lane, "_execute_chat_pc_files_lane", _unexpected)
    assert _run(request, "\uc624\ub298 \ub0a0\uc528 \uc5b4\ub54c?") is None
    assert bridge.requests == []
    assert b14.calls == []


def _run_selected(request, text, tool, plan=None):
    return asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=text, skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None, tier="free",
        selected_tool=tool,
        declared_plan=(
            plan if plan is not None else lane.chat_pc_plan_for_tool(tool)
        ),
    ))


def test_model_files_list_tool_call_runs_the_list_only_plan(monkeypatch):
    """3-B-2: a files_list call carries no read step, so no read is dispatched."""
    request, b14, bridge = _wire(monkeypatch)
    result = _run_selected(request, "\uadf8 \ud3f4\ub354 \uc548\uc5d0 \ubb50 \uc788\uc5b4?", "files_list")

    assert result == ("ok", CONVERSATION)
    sent = bridge.requests[0]
    assert [step["step_id"] for step in sent["agent_plan"]["steps"]] == [
        "list_files",
    ]
    assert all(
        step["tool_id"] != "claw.pc.read_file"
        for step in sent["agent_plan"]["steps"]
    )
    assert sent["tool_arguments"] == {"files_list": {"device_id": DEVICE}}
    assert b14.calls == []


def test_model_files_tool_call_keeps_the_list_read_plan(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    result = _run_selected(request, "\uadf8 \ud30c\uc77c \ub0b4\uc6a9 \uc54c\ub824\uc918", "files")

    assert result == ("ok", CONVERSATION)
    sent = bridge.requests[0]
    assert [step["step_id"] for step in sent["agent_plan"]["steps"]] == [
        "list_files", "read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_model_query_drives_tool_call_uses_the_drive_plan(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    result = _run_selected(request, "\ub4dc\ub77c\uc774\ube0c \uc54c\ub824\uc918", "query_drives")

    assert result == ("ok", CONVERSATION)
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.query_drives",
    ]
    assert sent["tool_arguments"] == {"query_drives": {"device_id": DEVICE}}
    assert b14.calls == []


def test_caller_plan_cannot_widen_the_tool_plan(monkeypatch):
    request, _, bridge = _wire(monkeypatch)
    _run_selected(
        request, "\uadf8 \ud3f4\ub354 \uc548\uc5d0 \ubb50 \uc788\uc5b4?", "files_list",
        plan=lane.chat_pc_plan_for_tool("files"),
    )

    assert [step["step_id"] for step in bridge.requests[0]["agent_plan"]["steps"]] == [
        "list_files",
    ]


def test_unknown_model_tool_falls_through_without_a_call(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    assert _run_selected(request, "\uc548\ub155", "shell_exec") is None
    assert bridge.requests == []
    assert b14.calls == []


def test_tools_available_requires_a_verified_target(monkeypatch):
    request, _, _ = _wire(monkeypatch)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is True

    request, _, _ = _wire(monkeypatch, devices=False, mesh_ready=False)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is False

    request, _, _ = _wire(monkeypatch)
    assert asyncio.run(lane.chat_pc_tools_available(request, uid=None)) is False

    async def _denied(request, session, *, device_id=None):
        return False

    monkeypatch.setattr(lane, "_check_mesh_grant", _denied)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is False


def test_pc_list_without_devices_or_mesh_returns_truthful_refusal(monkeypatch):
    """(c) No target means a fixed refusal, never a guessed model answer."""
    request, b14, bridge = _wire(
        monkeypatch, selected=None, devices=False, mesh_ready=False,
    )
    saved = []

    async def _record_pair(store, **kwargs):
        saved.append(kwargs)
        return CONVERSATION

    monkeypatch.setattr(lane, "_save_pair", _record_pair)
    result = _run(request, "\ub0b4 PC\uc758 sample \ud3f4\ub354 \ud30c\uc77c \ubaa9\ub85d \ubcf4\uc5ec\uc918")
    assert result[0].startswith(
        "\uac80\uc99d\ub41c PC \uc5f0\uacb0\uc744 \ud655\uc778\ud558\uc9c0 \ubabb\ud574 \ud30c\uc77c \ubaa9\ub85d\uc744"
    )
    assert result[1] == CONVERSATION
    assert len(saved) == 1 and saved[0]["answer"] == result[0]
    assert bridge.requests == []
    assert b14.calls == []
