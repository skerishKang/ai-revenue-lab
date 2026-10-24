"""#5573 (3-C-2) entry: a model-selected PC tool runs the Mesh lane.

No natural-language table decides PC entry any more. These drive the real lane
module with a fake Engine transport, so no provider and no PC is contacted, and
pin: any wording reaches the lane through the model's tool call, a turn with no
tool call never does, and the server still owns the owner/grant/target
verification and the plan ceiling.
"""

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
    def __init__(self):
        self.staged = []

    async def record_chat_pc_drive_run(self, **fields):
        self.staged.append(fields)
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
    store = _Store()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            b14_client=b14, orchestration_bridge=bridge, history_store=store,
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
    return request, b14, bridge, store


def _run(request, text, messages=None, *, selected_tool="files", run_id=None):
    return asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=text, skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None,
        conversation_messages=messages,
        selected_tool=selected_tool, run_id=run_id,
    ))


def test_one_engine_call_with_the_files_plan(monkeypatch):
    """The wording the deleted keyword table missed runs on the tool call.

    "PC의" without "내" was reported on #5572 as dropping to an ordinary model
    answer: the table only carried "내pc". Entry no longer reads the sentence.
    """
    request, b14, bridge, _store = _wire(monkeypatch)
    result = _run(request, "PC의 5015-conditions-20261022 폴더 목록")
    assert result == ("ok", CONVERSATION)
    assert len(bridge.requests) == 1
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_explicit_pc_follow_up_carries_the_prior_turns(monkeypatch):
    request, b14, bridge, _store = _wire(monkeypatch)
    history = [
        {"role": "user", "content": "5015-conditions-20261022 폴더를 봤어"},
        {"role": "assistant", "content": "목록을 확인했습니다."},
        {"role": "user", "content": "그 폴더 파일 목록 보여줘"},
    ]
    result = _run(request, history[-1]["content"], messages=history)
    assert result == ("ok", CONVERSATION)
    context = bridge.requests[0]["additional_system_context"]
    assert history[0]["content"] in context
    assert history[1]["content"] in context
    assert b14.calls == []


def test_no_model_tool_call_keeps_the_ordinary_path(monkeypatch):
    """A turn the model answers in text never reaches the lane, in any wording."""
    request, b14, bridge, _store = _wire(monkeypatch)
    for text in (
        "그 폴더 안에 뭐 있어?",
        "내 PC의 폴더 목록",
        "제 컴퓨터에서 문서 폴더 좀",
        "오늘 날씨 어때?",
    ):
        assert _run(request, text, selected_tool=None) is None
    assert bridge.requests == []
    assert b14.calls == []


def test_unreadable_selection_fails_closed_before_any_call(monkeypatch):
    request, b14, bridge, _store = _wire(monkeypatch, selected=False)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "내 PC 파일 목록")
    assert excinfo.value.code == "chat_pc_selection_unavailable"
    assert bridge.requests == []
    assert b14.calls == []


def test_authority_failure_on_a_tool_turn_is_a_handled_failure(monkeypatch):
    """A model-selected tool with no verified context is a handled failure."""
    request, b14, bridge, _store = _wire(monkeypatch)

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "내 PC의 폴더 파일 목록 보여줘")
    assert excinfo.value.code == "chat_pc_owner_unavailable"
    assert bridge.requests == []
    assert b14.calls == []


def test_authority_failure_leaves_an_ordinary_turn_untouched(monkeypatch):
    """The same failure must not disturb a turn with no tool call."""
    request, b14, bridge, _store = _wire(monkeypatch)

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    assert _run(request, "오늘 날씨 어때?", selected_tool=None) is None
    assert bridge.requests == []



def test_browser_supplied_target_is_refused_when_it_mismatches(monkeypatch):
    request, b14, bridge, _store = _wire(monkeypatch)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        asyncio.run(lane.execute_chat_pc_drive_lane(
            request, user_text="내 PC의 폴더 목록", skill=SimpleNamespace(id="auto"),
            model_id="m", conversation_id=None,
            selected_tool="files",
            device_id="node/meshdomain1/other-pc",
        ))
    assert excinfo.value.code == "chat_pc_selection_stale"
    assert bridge.requests == []


def test_mesh_only_pc_list_request_enters_files_lane(monkeypatch):
    """(a) An empty Broker directory never hides a usable Mesh target."""
    request, b14, bridge, _store = _wire(monkeypatch, devices=False)
    calls = []
    execute = lane._execute_chat_pc_files_lane

    async def _record(request, **kwargs):
        calls.append(kwargs)
        return await execute(request, **kwargs)

    monkeypatch.setattr(lane, "_execute_chat_pc_files_lane", _record)
    result = _run(request, "내 PC의 sample 폴더 파일 목록 보여줘")
    assert result == ("ok", CONVERSATION)
    assert len(calls) == len(bridge.requests) == 1
    assert calls[0]["device_id"] == DEVICE
    assert bridge.requests[0]["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_general_question_with_verified_pc_keeps_ordinary_lane(monkeypatch):
    """(b) A verified PC alone never routes an ordinary question to Engine."""
    request, b14, bridge, _store = _wire(monkeypatch)

    async def _unexpected(*args, **kwargs):
        pytest.fail("ordinary turn must not enter the PC files lane")

    monkeypatch.setattr(lane, "_execute_chat_pc_files_lane", _unexpected)
    assert _run(request, "오늘 날씨 어때?", selected_tool=None) is None
    assert bridge.requests == []
    assert b14.calls == []


def _run_selected(request, text, tool, plan=None):
    return asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=text, skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None,
        selected_tool=tool,
        declared_plan=(
            plan if plan is not None else lane.chat_pc_plan_for_tool(tool)
        ),
    ))


def test_model_files_list_tool_call_runs_the_list_only_plan(monkeypatch):
    """3-B-2: a files_list call carries no read step, so no read is dispatched."""
    request, b14, bridge, _store = _wire(monkeypatch)
    result = _run_selected(request, "그 폴더 안에 뭐 있어?", "files_list")

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
    request, b14, bridge, _store = _wire(monkeypatch)
    result = _run_selected(request, "그 파일 내용 알려줘", "files")

    assert result == ("ok", CONVERSATION)
    sent = bridge.requests[0]
    assert [step["step_id"] for step in sent["agent_plan"]["steps"]] == [
        "list_files", "read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}
    assert b14.calls == []


def test_a_caller_narrowing_is_applied_but_never_widens(monkeypatch):
    """A supplied plan can only take the read away from a ``files`` call.

    The request scope is the intersection of what the user asked for and what
    the server allows, so a narrower declaration is honoured and anything else
    falls back to the exact plan the tool name selects.
    """
    request, b14, bridge, _store = _wire(monkeypatch)
    _run_selected(
        request, "이 파일 내용 알려줘", "files",
        plan=lane.chat_pc_plan_for_tool("files_list"),
    )
    assert [
        step["step_id"] for step in bridge.requests[0]["agent_plan"]["steps"]
    ] == ["list_files"]
    assert bridge.requests[0]["tool_arguments"] == {
        "files_list": {"device_id": DEVICE},
    }


def test_model_query_drives_tool_call_uses_the_drive_plan(monkeypatch):
    request, b14, bridge, _store = _wire(monkeypatch)
    result = _run_selected(request, "드라이브 알려줘", "query_drives")

    assert result == ("ok", CONVERSATION)
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.query_drives",
    ]
    assert sent["tool_arguments"] == {"query_drives": {"device_id": DEVICE}}
    assert b14.calls == []


def test_caller_plan_cannot_widen_the_tool_plan(monkeypatch):
    request, _, bridge, _store = _wire(monkeypatch)
    _run_selected(
        request, "그 폴더 안에 뭐 있어?", "files_list",
        plan=lane.chat_pc_plan_for_tool("files"),
    )

    assert [step["step_id"] for step in bridge.requests[0]["agent_plan"]["steps"]] == [
        "list_files",
    ]


def test_unknown_model_tool_falls_through_without_a_call(monkeypatch):
    request, b14, bridge, _store = _wire(monkeypatch)
    assert _run_selected(request, "안녕", "shell_exec") is None
    assert bridge.requests == []
    assert b14.calls == []


def test_tools_available_requires_a_verified_target(monkeypatch):
    request, _, _, _store = _wire(monkeypatch)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is True

    request, _, _, _store = _wire(monkeypatch, devices=False, mesh_ready=False)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is False

    request, _, _, _store = _wire(monkeypatch)
    assert asyncio.run(lane.chat_pc_tools_available(request, uid=None)) is False

    async def _denied(request, session, *, device_id=None):
        return False

    monkeypatch.setattr(lane, "_check_mesh_grant", _denied)
    assert asyncio.run(
        lane.chat_pc_tools_available(request, uid="usr_5573")
    ) is False


def test_pc_list_without_devices_or_mesh_returns_truthful_refusal(monkeypatch):
    """(c) No target means a fixed refusal, never a guessed model answer."""
    request, b14, bridge, _store = _wire(
        monkeypatch, selected=None, devices=False, mesh_ready=False,
    )
    saved = []

    async def _record_pair(store, **kwargs):
        saved.append(kwargs)
        return CONVERSATION

    monkeypatch.setattr(lane, "_save_pair", _record_pair)
    result = _run(request, "내 PC의 sample 폴더 파일 목록 보여줘")
    assert result[0].startswith(
        "검증된 PC 연결을 확인하지 못해 파일 목록을"
    )
    assert result[1] == CONVERSATION
    assert len(saved) == 1 and saved[0]["answer"] == result[0]
    assert bridge.requests == []
    assert b14.calls == []


CLIENT_RUN = "chat_pcq_" + "b" * 32


def test_model_selected_tool_stages_the_browser_run_handle(monkeypatch):
    """#5573/#5735/#5567: the tool turn is the run the UI already waits on.

    The browser mints its ``chat_pcq_`` handle before submit so a dropped
    connection can recover the result and so the staged row can move
    ``pending -> running`` when the Engine reaches a real PC step. A
    model-selected tool must stage under that same handle, not a fresh id.
    """
    request, b14, bridge, store = _wire(monkeypatch)
    result = _run(
        request, "PC의 5015-conditions 폴더 목록만 보여줘",
        selected_tool="files_list", run_id=CLIENT_RUN,
    )

    assert result == ("ok", CONVERSATION)
    assert store.staged[0]["run_id"] == CLIENT_RUN
    assert store.staged[0]["action"] == "pc_files_query"
    assert bridge.requests[0]["session_id"] == CLIENT_RUN
    assert [step["step_id"] for step in bridge.requests[0]["agent_plan"]["steps"]] == [
        "list_files",
    ]


def test_a_drive_turn_is_staged_as_a_drive_run(monkeypatch):
    """The staged row says what the model actually asked for."""
    request, b14, bridge, store = _wire(monkeypatch)
    result = _run(
        request, "PC에 어떤 드라이브가 있는지 보여줘",
        selected_tool="query_drives",
    )

    assert result == ("ok", CONVERSATION)
    assert store.staged[0]["action"] == "pc_drive_query"
    assert store.staged[0]["title_prefix"] == "PC 드라이브 조회: "
