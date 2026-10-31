"""#5015: the PC step driver's closed failure details reach Engine telemetry.

The failing Chat PC turn was observable only as ``agent_step_failed``. These
tests drive the real ``build_live_pc_query_driver`` over fake B14 clients (no
provider, PC, network or database call) and follow each refusal through the
real Core runtime, the Engine's orchestration error mapping and the existing
``stack_telemetry`` refusal contract.

The normal JSON selection case stays in the file so the success path that
already reached the PC tool is pinned against the same driver.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.stack_telemetry as stack_telemetry
from app.claw_pc_query_step_driver import build_live_pc_query_driver
from app.orchestration_service import OrchestrationEngineService
from kagent.pc_query_adapter import (
    PC_LIST_FILES_TOOL_ID,
    PC_STEP_FAILURE_DETAILS,
    PCQueryStepError,
    StructuredPCQueryStepDriver,
)
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.agent_runtime import (
    AgentRunRequest,
    AgentRuntimeError,
    AgentStepKind,
    BoundedAgentRuntime,
)
from padiem_ai_core.orchestration import OrchestrationError
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

SENTINEL = "MODEL-OUTPUT-SENTINEL-/home/owner/private.txt"


class _Context:
    input_text = "list the folder and read the txt file"

    async def resolve_tool_results(self):
        return ()


class _Response:
    def __init__(self, answer) -> None:
        self.answer = answer


class _FakeB14:
    """Fake model client; returns text or raises, never contacts a provider."""

    def __init__(self, *, answer=None, raises: BaseException | None = None) -> None:
        self._answer = answer
        self._raises = raises
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return _Response(self._answer)


def _driver(answer=None, *, raises=None):
    # No service/secret: the PC context leg degrades to "PC context unavailable"
    # without a Chat transport call, which is the documented behaviour.
    return build_live_pc_query_driver(
        b14_client=_FakeB14(answer=answer, raises=raises),
        model_id="synthetic",
    )


def _detail_of(error: PCQueryStepError) -> str:
    assert isinstance(error, PCQueryStepError)
    assert error.code in PC_STEP_FAILURE_DETAILS
    return error.code


async def _refusal(answer=None, *, raises=None) -> str:
    driver = _driver(answer, raises=raises)
    with pytest.raises(PCQueryStepError) as caught:
        await driver.next_step(_Context(), None)
    return _detail_of(caught.value)


@pytest.mark.asyncio
async def test_non_json_model_answer_is_its_own_detail() -> None:
    detail = await _refusal(f"Here is the listing: {SENTINEL}")

    assert detail == "model_response_not_json"


@pytest.mark.asyncio
async def test_json_scalar_step_is_not_an_object() -> None:
    assert await _refusal("[\"not\", \"a\", \"step\"]") == "model_step_not_object"
    assert await _refusal("42") == "model_step_not_object"


@pytest.mark.asyncio
async def test_unknown_or_unauthorized_tool_is_a_selection_detail() -> None:
    unknown = json.dumps({"action": "tool", "tool_id": "claw.pc.format_disk",
                          "arguments": {}})
    bad_arguments = json.dumps({"action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
                                "arguments": {"path": ""}})

    assert await _refusal(unknown) == "tool_selection_invalid"
    assert await _refusal(bad_arguments) == "tool_selection_invalid"


@pytest.mark.asyncio
async def test_completion_answer_type_error_is_its_own_detail() -> None:
    missing = json.dumps({"action": "complete"})
    wrong_type = json.dumps({"action": "complete", "answer": 5})
    blank = json.dumps({"action": "complete", "answer": "   "})

    assert await _refusal(missing) == "completion_answer_invalid"
    assert await _refusal(wrong_type) == "completion_answer_invalid"
    assert await _refusal(blank) == "completion_answer_invalid"


@pytest.mark.asyncio
async def test_model_call_failure_is_its_own_detail() -> None:
    # The client raised: the provider policy still decides retry/fallback, and
    # the step only records that the model call itself failed.
    assert await _refusal(raises=RuntimeError(SENTINEL)) == "model_call_failed"

    # A returned response object without a text answer is the same boundary.
    for client in (_AnswerlessB14(), _FakeB14(answer=None)):
        driver = build_live_pc_query_driver(b14_client=client, model_id="synthetic")
        with pytest.raises(PCQueryStepError) as caught:
            await driver.next_step(_Context(), None)
        assert caught.value.code == "model_call_failed"


class _AnswerlessB14:
    async def execute(self, request):
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_normal_json_selection_still_reaches_the_tool() -> None:
    driver = _driver(json.dumps({
        "action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
        "arguments": {"path": "."},
    }))

    decision = await driver.next_step(_Context(), None)

    assert decision.kind is AgentStepKind.TOOL
    assert decision.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    assert decision.invocation.arguments == {"path": "."}


@pytest.mark.asyncio
async def test_markdown_fenced_tool_step_is_still_the_same_step() -> None:
    fenced = "```json\n" + json.dumps({
        "action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
        "arguments": {"path": "."},
    }) + "\n```"

    decision = await _driver(fenced).next_step(_Context(), None)

    assert decision.kind is AgentStepKind.TOOL
    assert decision.invocation.tool_id == PC_LIST_FILES_TOOL_ID
    assert decision.invocation.arguments == {"path": "."}


@pytest.mark.asyncio
async def test_prose_wrapped_completion_is_still_the_same_completion() -> None:
    answer = "Here is the result:\n" + json.dumps(
        {"action": "complete", "answer": "read complete"},
    ) + "\nDone."

    decision = await _driver(answer).next_step(_Context(), None)

    assert decision.kind is AgentStepKind.COMPLETE
    assert decision.answer == "read complete"


@pytest.mark.asyncio
async def test_truncated_object_is_not_repaired() -> None:
    truncated = ('{"action":"tool","tool_id":"' + PC_LIST_FILES_TOOL_ID
                 + '","arguments":{"path":"."')

    assert await _refusal(truncated) == "model_response_not_json"


@pytest.mark.asyncio
async def test_decorated_step_still_obeys_the_closed_tool_policy() -> None:
    fenced_unknown = "```json\n" + json.dumps({
        "action": "tool", "tool_id": "claw.pc.format_disk", "arguments": {},
    }) + "\n```"

    assert await _refusal(fenced_unknown) == "tool_selection_invalid"


@pytest.mark.asyncio
async def test_two_objects_are_not_arbitrarily_selected() -> None:
    first = json.dumps({"action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
                        "arguments": {"path": "."}})
    second = json.dumps({"action": "complete", "answer": "done"})

    assert await _refusal(first + second) == "model_response_not_json"


@pytest.mark.asyncio
async def test_prose_brace_outside_the_object_fails_closed() -> None:
    answer = "Use {path} then " + json.dumps(
        {"action": "complete", "answer": "done"},
    )

    assert await _refusal(answer) == "model_response_not_json"


@pytest.mark.asyncio
async def test_brace_inside_a_json_string_is_not_a_boundary() -> None:
    answer = json.dumps({"action": "complete", "answer": "a } { b"})

    decision = await _driver(answer).next_step(_Context(), None)

    assert decision.kind is AgentStepKind.COMPLETE
    assert decision.answer == "a } { b"


@pytest.mark.asyncio
async def test_conflicting_duplicate_action_is_refused() -> None:
    conflicting = ('{"action":"tool","tool_id":"' + PC_LIST_FILES_TOOL_ID
                   + '","arguments":{"path":"."},"action":"complete","answer":"done"}')

    assert await _refusal(conflicting) == "model_response_not_json"


@pytest.mark.asyncio
async def test_duplicate_argument_key_is_refused() -> None:
    duplicate = ('{"action":"tool","tool_id":"' + PC_LIST_FILES_TOOL_ID
                 + '","arguments":{"path":".","path":"elsewhere"}}')

    assert await _refusal(duplicate) == "model_response_not_json"


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
            max_steps=3, max_tool_calls=2, max_skill_calls=0, max_wall_seconds=60,
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
            max_steps_cap=3,
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


def _runtime_code(answer=None, *, raises=None) -> str:
    definition, compiled = _compiled()
    runtime = BoundedAgentRuntime(
        step_driver=_driver(answer, raises=raises),
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
        return raised.code
    raise AssertionError("the runtime must fail closed")


def test_detail_survives_driver_runtime_engine_and_telemetry() -> None:
    cases = {
        f"agent_step_failed.{detail}": answer
        for detail, answer in {
            "model_response_not_json": SENTINEL,
            "model_step_not_object": "42",
            "tool_selection_invalid": json.dumps(
                {"action": "tool", "tool_id": "claw.pc.format_disk", "arguments": {}}),
            "completion_answer_invalid": json.dumps({"action": "complete"}),
        }.items()
    }
    cases["agent_step_failed.model_call_failed"] = None

    for expected, answer in cases.items():
        # 1. Core runtime: the driver detail is no longer collapsed.
        code = _runtime_code(answer) if answer is not None else _runtime_code(raises=RuntimeError(SENTINEL))
        assert code == expected

        # 2. Engine API: the same code is the response's error.code at 400.
        response = OrchestrationEngineService._orchestration_run_error_response(
            OrchestrationError(code, "Agent step execution failed."),
        )
        assert response.status_code == 400
        assert response.body["error"]["code"] == expected

        # 3. Existing telemetry contract: the exported event carries it.
        state, token = stack_telemetry.start_trace(
            SimpleNamespace(method="POST", headers={"x-request-id": "req_synthetic"}),
            "padiem-ai-engine",
            "/internal/*",
        )
        try:
            stack_telemetry.record_refusal(400, response.body)
            events = stack_telemetry.make_events(state, 400)
        finally:
            stack_telemetry.reset_trace(token)
        assert events[0]["error_code"] == expected
        assert "SENTINEL" not in json.dumps(events)
        assert "private.txt" not in json.dumps(events)


def test_plain_step_error_keeps_the_generic_engine_code() -> None:
    driver = StructuredPCQueryStepDriver(
        select_step=_raise_plain_step_error,
    )
    definition, compiled = _compiled()
    runtime = BoundedAgentRuntime(
        step_driver=driver, tool_runtime=ToolRuntime(), id_factory=lambda: "fixed",
    )
    request = AgentRunRequest(
        definition=definition,
        compiled_profile=compiled,
        authorization=ToolAuthorizationContext(
            app_id="padiem-chat", agent_id=compiled.runtime_profile.id,
        ),
        input_text="list",
        run_id="run.synthetic",
    )
    with pytest.raises(AgentRuntimeError) as caught:
        asyncio.run(runtime.run(request))
    assert caught.value.code == "agent_step_failed"


async def _raise_plain_step_error(**_):
    raise PCQueryStepError("a detail outside the closed set", detail="not_in_the_set")


@pytest.mark.parametrize("outcome,status", [
    ("success", "ok"), ("http_error", "403"), ("exception", "error"), ("cancelled", "cancelled"),
])
@pytest.mark.asyncio
async def test_model_step_logs_bounded_completion_status_without_private_text(capsys, outcome, status):
    from padiem_ai_core.b14_execution import B14ExecutionError
    error = {
        "success": None,
        "http_error": B14ExecutionError("upstream_auth_error", SENTINEL, upstream_status_code=403),
        "exception": RuntimeError(SENTINEL),
        "cancelled": asyncio.CancelledError(SENTINEL),
    }[outcome]
    model = _FakeB14(answer=json.dumps({"action": "complete", "answer": SENTINEL}), raises=error)
    driver = build_live_pc_query_driver(b14_client=model, model_id="synthetic")
    if outcome == "success":
        await driver.next_step(_Context(), None)
    else:
        expected = asyncio.CancelledError if outcome == "cancelled" else PCQueryStepError
        with pytest.raises(expected):
            await driver.next_step(_Context(), None)
    assert model.calls == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["pc_step_select source=model", "pc_step_model_call stage=start",
                     "pc_step_model_call stage=done status=" + status]
    assert SENTINEL not in "\n".join(lines)
