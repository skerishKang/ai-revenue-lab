"""Server-side tool-calling contract for the Business 14 gateway (#5536).

The gateway validates the tool declaration, the tool choice and the tool
messages of an incoming request, and it decides whether the routed model may
serve a tool call at all.

Two rules shape this module:

* The tool declaration is validated *before* any provider call, so a malformed
  declaration never reaches a provider and never spends a credential.
* Tool support is a property of the routed model, read from the canonical
  ``b14_models.json`` registry. A request that declares a tool for a model
  that cannot serve one is refused before execution, with the model named.

Nothing here executes a tool. The gateway relays a tool call to its caller.
"""

from __future__ import annotations

from typing import Any

from app.pilot.errors import PilotError, StreamNotSupported, ToolsNotSupported

# The registry capability tag that marks a model able to serve tool calls.
TOOL_CAPABILITY = "tools"
# The provider whose models are served by the OpenCode Go wire adapter.
GO_PROVIDER_ID = "opencode-go"

# A tool name is a provider-side identifier. The bound and the character set
# keep a declared name small and predictable.
_TOOL_NAME_MAX = 64
_TOOL_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_TOOL_CALL_ID_MAX = 128
_TOOL_CALL_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)

MAX_TOOL_DEFINITIONS = 32
MAX_TOOL_CALLS = 16
# A call's arguments are the only part of a provider answer a caller may act
# on. The bound matches the Core execution contract's own limit, so B14 refuses
# an oversized call at the edge instead of relaying a payload its consumer
# would reject after the credential was already spent.
MAX_TOOL_ARGUMENT_CHARS = 65_536
# #4727: a provider-opaque continuation token (Gemini thought signature). It is
# relayed verbatim and never interpreted; the bound keeps a native follow-up
# inside the same payload envelope as the call it continues.
MAX_TOOL_SIGNATURE_CHARS = 65_536

_TOOL_CHOICE_KEYWORDS = frozenset({"auto", "none", "required"})

_VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})


class InvalidToolDeclaration(PilotError):
    """A malformed tool declaration, tool choice or tool message → HTTP 422."""

    def __init__(self, message: str) -> None:
        super().__init__(code="invalid_body", message=message, status_code=422)


def _is_safe_identifier(value: Any, allowed: frozenset[str], limit: int) -> bool:
    if not isinstance(value, str) or not value or len(value) > limit:
        return False
    if not value[0].isalnum():
        return False
    return all(char in allowed for char in value)


def validate_tools(raw: Any) -> list[dict[str, Any]]:
    """Validate a declared tool list into the provider's function schema.

    The result is the exact shape a provider expects, so the gateway can relay
    it without guessing. An empty list means no tool was declared.
    """

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidToolDeclaration("tools must be an array or null")
    if not raw:
        return []
    if len(raw) > MAX_TOOL_DEFINITIONS:
        raise InvalidToolDeclaration("too many tools declared")

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InvalidToolDeclaration(f"tools[{index}] must be a JSON object")
        declared_type = item.get("type", "function")
        if declared_type != "function":
            raise InvalidToolDeclaration(f"tools[{index}] must be a function tool")
        function = item.get("function")
        if not isinstance(function, dict):
            raise InvalidToolDeclaration(
                f"tools[{index}] must carry a function object"
            )
        name = function.get("name")
        if not _is_safe_identifier(name, _TOOL_NAME_CHARS, _TOOL_NAME_MAX):
            raise InvalidToolDeclaration(
                f"tools[{index}] must carry a safe function name"
            )
        if name in seen:
            raise InvalidToolDeclaration(
                f"tools[{index}] duplicates a declared tool name"
            )
        seen.add(name)

        description = function.get("description")
        if description is not None and not isinstance(description, str):
            raise InvalidToolDeclaration(
                f"tools[{index}] description must be a string"
            )
        parameters = function.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        if not isinstance(parameters, dict):
            raise InvalidToolDeclaration(
                f"tools[{index}] parameters must be a JSON object"
            )
        parameter_type = parameters.get("type")
        if parameter_type is not None and parameter_type != "object":
            raise InvalidToolDeclaration(
                f"tools[{index}] parameters type must be 'object'"
            )
        properties = parameters.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise InvalidToolDeclaration(
                f"tools[{index}] parameters properties must be a JSON object"
            )
        required = parameters.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(item, str) for item in required)
        ):
            raise InvalidToolDeclaration(
                f"tools[{index}] parameters required must be an array of names"
            )

        schema: dict[str, Any] = {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": dict(properties or {}),
            },
        }
        if required is not None:
            schema["parameters"]["required"] = list(required)
        if isinstance(description, str) and description.strip():
            schema["description"] = description.strip()
        validated.append({"type": "function", "function": schema})
    return validated


def validate_tool_choice(raw: Any, declared: list[dict[str, Any]]) -> Any:
    """Validate a tool choice against the declared tools.

    A named tool choice must name a tool that was declared, so a request
    cannot ask the provider for a tool the model was never told about.
    """

    if raw is None:
        return None
    if isinstance(raw, str):
        choice = raw.strip()
        if choice not in _TOOL_CHOICE_KEYWORDS:
            raise InvalidToolDeclaration(
                "tool_choice must be auto, none or required"
            )
        return choice
    if not isinstance(raw, dict):
        raise InvalidToolDeclaration(
            "tool_choice must be a keyword or a JSON object"
        )
    if raw.get("type") != "function":
        raise InvalidToolDeclaration("tool_choice type must be 'function'")
    function = raw.get("function")
    if not isinstance(function, dict):
        raise InvalidToolDeclaration("tool_choice must carry a function object")
    name = function.get("name")
    if not _is_safe_identifier(name, _TOOL_NAME_CHARS, _TOOL_NAME_MAX):
        raise InvalidToolDeclaration("tool_choice must carry a safe function name")
    declared_names = {item["function"]["name"] for item in declared}
    if name not in declared_names:
        raise InvalidToolDeclaration("tool_choice names an undeclared tool")
    return {"type": "function", "function": {"name": name}}


def _call_signature(call: dict[str, Any], index: int) -> str | None:
    """The opaque continuation token a provider attached to one call.

    B14's canonical field is ``signature``. Google's OpenAI-compatible wire
    returns the same value at ``extra_content.google.thought_signature``, so a
    caller echoing that message verbatim is accepted as well. The value is
    never parsed; only its shape is bounded here.
    """

    signature = call.get("signature")
    if signature is None:
        extra = call.get("extra_content")
        google = extra.get("google") if isinstance(extra, dict) else None
        if isinstance(google, dict):
            signature = google.get("thought_signature")
    if signature is None:
        return None
    if (
        not isinstance(signature, str)
        or not signature.strip()
        or len(signature) > MAX_TOOL_SIGNATURE_CHARS
    ):
        raise InvalidToolDeclaration(
            f"messages[{index}] tool call signature must be a bounded string"
        )
    return signature


def validate_tool_calls(raw: Any, index: int) -> list[dict[str, Any]]:
    """Validate the tool calls carried by an assistant turn."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidToolDeclaration(
            f"messages[{index}].tool_calls must be an array"
        )
    if not raw:
        raise InvalidToolDeclaration(
            f"messages[{index}].tool_calls must not be empty"
        )
    if len(raw) > MAX_TOOL_CALLS:
        raise InvalidToolDeclaration(
            f"messages[{index}] carries too many tool calls"
        )

    validated: list[dict[str, Any]] = []
    for call_index, call in enumerate(raw):
        if not isinstance(call, dict):
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] must be a JSON object"
            )
        call_id = call.get("id")
        if not _is_safe_identifier(call_id, _TOOL_CALL_ID_CHARS, _TOOL_CALL_ID_MAX):
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] must carry a safe id"
            )
        call_type = call.get("type", "function")
        if call_type != "function":
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] type must be 'function'"
            )
        function = call.get("function")
        if not isinstance(function, dict):
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] must carry a function object"
            )
        name = function.get("name")
        if not _is_safe_identifier(name, _TOOL_NAME_CHARS, _TOOL_NAME_MAX):
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] must carry a safe name"
            )
        arguments = function.get("arguments")
        if arguments is not None and not isinstance(arguments, str):
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] arguments must be a JSON string"
            )
        if isinstance(arguments, str) and len(arguments) > MAX_TOOL_ARGUMENT_CHARS:
            raise InvalidToolDeclaration(
                f"messages[{index}].tool_calls[{call_index}] arguments are too large"
            )
        signature = _call_signature(call, index)
        entry = {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments if arguments is not None else "{}",
            },
        }
        if signature is not None:
            entry["signature"] = signature
        validated.append(entry)
    return validated


def validate_messages(raw: Any) -> list[dict[str, Any]]:
    """Validate the messages of a request, including the tool messages.

    A tool turn is an ordinary turn with a role and a result. The assistant
    turn that requested the tool carries the tool calls, and its content may
    be empty because the call is the answer.
    """

    if not isinstance(raw, list):
        raise InvalidToolDeclaration("messages must be a non-empty array")
    if not raw:
        raise InvalidToolDeclaration("messages must be a non-empty array")

    validated: list[dict[str, Any]] = []
    for index, message in enumerate(raw):
        if not isinstance(message, dict):
            raise InvalidToolDeclaration(f"messages[{index}] must be a JSON object")
        role = message.get("role")
        if role not in _VALID_ROLES:
            raise InvalidToolDeclaration(
                f"messages[{index}] role must be one of system/user/assistant/tool"
            )

        if role == "tool":
            extra = set(message) - {"role", "content", "tool_call_id", "name"}
            if extra:
                raise InvalidToolDeclaration(
                    f"messages[{index}] unexpected fields: "
                    f"{', '.join(sorted(extra))}"
                )
            call_id = message.get("tool_call_id")
            if not _is_safe_identifier(
                call_id, _TOOL_CALL_ID_CHARS, _TOOL_CALL_ID_MAX
            ):
                raise InvalidToolDeclaration(
                    f"messages[{index}].tool_call_id must be a safe identifier"
                )
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise InvalidToolDeclaration(
                    f"messages[{index}] content must be a non-empty string"
                )
            tool_message: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": content.strip(),
            }
            name = message.get("name")
            if isinstance(name, str) and name.strip():
                tool_message["name"] = name.strip()
            validated.append(tool_message)
            continue

        if role == "assistant":
            extra = set(message) - {"role", "content", "tool_calls"}
            if extra:
                raise InvalidToolDeclaration(
                    f"messages[{index}] unexpected fields: "
                    f"{', '.join(sorted(extra))}"
                )
            content = message.get("content")
            tool_calls = (
                validate_tool_calls(message.get("tool_calls"), index)
                if "tool_calls" in message
                else []
            )
            if content is None:
                if not tool_calls:
                    raise InvalidToolDeclaration(
                        f"messages[{index}] must carry content or tool calls"
                    )
                validated.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls,
                    }
                )
                continue
            if not isinstance(content, str) or not content.strip():
                raise InvalidToolDeclaration(
                    f"messages[{index}] content must be a non-empty string"
                )
            turn: dict[str, Any] = {"role": "assistant", "content": content.strip()}
            if tool_calls:
                turn["tool_calls"] = tool_calls
            validated.append(turn)
            continue

        extra = set(message) - {"role", "content"}
        if extra:
            raise InvalidToolDeclaration(
                f"messages[{index}] unexpected fields: {', '.join(sorted(extra))}"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise InvalidToolDeclaration(
                f"messages[{index}] content must be a non-empty string"
            )
        validated.append({"role": role, "content": content.strip()})
    return validated


def model_supports_tools(model_id: str) -> bool:
    """Whether the routed model declares the tool-calling capability.

    The answer comes from the canonical model registry, so a model's tool
    support is declared once and read everywhere.
    """

    from app.pilot.catalog import get_catalog_by_id

    model = get_catalog_by_id(model_id)
    if model is None:
        return False
    return TOOL_CAPABILITY in model.capabilities


def require_tool_capability(model_id: str) -> None:
    """Refuse a tool request for a model that cannot serve one."""

    if not model_supports_tools(model_id):
        raise ToolsNotSupported(model_id)


def require_stream_tool_wire(
    model_id: str, platform_provider_id: str | None = None
) -> None:
    """Refuse a streaming tool request the routed adapter cannot carry.

    Serving a tool call is a property of the provider wire, not of the channel:
    the Google native lane and the OpenCode Go Responses lane each carry one,
    and every other route must be refused before a credential is spent rather
    than answered without the tool the caller asked for. Each adapter owns its
    own refusal, so this only dispatches to the one that will serve the call.
    """

    if platform_provider_id is None:
        from app.pilot.catalog import get_catalog_by_id

        model = get_catalog_by_id(model_id)
        platform_provider_id = model.platform_provider_id if model else None

    if platform_provider_id == GO_PROVIDER_ID:
        from .opencode_go_wire import go_tool_wire

        if go_tool_wire(model_id) is None:
            raise StreamNotSupported()
        return

    from .google_provider import require_stream_tool_support

    require_stream_tool_support(model_id, platform_provider_id)
