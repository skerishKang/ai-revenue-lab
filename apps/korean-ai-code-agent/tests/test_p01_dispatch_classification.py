"""#2226: the P01/Engine chain exposes an authoritative dispatch classification.

Only ``NOT_DISPATCHED`` failures are eligible for the B62 pre-dispatch quota
compensation. Ambiguous Engine-boundary errors and any failure after a wire
response must never carry ``NOT_DISPATCHED``, and the conservative default is
``UNKNOWN`` (never refundable).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration import OrchestrationResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_engine_client import (
    EngineTransportResponse,
    PadiemAiEngineClient,
)

from kagent.contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01RequestFactory,
    P01_FAILURE_DETAIL_DOWNSTREAM,
    P01_FAILURE_DETAIL_UNKNOWN,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.runs import ClawRun

_FAKE_CREDENTIAL = "b54-test-credential-" + ("0" * 32)
_COMPLETED_RUN_ID = "orch_dispatch_001"


class FakeEngineTransport:
    def __init__(self, response: EngineTransportResponse) -> None:
        self._response = response
        self.requests: list[dict] = []

    async def request(self, *, method, url, headers, body):
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return self._response


def _intent(task_id: str = "task_dispatch") -> ClawTaskIntent:
    return ClawTaskIntent(
        task_id=task_id,
        task="P01 디스패치 분류를 검증해줘",
        repository_ref="skerishKang/example",
        execution_mode=ExecutionMode.LOCAL,
    )


def _build_request():
    run = ClawRun.create("run_dispatch", _intent())
    bundle = P01RequestFactory().build(run)
    return run, bundle.orchestration_request


def _public_result(request, *, answer: str = "완료 답변") -> dict:
    kinds = (
        OrchestrationEventKind.RUN_STARTED,
        OrchestrationEventKind.CONTEXT_PREPARED,
        OrchestrationEventKind.RUN_COMPLETED,
    )
    events = [
        public_orchestration_event(
            event_id=f"evt_{sequence:03d}",
            run_id=_COMPLETED_RUN_ID,
            trace_id=request.context.trace_id,
            app_id=request.app_id,
            kind=kind,
            sequence=sequence,
            message=None,
            timestamp_iso="2026-09-09T10:00:00+00:00",
        )
        for sequence, kind in enumerate(kinds, start=1)
    ]
    result = OrchestrationResult(
        execution_result=ExecutionResult(
            answer=answer,
            route=B14RouteMetadata(),
            metadata=RunMetadata(
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                agent_id=P01_AGENT_ID,
                session_id=request.execution_request.session_id,
                status=RunStatus.COMPLETED,
            ),
        ),
        context=request.context,
        app_id=request.app_id,
        subject_id=None,
        plan=None,
        activated_skill=None,
        resolved_tool_ids=(),
        evidence_graph=None,
        claim_assessments=(),
        grounded_citations=(),
        events=tuple(events),
    )
    return result.to_public_dict()


def _ok_transport(public: dict) -> FakeEngineTransport:
    body = json.dumps({"ok": True, "orchestration": public}, ensure_ascii=False)
    return FakeEngineTransport(EngineTransportResponse(status=200, body=body.encode("utf-8")))


def _client(transport: FakeEngineTransport) -> PadiemAiEngineClient:
    return PadiemAiEngineClient(
        transport=transport,
        app_id=P01_APP_ID,
        caller_id="b54-kagent",
        credential=_FAKE_CREDENTIAL,
    )


def _run_port(transport: FakeEngineTransport, request):
    port = P01EngineOrchestrationClient(_client(transport))
    return asyncio.run(port.run(request))


class P01DispatchClassificationTests(unittest.TestCase):
    def test_default_dispatch_class_is_conservative_unknown(self) -> None:
        error = P01AdapterError("some_code", "safe message")
        self.assertEqual(error.dispatch_class, P01DispatchClass.UNKNOWN)

    def test_terminal_run_build_failure_is_not_dispatched(self) -> None:
        run = ClawRun.create("run_terminal", _intent(task_id="task_terminal"))
        run.transition(ClawRunStatus.FAILED, summary="terminal")
        with self.assertRaises(P01AdapterError) as ctx:
            P01RequestFactory().build(run)
        self.assertEqual(ctx.exception.code, "terminal_run")
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)

    def test_authority_pinning_is_refused_as_not_dispatched_before_transport(self) -> None:
        _, request = _build_request()
        bad_agent = replace(
            request.execution_request.agent,
            model_policy={"model": "caller/invented-model"},
        )
        bad_request = replace(
            request,
            execution_request=replace(request.execution_request, agent=bad_agent),
        )
        transport = _ok_transport(_public_result(request))

        with self.assertRaises(P01AdapterError) as ctx:
            _run_port(transport, bad_request)
        self.assertEqual(ctx.exception.code, "p01_authority_pinning")
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
        self.assertEqual(transport.requests, [])

    def test_engine_boundary_failure_is_unknown_not_not_dispatched(self) -> None:
        _, request = _build_request()
        body = json.dumps(
            {"ok": False, "error": {"code": "upstream_error", "message": "engine detail"}}
        ).encode("utf-8")
        transport = FakeEngineTransport(EngineTransportResponse(status=503, body=body))

        with self.assertRaises(P01AdapterError) as ctx:
            _run_port(transport, request)
        self.assertEqual(ctx.exception.code, "p01_engine_request_failed")
        self.assertEqual(ctx.exception.failure_detail, P01_FAILURE_DETAIL_DOWNSTREAM)
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.UNKNOWN)
        self.assertEqual(len(transport.requests), 1)

    def test_rate_limited_engine_response_is_unknown_not_not_dispatched(self) -> None:
        _, request = _build_request()
        body = json.dumps(
            {"ok": False, "error": {"code": "upstream_rate_limited", "message": "busy"}}
        ).encode("utf-8")
        transport = FakeEngineTransport(EngineTransportResponse(status=429, body=body))

        with self.assertRaises(P01AdapterError) as ctx:
            _run_port(transport, request)
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.UNKNOWN)

    def test_malformed_response_after_dispatch_is_dispatched(self) -> None:
        _, request = _build_request()
        public = _public_result(request)
        public["tool_authorization"] = {"grant": "unreviewed"}
        transport = _ok_transport(public)

        with self.assertRaises(P01AdapterError) as ctx:
            _run_port(transport, request)
        self.assertEqual(ctx.exception.code, "unsupported_result_field")
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.DISPATCHED)

    def test_correlation_mismatch_after_dispatch_is_dispatched(self) -> None:
        _, request = _build_request()
        public = _public_result(request)
        public["execution"]["metadata"]["session_id"] = "someone_elses_run"
        transport = _ok_transport(public)

        with self.assertRaises(P01AdapterError) as ctx:
            _run_port(transport, request)
        self.assertEqual(ctx.exception.code, "p01_result_correlation_mismatch")
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.DISPATCHED)

    def test_adapter_preserves_not_dispatched_classification_from_runner(self) -> None:
        class _PreDispatchRunner:
            def __init__(self) -> None:
                self.calls = 0

            async def run(self, request):
                self.calls += 1
                raise P01AdapterError(
                    "terminal_run",
                    "pre-dispatch failure",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )

        runner = _PreDispatchRunner()
        adapter = P01CoreOrchestrationAdapter(runner)
        run = ClawRun.create("run_preserve", _intent(task_id="task_preserve"))

        with self.assertRaises(P01AdapterError) as ctx:
            asyncio.run(adapter.execute(run))
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
        self.assertEqual(runner.calls, 1)

    def test_adapter_wraps_unexpected_failure_as_conservative_unknown(self) -> None:
        class _ExplodingRunner:
            async def run(self, request):
                raise RuntimeError("ambiguous network state")

        adapter = P01CoreOrchestrationAdapter(_ExplodingRunner())
        run = ClawRun.create("run_explode", _intent(task_id="task_explode"))

        with self.assertRaises(P01AdapterError) as ctx:
            asyncio.run(adapter.execute(run))
        self.assertEqual(ctx.exception.code, "p01_execution_failed")
        self.assertEqual(ctx.exception.failure_detail, P01_FAILURE_DETAIL_UNKNOWN)
        self.assertEqual(ctx.exception.dispatch_class, P01DispatchClass.UNKNOWN)

    def test_successful_execution_produces_no_error(self) -> None:
        run, request = _build_request()
        transport = _ok_transport(_public_result(request))
        adapter = P01CoreOrchestrationAdapter(P01EngineOrchestrationClient(_client(transport)))

        outcome = asyncio.run(adapter.execute(run))
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
