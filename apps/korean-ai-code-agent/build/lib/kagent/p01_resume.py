from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    OrchestrationError,
    OrchestrationEvent,
    OrchestrationEventKind,
    OrchestrationResumeRequest,
    OrchestrationResult,
)

from .contracts import ClawRunStatus, RunProjection
from .p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    P01AdapterError,
    P01ProjectionError,
    _trace_id_for,
)
from .runs import ClawRun, RunStateError
from .security import redact_secrets


class P01ResumePort(Protocol):
    async def resume(self, request: OrchestrationResumeRequest) -> OrchestrationResult: ...


@dataclass(frozen=True, slots=True)
class ClawResumeOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str
    p01_event_count: int
    decision_id: str
    next_pause: ApprovalPause | None = None

    def safe_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection.safe_dict(),
            "answer": redact_secrets(self.answer) if self.answer is not None else None,
            "p01_run_id": self.p01_run_id,
            "p01_event_count": self.p01_event_count,
            "decision_id": self.decision_id,
            "next_pause_id": self.next_pause.pause_id if self.next_pause is not None else None,
        }


class ClawResumeProjector:
    """Project one canonical P01 resume invocation into an existing Claw run.

    P01 emits a new RUN_STARTED envelope when `OrchestrationRunner.resume()` is
    entered. Because the B54 run is already WAITING_APPROVAL, that first event
    proves correlation only; B54 returns to RUNNING only after canonical
    RUN_RESUMED evidence is observed.
    """

    def __init__(
        self,
        run: ClawRun,
        *,
        trace_id: str,
        p01_run_id: str,
        app_id: str = P01_APP_ID,
    ) -> None:
        if run.status is not ClawRunStatus.WAITING_APPROVAL:
            raise P01ProjectionError(
                "run_not_waiting_approval",
                "Claw run must be WAITING_APPROVAL before P01 resume projection.",
            )
        self._run = run
        self._trace_id = trace_id
        self._p01_run_id = p01_run_id
        self._app_id = app_id
        self._last_sequence = 0
        self._seen_events: dict[str, tuple[object, ...]] = {}
        self._resume_seen = False

    @property
    def event_count(self) -> int:
        return len(self._seen_events)

    @property
    def resume_seen(self) -> bool:
        return self._resume_seen

    def consume(self, event: OrchestrationEvent) -> RunProjection:
        if not isinstance(event, OrchestrationEvent):
            raise P01ProjectionError("invalid_event", "Expected canonical P01 OrchestrationEvent.")
        if event.trace_id != self._trace_id or event.app_id != self._app_id:
            raise P01ProjectionError(
                "event_correlation_mismatch",
                "P01 resume event does not match Claw trace/app correlation.",
            )
        if event.run_id != self._p01_run_id:
            raise P01ProjectionError(
                "p01_run_mismatch",
                "P01 resume event belongs to a different orchestration run.",
            )

        fingerprint = self._event_fingerprint(event)
        previous = self._seen_events.get(event.event_id)
        if previous is not None:
            if previous != fingerprint:
                raise P01ProjectionError(
                    "event_id_reuse_conflict",
                    "P01 resume event_id was reused with different lifecycle data.",
                )
            return self._run.projection()

        expected_sequence = self._last_sequence + 1
        if event.sequence != expected_sequence:
            raise P01ProjectionError(
                "event_sequence_gap",
                "P01 resume event sequence must be contiguous and monotonic.",
            )
        if event.sequence == 1 and event.kind is not OrchestrationEventKind.RUN_STARTED:
            raise P01ProjectionError(
                "missing_resume_run_started",
                "First P01 resume event must be RUN_STARTED at sequence 1.",
            )
        if event.sequence > 1 and event.kind is OrchestrationEventKind.RUN_STARTED:
            raise P01ProjectionError(
                "duplicate_resume_run_started",
                "P01 resume RUN_STARTED may appear only as the first event.",
            )

        try:
            self._project_kind(event)
        except RunStateError:
            raise P01ProjectionError(
                "invalid_resume_transition",
                "P01 resume event is incompatible with the current Claw lifecycle state.",
            ) from None

        self._last_sequence = event.sequence
        self._seen_events[event.event_id] = fingerprint
        return self._run.projection()

    @staticmethod
    def _event_fingerprint(event: OrchestrationEvent) -> tuple[object, ...]:
        return (
            event.run_id,
            event.trace_id,
            event.app_id,
            event.kind.value,
            event.sequence,
            event.timestamp_iso,
            event.message,
            tuple(sorted(event.metadata.items())),
        )

    def _project_kind(self, event: OrchestrationEvent) -> None:
        kind = event.kind
        if self._run.terminal:
            raise P01ProjectionError(
                "terminal_run_event",
                "Late P01 resume event cannot mutate a terminal Claw run.",
            )

        if kind is OrchestrationEventKind.RUN_STARTED:
            # Correlation envelope only. B54 remains WAITING_APPROVAL until the
            # canonical RUN_RESUMED event proves that P01 accepted continuation.
            return
        if kind is OrchestrationEventKind.RUN_RESUMED:
            if self._resume_seen:
                raise P01ProjectionError(
                    "duplicate_run_resumed",
                    "P01 resume lifecycle may enter RUNNING only once per invocation.",
                )
            self._run.transition(
                ClawRunStatus.RUNNING,
                summary=redact_secrets(event.message or "승인 후 실행 재개"),
            )
            self._resume_seen = True
            return
        if kind is OrchestrationEventKind.APPROVAL_PAUSED:
            if not self._resume_seen:
                raise P01ProjectionError(
                    "pause_before_resume",
                    "P01 cannot project a new approval pause before RUN_RESUMED.",
                )
            self._run.transition(
                ClawRunStatus.WAITING_APPROVAL,
                summary=redact_secrets(event.message or "추가 승인 대기"),
            )
            return
        if kind is OrchestrationEventKind.RUN_COMPLETED:
            if not self._resume_seen:
                raise P01ProjectionError(
                    "completion_before_resume",
                    "P01 completion requires canonical RUN_RESUMED evidence.",
                )
            self._run.transition(
                ClawRunStatus.COMPLETED,
                summary=redact_secrets(event.message or "작업 완료"),
            )
            return
        if kind is OrchestrationEventKind.RUN_FAILED:
            self._run.transition(
                ClawRunStatus.FAILED,
                summary=redact_secrets(event.message or "P01 재개 실행 실패"),
            )
            return
        if kind is OrchestrationEventKind.RUN_CANCELLED:
            self._run.transition(
                ClawRunStatus.CANCELLED,
                summary=redact_secrets(event.message or "P01 재개 실행 취소"),
            )


class P01ApprovalResumeAdapter:
    """Thin B54 consumer of canonical P01 approval continuation semantics.

    This adapter never authenticates an actor, mints VerifiedApprovalDecision,
    widens ToolAuthorizationContext, or reconstructs tool arguments. A trusted
    caller must provide a fully formed canonical OrchestrationResumeRequest.
    """

    def __init__(self, runner: P01ResumePort) -> None:
        resume_method = getattr(runner, "resume", None)
        if not callable(resume_method):
            raise P01AdapterError(
                "invalid_resume_runner",
                "P01 resume runner must expose async resume(request).",
            )
        self._runner = runner

    async def resume(
        self,
        run: ClawRun,
        *,
        request: OrchestrationResumeRequest,
    ) -> ClawResumeOutcome:
        self._validate_request(run, request)
        trace_id = _trace_id_for(run)
        projector = ClawResumeProjector(
            run,
            trace_id=trace_id,
            p01_run_id=request.pause.run_id,
            app_id=request.app_id,
        )

        try:
            result = await self._runner.resume(request)
        except asyncio.CancelledError:
            self._cancel_run_if_possible(run, "P01 재개 실행이 취소되었습니다.")
            raise
        except OrchestrationError as exc:
            if exc.code == "approval_denied":
                self._cancel_run_if_possible(run, "사용자가 승인을 거절했습니다.")
                return ClawResumeOutcome(
                    projection=run.projection(),
                    answer=None,
                    p01_run_id=request.pause.run_id,
                    p01_event_count=0,
                    decision_id=request.decision.decision_id,
                    next_pause=None,
                )
            if exc.code in {"invalid_decision", "continuation_identity_mismatch"}:
                # Keep the valid pending pause retryable. P01 remains the authority
                # that rejected this decision; B54 does not consume or replace it.
                raise P01AdapterError(
                    exc.code,
                    "P01 rejected the approval decision correlation.",
                ) from None
            if exc.code == "continuation_expired":
                self._fail_run_if_possible(run, "승인 대기 시간이 만료되었습니다.")
                raise P01AdapterError(
                    "continuation_expired",
                    "P01 approval continuation expired before resume.",
                ) from None
            self._fail_run_if_possible(run, "P01 승인 재개 실행이 실패했습니다.")
            raise P01AdapterError(
                "p01_resume_rejected",
                "P01 rejected the approval resume request.",
            ) from None
        except Exception:
            self._fail_run_if_possible(run, "P01 승인 재개 실행이 실패했습니다.")
            raise P01AdapterError(
                "p01_resume_failed",
                "P01 approval resume failed without a safe product result.",
            ) from None

        try:
            if not isinstance(result, OrchestrationResult):
                raise P01AdapterError(
                    "invalid_p01_resume_result",
                    "P01 resume runner returned an invalid orchestration result.",
                )
            self._validate_result_correlation(run, request, result)
            for event in result.events:
                projector.consume(event)

            if not run.terminal and run.status is not ClawRunStatus.WAITING_APPROVAL:
                raise P01AdapterError(
                    "incomplete_p01_resume_lifecycle",
                    "P01 resume ended without terminal or approval-paused lifecycle evidence.",
                )
            if run.status is ClawRunStatus.COMPLETED and not projector.resume_seen:
                raise P01AdapterError(
                    "missing_run_resumed",
                    "P01 resume completed without RUN_RESUMED evidence.",
                )

            next_pause = result.approval_pause
            if next_pause is not None:
                self._validate_next_pause(request, projector, next_pause)
                if run.status is not ClawRunStatus.WAITING_APPROVAL:
                    raise P01AdapterError(
                        "unexpected_next_pause",
                        "P01 returned an approval pause without WAITING_APPROVAL lifecycle state.",
                    )
            elif run.status is ClawRunStatus.WAITING_APPROVAL:
                raise P01AdapterError(
                    "missing_next_pause",
                    "P01 paused again without returning the canonical approval pause.",
                )

            answer = (
                redact_secrets(result.execution_result.answer)
                if run.status is ClawRunStatus.COMPLETED
                else None
            )
            return ClawResumeOutcome(
                projection=run.projection(),
                answer=answer,
                p01_run_id=request.pause.run_id,
                p01_event_count=projector.event_count,
                decision_id=request.decision.decision_id,
                next_pause=next_pause,
            )
        except P01AdapterError:
            self._fail_run_if_possible(run, "P01 승인 재개 결과를 안전하게 투영할 수 없습니다.")
            raise
        except (RunStateError, ValueError):
            self._fail_run_if_possible(run, "P01 승인 재개 결과를 안전하게 투영할 수 없습니다.")
            raise P01AdapterError(
                "p01_resume_contract_failure",
                "P01 approval resume contract could not be safely projected.",
            ) from None
        except Exception:
            self._fail_run_if_possible(run, "P01 승인 재개 결과를 안전하게 투영할 수 없습니다.")
            raise P01AdapterError(
                "p01_resume_projection_failed",
                "P01 approval resume result could not be safely projected.",
            ) from None

    @staticmethod
    def _validate_request(run: ClawRun, request: OrchestrationResumeRequest) -> None:
        if run.status is not ClawRunStatus.WAITING_APPROVAL:
            raise P01AdapterError(
                "run_not_waiting_approval",
                "Claw run must be waiting for approval before canonical P01 resume.",
            )
        if not isinstance(request, OrchestrationResumeRequest):
            raise P01AdapterError(
                "invalid_resume_request",
                "Expected canonical P01 OrchestrationResumeRequest.",
            )
        expected_trace = _trace_id_for(run)
        if request.app_id != P01_APP_ID:
            raise P01AdapterError("resume_app_mismatch", "P01 resume app correlation mismatch.")
        if request.execution_request.agent.id != P01_AGENT_ID:
            raise P01AdapterError("resume_agent_mismatch", "P01 resume agent correlation mismatch.")
        if request.execution_request.session_id != run.run_id:
            raise P01AdapterError("resume_session_mismatch", "P01 resume session correlation mismatch.")
        if (
            request.execution_request.trace_id != expected_trace
            or request.context.trace_id != expected_trace
        ):
            raise P01AdapterError("resume_trace_mismatch", "P01 resume trace correlation mismatch.")
        if request.pause.trace_id is not None and request.pause.trace_id != expected_trace:
            raise P01AdapterError("resume_pause_trace_mismatch", "P01 approval pause trace mismatch.")
        if request.pause.agent_id != P01_AGENT_ID:
            raise P01AdapterError("resume_pause_agent_mismatch", "P01 approval pause agent mismatch.")
        if request.decision.pause_id != request.pause.pause_id:
            raise P01AdapterError("resume_pause_mismatch", "P01 approval decision does not match the pause.")

    @staticmethod
    def _validate_result_correlation(
        run: ClawRun,
        request: OrchestrationResumeRequest,
        result: OrchestrationResult,
    ) -> None:
        expected_trace = _trace_id_for(run)
        metadata = result.execution_result.metadata
        if (
            result.context.trace_id != expected_trace
            or result.app_id != P01_APP_ID
            or metadata.trace_id != expected_trace
            or metadata.app_id != P01_APP_ID
            or metadata.agent_id != P01_AGENT_ID
            or metadata.session_id != run.run_id
        ):
            raise P01AdapterError(
                "p01_resume_result_correlation_mismatch",
                "P01 resume result does not match the trusted Claw run correlation.",
            )
        if result.subject_id != request.subject_id:
            raise P01AdapterError(
                "p01_resume_subject_mismatch",
                "P01 resume result changed the trusted subject correlation.",
            )

    @staticmethod
    def _validate_next_pause(
        request: OrchestrationResumeRequest,
        projector: ClawResumeProjector,
        pause: ApprovalPause,
    ) -> None:
        if pause.run_id != request.pause.run_id:
            raise P01AdapterError(
                "next_pause_run_mismatch",
                "Next P01 approval pause belongs to a different orchestration run.",
            )
        if pause.trace_id is not None and pause.trace_id != request.context.trace_id:
            raise P01AdapterError(
                "next_pause_trace_mismatch",
                "Next P01 approval pause changed trace correlation.",
            )
        if pause.agent_id != P01_AGENT_ID:
            raise P01AdapterError(
                "next_pause_agent_mismatch",
                "Next P01 approval pause changed agent correlation.",
            )
        if not projector.resume_seen:
            raise P01AdapterError(
                "next_pause_before_resume",
                "Next P01 approval pause appeared before canonical RUN_RESUMED evidence.",
            )

    @staticmethod
    def _cancel_run_if_possible(run: ClawRun, summary: str) -> None:
        if run.terminal:
            return
        if run.status in {ClawRunStatus.WAITING_APPROVAL, ClawRunStatus.RUNNING}:
            try:
                run.transition(ClawRunStatus.CANCELLED, summary=summary)
            except RunStateError:
                pass

    @staticmethod
    def _fail_run_if_possible(run: ClawRun, summary: str) -> None:
        if run.terminal:
            return
        if run.status in {ClawRunStatus.WAITING_APPROVAL, ClawRunStatus.RUNNING}:
            try:
                run.transition(ClawRunStatus.FAILED, summary=summary)
            except RunStateError:
                pass


# Product policy is explicit: B54 accepts only a trusted canonical decision;
# it never infers approval from chat text, model output, or UI sentiment.
APPROVAL_FROM_CHAT_SENTIMENT_SUPPORTED = False
B54_MINTS_VERIFIED_APPROVAL_DECISION = False
