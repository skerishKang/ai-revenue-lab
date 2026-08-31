"""Language-neutral unified orchestration service contract for Padiem AI Engine.

Exposes bounded, product-neutral orchestration execution, approval continuation
resumption, cancellation, and streaming over the internal Engine transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

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


def _parse_approval_pause(value: Any) -> ApprovalPause:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_pause", "pause must be an object.")
    data = dict(value)
    req_str = data.get("requirement", "user_confirmation")
    requirement = ApprovalRequirement(req_str)
    created_at_str = data.get("created_at")
    expires_at_str = data.get("expires_at")
    created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else datetime.now(timezone.utc)

    scope = tuple(data.get("approval_scope") or ())
    return ApprovalPause(
        pause_id=data.get("pause_id", ""),
        run_id=data.get("run_id", ""),
        agent_runtime_id=data.get("agent_runtime_id", ""),
        tool_id=data.get("tool_id", ""),
        invocation_sha256=data.get("invocation_sha256", "0" * 64),
        requirement=requirement,
        step_index=data.get("step_index", 1),
        created_at=created_at,
        expires_at=expires_at,
        trace_id=data.get("trace_id"),
        plan_id=data.get("plan_id"),
        approval_scope=scope,
    )


def _parse_approval_decision(value: Any) -> VerifiedApprovalDecision:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_decision", "decision must be an object.")
    data = dict(value)
    outcome_str = data.get("outcome", "approved")
    outcome = ApprovalOutcome(outcome_str)
    decided_at_str = data.get("decided_at")
    decided_at = datetime.fromisoformat(decided_at_str) if decided_at_str else datetime.now(timezone.utc)

    return VerifiedApprovalDecision(
        decision_id=data.get("decision_id", ""),
        pause_id=data.get("pause_id", ""),
        outcome=outcome,
        authority_ref=data.get("authority_ref", "user:authenticated"),
        evidence_ref=data.get("evidence_ref", "session:authenticated"),
        decided_at=decided_at,
    )


class OrchestrationEngineService:
    """Pure-Python internal request handler for Unified Orchestration Pipeline."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        b14_service_bound: bool,
        idempotency_adapter: Any | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self._runtime_factory = runtime_factory
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter

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

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "orchestration": result.to_public_dict(),
            },
        )

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        """Resume an approval-paused continuation through OrchestrationRunner.resume()."""
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
            pause = _parse_approval_pause(payload.get("pause"))
            decision = _parse_approval_decision(payload.get("decision"))
            _, exec_req, ctx = build_execution_request(exec_payload)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        if ctx is None:
            ctx = ExecutionContext(trace_id=exec_req.trace_id or pause.trace_id or "orch_resume_trace")

        plan = _parse_agent_plan(payload.get("agent_plan"))
        rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
        max_retries = int(payload.get("max_retries", 3))

        resume_req = OrchestrationResumeRequest(
            pause=pause,
            decision=decision,
            execution_request=exec_req,
            context=ctx,
            app_id=app_id,
            subject_id=payload.get("subject_id"),
            agent_plan=plan,
            recovery_policy=rec_policy,
            max_retries=max_retries,
        )

        try:
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.resume(resume_req)
        except OrchestrationError as exc:
            status_code = 409 if exc.code in {"continuation_expired", "approval_denied"} else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except Exception:
            return _service_error("engine_internal_error", "Orchestration resumption failed.", status_code=500)

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "orchestration": result.to_public_dict(),
            },
        )

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        """Cancel an approval pause through OrchestrationRunner.cancel_pause()."""
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        try:
            pause = _parse_approval_pause(payload.get("pause"))
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        trace_id = payload.get("trace_id") or pause.trace_id or "cancel_trace"
        reason = payload.get("reason", "user_cancelled")

        try:
            runtime = self._runtime_factory(payload.get("app_id", "default"))
            runner = OrchestrationRunner(runtime=runtime)
            events = runner.cancel_pause(pause, trace_id=trace_id, reason=reason)
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
