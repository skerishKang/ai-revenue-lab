"""#5573: the client's closed PC plan table gains a list-only shape.

The shape is a contract prerequisite only: the Engine must still refuse
``read_file`` for it, so no test here claims a read-free execution.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from padiem_ai_engine_client import (
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)
from app.orchestration_bridge import B62EngineOrchestrationBridge

AGENT = "agent:padiem:chat-pc-query@1"
DEVICE = "node/meshdomain1/owner-pc"


def _list_only_plan():
    return {
        "agent_id": AGENT,
        "steps": [
            {
                "step_id": "list_files",
                "objective": "List the approved folder on the verified owner PC",
                "tool_id": "claw.pc.list_files",
            },
        ],
    }


def _files_plan():
    return {
        "agent_id": AGENT,
        "steps": [
            {"step_id": "list_files", "objective": "list", "tool_id": "claw.pc.list_files"},
            {"step_id": "read_file", "objective": "read", "tool_id": "claw.pc.read_file"},
        ],
    }


class _Transport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(
            status=200,
            body=b'{"ok": true, "orchestration": {"status": "queued"}}',
            headers={"content-type": "application/json"},
        )


def _skill():
    return SimpleNamespace(
        id="auto", title="Padiem Chat", description="Padiem Chat request",
        system_instruction=None, task_type="general", optimize_for="balanced",
        max_tokens=None,
    )


def _send(plan, tool_arguments):
    transport = _Transport()
    client = PadiemAiEngineClient(
        transport=transport, app_id="padiem-chat",
        caller_id="padiem-chat", credential="x" * 64,
    )
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_5573",
        messages=({"role": "user", "content": "list"},),
        skill=_skill(), model_id="unused", conversation_id=None,
        subject_id="sub_" + "a" * 32, agent_plan=plan,
        tool_arguments=tool_arguments, session_id="chat_pcq_" + "b" * 32,
    )

    async def run():
        await client.orchestrate(request)

    asyncio.run(run())
    return transport


def test_list_only_hint_is_admitted_and_carries_one_step():
    transport = _send(_list_only_plan(), {"files_list": {"device_id": DEVICE}})
    assert len(transport.calls) == 1
    sent = json.loads(transport.calls[0]["body"])
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files"
    ]
    assert sent["tool_arguments"] == {"files_list": {"device_id": DEVICE}}


def test_existing_two_step_files_hint_is_unchanged():
    transport = _send(_files_plan(), {"files": {"device_id": DEVICE}})
    sent = json.loads(transport.calls[0]["body"])
    assert [step["tool_id"] for step in sent["agent_plan"]["steps"]] == [
        "claw.pc.list_files",
        "claw.pc.read_file",
    ]


def test_list_only_hint_with_a_read_step_is_refused():
    plan = _list_only_plan()
    plan["steps"].append(
        {"step_id": "read_file", "objective": "read", "tool_id": "claw.pc.read_file"}
    )
    with pytest.raises(PadiemAiEngineClientError) as excinfo:
        _send(plan, {"files_list": {"device_id": DEVICE}})
    assert excinfo.value.code == "unsupported_orchestration_field"


def test_two_step_files_plan_with_the_list_only_hint_is_refused():
    with pytest.raises(PadiemAiEngineClientError) as excinfo:
        _send(_files_plan(), {"files_list": {"device_id": DEVICE}})
    assert excinfo.value.code == "unsupported_orchestration_field"


def test_list_only_hint_still_validates_the_device_hint():
    with pytest.raises(PadiemAiEngineClientError) as excinfo:
        _send(_list_only_plan(), {"files_list": {"device_id": "not a device!"}})
    assert excinfo.value.code == "unsupported_orchestration_field"
