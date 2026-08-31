"""Tests for canonical approval-continuation execution identity."""

from __future__ import annotations

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    AgentRecoveryPolicy,
    ExecutionContext,
    ExecutionRequest,
)

from app.continuation_identity import (
    build_continuation_execution_identity,
    continuation_identity_matches,
)


def _agent(**changes):
    values = {
        "id": "agent_profile_1",
        "title": "Agent",
        "description": "Test agent",
        "system_instruction": "Follow the task exactly.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 1024,
        "allowed_tools": ("calc",),
        "required_capabilities": ("text",),
        "context_policy": {"mode": "bounded"},
        "model_policy": {"model": "b14/auto", "temperature": 0.2},
        "max_steps": 4,
        "output_contract": {"type": "text"},
    }
    values.update(changes)
    return AgentProfile(**values)


def _request(**changes):
    values = {
        "agent": _agent(),
        "messages": ({"role": "user", "content": "hello"},),
        "session_id": "session_1",
        "additional_system_context": "bounded context",
        "trace_id": "trace_1",
    }
    values.update(changes)
    return ExecutionRequest(**values)


def _plan(tool_id: str = "calc", objective: str = "Calculate"):
    return AgentPlan(
        agent_id="agent:padiem:orchestrator@1",
        steps=(
            AgentPlanStep(
                step_id="step_1",
                objective=objective,
                tool_id=tool_id,
                depends_on=(),
            ),
        ),
    )


def _identity(**changes):
    values = {
        "app_id": "b62",
        "request": _request(),
        "context": ExecutionContext(
            trace_id="trace_1",
            idempotency_key="idem_1",
            timeout_seconds=20.0,
        ),
        "subject_id": "subject_1",
        "plan": _plan(),
        "recovery_policy": AgentRecoveryPolicy(
            retryable_driver_codes=("driver_timeout",),
            max_retries_per_step=1,
        ),
        "max_retries": 2,
        "require_evidence": True,
        "require_verification": True,
    }
    values.update(changes)
    return build_continuation_execution_identity(**values)


def test_identical_semantics_match() -> None:
    assert continuation_identity_matches(_identity(), _identity()) is True


def test_message_change_rejected() -> None:
    changed = _identity(
        request=_request(messages=({"role": "user", "content": "different"},))
    )
    assert continuation_identity_matches(_identity(), changed) is False


def test_session_and_system_context_changes_rejected() -> None:
    assert continuation_identity_matches(
        _identity(), _identity(request=_request(session_id="session_2"))
    ) is False
    assert continuation_identity_matches(
        _identity(),
        _identity(request=_request(additional_system_context="different context")),
    ) is False


def test_agent_semantic_change_rejected_even_when_id_is_same() -> None:
    changed_agent = _agent(system_instruction="Different instruction")
    assert continuation_identity_matches(
        _identity(), _identity(request=_request(agent=changed_agent))
    ) is False


def test_subject_and_trace_changes_rejected() -> None:
    assert continuation_identity_matches(
        _identity(), _identity(subject_id="subject_2")
    ) is False
    assert continuation_identity_matches(
        _identity(),
        _identity(
            request=_request(trace_id="trace_2"),
            context=ExecutionContext(
                trace_id="trace_2",
                idempotency_key="idem_1",
                timeout_seconds=20.0,
            ),
        ),
    ) is False


def test_idempotency_and_timeout_changes_rejected() -> None:
    assert continuation_identity_matches(
        _identity(),
        _identity(
            context=ExecutionContext(
                trace_id="trace_1",
                idempotency_key="idem_2",
                timeout_seconds=20.0,
            )
        ),
    ) is False
    assert continuation_identity_matches(
        _identity(),
        _identity(
            context=ExecutionContext(
                trace_id="trace_1",
                idempotency_key="idem_1",
                timeout_seconds=30.0,
            )
        ),
    ) is False


def test_plan_semantic_change_rejected_with_same_agent_id() -> None:
    assert continuation_identity_matches(
        _identity(), _identity(plan=_plan(tool_id="search"))
    ) is False
    assert continuation_identity_matches(
        _identity(), _identity(plan=_plan(objective="Different objective"))
    ) is False


def test_recovery_and_retry_widening_rejected() -> None:
    widened_policy = AgentRecoveryPolicy(
        retryable_driver_codes=("driver_timeout", "driver_unavailable"),
        max_retries_per_step=2,
    )
    assert continuation_identity_matches(
        _identity(), _identity(recovery_policy=widened_policy)
    ) is False
    assert continuation_identity_matches(
        _identity(), _identity(max_retries=3)
    ) is False


def test_evidence_or_verification_weakening_rejected() -> None:
    assert continuation_identity_matches(
        _identity(), _identity(require_evidence=False)
    ) is False
    assert continuation_identity_matches(
        _identity(), _identity(require_verification=False)
    ) is False
