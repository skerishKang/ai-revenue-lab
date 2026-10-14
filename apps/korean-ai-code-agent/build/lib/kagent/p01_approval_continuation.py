"""#2961: B54 consumption of an owner approve/deny through canonical continuation.

The Engine remains the sole approval-continuation authority. This module never
verifies an approval decision, never mints ``VerifiedApprovalDecision``,
``ApprovalPause``, ``continuation_ref`` or ``ToolAuthorizationContext``, and
never opens a second continuation store, resume protocol, or approval state
machine. It only:

* fail-closes the #2956 persisted trusted P01 request snapshot and replays it as
  the canonical Engine resume execution identity;
* assembles one bounded server-derived first-party decision *submission* (the
  wire shape the Engine verifier consumes) from the stored Engine pause identity
  and the authenticated session authority;
* submits it through the existing Engine-owned first-party resume transport;
* reconstructs the response with the existing Core public parser and projects it
  through the existing ``ClawResumeProjector``.

Product policy inherited from #2946/#2956: browser input is limited to
``run_id`` + ``decision``. Every authority field is server-derived.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from padiem_ai_core import (
    OrchestrationError,
    OrchestrationResult,
    orchestration_result_from_public,
)
from padiem_ai_engine_client import PadiemAiEngineClientError

from .contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode, RunProjection
from .p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    P01AdapterError,
    P01DispatchClass,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_TRANSPORT,
)
from .p01_approval_pause_transport import (
    EngineApprovalPauseWire,
    EngineApprovalPauseWireError,
    split_engine_approval_pause_wire,
)
from .p01_orchestration_client import PADIEM_EXECUTABLE_MODEL_IDS
from .p01_resume import ClawResumeProjector
from .runs import ClawRun, RunStateError
from .security import redact_secrets

APPROVAL_DECISION_APPROVE = "approve"
APPROVAL_DECISION_DENY = "deny"
OWNER_APPROVAL_DECISIONS = frozenset({APPROVAL_DECISION_APPROVE, APPROVAL_DECISION_DENY})

# The Engine wire outcome vocabulary (``ApprovalOutcome`` values). B54 maps one
# owner decision onto exactly one of these and never infers approval otherwise.
_OUTCOME_BY_DECISION = {
    APPROVAL_DECISION_APPROVE: "approved",
    APPROVAL_DECISION_DENY: "denied",
}

# Canonical denial: the Engine verifier accepted ``outcome="denied"`` and Core
# consumed the continuation, so this is proven terminal consumption rather than
# a transport failure.
ENGINE_APPROVAL_DENIED_CODE = "approval_denied"

# The Engine rejected this submission without consuming the stored
# continuation, so the owner may decide again.
RETRY_SAFE_RESUME_CODES = frozenset(
    {"invalid_decision", "continuation_identity_mismatch", "invalid_verified_decision"}
)

_TRUSTED_SNAPSHOT_KEYS = frozenset(
    {
        "app_id",
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
)
# ``agent_identity_payload`` closed shape: exactly what #2956 persisted.
_TRUSTED_AGENT_KEYS = frozenset(
    {
        "id",
        "title",
        "description",
        "system_instruction",
        "task_type",
        "optimize_for",
        "max_tokens",
        "allowed_tools",
        "required_capabilities",
        "context_policy",
        "model_policy",
        "max_steps",
        "output_contract",
    }
)
# The Engine execution-request agent wire carries a subset of the identity
# payload; the remaining fields are validated as inert and never silently
# dropped.
_WIRE_AGENT_KEYS = _TRUSTED_AGENT_KEYS - {
    "allowed_tools",
    "context_policy",
    "max_steps",
    "output_contract",
}
_TRUSTED_EXECUTION_CONTEXT_KEYS = frozenset({"trace_id", "idempotency_key", "timeout_seconds"})
_MESSAGE_KEYS = frozenset({"role", "content"})
_ENGINE_CONTINUATION_REF_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_B54_AUTHORITY_SCHEME = "b54_session:"

# Product policy inherited from #2946/#2956 and stated as an explicit module
# fact so a later child cannot quietly move decision assembly into B54: the
# Engine verifier is the only producer of a verified approval decision, and
# tool authorization is never constructed on this lane.
B54_CONSTRUCTS_VERIFIED_APPROVAL_DECISION = False
B54_CONSTRUCTS_TOOL_AUTHORIZATION_CONTEXT = False


def _wire_pause_field(wire: EngineApprovalPauseWire | None, name: str) -> str | None:
    """Read one bounded Engine-issued pause field, or ``None`` when absent."""
    if wire is None:
        return None
    value = wire.approval_pause.get(name)
    return value if isinstance(value, str) and value else None


class P01ApprovalDeniedError(P01AdapterError):
    """Canonical denial accepted by the Engine: the pause is terminal, consumed."""


@dataclass(frozen=True, slots=True)
class TrustedResumeRequest:
    """One validated #2956 snapshot replayed as canonical resume authority.

    ``payload`` is the Engine resume execution-identity body; ``snapshot`` is the
    unchanged trusted request re-persisted when the Engine pauses again, so a
    second approval generation never requires browser-supplied authority.
    """

    payload: Mapping[str, Any]
    snapshot: Mapping[str, Any]
    trace_id: str
    p01_run_id: str | None


@dataclass(frozen=True, slots=True)
class ContinuationResumeResult:
    """Core result plus the Engine-issued pause wire, kept out of the result."""

    result: OrchestrationResult
    pause_wire: EngineApprovalPauseWire | None = None


def _fail(code: str, message: str) -> P01AdapterError:
    return P01AdapterError(
        code,
        message,
        dispatch_class=P01DispatchClass.NOT_DISPATCHED,
        failure_detail=P01_FAILURE_DETAIL_CONTRACT,
    )


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def decision_outcome(decision: object) -> str:
    """Map one owner decision to the canonical Engine outcome, fail closed."""
    if isinstance(decision, str) and decision in _OUTCOME_BY_DECISION:
        return _OUTCOME_BY_DECISION[decision]
    raise _fail(
        "invalid_approval_decision",
        "승인 결정은 approve 또는 deny만 허용됩니다.",
    )


def build_first_party_decision_submission(
    *,
    pause_id: object,
    decision: object,
    owner_id: object,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Assemble one bounded first-party decision submission for the Engine verifier.

    ``pause_id`` comes only from the stored Engine handoff, the outcome only from
    the approve/deny pair, and the authority/evidence references are derived
    from the authenticated owner session. This is the Engine's *submission* wire
    shape; the Engine verifier stays the only producer of
    ``VerifiedApprovalDecision``.
    """
    outcome = decision_outcome(decision)
    if not isinstance(pause_id, str) or not _SAFE_ID_RE.fullmatch(pause_id):
        raise _fail("handoff_pause_id_invalid", "저장된 Engine 승인 구별자를 확인할 수 없습니다.")
    if not isinstance(owner_id, str) or not _SAFE_ID_RE.fullmatch(owner_id):
        raise _fail("approval_owner_unavailable", "승인 권한을 확인할 수 없습니다.")
    correlation = hashlib.sha256(
        f"{owner_id}|{pause_id}|{outcome}".encode("utf-8")
    ).hexdigest()[:32]
    decision_id = f"decision_b54_{correlation}"
    return {
        "decision_id": decision_id,
        "pause_id": pause_id,
        "outcome": outcome,
        "authority_ref": f"{_B54_AUTHORITY_SCHEME}{owner_id}",
        "evidence_ref": f"b54_decision:{decision_id}",
        "decided_at": _iso_z(now() if now is not None else datetime.now(timezone.utc)),
    }


def _submission_decision(outcome: object) -> str:
    """Read back one already-mapped wire outcome, fail closed."""
    if outcome in _OUTCOME_BY_DECISION.values():
        return "approved" if outcome == "approved" else "denied"
    raise _fail("invalid_approval_decision", "승인 결정이 올바르지 않습니다.")


def _require_text(value: Any, code: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(code, f"승인 컨텍스트의 {name} 값을 복원할 수 없습니다.")
    return value


def reconstruct_trusted_resume_request(
    *,
    trusted_request: object,
    run_id: object,
    p01_run_id: object = None,
) -> TrustedResumeRequest:
    """Rebuild the canonical resume execution identity from the #2956 snapshot.

    Every check below fails closed before any Engine transport is touched:
    unknown key, invalid agent shape, unsupported model or tool authority,
    trace/context trace mismatch, wrong app identity, and session/run
    correlation mismatch. No browser field is merged into the reconstruction.
    """
    if not isinstance(trusted_request, Mapping):
        raise _fail("handoff_snapshot_invalid", "승인 컨텍스트를 복원할 수 없습니다.")
    if set(trusted_request) - _TRUSTED_SNAPSHOT_KEYS:
        raise _fail(
            "handoff_snapshot_unknown_key",
            "승인 컨텍스트에 허용되지 않는 권한 필드가 있습니다.",
        )
    missing = _TRUSTED_SNAPSHOT_KEYS - set(trusted_request)
    if missing:
        raise _fail(
            "handoff_snapshot_incomplete",
            f"승인 컨텍스트의 {sorted(missing)[0]} 정보가 없습니다.",
        )

    if trusted_request["app_id"] != P01_APP_ID:
        raise _fail("handoff_app_mismatch", "승인 컨텍스트의 앱 신원이 일치하지 않습니다.")
    if not isinstance(run_id, str) or not run_id:
        raise _fail("handoff_run_id_invalid", "Claw run 식별자를 확인할 수 없습니다.")
    if trusted_request["session_id"] != run_id:
        raise _fail("handoff_session_mismatch", "승인 컨텍스트가 이 Claw run의 것이 아닙니다.")

    trace_id = _require_text(
        trusted_request["trace_id"], "handoff_trace_invalid", "trace"
    )
    if not _SAFE_ID_RE.fullmatch(trace_id):
        raise _fail("handoff_trace_invalid", "승인 컨텍스트의 trace 식별자가 무효합니다.")

    context = trusted_request["execution_context"]
    if not isinstance(context, Mapping) or set(context) - _TRUSTED_EXECUTION_CONTEXT_KEYS:
        raise _fail("handoff_execution_context_invalid", "승인 컨텍스트의 실행 환경이 무효합니다.")
    for name in sorted(_TRUSTED_EXECUTION_CONTEXT_KEYS):
        if name not in context:
            raise _fail(
                "handoff_execution_context_incomplete",
                f"승인 컨텍스트의 실행 환경 {name} 정보가 없습니다.",
            )
    if context["trace_id"] != trace_id:
        raise _fail(
            "handoff_context_trace_mismatch",
            "승인 컨텍스트의 trace 상관이 일치하지 않습니다.",
        )
    if context["idempotency_key"] is not None:
        raise _fail(
            "handoff_authority_pinning",
            "승인 컨텍스트가 Engine wire가 허용하지 않는 재시도 제어 권한을 담고 있습니다.",
        )
    timeout_seconds = context["timeout_seconds"]
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise _fail("handoff_execution_context_invalid", "승인 컨텍스트의 실행 시간 정보가 무효합니다.")

    agent = trusted_request["agent"]
    if not isinstance(agent, Mapping) or set(agent) - _TRUSTED_AGENT_KEYS:
        raise _fail("handoff_agent_shape_invalid", "승인 컨텍스트의 agent 정보가 무효합니다.")
    agent_missing = _TRUSTED_AGENT_KEYS - set(agent)
    if agent_missing:
        raise _fail(
            "handoff_agent_shape_incomplete",
            f"승인 컨텍스트의 agent {sorted(agent_missing)[0]} 정보가 없습니다.",
        )
    if agent["id"] != P01_AGENT_ID:
        raise _fail("handoff_agent_mismatch", "승인 컨텍스트의 agent 신원이 일치하지 않습니다.")
    model_policy = agent["model_policy"]
    if not isinstance(model_policy, Mapping):
        raise _fail("handoff_agent_shape_invalid", "승인 컨텍스트의 model 정책이 무효합니다.")
    route_is_pinned = bool(model_policy) and (
        set(model_policy) != {"model"} or model_policy["model"] not in PADIEM_EXECUTABLE_MODEL_IDS
    )
    if (
        route_is_pinned
        or agent["allowed_tools"]
        or agent["context_policy"]
        or agent["output_contract"]
        or agent["max_steps"] != 1
    ):
        raise _fail(
            "handoff_authority_pinning",
            "승인 컨텍스트가 Engine wire가 허용하지 않는 라우팅 또는 도구 권한을 담고 있습니다.",
        )

    raw_messages = trusted_request["messages"]
    if not isinstance(raw_messages, (list, tuple)) or not raw_messages:
        raise _fail("handoff_messages_invalid", "승인 컨텍스트의 작업 내용을 복원할 수 없습니다.")
    messages: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, Mapping) or set(item) != _MESSAGE_KEYS:
            raise _fail("handoff_messages_invalid", "승인 컨텍스트의 작업 내용 형식이 무효합니다.")
        if not isinstance(item["role"], str) or not _SAFE_ID_RE.fullmatch(item["role"]):
            raise _fail("handoff_messages_invalid", "승인 컨텍스트의 작업 발화자를 복원할 수 없습니다.")
        messages.append({"role": item["role"], "content": _require_text(
            item["content"], "handoff_messages_invalid", "작업 내용"
        )})

    payload: dict[str, Any] = {
        "agent": {name: agent[name] for name in sorted(_WIRE_AGENT_KEYS)},
        "messages": messages,
        "trace_id": trace_id,
        "execution_context": {
            "trace_id": trace_id,
            "timeout_seconds": float(timeout_seconds),
        },
        "session_id": run_id,
    }
    if trusted_request["additional_system_context"] is not None:
        payload["additional_system_context"] = _require_text(
            trusted_request["additional_system_context"],
            "handoff_context_invalid",
            "additional_system_context",
        )

    normalized_run_id = p01_run_id if isinstance(p01_run_id, str) and p01_run_id else None
    return TrustedResumeRequest(
        payload=payload,
        snapshot=dict(trusted_request),
        trace_id=trace_id,
        p01_run_id=normalized_run_id,
    )


class P01EngineApprovalContinuationClient:
    """The existing Engine resume transport, consumed as one bounded decision lane.

    The Engine verifier, continuation store, claim/commit lifecycle, and P01
    resume runner all remain behind ``resume_orchestration``. This class adds no
    protocol: it maps the reconstructed identity plus one submission onto the
    canonical resume route and reconstructs the response through the existing
    Core public parser.
    """

    def __init__(self, client: Any) -> None:
        if not callable(getattr(client, "resume_orchestration", None)):
            raise _fail(
                "invalid_engine_client",
                "Engine continuation 클라이언트가 resume transport를 노출하지 않습니다.",
            )
        client_app_id = getattr(client, "app_id", None)
        if client_app_id is not None and client_app_id != P01_APP_ID:
            raise _fail(
                "continuation_app_id_mismatch",
                "Engine 클라이언트 앱 신원이 B54 continuation과 일치하지 않습니다.",
            )
        self._client = client

    async def resume(
        self,
        *,
        continuation_ref: str,
        request: TrustedResumeRequest,
        submission: Mapping[str, Any],
    ) -> ContinuationResumeResult:
        payload = dict(request.payload)
        payload["continuation_ref"] = continuation_ref
        payload["decision"] = dict(submission)
        try:
            raw = await self._client.resume_orchestration(payload)
        except PadiemAiEngineClientError as exc:
            if exc.code == ENGINE_APPROVAL_DENIED_CODE:
                raise P01ApprovalDeniedError(
                    ENGINE_APPROVAL_DENIED_CODE,
                    "P01 승인이 거절되어 continuation이 Engine에서 소비되었습니다.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                ) from exc
            if exc.code in RETRY_SAFE_RESUME_CODES:
                raise P01AdapterError(
                    exc.code,
                    "P01이 해당 승인 결정을 거부했습니다. 결정을 다시 시도할 수 있습니다.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                ) from exc
            raise P01AdapterError(
                "p01_continuation_request_failed",
                "P01 승인 continuation이 Engine 경계에서 실패했습니다.",
                dispatch_class=P01DispatchClass.UNKNOWN,
                failure_detail=P01_FAILURE_DETAIL_TRANSPORT,
            ) from exc
        try:
            core_payload, pause_wire = split_engine_approval_pause_wire(raw)
        except EngineApprovalPauseWireError as exc:
            raise P01AdapterError(
                exc.code,
                "P01 continuation 응답의 승인 pause wire를 사용할 수 없습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from exc
        try:
            result = orchestration_result_from_public(core_payload)
        except OrchestrationError as exc:
            raise P01AdapterError(
                exc.code,
                "P01 continuation 응답을 canonical result로 복원할 수 없습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from exc
        self._validate_correlation(request, result)
        return ContinuationResumeResult(result=result, pause_wire=pause_wire)

    @staticmethod
    def _validate_correlation(request: TrustedResumeRequest, result: OrchestrationResult) -> None:
        metadata = result.execution_result.metadata
        if (
            result.app_id != P01_APP_ID
            or result.context.trace_id != request.trace_id
            or metadata.trace_id != request.trace_id
            or metadata.app_id != P01_APP_ID
            or metadata.agent_id != P01_AGENT_ID
        ):
            raise P01AdapterError(
                "p01_continuation_result_correlation_mismatch",
                "P01 continuation 결과가 trusted correlation과 일치하지 않습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )


@dataclass(frozen=True, slots=True)
class ClawApprovalContinuationOutcome:
    """Bounded product outcome of one consumed owner decision (#2961)."""

    projection: RunProjection
    answer: str | None
    decision: str
    decision_id: str
    p01_run_id: str
    p01_event_count: int
    # Present only when the Engine paused again: a fresh Engine-issued identity,
    # never a reuse of the decided one.
    next_continuation_ref: str | None = None
    next_pause_id: str | None = None
    next_pause_expires_at: str | None = None
    next_p01_run_id: str | None = None
    next_trusted_request: Mapping[str, Any] | None = None

    def safe_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection.safe_dict(),
            "answer": redact_secrets(self.answer) if self.answer is not None else None,
            "decision": self.decision,
            "p01_run_id": self.p01_run_id,
            "p01_event_count": self.p01_event_count,
            "continuation_ref": self.next_continuation_ref,
        }


def _rehydrate_waiting_run(*, run_id: str, request: TrustedResumeRequest) -> ClawRun:
    """Rebuild the B54 lifecycle container at WAITING_APPROVAL for one decision.

    Every value comes from the server-derived snapshot, and the container is
    validated through the same projection contract the original run passed.
    """
    task = str(list(request.payload["messages"])[-1]["content"])
    suffix = run_id[4:] if run_id.startswith("run_") else run_id
    intent = ClawTaskIntent(
        task_id=f"task_{suffix}",
        task=task,
        repository_ref="padiem-chat",
        execution_mode=ExecutionMode.LOCAL,
        source_surface="padiem-chat",
        trace_id=request.trace_id,
    )
    RunProjection(
        run_id=run_id,
        task_id=intent.task_id,
        status=ClawRunStatus.WAITING_APPROVAL,
        execution_mode=intent.execution_mode,
    )
    return ClawRun(
        run_id=run_id,
        intent=intent,
        status=ClawRunStatus.WAITING_APPROVAL,
        summary="승인 대기",
    )


class P01ApprovalContinuationService:
    """Consume one owner approve/deny through the existing canonical lane.

    ``ClawResumeProjector`` is reused unchanged, so B54 adds no approval state
    machine: WAITING_APPROVAL returns to RUNNING only on canonical RUN_RESUMED
    evidence, a further Engine pause returns to WAITING_APPROVAL, and a
    canonical denial is projected as CANCELLED.
    """

    def __init__(self, continuation: P01EngineApprovalContinuationClient) -> None:
        if not callable(getattr(continuation, "resume", None)):
            raise _fail(
                "invalid_continuation_client",
                "P01 continuation 클라이언트가 resume(...)를 노출하지 않습니다.",
            )
        self._continuation = continuation

    async def decide(
        self,
        *,
        run_id: str,
        continuation_ref: str,
        request: TrustedResumeRequest,
        submission: Mapping[str, Any],
    ) -> ClawApprovalContinuationOutcome:
        if not isinstance(continuation_ref, str) or not _ENGINE_CONTINUATION_REF_RE.fullmatch(
            continuation_ref
        ):
            raise _fail(
                "handoff_continuation_ref_invalid",
                "Engine 연속 실행 식별자를 복원할 수 없습니다.",
            )
        if request.p01_run_id is None:
            raise _fail(
                "handoff_p01_run_id_missing",
                "Engine 실행 식별자 없이 승인을 소비할 수 없습니다.",
            )
        decision = _submission_decision(submission.get("outcome"))
        run = _rehydrate_waiting_run(run_id=run_id, request=request)
        projector = ClawResumeProjector(
            run,
            trace_id=request.trace_id,
            p01_run_id=request.p01_run_id,
            app_id=P01_APP_ID,
        )
        base = {
            "decision": decision,
            "decision_id": str(submission.get("decision_id") or ""),
            "p01_run_id": request.p01_run_id,
        }

        try:
            resumed = await self._continuation.resume(
                continuation_ref=continuation_ref, request=request, submission=submission
            )
        except asyncio.CancelledError:
            self._transition_if_possible(
                run, ClawRunStatus.CANCELLED, "P01 승인 처리가 취소되었습니다."
            )
            raise
        except P01ApprovalDeniedError:
            self._transition_if_possible(
                run, ClawRunStatus.CANCELLED, "사용자가 승인을 거절했습니다."
            )
            return ClawApprovalContinuationOutcome(
                projection=run.projection(),
                answer=None,
                p01_event_count=0,
                **base,
            )
        except P01AdapterError as exc:
            # Retry-safe rejections keep the stored handoff and the live
            # WAITING_APPROVAL state intact; anything else is a proven failure.
            if exc.dispatch_class != P01DispatchClass.NOT_DISPATCHED:
                self._transition_if_possible(
                    run, ClawRunStatus.FAILED, "P01 승인 재개 실행이 실패했습니다."
                )
            raise

        try:
            for event in resumed.result.events:
                projector.consume(event)
            self._validate_lifecycle(run, projector, resumed)
        except P01AdapterError:
            self._transition_if_possible(
                run, ClawRunStatus.FAILED, "P01 승인 결과를 안전하게 투영할 수 없습니다."
            )
            raise
        except RunStateError:
            self._transition_if_possible(
                run, ClawRunStatus.FAILED, "P01 승인 결과를 안전하게 투영할 수 없습니다."
            )
            raise P01AdapterError(
                "p01_continuation_contract_failure",
                "P01 continuation contract를 안전하게 투영할 수 없습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from None
        except Exception:
            self._transition_if_possible(
                run, ClawRunStatus.FAILED, "P01 승인 결과를 안전하게 투영할 수 없습니다."
            )
            raise P01AdapterError(
                "p01_continuation_projection_failed",
                "P01 continuation 결과가 안전하게 투영되지 않았습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from None

        result = resumed.result
        wire = resumed.pause_wire
        next_pause_id = _wire_pause_field(wire, "continuation_id")
        answer = (
            redact_secrets(result.execution_result.answer)
            if run.status is ClawRunStatus.COMPLETED
            else None
        )
        return ClawApprovalContinuationOutcome(
            projection=run.projection(),
            answer=answer,
            p01_event_count=projector.event_count,
            next_continuation_ref=None if wire is None else wire.continuation_ref,
            next_pause_id=next_pause_id,
            next_pause_expires_at=None if wire is None else _wire_pause_field(wire, "expires_at"),
            next_p01_run_id=None if wire is None else _wire_pause_field(wire, "run_id"),
            next_trusted_request=None if wire is None else request.snapshot,
            **base,
        )

    @staticmethod
    def _validate_lifecycle(
        run: ClawRun, projector: ClawResumeProjector, resumed: ContinuationResumeResult
    ) -> None:
        if not run.terminal and run.status is not ClawRunStatus.WAITING_APPROVAL:
            raise P01AdapterError(
                "incomplete_p01_continuation_lifecycle",
                "P01 continuation이 terminal 또는 approval-paused 증거 없이 끝났습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )
        if run.status is ClawRunStatus.COMPLETED and not projector.resume_seen:
            raise P01AdapterError(
                "missing_run_resumed",
                "P01 continuation이 RUN_RESUMED 증거 없이 완료되었습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )
        if run.status is ClawRunStatus.WAITING_APPROVAL:
            # The generic Core public parser intentionally refuses pause keys,
            # so the re-pause identity is the validated Engine wire, exactly as
            # in #2946's first-pause path.
            if resumed.pause_wire is None:
                raise P01AdapterError(
                    "missing_next_pause",
                    "P01가 재일시정지했으나 Engine pause wire가 반환되지 않았습니다.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                    failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                )
            if _wire_pause_field(resumed.pause_wire, "continuation_id") is None:
                raise P01AdapterError(
                    "missing_pause_id",
                    "재일시정지된 Engine pause의 신원을 복원할 수 없습니다.",
                    dispatch_class=P01DispatchClass.DISPATCHED,
                    failure_detail=P01_FAILURE_DETAIL_CONTRACT,
                )
        elif resumed.pause_wire is not None:
            raise P01AdapterError(
                "continuation_without_pause",
                "WAITING_APPROVAL이 아닌 상태에서 Engine continuation 신원이 반환되었습니다.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )

    @staticmethod
    def _transition_if_possible(run: ClawRun, next_status: ClawRunStatus, summary: str) -> None:
        if run.terminal:
            return
        if run.status in {ClawRunStatus.WAITING_APPROVAL, ClawRunStatus.RUNNING}:
            try:
                run.transition(next_status, summary=summary)
            except RunStateError:
                pass


__all__ = [
    "APPROVAL_DECISION_APPROVE",
    "APPROVAL_DECISION_DENY",
    "ClawApprovalContinuationOutcome",
    "ContinuationResumeResult",
    "ENGINE_APPROVAL_DENIED_CODE",
    "OWNER_APPROVAL_DECISIONS",
    "P01ApprovalContinuationService",
    "P01ApprovalDeniedError",
    "P01EngineApprovalContinuationClient",
    "RETRY_SAFE_RESUME_CODES",
    "TrustedResumeRequest",
    "build_first_party_decision_submission",
    "decision_outcome",
    "reconstruct_trusted_resume_request",
]
