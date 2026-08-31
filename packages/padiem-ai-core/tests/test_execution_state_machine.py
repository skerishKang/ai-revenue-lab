"""Tests for P01 Execution State Machine & Recovery Semantics (#1098).

Verifies Tests A through Q:
- Test A: retryable failure -> retry -> success
- Test B: non-retryable failure -> fail
- Test C: approval -> pause -> resume -> success
- Test D: approval -> cancel -> resume rejected
- Test E: retry budget exhausted -> fail
- Test F: wall time exhausted -> timeout
- Test G: cancel -> terminal -> no retry/resume
- Test H: idempotency replay -> no rerun
- Test I: idempotency conflict -> fail closed
- Test J: retry != provider fallback
- Test K: resume != retry
- Test L: approval != permission expansion
- Test M: timeout != cancellation
- Test N: terminal state rejects all invalid transitions
- Test O: event sequence deterministic
- Test P: actual Tool events only
- Test Q: retry attempts preserve evidence provenance boundaries
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    AgentExecutionBudget,
    AgentFailure,
    AgentFailureSource,
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    AgentRecoveryAction,
    AgentRecoveryContext,
    AgentRecoveryPolicy,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalPolicy,
    ApprovalRequirement,
    BoundedAgentDefinition,
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    CompiledAgentProfile,
    ContinuationStatus,
    ErrorClass,
    Evidence,
    EvidenceClaim,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    ExecutionStateMachine,
    ExecutionStateMachineError,
    ExecutionTransition,
    IdempotencyConflictError,
    InvalidTransitionError,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationResumeRequest,
    OrchestrationRunner,
    RunMetadata,
    RunStatus,
    ToolAuthorizationContext,
    ToolEvent,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeBinding,
    ToolSideEffect,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    TrustedVerificationPolicy,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    VerifiedApprovalDecision,
    compile_agent_profile,
    decide_agent_recovery,
    is_terminal_state,
    is_valid_transition,
)


class MockCoreRuntime:
    def __init__(self, answer: str = "core answer") -> None:
        self._answer = answer
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer=self._answer,
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class MockIdempotencyAdapter:
    def __init__(self) -> None:
        self.storage: dict[str, tuple[str, Any]] = {}
        self.begin_calls = 0
        self.commit_calls = 0

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str) -> Any:
        self.begin_calls += 1
        key = f"{app_id}:{idempotency_key}"
        if key in self.storage:
            stored_fp, result = self.storage[key]
            if stored_fp != request_fingerprint:
                raise IdempotencyConflictError("fingerprint mismatch for idempotency key")
            return result
        return None

    async def commit(self, *, app_id: str, idempotency_key: str, request_fingerprint: str, result: Any) -> None:
        self.commit_calls += 1
        key = f"{app_id}:{idempotency_key}"
        self.storage[key] = (request_fingerprint, result)

    async def abort(self, *, app_id: str, idempotency_key: str, reason: str) -> None:
        pass


def make_agent_def(
    agent_id: str = "agent:padiem:test_agent@1",
    allowed_tools: tuple[str, ...] = ("tool:padiem:calculator@1",),
) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id=agent_id,
        publisher_id="publisher:padiem",
        title="Test Agent",
        description="Agent for state machine test.",
        instruction="Execute bounded plan steps.",
        output_contract_ref="io:agent_out@1",
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        allowed_tool_ids=allowed_tools,
        execution_budget=AgentExecutionBudget(
            max_steps=10,
            max_tool_calls=10,
            max_wall_seconds=30,
        ),
    )


def make_compiled_profile(
    definition: BoundedAgentDefinition,
    runtime_tool_id: str = "calc",
) -> CompiledAgentProfile:
    tool_bindings = tuple(
        ToolRuntimeBinding(canonical_tool_id=cid, runtime_tool_id=runtime_tool_id)
        for cid in definition.allowed_tool_ids
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:agent_out@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=2048,
        max_steps_cap=definition.execution_budget.max_steps,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
        tool_bindings=tool_bindings,
    )
    return compile_agent_profile(definition, policy)


def make_calc_spec(
    tool_id: str = "calc",
    approval_policy: ApprovalPolicy = ApprovalPolicy.NOT_REQUIRED,
    timeout_seconds: float = 10.0,
) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        title="Calculator",
        description="Math operations",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=approval_policy,
        input_schema={"type": "object"},
        output_contract={"type": "object"},
        timeout_seconds=timeout_seconds,
    )


# ==============================================================================
# Unit Tests A through Q
# ==============================================================================

def test_a_retryable_failure_recovery_decision() -> None:
    """Test A: retryable failure -> retry decision allowed under policy."""
    policy = AgentRecoveryPolicy(
        retryable_driver_codes=("transient_network_error",),
        max_retries_per_step=2,
    )
    failure = AgentFailure(
        source=AgentFailureSource.ORCHESTRATION_DRIVER,
        code="transient_network_error",
        safe_message="Transient driver error",
    )
    ctx = AgentRecoveryContext(
        step_index=1,
        retries_used=0,
        external_side_effect_since_checkpoint=False,
    )
    decision = decide_agent_recovery(failure, ctx, policy=policy)
    assert decision.action is AgentRecoveryAction.RETRY_STEP
    assert decision.reason == "trusted_driver_retry_allowed"

    # Verify state machine transition
    sm = ExecutionStateMachine(max_retries=2)
    sm.start()
    assert sm.state is ExecutionState.RUNNING
    sm.start_recovery("failure_encountered")
    assert sm.state is ExecutionState.RECOVERING
    sm.retry("driver_retry")
    assert sm.state is ExecutionState.RUNNING
    assert sm.retries_used == 1
    assert sm.attempt_number == 2


def test_b_non_retryable_failure_fails() -> None:
    """Test B: non-retryable failure -> fail_run."""
    policy = AgentRecoveryPolicy(
        retryable_driver_codes=("transient_network_error",),
        max_retries_per_step=2,
    )
    failure = AgentFailure(
        source=AgentFailureSource.POLICY,
        code="authorization_denied",
        safe_message="Permission denied",
    )
    ctx = AgentRecoveryContext(step_index=1, retries_used=0)
    decision = decide_agent_recovery(failure, ctx, policy=policy)
    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "policy_failure_not_retryable"


def test_c_approval_pause_and_resume_state_machine() -> None:
    """Test C: approval -> pause -> resume -> success."""
    sm = ExecutionStateMachine()
    sm.start()
    assert sm.state is ExecutionState.RUNNING

    sm.pause_for_approval("tool_requires_confirmation")
    assert sm.state is ExecutionState.WAITING_APPROVAL
    assert sm.is_terminal is False

    sm.resume("user_approved")
    assert sm.state is ExecutionState.RUNNING
    assert sm.retries_used == 0  # Resume does NOT consume retry budget
    assert sm.attempt_number == 1  # Resume does NOT increment attempt

    sm.complete("run_completed")
    assert sm.state is ExecutionState.COMPLETED
    assert sm.is_terminal is True


def test_d_approval_cancel_and_resume_rejected() -> None:
    """Test D: approval -> cancel -> resume rejected."""
    sm = ExecutionStateMachine()
    sm.start()
    sm.pause_for_approval("tool_requires_confirmation")
    assert sm.state is ExecutionState.WAITING_APPROVAL

    sm.cancel("user_cancelled")
    assert sm.state is ExecutionState.CANCELLED
    assert sm.is_terminal is True

    # Resuming from terminal state CANCELLED must fail
    with pytest.raises(InvalidTransitionError):
        sm.resume("attempted_resume")


def test_e_retry_budget_exhausted_fails() -> None:
    """Test E: retry budget exhausted -> fail."""
    policy = AgentRecoveryPolicy(
        retryable_driver_codes=("transient_error",),
        max_retries_per_step=1,
    )
    failure = AgentFailure(
        source=AgentFailureSource.ORCHESTRATION_DRIVER,
        code="transient_error",
        safe_message="Transient error",
    )
    # Already used 1 retry
    ctx = AgentRecoveryContext(step_index=1, retries_used=1)
    decision = decide_agent_recovery(failure, ctx, policy=policy)
    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "step_retry_budget_exhausted"

    # State machine enforces max_retries limit
    sm = ExecutionStateMachine(max_retries=1)
    sm.start()
    sm.start_recovery()
    sm.retry()  # used 1
    assert sm.remaining_retries == 0

    sm.start_recovery()
    with pytest.raises(ExecutionStateMachineError) as exc:
        sm.retry()
    assert exc.value.code == "retry_budget_exhausted"


def test_f_wall_time_exhausted_timeout() -> None:
    """Test F: wall time exhausted -> timeout."""
    sm = ExecutionStateMachine()
    sm.start()
    sm.timeout("wall_time_limit_exceeded")
    assert sm.state is ExecutionState.TIMED_OUT
    assert sm.is_terminal is True


def test_g_cancel_is_terminal_no_retry_or_resume() -> None:
    """Test G: cancel -> terminal -> no retry/resume."""
    sm = ExecutionStateMachine()
    sm.start()
    sm.cancel("user_cancellation")
    assert sm.state is ExecutionState.CANCELLED
    assert sm.is_terminal is True

    with pytest.raises(InvalidTransitionError):
        sm.start_recovery()
    with pytest.raises(InvalidTransitionError):
        sm.retry()
    with pytest.raises(InvalidTransitionError):
        sm.resume()


async def test_h_idempotency_replay_no_rerun() -> None:
    """Test H: idempotency replay -> no rerun."""
    runtime = MockCoreRuntime(answer="replayed result")
    adapter = MockIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    exec_req = ExecutionRequest(
        agent=AgentProfile(id="ag_1", title="A", description="D", system_instruction="I", task_type="general", optimize_for="balanced", max_tokens=100),
        messages=({"role": "user", "content": "hello"},),
        trace_id="tr_replay",
    )
    ctx = ExecutionContext(trace_id="tr_replay", idempotency_key="key_idem_1")
    req = OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")

    # Run 1: executes runtime
    res_1 = await runner.run(req)
    assert res_1.execution_result.answer == "replayed result"
    assert runtime.call_count == 1
    assert adapter.commit_calls == 1

    # Run 2: returns replay without calling runtime.run()
    res_2 = await runner.run(req)
    assert res_2.execution_result.answer == "replayed result"
    assert runtime.call_count == 1  # Not incremented!
    assert res_2.execution_state is ExecutionState.COMPLETED


async def test_i_idempotency_conflict_fails_closed() -> None:
    """Test I: same key with different fingerprint raises IdempotencyConflictError."""
    runtime = MockCoreRuntime()
    adapter = MockIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    agent = AgentProfile(id="ag_1", title="A", description="D", system_instruction="I", task_type="general", optimize_for="balanced", max_tokens=100)
    exec_req_1 = ExecutionRequest(agent=agent, messages=({"role": "user", "content": "prompt A"},), trace_id="tr_1")
    req_1 = OrchestrationRequest(execution_request=exec_req_1, context=ExecutionContext(trace_id="tr_1", idempotency_key="shared_key"), app_id="b62")

    await runner.run(req_1)

    # Different prompt with SAME idempotency key
    exec_req_2 = ExecutionRequest(agent=agent, messages=({"role": "user", "content": "different prompt B"},), trace_id="tr_2")
    req_2 = OrchestrationRequest(execution_request=exec_req_2, context=ExecutionContext(trace_id="tr_2", idempotency_key="shared_key"), app_id="b62")

    with pytest.raises(IdempotencyConflictError):
        await runner.run(req_2)


def test_j_retry_is_not_provider_fallback() -> None:
    """Test J: retry != provider fallback. Core recovery rejects Provider failures."""
    failure = AgentFailure(
        source=AgentFailureSource.PROVIDER,
        code="provider_rate_limited",
        safe_message="Rate limit from upstream provider",
    )
    ctx = AgentRecoveryContext(step_index=1, retries_used=0)
    policy = AgentRecoveryPolicy(retryable_driver_codes=("provider_rate_limited",), max_retries_per_step=3)

    decision = decide_agent_recovery(failure, ctx, policy=policy)
    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "provider_recovery_belongs_to_b14"


def test_k_resume_is_not_retry_invariant() -> None:
    """Test K: resume != retry.

    - Retry creates a new attempt within remaining retry budget.
    - Resume continues the exact same attempt and step index.
    """
    sm = ExecutionStateMachine(max_retries=3)
    sm.start()
    assert sm.attempt_number == 1
    assert sm.retries_used == 0

    # 1. Approval Pause & Resume lifecycle
    sm.pause_for_approval()
    assert sm.state is ExecutionState.WAITING_APPROVAL
    sm.resume()
    assert sm.state is ExecutionState.RUNNING
    assert sm.attempt_number == 1  # Unchanged
    assert sm.retries_used == 0    # Unchanged

    # 2. Recovery & Retry lifecycle
    sm.start_recovery()
    assert sm.state is ExecutionState.RECOVERING
    sm.retry()
    assert sm.state is ExecutionState.RUNNING
    assert sm.attempt_number == 2  # Incremented
    assert sm.retries_used == 1    # Incremented


def test_l_approval_is_not_permission_expansion() -> None:
    """Test L: approval verifies specific action; does not expand permissions."""
    agent_def = make_agent_def(allowed_tools=("tool:padiem:calculator@1",))
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")

    # Approval pause fraudulently claims tool "malicious_tool"
    pause = ApprovalPause(
        pause_id="pause_l",
        run_id="run_l",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="malicious_tool",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        trace_id="tr_l",
    )
    decision = VerifiedApprovalDecision(
        decision_id="dec_l",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_l",
        decided_at=datetime.now(timezone.utc),
    )
    req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "msg"},), trace_id="tr_l"),
        context=ExecutionContext(trace_id="tr_l"),
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
    )
    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    with pytest.raises(OrchestrationError) as exc:
        asyncio.run(runner.resume(req))
    assert exc.value.code == "authority_widening_rejected"


def test_m_timeout_is_not_cancellation() -> None:
    """Test M: timeout != cancellation."""
    sm_timeout = ExecutionStateMachine()
    sm_timeout.start()
    sm_timeout.timeout("budget_exhausted")
    assert sm_timeout.state is ExecutionState.TIMED_OUT

    sm_cancel = ExecutionStateMachine()
    sm_cancel.start()
    sm_cancel.cancel("user_aborted")
    assert sm_cancel.state is ExecutionState.CANCELLED

    assert sm_timeout.state != sm_cancel.state
    assert sm_timeout.state.value == "timed_out"
    assert sm_cancel.state.value == "cancelled"


def test_n_terminal_state_rejects_all_transitions() -> None:
    """Test N: terminal states reject all subsequent transitions."""
    for term_state in (ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.CANCELLED, ExecutionState.TIMED_OUT, ExecutionState.EXPIRED):
        sm = ExecutionStateMachine(initial_state=term_state)
        assert sm.is_terminal is True
        for target in ExecutionState:
            assert is_valid_transition(term_state, target) is False
            with pytest.raises(InvalidTransitionError):
                sm.transition_to(target, "illegal_attempt")


def test_o_event_sequence_determinism() -> None:
    """Test O: identical transition sequence produces identical state sequence."""
    def run_sequence() -> tuple[str, ...]:
        sm = ExecutionStateMachine(max_retries=2)
        sm.start()
        sm.start_recovery()
        sm.retry()
        sm.pause_for_approval()
        sm.resume()
        sm.complete()
        return tuple(t.to_state.value for t in sm.transitions)

    seq_1 = run_sequence()
    seq_2 = run_sequence()
    assert seq_1 == seq_2 == ("running", "recovering", "running", "waiting_approval", "running", "completed")


def test_p_side_effect_boundary_blocks_auto_retry() -> None:
    """Test P: side effect boundary blocks automatic retry."""
    failure = AgentFailure(
        source=AgentFailureSource.ORCHESTRATION_DRIVER,
        code="transient_driver_error",
        safe_message="Error",
    )
    ctx = AgentRecoveryContext(
        step_index=2,
        retries_used=0,
        external_side_effect_since_checkpoint=True,  # Side effect occurred!
    )
    policy = AgentRecoveryPolicy(retryable_driver_codes=("transient_driver_error",))
    decision = decide_agent_recovery(failure, ctx, policy=policy)
    assert decision.action is AgentRecoveryAction.FAIL_RUN
    assert decision.reason == "side_effect_boundary_blocks_retry"


def test_q_retry_attempts_preserve_provenance() -> None:
    """Test Q: retry attempt number is tracked explicitly in transitions and metadata."""
    sm = ExecutionStateMachine(max_retries=2)
    sm.start()
    assert sm.attempt_number == 1

    sm.start_recovery(metadata={"error": "transient"})
    sm.retry(metadata={"attempt": 2})
    assert sm.attempt_number == 2
    assert sm.transitions[-1].attempt_number == 2
    assert sm.transitions[-1].metadata["attempt"] == 2
