"""#4194: Agent/Task long-run contract — no fixed wall, inactivity watchdog only.

Offline, fake-clock and short real-time tests. No provider/model call is made and
no production resource is touched. Precisely:

- a run that keeps making verified progress may exceed the old total wall budget
  (900s default, 3600s max) and still complete;
- a run that stops progressing still fails closed as ``MAX_WALL_TIME`` inside the
  idle window (never reported as completed or resumable);
- step/Tool counts, an explicit host-opted total ceiling, cancellation and the
  single-shot model lane's caller-declared ExecutionContext budget are retained.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.agent_definition import (
    AgentDefinitionError,
    AgentExecutionBudget,
    AgentTerminalReason,
    BoundedAgentDefinition,
)
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.agent_progress import (
    AgentIdleTimeoutError,
    AgentProgressError,
    AgentProgressTracker,
    await_with_agent_progress,
)
from padiem_ai_core.agent_runtime import (
    AgentRunRequest,
    AgentRuntimeError,
    AgentStepDecision,
    BoundedAgentRuntime,
)
from padiem_ai_core.contracts import (
    ApprovalPolicy,
    RunMetadata,
    RunStatus,
    ToolSideEffect,
    ToolSpec,
)
from padiem_ai_core.execution_context import ExecutionContext
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionResult,
)
from padiem_ai_core.orchestration import (
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationRunner,
)
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext,
    ToolInvocation,
    ToolRuntime,
)


class MutableClock:
    """Deterministic monotonic clock; advances only when a phase completes."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ProgressingDriver:
    """Advances the clock once per step, i.e. every step does real work."""

    def __init__(self, clock: MutableClock, *, advance_per_step: float, steps: int) -> None:
        self._clock = clock
        self._advance = advance_per_step
        self._remaining = steps
        self.contexts = []

    async def next_step(self, context, compiled_profile):
        self.contexts.append(context)
        if self._remaining <= 0:
            self._clock.value += self._advance
            return AgentStepDecision.complete("Long but progressing answer")
        self._remaining -= 1
        self._clock.value += self._advance
        return AgentStepDecision.use_tool(
            ToolInvocation(tool_id="tool.lookup", arguments={"query": "alpha"})
        )


async def lookup_handler(arguments):
    return {"result": f"found:{arguments['query']}"}


def make_tool_runtime(
    *, approval_policy: ApprovalPolicy = ApprovalPolicy.NOT_REQUIRED
) -> ToolRuntime:
    runtime = ToolRuntime()
    runtime.register(
        ToolSpec(
            id="tool.lookup",
            title="Lookup",
            description="Return one bounded lookup result.",
            owner="core",
            side_effect=(
                ToolSideEffect.READ
                if approval_policy is ApprovalPolicy.NOT_REQUIRED
                else ToolSideEffect.WRITE
            ),
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


def make_definition(
    *,
    max_steps: int = 8,
    max_tool_calls: int = 8,
    max_wall_seconds: int = 5,
    max_total_seconds: int | None = None,
) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id="agent:padiem:researcher@1",
        publisher_id="publisher:padiem",
        title="Researcher",
        description="Bounded research Agent.",
        instruction="Use tools only when required.",
        output_contract_ref="io:answer@1",
        allowed_tool_ids=("tool:padiem:lookup@1",),
        required_capabilities=("chat",),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        execution_budget=AgentExecutionBudget(
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            max_skill_calls=0,
            max_wall_seconds=max_wall_seconds,
            max_total_seconds=max_total_seconds,
        ),
    )


def compile_definition(definition: BoundedAgentDefinition):
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        output_contract_ref="io:answer@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=800,
        max_steps_cap=8,
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


def make_authorization(compiled) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id="test.app",
        agent_id=compiled.runtime_profile.id,
    )


def run_runtime(definition, driver, *, clock: MutableClock, tracker=None):
    compiled = compile_definition(definition)
    runtime = BoundedAgentRuntime(
        step_driver=driver,
        tool_runtime=make_tool_runtime(),
        clock=clock,
        progress=tracker,
    )
    return asyncio.run(
        runtime.run(
            AgentRunRequest(
                definition=definition,
                compiled_profile=compiled,
                authorization=make_authorization(compiled),
                input_text="Research alpha.",
                run_id="run.4194",
            )
        )
    )


# ---------------------------------------------------------------------------
# A. No fixed total wall clock for a progressing Agent run
# ---------------------------------------------------------------------------


def test_progressing_run_exceeds_old_total_wall_and_still_completes() -> None:
    # 6 tool steps * 4s = 24s of verified work against a 5s idle window: the
    # pre-#4194 cumulative budget (5s) would have force-failed at step 2.
    clock = MutableClock()
    definition = make_definition(max_steps=8, max_tool_calls=8, max_wall_seconds=5)
    result = run_runtime(
        definition,
        ProgressingDriver(clock, advance_per_step=4.0, steps=6),
        clock=clock,
    )

    assert clock.value > 5.0  # total elapsed far beyond the idle window
    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    assert result.answer == "Long but progressing answer"
    assert result.tool_calls == 6


def test_shared_progress_tracker_records_only_verified_phases() -> None:
    clock = MutableClock()
    tracker = AgentProgressTracker(clock=clock)
    definition = make_definition(max_wall_seconds=5)
    result = run_runtime(
        definition,
        ProgressingDriver(clock, advance_per_step=4.0, steps=3),
        clock=clock,
        tracker=tracker,
    )

    assert result.terminal_reason is AgentTerminalReason.COMPLETED
    snapshot = tracker.snapshot()
    assert snapshot["progress_count"] >= 6  # run_start + 3 * (tool + checkpoint)
    assert snapshot["elapsed_seconds"] > 5.0
    assert set(snapshot) == {
        "progress_count",
        "last_phase",
        "seconds_since_progress",
        "elapsed_seconds",
    }
    # Non-sensitive payload only: no prompt, tool arguments or model output.
    assert "alpha" not in str(snapshot)


def test_stalled_step_fails_closed_and_never_looks_completed() -> None:
    clock = MutableClock()
    definition = make_definition(max_wall_seconds=5)
    result = run_runtime(
        definition,
        ProgressingDriver(clock, advance_per_step=30.0, steps=1),
        clock=clock,
    )

    assert result.terminal_reason is AgentTerminalReason.MAX_WALL_TIME
    assert result.answer is None
    assert result.to_public_dict()["terminal_reason"] == "max_wall_time"


def test_step_and_tool_count_budgets_still_bound_a_progressing_run() -> None:
    clock = MutableClock()
    definition = make_definition(max_steps=8, max_tool_calls=2, max_wall_seconds=5)
    result = run_runtime(
        definition,
        ProgressingDriver(clock, advance_per_step=1.0, steps=6),
        clock=clock,
    )

    assert result.terminal_reason is AgentTerminalReason.MAX_TOOL_CALLS
    assert result.tool_calls == 2


def test_host_opted_total_ceiling_still_stops_a_progressing_run() -> None:
    clock = MutableClock()
    definition = make_definition(
        max_steps=8, max_tool_calls=8, max_wall_seconds=5, max_total_seconds=10
    )
    result = run_runtime(
        definition,
        ProgressingDriver(clock, advance_per_step=4.0, steps=6),
        clock=clock,
    )

    assert result.terminal_reason is AgentTerminalReason.MAX_WALL_TIME
    assert result.answer is None


def test_revoked_durable_guard_stops_a_progressing_run_at_the_next_dispatch() -> None:
    # A user cancel / lost lease fences the run through the existing durable
    # guard: the long progress-based run stops before its next dispatch and is
    # never reported as completed.
    clock = MutableClock()
    calls = {"n": 0}

    def guard() -> bool:
        calls["n"] += 1
        return calls["n"] <= 2

    definition = make_definition(max_steps=8, max_tool_calls=8, max_wall_seconds=5)
    compiled = compile_definition(definition)
    runtime = BoundedAgentRuntime(
        step_driver=ProgressingDriver(clock, advance_per_step=4.0, steps=6),
        tool_runtime=make_tool_runtime(),
        clock=clock,
        run_guard=guard,
    )

    async def scenario() -> AgentRuntimeError:
        with pytest.raises(AgentRuntimeError) as raised:
            await runtime.run(
                AgentRunRequest(
                    definition=definition,
                    compiled_profile=compiled,
                    authorization=make_authorization(compiled),
                    input_text="Research alpha.",
                    run_id="run.4194.fenced",
                )
            )
        return raised.value

    error = asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    assert error.code == "agent_run_fenced"


def test_default_budget_has_no_total_ceiling_and_validates_an_opt_in_one() -> None:
    assert AgentExecutionBudget().max_total_seconds is None
    assert AgentExecutionBudget().max_wall_seconds == 900
    assert AgentExecutionBudget(max_total_seconds=86_400).max_total_seconds == 86_400

    for invalid in (0, -1, 86_401, True, 1.5):
        with pytest.raises(AgentDefinitionError):
            AgentExecutionBudget(max_total_seconds=invalid)


# ---------------------------------------------------------------------------
# B. Progress-aware bounded wait (idle watchdog, not a wall clock)
# ---------------------------------------------------------------------------


def test_progress_aware_wait_returns_the_inner_result() -> None:
    tracker = AgentProgressTracker()

    async def work() -> str:
        tracker.touch("step_decision")
        return "done"

    assert (
        asyncio.run(
            await_with_agent_progress(work(), tracker=tracker, idle_seconds=1.0)
        )
        == "done"
    )


def test_progress_aware_wait_fails_closed_only_on_a_real_stall() -> None:
    tracker = AgentProgressTracker()

    async def stalled() -> str:
        await asyncio.sleep(30)
        return "never"

    async def scenario() -> None:
        with pytest.raises(AgentIdleTimeoutError):
            await await_with_agent_progress(
                stalled(), tracker=tracker, idle_seconds=0.05, poll_interval=0.01
            )

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_progress_aware_wait_keeps_a_slow_but_progressing_run_alive() -> None:
    tracker = AgentProgressTracker()

    async def slow_but_progressing() -> str:
        for _ in range(15):
            await asyncio.sleep(0.02)
            tracker.touch("tool_result")
        return "progressed"

    async def scenario() -> str:
        # Total elapsed (~0.3s) is 6x the idle window (0.05s); only progress
        # resets the deadline, which is exactly the #4194 contract.
        return await await_with_agent_progress(
            slow_but_progressing(),
            tracker=tracker,
            idle_seconds=0.05,
            poll_interval=0.01,
        )

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=5)) == "progressed"


def test_progress_aware_wait_propagates_external_cancellation() -> None:
    tracker = AgentProgressTracker()
    inner_cancelled = []

    async def hanging() -> str:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            inner_cancelled.append(True)
            raise
        return "never"

    async def scenario() -> None:
        task = asyncio.ensure_future(
            await_with_agent_progress(hanging(), tracker=tracker, idle_seconds=30.0)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    assert inner_cancelled == [True]


def test_progress_aware_wait_rejects_invalid_configuration() -> None:
    tracker = AgentProgressTracker()

    async def work() -> str:
        return "done"

    async def scenario() -> None:
        pending = []
        for bad_idle in (0, -1, float("inf"), "600"):
            coroutine = work()
            pending.append(coroutine)
            with pytest.raises(AgentProgressError):
                await await_with_agent_progress(
                    coroutine, tracker=tracker, idle_seconds=bad_idle
                )
        coroutine = work()
        pending.append(coroutine)
        with pytest.raises(AgentProgressError):
            await await_with_agent_progress(
                coroutine, tracker="not-a-tracker", idle_seconds=1.0
            )
        for coroutine in pending:
            coroutine.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    with pytest.raises(AgentProgressError):
        tracker.touch("Not A Phase")


# ---------------------------------------------------------------------------
# C. Orchestration layer: bridge Agent run is watchdog-bounded, not wall-capped
# ---------------------------------------------------------------------------


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


def make_bridge_harness(*, steps: int, sleep_seconds: float, idle_window: int):
    definition = BoundedAgentDefinition(
        agent_id="agent:padiem:bridge_agent@1",
        publisher_id="publisher:padiem",
        title="Bridge Agent",
        description="Agent for the #4194 long-run contract.",
        instruction="Execute bounded plan steps.",
        output_contract_ref="io:agent_out@1",
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        allowed_tool_ids=("tool:padiem:calculator@1",),
        execution_budget=AgentExecutionBudget(
            max_steps=steps + 2,
            max_tool_calls=steps + 2,
            max_skill_calls=0,
            max_wall_seconds=idle_window,
        ),
    )
    compiled = compile_agent_profile(
        definition,
        TrustedAgentRuntimePolicy(
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
            tool_bindings=(
                ToolRuntimeBinding(
                    canonical_tool_id="tool:padiem:calculator@1",
                    runtime_tool_id="calc",
                ),
            ),
        ),
    )

    runtime = ToolRuntime()

    async def calc_handler(arguments):
        await asyncio.sleep(sleep_seconds)
        return {"result": 42}

    runtime.register(
        ToolSpec(
            id="calc",
            title="Calculator",
            description="Math operations",
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object"},
            output_contract={"type": "object"},
            timeout_seconds=30.0,
        ),
        calc_handler,
    )

    plan = AgentPlan(
        agent_id=definition.agent_id,
        steps=tuple(
            AgentPlanStep(step_id=f"s{index}", objective=f"Compute {index}", tool_id="calc")
            for index in range(1, steps + 1)
        ),
    )
    auth = ToolAuthorizationContext(
        app_id="b62",
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=("calc",),
    )
    return definition, compiled, plan, runtime, auth


def make_orchestration_request(
    *, context_timeout: float, steps: int, sleep_seconds: float, idle_window: int
) -> OrchestrationRequest:
    definition, compiled, plan, runtime, auth = make_bridge_harness(
        steps=steps, sleep_seconds=sleep_seconds, idle_window=idle_window
    )
    return OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=compiled.runtime_profile,
            messages=({"role": "user", "content": "Compute result"},),
            trace_id="tr_4194",
        ),
        context=ExecutionContext(trace_id="tr_4194", timeout_seconds=context_timeout),
        app_id="b62",
        agent_definition=definition,
        compiled_agent_profile=compiled,
        agent_plan=plan,
        tool_authorization=auth,
        tool_runtime=runtime,
    )


def test_bridge_agent_run_past_the_context_window_still_completes() -> None:
    # 5 steps * 0.3s = 1.5s of verified work against a 1.0s context window.
    # Pre-#4194 this raised orchestration_timeout at 1.0s of total elapsed time.
    request = make_orchestration_request(
        context_timeout=1.0, steps=5, sleep_seconds=0.3, idle_window=3
    )

    async def scenario():
        return await OrchestrationRunner(runtime=MockCoreRuntime()).run(request)

    result = asyncio.run(asyncio.wait_for(scenario(), timeout=20))

    assert result.execution_result.metadata.status is RunStatus.COMPLETED
    assert result.execution_result.metadata.tool_events
    assert len(result.execution_result.metadata.tool_events) == 5
    assert OrchestrationEventKind.RUN_COMPLETED in [event.kind for event in result.events]
    assert OrchestrationEventKind.RUN_FAILED not in [event.kind for event in result.events]


def test_bridge_agent_stall_fails_closed_with_timeout_and_no_success_claim() -> None:
    # The Tool never returns inside the 1s idle window and the Tool's own
    # 30s cap is irrelevant: the run must fail closed, not silently complete.
    request = make_orchestration_request(
        context_timeout=10.0, steps=2, sleep_seconds=3.0, idle_window=1
    )

    async def scenario() -> OrchestrationError:
        with pytest.raises(OrchestrationError) as raised:
            await OrchestrationRunner(runtime=MockCoreRuntime()).run(request)
        return raised.value

    error = asyncio.run(asyncio.wait_for(scenario(), timeout=20))

    assert error.code == "orchestration_timeout"
    assert "no verified progress" in error.safe_message
