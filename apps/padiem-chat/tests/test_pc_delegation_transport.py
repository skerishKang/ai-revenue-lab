"""Owner settings reach every PC wire outside the unchanged model input."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.chat_pc_drive import _execute_chat_pc_files_lane, chat_pc_plan_for_tool
from app.task_modes import get_task_mode
from kagent.p01_adapter import P01AdapterError, P01RequestFactory
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.p01_run_flow import create_claw_run

import test_5015_orchestration_pc_lane as native
import test_5484_canonical_subject_engine_admission as canonical
import test_chat_pc_drive as legacy


DEVICE = "dev_" + "a" * 32
POLICY = {"version": 1, "rules": [{
    "id": "rule-a", "device_id": DEVICE, "folder": "docs",
    "actions": ["write", "move"], "mode": "allow", "enabled": True,
}]}


@pytest.mark.parametrize("canonical_identity", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_chat_bridge_and_sdk_preserve_delegation_without_prompt_changes(
    monkeypatch, canonical_identity, streaming,
):
    bridge, transport, _ = canonical._selected_stream_bridge(
        monkeypatch, with_resolver=canonical_identity,
    )

    async def request(**kwargs):
        from padiem_ai_engine_client import EngineTransportResponse
        transport.calls.append(kwargs)
        return EngineTransportResponse(status=200, body=json.dumps({
            "ok": True, "orchestration": {
                "events": [{"event_id": "evt_delegation", "run_id": "run_delegation",
                            "trace_id": "trace_delegation", "app_id": "padiem-chat",
                            "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": "OK"}, "approval_pause": None,
            },
        }).encode(), headers={"content-type": "application/json"})

    transport.request = request
    messages = [{"role": "user", "content": "docs/a.txt 파일을 저장해 줘"}]

    async def exercise():
        fields = dict(
            user_id=canonical.PRODUCT_USER, messages=messages,
            skill=get_task_mode("auto"), model_id="b14/model", user_text=messages[0]["content"],
            conversation_id=None, subject_id=(canonical.CANONICAL_SUBJECT if canonical_identity
                                              else canonical.PRODUCT_USER),
            session_id="session_delegation", additional_system_context="unchanged context",
            pc_delegation=POLICY,
        )
        if streaming:
            records = [r async for r in bridge.start_stream(
                **fields, pc_tools={"device_id": DEVICE, "allowed_scopes": ["files_write"]},
            )]
            assert records[-1]["result"].answer == "OK"
        else:
            result = await bridge.start(**fields, agent_plan=chat_pc_plan_for_tool("files_write"),
                                        tool_arguments={"files_write": {"device_id": DEVICE}})
            assert result.answer == "OK"

    asyncio.run(exercise())
    wire = json.loads(transport.calls[0]["body"])
    assert wire["pc_delegation"] == POLICY
    assert wire["messages"] == messages
    assert wire["additional_system_context"] == "unchanged context"


@pytest.mark.parametrize("stored,expected", [
    (POLICY, POLICY),
    ({"version": 1, "rules": []}, {"version": 1, "rules": []}),
    (RuntimeError("settings unavailable"), {"version": 1, "available": False, "rules": []}),
])
def test_native_chat_loads_authenticated_owner_settings(monkeypatch, stored, expected):
    bridge = native._install(monkeypatch, native._Lane(), pc_entry=True)
    loader = AsyncMock(side_effect=stored) if isinstance(stored, Exception) else AsyncMock(return_value=stored)
    request = native._request({"messages": [{"role": "user", "content": "파일 정리해 줘"}]}, bridge)
    request.app.state.pc_delegation_store = SimpleNamespace(load=loader)
    response = native._call(request)
    assert response.status_code == 200
    loader.assert_awaited_once_with("owner")
    assert bridge.calls[0]["pc_delegation"] == expected


def test_browser_delegation_is_not_accepted_as_engine_authority(monkeypatch):
    bridge = native._install(monkeypatch, native._Lane(), pc_entry=True)
    request = native._request({
        "messages": [{"role": "user", "content": "파일 정리해 줘"}],
        "pc_delegation": POLICY,
    }, bridge)
    assert native._call(request).status_code == 422
    assert bridge.calls == []


def test_legacy_chat_loads_owner_policy_in_the_shared_pc_handoff(monkeypatch):
    import app.pc_delegation_routes as settings
    loader = AsyncMock(return_value=POLICY)
    monkeypatch.setattr(settings, "load_pc_delegation", loader)
    request, _, bridge, store = legacy._request(model_answers=[])
    asyncio.run(_execute_chat_pc_files_lane(
        request, store=store, uid="usr_chat_1", subject_id="sub_" + "a" * 32,
        workspace_id="tenant-1", user_text="docs/a.txt 저장해 줘", execution_user_text="model input",
        skill=None, model_id="model-x", conversation_id=None, device_id=DEVICE,
        additional_system_context="unchanged context", agent_plan=chat_pc_plan_for_tool("files_write"),
    ))
    loader.assert_awaited_once_with(request, "usr_chat_1")
    assert bridge.requests[0]["pc_delegation"] == POLICY
    assert bridge.requests[0]["messages"] == ({"role": "user", "content": "model input"},)


def test_claw_factory_and_client_preserve_policy_and_reject_non_pc_authority():
    run = create_claw_run("padiem-chat", "unchanged model input", model_only_text=True)
    factory = P01RequestFactory(allow_subject_identity=True)
    bundle = factory.build(run, subject_id="sub_" + "b" * 32, selected_model_id="fixture/model",
                           pc_files_query=True, pc_files_device_id=DEVICE, pc_delegation=POLICY)
    client = P01EngineOrchestrationClient(SimpleNamespace(orchestrate=AsyncMock()), allow_subject_identity=True)
    wire = client._build_payload(bundle.orchestration_request)
    assert wire["pc_delegation"] == POLICY
    assert wire["messages"] == [{"role": "user", "content": "unchanged model input"}]
    with pytest.raises(P01AdapterError, match="PC delegation"):
        client._build_payload(replace(bundle.orchestration_request, agent_plan=None))
    ordinary = factory.build(run, subject_id="sub_" + "b" * 32, selected_model_id="fixture/model")
    assert "pc_delegation" not in client._build_payload(ordinary.orchestration_request)


def test_live_claw_loads_owner_policy_before_adapter_dispatch(monkeypatch):
    import app.pc_delegation_routes as settings
    from test_3930_b54_live_sse_relay import _streaming_adapter
    from test_5015_live_staged_run_settle import OWNER, _drive_call, _tracking_store

    loader = AsyncMock(return_value=POLICY)
    monkeypatch.setattr(settings, "load_pc_delegation", loader)
    adapter = _streaming_adapter()
    response = _drive_call(adapter, _tracking_store())
    assert response.status_code == 200 and "event: done" in response.text
    assert loader.await_count == 1
    assert loader.await_args.args[1] == OWNER
    assert adapter.execute.await_args.kwargs["pc_delegation"] == POLICY
