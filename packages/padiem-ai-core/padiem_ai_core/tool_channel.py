"""Model-native tool-calling channel for the B14 execution contract (#5536).

The B14 execution contract was answer-only: a caller sent an agent profile and
messages and received an answer string. A generative-UI contract such as
``generateSandboxedUi`` cannot be expressed over an answer-only channel, because
the model's product is a *call*, not prose.

This module holds the neutral contract for that channel. It is deliberately
provider-shaped but provider-neutral in substance: the wire form is the
OpenAI-compatible ``tools``/``tool_choice``/``tool_calls`` layout that the
registered B14 providers already speak, and every part is normalized before it
is handed to a transport.

Nothing here executes a tool. A tool call travels out to the caller, the
caller runs it, and the caller returns the result through the same channel.
The contract carries the call, the identifier that ties a result to its call,
and the structured arguments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
import json
import re

# A tool name is a provider-side identifier, not free prose. The bound keeps a
# declared name small enough to travel as an identifier and rejects separators
# that a provider would silently rewrite.
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOOL_CALL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

MAX_TOOL_DEFINITIONS: int = 32
MAX_TOOL_NAME_CHARS: int = 64
MAX_TOOL_DESCRIPTION_CHARS: int = 2_000
MAX_TOOL_ARGUMENT_CHARS: int = 65_536
MAX_TOOL_RESULT_CHARS: int = 65_536
MAX_TOOL_CALLS: int = 16
MAX_TOOL_RESULTS: int = 16

_TOOL_CHOICE_KEYWORDS = frozenset({"auto", "none", "required"})


class ToolChannelError(ValueError):
    """A tool-channel contract violation. Never carries provider content."""


def _safe_tool_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ToolChannelError("tool name must be a string")
    name = value.strip()
    if not name or len(name) > MAX_TOOL_NAME_CHARS:
        raise ToolChannelError("tool name must be a non-empty bounded identifier")
    if not _TOOL_NAME_RE.fullmatch(name):
        raise ToolChannelError("tool name must be a safe identifier")
    return name


def _safe_tool_call_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ToolChannelError("tool call id must be a string")
    call_id = value.strip()
    if not call_id or len(call_id) > 128:
        raise ToolChannelError("tool call id must be a non-empty bounded identifier")
    if not _TOOL_CALL_ID_RE.fullmatch(call_id):
        raise ToolChannelError("tool call id must be a safe identifier")
    return call_id


def _freeze(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Freeze a JSON-ish mapping one level deep so a tool spec cannot mutate."""

    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = MappingProxyType(dict(item))
        elif isinstance(item, (list, tuple)):
            frozen[key] = tuple(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One callable tool the model is allowed to request.

    ``parameters`` is the JSON Schema of the tool's arguments. It is carried as
    data and never executed here; the schema is the contract the model reads
    and the caller's contract it answers.
    """

    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType(
            {"type": "object", "properties": MappingProxyType({})}
        )
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _safe_tool_name(self.name))
        if not isinstance(self.description, str):
            raise ToolChannelError("tool description must be a string")
        description = self.description.strip()
        if len(description) > MAX_TOOL_DESCRIPTION_CHARS:
            raise ToolChannelError("tool description exceeds the supported bound")
        object.__setattr__(self, "description", description)
        if not isinstance(self.parameters, Mapping):
            raise ToolChannelError("tool parameters must be a mapping")
        parameters = dict(self.parameters)
        declared_type = parameters.get("type")
        if declared_type is not None and declared_type != "object":
            raise ToolChannelError("tool parameters type must be 'object'")
        properties = parameters.get("properties")
        if properties is not None and not isinstance(properties, Mapping):
            raise ToolChannelError("tool parameters properties must be a mapping")
        required = parameters.get("required")
        if required is not None and (
            not isinstance(required, (list, tuple))
            or not all(isinstance(item, str) for item in required)
        ):
            raise ToolChannelError("tool parameters required must be a list of names")
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        object.__setattr__(self, "parameters", _freeze(parameters))

    def to_provider_schema(self) -> dict[str, Any]:
        """The OpenAI-compatible function schema for this tool."""

        function: dict[str, Any] = {
            "name": self.name,
            "parameters": {
                "type": self.parameters.get("type", "object"),
                "properties": dict(self.parameters.get("properties", {}) or {}),
            },
        }
        if "required" in self.parameters:
            function["parameters"]["required"] = list(self.parameters["required"])
        if self.description:
            function["description"] = self.description
        return {"type": "function", "function": function}

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call the model requested.

    ``arguments`` is the *parsed* argument object, never the raw JSON string the
    provider sends, so a consumer can read the call without re-parsing.
    """

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    type: str = "function"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _safe_tool_call_id(self.id))
        object.__setattr__(self, "name", _safe_tool_name(self.name))
        if not isinstance(self.arguments, Mapping):
            raise ToolChannelError("tool call arguments must be a mapping")
        object.__setattr__(self, "arguments", _freeze(self.arguments))
        if self.type != "function":
            raise ToolChannelError("tool call type must be 'function'")

    def to_provider_payload(self) -> dict[str, Any]:
        """The OpenAI-compatible assistant tool call entry."""

        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.name,
                "arguments": json.dumps(dict(self.arguments), ensure_ascii=False),
            },
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of a tool call, handed back to the model."""

    tool_call_id: str
    name: str
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_call_id", _safe_tool_call_id(self.tool_call_id))
        object.__setattr__(self, "name", _safe_tool_name(self.name))
        if not isinstance(self.content, str):
            raise ToolChannelError("tool result content must be a string")
        if len(self.content) > MAX_TOOL_RESULT_CHARS:
            raise ToolChannelError("tool result content exceeds the supported bound")
        object.__setattr__(self, "content", self.content)

    def to_message(self) -> dict[str, Any]:
        """The provider message that carries this result back to the model."""

        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }


def _parse_arguments(raw: Any, *, tool_name: str) -> Mapping[str, Any]:
    """Parse a provider's tool arguments into a structured object."""

    if raw is None:
        return MappingProxyType({})
    if isinstance(raw, Mapping):
        return _freeze(raw)
    if isinstance(raw, str):
        if len(raw) > MAX_TOOL_ARGUMENT_CHARS:
            raise ToolChannelError(
                f"tool call arguments for {tool_name!r} exceed the supported bound"
            )
        if not raw.strip():
            return MappingProxyType({})
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolChannelError(
                f"tool call arguments for {tool_name!r} are not valid JSON"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ToolChannelError(
                f"tool call arguments for {tool_name!r} must be a JSON object"
            )
        return _freeze(parsed)
    raise ToolChannelError(
        f"tool call arguments for {tool_name!r} must be a JSON object"
    )


def normalize_tool_definitions(
    raw: Sequence[Mapping[str, Any] | ToolDefinition] | None,
) -> tuple[ToolDefinition, ...]:
    """Normalize declared tools into the contract's tool definitions.

    Both the provider-shaped mapping (``{"type": "function", "function": {...}}``)
    and a :class:`ToolDefinition` are accepted, so a caller can build the
    declaration in whichever form it already holds.
    """

    if raw is None:
        return ()
    if isinstance(raw, (str, bytes, Mapping)):
        raise ToolChannelError("tools must be a sequence of tool definitions")
    items = tuple(raw)
    if not items:
        return ()
    if len(items) > MAX_TOOL_DEFINITIONS:
        raise ToolChannelError("too many tool definitions declared")

    definitions: list[ToolDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if isinstance(item, ToolDefinition):
            definition = item
        elif isinstance(item, Mapping):
            definition = _definition_from_provider_schema(item, index=index)
        else:
            raise ToolChannelError(f"tools[{index}] must be a mapping")
        if definition.name in seen:
            raise ToolChannelError(f"tools[{index}] duplicates a declared tool name")
        seen.add(definition.name)
        definitions.append(definition)
    return tuple(definitions)


def _definition_from_provider_schema(
    item: Mapping[str, Any], *, index: int
) -> ToolDefinition:
    declared_type = item.get("type", "function")
    if declared_type != "function":
        raise ToolChannelError(f"tools[{index}] must be a function tool")
    function = item.get("function")
    if not isinstance(function, Mapping):
        raise ToolChannelError(f"tools[{index}] must carry a function object")
    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolChannelError(f"tools[{index}] must carry a function name")
    description = function.get("description")
    parameters = function.get("parameters")
    if parameters is None:
        parameters = {"type": "object", "properties": {}}
    if not isinstance(parameters, Mapping):
        raise ToolChannelError(f"tools[{index}] parameters must be a mapping")
    return ToolDefinition(
        name=name,
        description=description if isinstance(description, str) else "",
        parameters=parameters,
    )


def normalize_tool_choice(
    raw: Any,
    *,
    declared: tuple[ToolDefinition, ...] = (),
) -> Any:
    """Normalize a tool choice into the provider's accepted shapes.

    ``"auto"``, ``"none"`` and ``"required"`` are keywords. A mapping names one
    declared function. A named function that was not declared is refused here
    rather than at the provider.
    """

    if raw is None:
        return None
    if isinstance(raw, str):
        choice = raw.strip()
        if choice not in _TOOL_CHOICE_KEYWORDS:
            raise ToolChannelError("tool choice must be auto, none or required")
        return choice
    if isinstance(raw, Mapping):
        declared_type = raw.get("type")
        if declared_type != "function":
            raise ToolChannelError("tool choice type must be 'function'")
        function = raw.get("function")
        if not isinstance(function, Mapping):
            raise ToolChannelError("tool choice must carry a function object")
        name = _safe_tool_name(function.get("name"))
        if declared and name not in {item.name for item in declared}:
            raise ToolChannelError("tool choice names an undeclared tool")
        return {"type": "function", "function": {"name": name}}
    raise ToolChannelError("tool choice must be a keyword or a mapping")


def normalize_tool_results(
    raw: Sequence[ToolResult | Mapping[str, Any]] | None,
) -> tuple[ToolResult, ...]:
    """Normalize the results of earlier tool calls."""

    if raw is None:
        return ()
    if isinstance(raw, (str, bytes, Mapping)):
        raise ToolChannelError("tool results must be a sequence")
    items = tuple(raw)
    if not items:
        return ()
    if len(items) > MAX_TOOL_RESULTS:
        raise ToolChannelError("too many tool results")

    results: list[ToolResult] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if isinstance(item, ToolResult):
            result = item
        elif isinstance(item, Mapping):
            call_id = item.get("tool_call_id")
            name = item.get("name")
            content = item.get("content")
            if not isinstance(content, str):
                raise ToolChannelError(f"tool_results[{index}] content must be a string")
            result = ToolResult(
                tool_call_id=call_id,  # type: ignore[arg-type]
                name=name,  # type: ignore[arg-type]
                content=content,
            )
        else:
            raise ToolChannelError(f"tool_results[{index}] must be a mapping")
        if result.tool_call_id in seen:
            raise ToolChannelError(
                f"tool_results[{index}] duplicates a tool call id"
            )
        seen.add(result.tool_call_id)
        results.append(result)
    return tuple(results)


def parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """Parse a provider's ``tool_calls`` array into structured tool calls."""

    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ToolChannelError("tool_calls must be an array")
    items = tuple(raw)
    if not items:
        return ()
    if len(items) > MAX_TOOL_CALLS:
        raise ToolChannelError("too many tool calls in one response")

    calls: list[ToolCall] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ToolChannelError(f"tool_calls[{index}] must be an object")
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolChannelError(f"tool_calls[{index}] must carry an id")
        call_type = item.get("type", "function")
        if call_type != "function":
            raise ToolChannelError(f"tool_calls[{index}] type must be 'function'")
        function = item.get("function")
        if not isinstance(function, Mapping):
            raise ToolChannelError(f"tool_calls[{index}] must carry a function object")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolChannelError(f"tool_calls[{index}] must carry a function name")
        arguments = _parse_arguments(function.get("arguments"), tool_name=name)
        call = ToolCall(id=call_id, name=name, arguments=arguments)
        if call.id in seen:
            raise ToolChannelError(f"tool_calls[{index}] duplicates a tool call id")
        seen.add(call.id)
        calls.append(call)
    return tuple(calls)


def tool_call_assistant_message(calls: Sequence[ToolCall]) -> dict[str, Any]:
    """The assistant message that carries tool calls back into a conversation."""

    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [call.to_provider_payload() for call in calls],
    }


def tool_result_messages(results: Sequence[ToolResult]) -> tuple[dict[str, Any], ...]:
    """The provider messages that carry tool results back to the model."""

    return tuple(result.to_message() for result in results)
