"""#5573 Option A: one Engine call decides the PC tool, no pre-classification."""

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


_DEVICES = [SimpleNamespace(device_id=DEVICE, state="READY")]


async def _resolve_context(request, **kwargs):
    devices = _DEVICES if _WIRE_DEVICES[0] else []
    return SimpleNamespace(
        devices=devices,
        selected_confirmed=True,
        execution=SimpleNamespace(ready=True),
    )


_WIRE_DEVICES = [True]


def _wire(monkeypatch, *, selected=True, devices=True):
    _WIRE_DEVICES[0] = devices
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


def test_follow_up_without_keywords_carries_the_prior_turns(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    history = [
        {"role": "user", "content": "5015-conditions-20261022 \ud3f4\ub354\ub97c \ubd24\uc5b4"},
        {"role": "assistant", "content": "\ubaa9\ub85d\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4."},
        {"role": "user", "content": "\uadf8 \ud3f4\ub354 \uc548\uc5d0 \ubb50 \uc788\uc5b4?"},
    ]
    result = _run(request, history[-1]["content"], messages=history)
    assert result == ("ok", CONVERSATION)
    context = bridge.requests[0]["additional_system_context"]
    assert history[0]["content"] in context
    assert history[1]["content"] in context
    assert b14.calls == []


def test_no_verified_pc_makes_no_call(monkeypatch):
    request, b14, bridge = _wire(monkeypatch, selected=None, devices=False)
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
    assert _run(request, "\uc624\ub298 \ub0a8\uc528 \uc5b4\ub54c?") is None
    assert bridge.requests == []
    assert b14.calls == []


def test_browser_supplied_target_is_refused_when_it_mismatches(monkeypatch):
    request, b14, bridge = _wire(monkeypatch)
    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        asyncio.run(lane.execute_chat_pc_drive_lane(
            request, user_text="PC\uc758 \ud3f4\ub354", skill=SimpleNamespace(id="auto"),
            model_id="m", conversation_id=None, tier="free",
            device_id="node/meshdomain1/other-pc",
        ))
    assert excinfo.value.code == "chat_pc_selection_stale"
    assert bridge.requests == []
