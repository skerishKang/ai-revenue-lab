"""Provider-free browser plan and explicitly opted-in PC progress contracts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import (
    P01AdapterError, P01CoreOrchestrationAdapter, P01DispatchClass, P01RequestFactory,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.runs import ClawRun
from model_route_fixture import plus_route_for_test
from padiem_ai_core.orchestration_events import OrchestrationEventKind as K
from test_p01_adapter import _ResultFactory
from test_p01_orchestration_client import _build_request, _public_result


SUBJECT = "sub_" + "a" * 32
DEVICE = "node//browser-PC$@1"
TOOLS = tuple("claw.pc." + op for op in (
    "browser_open", "browser_read", "browser_screenshot", "browser_act",
))


@pytest.fixture(autouse=True)
def synthetic_model_route():
    with plus_route_for_test():
        yield


def browser_request(**overrides):
    run = ClawRun.create("run_" + "a" * 24, ClawTaskIntent(
        task_id="task_browser_contract", task="example.com 열어서 제목 알려 줘",
        repository_ref="skerishKang/example", execution_mode=ExecutionMode.LOCAL,
    ))
    options = {"subject_id": SUBJECT, "pc_browser_query": True,
               "pc_browser_device_id": DEVICE, **overrides}
    return P01RequestFactory(allow_subject_identity=True).build(run, **options)


def test_browser_plan_has_exact_four_tools_and_owner_device_only():
    bundle = browser_request()
    request = bundle.orchestration_request
    assert request.subject_id == SUBJECT
    assert request.agent_plan.agent_id == "agent:padiem:claw-pc-query@1"
    assert tuple(step.tool_id for step in request.agent_plan.steps) == TOOLS
    assert tuple(step.step_id for step in request.agent_plan.steps) == tuple(
        tool.removeprefix("claw.pc.") for tool in TOOLS
    )
    assert request.tool_arguments == {"browser": {"device_id": DEVICE}}
    assert "example.com" in bundle.execution_request.messages[-1]["content"]
    assert "files" not in request.tool_arguments


@pytest.mark.parametrize("device", [None, "", "../../other", "https://other.invalid", "PC\nother"])
def test_browser_plan_requires_canonical_device(device):
    with pytest.raises(P01AdapterError) as caught:
        browser_request(pc_browser_device_id=device)
    assert caught.value.code == "pc_browser_owner_required"
    assert caught.value.dispatch_class is P01DispatchClass.NOT_DISPATCHED


def test_browser_plan_requires_subject_and_explicit_subject_lane():
    with pytest.raises(P01AdapterError) as caught:
        browser_request(subject_id=None)
    assert caught.value.code == "pc_browser_owner_required"
    run, _ = _build_request()
    with pytest.raises(P01AdapterError) as caught:
        P01RequestFactory().build(run, subject_id=SUBJECT, pc_browser_query=True,
                                  pc_browser_device_id=DEVICE)
    assert caught.value.code == "p01_authority_field_unsupported"
    assert caught.value.dispatch_class is P01DispatchClass.NOT_DISPATCHED


@pytest.mark.parametrize("other_lane", ["pc_drive_query", "pc_files_query", "desktop_capture"])
def test_browser_plan_cannot_mix_file_or_desktop_lanes(other_lane):
    with pytest.raises(P01AdapterError) as caught:
        browser_request(**{other_lane: True})
    assert caught.value.code == "conflicting_pc_observation"
    assert caught.value.dispatch_class is P01DispatchClass.NOT_DISPATCHED


def test_default_plan_does_not_expose_browser_tools():
    _, request = _build_request()
    assert request.agent_plan is None
    assert not request.tool_arguments


def test_factory_browser_plan_crosses_real_p01_wire_boundary():
    request = browser_request().orchestration_request

    class Transport:
        async def orchestrate(self, payload):
            self.payload = payload
            return _public_result(request)

    transport = Transport()
    asyncio.run(P01EngineOrchestrationClient(
        transport, allow_subject_identity=True,
    ).run(request))
    assert transport.payload["subject_id"] == SUBJECT
    assert transport.payload["tool_arguments"] == {"browser": {"device_id": DEVICE}}
    assert tuple(step["tool_id"] for step in transport.payload["agent_plan"]["steps"]) == TOOLS


@pytest.mark.parametrize("arguments", [None, {}, {"browser": {"device_id": DEVICE, "url": "https://example.com"}},
                                        {"files": {"device_id": DEVICE}}])
def test_browser_wire_refuses_missing_target_or_extra_authority(arguments):
    request = replace(browser_request().orchestration_request, tool_arguments=arguments)
    port = P01EngineOrchestrationClient(RecordTransport([]), allow_subject_identity=True)
    with pytest.raises(P01AdapterError) as caught:
        asyncio.run(port.run(request))
    assert caught.value.dispatch_class is P01DispatchClass.NOT_DISPATCHED


def test_live_adapter_forwards_browser_plan_and_progress_observer_together():
    seen = []

    async def observe(record):
        seen.append(record)

    async def event_observer(event):
        pass

    class Runner:
        async def run(self, request):
            raise AssertionError("live request must not use the completed lane")

        async def run_stream(self, request, *, on_event, on_pc_progress):
            assert on_pc_progress is observe
            assert tuple(step.tool_id for step in request.agent_plan.steps) == TOOLS
            assert request.tool_arguments == {"browser": {"device_id": DEVICE}}
            assert request.subject_id == SUBJECT
            result = _ResultFactory.result(request, [K.RUN_STARTED, K.RUN_COMPLETED])
            await on_event(result.events[0])
            await on_pc_progress({"pc_progress": {"pc_run_id": request.execution_request.session_id,
                "dispatch_id": "dsp_" + "b" * 32, "kind": "command", "stage": "executing",
                "sequence": 1, "elapsed_ms": 500}})
            await on_event(result.events[1])
            return result

    run, _ = _build_request()
    outcome = asyncio.run(P01CoreOrchestrationAdapter(Runner(), allow_subject_identity=True).execute(
        run, subject_id=SUBJECT, pc_browser_query=True, pc_browser_device_id=DEVICE,
        on_event=event_observer, on_pc_progress=observe,
    ))
    assert outcome.answer == "완료 답변"
    assert len(seen) == 1
    assert seen[0]["pc_progress"]["pc_run_id"] == run.run_id


class RecordTransport:
    def __init__(self, records):
        self.records, self.calls, self.closed = records, [], False

    async def orchestrate(self, payload):
        raise AssertionError("unapproved completed or fallback dispatch")

    async def stream_orchestration(self, payload, **options):
        self.calls.append((payload, options))
        try:
            for record in self.records:
                yield record
        finally:
            self.closed = True


def stream_fixture():
    _, request = _build_request()
    result = _public_result(request)
    events = deepcopy(result["events"])
    progress = {"pc_progress": {
        "pc_run_id": request.execution_request.session_id,
        "dispatch_id": "dsp_" + "b" * 32, "kind": "command",
        "stage": "executing", "sequence": 1, "elapsed_ms": 1200,
    }}
    heartbeat = {"heartbeat": {
        "run_id": events[0]["run_id"], "trace_id": request.context.trace_id,
        "elapsed_ms": 1500,
    }}
    return request, result, events, progress, heartbeat


def consume(request, records, *, opted_in=True):
    seen, transport = [], RecordTransport(records)

    async def observe(record):
        seen.append(record)

    options = {"on_pc_progress": observe} if opted_in else {}
    result = asyncio.run(P01EngineOrchestrationClient(transport).run_stream(request, **options))
    return result, transport, seen


def test_progress_and_heartbeat_require_explicit_transport_opt_in():
    request, result, events, progress, heartbeat = stream_fixture()
    records = [{"event": events[0]}, progress, heartbeat,
               *({"event": event} for event in events[1:]), {"orchestration": result}]
    parsed, transport, seen = consume(request, records)
    assert seen == [progress, heartbeat]
    assert transport.calls[0][1] == {"pc_progress": True}
    assert transport.calls[0][0]["session_id"] == request.execution_request.session_id
    assert parsed.execution_result.answer == "완료 답변"
    assert transport.closed


def test_default_stream_does_not_enable_pc_progress():
    request, result, events, _, _ = stream_fixture()
    _, transport, seen = consume(request, [*({"event": e} for e in events),
                                          {"orchestration": result}], opted_in=False)
    assert transport.calls[0][1] == {}
    assert seen == []


@pytest.mark.parametrize("changed", ["pc_run_id", "run_id", "trace_id"])
def test_foreign_progress_identity_rejected_before_callback(changed):
    request, result, events, progress, heartbeat = stream_fixture()
    record = deepcopy(progress if changed == "pc_run_id" else heartbeat)
    next(iter(record.values()))[changed] = "foreign_owner_run"
    transport, seen = RecordTransport([{"event": events[0]}, record]), []

    async def observe(value):
        seen.append(value)

    with pytest.raises(P01AdapterError) as caught:
        asyncio.run(P01EngineOrchestrationClient(transport).run_stream(request, on_pc_progress=observe))
    assert caught.value.code == "p01_stream_correlation_mismatch"
    assert seen == []
    assert transport.closed


@pytest.mark.parametrize("position", ["before_start", "after_terminal", "without_opt_in"])
def test_progress_cannot_bypass_live_lifecycle(position):
    request, result, events, progress, _ = stream_fixture()
    records = ([progress] if position == "before_start" else
               [*({"event": e} for e in events), progress] if position == "after_terminal" else
               [{"event": events[0]}, progress])
    with pytest.raises(P01AdapterError) as caught:
        consume(request, records, opted_in=position != "without_opt_in")
    assert caught.value.code == "p01_stream_invalid_record"
