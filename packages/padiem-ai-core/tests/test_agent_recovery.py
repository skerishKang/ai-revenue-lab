import pytest

from padiem_ai_core.agent_recovery import (
    AgentFailure,
    AgentFailureSource,
    AgentRecoveryAction,
    AgentRecoveryContext,
    AgentRecoveryError,
    AgentRecoveryPolicy,
    decide_agent_recovery,
)


def failure(
    source: AgentFailureSource = AgentFailureSource.ORCHESTRATION_DRIVER,
    code: str = "driver_connection_reset",
) -> AgentFailure:
    return AgentFailure(
        source=source,
        code=code,
        safe_message="A bounded orchestration failure occurred.",
    )


def context(**overrides) -> AgentRecoveryContext:
    values = {
        "step_index": 2,
        "retries_used": 0,
        "external_side_effect_since_checkpoint": False,
    }
    values.update(overrides)
    return AgentRecoveryContext(**values)


def policy(**overrides) -> AgentRecoveryPolicy:
    values = {
        "retryable_driver_codes": ("driver_connection_reset",),
        "max_retries_per_step": 2,
    }
    values.update(overrides)
    return AgentRecoveryPolicy(**values)


def test_allowlisted_driver_failure_can_retry_within_budget() -> None:
    decision = decide_agent_recovery(failure(), context(), policy=policy())

    assert decision.action is AgentRecoveryAction.RETRY_STEP
    assert decision.reason == "trusted_driver_retry_allowed"


def test_driver_failure_not_allowlisted_fails_closed() -> None:
    decision = decide_agent_recovery(
        failure(code="driver_unknown"),
        context(),
        policy=policy(),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "driver_failure_not_allowlisted"


def test_retry_budget_exhaustion_fails_run() -> None:
    decision = decide_agent_recovery(
        failure(),
        context(retries_used=2),
        policy=policy(max_retries_per_step=2),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "step_retry_budget_exhausted"


def test_side_effect_boundary_blocks_driver_retry() -> None:
    decision = decide_agent_recovery(
        failure(),
        context(external_side_effect_since_checkpoint=True),
        policy=policy(),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "side_effect_boundary_blocks_retry"


def test_provider_failure_never_retries_in_core() -> None:
    decision = decide_agent_recovery(
        failure(AgentFailureSource.PROVIDER, "provider_timeout"),
        context(),
        policy=AgentRecoveryPolicy(
            retryable_driver_codes=("provider_timeout",),
            max_retries_per_step=4,
        ),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "provider_recovery_belongs_to_b14"


def test_tool_failure_never_auto_retries() -> None:
    decision = decide_agent_recovery(
        failure(AgentFailureSource.TOOL_RUNTIME, "tool_runtime_error"),
        context(),
        policy=AgentRecoveryPolicy(
            retryable_driver_codes=("tool_runtime_error",),
            max_retries_per_step=4,
        ),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "tool_failure_not_auto_retryable"


def test_policy_failure_never_retries() -> None:
    decision = decide_agent_recovery(
        failure(AgentFailureSource.POLICY, "permission_denied"),
        context(),
        policy=policy(),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "policy_failure_not_retryable"


def test_unknown_failure_never_retries() -> None:
    decision = decide_agent_recovery(
        failure(AgentFailureSource.UNKNOWN, "unknown_failure"),
        context(),
        policy=policy(),
    )

    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "unknown_failure_not_retryable"


def test_recovery_policy_rejects_duplicate_codes() -> None:
    with pytest.raises(AgentRecoveryError) as exc_info:
        AgentRecoveryPolicy(
            retryable_driver_codes=("driver_reset", "driver_reset"),
        )

    assert exc_info.value.code == "invalid_agent_recovery_policy"


def test_recovery_context_rejects_negative_retry_count() -> None:
    with pytest.raises(AgentRecoveryError) as exc_info:
        AgentRecoveryContext(step_index=1, retries_used=-1)

    assert exc_info.value.code == "invalid_agent_recovery_context"


def test_public_decision_has_no_executable_retry_payload() -> None:
    public = decide_agent_recovery(failure(), context(), policy=policy()).to_public_dict()

    assert public == {
        "action": "retry_step",
        "reason": "trusted_driver_retry_allowed",
    }
    assert "arguments" not in public
    assert "provider" not in public
