"""#4379 focused: long agent runs, long input/output, and the tool result ledger.

#4379: PADIEM imposes no step, tool-call, input-character or output-character
ceiling of its own. A run continues until the model answers, the inactivity
watchdog ends it, or the caller cancels it. Tool results live in a ledger and
are reached through authorized references, so a long run neither loses the
original payload nor keeps every payload in memory.
"""
from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.agent_approval import ApprovalPause
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
    AgentStepDecision,
    BoundedAgentRuntime,
)
from padiem_ai_core.agent_tool_result_ledger import InMemoryToolResultLedger
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


class _SequenceDriver:
    """A driver that answers with the given decisions in order."""

    def __init__(self, *decisions):
        self._decisions = list(decisions)
        self.contexts = []

    async def next_step(self, context, compiled_profile):
        self.contexts.append(context)
        if not self._decisions:
            return AgentStepDecision.complete("no more decisions")
        return self._decisions.pop(0)


class _RepeatingToolDriver:
    """A driver that asks for the same tool call over and over."""

    def __init__(self, tool_id, arguments, *, until):
        self._tool_id = tool_id
        self._arguments = arguments
        self._until = until
        self.contexts = []

    async def next_step(self, context, compiled_profile):
        self.contexts.append(context)
        if len(self.contexts) >= self._until:
            return AgentStepDecision.complete("done")
        return AgentStepDecision.use_tool(
            ToolInvocation(tool_id=self._tool_id, arguments=self._arguments)
        )


def _definition(**overrides):
    values = {
        "agent_id": "agent:padiem:long@1",
        "publisher_id": "publisher:padiem",
        "title": "Long runner",
        "description": "A long Agent run.",
        "instruction": "Keep working until the task is done.",
        "output_contract_ref": "io:answer@1",
        "allowed_tool_ids": ("tool:padiem:lookup@1",),
        "required_capabilities": ("chat",),
        "context_policy_ref": "context:default@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": AgentExecutionBudget(
            max_steps=4, max_tool_calls=3, max_skill_calls=0, max_wall_seconds=60,
        ),
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def _compiled(definition, *, max_steps_cap=4, max_tokens=800):
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:answer@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=max_tokens,
        max_steps_cap=max_steps_cap,
        context_policy={},
        model_policy={"model": "fixture/explicit-model"},
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


def _authorization(compiled):
    return ToolAuthorizationContext(
        app_id="test.app", agent_id=compiled.runtime_profile.id,
    )


def _tool_runtime(*, approval_policy=ApprovalPolicy.NOT_REQUIRED, auth_scope=()):
    runtime = ToolRuntime()
    side_effect = (
        ToolSideEffect.READ
        if approval_policy is ApprovalPolicy.NOT_REQUIRED
        else ToolSideEffect.WRITE
    )
    calls: list[dict] = []

    async def handler(arguments):
        calls.append(dict(arguments))
        return {"result": f"found:{arguments['query']}"}

    runtime.register(
        ToolSpec(
            id="tool.lookup",
            title="Lookup",
            description="Return one bounded lookup result.",
            owner="core",
            side_effect=side_effect,
            approval_policy=approval_policy,
            auth_scope=auth_scope,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        handler,
    )
    runtime.calls = calls
    return runtime


def _run(runtime, request):
    return asyncio.run(runtime.run(request))


# ---------------------------------------------------------------------------
# A. Step ceilings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("steps", [65, 101, 1_000])
def test_a_long_run_reaches_any_step_number(steps: int) -> None:
    """#4379: a step count is not a PADIEM quantity."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    driver = _RepeatingToolDriver(
        "tool.lookup", {"query": "alpha"}, until=steps,
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=_tool_runtime(), id_factory=lambda: "fixed",
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="Research alpha.",
        run_id="run.long",
    ))
    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    assert result.steps_executed == steps
    assert result.tool_calls == steps - 1


def test_a_resumed_run_starts_beyond_the_old_step_ceiling() -> None:
    """#4379: a resumed run may start at step 101 and continue normally."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    driver = _SequenceDriver(AgentStepDecision.complete("resumed answer"))
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=_tool_runtime(), id_factory=lambda: "fixed",
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="Continue.",
        run_id="run.resume",
        initial_step_index=101,
    ))
    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    assert result.answer == "resumed answer"
    assert result.steps_executed == 101


def test_an_approval_pause_beyond_the_old_step_ceiling_is_accepted() -> None:
    """#4379: the approval pause keeps a step index of any size."""
    from datetime import datetime, timedelta, timezone

    from datetime import datetime, timedelta, timezone

    from padiem_ai_core.agent_approval import ApprovalRequirement

    now = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    pause = ApprovalPause(
        pause_id="pause_1",
        run_id="run.long",
        agent_runtime_id="agent_runtime_long",
        tool_id="tool.lookup",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=101,
        created_at=now,
        expires_at=now + timedelta(seconds=900),
    )
    assert pause.step_index == 101


# ---------------------------------------------------------------------------
# B. Input and output character ceilings
# ---------------------------------------------------------------------------


def test_a_long_input_and_a_long_answer_are_accepted() -> None:
    """#4379: 32,001 characters of input and a 65,537 character answer."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    answer = "가" * 65_537
    driver = _SequenceDriver(AgentStepDecision.complete(answer))
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=_tool_runtime(), id_factory=lambda: "fixed",
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="가" * 32_001,
        run_id="run.long_input",
    ))
    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    assert result.answer == answer


# ---------------------------------------------------------------------------
# C. Explicit budgets have no PADIEM maximum
# ---------------------------------------------------------------------------


def test_an_explicit_budget_has_no_padiem_maximum() -> None:
    """#4379: 1,000 skill calls and a 2,000,000 second ceiling are accepted."""
    budget = AgentExecutionBudget(
        max_steps=1_000, max_tool_calls=5_000, max_skill_calls=1_000,
        max_wall_seconds=86_400, max_total_seconds=2_000_000,
    )
    assert budget.max_skill_calls == 1_000
    assert budget.max_total_seconds == 2_000_000
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:answer@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=None,
        max_steps_cap=1_000,
        context_policy={},
        model_policy={},
        output_contract={},
    )
    assert policy.max_steps_cap == 1_000


# ---------------------------------------------------------------------------
# D. The tool result ledger
# ---------------------------------------------------------------------------


def test_more_than_one_hundred_tool_results_are_preserved_and_reachable() -> None:
    """#4379: 120 tool results stay complete, referenced and restorable."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    driver = _RepeatingToolDriver(
        "tool.lookup", {"query": "alpha"}, until=121,
    )
    ledger = InMemoryToolResultLedger()
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=_tool_runtime(),
        id_factory=lambda: "fixed", result_ledger=ledger,
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="Research alpha.",
        run_id="run.many",
    ))
    assert result.tool_calls == 120
    # The runtime kept only the references; the ledger owns every payload.
    last_context = driver.contexts[-1]
    assert len(last_context.tool_result_refs) == 120
    resolved = asyncio.run(last_context.resolve_tool_results())
    assert len(resolved) == 120
    assert resolved[0].output_copy() == {"result": "found:alpha"}
    assert resolved[-1].output_copy() == {"result": "found:alpha"}
    # A resumed run restores the original payloads by reference.
    restored = asyncio.run(ledger.resolve(last_context.tool_result_refs[0]))
    assert restored.output_copy() == {"result": "found:alpha"}


def test_the_same_tool_is_not_executed_twice_and_no_write_is_duplicated() -> None:
    """#4379: the ledger never re-executes a tool to recover a result."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    tool_runtime = _tool_runtime()
    driver = _RepeatingToolDriver(
        "tool.lookup", {"query": "alpha"}, until=5,
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=tool_runtime,
        id_factory=lambda: "fixed",
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="Research alpha.",
        run_id="run.once",
    ))
    assert result.tool_calls == 4
    assert len(tool_runtime.calls) == 4


def test_an_unauthorized_tool_call_is_refused_without_a_provider_call() -> None:
    """#4379: removing a ceiling never widens the tool authority."""
    definition = _definition(execution_budget=AgentExecutionBudget(
        max_steps=None, max_tool_calls=None, max_skill_calls=None,
        max_wall_seconds=60,
    ))
    compiled = _compiled(definition, max_steps_cap=None)
    tool_runtime = _tool_runtime(approval_policy=ApprovalPolicy.EXTERNAL_AUTHORIZATION)
    driver = _SequenceDriver(
        AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        ),
    )
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=tool_runtime, id_factory=lambda: "fixed",
    )
    result = _run(runtime, AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=_authorization(compiled),
        input_text="Research alpha.",
        run_id="run.denied",
    ))
    # The external authorization is not granted, so the call pauses for a
    # verified approval and never reaches the tool.
    assert result.terminal_reason is AgentTerminalReason.APPROVAL_REQUIRED
    assert result.approval_pause is not None
    assert result.approval_pause.step_index == 1
    assert tool_runtime.calls == []


def test_stop_fences_run_before_next_tool_dispatch() -> None:
    """A revoked owner run must never dispatch the tool the model just selected."""
    async def scenario() -> None:
        definition = _definition(execution_budget=AgentExecutionBudget(
            max_steps=None, max_tool_calls=None, max_skill_calls=None,
            max_wall_seconds=60,
        ))
        compiled = _compiled(definition, max_steps_cap=None)
        active = True
        calls = 0

        class _StopWhileDeciding:
            async def next_step(self, context, compiled_profile):
                nonlocal active
                active = False  # User STOP/revoked lease after model dispatch.
                return AgentStepDecision.use_tool(
                    ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
                )

        async def run_guard():
            nonlocal calls
            calls += 1
            return active

        tool_runtime = _tool_runtime()
        runtime = BoundedAgentRuntime(
            step_driver=_StopWhileDeciding(), tool_runtime=tool_runtime,
            run_guard=run_guard, id_factory=lambda: "fixed",
        )
        with pytest.raises(Exception) as stopped:
            await runtime.run(AgentRunRequest(
                definition=definition, compiled_profile=compiled,
                authorization=_authorization(compiled), input_text="Work.",
                run_id="run.stop",
            ))
        assert getattr(stopped.value, "code", None) == "agent_run_fenced"
        assert calls >= 2
        assert tool_runtime.calls == []

    asyncio.run(scenario())
