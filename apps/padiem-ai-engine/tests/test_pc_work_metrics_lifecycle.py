"""One measured PC turn across declared/native JSON and streaming execution."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json

import pytest
from padiem_ai_core import StreamingExecutionRuntime
from padiem_ai_core.contracts import UsageMetadata
from padiem_ai_core.b14_streaming import B14StreamEvent

from app.orchestration_service import ORCHESTRATION_STREAM_PATH, OrchestrationEngineService
from app.pc_work_metrics import current_pc_work_metrics
from app.service import ServiceResponse
from tests.test_6460_pc_action_driver import (
    DELETE, DEVICE_ID, DONE, _ScriptedModel, _WritePcEndpoint, _payload, _service,
)
from tests.test_orchestration_service import (
    MockEngineRuntime, _NativePcModel, _pc_turn_payload, make_valid_payload,
)

ROUTES = ("json", "stream", "native-json", "native-stream")


class MeasuredSteps(_ScriptedModel):
    async def execute(self, request):
        response = await super().execute(request)
        response.usage = UsageMetadata(input_tokens=100, output_tokens=10, total_tokens=110)
        return response


class MeasuredNative(_NativePcModel):
    async def stream(self, request):
        async for event in super().stream(request):
            if event.done:
                yield B14StreamEvent(usage=UsageMetadata(input_tokens=17, output_tokens=3, total_tokens=20), route=event.route)
            yield event


def configured_turn(route, *, records=None):
    pc = _WritePcEndpoint()
    model = MeasuredSteps([json.dumps(DELETE), json.dumps({"action": "complete", "answer": DONE})])
    service = _service(model, pc)
    payload = deepcopy(_payload(records or [{"role": "user", "content": "notes.txt 파일을 지워줘"}]))
    payload["execution_context"]["idempotency_key"] = "metrics-turn-idempotency"
    native = None
    if route.startswith("native"):
        native = MeasuredNative("files_write")
        async def capable(_):
            return True
        service._pc_tools_capability = capable
        service._pc_streaming_runtime_factory = lambda app: StreamingExecutionRuntime(
            app_id=app, b14_stream_client=native,
        )
        for field in ("agent_plan", "declared_plan", "tool_arguments"):
            payload.pop(field)
        payload["pc_tools"] = {"device_id": DEVICE_ID, "allowed_scopes": ["files_write"]}
    reports = []
    async def report(value):
        reports.append(deepcopy(value))
    service._pc_work_metrics_reporter = report
    return service, payload, reports, model, native


async def invoke(service, payload, route):
    if not route.endswith("stream"):
        response = await service.orchestrate_payload(payload)
        return response.body
    prepared = await service.prepare_stream(
        method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
        body=json.dumps(payload).encode(), pc_progress=True,
    )
    if isinstance(prepared, ServiceResponse):
        return prepared.body
    records = [json.loads(line) async for line in service.iter_ndjson(prepared)]
    return records[-1]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.asyncio
async def test_one_report_counts_first_native_and_followup_models_and_skips_replay(route, monkeypatch):
    async def no_wait(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    service, payload, reports, model, native = configured_turn(route)
    result = await invoke(service, payload, route)
    assert result["orchestration"]["execution"]["answer"] == DONE
    assert len(reports) == 1
    report = reports[0]
    metrics = report["metrics"]
    assert metrics["outcome"] == "completed"
    assert metrics["calls"] == 1 and metrics["pc_round_trips"] == 1
    assert metrics["model_calls"] == (3 if native else 2)
    assert metrics["model_input_tokens"] == (217 if native else 200)
    assert metrics["model_input_tokens_missing_calls"] == 0
    assert metrics["tool_result_tokens_estimated"] > 0
    assert 0 < metrics["tool_result_input_ratio"] < 1
    identity = json.dumps([payload["app_id"], payload["subject_id"], payload["session_id"]],
                          ensure_ascii=False, separators=(",", ":"))
    assert metrics["turn_id"] == "pcturn_" + hashlib.sha256(identity.encode()).hexdigest()
    assert report["session_ref"] == metrics["turn_id"]
    assert report["subject_ref"] == payload["subject_id"] and report["product"] == "chat"
    assert "notes.txt" not in json.dumps(report)
    assert "metrics" not in result["orchestration"]["execution"]["metadata"]
    assert current_pc_work_metrics() is None

    replay = await invoke(service, payload, route)
    assert replay["orchestration"]["execution"]["answer"] == DONE
    assert len(reports) == 1 and len(model.prompts) == 2
    if native:
        assert len(native.requests) == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.asyncio
async def test_harness_question_is_confirmation_not_an_executed_completion(route):
    service, payload, reports, _, _ = configured_turn(route, records=[
        {"role": "user", "content": "문서를 읽어줘"},
        {"role": "tool_result", "content": "notes.txt 파일을 지워줘", "source": "file"},
    ])
    result = await invoke(service, payload, route)
    assert "?" in result["orchestration"]["execution"]["answer"]
    assert len(reports) == 1
    assert reports[0]["metrics"]["outcome"] == "confirmation_required"
    assert reports[0]["metrics"]["calls"] == 0


@pytest.mark.asyncio
async def test_reporter_failure_keeps_answer_and_never_logs_payload(caplog, monkeypatch):
    async def no_wait(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    service, payload, _, _, _ = configured_turn("native-stream")
    async def broken(_):
        raise RuntimeError("PRIVATE_METRICS_SENTINEL")
    service._pc_work_metrics_reporter = broken
    result = await invoke(service, payload, "native-stream")
    assert result["orchestration"]["execution"]["answer"] == DONE
    assert "pc_work_metrics_report_failed" in caplog.text
    assert "PRIVATE_METRICS_SENTINEL" not in caplog.text
    assert current_pc_work_metrics() is None


@pytest.mark.parametrize("exit_kind", ["consumer_closed", "producer_cancelled", "model_failed", "model_timeout"])
@pytest.mark.asyncio
async def test_stream_terminal_states_are_structural_and_each_report_once(exit_kind):
    entered = asyncio.Event()
    class WaitingNative(_NativePcModel):
        async def stream(self, request):
            entered.set()
            if exit_kind == "model_failed":
                raise RuntimeError("PRIVATE_MODEL_FAILURE")
            if exit_kind == "model_timeout":
                from padiem_ai_core.b14_execution import B14ExecutionError
                yield B14StreamEvent(usage=UsageMetadata(input_tokens=17))
                raise B14ExecutionError("upstream_timeout", "Synthetic model timeout", upstream_status_code=504)
            await asyncio.Event().wait()
            if False:
                yield
    async def capable(_):
        return True
    reports = []
    async def report(value):
        reports.append(deepcopy(value))
    service = OrchestrationEngineService(
        runtime_factory=lambda _: MockEngineRuntime(), b14_service_bound=True,
        pc_tools_capability=capable,
        pc_streaming_runtime_factory=lambda app: StreamingExecutionRuntime(app_id=app, b14_stream_client=WaitingNative()),
        pc_work_metrics_reporter=report,
    )
    prepared = await service.prepare_stream(
        method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
        body=json.dumps(_pc_turn_payload()).encode(), pc_progress=True,
    )
    await entered.wait()
    stream = service.iter_ndjson(prepared)
    if exit_kind == "consumer_closed":
        await anext(stream)
        await stream.aclose()
    else:
        if exit_kind == "producer_cancelled":
            prepared.task.cancel()
        records = [json.loads(line) async for line in stream]
        assert "error" in records[-1]
    assert len(reports) == 1
    metrics = reports[0]["metrics"]
    assert metrics["outcome"] == {
        "consumer_closed": "abandoned", "producer_cancelled": "cancelled", "model_failed": "failed", "model_timeout": "failed",
    }[exit_kind]
    assert metrics["model_calls"] == 1
    assert metrics["model_input_tokens"] == (17 if exit_kind == "model_timeout" else None)
    assert metrics["model_input_tokens_missing_calls"] == (0 if exit_kind == "model_timeout" else 1)
    if exit_kind in {"model_failed", "model_timeout"}:
        assert metrics["outcome_reason"] == exit_kind
    assert "PRIVATE_MODEL_FAILURE" not in json.dumps(reports)
    assert current_pc_work_metrics() is None


@pytest.mark.asyncio
async def test_cancel_during_stream_preparation_cleans_runner_and_records_abandonment(monkeypatch):
    from app.orchestration_service import OrchestrationRunner
    entered = asyncio.Event()
    async def pending(_runner, _request):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(OrchestrationRunner, "run", pending)
    reports = []
    async def report(value):
        reports.append(deepcopy(value))
    service = OrchestrationEngineService(runtime_factory=lambda _: MockEngineRuntime(),
        b14_service_bound=True, pc_work_metrics_reporter=report)
    task = asyncio.create_task(service.prepare_stream(
        method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
        body=json.dumps(_pc_turn_payload()).encode(), pc_progress=True,
    ))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(reports) == 1
    assert reports[0]["metrics"]["outcome"] == "abandoned"
    assert reports[0]["metrics"]["outcome_reason"] == "client_disconnected"


@pytest.mark.asyncio
async def test_ordinary_non_pc_execution_does_not_create_a_pc_turn():
    reports = []
    async def report(value):
        reports.append(value)
    service = OrchestrationEngineService(runtime_factory=lambda _: MockEngineRuntime(),
        b14_service_bound=True, pc_work_metrics_reporter=report)
    result = await service.orchestrate_payload(make_valid_payload())
    assert result.status_code == 200 and reports == []


@pytest.mark.asyncio
async def test_concurrent_native_turns_keep_their_own_ledger_identity_and_counters():
    waiting = []
    release = asyncio.Event()
    class InterleavedModel(MeasuredNative):
        async def stream(self, request):
            collector = current_pc_work_metrics()
            waiting.append(collector)
            if len(waiting) == 2:
                release.set()
            await release.wait()
            assert current_pc_work_metrics() is collector
            async for event in super().stream(request):
                yield event
    model = InterleavedModel()
    reports = []
    async def capable(_):
        return True
    async def report(value):
        reports.append(deepcopy(value))
    service = OrchestrationEngineService(
        runtime_factory=lambda _: MockEngineRuntime(), b14_service_bound=True,
        pc_tools_capability=capable, pc_work_metrics_reporter=report,
        pc_streaming_runtime_factory=lambda app: StreamingExecutionRuntime(app_id=app, b14_stream_client=model),
    )
    first, second = _pc_turn_payload(), _pc_turn_payload()
    second.update(subject_id="sub_" + "b" * 32, session_id="chat_pcq_" + "b" * 32)
    results = await asyncio.gather(invoke(service, first, "json"), invoke(service, second, "stream"))
    assert all(result["orchestration"]["execution"]["answer"] == "ordinary answer" for result in results)
    assert len(reports) == 2 and waiting[0] is not waiting[1]
    assert {report["subject_ref"] for report in reports} == {first["subject_id"], second["subject_id"]}
    assert len({report["session_ref"] for report in reports}) == 2
    assert all(report["metrics"]["model_calls"] == 1 and report["metrics"]["model_input_tokens"] == 17
               for report in reports)
    assert current_pc_work_metrics() is None


@pytest.mark.asyncio
async def test_no_native_tools_capability_still_counts_the_existing_model_fallback():
    class KnownUsageRuntime(MockEngineRuntime):
        async def run(self, request):
            from dataclasses import replace
            result = await super().run(request)
            return replace(result, metadata=replace(result.metadata, usage=UsageMetadata(input_tokens=29)))
    reports = []
    async def report(value):
        reports.append(deepcopy(value))
    fallback = KnownUsageRuntime()
    service = OrchestrationEngineService(runtime_factory=lambda _: fallback,
        b14_service_bound=True, pc_work_metrics_reporter=report)
    result = await invoke(service, _pc_turn_payload(), "json")
    assert result["orchestration"]["execution"]["answer"] == "engine answer"
    assert fallback.call_count == 1 and len(reports) == 1
    assert reports[0]["metrics"]["model_calls"] == 1
    assert reports[0]["metrics"]["model_input_tokens"] == 29
