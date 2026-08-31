import asyncio
import pytest

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    B14RouteMetadata,
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
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
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntimeBinding,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    TrustedSkillRuntimePolicy,
    UsageMetadata,
)


class FakeRuntime:
    def __init__(self, answer: str = "Test answer") -> None:
        self.answer = answer
        self.received_requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.received_requests.append(request)
        return ExecutionResult(
            answer=self.answer,
            route=B14RouteMetadata(selected_provider="test_prov", selected_model="test_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace_1",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class SlowRuntime:
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        await asyncio.sleep(5.0)
        return ExecutionResult(
            answer="too slow",
            route=B14RouteMetadata(),
            metadata=RunMetadata(trace_id="t", app_id="b62", agent_id="a", status=RunStatus.COMPLETED),
        )


class InMemoryIdempotencyAdapter(IdempotencyAdapter):
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], tuple[str, ExecutionResult]] = {}

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


def make_agent_profile(agent_id: str = "general_assistant", allowed_tools: tuple[str, ...] = ()) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="General Assistant",
        description="Handles general tasks safely.",
        system_instruction="You are a helpful assistant.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1024,
        allowed_tools=allowed_tools,
        max_steps=3,
    )


@pytest.mark.asyncio
async def test_context_only_run() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_ctx_1", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "hello"}], trace_id="trace_ctx_1")
    req = OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")

    result = await runner.run(req)

    assert result.execution_result.answer == "Test answer"
    assert result.context.trace_id == "trace_ctx_1"
    assert result.app_id == "b62"
    assert len(result.events) >= 4
    assert result.events[0].kind == OrchestrationEventKind.RUN_STARTED
    assert result.events[1].kind == OrchestrationEventKind.CONTEXT_PREPARED
    assert result.events[-1].kind == OrchestrationEventKind.RUN_COMPLETED


@pytest.mark.asyncio
async def test_memory_assisted_run_isolates_untrusted_reference() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_mem_1", timeout_seconds=5.0)
    exec_req = ExecutionRequest(
        agent=agent,
        messages=[{"role": "user", "content": "What is my preferred tone?"}],
        additional_system_context="Base system context.",
        trace_id="trace_mem_1",
    )
    ns = MemoryNamespace(app_id="b62", scope=MemoryScope.USER, subject_id="user_1")
    mem_auth = MemoryReadAuthorization(app_id="b62", readable_namespaces=(ns,))
    items = (
        RetrievedItem(id="m1", namespace=ns.key, source_type="memory", provider="local", source_ref="ref_1", content="User prefers formal tone"),
    )

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        subject_id="user_1",
        memory_authorization=mem_auth,
        memory_items=items,
    )

    result = await runner.run(req)
    assert result.execution_result.answer == "Test answer"

    # Verify that memory is fenced as UNTRUSTED_REFERENCE and not elevated to system prompt
    received = runtime.received_requests[0]
    assert "[UNTRUSTED_REFERENCE: Memory & Retrieved Context]" in received.additional_system_context
    assert "User prefers formal tone" in received.additional_system_context
    assert "[END_UNTRUSTED_REFERENCE]" in received.additional_system_context
    assert "Base system context." in received.additional_system_context

    # Verify event
    mem_events = [e for e in result.events if e.kind == OrchestrationEventKind.MEMORY_READ]
    assert len(mem_events) == 1
    assert mem_events[0].metadata["items_count"] == 1


@pytest.mark.asyncio
async def test_memory_namespace_mismatch_fails_closed() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_mem_err", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "hi"}], trace_id="trace_mem_err")
    other_ns = MemoryNamespace(app_id="other_app", scope=MemoryScope.USER, subject_id="user_other")
    mem_auth = MemoryReadAuthorization(app_id="other_app", readable_namespaces=(other_ns,))

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        memory_authorization=mem_auth,
        memory_items=(RetrievedItem(id="m1", namespace=other_ns.key, source_type="memory", provider="local", source_ref="ref_1", content="secret"),),
    )

    with pytest.raises(OrchestrationError) as exc:
        await runner.run(req)
    assert exc.value.code == "memory_authorization_mismatch"


@pytest.mark.asyncio
async def test_agent_with_skill_resolution_and_widening_prevention() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile(allowed_tools=("web_search",))
    ctx = ExecutionContext(trace_id="trace_sk_1", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "search doc"}], trace_id="trace_sk_1")

    skill_id = "skill:padiem:research@1"
    pkg = ReusableSkillPackage(
        skill_id=skill_id,
        publisher_id="publisher:padiem",
        description="Research skill",
        instruction="Do research",
        input_contract_ref="io:in@1",
        output_contract_ref="io:out@1",
        required_capabilities=("web_search",),
        allowed_tool_ids=("tool:padiem:web_search@1",),
        connector_requirement_ids=(),
        context_policy_ref="context:ref@1",
        model_policy_ref="model:auto@1",
        entitlement_ref=None,
    )
    reg = SkillRegistrySnapshot.from_packages((pkg,))
    inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(app_id="b62", subject_id="user_1", skill_id=skill_id, status=SkillInstallStatus.ENABLED),
    ))
    policy = TrustedSkillRuntimePolicy(
        context_policy_ref="context:ref@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="research",
        optimize_for="speed",
        max_tokens=512,
        max_steps_cap=2,
        context_policy={"mode": "reference"},
        model_policy={"model": "fast"},
        output_contract={"type": "text"},
        tool_bindings=(ToolRuntimeBinding("tool:padiem:web_search@1", "web_search"),),
        available_capabilities=frozenset({"web_search"}),
    )

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        subject_id="user_1",
        skill_id=skill_id,
        skill_registry=reg,
        skill_installations=inst,
        skill_runtime_policy=policy,
    )

    result = await runner.run(req)
    assert result.activated_skill is not None
    assert result.activated_skill.compiled.canonical_skill_id == skill_id

    # Verify authority widening rejection when a skill attempts to grant an unallowed tool
    widened_skill_id = "skill:padiem:widened@1"
    widened_pkg = ReusableSkillPackage(
        skill_id=widened_skill_id,
        publisher_id="publisher:padiem",
        description="Widened skill",
        instruction="Execute unauthorized admin",
        input_contract_ref="io:in@1",
        output_contract_ref="io:out@1",
        required_capabilities=("admin",),
        allowed_tool_ids=("tool:padiem:unauthorized_admin@1",),
        connector_requirement_ids=(),
        context_policy_ref="context:ref@1",
        model_policy_ref="model:auto@1",
        entitlement_ref=None,
    )
    widened_reg = SkillRegistrySnapshot.from_packages((widened_pkg,))
    widened_inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(app_id="b62", subject_id="user_1", skill_id=widened_skill_id, status=SkillInstallStatus.ENABLED),
    ))
    disallowed_policy = TrustedSkillRuntimePolicy(
        context_policy_ref="context:ref@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:out@1",
        task_type="research",
        optimize_for="speed",
        max_tokens=512,
        max_steps_cap=2,
        context_policy={"mode": "reference"},
        model_policy={"model": "fast"},
        output_contract={"type": "text"},
        tool_bindings=(ToolRuntimeBinding("tool:padiem:unauthorized_admin@1", "unauthorized_admin"),),
        available_capabilities=frozenset({"admin"}),
    )
    bad_req = OrchestrationRequest(
        execution_request=exec_req,  # agent only allows ("web_search",)
        context=ctx,
        app_id="b62",
        subject_id="user_1",
        skill_id=widened_skill_id,
        skill_registry=widened_reg,
        skill_installations=widened_inst,
        skill_runtime_policy=disallowed_policy,
    )
    with pytest.raises(OrchestrationError) as exc:
        await runner.run(bad_req)
    assert exc.value.code == "authority_widening_rejected"


@pytest.mark.asyncio
async def test_agent_with_evidence_and_grounded_citation() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_ev_1", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "analyze facts"}], trace_id="trace_ev_1")

    ev = Evidence(
        id="ev_src_1",
        title="Fact sheet",
        snippet="Verified fact statement",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url="https://example.com/facts",
    )
    claim = EvidenceClaim(id="c1", text="The statement is grounded", derivation=ClaimDerivation.GENERATED)
    link = ClaimEvidenceLink(claim_id="c1", evidence_id="ev_src_1", relation=ClaimEvidenceRelation.SUPPORTS)

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        evidence_sources=(ev,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )

    result = await runner.run(req)
    assert result.evidence_graph is not None
    assert len(result.claim_assessments) == 1
    assert len(result.grounded_citations) == 1
    assert result.grounded_citations[0].evidence_id == "ev_src_1"


@pytest.mark.asyncio
async def test_required_evidence_missing_fails_closed() -> None:
    runtime = FakeRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_ev_req", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "analyze"}], trace_id="trace_ev_req")

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        require_evidence=True,
    )

    with pytest.raises(OrchestrationError) as exc:
        await runner.run(req)
    assert exc.value.code == "required_evidence_missing"


@pytest.mark.asyncio
async def test_timeout_fails_closed() -> None:
    runtime = SlowRuntime()
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_timeout", timeout_seconds=1.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "hi"}], trace_id="trace_timeout")
    req = OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")

    with pytest.raises(OrchestrationError) as exc:
        await runner.run(req)
    assert exc.value.code == "orchestration_timeout"


@pytest.mark.asyncio
async def test_idempotency_replay_and_conflict() -> None:
    runtime = FakeRuntime()
    adapter = InMemoryIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_idem", idempotency_key="key_1", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "first call"}], trace_id="trace_idem")
    req = OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")

    res1 = await runner.run(req)
    assert res1.execution_result.answer == "Test answer"
    assert len(runtime.received_requests) == 1

    # Replay with same key and same payload
    res2 = await runner.run(req)
    assert res2.execution_result.answer == "Test answer"
    assert len(runtime.received_requests) == 1  # Did not execute underlying runtime again!

    # Conflict with same key and different payload
    diff_exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "different content"}], trace_id="trace_idem")
    diff_req = OrchestrationRequest(execution_request=diff_exec_req, context=ctx, app_id="b62")
    with pytest.raises(IdempotencyConflictError):
        await runner.run(diff_req)


@pytest.mark.asyncio
async def test_trace_id_conflict_fails_closed() -> None:
    agent = make_agent_profile()
    ctx = ExecutionContext(trace_id="trace_outer", timeout_seconds=5.0)
    exec_req = ExecutionRequest(agent=agent, messages=[{"role": "user", "content": "hi"}], trace_id="trace_inner")

    with pytest.raises(OrchestrationError) as exc:
        OrchestrationRequest(execution_request=exec_req, context=ctx, app_id="b62")
    assert exc.value.code == "trace_id_conflict"


@pytest.mark.asyncio
async def test_full_composition_pipeline() -> None:
    runtime = FakeRuntime("Full orchestration success.")
    adapter = InMemoryIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    agent = make_agent_profile(allowed_tools=("web_search",))
    ctx = ExecutionContext(trace_id="trace_full_1", timeout_seconds=5.0, idempotency_key="full_idem_1")
    exec_req = ExecutionRequest(
        agent=agent,
        messages=[{"role": "user", "content": "Synthesize market facts"}],
        additional_system_context="Base system rule.",
        trace_id="trace_full_1",
    )

    # Memory
    ns = MemoryNamespace(app_id="b62", scope=MemoryScope.USER, subject_id="user_full")
    mem_auth = MemoryReadAuthorization(app_id="b62", readable_namespaces=(ns,))
    items = (RetrievedItem(id="m_full", namespace=ns.key, source_type="memory", provider="local", source_ref="ref_1", content="Target market is APAC"),)

    # Plan
    plan = AgentPlan(
        agent_id="agent:padiem:general@1",
        steps=(AgentPlanStep(step_id="step_1", objective="Retrieve facts", tool_id="web_search"),),
    )

    # Evidence
    ev = Evidence(
        id="ev_apac",
        title="APAC Report",
        snippet="APAC revenue grew 30%",
        retrieved_at="2026-08-31T00:00:00Z",
        provider="web",
        source_type="web_page",
        url="https://example.com/apac",
    )
    claim = EvidenceClaim(id="claim_apac", text="APAC growth observed", derivation=ClaimDerivation.GENERATED)
    link = ClaimEvidenceLink(claim_id="claim_apac", evidence_id="ev_apac", relation=ClaimEvidenceRelation.SUPPORTS)

    req = OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        subject_id="user_full",
        memory_authorization=mem_auth,
        memory_items=items,
        agent_plan=plan,
        evidence_sources=(ev,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )

    result = await runner.run(req)

    assert result.execution_result.answer == "Full orchestration success."
    assert result.app_id == "b62"
    assert result.plan is not None
    assert len(result.plan.steps) == 1
    assert result.evidence_graph is not None
    assert len(result.claim_assessments) == 1
    assert len(result.grounded_citations) == 1

    # Check event ordering
    event_kinds = [e.kind for e in result.events]
    assert event_kinds[0] == OrchestrationEventKind.RUN_STARTED
    assert OrchestrationEventKind.CONTEXT_PREPARED in event_kinds
    assert OrchestrationEventKind.MEMORY_READ in event_kinds
    assert OrchestrationEventKind.PLAN_CREATED in event_kinds
    assert OrchestrationEventKind.TOOL_STARTED in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED in event_kinds
    assert OrchestrationEventKind.EVIDENCE_ATTACHED in event_kinds
    assert OrchestrationEventKind.VERIFICATION_COMPLETED in event_kinds
    assert event_kinds[-1] == OrchestrationEventKind.RUN_COMPLETED

    d = result.to_public_dict()
    assert d["execution"]["answer"] == "Full orchestration success."
    assert d["evidence"]["claim_count"] == 1
    assert len(d["events"]) == len(result.events)
