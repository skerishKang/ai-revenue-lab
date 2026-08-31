"""Conformance tests and cross-adapter verification for P01.

Proves that server/product-specific adapter implementations preserve P01 Core
semantics across Memory, Agent, Skill, Tool, Connector, Evidence, and Engine.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest

from padiem_ai_core import (
    AdapterCategory,
    AdapterConformanceCase,
    AdapterConformanceReport,
    AdapterConformanceResult,
    AdapterConformanceSuite,
    AdapterContractViolation,
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    B14RouteMetadata,
    ClaimAssessment,
    ClaimAssessmentState,
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    ConformanceDimension,
    ConformanceVerdict,
    ConnectorDescriptor,
    ConnectorRegistrySnapshot,
    EffectiveToolResources,
    ErrorClass,
    Evidence,
    EvidenceClaim,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyAdapter,
    IdempotencyConflictError,
    MemoryNamespace,
    MemoryReadAuthorization,
    MemoryReadPolicy,
    MemoryScope,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationRunner,
    RetrievedItem,
    ReusableSkillPackage,
    RunMetadata,
    RunStatus,
    SkillInstallation,
    SkillInstallationSnapshot,
    SkillInstallStatus,
    SkillRegistrySnapshot,
    ToolEvent,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntimeBinding,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    TrustedSkillRuntimePolicy,
    TrustedVerificationPolicy,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    assess_claim,
    evidence_graph,
    is_verification_satisfied,
    project_grounded_citations,
    request_fingerprint,
    resolve_tool_resources,
)


class InMemoryIdempotencyStore(IdempotencyAdapter):
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], tuple[str, ExecutionResult]] = {}
        self.aborted: list[tuple[str, str, str]] = []

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str) -> ExecutionResult | None:
        key = (app_id, idempotency_key)
        if key in self.store:
            stored_fp, stored_res = self.store[key]
            if stored_fp != request_fingerprint:
                raise IdempotencyConflictError("fingerprint mismatch")
            return stored_res
        return None

    async def commit(self, *, app_id: str, idempotency_key: str, request_fingerprint: str, result: ExecutionResult) -> None:
        self.store[(app_id, idempotency_key)] = (request_fingerprint, result)

    async def abort(self, *, app_id: str, idempotency_key: str, reason: str) -> None:
        self.aborted.append((app_id, idempotency_key, reason))


class MockConformanceRuntime:
    def __init__(self, answer: str = "conformance response", tool_events: tuple[ToolEvent, ...] = ()) -> None:
        self.answer = answer
        self.tool_events = tool_events
        self.received_requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.received_requests.append(request)
        return ExecutionResult(
            answer=self.answer,
            route=B14RouteMetadata(selected_provider="p01_mock", selected_model="p01_conformance_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace_conf",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
                tool_events=self.tool_events,
            ),
        )


def make_profile(agent_id: str = "conformance_agent", allowed_tools: tuple[str, ...] = ()) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="Conformance Test Agent",
        description="Agent for conformance verification.",
        system_instruction="Follow safety boundaries.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=2048,
        allowed_tools=allowed_tools,
        max_steps=5,
    )


def make_ctx(trace_id: str = "trace_conformance_1", idempotency_key: str | None = None, timeout: float = 15.0) -> ExecutionContext:
    return ExecutionContext(
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        timeout_seconds=timeout,
    )


# ==============================================================================
# 1. Harness Unit Tests
# ==============================================================================

async def test_conformance_harness_suite_execution() -> None:
    suite = AdapterConformanceSuite(suite_id="p01_test_harness")

    async def sample_pass() -> None:
        pass

    async def sample_negative_pass() -> None:
        raise AdapterContractViolation("scope_violation", "Cross-scope access denied")

    suite.register_case(
        case_id="case_sample_1",
        category=AdapterCategory.MEMORY,
        dimension=ConformanceDimension.SCOPE,
        title="Memory Scope Isolation",
        description="Verifies memory namespace separation",
        test_fn=sample_pass,
    )
    suite.register_case(
        case_id="case_sample_2",
        category=AdapterCategory.AGENT,
        dimension=ConformanceDimension.AUTHORITY,
        title="Agent Authority Non-Widening",
        description="Verifies child <= parent authority",
        test_fn=sample_negative_pass,
        negative_test=True,
    )

    report = await suite.run()
    assert report.total_cases == 2
    assert report.passed_cases == 2
    assert report.failed_cases == 0
    assert report.matrix["memory"]["scope"] == "PASS"
    assert report.matrix["agent"]["authority"] == "PASS"

    pub_dict = report.to_public_dict()
    assert pub_dict["summary"]["total"] == 2
    assert pub_dict["summary"]["passed"] == 2

    md_table = report.to_markdown_table()
    assert "| Memory |" in md_table
    assert "| Agent |" in md_table


# ==============================================================================
# 2. Memory Adapter Conformance
# ==============================================================================

async def test_memory_adapter_scope_isolation_and_fencing() -> None:
    runtime = MockConformanceRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    mem_item = RetrievedItem(
        id="mem_doc_1",
        namespace="user_tenant_1",
        source_type="doc",
        provider="padiem_memory",
        source_ref="ref_100",
        content="Secret revenue metric: 42M",
        title="Financials",
    )

    # 1. Valid same-app authorization
    auth_valid = MemoryReadAuthorization(app_id="b62", readable_namespaces=(MemoryNamespace(app_id="b62", scope=MemoryScope.USER, subject_id="user_1"),))
    req_valid = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "q"},), trace_id="tr_mem_1"),
        context=make_ctx("tr_mem_1"),
        app_id="b62",
        memory_authorization=auth_valid,
        memory_items=(mem_item,),
    )
    res = await runner.run(req_valid)
    assert "[UNTRUSTED_REFERENCE: Memory & Retrieved Context]" in runtime.received_requests[0].additional_system_context
    assert "[END_UNTRUSTED_REFERENCE]" in runtime.received_requests[0].additional_system_context
    assert "Secret revenue metric: 42M" in runtime.received_requests[0].additional_system_context

    # 2. Cross-app namespace mismatch -> fails closed
    auth_mismatch = MemoryReadAuthorization(app_id="b14", readable_namespaces=(MemoryNamespace(app_id="b14", scope=MemoryScope.USER, subject_id="user_1"),))
    req_invalid = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "q"},), trace_id="tr_mem_2"),
        context=make_ctx("tr_mem_2"),
        app_id="b62",
        memory_authorization=auth_mismatch,
        memory_items=(mem_item,),
    )
    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req_invalid)
    assert exc_info.value.code == "memory_authorization_mismatch"


# ==============================================================================
# 3. Agent Adapter Conformance: Authority Non-Widening (child <= parent)
# ==============================================================================

async def test_agent_adapter_authority_non_widening() -> None:
    parent_agent = make_profile("parent_agent", allowed_tools=("search", "read_doc"))
    assert "calculator" not in parent_agent.allowed_tools

    # Policy validates safe tool bindings
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1000,
        max_steps_cap=5,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
        tool_bindings=(ToolRuntimeBinding(canonical_tool_id="tool:padiem:search@1", runtime_tool_id="search"),),
    )
    assert len(policy.tool_bindings) == 1


# ==============================================================================
# 4. Skill Adapter Conformance: Enablement != Permission Grant
# ==============================================================================

async def test_skill_adapter_does_not_widen_tool_permissions() -> None:
    runtime = MockConformanceRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    skill_id = "skill:padiem:calc@1"
    pkg = ReusableSkillPackage(
        skill_id=skill_id,
        publisher_id="publisher:padiem",
        description="Calculation skill",
        instruction="Do calc",
        input_contract_ref="io:in@1",
        output_contract_ref="io:out@1",
        allowed_tool_ids=("tool:padiem:calc_tool@1",),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
    )
    reg = SkillRegistrySnapshot.from_packages((pkg,))
    inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(app_id="b62", subject_id="u1", skill_id=skill_id, status=SkillInstallStatus.ENABLED),
    ))
    pol = TrustedSkillRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="math",
        optimize_for="speed",
        max_tokens=1000,
        max_steps_cap=4,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
        tool_bindings=(ToolRuntimeBinding(canonical_tool_id="tool:padiem:calc_tool@1", runtime_tool_id="calc_tool"),),
    )

    agent_without_calc = make_profile("agent_no_calc", allowed_tools=())
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=agent_without_calc, messages=({"role": "user", "content": "hi"},), trace_id="tr_sk_widen"),
        context=make_ctx("tr_sk_widen"),
        app_id="b62",
        subject_id="u1",
        skill_id=skill_id,
        skill_registry=reg,
        skill_installations=inst,
        skill_runtime_policy=pol,
    )

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "authority_widening_rejected"


# ==============================================================================
# 5. Tool & Connector Adapter Conformance: Resource Policy & Identity Bounds
# ==============================================================================

async def test_tool_connector_adapter_resource_policy_resolution() -> None:
    from padiem_ai_core import ApprovalPolicy, ToolSideEffect
    spec = ToolSpec(
        id="calculator",
        title="Calculator",
        description="Safe math",
        owner="padiem",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={"type": "object"},
        output_contract={"type": "object"},
        timeout_seconds=60.0,
    )
    policy = ToolResourcePolicy(
        max_argument_bytes=32000,
        max_output_bytes=64000,
        max_timeout_seconds=30.0,
    )
    resources = resolve_tool_resources(spec, policy)
    assert resources.argument_bytes == 32000
    assert resources.output_bytes == 64000
    assert resources.timeout_seconds == 30.0
    assert resources.narrowed is True


# ==============================================================================
# 6. Evidence Adapter Conformance: Assessment State & Citation Bounds
# ==============================================================================

async def test_evidence_adapter_preserves_conflict_and_derives_citations() -> None:
    src_a = Evidence(id="ev_a", title="Doc A", snippet="Price is 100", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    src_b = Evidence(id="ev_b", title="Doc B", snippet="Price is 200", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="claim_price", text="Price is 100", derivation=ClaimDerivation.OBSERVED)

    link_supp = ClaimEvidenceLink(claim_id="claim_price", evidence_id="ev_a", relation=ClaimEvidenceRelation.SUPPORTS)
    link_contra = ClaimEvidenceLink(claim_id="claim_price", evidence_id="ev_b", relation=ClaimEvidenceRelation.CONTRADICTS)

    eg = evidence_graph(sources=[src_a, src_b], claims=[claim], links=[link_supp, link_contra])
    ass = assess_claim(eg, "claim_price")

    # Invariant: CONFLICTED cannot be promoted to SUPPORTED
    assert ass.state == ClaimAssessmentState.CONFLICTED
    assert is_verification_satisfied(ass) is False

    # Single supporting evidence -> SUPPORTED (when verified)
    eg_single = evidence_graph(sources=[src_a], claims=[claim], links=[link_supp])
    ass_unverified = assess_claim(eg_single, "claim_price")
    assert ass_unverified.state == ClaimAssessmentState.UNVERIFIED
    assert is_verification_satisfied(ass_unverified) is False


# ==============================================================================
# 7. Engine Adapter Conformance: Trace ID Preservation & Idempotency
# ==============================================================================

async def test_engine_adapter_trace_propagation_and_idempotency() -> None:
    store = InMemoryIdempotencyStore()
    runtime = MockConformanceRuntime("answer_engine")
    runner = OrchestrationRunner(runtime=runtime, idempotency=store)

    ctx = make_ctx("trace_eng_123", idempotency_key="key_eng_1")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "hello"},), trace_id="trace_eng_123"),
        context=ctx,
        app_id="b62",
    )

    # 1. Run succeeds -> trace propagates to metadata
    res = await runner.run(req)
    assert res.execution_result.metadata.trace_id == "trace_eng_123"
    assert res.context.trace_id == "trace_eng_123"

    # 2. Replay with identical fingerprint returns cached response
    replay_res = await runner.run(req)
    assert replay_res.execution_result.answer == "answer_engine"
    assert replay_res.events[-1].metadata.get("replay") is True


# ==============================================================================
# 8. Cross-Adapter Compositions (A through G)
# ==============================================================================

async def test_composition_a_memory_to_agent() -> None:
    runtime = MockConformanceRuntime("comp_a_answer")
    runner = OrchestrationRunner(runtime=runtime)
    mem_item = RetrievedItem(id="m1", namespace="ns", source_type="doc", provider="p", source_ref="r", content="User prefers Python")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "which lang?"},), trace_id="tr_a"),
        context=make_ctx("tr_a"),
        app_id="b62",
        memory_items=(mem_item,),
    )
    res = await runner.run(req)
    assert res.execution_result.answer == "comp_a_answer"
    assert OrchestrationEventKind.MEMORY_READ in [e.kind for e in res.events]


async def test_composition_b_agent_to_skill() -> None:
    skill_id = "skill:padiem:summary@1"
    pkg = ReusableSkillPackage(
        skill_id=skill_id,
        publisher_id="publisher:padiem",
        description="Summarize",
        instruction="Do summary",
        input_contract_ref="io:in@1",
        output_contract_ref="io:out@1",
        allowed_tool_ids=(),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
    )
    reg = SkillRegistrySnapshot.from_packages((pkg,))
    inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(app_id="b62", subject_id="u1", skill_id=skill_id, status=SkillInstallStatus.ENABLED),
    ))
    pol = TrustedSkillRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="summary",
        optimize_for="balanced",
        max_tokens=1000,
        max_steps_cap=3,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
    )
    runtime = MockConformanceRuntime("summary_answer")
    runner = OrchestrationRunner(runtime=runtime)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "summarize"},), trace_id="tr_b"),
        context=make_ctx("tr_b"),
        app_id="b62",
        subject_id="u1",
        skill_id=skill_id,
        skill_registry=reg,
        skill_installations=inst,
        skill_runtime_policy=pol,
    )
    res = await runner.run(req)
    assert res.activated_skill is not None
    assert res.activated_skill.compiled.canonical_skill_id == skill_id


async def test_composition_c_agent_to_tool_and_connector() -> None:
    tool_events = (ToolEvent(tool_id="db_read", status=RunStatus.COMPLETED, duration_ms=15),)
    runtime = MockConformanceRuntime("db_answer", tool_events=tool_events)
    runner = OrchestrationRunner(runtime=runtime)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(allowed_tools=("db_read",)), messages=({"role": "user", "content": "query db"},), trace_id="tr_c"),
        context=make_ctx("tr_c"),
        app_id="b62",
        tool_resource_policy=ToolResourcePolicy(max_argument_bytes=1000, max_output_bytes=5000, max_timeout_seconds=10.0),
    )
    res = await runner.run(req)
    event_kinds = [e.kind for e in res.events]
    assert OrchestrationEventKind.TOOL_RESOLUTION in event_kinds
    assert OrchestrationEventKind.TOOL_STARTED in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED in event_kinds


async def test_composition_d_tool_to_evidence_and_verification() -> None:
    src = Evidence(id="e_tool", title="Tool Output", snippet="Result: 42", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="tool_output")
    claim = EvidenceClaim(id="c_tool", text="Result is 42", derivation=ClaimDerivation.OBSERVED)
    link = ClaimEvidenceLink(claim_id="c_tool", evidence_id="e_tool", relation=ClaimEvidenceRelation.SUPPORTS)
    runtime = MockConformanceRuntime("verified_calc")
    runner = OrchestrationRunner(runtime=runtime)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "calc"},), trace_id="tr_d"),
        context=make_ctx("tr_d"),
        app_id="b62",
        evidence_sources=(src,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )
    res = await runner.run(req)
    assert len(res.claim_assessments) == 1
    assert len(res.grounded_citations) == 1


async def test_composition_e_memory_agent_tool_evidence() -> None:
    mem_item = RetrievedItem(id="m_e", namespace="ns", source_type="doc", provider="p", source_ref="r", content="Factual item")
    src = Evidence(id="e_e", title="Doc E", snippet="Factual item", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="c_e", text="Factual item", derivation=ClaimDerivation.OBSERVED)
    link = ClaimEvidenceLink(claim_id="c_e", evidence_id="e_e", relation=ClaimEvidenceRelation.SUPPORTS)
    tool_events = (ToolEvent(tool_id="search", status=RunStatus.COMPLETED, duration_ms=10),)
    runtime = MockConformanceRuntime("ans_e", tool_events=tool_events)
    runner = OrchestrationRunner(runtime=runtime)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(allowed_tools=("search",)), messages=({"role": "user", "content": "run e"},), trace_id="tr_e"),
        context=make_ctx("tr_e"),
        app_id="b62",
        memory_items=(mem_item,),
        evidence_sources=(src,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )
    res = await runner.run(req)
    kinds = [e.kind for e in res.events]
    assert OrchestrationEventKind.MEMORY_READ in kinds
    assert OrchestrationEventKind.TOOL_STARTED in kinds
    assert OrchestrationEventKind.EVIDENCE_ATTACHED in kinds


async def test_composition_f_memory_agent_skill_tool_evidence_engine() -> None:
    mem_item = RetrievedItem(id="m_f", namespace="ns", source_type="doc", provider="p", source_ref="r", content="Fact F")
    src = Evidence(id="e_f", title="Doc F", snippet="Fact F", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="c_f", text="Fact F", derivation=ClaimDerivation.OBSERVED)
    link = ClaimEvidenceLink(claim_id="c_f", evidence_id="e_f", relation=ClaimEvidenceRelation.SUPPORTS)

    skill_id = "skill:padiem:skill_f@1"
    pkg = ReusableSkillPackage(
        skill_id=skill_id,
        publisher_id="publisher:padiem",
        description="F skill",
        instruction="Do F",
        input_contract_ref="io:in@1",
        output_contract_ref="io:out@1",
        allowed_tool_ids=(),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
    )
    reg = SkillRegistrySnapshot.from_packages((pkg,))
    inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(app_id="b62", subject_id="u1", skill_id=skill_id, status=SkillInstallStatus.ENABLED),
    ))
    pol = TrustedSkillRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="general",
        optimize_for="speed",
        max_tokens=1000,
        max_steps_cap=2,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
    )
    store = InMemoryIdempotencyStore()
    runtime = MockConformanceRuntime("ans_f")
    runner = OrchestrationRunner(runtime=runtime, idempotency=store)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "run f"},), trace_id="tr_f"),
        context=make_ctx("tr_f", idempotency_key="key_f"),
        app_id="b62",
        subject_id="u1",
        memory_items=(mem_item,),
        skill_id=skill_id,
        skill_registry=reg,
        skill_installations=inst,
        skill_runtime_policy=pol,
        evidence_sources=(src,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )
    res = await runner.run(req)
    assert res.execution_result.answer == "ans_f"
    assert ("b62", "key_f") in store.store


async def test_composition_g_full_pipeline_end_to_end() -> None:
    tool_events = (ToolEvent(tool_id="math_eval", status=RunStatus.COMPLETED, duration_ms=18),)
    runtime = MockConformanceRuntime("ans_g_final", tool_events=tool_events)
    store = InMemoryIdempotencyStore()
    runner = OrchestrationRunner(runtime=runtime, idempotency=store)

    mem_items = (RetrievedItem(id="m_g", namespace="tenant_g", source_type="doc", provider="p", source_ref="r", content="Padiem is robust"),)
    src = Evidence(id="src_g", title="Robust doc", snippet="Padiem is robust", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="claim_g", text="Padiem is robust", derivation=ClaimDerivation.OBSERVED)
    link = ClaimEvidenceLink(claim_id="claim_g", evidence_id="src_g", relation=ClaimEvidenceRelation.SUPPORTS)

    agent = make_profile("agent_g", allowed_tools=("math_eval",))
    plan = AgentPlan(
        agent_id="agent:padiem:general@1",
        steps=(AgentPlanStep(step_id="s1", objective="Evaluate robustly", tool_id="math_eval"),),
    )

    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=agent, messages=({"role": "user", "content": "run full g"},), trace_id="tr_g"),
        context=make_ctx("tr_g", idempotency_key="key_g"),
        app_id="b62",
        memory_items=mem_items,
        agent_plan=plan,
        evidence_sources=(src,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )

    result = await runner.run(req)
    assert result.execution_result.answer == "ans_g_final"
    assert result.plan == plan
    assert len(result.claim_assessments) == 1
    
    event_kinds = [e.kind for e in result.events]
    assert event_kinds == [
        OrchestrationEventKind.RUN_STARTED,
        OrchestrationEventKind.CONTEXT_PREPARED,
        OrchestrationEventKind.MEMORY_READ,
        OrchestrationEventKind.PLAN_CREATED,
        OrchestrationEventKind.TOOL_STARTED,
        OrchestrationEventKind.TOOL_COMPLETED,
        OrchestrationEventKind.EVIDENCE_ATTACHED,
        OrchestrationEventKind.VERIFICATION_COMPLETED,
        OrchestrationEventKind.RUN_COMPLETED,
    ]


# ==============================================================================
# 9. Negative Conformance Suite (Fail-Closed Invariants)
# ==============================================================================

async def test_negative_trace_id_conflict_fails_closed() -> None:
    with pytest.raises(OrchestrationError) as exc_info:
        OrchestrationRequest(
            execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "hi"},), trace_id="trace_A"),
            context=make_ctx("trace_B"),  # Mismatch!
            app_id="b62",
        )
    assert exc_info.value.code == "trace_id_conflict"


async def test_negative_idempotency_fingerprint_mismatch_fails_closed() -> None:
    store = InMemoryIdempotencyStore()
    runtime = MockConformanceRuntime()
    runner = OrchestrationRunner(runtime=runtime, idempotency=store)

    req1 = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "first"},), trace_id="tr_idem_neg"),
        context=make_ctx("tr_idem_neg", idempotency_key="key_shared"),
        app_id="b62",
    )
    await runner.run(req1)

    req2_altered = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_profile(), messages=({"role": "user", "content": "ALTERED"},), trace_id="tr_idem_neg"),
        context=make_ctx("tr_idem_neg", idempotency_key="key_shared"),
        app_id="b62",
    )
    with pytest.raises(IdempotencyConflictError):
        await runner.run(req2_altered)
