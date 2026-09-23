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
from padiem_ai_core.logical_execution_identity import agent_identity_payload
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)

from .contracts import (
    ClawRunStatus,
    ExecutionMode,
    RunProjection,
    SandboxLease,
    SandboxLeaseState,
)
from .p01_approval_pause_transport import (
    EngineApprovalPauseWire,
    P01PausedWireResult,
)
from .runs import ClawRun, RunStateError
from .security import redact_secrets


P01_APP_ID = "b54-padiem-claw"
P01_AGENT_ID = "b54-padiem-claw"
DEFAULT_P01_TIMEOUT_SECONDS = 20.0

P01_FAILURE_DETAIL_AUTHENTICATION = "engine_authentication_failed"
P01_FAILURE_DETAIL_AUTHORIZATION = "engine_authorization_failed"
P01_FAILURE_DETAIL_TRANSPORT = "engine_transport_or_response_failed"
P01_FAILURE_DETAIL_DOWNSTREAM = "engine_downstream_execution_failed"
P01_FAILURE_DETAIL_CONTRACT = "p01_contract_failure"
P01_FAILURE_DETAIL_UNKNOWN = "unknown_engine_failure"
P01_FAILURE_DETAILS = frozenset(
    {
        P01_FAILURE_DETAIL_AUTHENTICATION,
        P01_FAILURE_DETAIL_AUTHORIZATION,
        P01_FAILURE_DETAIL_TRANSPORT,
        P01_FAILURE_DETAIL_DOWNSTREAM,
        P01_FAILURE_DETAIL_CONTRACT,
        P01_FAILURE_DETAIL_UNKNOWN,
    }
)


class P01DispatchClass:
    """Authoritative dispatch classification for one P01 execution attempt (#2226).

    Canonical accounting policy (#830/#1230): a consumed B62 request-quota
    authorization may be compensated only when the failure is proven to have
    happened before any Engine/P01 transport attempt. ``DISPATCHED`` and
    ``UNKNOWN`` (ambiguous timeout/network, conservative default) are never
    refundable. Usage accounting stays in B62; this module only classifies
    where the execution chain failed.
    """

    NOT_DISPATCHED = "not_dispatched"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"


class P01AdapterError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        dispatch_class: str = P01DispatchClass.UNKNOWN,
        failure_detail: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.dispatch_class = dispatch_class
        self.failure_detail = (
            failure_detail
            if isinstance(failure_detail, str) and failure_detail in P01_FAILURE_DETAILS
            else None
        )


class P01ProjectionError(P01AdapterError):
    pass


class P01OrchestrationPort(Protocol):
    async def run(
        self, request: OrchestrationRequest
    ) -> OrchestrationResult | P01PausedWireResult: ...


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
    # #2946: Engine-issued opaque continuation reference when the run is
    # WAITING_APPROVAL; never minted, parsed, or stored by B54.
    continuation_ref: str | None = None
    # #2956: Engine-issued pause identity + server-derived trusted P01 request
    # snapshot for one owner-scoped durable handoff. None outside WAITING.
    pause_id: str | None = None
    pause_expires_at: str | None = None
    trusted_request: dict[str, object] | None = None

    def safe_dict(self) -> dict[str, object]:
        # pause_id / pause_expires_at / trusted_request stay server-side only;
        # the browser never receives resume authority or the trusted request.
        return {
            "projection": self.projection.safe_dict(),
            "answer": redact_secrets(self.answer) if self.answer is not None else None,
            "p01_run_id": self.p01_run_id,
            "p01_event_count": self.p01_event_count,
            "continuation_ref": self.continuation_ref,
        }


def _trace_id_for(run: ClawRun) -> str:
    if run.intent.trace_id is not None:
        return run.intent.trace_id
    digest = hashlib.sha256(run.run_id.encode("utf-8")).hexdigest()[:24]
    return f"claw_{digest}"


def _trusted_p01_request_snapshot(bundle: P01RequestBundle) -> dict[str, object]:
    """Server-derived trusted P01 request shape for one durable handoff (#2956).

    Mirrors the Engine ``execution_request_identity_payload`` closed shape so a
    later canonical Engine resume can reconstruct the original execution without
    the browser re-supplying authority fields. No credentials, tool arguments,
    provider tokens, or hidden reasoning are included.
    """
    execution_request = bundle.execution_request
    context = bundle.context
    return {
        "app_id": bundle.orchestration_request.app_id,
        "agent": agent_identity_payload(execution_request),
        "messages": [dict(message) for message in execution_request.messages],
        "session_id": execution_request.session_id,
        "additional_system_context": execution_request.additional_system_context,
        "trace_id": execution_request.trace_id,
        "execution_context": {
            "trace_id": context.trace_id,
            "idempotency_key": context.idempotency_key,
            "timeout_seconds": context.timeout_seconds,
        },
    }


def _agent_profile(product_tier: ProductTierLabel = ProductTierLabel.PLUS) -> AgentProfile:
    """Return the conservative B54 product profile consumed by P01.

    The model route is derived from the canonical Padiem v1 product-tier
    declaration (padiem_control_plane.product_tier_routes), shared with
    B62 Padiem Chat.  B14 remains provider/model execution authority.

    Plus → agnes-ai/agnes-3.0-flash
    Pro  → HOLD / fail-closed
    Max  → HOLD / fail-closed
    """
    try:
        route = active_route_for(product_tier)
    except ProductTierRoutesError as exc:
        raise P01AdapterError(
            "invalid_product_tier",
            f"제품 등급 라우트 계약이 무효합니다: {exc}",
            dispatch_class=P01DispatchClass.NOT_DISPATCHED,
        ) from exc

    if route is None or route.model_id is None:
        code = "max_tier_hold" if product_tier is ProductTierLabel.MAX else "tier_hold"
        raise P01AdapterError(
            code,
            f"{product_tier.value}은(는) 현재 실행 가능한 라우트가 없습니다 (HOLD).",
            dispatch_class=P01DispatchClass.NOT_DISPATCHED,
        )

    return AgentProfile(
        id=P01_AGENT_ID,
        title="Padiem Claw",
        description="B54 repository task execution consumer",
        system_instruction=None,
        # Core is the only authority for these two enums (see
        # padiem_ai_core.b14_execution.B14RoutingOptions). Values outside the
        # Core sets are rejected while the B14 routing options are built, i.e.
        # before any provider/model request is made.
        task_type="coding",
        optimize_for="balanced",
        max_tokens=None,
        allowed_tools=(),
        required_capabilities=(),
        context_policy={},
        model_policy={"model": route.model_id},
        max_steps=1,
        output_contract={},
    )


class P01RequestFactory:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_P01_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        product_tier: ProductTierLabel = ProductTierLabel.PLUS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise P01AdapterError(
                "invalid_timeout",
                "P01 timeout must be numeric.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
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
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            ) from None
        self._timeout_seconds = normalized_timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._product_tier = product_tier

    def build(
        self,
        run: ClawRun,
        *,
        lease: SandboxLease | None = None,
        product_tier: ProductTierLabel | None = None,
    ) -> P01RequestBundle:
        if run.terminal:
            raise P01AdapterError(
                "terminal_run",
                "Terminal Claw run cannot start P01 execution.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )

        if run.intent.execution_mode is ExecutionMode.CLOUD:
            self._validate_cloud_lease(run, lease)
            if run.status is not ClawRunStatus.PREPARING:
                raise P01AdapterError(
                    "cloud_run_not_prepared",
                    "Cloud Claw run must be in PREPARING after workspace allocation.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )
        else:
            if lease is not None:
                raise P01AdapterError(
                    "unexpected_cloud_lease",
                    "Local Claw run must not receive a cloud sandbox lease.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )
            if run.status is ClawRunStatus.QUEUED:
                run.transition(ClawRunStatus.PREPARING, summary="P01 실행 준비")
            elif run.status is not ClawRunStatus.PREPARING:
                raise P01AdapterError(
                    "local_run_not_preparable",
                    f"Local Claw run cannot prepare P01 from {run.status.value}.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )

        trace_id = _trace_id_for(run)
        execution_request = ExecutionRequest(
            agent=_agent_profile(product_tier or self._product_tier),
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
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if lease.run_id != run.run_id:
            raise P01AdapterError(
                "cloud_lease_run_mismatch",
                "Sandbox lease does not belong to this Claw run.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if lease.execution_mode is not ExecutionMode.CLOUD:
            raise P01AdapterError(
                "cloud_lease_mode_mismatch",
                "Sandbox lease is not a cloud execution lease.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if lease.state is not SandboxLeaseState.RESERVED:
            raise P01AdapterError(
                "cloud_lease_inactive",
                "Sandbox lease must be active before P01 handoff.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise P01AdapterError(
                "invalid_clock",
                "Sandbox lease validation clock must be timezone-aware.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if now.astimezone(timezone.utc) >= lease.expires_at:
            raise P01AdapterError(
                "cloud_lease_expired",
                "Sandbox lease expired before P01 handoff.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
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
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
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
        # consume() is only reached after the Engine returned a result, so every
        # projection failure here is post-dispatch and never refundable (#2226).
        if not isinstance(event, OrchestrationEvent):
            raise P01ProjectionError(
                "invalid_event",
                "Expected canonical P01 OrchestrationEvent.",
                dispatch_class=P01DispatchClass.DISPATCHED,
            )
        if event.trace_id != self._trace_id or event.app_id != self._app_id:
            raise P01ProjectionError(
                "event_correlation_mismatch",
                "P01 event does not match the Claw trace/app correlation.",
                dispatch_class=P01DispatchClass.DISPATCHED,
            )

        fingerprint = self._event_fingerprint(event)
        seen = self._seen_events.get(event.event_id)
        if seen is not None:
            if seen != fingerprint:
                raise P01ProjectionError(
                    "event_id_reuse_conflict",
                    "P01 event_id was reused with different lifecycle data.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                )
            return self._run.projection()

        if self._p01_run_id is None:
            if event.kind is not OrchestrationEventKind.RUN_STARTED or event.sequence != 1:
                raise P01ProjectionError(
                    "missing_run_started",
                    "First P01 event must be RUN_STARTED at sequence 1.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                )
            self._p01_run_id = event.run_id
        elif event.run_id != self._p01_run_id:
            raise P01ProjectionError(
                "p01_run_mismatch",
                "P01 event belongs to a different orchestration run.",
                dispatch_class=P01DispatchClass.DISPATCHED,
            )

        expected_sequence = self._last_sequence + 1
        if event.sequence != expected_sequence:
            raise P01ProjectionError(
                "event_sequence_gap",
                "P01 event sequence must be contiguous and monotonic.",
                dispatch_class=P01DispatchClass.DISPATCHED,
            )

        try:
            self._project_kind(event)
        except RunStateError:
            raise P01ProjectionError(
                "invalid_event_transition",
                "P01 event is incompatible with the current Claw lifecycle state.",
                dispatch_class=P01DispatchClass.DISPATCHED,
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
                dispatch_class=P01DispatchClass.DISPATCHED,
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
            raise P01AdapterError(
                "invalid_runner",
                "P01 runner must expose async run(request).",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        self._runner = runner
        self._factory = request_factory or P01RequestFactory()

    async def execute(
        self,
        run: ClawRun,
        *,
        lease: SandboxLease | None = None,
        product_tier: ProductTierLabel | None = None,
    ) -> ClawOrchestrationOutcome:
        try:
            bundle = self._factory.build(
                run,
                lease=lease,
                product_tier=product_tier,
            )
            projector = ClawOrchestrationProjector(
                run,
                trace_id=bundle.context.trace_id,
                app_id=bundle.orchestration_request.app_id,
            )
            port_result = await self._runner.run(bundle.orchestration_request)
            approval_pause_wire: EngineApprovalPauseWire | None = None
            if isinstance(port_result, P01PausedWireResult):
                approval_pause_wire = port_result.wire
                port_result = port_result.result
            result = port_result
            if not isinstance(result, OrchestrationResult):
                raise P01AdapterError(
                    "invalid_p01_result",
                    "P01 runner returned an invalid orchestration result.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                )
            self._validate_result_correlation(run, bundle, result)
            for event in result.events:
                projector.consume(event)

            if not run.terminal and run.status is not ClawRunStatus.WAITING_APPROVAL:
                raise P01AdapterError(
                    "incomplete_p01_lifecycle",
                    "P01 result ended without terminal or approval-paused lifecycle evidence.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                )
            if run.status is ClawRunStatus.WAITING_APPROVAL:
                if approval_pause_wire is None or not approval_pause_wire.continuation_ref:
                    # A paused Claw run without the Engine-issued continuation
                    # identity cannot be resumed truthfully; fail closed (#2946).
                    raise P01AdapterError(
                        "missing_continuation_ref",
                        "P01 approval pause arrived without an Engine-issued continuation reference.",
                        dispatch_class=P01DispatchClass.DISPATCHED,
                        failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                    )
                pause_id = approval_pause_wire.approval_pause.get("continuation_id")
                pause_expires_at = approval_pause_wire.approval_pause.get("expires_at")
                if not isinstance(pause_id, str) or not pause_id:
                    # #2956: a pause without its Engine-issued identity cannot
                    # form a durable owner-scoped handoff; fail closed.
                    raise P01AdapterError(
                        "missing_pause_id",
                        "P01 approval pause arrived without an Engine-issued pause identity.",
                        dispatch_class=P01DispatchClass.DISPATCHED,
                        failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                    )
                if not isinstance(pause_expires_at, str) or not pause_expires_at:
                    raise P01AdapterError(
                        "missing_pause_expires_at",
                        "P01 approval pause arrived without an Engine-issued expiry.",
                        dispatch_class=P01DispatchClass.DISPATCHED,
                        failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                    )
            elif approval_pause_wire is not None:
                raise P01AdapterError(
                    "continuation_without_pause",
                    "P01 returned Engine continuation identity without WAITING_APPROVAL lifecycle state.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                    failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                )

            answer = (
                redact_secrets(result.execution_result.answer)
                if run.status is ClawRunStatus.COMPLETED
                else None
            )
            if run.status is ClawRunStatus.WAITING_APPROVAL:
                assert approval_pause_wire is not None
                return ClawOrchestrationOutcome(
                    projection=run.projection(),
                    answer=answer,
                    p01_run_id=projector.p01_run_id,
                    p01_event_count=projector.event_count,
                    continuation_ref=approval_pause_wire.continuation_ref,
                    pause_id=str(approval_pause_wire.approval_pause.get("continuation_id")),
                    pause_expires_at=str(approval_pause_wire.approval_pause.get("expires_at")),
                    trusted_request=_trusted_p01_request_snapshot(bundle),
                )
            return ClawOrchestrationOutcome(
                projection=run.projection(),
                answer=answer,
                p01_run_id=projector.p01_run_id,
                p01_event_count=projector.event_count,
                continuation_ref=None,
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
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from None
        except Exception:
            self._fail_run_if_possible(run)
            raise P01AdapterError(
                "p01_execution_failed",
                "P01 orchestration failed without a safe product result.",
                failure_detail=P01_FAILURE_DETAIL_UNKNOWN,
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
                dispatch_class=P01DispatchClass.DISPATCHED,
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
