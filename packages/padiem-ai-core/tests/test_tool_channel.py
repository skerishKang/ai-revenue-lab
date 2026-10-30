"""The model-native tool channel of the B14 execution contract (#5536).

These tests cover the contract itself: the tool declaration, the tool choice,
the structured call the model returns, and the round trip that hands the tool
result back to the model for its final answer.

The channel is opt-in. A request that declares no tool keeps the exact
pre-#5536 request and answer shape, and that is asserted here too.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
)
from padiem_ai_core.contracts import AgentProfile, ErrorClass, RunStatus, ToolEvent
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
)
from padiem_ai_core.tool_channel import (
    ToolCall,
    ToolChannelError,
    ToolDefinition,
    ToolResult,
    normalize_tool_choice,
    normalize_tool_definitions,
    parse_tool_calls,
    tool_call_assistant_message,
)


def run(coro):
    return asyncio.run(coro)


class FakeExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result if result is not None else B14ExecutionResult(answer="ok")
        self.error = error
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-agent",
        "title": "General",
        "description": "General product-neutral agent",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("free",),
        "model_policy": {"model": "test/route"},
    }
    values.update(overrides)
    return AgentProfile(**values)


DESIGNER_TOOL = {
    "type": "function",
    "function": {
        "name": "generateSandboxedUi",
        "description": "Generate the interactive UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "css": {"type": "string"},
                "html": {"type": "string"},
            },
            "required": ["css", "html"],
        },
    },
}


# ---------------------------------------------------------------------------
# The tool declaration
# ---------------------------------------------------------------------------


def test_provider_schema_becomes_a_tool_definition() -> None:
    definitions = normalize_tool_definitions([DESIGNER_TOOL])

    assert len(definitions) == 1
    definition = definitions[0]
    assert definition.name == "generateSandboxedUi"
    assert definition.description == "Generate the interactive UI."
    assert list(definition.parameters["required"]) == ["css", "html"]
    assert definition.parameters["properties"]["css"]["type"] == "string"


def test_tool_definition_round_trips_to_the_provider_schema() -> None:
    definition = normalize_tool_definitions([DESIGNER_TOOL])[0]

    assert definition.to_provider_schema() == {
        "type": "function",
        "function": {
            "name": "generateSandboxedUi",
            "parameters": {
                "type": "object",
                "properties": {
                    "css": {"type": "string"},
                    "html": {"type": "string"},
                },
                "required": ["css", "html"],
            },
            "description": "Generate the interactive UI.",
        },
    }


@pytest.mark.parametrize(
    "broken",
    [
        {"type": "not_a_function", "function": {"name": "x"}},
        {"type": "function"},
        {"type": "function", "function": {"name": "bad name!"}},
        {"type": "function", "function": {"name": "x", "parameters": "nope"}},
        {"type": "function", "function": {"name": "x", "parameters": {"type": "array"}}},
    ],
)
def test_a_malformed_tool_declaration_is_refused(broken) -> None:
    with pytest.raises(ValueError):
        normalize_tool_definitions([broken])


def test_two_tools_with_the_same_name_are_refused() -> None:
    with pytest.raises(ValueError):
        normalize_tool_definitions([DESIGNER_TOOL, DESIGNER_TOOL])


def test_a_tool_choice_must_name_a_declared_tool() -> None:
    definitions = normalize_tool_definitions([DESIGNER_TOOL])

    assert normalize_tool_choice("auto", declared=definitions) == "auto"
    assert normalize_tool_choice("required", declared=definitions) == "required"
    with pytest.raises(ValueError):
        normalize_tool_choice(
            {"type": "function", "function": {"name": "otherTool"}},
            declared=definitions,
        )


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


def test_a_request_without_a_tool_keeps_the_previous_payload_shape() -> None:
    payload = B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="fixture/explicit-model",
    ).to_payload()

    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_a_declared_tool_travels_with_the_request() -> None:
    payload = B14ChatRequest(
        messages=({"role": "user", "content": "화면을 만들어줘"},),
        model="fixture/explicit-model",
        tools=(DESIGNER_TOOL,),
        tool_choice={"type": "function", "function": {"name": "generateSandboxedUi"}},
    ).to_payload()

    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "generateSandboxedUi",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "css": {"type": "string"},
                        "html": {"type": "string"},
                    },
                    "required": ["css", "html"],
                },
                "description": "Generate the interactive UI.",
            },
        }
    ]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "generateSandboxedUi"},
    }


def test_a_tool_choice_without_a_tool_is_refused() -> None:
    with pytest.raises(ValueError):
        B14ChatRequest(
            messages=({"role": "user", "content": "hi"},),
            model="fixture/explicit-model",
            tool_choice="auto",
        )


def test_the_execution_request_carries_the_tool_declaration() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    run(
        runtime.run(
            ExecutionRequest(
                agent=agent(),
                messages=({"role": "user", "content": "화면을 만들어줘"},),
                tools=(DESIGNER_TOOL,),
            )
        )
    )

    payload = executor.calls[0].to_payload()
    assert payload["tools"][0]["function"]["name"] == "generateSandboxedUi"


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


def test_a_tool_call_is_parsed_into_a_structured_call() -> None:
    calls = parse_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "generateSandboxedUi",
                    "arguments": json.dumps({"css": "p{}", "html": "<p>hi</p>"}),
                },
            }
        ]
    )

    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "generateSandboxedUi"
    # The arguments are structured, not a JSON string the consumer must parse.
    assert calls[0].arguments == {"css": "p{}", "html": "<p>hi</p>"}


def test_an_opaque_call_signature_survives_the_contract_round_trip() -> None:
    calls = parse_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "signature": "sig_native_abc123",
                "function": {
                    "name": "generateSandboxedUi",
                    "arguments": json.dumps({"html": "<p>hi</p>"}),
                },
            }
        ]
    )

    assert calls[0].signature == "sig_native_abc123"
    # A native follow-up must receive the token unchanged, and the public
    # projection must not hide it from the caller that replays the call.
    assert tool_call_assistant_message(calls)["tool_calls"][0]["signature"] == "sig_native_abc123"
    assert calls[0].to_public_dict()["signature"] == "sig_native_abc123"


def test_a_call_without_a_signature_keeps_its_exact_provider_shape() -> None:
    calls = parse_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "generateSandboxedUi", "arguments": "{}"},
            }
        ]
    )

    assert calls[0].signature is None
    assert "signature" not in tool_call_assistant_message(calls)["tool_calls"][0]
    assert "signature" not in calls[0].to_public_dict()


def test_a_malformed_call_signature_is_refused() -> None:
    from padiem_ai_core.tool_channel import MAX_TOOL_SIGNATURE_CHARS

    for signature in (123, "", "x" * (MAX_TOOL_SIGNATURE_CHARS + 1)):
        with pytest.raises(ValueError):
            parse_tool_calls(
                [
                    {
                        "id": "call_1",
                        "type": "function",
                        "signature": signature,
                        "function": {"name": "generateSandboxedUi", "arguments": "{}"},
                    }
                ]
            )


def test_a_tool_call_with_broken_arguments_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_tool_calls(
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "generateSandboxedUi", "arguments": "{not json"},
                }
            ]
        )


def test_a_tool_call_answer_is_carried_to_the_caller() -> None:
    call = ToolCall(
        id="call_1",
        name="generateSandboxedUi",
        arguments={"css": "p{}", "html": "<p>hi</p>"},
    )
    executor = FakeExecutor(
        result=B14ExecutionResult(answer="", tool_calls=(call,)),
    )
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    result = run(
        runtime.run(
            ExecutionRequest(
                agent=agent(),
                messages=({"role": "user", "content": "화면을 만들어줘"},),
                tools=(DESIGNER_TOOL,),
            )
        )
    )

    assert result.answer == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].arguments == {"css": "p{}", "html": "<p>hi</p>"}


def test_a_text_answer_carries_no_tool_call() -> None:
    executor = FakeExecutor(result=B14ExecutionResult(answer="완료"))
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    result = run(
        runtime.run(
            ExecutionRequest(
                agent=agent(),
                messages=({"role": "user", "content": "안녕하세요"},),
            )
        )
    )

    assert result.answer == "완료"
    assert result.tool_calls == ()


def test_an_empty_answer_without_a_tool_call_is_still_refused() -> None:
    with pytest.raises(ValueError):
        ExecutionResult(
            answer="",
            route=B14RouteMetadata(),
            metadata=_metadata(),
        )


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


def test_the_tool_result_travels_back_to_the_model() -> None:
    executor = FakeExecutor(result=B14ExecutionResult(answer="완료"))
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    call = ToolCall(
        id="call_1",
        name="generateSandboxedUi",
        arguments={"css": "p{}", "html": "<p>hi</p>"},
    )

    run(
        runtime.run(
            ExecutionRequest(
                agent=agent(),
                messages=(
                    {"role": "user", "content": "화면을 만들어줘"},
                    tool_call_assistant_message((call,)),
                ),
                tools=(DESIGNER_TOOL,),
                tool_results=(
                    ToolResult(
                        tool_call_id="call_1",
                        name="generateSandboxedUi",
                        content='{"ok":true}',
                    ),
                ),
            )
        )
    )

    payload = executor.calls[0].to_payload()
    tool_messages = [m for m in payload["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[0]["content"] == '{"ok":true}'
    # The assistant turn that requested the call is part of the conversation.
    assistant = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant[0]["tool_calls"][0]["id"] == "call_1"


def test_a_tool_result_without_its_call_is_refused() -> None:
    with pytest.raises(ValueError):
        ExecutionRequest(
            agent=agent(),
            messages=({"role": "user", "content": "화면을 만들어줘"},),
            tools=(DESIGNER_TOOL,),
            tool_results=(
                ToolResult(
                    tool_call_id="call_missing",
                    name="generateSandboxedUi",
                    content="{}",
                ),
            ),
        )


def test_a_tool_call_for_an_undeclared_tool_is_refused() -> None:
    call = ToolCall(id="call_1", name="otherTool", arguments={})

    with pytest.raises(ValueError):
        ExecutionRequest(
            agent=agent(),
            messages=(
                {"role": "user", "content": "화면을 만들어줘"},
                tool_call_assistant_message((call,)),
            ),
            tools=(DESIGNER_TOOL,),
        )


# ---------------------------------------------------------------------------
# The agent allowlist
# ---------------------------------------------------------------------------


def test_an_agent_allowlist_narrows_the_declared_tools() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(
            runtime.run(
                ExecutionRequest(
                    agent=agent(allowed_tools=("web_search",)),
                    messages=({"role": "user", "content": "화면을 만들어줘"},),
                    tools=(DESIGNER_TOOL,),
                )
            )
        )

    assert info.value.code == "tool_not_allowed"
    assert info.value.metadata.status is RunStatus.POLICY_BLOCKED
    assert executor.calls == []


def test_an_agent_allowlist_without_a_declared_tool_is_still_refused() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(
            runtime.run(
                ExecutionRequest(
                    agent=agent(allowed_tools=("web_search",)),
                    messages=({"role": "user", "content": "안녕하세요"},),
                )
            )
        )

    assert info.value.code == "native_tools_unsupported"
    assert executor.calls == []


def _metadata() -> "object":
    from padiem_ai_core.contracts import RunMetadata

    return RunMetadata(
        trace_id="trace-1",
        app_id="test-app",
        agent_id="general-agent",
        status=RunStatus.COMPLETED,
    )


def test_an_upstream_tool_call_malformation_is_reported_as_upstream_failure() -> None:
    executor = FakeExecutor(
        error=B14ExecutionError(
            "malformed_upstream",
            "Business 14 returned an invalid tool call.",
            diagnostic_class="upstream_invalid_tool_call",
        )
    )
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(
            runtime.run(
                ExecutionRequest(
                    agent=agent(),
                    messages=({"role": "user", "content": "화면을 만들어줘"},),
                    tools=(DESIGNER_TOOL,),
                )
            )
        )

    assert info.value.code == "malformed_upstream"
    assert info.value.metadata.error_class is ErrorClass.PROVIDER_BAD_RESPONSE


# ---------------------------------------------------------------------------
# #4727: the token a provider attached to a turn, and the outcome an executor
# actually reported. Both travel unchanged; neither is invented here.
# ---------------------------------------------------------------------------


def test_an_assistant_turn_carries_the_token_of_its_own_answer_text() -> None:
    calls = parse_tool_calls([
        {"id": "call_1", "function": {"name": "pc_files", "arguments": "{}"},
         "signature": "sig_call"},
    ])

    message = tool_call_assistant_message(calls, signature="sig_turn")

    assert message["signature"] == "sig_turn"
    assert message["tool_calls"][0]["signature"] == "sig_call"
    # Without a turn token the message keeps its exact pre-#4727 shape.
    assert "signature" not in tool_call_assistant_message(calls)


def test_a_replayed_turn_token_survives_the_request_contract() -> None:
    request = B14ChatRequest(
        model="google/gemini-3.1-flash-lite",
        messages=[
            {"role": "user", "content": "파일 내용을 알려줘"},
            {"role": "assistant", "content": "읽어 보겠습니다.",
             "signature": "sig_turn", "tool_calls": [{
                 "id": "call_1", "type": "function",
                 "function": {"name": "pc_files",
                              "arguments": json.dumps({"path": "a.txt"})},
                 "signature": "sig_call",
             }]},
            {"role": "tool", "tool_call_id": "call_1", "name": "pc_files",
             "content": "hello"},
        ],
    )

    turn = request.to_payload()["messages"][1]
    assert turn["signature"] == "sig_turn"
    assert turn["tool_calls"][0]["signature"] == "sig_call"


def test_a_turn_token_needs_the_answer_text_it_belongs_to() -> None:
    for content in (None, ""):
        with pytest.raises(ValueError):
            B14ChatRequest(
                model="google/gemini-3.1-flash-lite",
                messages=[
                    {"role": "user", "content": "파일"},
                    {"role": "assistant", "content": content,
                     "signature": "sig_turn",
                     "tool_calls": [{
                         "id": "call_1", "type": "function",
                         "function": {"name": "pc_files", "arguments": "{}"},
                     }]},
                ],
            )


def _event(status: RunStatus, *, error_class=None, error_code=None) -> ToolEvent:
    return ToolEvent(tool_id="pc_files", status=status, error_class=error_class,
                     error_code=error_code)


def _result(event: ToolEvent, *, content: str = "hello") -> ToolResult:
    return ToolResult.from_execution(
        tool_call_id="call_1", name="pc_files", content=content, event=event,
    )


def test_a_completed_run_stays_the_message_it_always_was() -> None:
    result = _result(_event(RunStatus.COMPLETED))

    assert result.completed is True
    # The outcome block is what separates a failure; a completion needs none, so
    # the ordinary round trip keeps its exact pre-#4727 message.
    assert result.to_message() == {
        "role": "tool", "tool_call_id": "call_1", "name": "pc_files",
        "content": "hello",
    }
    # The executor still keeps its own record of the run.
    assert result.to_public_dict()["execution"]["status"] == "completed"


@pytest.mark.parametrize("event,expected", [
    (_event(RunStatus.REJECTED, error_code="approval_denied"), "rejected"),
    (_event(RunStatus.POLICY_BLOCKED, error_class=ErrorClass.POLICY_BLOCKED,
            error_code="tool_auth_scope_missing"), "policy_blocked"),
    (_event(RunStatus.FAILED, error_class=ErrorClass.TOOL_RUNTIME_ERROR,
            error_code="pc_query_unavailable"), "failed"),
    (_event(RunStatus.FAILED, error_code="cancelled"), "failed"),
])
def test_a_refused_or_failed_run_travels_as_what_it_was(event, expected) -> None:
    assert event.status.value == expected
    result = _result(event)

    assert result.completed is False
    message = result.to_message()
    assert message["execution"]["status"] == expected
    assert message["execution"]["error_code"] == event.error_code


def test_five_non_completions_are_five_different_facts() -> None:
    events = [
        _event(RunStatus.REJECTED, error_code="approval_denied"),
        _event(RunStatus.POLICY_BLOCKED, error_class=ErrorClass.POLICY_BLOCKED),
        _event(RunStatus.FAILED, error_code="pc_query_unavailable"),
        _event(RunStatus.FAILED, error_code="cancelled"),
        _event(RunStatus.TIMEOUT, error_class=ErrorClass.PROVIDER_TIMEOUT,
               error_code="stream_timeout"),
    ]

    projections = [
        json.dumps(_result(event).to_message()["execution"], sort_keys=True)
        for event in events
    ]
    assert len(set(projections)) == 5
    # A timed-out run keeps the status the executor recorded, so the model is not
    # told it failed when the budget ran out.
    assert _result(events[-1]).to_message()["execution"] == {
        "tool_id": "pc_files", "status": "timeout",
        "error_class": "provider_timeout", "error_code": "stream_timeout",
    }


def test_a_refusal_does_not_have_to_invent_prose() -> None:
    result = _result(
        _event(RunStatus.REJECTED, error_code="approval_denied"), content="",
    )

    assert result.to_message()["content"] == ""
    assert result.to_message()["execution"]["status"] == "rejected"


def test_a_completion_still_owes_the_model_its_text() -> None:
    with pytest.raises(ValueError):
        _result(_event(RunStatus.COMPLETED), content="")
    with pytest.raises(ValueError):
        ToolResult(tool_call_id="call_1", name="pc_files", content="")


def test_a_non_completion_must_name_its_cause() -> None:
    with pytest.raises(ToolChannelError):
        _result(_event(RunStatus.FAILED))


def test_the_outcome_vocabulary_is_the_executors_own() -> None:
    for bogus in ({"status": "banana"}, {"status": 1}, {"status": None}):
        with pytest.raises(ToolChannelError):
            ToolResult(tool_call_id="call_1", name="pc_files", content="x",
                       execution=bogus)
    with pytest.raises(ToolChannelError):
        ToolResult(tool_call_id="call_1", name="pc_files", content="x",
                   execution={"status": "failed", "error_code": "x",
                              "http_status": 500})


def test_a_result_message_replayed_through_the_request_contract_keeps_its_fact() -> None:
    result = _result(_event(RunStatus.FAILED, error_code="cancelled"))

    request = B14ChatRequest(
        model="google/gemini-3.1-flash-lite",
        messages=[
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "pc_files", "arguments": "{}"},
            }]},
            result.to_message(),
        ],
    )

    carried = request.to_payload()["messages"][2]
    assert carried["execution"]["error_code"] == "cancelled"
    assert carried["execution"]["status"] == "failed"
