from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import unittest

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
    P01RequestFactory,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.runs import ClawRun


_FAKE_CREDENTIAL = "b54-test-credential-" + ("0" * 32)
_COMPLETED_RUN_ID = "orch_test_001"


class FakeEngineTransport:
    """Network-free transport: records requests, replays a canned response."""

    def __init__(self, response: EngineTransportResponse) -> None:
        self._response = response
        self.requests: list[dict] = []

    async def request(self, *, method, url, headers, body):
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        return self._response


def _build_request():
    intent = ClawTaskIntent(
        task_id="task_p01_client",
        task="P01 오케스트레이션 포트를 검증해줘",
        repository_ref="skerishKang/example",
        execution_mode=ExecutionMode.LOCAL,
    )
    run = ClawRun.create("run_p01_client", intent)
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
            timestamp_iso="2026-09-05T10:00:00+00:00",
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


class P01EngineOrchestrationClientTests(unittest.TestCase):
    def run_port(self, transport: FakeEngineTransport, request):
        port = P01EngineOrchestrationClient(_client(transport))
        return asyncio.run(port.run(request))

    def test_happy_path_reconstructs_core_result(self) -> None:
        _, request = _build_request()
        transport = _ok_transport(_public_result(request))

        result = self.run_port(transport, request)

        self.assertIsInstance(result, OrchestrationResult)
        self.assertEqual(result.app_id, P01_APP_ID)
        self.assertEqual(result.context.trace_id, request.context.trace_id)
        self.assertEqual(result.execution_result.answer, "완료 답변")
        self.assertEqual(
            [event.kind for event in result.events],
            [
                OrchestrationEventKind.RUN_STARTED,
                OrchestrationEventKind.CONTEXT_PREPARED,
                OrchestrationEventKind.RUN_COMPLETED,
            ],
        )
        self.assertEqual([event.sequence for event in result.events], [1, 2, 3])
        self.assertEqual(transport.requests[0]["url"], "https://padiem-ai-engine.internal/internal/v1/orchestrate")

    def test_outgoing_payload_pins_approved_free_model_only(self) -> None:
        _, request = _build_request()
        transport = _ok_transport(_public_result(request))

        self.run_port(transport, request)

        sent = transport.requests[0]
        payload = json.loads(sent["body"].decode("utf-8"))
        self.assertTrue(
            set(payload)
            <= {"app_id", "agent", "messages", "session_id", "trace_id", "execution_context"}
        )
        self.assertEqual(payload["app_id"], P01_APP_ID)
        self.assertEqual(payload["agent"]["id"], P01_AGENT_ID)
        self.assertEqual(payload["agent"]["model_policy"], {"model": "stealth/ox-alpha"})
        self.assertNotIn("provider", json.dumps(payload).lower())
        self.assertNotIn("credential", payload["agent"])
        self.assertNotIn("api_key", json.dumps(payload).lower())
        self.assertNotIn(_FAKE_CREDENTIAL, sent["body"].decode("utf-8"))
        self.assertEqual(sent["headers"]["X-Padiem-Engine-Credential"], _FAKE_CREDENTIAL)
        self.assertEqual(sent["headers"]["X-Padiem-Engine-Caller"], "b54-kagent")

    def test_unapproved_model_policy_is_refused_before_transport(self) -> None:
        _, request = _build_request()
        bad_agent = replace(
            request.execution_request.agent,
            model_policy={"model": "google/gemini-2.5-flash"},
        )
        bad_execution = replace(request.execution_request, agent=bad_agent)
        bad_request = replace(request, execution_request=bad_execution)
        transport = _ok_transport(_public_result(request))

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, bad_request)
        self.assertEqual(ctx.exception.code, "p01_authority_pinning")
        self.assertEqual(transport.requests, [])

    def test_empty_model_policy_is_accepted_for_back_compat(self) -> None:
        _, request = _build_request()
        empty_agent = replace(request.execution_request.agent, model_policy={})
        empty_execution = replace(request.execution_request, agent=empty_agent)
        empty_request = replace(request, execution_request=empty_execution)
        transport = _ok_transport(_public_result(empty_request))

        self.run_port(transport, empty_request)
        sent = transport.requests[0]
        payload = json.loads(sent["body"].decode("utf-8"))
        self.assertEqual(payload["agent"]["model_policy"], {})

    def test_unknown_result_field_fails_closed(self) -> None:
        _, request = _build_request()
        public = _public_result(request)
        public["tool_authorization"] = {"grant": "unreviewed"}
        transport = _ok_transport(public)

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, request)
        self.assertEqual(ctx.exception.code, "unsupported_result_field")

    def test_approval_pause_result_fails_closed(self) -> None:
        _, request = _build_request()
        public = _public_result(request)
        public["approval_pause"] = {"status": "paused", "continuation_id": "cont_abc12345"}
        public["continuation_ref"] = "cont_abc12345"
        transport = _ok_transport(public)

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, request)
        self.assertEqual(ctx.exception.code, "unsupported_result_approval_pause")

    def test_engine_error_maps_to_adapter_error_without_leakage(self) -> None:
        _, request = _build_request()
        body = json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "upstream_rate_limited",
                    "message": "provider secret detail must not escape",
                },
            }
        ).encode("utf-8")
        transport = FakeEngineTransport(EngineTransportResponse(status=429, body=body))

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, request)
        self.assertEqual(ctx.exception.code, "p01_engine_request_failed")
        self.assertNotIn("provider", ctx.exception.safe_message.lower())
        self.assertNotIn("secret", ctx.exception.safe_message.lower())

    def test_authority_bearing_request_is_refused_before_transport(self) -> None:
        _, request = _build_request()
        pinned = replace(request, subject_id="subject_1")
        transport = _ok_transport(_public_result(request))

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, pinned)
        self.assertEqual(ctx.exception.code, "p01_authority_field_unsupported")
        self.assertEqual(transport.requests, [])

    def test_idempotency_key_is_refused_before_transport(self) -> None:
        _, request = _build_request()
        replayable = replace(
            request,
            context=replace(request.context, idempotency_key="claw_replay_key"),
        )
        transport = _ok_transport(_public_result(request))

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, replayable)
        self.assertEqual(ctx.exception.code, "p01_authority_field_unsupported")
        self.assertEqual(transport.requests, [])

    def test_mismatched_app_identity_on_client_is_refused(self) -> None:
        _, request = _build_request()
        transport = _ok_transport(_public_result(request))
        port = P01EngineOrchestrationClient(
            PadiemAiEngineClient(
                transport=transport,
                app_id="other-app",
                caller_id="b54-kagent",
                credential=_FAKE_CREDENTIAL,
            )
        )

        with self.assertRaises(P01AdapterError) as ctx:
            asyncio.run(port.run(request))
        self.assertEqual(ctx.exception.code, "p01_app_id_mismatch")
        self.assertEqual(transport.requests, [])

    def test_result_correlation_mismatch_fails_closed(self) -> None:
        _, request = _build_request()
        public = _public_result(request)
        public["execution"]["metadata"]["session_id"] = "someone_elses_run"
        transport = _ok_transport(public)

        with self.assertRaises(P01AdapterError) as ctx:
            self.run_port(transport, request)
        self.assertEqual(ctx.exception.code, "p01_result_correlation_mismatch")

    def test_adapter_executes_claw_run_over_the_engine_port(self) -> None:
        run, request = _build_request()
        transport = _ok_transport(_public_result(request))
        adapter = P01CoreOrchestrationAdapter(P01EngineOrchestrationClient(_client(transport)))

        outcome = asyncio.run(adapter.execute(run))

        self.assertEqual(run.status, ClawRunStatus.COMPLETED)
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(outcome.answer, "완료 답변")
        self.assertEqual(outcome.p01_run_id, _COMPLETED_RUN_ID)
        self.assertEqual(outcome.p01_event_count, 3)


if __name__ == "__main__":
    unittest.main()
