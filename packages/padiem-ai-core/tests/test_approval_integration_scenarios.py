"""Integration scenarios for P01 Approval Pause & Resume (#1221).

Verifies Scenarios A through E:
- Scenario A: Plan -> authorized Tool -> approval -> pause -> resume -> Tool -> evidence -> complete
- Scenario B: Plan -> Tool -> approval -> cancel -> resume rejected
- Scenario C: Plan -> Tool timeout before approval -> deterministic timeout
- Scenario D: Plan -> approval pause -> continuation mismatch -> fail closed
- Scenario E: Full composition: Memory -> Agent -> Skill -> Tool -> Approval -> Evidence -> Verification -> Result
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from padiem_ai_core import (
    is_verification_satisfied,
    AgentExecutionBudget,
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
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


class MockValidator:
    async def verify(self, request: VerificationRequest, graph: EvidenceGraph) -> VerificationVerdict:
        return VerificationVerdict(
            verdict_id="verd_mock_1",
            claim_id=request.claim_id,
            validator_id="val:test:1",
            disposition=VerificationDisposition.VERIFIED,
            checked_evidence_ids=tuple(e.id for e in graph.sources),
            confidence=0.98,
            summary="Claim verified against evidence.",
        )


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


# ==============================================================================
# Scenario A: Plan -> Tool -> Approval -> Pause -> Resume -> Evidence -> Complete
# ==============================================================================

async def test_scenario_a_pause_resume_evidence_complete() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=(),
    )

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()
    async def calc_h(args: dict) -> dict:
        return {"result": 42}
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

    # Step 1: Initial run pauses
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
    res_1 = await runner.run(req)
    assert res_1.execution_result.metadata.status == RunStatus.PAUSED
    assert res_1.approval_pause is not None

    # Step 2: Resume with evidence and verification
    now = datetime.now(timezone.utc)
    decision = VerifiedApprovalDecision(
        decision_id="dec_scen_a",
        pause_id=res_1.approval_pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:lead",
        evidence_ref="session:scen_a",
        decided_at=now,
    )

    resumed_auth = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    ev_source = Evidence(
        id="ev_src_1",
        title="Calculator Specs",
        snippet="Standard calculator result documentation.",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="docs",
        source_type="web",
        url="https://docs.padiem.io/calc",
    )
    ev_claim = EvidenceClaim(
        id="clm_1",
        text="The calculation returned 42.",
        derivation=ClaimDerivation.OBSERVED,
    )
    ev_link = ClaimEvidenceLink(
        claim_id="clm_1",
        evidence_id="ev_src_1",
        relation=ClaimEvidenceRelation.SUPPORTS,
    )
    v_policy = TrustedVerificationPolicy(
        allowed_validator_ids=("val:test:1",),
    )

    resume_req = OrchestrationResumeRequest(
        pause=res_1.approval_pause,
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
        evidence_sources=(ev_source,),
        evidence_claims=(ev_claim,),
        evidence_links=(ev_link,),
        evidence_validator=MockValidator(),
        verification_policy=v_policy,
    )

    res_2 = await runner.resume(resume_req)
    assert res_2.execution_result.metadata.status == RunStatus.COMPLETED
    assert res_2.evidence_graph is not None
    assert len(res_2.claim_assessments) == 1
    assert is_verification_satisfied(res_2.claim_assessments[0]) is True

    events = [e.kind for e in res_2.events]
    assert OrchestrationEventKind.RUN_RESUMED in events
    assert OrchestrationEventKind.TOOL_COMPLETED in events
    assert OrchestrationEventKind.EVIDENCE_ATTACHED in events
    assert OrchestrationEventKind.VERIFICATION_COMPLETED in events
    assert OrchestrationEventKind.RUN_COMPLETED in events


# ==============================================================================
# Scenario B: Plan -> Tool -> Approval -> Cancel -> Resume Rejected
# ==============================================================================

async def test_scenario_b_pause_cancel_and_resume_rejected() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=(),
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def dummy_b(a: dict) -> dict:
        return {"r": 1}
    runtime.register(calc_spec, dummy_b)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )

    ctx = ExecutionContext(trace_id="tr_scen_b")
    exec_req = ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "Compute"},), trace_id="tr_scen_b")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

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
    pause = res_1.approval_pause
    assert pause is not None

    # Cancel the pause
    cancel_evts = runner.cancel_pause(pause, trace_id="tr_scen_b")
    assert cancel_evts[0].kind == OrchestrationEventKind.RUN_CANCELLED

    # Subsequent resume with denied decision
    decision = VerifiedApprovalDecision(
        decision_id="dec_cancel",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.DENIED,
        authority_ref="user:lead",
        evidence_ref="session:scen_b",
        decided_at=datetime.now(timezone.utc),
    )
    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(
            OrchestrationResumeRequest(
                pause=pause,
                decision=decision,
                execution_request=exec_req,
                context=ctx,
                app_id="b62",
            )
        )
    assert exc.value.code == "approval_denied"


# ==============================================================================
# Scenario C: Tool Timeout Before Approval (Deterministic Timeout)
# ==============================================================================

async def test_scenario_c_tool_timeout_before_approval() -> None:
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

    # Context timeout 1.0s vs 2.0s sleep
    ctx = ExecutionContext(trace_id="tr_scen_c", timeout_seconds=1.0)
    exec_req = ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "Compute"},), trace_id="tr_scen_c")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    # Tool timeout or orchestration timeout fails closed
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
# Scenario D: Plan -> Approval Pause -> Continuation Mismatch -> Fail Closed
# ==============================================================================

async def test_scenario_d_continuation_mismatch_fails_closed() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=(),
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def calc_h(args: dict) -> dict:
        return {"r": 1}
    runtime.register(calc_spec, calc_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )

    ctx = ExecutionContext(trace_id="tr_scen_d")
    exec_req = ExecutionRequest(agent=compiled.runtime_profile, messages=({"role": "user", "content": "Compute"},), trace_id="tr_scen_d")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    res = await runner.run(
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
    pause = res.approval_pause
    assert pause is not None

    # Mismatched continuation ID in decision
    decision_mismatch = VerifiedApprovalDecision(
        decision_id="dec_mismatch",
        pause_id="pause_forged_other",
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:lead",
        evidence_ref="session:scen_d",
        decided_at=datetime.now(timezone.utc),
    )

    with pytest.raises(OrchestrationError) as exc:
        await runner.resume(
            OrchestrationResumeRequest(
                pause=pause,
                decision=decision_mismatch,
                execution_request=exec_req,
                context=ctx,
                app_id="b62",
            )
        )
    assert exc.value.code == "continuation_identity_mismatch"


# ==============================================================================
# Scenario E: Full Composition (Memory -> Agent -> Skill -> Tool -> Approval -> Evidence -> Verification -> Result)
# ==============================================================================

async def test_scenario_e_full_composition_pipeline() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=(),
    )

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def calc_h(args: dict) -> dict:
        return {"result": 999}
    runtime.register(calc_spec, calc_h)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Finalize", depends_on=("s1",)),
        ),
    )

    ns = MemoryNamespace(app_id="b62", scope=MemoryScope.PROJECT, subject_id="sub_1")
    mem_item = RetrievedItem(
        id="mem_1",
        namespace="b62:project:sub_1",
        source_type="doc",
        provider="padiem",
        source_ref="doc:guidelines",
        content="Reference calculation guidelines.",
    )
    mem_auth = MemoryReadAuthorization(
        app_id="b62",
        readable_namespaces=(ns,),
    )

    ctx = ExecutionContext(trace_id="tr_scen_e", timeout_seconds=20.0)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute full composition"},),
        trace_id="tr_scen_e",
    )

    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    # 1. Run pipeline -> enters approval pause
    res_1 = await runner.run(
        OrchestrationRequest(
            execution_request=exec_req,
            context=ctx,
            app_id="b62",
            subject_id="sub_1",
            agent_definition=agent_def,
            compiled_agent_profile=compiled,
            agent_plan=plan,
            tool_authorization=auth_ctx,
            tool_runtime=runtime,
            memory_authorization=mem_auth,
            memory_items=(mem_item,),
            memory_read_policy=MemoryReadPolicy(allowed_scopes=(MemoryScope.PROJECT,)),
        )
    )
    assert res_1.execution_result.metadata.status == RunStatus.PAUSED
    assert res_1.approval_pause is not None

    # 2. Resume pipeline with approved decision
    now = datetime.now(timezone.utc)
    decision = VerifiedApprovalDecision(
        decision_id="dec_scen_e",
        pause_id=res_1.approval_pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="user:lead",
        evidence_ref="session:scen_e",
        decided_at=now,
    )
    resumed_auth = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
        user_confirmed_tools=("calc",),
    )

    ev_source = Evidence(
        id="ev_e_1",
        title="Full Calc Spec",
        snippet="Full composition verified output 999.",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="docs",
        source_type="web",
        url="https://docs.padiem.io/calc_full",
    )
    ev_claim = EvidenceClaim(
        id="clm_e_1",
        text="Output 999 is verified.",
        derivation=ClaimDerivation.OBSERVED,
    )
    ev_link = ClaimEvidenceLink(
        claim_id="clm_e_1",
        evidence_id="ev_e_1",
        relation=ClaimEvidenceRelation.SUPPORTS,
    )
    v_policy = TrustedVerificationPolicy(
        allowed_validator_ids=("val:test:1",),
    )

    res_2 = await runner.resume(
        OrchestrationResumeRequest(
            pause=res_1.approval_pause,
            decision=decision,
            execution_request=exec_req,
            context=ctx,
            app_id="b62",
            subject_id="sub_1",
            agent_definition=agent_def,
            compiled_agent_profile=compiled,
            agent_plan=plan,
            tool_authorization=resumed_auth,
            tool_runtime=runtime,
            now=now,
            evidence_sources=(ev_source,),
            evidence_claims=(ev_claim,),
            evidence_links=(ev_link,),
            evidence_validator=MockValidator(),
            verification_policy=v_policy,
        )
    )

    assert res_2.execution_result.metadata.status == RunStatus.COMPLETED
    assert res_2.continuation_state.status == ContinuationStatus.RESUMABLE
    assert len(res_2.claim_assessments) == 1
    assert is_verification_satisfied(res_2.claim_assessments[0]) is True
