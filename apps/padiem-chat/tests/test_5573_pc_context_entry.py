"""#5573: the verified PC selection plus one model step routes the turn.

No keyword list decides entry and no word list picks the plan: the model
returns one closed action and the lane sends the matching plan.
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
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, messages, skill, additional_system_context=None):
        self.calls.append({"messages": tuple(messages), "contract": additional_system_context})
        return {"answer": self.answers.pop(0)}


class _Store:
    async def record_chat_pc_drive_run(self, **fields):
        return CONVERSATION


def _context():
    return SimpleNamespace(
        devices=[SimpleNamespace(device_id=DEVICE, state="READY")],
        selected_confirmed=True,
        execution=SimpleNamespace(ready=True),
    )


def _wire(monkeypatch, *, answers, selected=True):
    b14 = _B14(answers)
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
    monkeypatch.setattr(
        pc_work_context, "read_saved_device_selection", _selection(selected)
    )
    monkeypatch.setattr(
        pc_work_context, "resolve_pc_work_context", _resolve_context
    )
    monkeypatch.setattr(
        pc_work_context, "render_pc_work_context", lambda ctx: "selected PC: " + DEVICE
    )
    return request, b14, bridge


async def _always_true(*args, **kwargs):
    return True


async def _save_pair(store, *, uid, conversation_id, user_text, answer):
    return CONVERSATION


def _selection(selected):
    status = pc_work_context.SAVED_SELECTION_SELECTED if selected else pc_work_context.SAVED_SELECTION_UNAVAILABLE

    async def _read(request, *, owner_id, workspace_id):
        return SimpleNamespace(status=status, device_id=DEVICE if selected else None)

    return _read


async def _resolve_context(request, **kwargs):
    return _context()


def _run(request, text):
    return asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=text, skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None, tier="free",
    ))


def test_context_entry_selects_the_list_only_plan(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'])
    result = _run(request, "5015-conditions-20261022 \ud3f4\ub354\uc5d0 \uc788\ub294 \ud30c\uc77c \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918")
    assert result == ("ok", CONVERSATION)
    assert len(bridge.requests) == 1
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == ["claw.pc.list_files"]
    assert sent["tool_arguments"] == {"files_list": {"device_id": DEVICE}}


def test_context_entry_keeps_the_two_step_read_plan(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_read"}'])
    _run(request, "\uadf8 \ud3f4\ub354\uc5d0\uc11c \ubb50\uac00 \uc788\ub294\uc9c0 \uc54c\ub824\uc918")
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE}}


def test_general_turn_executes_nothing(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"none"}'])
    assert _run(request, "\uc624\ub298 \ub0a0\uc528 \uc5b4\ub54c?") is None
    assert bridge.requests == []
    assert len(b14.calls) == 1


def test_ambiguous_turn_answers_with_a_question(monkeypatch):
    request, b14, bridge = _wire(
        monkeypatch, answers=['{"action":"clarify","answer":"\uc5b4\ub290 PC\uc778\uac00\uc694?"}']
    )
    result = _run(request, "\uadf8\uac83 \uc880 \ubcf4\uc5ec\uc918")
    assert result == ("\uc5b4\ub290 PC\uc778\uac00\uc694?", CONVERSATION)
    assert bridge.requests == []


def test_no_selected_pc_general_turn_still_falls_through(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"none"}'], selected=False)
    assert _run(request, "\uc624\ub298 \ub0a0\uc528 \uc5b4\ub54c?") is None
    assert len(b14.calls) == 1
    assert bridge.requests == []


def test_no_selected_pc_clear_pc_request_is_a_refusal(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'], selected=False)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "PC\uc758 \uadf8 \ud3f4\ub354 \ubaa9\ub85d\ub9cc \ubcf4\uc5ec\uc918")
    assert excinfo.value.code == "chat_pc_selection_unavailable"
    assert bridge.requests == []


def test_authority_failure_falls_through(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=[])

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    assert _run(request, "\uadf8 \ud3f4\ub354 \ubcf4\uc5ec\uc918") is None
    assert bridge.requests == []


def test_keyword_turn_also_uses_the_scope_decision(monkeypatch):
    """The old keyword path no longer keeps its own two-step plan."""
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_list"}'])
    _run(request, "\ub0b4 PC \ub4dc\ub77c\uc774\ube0c \ubaa9\ub85d \uc54c\ub824\uc918")
    sent = bridge.requests[0]
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == ["claw.pc.list_files"]
    assert sent["tool_arguments"] == {"files_list": {"device_id": DEVICE}}


def test_scope_decision_receives_prior_turns(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=['{"action":"files_read"}'])
    history = [
        {"role": "user", "content": "5015-conditions-20261022 \ud3f4\ub354\ub97c \ubd24\uc5b4"},
        {"role": "assistant", "content": "\ubaa9\ub85d\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4."},
        {"role": "user", "content": "\uadf8 \ud3f4\ub354\uc5d0\uc11c \ubb50\uac00 \uc788\uc5b4?"},
    ]
    asyncio.run(lane.execute_chat_pc_drive_lane(
        request, user_text=history[-1]["content"], skill=SimpleNamespace(id="auto"),
        model_id="m", conversation_id=None, tier="free",
        conversation_messages=history,
    ))
    sent = b14.calls[0]["messages"]
    contents = [item["content"] for item in sent]
    assert contents[0] == history[0]["content"]
    assert contents[1] == history[1]["content"]
    assert contents[-1] == history[-1]["content"]


def test_clear_pc_request_without_authority_is_not_generalised(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=[])

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "\ub0b4 PC \ub4dc\ub77c\uc774\ube0c \uc54c\ub824\uc918")
    assert excinfo.value.code == "chat_pc_owner_unavailable"
    assert bridge.requests == []


def test_keyword_pc_request_without_authority_is_a_refusal(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, answers=[])

    async def _denied(request, uid):
        raise lane.ChatPCDriveError("chat_pc_owner_unavailable", "denied", 503)

    monkeypatch.setattr(lane, "_resolve_chat_owner", _denied)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        _run(request, "\ub0b4 PC \ub4dc\ub77c\uc774\ube0c \uc54c\ub824\uc918")
    assert excinfo.value.code == "chat_pc_owner_unavailable"
