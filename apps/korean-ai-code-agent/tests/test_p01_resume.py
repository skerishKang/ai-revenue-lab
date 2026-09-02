from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    OrchestrationResumeRequest,
    OrchestrationResult,
    OrchestrationRunner,
    VerifiedApprovalDecision,
)
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)

from kagent.contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import P01_AGENT_ID, P01_APP_ID, P01AdapterError, P01RequestFactory
from kagent.p01_resume import (
    APPROVAL_FROM_CHAT_SENTIMENT_SUPPORTED,
    B54_MINTS_VERIFIED_APPROVAL_DECISION,
    P01ApprovalResumeAdapter,
)
from kagent.runs import ClawRun


NOW = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)


class _Runtime:
    def __init__(self, answer: str = "재개 완료") -> None:
        self.answer = answer
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return ExecutionResult(
            answer=self.answer,
            route=B14RouteMetadata(),
            metadata=RunMetadata(
                trace_id=request.trace_id,
                app_id=P01_APP_ID,
                agent_id=P01_AGENT_ID,
                session_id=request.session_id,
                status=RunStatus.COMPLETED,
            ),
        )


class _FakeResumeRunner:
    def __init__(self, kinds, *, next_pause: ApprovalPause | None = None, answer: str = "완료") -> None:
        self.kinds = tuple(kinds)
        self.next_pause = next_pause
        self.answer = answer
        self.requests = []

    async def resume(self, request):
        self.requests.append(request)
        events = tuple(
            public_orchestration_event(
                event_id=f"evt_resume_{index}",
                run_id=request.pause.run_id,
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                kind=kind,
                sequence=index,
                message="추가 승인 token=fixturevalue" if kind is OrchestrationEventKind.APPROVAL_PAUSED else None,
                timestamp_iso="2026-09-02T16:10:00+00:00",
            )
            for index, kind in enumerate(self.kinds, start=1)
        )
        status = RunStatus.PAUSED if self.next_pause is not None else RunStatus.COMPLETED
        return OrchestrationResult(
            execution_result=ExecutionResult(
                answer=self.answer,
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=request.context.trace_id,
                    app_id=request.app_id,
                    agent_id=P01_AGENT_ID,
                    session_id=request.execution_request.session_id,
                    status=status,
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
            approval_pause=self.next_pause,
        )


class P01ApprovalResumeTests(unittest.IsolatedAsyncioTestCase):
    def make_waiting_run_and_request(
        self,
        *,
        outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
        consumed_decision_ids: frozenset[str] = frozenset(),
    ) -> tuple[ClawRun, OrchestrationResumeRequest]:
        intent = ClawTaskIntent(
            task_id="task_resume",
            task="승인 후 작업을 계속해줘",
            repository_ref="skerishKang/example",
            execution_mode=ExecutionMode.LOCAL,
            trace_id="trace_resume",
        )
        run = ClawRun.create("run_resume", intent)
        bundle = P01RequestFactory().build(run)
        run.transition(ClawRunStatus.RUNNING, summary="실행 중")
        run.transition(ClawRunStatus.WAITING_APPROVAL, summary="승인 대기")
        pause = ApprovalPause(
            pause_id="pause_resume_1",
            run_id="orch_resume_1",
            agent_runtime_id=P01_AGENT_ID,
            tool_id="tool_write_file",
            invocation_sha256="a" * 64,
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            trace_id=bundle.context.trace_id,
            plan_id="plan_resume_1",
            approval_scope=("workspace_write",),
        )
        decision = VerifiedApprovalDecision(
            decision_id="decision_resume_1",
            pause_id=pause.pause_id,
            outcome=outcome,
            authority_ref="actor:user_1",
            evidence_ref="evidence:approval_1",
            decided_at=NOW + timedelta(minutes=5),
        )
        request = OrchestrationResumeRequest(
            pause=pause,
            decision=decision,
            execution_request=bundle.execution_request,
            context=bundle.context,
            app_id=P01_APP_ID,
            subject_id=None,
            now=NOW + timedelta(minutes=10),
            consumed_decision_ids=consumed_decision_ids,
        )
        return run, request

    async def test_real_core_resume_projects_running_then_completed(self):
        run, request = self.make_waiting_run_and_request()
        runtime = _Runtime(answer="완료 token=fixturevalue")
        outcome = await P01ApprovalResumeAdapter(OrchestrationRunner(runtime=runtime)).resume(
            run,
            request=request,
        )
        self.assertEqual(run.status, ClawRunStatus.COMPLETED)
        self.assertFalse(outcome.projection.approval_required)
        self.assertEqual(outcome.p01_run_id, request.pause.run_id)
        self.assertGreaterEqual(outcome.p01_event_count, 3)
        self.assertNotIn("fixturevalue", outcome.answer or "")
        self.assertEqual(len(runtime.requests), 1)
        rendered = str(outcome.safe_dict())
        self.assertNotIn("invocation_sha256", rendered)
        self.assertNotIn("provider", rendered)

    async def test_denied_decision_is_validated_by_core_then_projects_cancelled(self):
        run, request = self.make_waiting_run_and_request(outcome=ApprovalOutcome.DENIED)
        runtime = _Runtime()
        outcome = await P01ApprovalResumeAdapter(OrchestrationRunner(runtime=runtime)).resume(
            run,
            request=request,
        )
        self.assertEqual(run.status, ClawRunStatus.CANCELLED)
        self.assertEqual(outcome.decision_id, request.decision.decision_id)
        self.assertIsNone(outcome.answer)
        self.assertEqual(len(runtime.requests), 0)

    async def test_consumed_decision_replay_is_rejected_by_core_without_consuming_valid_pause(self):
        run, request = self.make_waiting_run_and_request()
        request = replace(
            request,
            consumed_decision_ids=frozenset({request.decision.decision_id}),
        )
        with self.assertRaises(P01AdapterError) as caught:
            await P01ApprovalResumeAdapter(OrchestrationRunner(runtime=_Runtime())).resume(
                run,
                request=request,
            )
        self.assertEqual(caught.exception.code, "invalid_decision")
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)

    async def test_mismatched_decision_pause_is_rejected_before_runner_and_waiting_state_is_preserved(self):
        run, request = self.make_waiting_run_and_request()
        bad_decision = replace(request.decision, pause_id="pause_other")
        bad_request = replace(request, decision=bad_decision)
        runner = _FakeResumeRunner([])
        with self.assertRaises(P01AdapterError) as caught:
            await P01ApprovalResumeAdapter(runner).resume(run, request=bad_request)
        self.assertEqual(caught.exception.code, "resume_pause_mismatch")
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)
        self.assertEqual(runner.requests, [])

    async def test_session_or_trace_substitution_is_rejected_before_resume(self):
        run, request = self.make_waiting_run_and_request()
        runner = _FakeResumeRunner([])
        wrong_session = replace(
            request,
            execution_request=replace(request.execution_request, session_id="run_other"),
        )
        with self.assertRaises(P01AdapterError):
            await P01ApprovalResumeAdapter(runner).resume(run, request=wrong_session)
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)

        wrong_context = replace(request, context=replace(request.context, trace_id="trace_other"))
        with self.assertRaises(P01AdapterError):
            await P01ApprovalResumeAdapter(runner).resume(run, request=wrong_context)
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)
        self.assertEqual(runner.requests, [])

    async def test_completion_without_run_resumed_fails_closed(self):
        run, request = self.make_waiting_run_and_request()
        runner = _FakeResumeRunner(
            [OrchestrationEventKind.RUN_STARTED, OrchestrationEventKind.RUN_COMPLETED]
        )
        with self.assertRaises(P01AdapterError):
            await P01ApprovalResumeAdapter(runner).resume(run, request=request)
        self.assertEqual(run.status, ClawRunStatus.FAILED)

    async def test_second_canonical_pause_returns_to_waiting_and_exposes_only_safe_pause_id(self):
        run, request = self.make_waiting_run_and_request()
        next_pause = ApprovalPause(
            pause_id="pause_resume_2",
            run_id=request.pause.run_id,
            agent_runtime_id=P01_AGENT_ID,
            tool_id="tool_send_message",
            invocation_sha256="b" * 64,
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=2,
            created_at=NOW + timedelta(minutes=11),
            expires_at=NOW + timedelta(hours=1),
            trace_id=request.context.trace_id,
            plan_id="plan_resume_1",
            approval_scope=("external_send",),
        )
        runner = _FakeResumeRunner(
            [
                OrchestrationEventKind.RUN_STARTED,
                OrchestrationEventKind.RUN_RESUMED,
                OrchestrationEventKind.APPROVAL_PAUSED,
            ],
            next_pause=next_pause,
        )
        outcome = await P01ApprovalResumeAdapter(runner).resume(run, request=request)
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)
        self.assertEqual(outcome.next_pause, next_pause)
        self.assertTrue(outcome.projection.approval_required)
        self.assertNotIn("fixturevalue", run.summary)
        rendered = outcome.safe_dict()
        self.assertEqual(rendered["next_pause_id"], "pause_resume_2")
        self.assertNotIn("invocation_sha256", str(rendered))

    def test_product_never_infers_or_mints_approval(self):
        self.assertFalse(APPROVAL_FROM_CHAT_SENTIMENT_SUPPORTED)
        self.assertFalse(B54_MINTS_VERIFIED_APPROVAL_DECISION)


if __name__ == "__main__":
    unittest.main()
