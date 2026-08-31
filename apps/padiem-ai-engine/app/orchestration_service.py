"""Language-neutral unified orchestration service contract for Padiem AI Engine.

Exposes bounded, product-neutral orchestration execution, approval continuation
resumption, cancellation, and streaming over the internal Engine transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import secrets
from typing import Any, Awaitable, Protocol

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    AgentRecoveryPolicy,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    BoundedAgentDefinition,
    CompiledAgentProfile,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    OrchestrationError,
    OrchestrationEvent,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationResumeRequest,
    OrchestrationRunner,
    ToolAuthorizationContext,
    VerifiedApprovalDecision,
)

from app.execution_context_wire import parse_execution_context
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _require_exact_object,
    _service_error,
    build_execution_request,
)

ORCHESTRATE_PATH = "/internal/v1/orchestrate"
ORCHESTRATE_RESUME_PATH = "/internal/v1/orchestrate/resume"
ORCHESTRATE_CANCEL_PATH = "/internal/v1/orchestrate/cancel"
ORCHESTRATE_STREAM_PATH = "/internal/v1/orchestrate/stream"


class ApprovalDecisionVerifier(Protocol):
    """Trusted adapter that authenticates a product/control-plane decision."""

    def verify(
        self,
        submission: "ApprovalDecisionSubmission",
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision | Awaitable[VerifiedApprovalDecision]: ...


@dataclass(frozen=True, slots=True)
class ApprovalDecisionSubmission:
    """Untrusted wire data; never pass this type to Core resume()."""

    decision_id: str
    pause_id: str
    outcome: ApprovalOutcome
    authority_ref: str
    evidence_ref: str
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class ContinuationRecord:
    app_id: str
    pause: ApprovalPause
    continuation_ref: str
    plan_id: str | None
    state: str = "active"


class ContinuationStore(Protocol):
    def issue(self, *, app_id: str, pause: ApprovalPause, plan_id: str | None) -> str: ...
    def resolve(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord: ...
    def consume(self, *, app_id: str, continuation_ref: str) -> None: ...
    def cancel(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord: ...


class InMemoryContinuationStore:
    """Opaque server-side continuation adapter for the Engine process.

    Deployments that need durable continuation state inject their own adapter.
    The wire never accepts an ApprovalPause as a substitute for this lookup.
    """

    def __init__(self) -> None:
        self._records: dict[str, ContinuationRecord] = {}

    def issue(self, *, app_id: str, pause: ApprovalPause, plan_id: str | None) -> str:
        ref = f"cont_{secrets.token_urlsafe(32)}"
        self._records[ref] = ContinuationRecord(
            app_id=app_id,
            pause=pause,
            continuation_ref=ref,
            plan_id=plan_id,
        )
        return ref

    def _get(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        if record.state == "cancelled":
            raise ServiceContractError("continuation_cancelled", "Continuation has been cancelled.", status_code=409)
        if record.state == "consumed":
            raise ServiceContractError("continuation_consumed", "Continuation has already been consumed.", status_code=409)
        if record.pause.expires_at <= datetime.now(timezone.utc):
            raise ServiceContractError("continuation_expired", "Continuation has expired.", status_code=409)
        return record

    def resolve(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        if not isinstance(continuation_ref, str) or not continuation_ref.startswith("cont_"):
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        return self._get(app_id=app_id, continuation_ref=continuation_ref)

    def consume(self, *, app_id: str, continuation_ref: str) -> None:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        self._records[continuation_ref] = ContinuationRecord(
            app_id=record.app_id,
            pause=record.pause,
            continuation_ref=record.continuation_ref,
            plan_id=record.plan_id,
            state="consumed",
        )

    def cancel(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        cancelled = ContinuationRecord(
            app_id=record.app_id,
            pause=record.pause,
            continuation_ref=record.continuation_ref,
            plan_id=record.plan_id,
            state="cancelled",
        )
        self._records[continuation_ref] = cancelled
        return cancelled


_DEFAULT_CONTINUATION_STORE = InMemoryContinuationStore()


def _parse_agent_plan(value: Any) -> AgentPlan | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_plan", "agent_plan must be an object.")
    data = dict(value)
    agent_id = data.get("agent_id")
    if not isinstance(agent_id, str):
        raise ServiceContractError("invalid_plan", "agent_plan.agent_id must be a string.")
    raw_steps = data.get("steps", ())
    if not isinstance(raw_steps, (list, tuple)):
        raise ServiceContractError("invalid_plan", "agent_plan.steps must be an array.")
    steps: list[AgentPlanStep] = []
    for step_item in raw_steps:
        if not isinstance(step_item, Mapping):
            raise ServiceContractError("invalid_plan", "each plan step must be an object.")
        sd = dict(step_item)
        steps.append(
            AgentPlanStep(
                step_id=sd.get("step_id", ""),
                objective=sd.get("objective", ""),
                tool_id=sd.get("tool_id"),
                depends_on=tuple(sd.get("depends_on", ())),
            )
        )
    return AgentPlan(agent_id=agent_id, steps=tuple(steps))


def _parse_recovery_policy(value: Any) -> AgentRecoveryPolicy | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_recovery_policy", "recovery_policy must be an object.")
    data = dict(value)
    codes = tuple(data.get("retryable_driver_codes", ()))
    max_retries = data.get("max_retries_per_step", 1)
    return AgentRecoveryPolicy(
        retryable_driver_codes=codes,
        max_retries_per_step=max_retries,
    )


def _parse_required_timestamp(data: Mapping[str, Any], name: str) -> datetime:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be explicit.")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be a valid timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be timezone-aware.")
    return parsed


def _required_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be explicit.")
    return value


def _parse_approval_decision_submission(value: Any) -> ApprovalDecisionSubmission:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_decision", "decision must be an object.")
    data = dict(value)
    required = {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}
    if required - set(data):
        raise ServiceContractError("invalid_decision", "decision is missing required fields.")
    try:
        outcome = ApprovalOutcome(data["outcome"])
    except (TypeError, ValueError):
        raise ServiceContractError("invalid_decision", "decision.outcome is invalid.") from None
    return ApprovalDecisionSubmission(
        decision_id=_required_text(data, "decision_id"),
        pause_id=_required_text(data, "pause_id"),
        outcome=outcome,
        authority_ref=_required_text(data, "authority_ref"),
        evidence_ref=_required_text(data, "evidence_ref"),
        decided_at=_parse_required_timestamp(data, "decided_at"),
    )


def _parse_continuation_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("cont_") or len(value) > 128:
        raise ServiceContractError("invalid_continuation", "continuation_ref is invalid.", status_code=409)
    return value


class OrchestrationEngineService:
    """Pure-Python internal request handler for Unified Orchestration Pipeline."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        b14_service_bound: bool,
        idempotency_adapter: Any | None = None,
        approval_decision_verifier: ApprovalDecisionVerifier | None = None,
        continuation_store: ContinuationStore | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if approval_decision_verifier is not None and not callable(getattr(approval_decision_verifier, "verify", None)):
            raise ValueError("approval_decision_verifier must provide verify()")
        if continuation_store is not None:
            for method in ("issue", "resolve", "consume", "cancel"):
                if not callable(getattr(continuation_store, method, None)):
                    raise ValueError(f"continuation_store must provide {method}()")
        self._runtime_factory = runtime_factory
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter
        self._approval_decision_verifier = approval_decision_verifier
        self._continuation_store = continuation_store or _DEFAULT_CONTINUATION_STORE
        self._continuation_store_is_explicit = continuation_store is not None

    async def _verify_decision(
        self,
        submission: ApprovalDecisionSubmission,
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision:
        verifier = self._approval_decision_verifier
        if verifier is None:
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Approval decision verification is unavailable.",
                status_code=503,
            )
        verified = verifier.verify(submission, pause=pause, app_id=app_id)
        if inspect.isawaitable(verified):
            verified = await verified
        if not isinstance(verified, VerifiedApprovalDecision):
            raise ServiceContractError(
                "invalid_verified_decision",
                "Approval decision verification failed.",
                status_code=422,
            )
        return verified

    def _orchestration_body(
        self,
        result: OrchestrationResult,
        *,
        app_id: str,
    ) -> dict[str, Any]:
        body = result.to_public_dict()
        pause = result.approval_pause
        if pause is not None:
            if self._approval_decision_verifier is None or not self._continuation_store_is_explicit:
                raise ServiceContractError(
                    "approval_verification_unavailable",
                    "Approval continuation requires trusted verification and an explicit continuation store.",
                    status_code=503,
                )
            plan_id = result.plan.agent_id if result.plan is not None else pause.plan_id
            if pause.trace_id is None:
                raise ServiceContractError(
                    "invalid_continuation",
                    "Approval pause is missing trusted continuation identity.",
                    status_code=500,
                )
            body["continuation_ref"] = self._continuation_store.issue(
                app_id=app_id,
                pause=pause,
                plan_id=plan_id,
            )
        return body

    async def orchestrate_payload(self, payload: Any) -> ServiceResponse:
        """Execute an orchestration request through OrchestrationRunner."""
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )

        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)

        exec_payload = {
            k: payload[k]
            for k in ("app_id", "agent", "messages", "session_id", "additional_system_context", "trace_id", "execution_context")
            if k in payload
        }
        try:
            _, exec_req, ctx = build_execution_request(exec_payload)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        if ctx is None:
            ctx = ExecutionContext(trace_id=exec_req.trace_id or "orch_trace")

        plan = _parse_agent_plan(payload.get("agent_plan"))
        rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
        max_retries = int(payload.get("max_retries", 3))

        orch_req = OrchestrationRequest(
            execution_request=exec_req,
            context=ctx,
            app_id=app_id,
            subject_id=payload.get("subject_id"),
            agent_plan=plan,
            recovery_policy=rec_policy,
            max_retries=max_retries,
            require_evidence=bool(payload.get("require_evidence", False)),
            require_verification=bool(payload.get("require_verification", False)),
        )

        try:
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.run(orch_req)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except OrchestrationError as exc:
            status_code = 422 if exc.code in {"invalid_plan", "authority_widening_rejected"} else 400
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except Exception:
            return _service_error("engine_internal_error", "Orchestration execution failed.", status_code=500)

        try:
            orchestration_body = self._orchestration_body(result, app_id=app_id)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "orchestration": orchestration_body,
            },
        )

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        """Resume only a server-issued continuation with a verified decision."""
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = self._continuation_store.resolve(
                app_id=app_id,
                continuation_ref=continuation_ref,
            )
            submission = _parse_approval_decision_submission(payload.get("decision"))
            if submission.pause_id != record.pause.pause_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "decision does not match the server-issued continuation.",
                    status_code=409,
                )
            _, exec_req, ctx = build_execution_request({
                k: payload[k]
                for k in ("app_id", "agent", "messages", "session_id", "additional_system_context", "trace_id", "execution_context")
                if k in payload
            })
            plan = _parse_agent_plan(payload.get("agent_plan"))
            if record.plan_id is not None:
                if plan is None or plan.agent_id != record.plan_id:
                    raise ServiceContractError("continuation_identity_mismatch", "agent plan does not match the server-issued continuation.", status_code=409)
            elif plan is not None:
                raise ServiceContractError("continuation_identity_mismatch", "unexpected agent plan does not match the server-issued continuation.", status_code=409)
            if exec_req.agent.id != record.pause.agent_runtime_id:
                raise ServiceContractError("continuation_identity_mismatch", "agent runtime does not match the server-issued continuation.", status_code=409)
            if ctx is None:
                ctx = ExecutionContext(trace_id=exec_req.trace_id or record.pause.trace_id or "orch_resume_trace")
            if ctx.trace_id != record.pause.trace_id:
                raise ServiceContractError("continuation_identity_mismatch", "trace_id does not match the server-issued continuation.", status_code=409)
            decision = await self._verify_decision(submission, pause=record.pause, app_id=app_id)
            if (
                decision.decision_id != submission.decision_id
                or decision.pause_id != submission.pause_id
                or decision.outcome is not submission.outcome
                or decision.decided_at != submission.decided_at
            ):
                raise ServiceContractError("invalid_verified_decision", "Verified decision does not match the submitted decision.", status_code=422)
            self._continuation_store.consume(app_id=app_id, continuation_ref=record.continuation_ref)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
        try:
            max_retries = int(payload.get("max_retries", 3))
            resume_req = OrchestrationResumeRequest(
                pause=record.pause,
                decision=decision,
                execution_request=exec_req,
                context=ctx,
                app_id=app_id,
                subject_id=payload.get("subject_id"),
                agent_plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
            )
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.resume(resume_req)
        except OrchestrationError as exc:
            status_code = 409 if exc.code in {"continuation_expired", "approval_denied", "continuation_identity_mismatch"} else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except Exception:
            return _service_error("engine_internal_error", "Orchestration resumption failed.", status_code=500)

        try:
            orchestration_body = self._orchestration_body(result, app_id=app_id)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "orchestration": orchestration_body,
            },
        )

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        """Cancel only a server-issued continuation."""
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = self._continuation_store.resolve(app_id=app_id, continuation_ref=continuation_ref)
            self._continuation_store.cancel(app_id=app_id, continuation_ref=record.continuation_ref)
            trace_id = record.pause.trace_id or "cancel_trace"
            reason = payload.get("reason", "user_cancelled")
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime)
            events = runner.cancel_pause(record.pause, trace_id=trace_id, reason=reason)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except Exception:
            return _service_error("engine_internal_error", "Cancellation failed.", status_code=500)

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "status": "cancelled",
                "events": [e.to_public_dict() for e in events],
            },
        )

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        """Route and handle incoming orchestration requests."""
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path not in {ORCHESTRATE_PATH, ORCHESTRATE_RESUME_PATH, ORCHESTRATE_CANCEL_PATH}:
            return _service_error("not_found", "Orchestration route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _service_error("unsupported_media_type", "Content-Type must be application/json.", status_code=415)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error("request_too_large", "Request body exceeds the safety limit.", status_code=413)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)

        if path == ORCHESTRATE_PATH:
            return await self.orchestrate_payload(payload)
        if path == ORCHESTRATE_RESUME_PATH:
            return await self.resume_payload(payload)
        return await self.cancel_payload(payload)
