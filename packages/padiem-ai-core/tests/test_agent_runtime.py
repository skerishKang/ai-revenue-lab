import asyncio

import pytest

from padiem_ai_core.agent_definition import (
    AgentExecutionBudget,
    AgentTerminalReason,
    BoundedAgentDefinition,
)
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.agent_runtime import (
    AgentRunRequest,
    AgentRuntimeError,
    AgentStepDecision,
    BoundedAgentRuntime,
)
from padiem_ai_core.contracts import (
    ApprovalPolicy,
    RunStatus,
    ToolSideEffect,
    ToolSpec,
)
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
)


class SequenceDriver:
    def __init__(self, *decisions):
        self._decisions = list(decisions)
        self.contexts = []

    async def next_step(self, context, compiled_profile):
        self.contexts.append(context)
        if not self._decisions:
            raise RuntimeError("no decision configured")
        return self._decisions.pop(0)


class MutableClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class AdvancingDriver:
    def __init__(self, clock):
        self.clock = clock

    async def next_step(self, context, compiled_profile):
        self.clock.value = 2.0
        return AgentStepDecision.complete("late answer")


def make_definition(**overrides):
    values = {
        "agent_id": "agent:padiem:researcher@1",
        "publisher_id": "publisher:padiem",
        "title": "Researcher",
        "description": "Bounded research Agent.",
        "instruction": "Use tools only when required.",
        "output_contract_ref": "io:answer@1",
        "allowed_tool_ids": ("tool:padiem:lookup@1",),
        "required_capabilities": ("chat",),
        "context_policy_ref": "context:default@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": AgentExecutionBudget(
            max_steps=4,
            max_tool_calls=3,
            max_skill_calls=0,
            max_wall_seconds=60,
        ),
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def compile_definition(definition):
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:answer@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=800,
        max_steps_cap=4,
        context_policy={},
        model_policy={"model": "b14/auto"},
        output_contract={"type": "text"},
        tool_bindings=(
            ToolRuntimeBinding(
                canonical_tool_id="tool:padiem:lookup@1",
                runtime_tool_id="tool.lookup",
            ),
        ),
        available_capabilities=frozenset({"chat"}),
    )
    return compile_agent_profile(definition, policy)


def make_authorization(compiled, **overrides):
    values = {
        "app_id": "test.app",
        "agent_id": compiled.runtime_profile.id,
    }
    values.update(overrides)
    return ToolAuthorizationContext(**values)


def make_tool_runtime(*, approval_policy=ApprovalPolicy.NOT_REQUIRED):
    runtime = ToolRuntime()
    side_effect = (
        ToolSideEffect.READ
        if approval_policy is ApprovalPolicy.NOT_REQUIRED
        else ToolSideEffect.WRITE
    )
    runtime.register(
        ToolSpec(
            id="tool.lookup",
            title="Lookup",
            description="Return one bounded lookup result.",
            owner="core",
            side_effect=side_effect,
            approval_policy=approval_policy,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        lookup_handler,
    )
    return runtime


async def lookup_handler(arguments):
    return {"result": f"found:{arguments['query']}"}


def test_bounded_agent_runtime_executes_tool_then_completes() -> None:
    definition = make_definition()
    compiled = compile_definition(definition)
    driver = SequenceDriver(
        AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        ),
        AgentStepDecision.complete("Final answer"),
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(),
        id_factory=lambda: "fixed",
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
            run_id="run.test",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    assert result.answer == "Final answer"
    assert result.steps_executed == 2
    assert result.tool_calls == 1
    assert len(result.tool_events) == 1
    assert result.tool_events[0].status is RunStatus.COMPLETED
    assert driver.contexts[1].tool_results[0].output_copy() == {
        "result": "found:alpha"
    }
    public = result.to_public_dict()
    assert public["answer"] == "Final answer"
    assert "found:alpha" not in str(public)


def test_agent_runtime_stops_before_tool_call_when_tool_budget_is_zero() -> None:
    definition = make_definition(
        execution_budget=AgentExecutionBudget(
            max_steps=4,
            max_tool_calls=0,
            max_skill_calls=0,
            max_wall_seconds=60,
        )
    )
    compiled = compile_definition(definition)
    driver = SequenceDriver(
        AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        )
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(),
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
            run_id="run.toolbudget",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.MAX_TOOL_CALLS
    assert result.tool_calls == 0
    assert result.tool_events == ()


def test_agent_runtime_converts_explicit_tool_approval_block_into_pause() -> None:
    definition = make_definition()
    compiled = compile_definition(definition)
    invocation = ToolInvocation(
        tool_id="tool.lookup",
        arguments={"query": "sensitive"},
    )
    driver = SequenceDriver(AgentStepDecision.use_tool(invocation))
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(
            approval_policy=ApprovalPolicy.USER_CONFIRMATION
        ),
        id_factory=lambda: "fixed",
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Run the lookup.",
            run_id="run.approval",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.APPROVAL_REQUIRED
    assert result.approval_pause is not None
    assert result.pending_invocation == invocation
    assert result.approval_pause.tool_id == "tool.lookup"
    assert result.tool_events[-1].status is RunStatus.POLICY_BLOCKED
    public = result.to_public_dict()
    assert public["approval_pause"]["pause_id"].startswith("pause:")
    assert "sensitive" not in str(public)


def test_agent_runtime_treats_non_approval_policy_block_as_authorization_denied() -> None:
    definition = make_definition(allowed_tool_ids=())
    compiled = compile_definition(definition)
    driver = SequenceDriver(
        AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        )
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(),
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
            run_id="run.denied",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.AUTHORIZATION_DENIED
    assert result.tool_events[-1].status is RunStatus.POLICY_BLOCKED


def test_agent_runtime_enforces_step_budget() -> None:
    definition = make_definition(
        execution_budget=AgentExecutionBudget(
            max_steps=1,
            max_tool_calls=2,
            max_skill_calls=0,
            max_wall_seconds=60,
        )
    )
    compiled = compile_definition(definition)
    driver = SequenceDriver(
        AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        ),
        AgentStepDecision.complete("would be step two"),
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(),
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
            run_id="run.steps",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.MAX_STEPS
    assert result.steps_executed == 1
    assert result.tool_calls == 1
    assert len(driver.contexts) == 1


def test_agent_runtime_rejects_answer_that_arrives_after_wall_budget() -> None:
    definition = make_definition(
        execution_budget=AgentExecutionBudget(
            max_steps=2,
            max_tool_calls=1,
            max_skill_calls=0,
            max_wall_seconds=1,
        )
    )
    compiled = compile_definition(definition)
    clock = MutableClock()
    runtime = BoundedAgentRuntime(
        step_driver=AdvancingDriver(clock),
        tool_runtime=make_tool_runtime(),
        clock=clock,
    )

    result = asyncio.run(runtime.run(
        AgentRunRequest(
            definition=definition,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
            run_id="run.wall",
        )
    ))

    assert result.terminal_reason is AgentTerminalReason.MAX_WALL_TIME
    assert result.answer is None


def test_agent_run_request_rejects_compiled_profile_from_another_agent() -> None:
    first = make_definition()
    second = make_definition(agent_id="agent:padiem:other@1")
    compiled = compile_definition(first)

    with pytest.raises(AgentRuntimeError, match="Compiled profile"):
        AgentRunRequest(
            definition=second,
            compiled_profile=compiled,
            authorization=make_authorization(compiled),
            input_text="Research alpha.",
        )
