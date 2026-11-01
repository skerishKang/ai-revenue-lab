"""#6460-5: a native tool wire that refuses falls back; Gemma rides the harness.

The fallback cases drive the real PcToolsTurnRuntime with an in-process stream
fake. The Gemma case drives the real Engine service, the real PC step driver and
the real signed-call correlation with the PC endpoint fake from #5015.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest

from app.pc_tools_turn import PcToolsTurnRuntime, _native_tool_fallback
from padiem_ai_core.b14_execution import B14ExecutionError
from padiem_ai_core.execution_runtime import ExecutionResult

GEMMA = "google/gemma-4-31b-it"
DEVICE = "office-pc"


@dataclass
class _Request:
    agent: object
    messages: tuple = ()
    tools: tuple = ()
    tool_choice: object = None
    trace_id: str = "tr_gemma"


class _Agent:
    def __init__(self, model=GEMMA):
        self.model_policy = {"model": model}
        self.allowed_tools = ()
        self.system_instruction = None
        self.max_tokens = None
        self.task_type = "general"
        self.optimize_for = "balanced"


class _FailingStream:
    def __init__(self, error, *, delta=None):
        self.error = error
        self.delta = delta
        self.closed = False

    async def stream(self, request):
        try:
            if self.delta:
                yield _event(delta=self.delta)
            raise self.error
        finally:
            self.closed = True


class _Event:
    def __init__(self, delta=None, tool_call=None, done=False):
        self.delta_content = delta
        self.tool_call = tool_call
        self.done = done
        self.answer = None
        self.route = None
        self.metadata = None


def _event(*, delta=None, tool_call=None, done=False):
    return _Event(delta=delta, tool_call=tool_call, done=done)


class _Fallback:
    def __init__(self):
        self.calls = 0

    async def run(self, request):
        from padiem_ai_core.b14_execution import B14RouteMetadata
        from padiem_ai_core.contracts import RunStatus
        from padiem_ai_core.execution_runtime import RunMetadata

        self.calls += 1
        return ExecutionResult(
            answer="fallback answer",
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_gemma", app_id="padiem-chat",
                agent_id="agent:test", status=RunStatus.COMPLETED,
            ),
        )


class _Service:
    def __init__(self, stream, *, capable=True, seen=None):
        self._stream = stream
        self._capable = capable
        self._seen = seen if seen is not None else []
        self._pc_streaming_runtime_factory = lambda app_id: self._stream

    async def _pc_tools_capability(self, model_id):
        self._seen.append(model_id)
        return self._capable


def _runtime(service, fallback):
    payload = {
        "app_id": "padiem-chat",
        "subject_id": "sub_" + "a" * 32,
        "session_id": "chat_pcq_" + "a" * 32,
        "pc_tools": {"device_id": DEVICE, "allowed_scopes": ["files_list", "files"]},
    }
    return PcToolsTurnRuntime(service, payload, fallback)


def _refusal(code="tools_not_supported", status=400):
    return B14ExecutionError(code, "tools refused", upstream_status_code=status)


def test_a_native_tool_refusal_before_output_falls_back_to_the_existing_lane():
    stream = _FailingStream(_refusal())
    fallback = _Fallback()
    seen: list[str] = []
    service = _Service(stream, seen=seen)
    result = asyncio.run(_runtime(service, fallback).run(_Request(agent=_Agent())))
    assert result.answer == "fallback answer"
    assert fallback.calls == 1
    assert seen == [GEMMA]
    assert stream.closed is True


def test_a_refusal_after_output_is_a_real_failure_not_a_replay():
    stream = _FailingStream(_refusal(), delta="부분 응답")
    fallback = _Fallback()
    service = _Service(stream)
    with pytest.raises(Exception):
        asyncio.run(_runtime(service, fallback).run(_Request(agent=_Agent())))
    assert fallback.calls == 0


def test_a_model_without_the_capability_keeps_the_old_path():
    stream = _FailingStream(_refusal())
    fallback = _Fallback()
    service = _Service(stream, capable=False)
    result = asyncio.run(_runtime(service, fallback).run(_Request(agent=_Agent())))
    assert result.answer == "fallback answer"
    assert fallback.calls == 1


def test_only_tool_wire_failures_are_fallback_eligible():
    assert _native_tool_fallback(_refusal("tools_not_supported", None)) is True
    assert _native_tool_fallback(_refusal("other", 400)) is True
    assert _native_tool_fallback(_refusal("other", 429)) is False
    assert _native_tool_fallback(_refusal("other", 500)) is False
    assert _native_tool_fallback(RuntimeError("boom")) is False


@pytest.mark.asyncio
async def test_gemma_reaches_the_pc_harness_through_the_same_native_path(monkeypatch):
    """The model name changes; the admitted plan, dispatch and claim do not."""
    from padiem_ai_core import StreamingExecutionRuntime
    from tests.test_5574_pc_read_boundary_end_to_end import (
        _FakePcEndpoint, _Request as _WireRequest, SIGNING_SECRET,
        WRONG_READ_STEP, COMPLETE_STEP, _ScriptedModel,
        build_chat_pc_query_tool_binding, build_live_pc_query_driver,
    )
    from tests.test_orchestration_service import (
        MockEngineRuntime, _NativePcModel, _pc_turn_payload,
    )
    from app.orchestration_service import (
        OrchestrationEngineService, ORCHESTRATION_STREAM_PATH,
    )

    pc = _FakePcEndpoint()
    model = _NativePcModel("files_list")
    followups = _ScriptedModel([WRONG_READ_STEP, COMPLETE_STEP])
    binding = build_chat_pc_query_tool_binding(
        service=pc, request_factory=_WireRequest, secret=SIGNING_SECRET,
    )
    seen_models: list[str] = []

    def factory(model_id, model_policy, task_type, optimize_for,
                tool_arguments=None, initial_decision=None):
        return build_live_pc_query_driver(
            b14_client=followups, model_id=model_id, model_policy=model_policy,
            task_type=task_type, optimize_for=optimize_for, service=pc,
            request_factory=_WireRequest, secret=SIGNING_SECRET,
            tool_arguments=tool_arguments, initial_decision=initial_decision,
        )

    async def capable(model_id):
        seen_models.append(model_id)
        # The capability evidence is the registry's; the route under test is
        # the same one every tool-capable model takes.
        return model_id == GEMMA

    async def fast_poll(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_poll)
    service = OrchestrationEngineService(
        runtime_factory=lambda _: MockEngineRuntime(), b14_service_bound=True,
        pc_streaming_runtime_factory=lambda app: StreamingExecutionRuntime(
            app_id=app, b14_stream_client=model),
        pc_tools_capability=capable, tool_binding_resolver=lambda _: binding,
        pc_query_step_driver_factory=factory,
    )
    payload = _pc_turn_payload()
    payload["agent"]["model_policy"]["model"] = GEMMA
    payload["pc_tools"]["allowed_scopes"] = ["files_list"]
    prepared = await service.prepare_stream(
        method="POST", path=ORCHESTRATION_STREAM_PATH,
        content_type="application/json", body=json.dumps(payload).encode(),
        pc_progress=True,
    )
    chunks = [line.encode() async for line in service.iter_ndjson(prepared)]

    assert seen_models == [GEMMA]
    assert pc.ops == ["list"]
    assert pc.claims and all(
        claim["ops"] == ["list"] and claim["source"] == "declared"
        for claim in pc.claims
    )
    assert chunks
