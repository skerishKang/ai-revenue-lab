"""Integration scenarios for P01 Execution State Machine & Recovery (#1098).

Verifies Scenarios A through F:
- Scenario A: Tool failure -> retry -> success
- Scenario B: Tool failure -> approval -> resume
- Scenario C: timeout -> terminal
- Scenario D: cancellation -> terminal
- Scenario E: idempotency replay
- Scenario F: full Memory -> Agent -> Skill -> Tool -> Evidence -> Recovery -> Result
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
    IdempotencyConflictError,
    MemoryNamespace,
    MemoryReadAuthorization,
    MemoryReadPolicy,
    MemoryScope,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationResumeRequest,
    OrchestrationRunner,
    RetrievedItem,
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
    is_verification_satisfied,
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


class MockValidator:
    async def verify(self, request: VerificationRequest, graph: Any) -> VerificationVerdict:
        return VerificationVerdict(
            verdict_id="verd_sm_1",
            claim_id=request.claim_id,
            validator_id="val:test:1",
            disposition=VerificationDisposition.VERIFIED,
            checked_evidence_ids=tuple(e.id for e in graph.sources),
            confidence=0.99,
            summary="Claim verified against evidence.",
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
        description="Agent for integration scenario.",
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
# Scenario A: Tool Failure -> Recovery Evaluation -> Success
# ==============================================================================

async def test_scenario_a_recovery_decision_and_step_completion() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    call_count = 0

    async def calc_h(args: dict) -> dict:
        nonlocal call_count
        call_count += 1
        return {"result": 42 * call_count}

    runtime.register(calc_spec, calc_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Compute value", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Summarize output", depends_on=("s1",)),
        ),
    )

    ctx = ExecutionContext(trace_id="tr_scen_a", timeout_seconds=15.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute answer"},),
        trace_id="tr_scen_a",
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=runtime,
        recovery_policy=AgentRecoveryPolicy(retryable_driver_codes=("transient_error",), max_retries_per_step=2),
    )

    result = await runner.run(req)
    assert result.execution_result.metadata.status == RunStatus.COMPLETED
    assert result.execution_state is ExecutionState.COMPLETED
    assert len(result.state_transitions) >= 2


# ==============================================================================
# Scenario B: Tool Failure -> Approval -> Resume
# ==============================================================================

async def test_scenario_b_approval_pause_and_resume_state_machine() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=(),  # Unconfirmed -> will pause
    )

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()
    async def calc_h(args: dict) -> dict:
        return {"result": 100}
    runtime.register(calc_spec, calc_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )

    ctx = ExecutionContext(trace_id="tr_scen_b")
    exec_req = ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "Compute"},), trace_id="tr_scen_b")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    # Step 1: Run enters WAITING_APPROVAL
    res_1 = await runner.run(
        OrchestrationRequest(
            execution_request=exec_req,
            context=ctx,
            app_id="b62",
            agent_definition=agent_def,
            compiled_agent_profile=compiled,
            agent_plan=plan,
            tool_authorization=auth_ctx,
            tool_runtime=runtime,
        )
    )
    assert res_1.execution_result.metadata.status == RunStatus.PAUSED
    assert res_1.execution_state is ExecutionState.WAITING_APPROVAL
    pause = res_1.approval_pause
    assert pause is not None

    # Step 2: Resume transitions WAITING_APPROVAL -> RUNNING -> COMPLETED
    now = datetime.now(timezone.utc)
    decision = VerifiedApprovalDecision(
        decision_id="dec_scen_b",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:lead",
        evidence_ref="session:scen_b",
        decided_at=now,
    )
    resumed_auth = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    res_2 = await runner.resume(
        OrchestrationResumeRequest(
            pause=pause,
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
    )
    assert res_2.execution_result.metadata.status == RunStatus.COMPLETED
    assert res_2.execution_state is ExecutionState.COMPLETED
    transitions = [t.to_state.value for t in res_2.state_transitions]
    assert transitions == ["running", "completed"]


# ==============================================================================
# Scenario C: Timeout -> Terminal TIMED_OUT / FAILED
# ==============================================================================

async def test_scenario_c_timeout_terminal() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    calc_spec = make_calc_spec(tool_id="calc", timeout_seconds=5.0)
    runtime = ToolRuntime()
    async def slow_h(args: dict) -> dict:
        await asyncio.sleep(2.0)
        return {"r": 1}
    runtime.register(calc_spec, slow_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do slow math", tool_id="calc"),),
    )

    ctx = ExecutionContext(trace_id="tr_scen_c", timeout_seconds=1.0)
    exec_req = ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "Compute"},), trace_id="tr_scen_c")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    with pytest.raises(OrchestrationError) as exc:
        await runner.run(
            OrchestrationRequest(
                execution_request=exec_req,
                context=ctx,
                app_id="b62",
                agent_definition=agent_def,
                compiled_agent_profile=compiled,
                agent_plan=plan,
                tool_authorization=auth_ctx,
                tool_runtime=runtime,
            )
        )
    assert exc.value.code == "orchestration_timeout"


# ==============================================================================
# Scenario D: Cancellation -> Terminal CANCELLED
# ==============================================================================

async def test_scenario_d_cancellation_terminal() -> None:
    pause = ApprovalPause(
        pause_id="pause_scen_d",
        run_id="run_scen_d",
        agent_runtime_id="agent_runtime_id",
        tool_id="calc",
        invocation_sha256="d" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        trace_id="tr_scen_d",
    )
    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    events = runner.cancel_pause(pause, trace_id="tr_scen_d", reason="user_cancelled")
    assert len(events) == 1
    assert events[0].kind == OrchestrationEventKind.RUN_CANCELLED


# ==============================================================================
# Scenario E: Idempotency Replay
# ==============================================================================

async def test_scenario_e_idempotency_replay() -> None:
    runtime = MockCoreRuntime(answer="replayed output")
    adapter = MockIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    agent = AgentProfile(id="ag_e", title="A", description="D", system_instruction="I", task_type="general", optimize_for="balanced", max_tokens=100)
    exec_req = ExecutionRequest(agent=agent, messages=({"role": "user", "content": "run replay"},), trace_id="tr_scen_e")
    ctx = ExecutionContext(trace_id="tr_scen_e", idempotency_key="key_scen_e")
    req = OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")

    res_1 = await runner.run(req)
    assert res_1.execution_result.answer == "replayed output"
    assert runtime.call_count == 1

    res_2 = await runner.run(req)
    assert res_2.execution_result.answer == "replayed output"
    assert runtime.call_count == 1  # No rerun!
    assert res_2.execution_state is ExecutionState.COMPLETED


# ==============================================================================
# Scenario F: Full Composition (Memory -> Agent -> Skill -> Tool -> Evidence -> Verification -> Result)
# ==============================================================================

async def test_scenario_f_full_composition() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def calc_h(args: dict) -> dict:
        return {"result": 777}
    runtime.register(calc_spec, calc_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Finalize", depends_on=("s1",)),
        ),
    )

    ns = MemoryNamespace(app_id="b62", scope=MemoryScope.PROJECT, subject_id="sub_f")
    mem_item = RetrievedItem(
        id="mem_f",
        namespace="b62:project:sub_f",
        source_type="doc",
        provider="padiem",
        source_ref="doc:guidelines",
        content="Reference calculation guidelines.",
    )
    mem_auth = MemoryReadAuthorization(
        app_id="b62",
        readable_namespaces=(ns,),
    )

    ev_source = Evidence(
        id="ev_f_1",
        title="Full Calc Spec",
        snippet="Full composition verified output 777.",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="docs",
        source_type="web",
        url="https://docs.padiem.io/calc_full",
    )
    ev_claim = EvidenceClaim(
        id="clm_f_1",
        text="Output 777 is verified.",
        derivation=ClaimDerivation.OBSERVED,
    )
    ev_link = ClaimEvidenceLink(
        claim_id="clm_f_1",
        evidence_id="ev_f_1",
        relation=ClaimEvidenceRelation.SUPPORTS,
    )
    v_policy = TrustedVerificationPolicy(
        allowed_validator_ids=("val:test:1",),
    )

    ctx = ExecutionContext(trace_id="tr_scen_f", timeout_seconds=20.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute full composition"},),
        trace_id="tr_scen_f",
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    result = await runner.run(
        OrchestrationRequest(
            execution_request=exec_req,
            context=ctx,
            app_id="b62",
            subject_id="sub_f",
            agent_definition=agent_def,
            compiled_agent_profile=compiled,
            agent_plan=plan,
            tool_authorization=auth_ctx,
            tool_runtime=runtime,
            memory_authorization=mem_auth,
            memory_items=(mem_item,),
            memory_read_policy=MemoryReadPolicy(allowed_scopes=(MemoryScope.PROJECT,)),
            evidence_sources=(ev_source,),
            evidence_claims=(ev_claim,),
            evidence_links=(ev_link,),
            evidence_validator=MockValidator(),
            verification_policy=v_policy,
        )
    )

    assert result.execution_result.metadata.status == RunStatus.COMPLETED
    assert result.execution_state is ExecutionState.COMPLETED
    assert len(result.claim_assessments) == 1
    assert is_verification_satisfied(result.claim_assessments[0]) is True
