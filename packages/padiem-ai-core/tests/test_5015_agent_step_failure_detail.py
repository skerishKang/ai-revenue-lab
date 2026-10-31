"""#5015: a step driver's own bounded detail survives the runtime boundary.

Before this change every exception raised by ``next_step`` was rewritten as
the single generic ``agent_step_failed`` with ``from None``, so a support read
could not tell an unparsable model answer from an unauthorized tool choice.
These tests pin the two halves of the contract:

* a driver that names a closed detail keeps it, and
* every other failure, including an unbounded or non-textual detail, keeps the
  previous generic code, generic message and unchained exception.

The last test is the mutation guard: removing the preservation in
``agent_runtime`` makes ``test_driver_detail_code_is_preserved`` fail.
"""

from __future__ import annotations

import asyncio

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.agent_runtime import (
    AgentRunRequest,
    AgentRuntimeError,
    BoundedAgentRuntime,
)
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

SENTINEL = "MODEL-OUTPUT-SENTINEL-/home/owner/private.txt"


class _RaisingDriver:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def next_step(self, context, compiled_profile):
        raise self._exc


class _DetailError(ValueError):
    """A driver-owned failure whose bounded identifier is its ``code``."""

    def __init__(self, code, message: str = SENTINEL) -> None:
        super().__init__(message)
        self.code = code


def _compiled():
    definition = BoundedAgentDefinition(
        agent_id="agent:padiem:chat-pc-query@1",
        publisher_id="publisher:padiem",
        title="PC query",
        description="PC query.",
        instruction="Use the verified PC tool.",
        output_contract_ref="io:answer@1",
        allowed_tool_ids=("tool:padiem:lookup@1",),
        required_capabilities=("chat",),
        context_policy_ref="context:default@1",
        model_policy_ref="model:auto@1",
        execution_budget=AgentExecutionBudget(
            max_steps=4, max_tool_calls=3, max_skill_calls=0, max_wall_seconds=60,
        ),
    )
    compiled = compile_agent_profile(
        definition,
        TrustedAgentRuntimePolicy(
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
        ),
    )
    return definition, compiled


def _run(exc: BaseException) -> AgentRuntimeError:
    definition, compiled = _compiled()
    runtime = BoundedAgentRuntime(
        step_driver=_RaisingDriver(exc),
        tool_runtime=ToolRuntime(),
        id_factory=lambda: "fixed",
    )
    request = AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=ToolAuthorizationContext(
            app_id="padiem-chat", agent_id=compiled.runtime_profile.id,
        ),
        input_text="list and read",
        run_id="run.synthetic",
    )
    try:
        asyncio.run(runtime.run(request))
    except AgentRuntimeError as raised:
        return raised
    raise AssertionError("the runtime must fail closed")


def test_driver_detail_code_is_preserved() -> None:
    raised = _run(_DetailError("model_response_not_json"))

    assert raised.code == "agent_step_failed.model_response_not_json"
    # The public message and the absence of a chained exception are unchanged.
    assert raised.safe_message == "Agent step execution failed."
    assert raised.__cause__ is None
    assert raised.__suppress_context__ is True


def test_unmarked_exception_keeps_the_generic_code() -> None:
    raised = _run(RuntimeError(SENTINEL))

    assert raised.code == "agent_step_failed"
    assert raised.__cause__ is None


def test_unbounded_detail_is_dropped() -> None:
    # Uppercase, whitespace, punctuation, over-long, empty and non-text values
    # are not the closed identifier shape, so they never cross the boundary.
    for code in (
        "MODEL_FAILED",
        "model failed",
        "model-failed",
        "model/failed",
        "a" * 49,
        "",
        None,
        123,
        SENTINEL,
    ):
        raised = _run(_DetailError(code))
        assert raised.code == "agent_step_failed", code


def test_preserved_detail_never_carries_exception_text() -> None:
    raised = _run(_DetailError("tool_selection_invalid"))

    assert "SENTINEL" not in raised.code
    assert "private.txt" not in raised.code
    assert SENTINEL not in raised.safe_message
