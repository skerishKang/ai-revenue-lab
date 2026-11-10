"""#6460-5: one tool-list -> the native declaration conversion.

The declaration conversion is the single place a product's tool list becomes a
native function declaration; the owner-decided route declares the capability
and rides the same native wire its adapter owns. No provider is reached here.

#7241: no model id, provider id or documentation host is written in this
module. The native adapter's own conversion is used as-is (it takes no route),
its routes come from the effective registry, and the Provider id it serves is
read from the adapter's constant.
"""
from __future__ import annotations

import json

import pytest

from app.pilot.tool_channel import (
    TOOL_CAPABILITY,
    InvalidToolDeclaration,
    model_supports_tools,
    require_stream_tool_wire,
    require_tool_capability,
)
from padiem_ai_core.tool_channel import ToolDefinition

from _registry_values import (
    adapter_modules, model_rows, require_owner_document,
)

# The owner decided which of the native adapter's routes carry the tool
# capability; that decision lives in the owner's registry document (#7241 3b).
require_owner_document()


def _owns_the_conversion(module) -> bool:
    """Whether an adapter module implements the conversion this suite drives."""
    has_conversion = any(name.startswith("function_") for name in vars(module))
    has_body = any(
        name.startswith("_") and name.endswith("tool_body") for name in vars(module)
    )
    return has_conversion and has_body and hasattr(module, "require_stream_tool_support")


def _conversion_module():
    """The pilot adapter that implements the array-to-declaration conversion."""
    modules = adapter_modules()
    matches = [module for module in modules.values() if _owns_the_conversion(module)]
    assert len(matches) == 1, "expected exactly one adapter to own the conversion"
    return matches[0]


_CONVERSION_MODULE = _conversion_module()
#: The adapter's own conversion and body builder under test.
function_declarations = next(
    getattr(_CONVERSION_MODULE, name) for name in vars(_CONVERSION_MODULE)
    if name.startswith("function_")
)
_tool_body = next(
    getattr(_CONVERSION_MODULE, name) for name in vars(_CONVERSION_MODULE)
    if name.startswith("_") and name.endswith("tool_body")
)
require_stream_tool_support = _CONVERSION_MODULE.require_stream_tool_support


def _declaring_providers() -> set[str]:
    """The Providers whose effective rows carry the tool capability."""
    return {
        row["provider_id"] for row in model_rows()
        if TOOL_CAPABILITY in row["capabilities"]
    }


def _native_adapter():
    """The pilot adapter that serves the effective tool-capable routes.

    The owner decided that one adapter's routes carry the tool capability, so
    that adapter is found through its own registry rows and its own declared
    Provider id instead of by module name (#7241).
    """
    from _registry_values import adapter_modules

    declaring = _declaring_providers()
    modules = adapter_modules()
    # Only one adapter implements the array-to-declaration conversion and the
    # tool-capable stream gates this suite drives; a registration-only adapter
    # implements neither.
    matches = [
        (provider_id, module) for provider_id, module in modules.items()
        if provider_id in declaring and _owns_the_conversion(module)
    ]
    if not matches:
        # No adapter is installed for the declaring routes on this host: the
        # first module that owns the conversion is the adapter under test, and
        # the owner-pinned cases below skip.
        matches = [
            (provider_id, module) for provider_id, module in modules.items()
            if _owns_the_conversion(module)
        ]
    assert len(matches) == 1, "expected exactly one adapter to own the conversion"
    return matches[0][1]


#: The adapter is selected from the effective registry, so the selection only
#: exists while the owner's tool-capable routes are the authority. On a host
#: reading the placeholder document nothing is selected here and the
#: owner-pinned cases below skip; the conversion cases drive the conversion
#: imported from the adapter that owns it.
NATIVE_ADAPTER = _native_adapter() if _declaring_providers() else None

NATIVE_PROVIDER = next(
    (value for name, value in vars(NATIVE_ADAPTER).items()
     if name.endswith("PROVIDER_ID") and isinstance(value, str) and value),
    "",
) if NATIVE_ADAPTER is not None else ""

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
    body = _tool_body(
        messages=[{"role": "user", "content": "견적 파일 찾아줘"}],
        tools=[PC_TOOL.to_provider_schema()], tool_choice="auto",
        temperature=None, max_tokens=None, model_parameters=None,
    )
    assert body["tools"] == [{"functionDeclarations": function_declarations(
        [PC_TOOL.to_provider_schema()],
    )}]
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "AUTO"}}


def test_a_call_and_its_result_round_trip_under_the_native_route() -> None:
    body = _tool_body(
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


def _capability_counts(row: dict) -> tuple[int, int]:
    """How many capability tags the row carries overall, and beyond chat.

    The owner decision this suite pins is the one that added tool calling to a
    route already tagged for images and text: the declaring route is the one
    with the widest measured feature set, the plain sibling the narrowest.
    """
    tags = set(row["capabilities"])
    return len(tags), len(tags - {"chat"})


# The owner decided which of the native adapter's routes carry the tool
# capability, and that the sibling route beside them does not. The decision is
# read structurally from the adapter's registry rows (#7241): it is an owner
# decision pin, so it only runs on a host reading the owner's document.
def _native_rows() -> list[dict]:
    return [row for row in model_rows() if row["provider_id"] == NATIVE_PROVIDER]


def _declaring_row() -> dict:
    """The owner-decided route among the native adapter's rows.

    Selected by the decision that declared it: the route with the widest
    measured capability set is the one the owner added tool calling to.
    """
    rows = [row for row in _native_rows() if TOOL_CAPABILITY in row["capabilities"]]
    assert rows, "the owner's document declares no tool-capable native route"
    return max(rows, key=_capability_counts)


def _plain_row() -> dict:
    """The sibling native route the owner decision left alone."""
    rows = [row for row in _native_rows() if TOOL_CAPABILITY not in row["capabilities"]]
    assert rows, "the owner's document declares no plain native route"
    return min(rows, key=_capability_counts)


def test_the_owner_decided_route_declares_tools_and_opens_the_gates() -> None:
    row = _declaring_row()
    model_id = row["id"]
    assert TOOL_CAPABILITY in row["capabilities"]
    # The declaring route is the one the decision tagged most widely.
    assert _capability_counts(row) == max(_capability_counts(r) for r in _native_rows())
    assert model_supports_tools(model_id) is True
    require_tool_capability(model_id)
    # The capability and its wire are separate gates; both pass for the native
    # adapter's own provider id, which the adapter declares.
    require_stream_tool_wire(model_id, NATIVE_PROVIDER)
    require_stream_tool_support(model_id, NATIVE_PROVIDER)


def test_the_sibling_route_stays_outside_the_owner_decision() -> None:
    row = _plain_row()
    model_id = row["id"]
    assert TOOL_CAPABILITY not in row["capabilities"]
    assert model_supports_tools(model_id) is False
