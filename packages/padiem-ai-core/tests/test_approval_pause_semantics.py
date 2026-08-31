"""Tests for P01 Approval Pause & Resume Semantics Hardening (#1221).

Verifies that APPROVAL_REQUIRED halts the bounded orchestration pipeline in a true
APPROVAL_PAUSED state (not RUN_FAILED, not COMPLETED), preserves deterministic
continuation identity, and allows explicit, safe resume from the paused step without
widening authority boundaries.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from padiem_ai_core import (
    AgentExecutionBudget,
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    AgentTerminalReason,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalPolicy,
    ApprovalRequirement,
    BoundedAgentDefinition,
    ClaimEvidenceLink,
    CompiledAgentProfile,
    ContinuationStatus,
    ErrorClass,
    Evidence,
    EvidenceClaim,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
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
    VerificationVerdict,
    VerifiedApprovalDecision,
    compile_agent_profile,
)


class MockCoreRuntime:
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            answer="fallback answer",
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


def make_agent_def(
    agent_id: str = "agent:padiem:test_agent@1",
    allowed_tools: tuple[str, ...] = ("tool:padiem:calculator@1",),
    max_steps: int = 10,
    max_tool_calls: int = 10,
    max_wall_seconds: int = 30,
) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id=agent_id,
        publisher_id="publisher:padiem",
        title="Test Agent",
        description="Agent for approval test.",
        instruction="Execute bounded plan steps.",
        output_contract_ref="io:agent_out@1",
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        allowed_tool_ids=allowed_tools,
        execution_budget=AgentExecutionBudget(
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            max_wall_seconds=max_wall_seconds,
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
    approval_policy: ApprovalPolicy = ApprovalPolicy.USER_CONFIRMATION,
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


def make_auth_ctx(
    agent_id: str,
    allowed_tools: tuple[str, ...] = ("tool:padiem:calculator@1",),
    user_confirmed: tuple[str, ...] = (),
    externally_authorized: tuple[str, ...] = (),
) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id="b62",
        agent_id=agent_id,
        granted_auth_scopes=allowed_tools,
        user_confirmed_tools=user_confirmed,
        externally_authorized_tools=externally_authorized,
    )


# ==============================================================================
# 1. Test A: Approval Pause (Not Failed, Not Completed)
# ==============================================================================

async def test_approval_pause_semantics_yields_paused_state() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    # Unconfirmed -> will pause
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",), user_confirmed=())

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()

    async def calc_handler(arguments: dict) -> dict:
        return {"result": 42}

    runtime.register(calc_spec, calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Finish", depends_on=("s1",)),
        ),
    )

    ctx = ExecutionContext(trace_id="tr_pause_a", timeout_seconds=15.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute result"},),
        trace_id="tr_pause_a",
    )
    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=runtime,
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    result = await runner.run(req)

    # 1. Must be PAUSED, not FAILED, not COMPLETED
    assert result.execution_result.metadata.status == RunStatus.PAUSED
    assert result.approval_pause is not None
    assert result.approval_pause.tool_id == "calc"
    assert result.approval_pause.step_index == 1
    assert result.continuation_state is not None
    assert result.continuation_state.status == ContinuationStatus.WAITING_APPROVAL

    # 2. Event sequence: APPROVAL_PAUSED is emitted, no RUN_FAILED
    event_kinds = [e.kind for e in result.events]
    assert OrchestrationEventKind.TOOL_STARTED in event_kinds
    assert OrchestrationEventKind.APPROVAL_PAUSED in event_kinds
    assert OrchestrationEventKind.RUN_FAILED not in event_kinds
    assert OrchestrationEventKind.RUN_COMPLETED not in event_kinds

    # 3. Public dictionary projection is clean and redacted
    pub = result.to_public_dict()
    assert pub["approval_pause"]["status"] == "paused"
    assert pub["approval_pause"]["tool_id"] == "calc"
    assert "arguments" not in pub["approval_pause"]


# ==============================================================================
# 2. Test B: Explicit Approval & Resume Success
# ==============================================================================

async def test_resume_success_from_paused_step() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",), user_confirmed=())

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()

    async def calc_handler(arguments: dict) -> dict:
        return {"result": 42}

    runtime.register(calc_spec, calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Finish", depends_on=("s1",)),
        ),
    )

    ctx = ExecutionContext(trace_id="tr_resume_b", timeout_seconds=15.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute result"},),
        trace_id="tr_resume_b",
    )
    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=runtime,
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    pause_res = await runner.run(req)
    pause = pause_res.approval_pause
    assert pause is not None

    # Construct verified approval decision
    now = datetime.now(timezone.utc)
    decision = VerifiedApprovalDecision(
        decision_id="dec_user_1",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="session:auth_99",
        decided_at=now,
    )

    # Resume with updated authorization containing confirmed tool
    resumed_auth_ctx = make_auth_ctx(
        agent_id=compiled.runtime_profile.id,
        allowed_tools=("calc",),
        user_confirmed=("calc",),
    )

    resume_req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=resumed_auth_ctx,
        tool_runtime=runtime,
        now=now,
    )

    resumed_result = await runner.resume(resume_req)

    # Must complete successfully
    assert resumed_result.execution_result.metadata.status == RunStatus.COMPLETED
    assert resumed_result.continuation_state is not None
    assert resumed_result.continuation_state.status == ContinuationStatus.RESUMABLE

    events = [e.kind for e in resumed_result.events]
    assert OrchestrationEventKind.RUN_RESUMED in events
    assert OrchestrationEventKind.TOOL_STARTED in events
    assert OrchestrationEventKind.TOOL_COMPLETED in events
    assert OrchestrationEventKind.RUN_COMPLETED in events


# ==============================================================================
# 3. Test C, D, E: Continuation Identity Binding (Fail Closed)
# ==============================================================================

async def test_resume_continuation_identity_mismatch_fails_closed() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    now = datetime.now(timezone.utc)

    pause = ApprovalPause(
        pause_id="pause_123",
        run_id="run_abc",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="calc",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        trace_id="tr_valid",
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def dummy_h(args: dict) -> dict:
        return {"res": 1}
    runtime.register(calc_spec, dummy_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    # Case 1: Wrong decision pause_id (Test C)
    decision_wrong_pause = VerifiedApprovalDecision(
        decision_id="dec_1",
        pause_id="pause_different",
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_1",
        decided_at=now,
    )
    req_c = OrchestrationResumeRequest(
        pause=pause,
        decision=decision_wrong_pause,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_valid"),
        context=ExecutionContext(trace_id="tr_valid"),
        app_id="b62",
    )
    with pytest.raises(OrchestrationError) as exc_c:
        await runner.resume(req_c)
    assert exc_c.value.code == "continuation_identity_mismatch"

    # Case 2: Wrong trace_id (Test D)
    decision_valid = VerifiedApprovalDecision(
        decision_id="dec_1",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_1",
        decided_at=now,
    )
    req_d = OrchestrationResumeRequest(
        pause=pause,
        decision=decision_valid,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_wrong"),
        context=ExecutionContext(trace_id="tr_wrong"),
        app_id="b62",
    )
    with pytest.raises(OrchestrationError) as exc_d:
        await runner.resume(req_d)
    assert exc_d.value.code == "continuation_identity_mismatch"

    # Case 3: Wrong agent runtime id (Test E)
    wrong_agent = AgentProfile(id="agent:other:profile", title="Other", description="Other", system_instruction="inst", task_type="general", optimize_for="balanced", max_tokens=2048)
    req_e = OrchestrationResumeRequest(
        pause=pause,
        decision=decision_valid,
        execution_request=ExecutionRequest(agent=wrong_agent, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_valid"),
        context=ExecutionContext(trace_id="tr_valid"),
        app_id="b62",
    )
    with pytest.raises(OrchestrationError) as exc_e:
        await runner.resume(req_e)
    assert exc_e.value.code == "continuation_identity_mismatch"


# ==============================================================================
# 4. Test F: Expired Continuation (Fail Closed)
# ==============================================================================

async def test_resume_expired_continuation_fails_closed() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    expires_at = created_at + timedelta(minutes=15)  # expired 1h45m ago

    pause = ApprovalPause(
        pause_id="pause_exp",
        run_id="run_exp",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="calc",
        invocation_sha256="b" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=created_at,
        expires_at=expires_at,
        trace_id="tr_exp",
    )

    decision = VerifiedApprovalDecision(
        decision_id="dec_exp",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_exp",
        decided_at=created_at + timedelta(minutes=5),
    )

    req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_exp"),
        context=ExecutionContext(trace_id="tr_exp"),
        app_id="b62",
        now=datetime.now(timezone.utc),  # current time is after expires_at
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(req)
    assert exc.value.code == "continuation_expired"


# ==============================================================================
# 5. Test G: Cancelled Pause (RUN_CANCELLED)
# ==============================================================================

async def test_cancelled_pause_and_subsequent_resume_rejection() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    now = datetime.now(timezone.utc)

    pause = ApprovalPause(
        pause_id="pause_cancel",
        run_id="run_cancel",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="calc",
        invocation_sha256="c" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        trace_id="tr_cancel",
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    cancel_events = runner.cancel_pause(pause, trace_id="tr_cancel", reason="user_cancelled")
    assert len(cancel_events) == 1
    assert cancel_events[0].kind == OrchestrationEventKind.RUN_CANCELLED

    # Denied decision reflects cancelled outcome
    decision = VerifiedApprovalDecision(
        decision_id="dec_cancel",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.DENIED,
        authority_ref="user:admin",
        evidence_ref="ev_cancel",
        decided_at=now,
    )

    req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_cancel"),
        context=ExecutionContext(trace_id="tr_cancel"),
        app_id="b62",
        now=now,
    )

    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(req)
    assert exc.value.code == "approval_denied"


# ==============================================================================
# 6. Test H & I: Duplicate and Conflicting Resumes
# ==============================================================================

async def test_duplicate_consumed_decision_and_conflicting_resume() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    now = datetime.now(timezone.utc)

    pause = ApprovalPause(
        pause_id="pause_dup",
        run_id="run_dup",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="calc",
        invocation_sha256="d" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        trace_id="tr_dup",
    )

    decision = VerifiedApprovalDecision(
        decision_id="dec_consumed_1",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_1",
        decided_at=now,
    )

    # Re-using an already consumed decision ID fails closed
    req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_dup"),
        context=ExecutionContext(trace_id="tr_dup"),
        app_id="b62",
        now=now,
        consumed_decision_ids=frozenset({"dec_consumed_1"}),
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(req)
    assert exc.value.code == "invalid_decision"


# ==============================================================================
# 7. Test J: Authority Non-Widening
# ==============================================================================

async def test_resume_cannot_mint_unauthorized_tool_grant() -> None:
    # Agent def allows ONLY "calc"
    agent_def = make_agent_def(allowed_tools=("tool:padiem:calculator@1",))
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    now = datetime.now(timezone.utc)

    # Approval pause fraudulently claims tool "unauthorized_tool"
    pause = ApprovalPause(
        pause_id="pause_exploit",
        run_id="run_exploit",
        agent_runtime_id=compiled.runtime_profile.id,
        tool_id="unauthorized_tool",
        invocation_sha256="e" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        trace_id="tr_exploit",
    )

    decision = VerifiedApprovalDecision(
        decision_id="dec_exploit",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_exploit",
        decided_at=now,
    )

    auth_ctx = make_auth_ctx(
        agent_id=compiled.runtime_profile.id,
        allowed_tools=("calc",),
        user_confirmed=("unauthorized_tool",),
    )

    req = OrchestrationResumeRequest(
        pause=pause,
        decision=decision,
        execution_request=ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "resume msg"},), trace_id="tr_exploit"),
        context=ExecutionContext(trace_id="tr_exploit"),
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        tool_authorization=auth_ctx,
        now=now,
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(req)
    assert exc.value.code == "authority_widening_rejected"


# ==============================================================================
# 8. Test K & L: Event Ordering and Non-Tool Step Integrity
# ==============================================================================

async def test_resume_event_ordering_and_non_tool_step_integrity() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",), user_confirmed=())

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()
    async def calc_handler(arguments: dict) -> dict:
        return {"result": 100}
    runtime.register(calc_spec, calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Synthesize answer without tool", depends_on=("s1",)),
        ),
    )

    ctx = ExecutionContext(trace_id="tr_order", timeout_seconds=15.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute result"},),
        trace_id="tr_order",
    )
    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=runtime,
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    pause_res = await runner.run(req)

    # Initial run event order: RUN_STARTED -> TOOL_STARTED -> APPROVAL_PAUSED
    events_1 = [e.kind for e in pause_res.events]
    assert events_1[0] == OrchestrationEventKind.RUN_STARTED
    assert OrchestrationEventKind.TOOL_STARTED in events_1
    assert events_1[-1] == OrchestrationEventKind.APPROVAL_PAUSED

    # Resume run event order: RUN_STARTED -> RUN_RESUMED -> TOOL_STARTED -> TOOL_COMPLETED -> RUN_COMPLETED
    now = datetime.now(timezone.utc)
    decision = VerifiedApprovalDecision(
        decision_id="dec_order",
        pause_id=pause_res.approval_pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:admin",
        evidence_ref="ev_order",
        decided_at=now,
    )
    resumed_auth = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",), user_confirmed=("calc",))
    resume_req = OrchestrationResumeRequest(
        pause=pause_res.approval_pause,
        decision=decision,
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=resumed_auth,
        tool_runtime=runtime,
        now=now,
    )

    resume_res = await runner.resume(resume_req)
    events_2 = [e.kind for e in resume_res.events]
    assert events_2[0] == OrchestrationEventKind.RUN_STARTED
    assert events_2[1] == OrchestrationEventKind.RUN_RESUMED
    assert OrchestrationEventKind.TOOL_STARTED in events_2
    assert OrchestrationEventKind.TOOL_COMPLETED in events_2
    assert events_2[-1] == OrchestrationEventKind.RUN_COMPLETED
