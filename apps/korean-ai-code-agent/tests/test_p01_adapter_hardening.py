from __future__ import annotations

import asyncio
import unittest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    OrchestrationEventKind,
    OrchestrationResult,
    OrchestrationRunner,
    RunMetadata,
    RunStatus,
    public_orchestration_event,
)

from kagent.contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    ClawOrchestrationProjector,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01ProjectionError,
)
from kagent.runs import ClawRun


class _NetworkFreeRuntime:
    async def run(self, request):
        return ExecutionResult(
            answer="실제 P01 OrchestrationRunner 경계 통과",
            route=B14RouteMetadata(),
            metadata=RunMetadata(
                trace_id=request.trace_id,
                app_id=P01_APP_ID,
                agent_id=request.agent.id,
                session_id=request.session_id,
                status=RunStatus.COMPLETED,
            ),
        )


class _CancelledRuntime:
    async def run(self, request):
        raise asyncio.CancelledError()


class _WrongCorrelationRunner:
    async def run(self, request):
        events = (
            public_orchestration_event(
                event_id="evt_mismatch_1",
                run_id="orch_mismatch",
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                kind=OrchestrationEventKind.RUN_STARTED,
                sequence=1,
                timestamp_iso="2026-09-02T10:00:00+00:00",
            ),
            public_orchestration_event(
                event_id="evt_mismatch_2",
                run_id="orch_mismatch",
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                kind=OrchestrationEventKind.RUN_COMPLETED,
                sequence=2,
                timestamp_iso="2026-09-02T10:00:01+00:00",
            ),
        )
        return OrchestrationResult(
            execution_result=ExecutionResult(
                answer="잘못 상관된 결과",
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=request.context.trace_id,
                    app_id="other-app",
                    agent_id=P01_AGENT_ID,
                    session_id=request.execution_request.session_id,
                    status=RunStatus.COMPLETED,
                ),
            ),
            context=request.context,
            app_id=request.app_id,
            subject_id=request.subject_id,
            plan=None,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=events,
        )


def _local_run(run_id: str) -> ClawRun:
    return ClawRun.create(
        run_id,
        ClawTaskIntent(
            task_id=f"task_{run_id}",
            task="저장소 오류를 분석하고 수정해줘",
            repository_ref="skerishKang/example",
            execution_mode=ExecutionMode.LOCAL,
        ),
    )


class P01PublicContractConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_core_orchestration_runner_projects_network_free_completion(self):
        run = _local_run("run_real_core")
        runner = OrchestrationRunner(runtime=_NetworkFreeRuntime())

        outcome = await P01CoreOrchestrationAdapter(runner).execute(run)

        self.assertEqual(run.status, ClawRunStatus.COMPLETED)
        self.assertEqual(outcome.answer, "실제 P01 OrchestrationRunner 경계 통과")
        self.assertIsNotNone(outcome.p01_run_id)
        self.assertGreaterEqual(outcome.p01_event_count, 3)

    async def test_real_core_cancellation_remains_b54_cancellation(self):
        run = _local_run("run_cancelled")
        runner = OrchestrationRunner(runtime=_CancelledRuntime())

        with self.assertRaises(asyncio.CancelledError):
            await P01CoreOrchestrationAdapter(runner).execute(run)

        self.assertEqual(run.status, ClawRunStatus.CANCELLED)
        self.assertTrue(run.terminal)

    async def test_result_metadata_correlation_mismatch_fails_closed(self):
        run = _local_run("run_bad_result")

        with self.assertRaises(P01AdapterError) as caught:
            await P01CoreOrchestrationAdapter(_WrongCorrelationRunner()).execute(run)

        self.assertEqual(caught.exception.code, "p01_result_correlation_mismatch")
        self.assertEqual(run.status, ClawRunStatus.FAILED)
        self.assertTrue(run.terminal)


class P01EventSequenceHardeningTests(unittest.TestCase):
    def test_projector_rejects_missing_sequence_gap(self):
        run = _local_run("run_sequence_gap")
        run.transition(ClawRunStatus.PREPARING, summary="준비")
        trace_id = "trace_sequence_gap"
        projector = ClawOrchestrationProjector(run, trace_id=trace_id)

        projector.consume(
            public_orchestration_event(
                event_id="evt_gap_1",
                run_id="orch_gap",
                trace_id=trace_id,
                app_id=P01_APP_ID,
                kind=OrchestrationEventKind.RUN_STARTED,
                sequence=1,
                timestamp_iso="2026-09-02T10:00:00+00:00",
            )
        )

        with self.assertRaises(P01ProjectionError) as caught:
            projector.consume(
                public_orchestration_event(
                    event_id="evt_gap_3",
                    run_id="orch_gap",
                    trace_id=trace_id,
                    app_id=P01_APP_ID,
                    kind=OrchestrationEventKind.RUN_COMPLETED,
                    sequence=3,
                    timestamp_iso="2026-09-02T10:00:02+00:00",
                )
            )

        self.assertEqual(caught.exception.code, "event_sequence_gap")
        self.assertEqual(run.status, ClawRunStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
