"""Bounded AgentPlan to ToolRuntime Execution Bridge for Padiem AI Core (P01).

This module binds a validated, finite AgentPlan to the existing fail-closed
BoundedAgentRuntime and ToolRuntime without inventing new provider protocols or
widening authority boundaries.

Invariants:
- Plan != Authorization: A plan describes what to do; it cannot grant permissions.
- Tool execution occurs exclusively through the existing ToolRuntime.execute().
- Genuine Tool events only: TOOL_STARTED/COMPLETED/FAILED are emitted only on actual ToolRuntime execution.
- Transparent failure, timeout, cancellation, and approval pause lifecycles.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Any

from .agent_definition import AgentTerminalReason, BoundedAgentDefinition
from .agent_planner import AgentPlan, AgentPlanStep, validate_agent_plan
from .agent_profile_adapter import CompiledAgentProfile
from .agent_runtime import (
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimeError,
    AgentStepContext,
    AgentStepDecision,
    AgentStepDriver,
    BoundedAgentRuntime,
)
from .contracts import ToolEvent
from .tool_runtime import (
    ToolAuthorizationContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolRuntime,
)


class PlanBackedStepDriver:
    """Deterministic, provider-neutral AgentStepDriver backed by a validated AgentPlan."""

    def __init__(
        self,
        plan: AgentPlan,
        *,
        tool_arguments: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(plan, AgentPlan):
            raise AgentRuntimeError("invalid_plan", "plan must be an AgentPlan")
        self._plan = plan
        self._tool_arguments = tool_arguments or {}

    @property
    def plan(self) -> AgentPlan:
        return self._plan

    async def next_step(
        self,
        context: AgentStepContext,
        compiled_profile: CompiledAgentProfile,
    ) -> AgentStepDecision:
        step_idx = context.step_index - 1
        if step_idx >= len(self._plan.steps):
            # All plan steps completed; synthesize final answer from results
            if context.tool_results:
                last_res = context.tool_results[-1]
                ans = f"Plan completed. Tool '{last_res.tool_id}' finished with status: {last_res.event.status.value}."
            else:
                ans = "Plan completed successfully."
            return AgentStepDecision.complete(answer=ans)

        current_step = self._plan.steps[step_idx]

        if current_step.tool_id is not None:
            # Propose tool invocation
            args = dict(self._tool_arguments.get(current_step.step_id, {}))
            if not args and current_step.objective:
                args["query"] = current_step.objective
            invocation = ToolInvocation(
                tool_id=current_step.tool_id,
                arguments=args,
            )
            return AgentStepDecision.use_tool(invocation)

        # Plan step is an answer/synthesis step
        return AgentStepDecision.complete(answer=current_step.objective)


class AgentPlanExecutor:
    """Binds a validated AgentPlan to the BoundedAgentRuntime and existing ToolRuntime."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        approval_pause_seconds: int = 900,
    ) -> None:
        self._clock = clock
        self._approval_pause_seconds = approval_pause_seconds

    async def execute(
        self,
        *,
        plan: AgentPlan,
        definition: BoundedAgentDefinition,
        compiled_profile: CompiledAgentProfile,
        authorization: ToolAuthorizationContext,
        tool_runtime: ToolRuntime,
        input_text: str,
        run_id: str | None = None,
        step_driver: AgentStepDriver | None = None,
        tool_arguments: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> AgentRunResult:
        # 1. Authoritative plan validation against compiled profile
        validated_plan = validate_agent_plan(
            plan,
            definition=definition,
            compiled_profile=compiled_profile,
        )

        # 2. Construct step driver backed by plan
        driver = step_driver or PlanBackedStepDriver(
            validated_plan,
            tool_arguments=tool_arguments,
        )

        # 3. Instantiate bounded runtime
        runtime = BoundedAgentRuntime(
            step_driver=driver,
            tool_runtime=tool_runtime,
            clock=self._clock,
            approval_pause_seconds=self._approval_pause_seconds,
        )

        # 4. Execute bounded agent loop
        request = AgentRunRequest(
            definition=definition,
            compiled_profile=compiled_profile,
            authorization=authorization,
            input_text=input_text,
            run_id=run_id,
        )

        return await runtime.run(request)
