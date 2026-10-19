"""Product-side Core execution assembly for the verified PC query lane (#5151).

The product adapter (:mod:`kagent.pc_query_adapter`) owns the PC tool
contract. This module is the product-side *assembly* that lets a product run
that contract through the existing Core runtime, without the Engine
application:

```text
product adapter contract
  -> Core AgentPlanExecutor (BoundedAgentRuntime) with the product step policy
  -> Core ToolRuntime (the product's registered tools)
  -> tool result re-fed into the next step
  -> completed answer
```

What is reused, never re-implemented:

* the Core agent runtime and tool runtime (``padiem_ai_core``) — no new
  runtime, router, broker or model gateway is introduced here;
* the product contract, the product step policy and the trusted plan
  arguments from :mod:`kagent.pc_query_adapter` (#5209);
* the existing injection points: the Core ``ToolRuntime`` with the product's
  registered tools, and the model step selector that the product injects.

What this module deliberately does not do: it never talks to a PC, a model
provider, the Control Plane or the Engine, and it is not wired to the live
Chat/Claw routes yet. The tool runtime and the step selector are injected, so
the same assembly serves an offline synthetic tool today and the real signed
callback later.

Correlation scope: this assembly proves the **run id** correlation. It carries
no product session or conversation id, so a session/conversation correlation
is not implemented here and stays follow-up work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from padiem_ai_core.agent_definition import AgentTerminalReason
from padiem_ai_core.agent_execution_bridge import AgentPlanExecutor
from padiem_ai_core.agent_planner import AgentPlan
from padiem_ai_core.contracts import ToolEvent
from padiem_ai_core.tool_runtime import ToolRuntime

from .pc_query_adapter import (
    PC_QUERY_OWNER,
    PcQueryProductContract,
    StructuredPCQueryStepDriver,
    pc_query_agent_plan,
    pc_query_plan_arguments,
    validate_pc_query_product_identity,
)

# The model step selector is an injection point: the product owns the model
# call, this assembly owns everything around it.
ModelStepSelector = Callable[..., Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class PcQueryCoreRequest:
    """One product-side PC query run.

    ``tool_runtime`` is the Core runtime that already carries the product's
    registered tools; ``subject_id``, ``run_id`` and ``device_id`` are
    server-owned values resolved by the product's own authority path.

    Correlation scope: this request carries no session or conversation id, so
    the correlation this slice proves is the **run id** (subject, product and
    target included). Binding a product session/conversation to the run is
    not implemented here and stays follow-up work.
    """

    contract: PcQueryProductContract
    tool_runtime: ToolRuntime
    input_text: str
    run_id: str
    subject_id: str
    device_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class PcQueryCoreOutcome:
    """The verified outcome of one product-side PC query run.

    Correlation scope: the outcome proves the run id correlation (run id,
    product, agent, target and the tool events of that run). It carries no
    session or conversation id, so a product session/conversation correlation
    is not part of this slice.
    """

    run_id: str
    product_app_id: str
    agent_id: str
    answer: str | None
    terminal_reason: AgentTerminalReason
    steps_executed: int
    tool_calls: int
    tool_events: tuple[ToolEvent, ...]
    device_id: str | None

    @property
    def completed(self) -> bool:
        return (
            self.terminal_reason is AgentTerminalReason.COMPLETED
            and isinstance(self.answer, str)
            and bool(self.answer.strip())
        )


def _validate_contract(contract: PcQueryProductContract) -> None:
    """Fail closed when a product contract is mixed with another product."""
    if not isinstance(contract, PcQueryProductContract):
        raise ValueError("contract must be PcQueryProductContract")
    # A self-consistent contract is not enough: the product app and the agent
    # must also be one of the reviewed pairs, so a crossed pair (Chat app with
    # the Claw agent, or the reverse) never reaches a tool.
    validate_pc_query_product_identity(
        app_id=contract.app_id, agent_id=contract.agent_id,
    )
    if contract.authorization.app_id != contract.app_id:
        raise ValueError("contract authorization does not belong to the product app")
    if contract.authorization.agent_id != contract.compiled.runtime_profile.id:
        raise ValueError("contract authorization does not belong to the product agent")
    if contract.compiled.canonical_agent_id != contract.agent_id:
        raise ValueError("contract profile does not belong to the product agent")


async def run_pc_query_with_core(
    *,
    request: PcQueryCoreRequest,
    select_step: ModelStepSelector,
    plan: AgentPlan | None = None,
) -> PcQueryCoreOutcome:
    """Run the product's PC query contract through the existing Core runtime.

    The product keeps its own authority, target and model call:

    * the server-owned target travels as the trusted plan argument, and the
      product step policy replaces the model's empty arguments with it — a
      model that names another PC is refused, not silently accepted;
    * the verified owner run is bound to the tool handler through the shared
      product owner context, so the tool sees the same subject, run, product
      and target the product resolved;
    * the tool result is re-fed into the next step by the Core runtime, and
      the completed answer is the model's own completion decision.

    The proven correlation is the **run id**. A product session/conversation
    correlation is not implemented in this slice: the request and the outcome
    carry no session id, and binding one is follow-up work.
    """
    if not isinstance(request, PcQueryCoreRequest):
        raise ValueError("request must be PcQueryCoreRequest")
    if not isinstance(request.tool_runtime, ToolRuntime):
        raise ValueError("tool_runtime must be ToolRuntime")
    if not callable(select_step):
        raise ValueError("select_step must be callable")
    _validate_contract(request.contract)

    contract = request.contract
    # The trusted plan argument is validated with the reviewed device-id
    # grammar, so an invalid server value never becomes a dispatch target.
    static_arguments = pc_query_plan_arguments(request.device_id)
    step_driver = StructuredPCQueryStepDriver(
        select_step=select_step, static_arguments=static_arguments,
    )
    agent_plan = plan if plan is not None else pc_query_agent_plan(contract.agent_id)
    if not isinstance(agent_plan, AgentPlan):
        raise ValueError("plan must be AgentPlan")

    owner = (
        request.subject_id,
        request.run_id,
        contract.app_id,
        request.device_id,
    )
    owner_token = PC_QUERY_OWNER.set(owner)
    try:
        result = await AgentPlanExecutor().execute(
            plan=agent_plan,
            definition=contract.definition,
            compiled_profile=contract.compiled,
            authorization=contract.authorization,
            tool_runtime=request.tool_runtime,
            input_text=request.input_text,
            run_id=request.run_id,
            step_driver=step_driver,
            trace_id=request.trace_id,
        )
    finally:
        PC_QUERY_OWNER.reset(owner_token)

    return PcQueryCoreOutcome(
        run_id=result.run_id,
        product_app_id=contract.app_id,
        agent_id=contract.agent_id,
        answer=result.answer,
        terminal_reason=result.terminal_reason,
        steps_executed=result.steps_executed,
        tool_calls=result.tool_calls,
        tool_events=tuple(result.tool_events),
        device_id=request.device_id,
    )


__all__ = [
    "ModelStepSelector",
    "PcQueryCoreOutcome",
    "PcQueryCoreRequest",
    "run_pc_query_with_core",
]
