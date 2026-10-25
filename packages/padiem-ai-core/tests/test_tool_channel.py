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
from padiem_ai_core.contracts import AgentProfile, ErrorClass, RunStatus
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
)
from padiem_ai_core.tool_channel import (
    ToolCall,
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
        model="b14/auto",
    ).to_payload()

    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_a_declared_tool_travels_with_the_request() -> None:
    payload = B14ChatRequest(
        messages=({"role": "user", "content": "화면을 만들어줘"},),
        model="b14/auto",
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
            model="b14/auto",
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
