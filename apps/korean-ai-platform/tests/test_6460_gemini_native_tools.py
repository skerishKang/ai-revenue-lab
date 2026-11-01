"""#6460-5: one tool-list -> Gemini functionDeclarations conversion, Gemma tools.

The declaration conversion is the single place a product's tool list becomes a
Gemini declaration; the Gemma route declares the same capability the owner
decided and rides the same native wire. No provider is reached here.
"""
from __future__ import annotations

import json

import pytest

from app.pilot.google_provider import _google_tool_body, function_declarations
from app.pilot.model_registry_file import read_registry
from app.pilot.tool_channel import (
    InvalidToolDeclaration,
    model_supports_tools,
    require_stream_tool_wire,
    require_tool_capability,
)
from padiem_ai_core.tool_channel import ToolDefinition

GEMMA = "google/gemma-4-31b-it"
PLAIN = "google/gemma-4-26b-a4b-it"

PC_TOOL = ToolDefinition(
    name="search_files",
    description="Find files whose NAME contains the text.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "path": {"type": "string", "maxLength": 2048},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


def test_the_one_conversion_turns_a_contract_tool_into_a_declaration() -> None:
    declared = function_declarations([PC_TOOL.to_provider_schema()])
    assert declared == [{
        "name": "search_files",
        "description": "Find files whose NAME contains the text.",
        "parametersJsonSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "path": {"type": "string", "maxLength": 2048},
            },
            "required": ["query"],
        },
    }]
    # The contract's own schema is carried verbatim; `additionalProperties` is
    # a contract rule the caller's tool definition owns, and the conversion
    # neither adds nor drops a declared contract field it was not given.
    assert "additionalProperties" not in declared[0]["parametersJsonSchema"]


def test_the_body_uses_that_same_conversion() -> None:
    body = _google_tool_body(
        messages=[{"role": "user", "content": "견적 파일 찾아줘"}],
        tools=[PC_TOOL.to_provider_schema()], tool_choice="auto",
        temperature=None, max_tokens=None, model_parameters=None,
    )
    assert body["tools"] == [{"functionDeclarations": function_declarations(
        [PC_TOOL.to_provider_schema()],
    )}]
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "AUTO"}}


def test_a_call_and_its_result_round_trip_under_the_gemma_route() -> None:
    body = _google_tool_body(
        messages=[
            {"role": "user", "content": "견적 파일 찾아줘"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "search_files",
                             "arguments": json.dumps({"query": "견적"},
                                                     ensure_ascii=False)},
            }]},
            {"role": "tool", "tool_call_id": "call_1", "name": "search_files",
             "content": '{"ok":true,"count":1}'},
        ],
        tools=[PC_TOOL.to_provider_schema()], tool_choice=None,
        temperature=None, max_tokens=None, model_parameters=None,
    )
    assert body["contents"][1]["parts"][0]["functionCall"] == {
        "id": "call_1", "name": "search_files", "args": {"query": "견적"},
    }
    assert body["contents"][2]["parts"][0]["functionResponse"] == {
        "id": "call_1", "name": "search_files",
        "response": {"result": '{"ok":true,"count":1}'},
    }


def test_a_bad_declaration_is_refused_by_the_same_conversion() -> None:
    with pytest.raises(InvalidToolDeclaration):
        function_declarations([{"type": "function", "function": {"name": "bad name"}}])
    with pytest.raises(InvalidToolDeclaration):
        function_declarations([PC_TOOL.to_provider_schema(),
                               PC_TOOL.to_provider_schema()])


def test_gemma_31b_declares_tools_in_the_registry_and_opens_the_gates() -> None:
    row = next(r for r in read_registry()["models"] if r["id"] == GEMMA)
    assert "tools" in row["capabilities"]
    assert "https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api" in row["source"]
    assert model_supports_tools(GEMMA) is True
    require_tool_capability(GEMMA)
    require_stream_tool_wire(GEMMA, "google")
    # The sibling Gemma route is untouched by the owner decision.
    plain = next(r for r in read_registry()["models"] if r["id"] == PLAIN)
    assert "tools" not in plain["capabilities"]
    assert model_supports_tools(PLAIN) is False
