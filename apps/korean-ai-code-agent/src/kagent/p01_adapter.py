from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Protocol

from padiem_ai_core import (
    AgentProfile,
    ExecutionContext,
    ExecutionRequest,
    OrchestrationEvent,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationResult,
)

from .contracts import (
    ClawRunStatus,
    ExecutionMode,
    RunProjection,
    SandboxLease,
    SandboxLeaseState,
)
from .runs import ClawRun, RunStateError
from .security import redact_secrets


P01_APP_ID = "b54-padiem-claw"
P01_AGENT_ID = "b54-padiem-claw"
DEFAULT_P01_TIMEOUT_SECONDS = 20.0


class P01AdapterError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class P01ProjectionError(P01AdapterError):
    pass


class P01OrchestrationPort(Protocol):
    async def run(self, request: OrchestrationRequest) -> OrchestrationResult: ...


@dataclass(frozen=True, slots=True)
class P01RequestBundle:
    execution_request: ExecutionRequest
    context: ExecutionContext
    orchestration_request: OrchestrationRequest


@dataclass(frozen=True, slots=True)
class ClawOrchestrationOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str | None
    p01_event_count: int

    def safe_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection.safe_dict(),
            "answer": redact_secrets(self.answer) if self.answer is not None else None,
            "p01_run_id": self.p01_run_id,
            "p01_event_count": self.p01_event_count,
        }


def _trace_id_for(run: ClawRun) -> str:
    if run.intent.trace_id is not None:
        return run.intent.trace_id
    digest = hashlib.sha256(run.run_id.encode("utf-8")).hexdigest()[:24]
    return f"claw_{digest}"


def _agent_profile() -> AgentProfile:
    """Return the conservative B54 product profile consumed by P01.

    The profile intentionally leaves model policy empty so the existing Core/B14
    defaults remain authoritative. Product/client task input cannot pin a
    Provider, model, fallback order, or credential through this adapter.
    """

    return AgentProfile(
        id=P01_AGENT_ID,
        title="Padiem Claw",
        description="B54 repository task execution consumer",
        system_instruction=None,
        task_type="code",
        optimize_for="quality",
        max_tokens=None,
        allowed_tools=(),
        required_capabilities=(),
        context_policy={},
        model_policy={},
        max_steps=1,
        output_contract={},
    )


class P01RequestFactory:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_P01_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise P01AdapterError("invalid_timeout", "P01 timeout must be numeric.")
        normalized_timeout = float(timeout_seconds)
        # Validate against the canonical public P01 contract instead of importing
        # private/internal timeout constants. This makes Core the single authority
        # for the accepted execution budget.
        try:
            ExecutionContext(
                trace_id="claw_timeout_contract_probe",
                timeout_seconds=normalized_timeout,
            )
        except ValueError:
            raise P01AdapterError(
                "invalid_timeout",
                "P01 timeout is outside the canonical Core execution-context bounds.",
            ) from None
        self._timeout_seconds = normalized_timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build(self, run: ClawRun, *, lease: SandboxLease | None = None) -> P01RequestBundle:
        if run.terminal:
            raise P01AdapterError("terminal_run", "Terminal Claw run cannot start P01 execution.")

        if run.intent.execution_mode is ExecutionMode.CLOUD:
            self._validate_cloud_lease(run, lease)
            if run.status is not ClawRunStatus.PREPARING:
                raise P01AdapterError(
                    "cloud_run_not_prepared",
                    "Cloud Claw run must be in PREPARING after workspace allocation.",
                )
        else:
            if lease is not None:
                raise P01AdapterError(
                    "unexpected_cloud_lease",
                    "Local Claw run must not receive a cloud sandbox lease.",
                )
            if run.status is ClawRunStatus.QUEUED:
                run.transition(ClawRunStatus.PREPARING, summary="P01 실행 준비")
            elif run.status is not ClawRunStatus.PREPARING:
                raise P01AdapterError(
                    "local_run_not_preparable",
                    f"Local Claw run cannot prepare P01 from {run.status.value}.",
                )

        trace_id = _trace_id_for(run)
        execution_request = ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": run.intent.task},),
            session_id=run.run_id,
            additional_system_context=None,
            trace_id=trace_id,
        )
        context = ExecutionContext(
            trace_id=trace_id,
            idempotency_key=None,
            timeout_seconds=self._timeout_seconds,
        )
        orchestration_request = OrchestrationRequest(
            execution_request=execution_request,
            context=context,
            app_id=P01_APP_ID,
            subject_id=None,
        )
        return P01RequestBundle(
            execution_request=execution_request,
            context=context,
            orchestration_request=orchestration_request,
        )

    def _validate_cloud_lease(self, run: ClawRun, lease: SandboxLease | None) -> None:
        if lease is None:
            raise P01AdapterError(
                "cloud_lease_required",
                "Cloud Claw run requires an active sandbox lease before P01 handoff.",
            )
        if lease.run_id != run.run_id:
            raise P01AdapterError(
                "cloud_lease_run_mismatch",
                "Sandbox lease does not belong to this Claw run.",
            )
        if lease.execution_mode is not ExecutionMode.CLOUD:
            raise P01AdapterError(
                "cloud_lease_mode_mismatch",
                "Sandbox lease is not a cloud execution lease.",
            )
        if lease.state is not SandboxLeaseState.RESERVED:
            raise P01AdapterError(
                "cloud_lease_inactive",
                "Sandbox lease must be active before P01 handoff.",
            )
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise P01AdapterError(
                "invalid_clock",
                "Sandbox lease validation clock must be timezone-aware.",
            )
        if now.astimezone(timezone.utc) >= lease.expires_at:
            raise P01AdapterError(
                "cloud_lease_expired",
                "Sandbox lease expired before P01 handoff.",
            )


class ClawOrchestrationProjector:
    """Project canonical P01 events into B54 product lifecycle state.

    P01 event semantics stay authoritative. B54 only projects a small set of
    user-visible states and rejects mismatched, out-of-order, or resurrecting
    events.
    """

    def __init__(self, run: ClawRun, *, trace_id: str, app_id: str = P01_APP_ID) -> None:
        if run.status is not ClawRunStatus.PREPARING:
            raise P01ProjectionError(
                "run_not_preparing",
                "Claw run must be PREPARING before P01 event projection.",
            )
        self._run = run
        self._trace_id = trace_id
        self._app_id = app_id
        self._p01_run_id: str | None = None
        self._last_sequence = 0
        self._seen_events: dict[str, tuple[object, ...]] = {}

    @property
    def p01_run_id(self) -> str | None:
        return self._p01_run_id

    @property
    def event_count(self) -> int:
        return len(self._seen_events)

    def consume(self, event: OrchestrationEvent) -> RunProjection:
        if not isinstance(event, OrchestrationEvent):
            raise P01ProjectionError("invalid_event", "Expected canonical P01 OrchestrationEvent.")
        if event.trace_id != self._trace_id or event.app_id != self._app_id:
            raise P01ProjectionError(
                "event_correlation_mismatch",
                "P01 event does not match the Claw trace/app correlation.",
            )

        fingerprint = self._event_fingerprint(event)
        seen = self._seen_events.get(event.event_id)
        if seen is not None:
            if seen != fingerprint:
                raise P01ProjectionError(
                    "event_id_reuse_conflict",
                    "P01 event_id was reused with different lifecycle data.",
                )
            return self._run.projection()

        if self._p01_run_id is None:
            if event.kind is not OrchestrationEventKind.RUN_STARTED or event.sequence != 1:
                raise P01ProjectionError(
                    "missing_run_started",
                    "First P01 event must be RUN_STARTED at sequence 1.",
                )
            self._p01_run_id = event.run_id
        elif event.run_id != self._p01_run_id:
            raise P01ProjectionError(
                "p01_run_mismatch",
                "P01 event belongs to a different orchestration run.",
            )

        expected_sequence = self._last_sequence + 1
        if event.sequence != expected_sequence:
            raise P01ProjectionError(
                "event_sequence_gap",
                "P01 event sequence must be contiguous and monotonic.",
            )

        try:
            self._project_kind(event)
        except RunStateError:
            raise P01ProjectionError(
                "invalid_event_transition",
                "P01 event is incompatible with the current Claw lifecycle state.",
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
                "Late P01 event cannot resurrect or mutate a terminal Claw run.",
            )

        if kind is OrchestrationEventKind.RUN_STARTED:
            self._run.transition(ClawRunStatus.RUNNING, summary="P01 실행 시작")
        elif kind is OrchestrationEventKind.APPROVAL_PAUSED:
            self._run.transition(
                ClawRunStatus.WAITING_APPROVAL,
                summary=redact_secrets(event.message or "사용자 승인 대기"),
            )
        elif kind is OrchestrationEventKind.RUN_RESUMED:
            self._run.transition(
                ClawRunStatus.RUNNING,
                summary=redact_secrets(event.message or "승인 후 실행 재개"),
            )
        elif kind is OrchestrationEventKind.RUN_COMPLETED:
            self._run.transition(
                ClawRunStatus.COMPLETED,
                summary=redact_secrets(event.message or "작업 완료"),
            )
        elif kind is OrchestrationEventKind.RUN_FAILED:
            self._run.transition(
                ClawRunStatus.FAILED,
                summary=redact_secrets(event.message or "P01 실행 실패"),
            )
        elif kind is OrchestrationEventKind.RUN_CANCELLED:
            self._run.transition(
                ClawRunStatus.CANCELLED,
                summary=redact_secrets(event.message or "작업 취소"),
            )


class P01CoreOrchestrationAdapter:
    def __init__(
        self,
        runner: P01OrchestrationPort,
        *,
        request_factory: P01RequestFactory | None = None,
    ) -> None:
        run_method = getattr(runner, "run", None)
        if not callable(run_method):
            raise P01AdapterError("invalid_runner", "P01 runner must expose async run(request).")
        self._runner = runner
        self._factory = request_factory or P01RequestFactory()

    async def execute(
        self,
        run: ClawRun,
        *,
        lease: SandboxLease | None = None,
    ) -> ClawOrchestrationOutcome:
        try:
            bundle = self._factory.build(run, lease=lease)
            projector = ClawOrchestrationProjector(
                run,
                trace_id=bundle.context.trace_id,
                app_id=bundle.orchestration_request.app_id,
            )
            result = await self._runner.run(bundle.orchestration_request)
            if not isinstance(result, OrchestrationResult):
                raise P01AdapterError(
                    "invalid_p01_result",
                    "P01 runner returned an invalid orchestration result.",
                )
            self._validate_result_correlation(run, bundle, result)
            for event in result.events:
                projector.consume(event)

            if not run.terminal and run.status is not ClawRunStatus.WAITING_APPROVAL:
                raise P01AdapterError(
                    "incomplete_p01_lifecycle",
                    "P01 result ended without terminal or approval-paused lifecycle evidence.",
                )

            answer = (
                redact_secrets(result.execution_result.answer)
                if run.status is ClawRunStatus.COMPLETED
                else None
            )
            return ClawOrchestrationOutcome(
                projection=run.projection(),
                answer=answer,
                p01_run_id=projector.p01_run_id,
                p01_event_count=projector.event_count,
            )
        except asyncio.CancelledError:
            self._cancel_run_if_possible(run)
            raise
        except P01AdapterError:
            self._fail_run_if_possible(run)
            raise
        except (RunStateError, ValueError):
            self._fail_run_if_possible(run)
            raise P01AdapterError(
                "p01_contract_failure",
                "P01 orchestration contract could not be safely projected.",
            ) from None
        except Exception:
            self._fail_run_if_possible(run)
            raise P01AdapterError(
                "p01_execution_failed",
                "P01 orchestration failed without a safe product result.",
            ) from None

    @staticmethod
    def _validate_result_correlation(
        run: ClawRun,
        bundle: P01RequestBundle,
        result: OrchestrationResult,
    ) -> None:
        expected_trace = bundle.context.trace_id
        expected_app = bundle.orchestration_request.app_id
        metadata = result.execution_result.metadata
        if (
            result.context.trace_id != expected_trace
            or result.app_id != expected_app
            or metadata.trace_id != expected_trace
            or metadata.app_id != expected_app
            or metadata.agent_id != P01_AGENT_ID
            or metadata.session_id != run.run_id
        ):
            raise P01AdapterError(
                "p01_result_correlation_mismatch",
                "P01 result does not match the trusted Claw run correlation.",
            )

    @staticmethod
    def _cancel_run_if_possible(run: ClawRun) -> None:
        if run.terminal:
            return
        if run.status in {
            ClawRunStatus.QUEUED,
            ClawRunStatus.PREPARING,
            ClawRunStatus.RUNNING,
            ClawRunStatus.WAITING_APPROVAL,
        }:
            try:
                run.transition(
                    ClawRunStatus.CANCELLED,
                    summary="P01 실행이 취소되었습니다.",
                )
            except RunStateError:
                pass

    @staticmethod
    def _fail_run_if_possible(run: ClawRun) -> None:
        if run.terminal:
            return
        if run.status in {
            ClawRunStatus.QUEUED,
            ClawRunStatus.PREPARING,
            ClawRunStatus.RUNNING,
            ClawRunStatus.WAITING_APPROVAL,
        }:
            try:
                run.transition(
                    ClawRunStatus.FAILED,
                    summary="P01 실행을 안전하게 완료하지 못했습니다.",
                )
            except RunStateError:
                pass
