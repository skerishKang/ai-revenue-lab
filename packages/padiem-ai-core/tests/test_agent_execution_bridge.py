"""Tests for P01 Bounded AgentPlan to ToolRuntime Execution Bridge (#1219).

Verifies that validated finite AgentPlans execute through BoundedAgentRuntime and
ToolRuntime with strict authority non-widening, genuine tool event tracking,
and robust approval pause / timeout / cancellation handling.
"""

from __future__ import annotations

from padiem_ai_core.agent_runtime import AgentRuntimeError

import asyncio
from datetime import datetime, timezone
import pytest

from padiem_ai_core import (
    AgentExecutionBudget,
    AgentPlan,
    AgentPlanExecutor,
    AgentPlanStep,
    AgentProfile,
    AgentTerminalReason,
    ApprovalPolicy,
    BoundedAgentDefinition,
    CompiledAgentProfile,
    EffectiveToolResources,
    ErrorClass,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyAdapter,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationRunner,
    PlanBackedStepDriver,
    RunMetadata,
    RunStatus,
    ToolAuthorizationContext,
    ToolEvent,
    ToolExecutionResult,
    ToolInvocation,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntime,
    ToolRuntimeBinding,
    ToolRuntimeError,
    ToolSideEffect,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
    validate_agent_plan,
)


class MockCoreRuntime:
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            answer="fallback answer",
            metadata=RunMetadata(trace_id=request.trace_id or "tr", app_id="b62", agent_id=request.agent.id, status=RunStatus.COMPLETED),
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
        description="Agent for bridge execution test.",
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


def make_auth_ctx(
    agent_id: str,
    allowed_tools: tuple[str, ...] = ("calc",),
    user_confirmed: tuple[str, ...] = (),
) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id="b62",
        agent_id=agent_id,
        granted_auth_scopes=allowed_tools,
        user_confirmed_tools=user_confirmed,
    )


def make_orch_req(
    definition: BoundedAgentDefinition,
    compiled: CompiledAgentProfile,
    plan: AgentPlan,
    tool_runtime: ToolRuntime,
    auth_ctx: ToolAuthorizationContext,
    trace_id: str = "tr_bridge_1",
    timeout: float = 15.0,
    tool_arguments: dict | None = None,
) -> OrchestrationRequest:
    ctx = ExecutionContext(trace_id=trace_id, timeout_seconds=timeout)
    exec_req = ExecutionRequest(
        agent=compiled.runtime_profile,
        messages=({"role": "user", "content": "Compute result"},),
        trace_id=trace_id,
    )
    return OrchestrationRequest(
        execution_request=exec_req,
        context=ctx,
        app_id="b62",
        agent_definition=definition,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=tool_runtime,
        tool_arguments=tool_arguments,
    )


# ==============================================================================
# 1. Test A: Complete Step (No Tool Event)
# ==============================================================================

async def test_bridge_plan_complete_step_emits_no_tool_events() -> None:
    agent_def = make_agent_def(allowed_tools=())
    compiled = make_compiled_profile(agent_def)
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=())

    runtime = ToolRuntime()
    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Synthesize answer without tool"),
        ),
    )

    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_a")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    result = await runner.run(req)
    assert result.execution_result.answer == "Synthesize answer without tool"
    assert result.execution_result.metadata.tool_events == ()
    
    event_kinds = [e.kind for e in result.events]
    assert OrchestrationEventKind.TOOL_STARTED not in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED not in event_kinds
    assert OrchestrationEventKind.RUN_COMPLETED in event_kinds


# ==============================================================================
# 2. Test B: Authorized Tool Execution
# ==============================================================================

async def test_bridge_plan_authorized_tool_execution() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    
    async def calc_handler(arguments: dict) -> dict:
        return {"result": 42}

    runtime.register(calc_spec, calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(
            AgentPlanStep(step_id="s1", objective="Do addition", tool_id="calc"),
            AgentPlanStep(step_id="s2", objective="Summarize math result", depends_on=("s1",)),
        ),
    )

    tool_args = {"s1": {"expr": "40 + 2"}}
    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_b", tool_arguments=tool_args)
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    result = await runner.run(req)
    assert len(result.execution_result.metadata.tool_events) == 1
    assert result.execution_result.metadata.tool_events[0].tool_id == "calc"
    assert result.execution_result.metadata.tool_events[0].status == RunStatus.COMPLETED

    event_kinds = [e.kind for e in result.events]
    assert OrchestrationEventKind.TOOL_STARTED in event_kinds
    assert OrchestrationEventKind.TOOL_COMPLETED in event_kinds
    assert OrchestrationEventKind.RUN_COMPLETED in event_kinds


# ==============================================================================
# 3. Test C: Unauthorized Tool (Fails Closed)
# ==============================================================================

async def test_bridge_plan_unauthorized_tool_fails_closed() -> None:
    # Agent definition does not allow any tools
    agent_def = make_agent_def(allowed_tools=())
    compiled = make_compiled_profile(agent_def)
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=())

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def dummy_tool_handler(arguments: dict) -> dict:
        return {"result": 1}

    runtime.register(calc_spec, dummy_tool_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )

    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_c")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    with pytest.raises(Exception):
        await runner.run(req)


# ==============================================================================
# 4. Test D: Approval Required Path
# ==============================================================================

async def test_bridge_plan_approval_required_pauses() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",), user_confirmed=())

    calc_spec = make_calc_spec(tool_id="calc", approval_policy=ApprovalPolicy.USER_CONFIRMATION)
    runtime = ToolRuntime()
    async def dummy_tool_handler(arguments: dict) -> dict:
        return {"result": 1}

    runtime.register(calc_spec, dummy_tool_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do sensitive math", tool_id="calc"),),
    )

    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_d")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "approval_required"


# ==============================================================================
# 5. Test E & F: Tool / Agent Timeout
# ==============================================================================

async def test_bridge_plan_timeout_fails_closed() -> None:
    agent_def = make_agent_def(max_wall_seconds=1)
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    calc_spec = make_calc_spec(tool_id="calc", timeout_seconds=5.0)
    runtime = ToolRuntime()

    async def slow_handler(arguments: dict) -> dict:
        await asyncio.sleep(2.0)
        return {"result": 1}

    runtime.register(calc_spec, slow_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Slow step", tool_id="calc"),),
    )

    # Orchestration timeout is 0.5s
    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_timeout", timeout=1.0)
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    with pytest.raises(OrchestrationError) as exc_info:
        await runner.run(req)
    assert exc_info.value.code == "orchestration_timeout"


# ==============================================================================
# 6. Test G: Cancellation Propagation
# ==============================================================================

async def test_bridge_plan_cancellation_propagates_run_cancelled() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()

    async def cancel_handler(arguments: dict) -> dict:
        raise asyncio.CancelledError()

    runtime.register(calc_spec, cancel_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Cancel step", tool_id="calc"),),
    )

    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_cancel")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    with pytest.raises(asyncio.CancelledError):
        await runner.run(req)


# ==============================================================================
# 7. Test H & I: Max Steps and Budget Bounds
# ==============================================================================

async def test_bridge_plan_step_budget_exhaustion_terminates_cleanly() -> None:
    agent_def = make_agent_def(max_steps=2, max_tool_calls=1)
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    async def dummy_tool_handler(arguments: dict) -> dict:
        return {"result": 1}

    runtime.register(calc_spec, dummy_tool_handler)

    # Plan with 3 tool steps exceeds max_tool_calls budget of 1 -> validate_agent_plan raises AgentPlannerError
    with pytest.raises(ValueError):
        validate_agent_plan(
            AgentPlan(
                agent_id=agent_def.agent_id,
                steps=(
                    AgentPlanStep(step_id="s1", objective="Step 1", tool_id="calc"),
                    AgentPlanStep(step_id="s2", objective="Step 2", tool_id="calc", depends_on=("s1",)),
                ),
            ),
            definition=agent_def,
            compiled_profile=compiled,
        )


# ==============================================================================
# 8. Test J & K: Tool Event Integrity & Public Redaction
# ==============================================================================

async def test_bridge_plan_tool_event_integrity_and_redaction() -> None:
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    calc_spec = make_calc_spec(tool_id="calc")
    runtime = ToolRuntime()
    
    async def calc_handler(arguments: dict) -> dict:
        return {"secret_data": "sk-12345", "result": 100}

    runtime.register(calc_spec, calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Calculate secret", tool_id="calc"),),
    )

    req = make_orch_req(agent_def, compiled, plan, runtime, auth_ctx, trace_id="tr_plan_int")
    runner = OrchestrationRunner(runtime=MockCoreRuntime())

    result = await runner.run(req)
    pub_dict = result.to_public_dict()

    # Verify event counts match tool execution count
    tool_events = [e for e in pub_dict["events"] if e["kind"] in ("tool_started", "tool_completed", "tool_failed")]
    assert len(tool_events) == 2  # 1 started, 1 completed
    assert tool_events[0]["kind"] == "tool_started"
    assert tool_events[1]["kind"] == "tool_completed"

    # Verify secret_data in raw tool return is NOT in public events metadata
    for ev in pub_dict["events"]:
        meta_str = str(ev.get("metadata", {}))
        assert "sk-12345" not in meta_str
