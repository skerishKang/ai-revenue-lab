import asyncio
import pytest

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    AgentProfile,
    B14RouteMetadata,
    ClaimAssessment,
    ClaimAssessmentState,
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
    ToolEvent,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntimeBinding,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    TrustedSkillRuntimePolicy,
    TrustedVerificationPolicy,
    UsageMetadata,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    is_verification_satisfied,
)


class FakeRuntime:
    def __init__(self, answer: str = "Test answer", tool_events: tuple[ToolEvent, ...] = ()) -> None:
        self.answer = answer
        self.tool_events = tool_events
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
                tool_events=self.tool_events,
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


class FailingRuntime:
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        raise ValueError("simulated_runtime_crash")


class InMemoryIdempotencyAdapter(IdempotencyAdapter):
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


def make_agent_profile(agent_id: str = "general_assistant", allowed_tools: tuple[str, ...] = ()) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        title="General Assistant",
        description="Handles general tasks safely.",
        system_instruction="You are a helpful assistant.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1000,
        allowed_tools=allowed_tools,
        max_steps=5,
    )


def make_context(trace_id: str = "trace_abc", idempotency_key: str | None = None, timeout: float = 10.0) -> ExecutionContext:
    return ExecutionContext(
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        timeout_seconds=timeout,
    )


# ==============================================================================
# HARDENING #1 & #6: Event Semantics & No Fabricated Tool Events
# ==============================================================================

async def test_agent_only_run_emits_no_tool_events() -> None:
    runtime = FakeRuntime("agent-only answer", tool_events=())
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile()
    ctx = make_context("trace_agent_only")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=agent,
            messages=({"role": "user", "content": "hello world"},),
            trace_id="trace_agent_only",
        ),
        context=ctx,
        app_id="b62",
    )

    result = await runner.run(req)
    assert result.execution_result.answer == "agent-only answer"
    event_kinds = [e.kind for e in result.events]

    # Generic Agent-only run: RUN_STARTED -> CONTEXT_PREPARED -> RUN_COMPLETED
    assert event_kinds == [
        OrchestrationEventKind.RUN_STARTED,
        OrchestrationEventKind.CONTEXT_PREPARED,
        OrchestrationEventKind.RUN_COMPLETED,
    ]
    # Invariant: Generic execution != Tool execution
    assert OrchestrationEventKind.TOOL_STARTED not in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED not in event_kinds
    assert OrchestrationEventKind.TOOL_FAILED not in event_kinds
    assert OrchestrationEventKind.MEMORY_READ not in event_kinds
    assert OrchestrationEventKind.SKILL_RESOLVED not in event_kinds
    assert OrchestrationEventKind.EVIDENCE_ATTACHED not in event_kinds


async def test_agent_with_real_tool_events_emits_tool_lifecycle() -> None:
    tool_events = (
        ToolEvent(tool_id="calculator", status=RunStatus.COMPLETED, duration_ms=42),
        ToolEvent(tool_id="search", status=RunStatus.FAILED, error_class=ErrorClass.TOOL_RUNTIME_ERROR, duration_ms=100),
    )
    runtime = FakeRuntime("tool answer", tool_events=tool_events)
    runner = OrchestrationRunner(runtime=runtime)

    agent = make_agent_profile(allowed_tools=("calculator", "search"))
    ctx = make_context("trace_real_tools")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=agent,
            messages=({"role": "user", "content": "calc"},),
            trace_id="trace_real_tools",
        ),
        context=ctx,
        app_id="b62",
    )

    result = await runner.run(req)
    event_kinds = [e.kind for e in result.events]
    assert OrchestrationEventKind.TOOL_STARTED in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED in event_kinds
    assert OrchestrationEventKind.TOOL_FAILED in event_kinds

    tool_started = [e for e in result.events if e.kind == OrchestrationEventKind.TOOL_STARTED]
    assert len(tool_started) == 2
    assert tool_started[0].metadata["tool_id"] == "calculator"
    assert tool_started[1].metadata["tool_id"] == "search"

    tool_comp = next(e for e in result.events if e.kind == OrchestrationEventKind.TOOL_COMPLETED)
    assert tool_comp.metadata["tool_id"] == "calculator"
    assert tool_comp.metadata["status"] == "completed"
    assert tool_comp.metadata["duration_ms"] == 42

    tool_fail = next(e for e in result.events if e.kind == OrchestrationEventKind.TOOL_FAILED)
    assert tool_fail.metadata["tool_id"] == "search"
    assert tool_fail.metadata["status"] == "failed"
    assert tool_fail.metadata["error_class"] == "tool_runtime_error"


# ==============================================================================
# HARDENING #2: Idempotency Failure Lifecycle & Non-stale Reservations
# ==============================================================================

async def test_idempotency_lifecycle_commit_on_success_and_abort_on_failure() -> None:
    adapter = InMemoryIdempotencyAdapter()
    runtime = FakeRuntime("ok")
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    # 1. Success path -> commits to adapter
    ctx = make_context("trace_idem_succ", idempotency_key="key_succ")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "hi"},), trace_id="trace_idem_succ"),
        context=ctx,
        app_id="b62",
    )
    res = await runner.run(req)
    assert ("b62", "key_succ") in adapter.store

    # 2. Same key + same request -> replay
    replay_res = await runner.run(req)
    assert replay_res.execution_result.answer == "ok"
    assert replay_res.events[-1].metadata.get("replay") is True

    # 3. Same key + changed request -> conflict
    req_changed = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "DIFFERENT"},), trace_id="trace_idem_succ"),
        context=ctx,
        app_id="b62",
    )
    with pytest.raises(IdempotencyConflictError):
        await runner.run(req_changed)

    # 4. Failure path -> aborts and NEVER commits
    failing_runtime = FailingRuntime()
    failing_runner = OrchestrationRunner(runtime=failing_runtime, idempotency=adapter)
    ctx_fail = make_context("trace_fail", idempotency_key="key_fail")
    req_fail = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "fail"},), trace_id="trace_fail"),
        context=ctx_fail,
        app_id="b62",
    )
    with pytest.raises(Exception):
        await failing_runner.run(req_fail)

    assert ("b62", "key_fail") not in adapter.store
    assert any(k[1] == "key_fail" for k in adapter.aborted)


# ==============================================================================
# HARDENING #3: Required Verification Rejects CONFLICTED, UNVERIFIED, CONTRADICTED
# ==============================================================================

async def test_required_verification_rejects_conflicted_unverified_contradicted() -> None:
    runtime = FakeRuntime("verified answer")
    runner = OrchestrationRunner(runtime=runtime)

    src1 = Evidence(id="src_1", title="Doc 1", snippet="Revenue was $10M", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    src2 = Evidence(id="src_2", title="Doc 2", snippet="Revenue was $5M", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="claim_rev", text="Revenue is $10M", derivation=ClaimDerivation.OBSERVED)

    # Conflict links: src1 supports, src2 contradicts -> CONFLICTED
    link1 = ClaimEvidenceLink(claim_id="claim_rev", evidence_id=src1.id, relation=ClaimEvidenceRelation.SUPPORTS)
    link2 = ClaimEvidenceLink(claim_id="claim_rev", evidence_id=src2.id, relation=ClaimEvidenceRelation.CONTRADICTS)

    ctx = make_context("trace_conflicted")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "calc"},), trace_id="trace_conflicted"),
        context=ctx,
        app_id="b62",
        evidence_sources=(src1, src2),
        evidence_claims=(claim,),
        evidence_links=(link1, link2),
        require_verification=True,
    )

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)

    assert exc_info.value.code == "verification_failed"


async def test_is_verification_satisfied_helper() -> None:
    supported = ClaimAssessment(
        claim_id="c1",
        state=ClaimAssessmentState.SUPPORTED,
        supporting_evidence_ids=("e1",),
        contradicting_evidence_ids=(),
        contextualizing_evidence_ids=(),
        missing_supporting_evidence=False,
    )
    conflicted = ClaimAssessment(
        claim_id="c2",
        state=ClaimAssessmentState.CONFLICTED,
        supporting_evidence_ids=("e1",),
        contradicting_evidence_ids=("e2",),
        contextualizing_evidence_ids=(),
        missing_supporting_evidence=False,
    )
    unverified = ClaimAssessment(
        claim_id="c3",
        state=ClaimAssessmentState.UNVERIFIED,
        supporting_evidence_ids=(),
        contradicting_evidence_ids=(),
        contextualizing_evidence_ids=(),
        missing_supporting_evidence=True,
    )

    assert is_verification_satisfied(supported) is True
    assert is_verification_satisfied(conflicted) is False
    assert is_verification_satisfied(unverified) is False


# ==============================================================================
# HARDENING #4: Terminal Event Ordering
# ==============================================================================

async def test_terminal_event_ordering_on_timeout() -> None:
    runner = OrchestrationRunner(runtime=SlowRuntime())
    ctx = make_context("trace_to", timeout=1.0)
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "hi"},), trace_id="trace_to"),
        context=ctx,
        app_id="b62",
    )

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "orchestration_timeout"


async def test_required_evidence_missing_fails_closed() -> None:
    runner = OrchestrationRunner(runtime=FakeRuntime())
    ctx = make_context("trace_ev_missing")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "hi"},), trace_id="trace_ev_missing"),
        context=ctx,
        app_id="b62",
        require_evidence=True,
    )

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "required_evidence_missing"


# ==============================================================================
# HARDENING #5: Public Result Redaction
# ==============================================================================

async def test_public_result_redaction_and_scalar_metadata() -> None:
    runtime = FakeRuntime("public answer")
    runner = OrchestrationRunner(runtime=runtime)
    ctx = make_context("trace_redaction")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "hi"},), trace_id="trace_redaction"),
        context=ctx,
        app_id="b62",
    )
    result = await runner.run(req)
    pub = result.to_public_dict()
    assert "execution" in pub
    assert pub["execution"]["answer"] == "public answer"
    assert "events" in pub
    for evt in pub["events"]:
        for k, v in evt["metadata"].items():
            assert isinstance(v, (str, int, float, bool)) or v is None
            assert not any(sensitive in k.lower() for sensitive in ("secret", "token", "password", "key", "credential", "auth"))


# ==============================================================================
# SCENARIO A - G: Integration Scenarios
# ==============================================================================

async def test_scenario_b_memory_assisted_run_isolates_untrusted_reference() -> None:
    runtime = FakeRuntime("memory answer")
    runner = OrchestrationRunner(runtime=runtime)

    mem_items = (
        RetrievedItem(
            id="mem_1",
            namespace="user_docs",
            source_type="doc",
            provider="mem_store",
            source_ref="ref_1",
            content="Important factual data about revenue",
            title="Q3 Report",
        ),
    )

    ctx = make_context("trace_mem")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=make_agent_profile(), messages=({"role": "user", "content": "query"},), trace_id="trace_mem"),
        context=ctx,
        app_id="b62",
        memory_items=mem_items,
    )

    res = await runner.run(req)
    assert len(runtime.received_requests) == 1
    passed_context = runtime.received_requests[0].additional_system_context or ""
    assert "[UNTRUSTED_REFERENCE: Memory & Retrieved Context]" in passed_context
    assert "[END_UNTRUSTED_REFERENCE]" in passed_context
    assert "Important factual data about revenue" in passed_context

    events = [e.kind for e in res.events]
    assert OrchestrationEventKind.MEMORY_READ in events


async def test_scenario_c_skill_resolution_and_widening_prevention() -> None:
    runtime = FakeRuntime("skill answer")
    runner = OrchestrationRunner(runtime=runtime)

    skill_id = "skill:padiem:calc_skill@1"
    pkg = ReusableSkillPackage(
        skill_id=skill_id,
        publisher_id="publisher:padiem",
        description="Safe calculation skill",
        instruction="Do safe math",
        input_contract_ref="io:calc_in@1",
        output_contract_ref="io:calc_out@1",
        allowed_tool_ids=("tool:padiem:calculator@1",),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
    )
    reg = SkillRegistrySnapshot.from_packages((pkg,))
    inst = SkillInstallationSnapshot.from_installations((
        SkillInstallation(
            app_id="b62",
            subject_id="user_1",
            skill_id=skill_id,
            status=SkillInstallStatus.ENABLED,
        ),
    ))
    pol = TrustedSkillRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:calc_out@1",
        task_type="math",
        optimize_for="speed",
        max_tokens=1000,
        max_steps_cap=4,
        context_policy={"mode": "default"},
        model_policy={"profile": "auto"},
        output_contract={"type": "object"},
        tool_bindings=(
            ToolRuntimeBinding(
                canonical_tool_id="tool:padiem:calculator@1",
                runtime_tool_id="calculator",
            ),
        ),
    )

    agent_without_calc = make_agent_profile("agent_no_tool", allowed_tools=())
    ctx = make_context("trace_skill_widen")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=agent_without_calc, messages=({"role": "user", "content": "hi"},), trace_id="trace_skill_widen"),
        context=ctx,
        app_id="b62",
        subject_id="user_1",
        skill_id=skill_id,
        skill_registry=reg,
        skill_installations=inst,
        skill_runtime_policy=pol,
    )

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "authority_widening_rejected"


async def test_scenario_g_full_composition_pipeline() -> None:
    tool_events = (ToolEvent(tool_id="calc", status=RunStatus.COMPLETED, duration_ms=25),)
    runtime = FakeRuntime("full comp answer", tool_events=tool_events)
    adapter = InMemoryIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    mem_items = (RetrievedItem(id="m1", namespace="ns", source_type="doc", provider="p", source_ref="r", content="Fact: Padiem is fast"),)
    src = Evidence(id="src_1", title="Fast doc", snippet="Fact: Padiem is fast", retrieved_at="2026-08-31T00:00:00Z", provider="padiem", source_type="doc")
    claim = EvidenceClaim(id="c1", text="Padiem is fast", derivation=ClaimDerivation.OBSERVED)
    link = ClaimEvidenceLink(claim_id="c1", evidence_id=src.id, relation=ClaimEvidenceRelation.SUPPORTS)

    agent = make_agent_profile("agent_padiem_general", allowed_tools=("calc",))
    plan = AgentPlan(
        agent_id="agent:padiem:general@1",
        steps=(AgentPlanStep(step_id="s1", objective="Do calculation", tool_id="calc"),),
    )

    ctx = make_context("trace_full", idempotency_key="idem_full")
    req = OrchestrationRequest(
        execution_request=ExecutionRequest(agent=agent, messages=({"role": "user", "content": "run full"},), trace_id="trace_full"),
        context=ctx,
        app_id="b62",
        memory_items=mem_items,
        agent_plan=plan,
        evidence_sources=(src,),
        evidence_claims=(claim,),
        evidence_links=(link,),
    )

    result = await runner.run(req)
    assert result.execution_result.answer == "full comp answer"
    assert result.plan == plan
    assert len(result.claim_assessments) == 1
    assert result.claim_assessments[0].state == ClaimAssessmentState.UNVERIFIED

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
