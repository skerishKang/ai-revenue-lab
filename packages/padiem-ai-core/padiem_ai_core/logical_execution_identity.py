"""Canonical material identity for one logical P01 orchestration execution.

This module owns the field classification used by idempotent replay semantics.
It fingerprints execution meaning, not observability or durable-record selectors:
``trace_id`` may change across a retry and ``idempotency_key`` selects the
record, so neither belongs to the logical execution fingerprint.
"""

from __future__ import annotations

from typing import Any

from .agent_planner import AgentPlan
from .agent_recovery import AgentRecoveryPolicy
from .execution_context import ExecutionContext, request_fingerprint
from .execution_runtime import ExecutionRequest


def agent_identity_payload(request: ExecutionRequest) -> dict[str, Any]:
    """Project the full execution-relevant AgentProfile semantics."""

    if not isinstance(request, ExecutionRequest):
        raise TypeError("request must be ExecutionRequest")
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


def agent_plan_identity_fingerprint(plan: AgentPlan | None) -> str | None:
    """Fingerprint a validated finite plan without adding authorization meaning."""

    if plan is None:
        return None
    if not isinstance(plan, AgentPlan):
        raise TypeError("plan must be AgentPlan or None")
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
    """Fingerprint trusted recovery semantics; code ordering has no meaning."""

    if policy is None:
        return None
    if not isinstance(policy, AgentRecoveryPolicy):
        raise TypeError("policy must be AgentRecoveryPolicy or None")
    return request_fingerprint(
        {
            "retryable_driver_codes": sorted(policy.retryable_driver_codes),
            "max_retries_per_step": policy.max_retries_per_step,
        }
    )


def canonical_logical_execution_payload(
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
) -> dict[str, Any]:
    """Return material execution semantics for replay/conflict classification."""

    if not isinstance(request, ExecutionRequest):
        raise TypeError("request must be ExecutionRequest")
    if not isinstance(context, ExecutionContext):
        raise TypeError("context must be ExecutionContext")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    if not isinstance(require_evidence, bool) or not isinstance(require_verification, bool):
        raise TypeError("evidence/verification requirements must be booleans")

    return {
        "app_id": app_id,
        "agent": agent_identity_payload(request),
        "messages": [dict(message) for message in request.messages],
        "session_id": request.session_id,
        "additional_system_context": request.additional_system_context,
        "timeout_seconds": context.timeout_seconds,
        "subject_id": subject_id,
        "plan_fingerprint": agent_plan_identity_fingerprint(plan),
        "recovery_policy_fingerprint": recovery_policy_identity_fingerprint(
            recovery_policy
        ),
        "max_retries": max_retries,
        "require_evidence": require_evidence,
        "require_verification": require_verification,
    }


def canonical_logical_execution_fingerprint(
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
) -> str:
    """Return the canonical SHA-256 identity of one logical execution."""

    return request_fingerprint(
        canonical_logical_execution_payload(
            app_id=app_id,
            request=request,
            context=context,
            subject_id=subject_id,
            plan=plan,
            recovery_policy=recovery_policy,
            max_retries=max_retries,
            require_evidence=require_evidence,
            require_verification=require_verification,
        )
    )
