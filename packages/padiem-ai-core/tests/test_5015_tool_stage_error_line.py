"""#5015 — a policy-blocked tool names its bounded stage code on the error line.

The Engine's NDJSON error line is what the Claw adapter classifies. When a
bounded-run tool is blocked, the terminal reason alone
(``authorization_denied``) does not say *which* stage blocked it: a missing
verification owner, an unconfigured integration and a request-creation fault
would all collapse into one generic code. The orchestration runner must fail
with the tool's own closed stage code and emit a matching ``tool_failed``
event so the cause survives to every downstream lane.
"""
from __future__ import annotations

import pytest

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    ApprovalPolicy,
    ExecutionContext,
    ExecutionRequest,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationRunner,
    RunStatus,
    ToolRuntime,
    ToolSideEffect,
    ToolSpec,
)
from test_approval_pause_semantics import (
    MockCoreRuntime,
    make_agent_def,
    make_auth_ctx,
    make_compiled_profile,
)


def _foreign_owned_spec(tool_id: str = "calc") -> ToolSpec:
    # The owner is neither "core" nor the authorizing app ("b62"), so the
    # tool runtime blocks the call as tool_owner_mismatch before any handler
    # runs -- the exact shape a missing-owner production failure has.
    return ToolSpec(
        id=tool_id,
        title="Foreign tool",
        description="Owned by another application boundary",
        owner="other_app",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={"type": "object"},
        output_contract={"type": "object"},
        timeout_seconds=10.0,
    )


def _blocked_request():
    agent_def = make_agent_def()
    compiled = make_compiled_profile(agent_def, runtime_tool_id="calc")
    auth_ctx = make_auth_ctx(agent_id=compiled.runtime_profile.id, allowed_tools=("calc",))

    runtime = ToolRuntime()

    async def calc_handler(arguments: dict) -> dict:
        return {"result": 42}

    runtime.register(_foreign_owned_spec(), calc_handler)

    plan = AgentPlan(
        agent_id=agent_def.agent_id,
        steps=(AgentPlanStep(step_id="s1", objective="Do math", tool_id="calc"),),
    )
    return OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=compiled.runtime_profile,
            messages=({"role": "user", "content": "Compute result"},),
            trace_id="tr_stage_5015",
        ),
        context=ExecutionContext(trace_id="tr_stage_5015", timeout_seconds=15.0),
        app_id="b62",
        agent_definition=agent_def,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth_ctx,
        tool_runtime=runtime,
    )


async def test_policy_blocked_tool_stage_code_rides_the_error_line() -> None:
    runner = OrchestrationRunner(runtime=MockCoreRuntime())
    with pytest.raises(OrchestrationError) as err:
        await runner.run(_blocked_request())
    assert err.value.code == "tool_owner_mismatch", (
        "the bounded tool stage must outrank the generic terminal reason"
    )


async def test_policy_blocked_tool_emits_a_matching_failure_event() -> None:
    seen = []
    runner = OrchestrationRunner(runtime=MockCoreRuntime(), event_sink=seen.append)
    with pytest.raises(OrchestrationError):
        await runner.run(_blocked_request())

    failed = [
        event for event in seen
        if event.kind is OrchestrationEventKind.TOOL_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].metadata["tool_id"] == "calc"
    assert failed[0].metadata["status"] == RunStatus.POLICY_BLOCKED.value
    assert failed[0].metadata["error_code"] == "tool_owner_mismatch"
    assert failed[0].metadata["error_class"] == "policy_blocked"

    run_failed = [
        event for event in seen
        if event.kind is OrchestrationEventKind.RUN_FAILED
    ]
    assert len(run_failed) == 1
    assert run_failed[0].metadata == {"error": "authorization_denied"}