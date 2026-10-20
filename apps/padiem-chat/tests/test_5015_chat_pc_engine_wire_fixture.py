"""#5015: the Engine wire body is exactly what Chat's real builders still send.

The Engine lane executes a recorded payload (``apps/padiem-ai-engine/tests/
fixtures/5015_chat_pc_engine_payloads.json``). A recorded payload is only worth
anything if the producing code cannot drift away from it, so this test rebuilds
each body through the real production sequence —

    app.chat_pc_drive.build_chat_pc_agent_plan / build_chat_pc_files_agent_plan
    app.orchestration_bridge.B62EngineOrchestrationBridge.build_engine_request
    app.task_modes.get_task_mode("auto")
    padiem_ai_engine_client...orchestrate -> _run_payload -> transport

— and compares the captured transport body with the record. Nothing here
matches Chat source text: the body is the bytes the Engine would receive. The
transport is a recording fake, so no request leaves the process and no provider,
PC or model call happens.

Pinned inputs (``_provenance.pinned_inputs``) are read back out of the record;
every other field is derived by the code under test. ``trace_id`` is generated
per call, so it is normalized — and separately proven to keep its shape and to
stay mirrored inside ``execution_context``.

When Chat's wire shape changes on purpose, refresh the record from the producer
app instead of editing JSON by hand::

    REGENERATE_5015_WIRE_RECORD=1 python -m pytest tests/test_5015_chat_pc_engine_wire_fixture.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import pathlib

from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app.chat_pc_drive import (
    build_chat_pc_agent_plan,
    build_chat_pc_files_agent_plan,
)
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.task_modes import get_task_mode

RECORD_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "padiem-ai-engine" / "tests" / "fixtures" / "5015_chat_pc_engine_payloads.json"
)
RECORD = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
REGENERATE = os.environ.get("REGENERATE_5015_WIRE_RECORD") == "1"
TRACE_RE = re.compile(r"^b62_orch_[0-9a-f]{24}$")


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps(
                {"ok": True, "orchestration": {"run_status": "completed"}}
            ).encode("utf-8"),
        )


def send(record: dict) -> tuple[dict, RecordingTransport]:
    """Run one recorded lane through the real Chat -> Engine client sequence."""
    steps = record["agent_plan"]["steps"]
    plan = (
        build_chat_pc_agent_plan()
        if steps[0]["step_id"] == "query_drives"
        else build_chat_pc_files_agent_plan()
    )
    transport = RecordingTransport()
    engine_request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_5015",
        messages=[dict(item) for item in record["messages"]],
        skill=get_task_mode("auto"),
        model_id=record["agent"]["model_policy"]["model"],
        conversation_id=None,
        additional_system_context=record["additional_system_context"],
        subject_id=record["subject_id"],
        agent_plan=plan,
        tool_arguments=record["tool_arguments"],
        session_id=record["session_id"],
    )
    client = PadiemAiEngineClient(
        transport=transport,
        app_id=record["app_id"],
        caller_id="padiem-chat",
        credential="x" * 64,
    )
    asyncio.run(client.orchestrate(engine_request))
    assert len(transport.calls) == 1
    return json.loads(transport.calls[0]["body"].decode("utf-8")), transport


def _without_trace(body: dict) -> dict:
    rest = dict(body)
    rest.pop("trace_id")
    rest.pop("execution_context")
    return rest


def _refresh_or_assert(lane: str, live: dict) -> None:
    if REGENERATE:
        RECORD[lane] = live
        RECORD_PATH.write_text(
            json.dumps(RECORD, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return
    assert _without_trace(live) == _without_trace(RECORD[lane]), json.dumps(
        {"live": _without_trace(live), "record": _without_trace(RECORD[lane])},
        ensure_ascii=False,
        sort_keys=True,
    )


def test_the_record_names_the_producing_builders_and_the_pinned_inputs():
    provenance = RECORD["_provenance"]
    assert "app.chat_pc_drive.build_chat_pc_files_agent_plan" in provenance["chat_builders"]
    assert set(provenance["pinned_inputs"]) == {
        "messages",
        "additional_system_context",
        "subject_id",
        "session_id",
        "tool_arguments",
        "agent.model_policy.model",
        "app_id",
    }


def test_the_drives_record_is_the_live_chat_wire_body():
    live, transport = send(RECORD["drives"])

    assert transport.calls[0]["url"].endswith("/internal/v1/orchestrate")
    _refresh_or_assert("drives", live)
    assert TRACE_RE.fullmatch(live["trace_id"])
    assert live["execution_context"] == {"trace_id": live["trace_id"]}


def test_the_files_record_is_the_live_chat_wire_body():
    live, _transport = send(RECORD["files"])

    _refresh_or_assert("files", live)
    assert live["agent_plan"]["steps"] == [
        {"step_id": "list_files",
         "objective": "List the approved folder on the verified owner PC",
         "tool_id": "claw.pc.list_files"},
        {"step_id": "read_file",
         "objective": "Read the requested UTF-8 text file",
         "tool_id": "claw.pc.read_file"},
    ]


def test_a_targetless_chat_request_never_reaches_the_pc_field():
    """Without a server-resolved device there is no tool_arguments on the wire."""
    record = RECORD["drives"]
    steps = record["agent_plan"]["steps"]
    engine_request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_5015",
        messages=[dict(item) for item in record["messages"]],
        skill=get_task_mode("auto"),
        model_id=record["agent"]["model_policy"]["model"],
        conversation_id=None,
        subject_id=record["subject_id"],
        agent_plan=build_chat_pc_agent_plan() if steps[0]["step_id"] == "query_drives" else None,
        tool_arguments=None,
        session_id=record["session_id"],
    )
    transport = RecordingTransport()
    client = PadiemAiEngineClient(
        transport=transport,
        app_id=record["app_id"],
        caller_id="padiem-chat",
        credential="x" * 64,
    )
    asyncio.run(client.orchestrate(engine_request))

    body = json.loads(transport.calls[0]["body"].decode("utf-8"))
    assert "tool_arguments" not in body
    assert body["agent_plan"]["agent_id"] == "agent:padiem:chat-pc-query@1"
