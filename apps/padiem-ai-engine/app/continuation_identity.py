"""Canonical execution identity for approval continuations.

A continuation belongs to one logical orchestration execution. Resume requests
must not mutate execution-relevant semantics after the approval pause was
issued. This module deliberately derives identity from validated Core contracts,
not arbitrary caller JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from padiem_ai_core import (
    AgentPlan,
    AgentRecoveryPolicy,
    ExecutionContext,
    ExecutionRequest,
    request_fingerprint,
)


def _agent_identity(request: ExecutionRequest) -> dict[str, Any]:
    agent = request.agent
    return {
        "id": agent.id,
        "title": agent.title,
        "description": agent.description,
        "system_instruction": agent.system_instruction,
        "task_type": agent.task_type,
        "optimize_for": agent.optimize_for,
        "max_tokens": agent.max_tokens,
        "allowed_tools": list(agent.allowed_tools),
        "required_capabilities": list(agent.required_capabilities),
        "context_policy": agent.context_policy,
        "model_policy": agent.model_policy,
        "max_steps": agent.max_steps,
        "output_contract": agent.output_contract,
    }


def execution_request_identity_payload(
    *,
    app_id: str,
    request: ExecutionRequest,
    context: ExecutionContext,
) -> dict[str, Any]:
    """Return the canonical logical-execution projection used for replay/binding."""
    return {
        "app_id": app_id,
        "agent": _agent_identity(request),
        "messages": [dict(message) for message in request.messages],
        "session_id": request.session_id,
        "additional_system_context": request.additional_system_context,
        "trace_id": request.trace_id,
        "execution_context": {
            "trace_id": context.trace_id,
            "idempotency_key": context.idempotency_key,
            "timeout_seconds": context.timeout_seconds,
        },
    }


def execution_request_identity_fingerprint(
    *,
    app_id: str,
    request: ExecutionRequest,
    context: ExecutionContext,
) -> str:
    return request_fingerprint(
        execution_request_identity_payload(app_id=app_id, request=request, context=context)
    )


def agent_plan_identity_fingerprint(plan: AgentPlan | None) -> str | None:
    if plan is None:
        return None
    return request_fingerprint(
        {
            "agent_id": plan.agent_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "objective": step.objective,
                    "tool_id": step.tool_id,
                    "depends_on": list(step.depends_on),
                }
                for step in plan.steps
            ],
        }
    )


def recovery_policy_identity_fingerprint(
    policy: AgentRecoveryPolicy | None,
) -> str | None:
    if policy is None:
        return None
    # Code order has no authorization meaning; canonicalize it as a set.
    return request_fingerprint(
        {
            "retryable_driver_codes": sorted(policy.retryable_driver_codes),
            "max_retries_per_step": policy.max_retries_per_step,
        }
    )


@dataclass(frozen=True, slots=True)
class ContinuationExecutionIdentity:
    """Server-persisted identity of one paused logical orchestration execution."""

    request_fingerprint: str
    plan_fingerprint: str | None
    subject_id: str | None
    recovery_policy_fingerprint: str | None
    max_retries: int
    require_evidence: bool
    require_verification: bool

    def __post_init__(self) -> None:
        if not isinstance(self.request_fingerprint, str) or len(self.request_fingerprint) != 64:
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        for name in ("plan_fingerprint", "recovery_policy_fingerprint"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) != 64):
                raise ValueError(f"{name} must be a sha256 hex digest or None")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not isinstance(self.require_evidence, bool) or not isinstance(self.require_verification, bool):
            raise ValueError("evidence/verification requirements must be booleans")

    @property
    def fingerprint(self) -> str:
        """Return a compact storage/index identity without dropping field semantics."""
        return request_fingerprint(
            {
                "request_fingerprint": self.request_fingerprint,
                "plan_fingerprint": self.plan_fingerprint,
                "subject_id": self.subject_id,
                "recovery_policy_fingerprint": self.recovery_policy_fingerprint,
                "max_retries": self.max_retries,
                "require_evidence": self.require_evidence,
                "require_verification": self.require_verification,
            }
        )


def build_continuation_execution_identity(
    *,
    app_id: str,
    request: ExecutionRequest,
    context: ExecutionContext,
    subject_id: str | None,
    plan: AgentPlan | None,
    recovery_policy: AgentRecoveryPolicy | None,
    max_retries: int,
    require_evidence: bool,
    require_verification: bool,
) -> ContinuationExecutionIdentity:
    return ContinuationExecutionIdentity(
        request_fingerprint=execution_request_identity_fingerprint(
            app_id=app_id,
            request=request,
            context=context,
        ),
        plan_fingerprint=agent_plan_identity_fingerprint(plan),
        subject_id=subject_id,
        recovery_policy_fingerprint=recovery_policy_identity_fingerprint(recovery_policy),
        max_retries=max_retries,
        require_evidence=require_evidence,
        require_verification=require_verification,
    )


def continuation_identity_matches(
    stored: ContinuationExecutionIdentity,
    candidate: ContinuationExecutionIdentity,
) -> bool:
    """Exact equality is intentional: resume may not widen or mutate semantics."""
    if not isinstance(stored, ContinuationExecutionIdentity):
        raise TypeError("stored continuation identity is invalid")
    if not isinstance(candidate, ContinuationExecutionIdentity):
        raise TypeError("candidate continuation identity is invalid")
    return stored == candidate
