"""The model route: where a Designer turn is executed.

Two routes exist and they are deliberately different in kind.

``OpenAICompatibleRoute``
    Speaks an OpenAI-compatible chat-completions contract with tool calling.
    This is the route the local end-to-end run uses, because the tool channel
    is what the generative-UI contract needs.

``B14Route``
    Speaks PADIEM's B14 execution contract through the same transport protocol
    the B62 product uses. Since #5536 that contract carries a tool channel, so
    the generative-UI contract is expressed over it directly: the route
    declares ``generateSandboxedUi`` and reads the model's tool call out of
    the B14 answer.

Neither route selects a model. The model id comes from configuration, and the
product's model id comes from the B14 registry through the product route.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import httpx

from .config import Settings
from .contracts import (
    DESIGNER_TOOL_NAME,
    DESIGNER_TOOL_PARAMETERS,
    MAX_GENERATED_CSS_CHARS,
    MAX_GENERATED_HTML_CHARS,
    MAX_GENERATED_JS_CHARS,
    DesignerError,
    GeneratedUi,
    ModelTurn,
)

#: The B14 chat-completions path. The same path the shared Core client and
#: the B62 product post to.
B14_CHAT_COMPLETIONS_PATH = "/api/pilot/v1/chat/completions"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """What one model turn needs."""

    system_prompt: str
    user_prompt: str
    # The earlier turns. A turn may carry a tool result with the identifier of
    # the call it answers, and an assistant turn may carry the tool calls it
    # made, so the round trip can be replayed to the model.
    history: tuple[Mapping[str, Any], ...] = ()
    interaction_state: Mapping[str, Any] | None = None


def designer_tool_schema() -> dict[str, Any]:
    """The tool the model calls, in the upstream parameter order."""

    return {
        "type": "function",
        "function": {
            "name": DESIGNER_TOOL_NAME,
            "description": (
                "Generate the interactive UI for the user. Call this exactly once "
                "per UI answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "initialHeight": {
                        "type": "number",
                        "description": "Estimated finished height in pixels.",
                    },
                    "placeholderMessages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-4 short progress messages.",
                    },
                    "css": {
                        "type": "string",
                        "description": "All styles. The html parameter carries none.",
                    },
                    "html": {
                        "type": "string",
                        "description": (
                            "Body markup with readable initial content. No style "
                            "block, no script block, no inline script."
                        ),
                    },
                    "jsFunctions": {
                        "type": "string",
                        "description": "Named function declarations for behaviour.",
                    },
                    "jsExpressions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Small synchronous statements invoking those functions.",
                    },
                },
                "required": ["css", "html"],
            },
        },
    }


class ModelRoute(Protocol):
    """One way of executing a Designer turn."""

    kind: str

    @property
    def supports_tool_calls(self) -> bool: ...

    async def generate(self, request: ModelRequest) -> ModelTurn: ...


def _history_messages(
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Carry the earlier turns into the request.

    A plain turn is a role and its content. A tool turn is a role, its
    content and the identifier of the call it answers; without that
    identifier the model cannot read the result, so it is carried here and
    not dropped. An assistant turn may also carry the tool calls it made,
    which is what lets the round trip be replayed to the model.
    """

    messages: list[dict[str, Any]] = []
    for entry in history:
        role = entry.get("role")
        if not isinstance(role, str) or not role:
            continue
        message: dict[str, Any] = {"role": role}
        content = entry.get("content")
        if isinstance(content, str):
            message["content"] = content
        call_id = entry.get("tool_call_id")
        if isinstance(call_id, str) and call_id:
            message["tool_call_id"] = call_id
        name = entry.get("name")
        if isinstance(name, str) and name:
            message["name"] = name
        tool_calls = entry.get("tool_calls")
        if isinstance(tool_calls, (list, tuple)) and tool_calls:
            message["tool_calls"] = [
                dict(call) for call in tool_calls if isinstance(call, Mapping)
            ]
        if "content" not in message and "tool_calls" not in message:
            continue
        messages.append(message)
    return messages


def _tool_arguments(call: Mapping[str, Any]) -> dict[str, Any]:
    raw = call.get("function", {}).get("arguments") if isinstance(call.get("function"), Mapping) else None
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _clamp(value: object, limit: int) -> str:
    text = "" if value is None else str(value)
    return text[:limit]


def ui_from_tool_arguments(arguments: Mapping[str, Any]) -> GeneratedUi:
    """Build a generated UI from the tool call arguments.

    The upstream refuses a style block inside ``html``. That refusal is kept:
    a style block in the body would not be applied by the preview the same way
    the upstream renderer applies it, so the html is cleaned instead of being
    trusted.
    """

    html = _clamp(arguments.get("html"), MAX_GENERATED_HTML_CHARS)
    lowered = html.lower()
    if "<style" in lowered or "<script" in lowered:
        raise DesignerError(
            502,
            "generated_ui_contract_violation",
            "The generated html carried a style or script block; the contract "
            "keeps those in the css and jsFunctions channels.",
        )

    css = _clamp(arguments.get("css"), MAX_GENERATED_CSS_CHARS)
    js_functions = _clamp(arguments.get("jsFunctions"), MAX_GENERATED_JS_CHARS)
    raw_expressions = arguments.get("jsExpressions") or []
    expressions: list[str] = []
    if isinstance(raw_expressions, Sequence) and not isinstance(raw_expressions, (str, bytes)):
        for item in list(raw_expressions)[:50]:
            expressions.append(_clamp(item, 4_000))

    raw_height = arguments.get("initialHeight")
    initial_height: int | None = None
    if isinstance(raw_height, (int, float)) and not isinstance(raw_height, bool):
        initial_height = max(50, min(4000, int(raw_height)))

    raw_placeholders = arguments.get("placeholderMessages") or []
    placeholders: list[str] = []
    if isinstance(raw_placeholders, Sequence) and not isinstance(raw_placeholders, (str, bytes)):
        for item in list(raw_placeholders)[:6]:
            placeholders.append(_clamp(item, 200))

    return GeneratedUi(
        html=html,
        css=css,
        js_functions=js_functions,
        js_expressions=tuple(expressions),
        initial_height=initial_height,
        placeholder_messages=tuple(placeholders),
        title=_clamp(arguments.get("title"), 200),
    )


class OpenAICompatibleRoute:
    """A route that speaks an OpenAI-compatible tool-calling contract."""

    kind = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def supports_tool_calls(self) -> bool:
        return True

    async def generate(self, request: ModelRequest) -> ModelTurn:
        if not self._settings.has_model_credentials:
            raise DesignerError(
                503,
                "model_route_not_configured",
                "No model route is configured. Set DESIGNER_MODEL_BASE_URL, "
                "DESIGNER_MODEL_API_KEY and DESIGNER_MODEL_ID.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt}
        ]
        messages.extend(_history_messages(request.history))
        messages.append({"role": "user", "content": request.user_prompt})

        url = self._settings.model_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.model_api_key}",
        }

        turn: ModelTurn | None = None
        for attempt in range(self._settings.model_tool_retries + 1):
            attempt_messages = list(messages)
            if attempt:
                # A model that answered in prose did not produce a preview.
                # The app asks once more, explicitly, and reports the retry.
                attempt_messages[-1] = {
                    "role": "user",
                    "content": (
                        request.user_prompt
                        + "\n\nCall the generateSandboxedUi tool now. Do not "
                        "answer with text only."
                    ),
                }
            turn = await self._post(
                url=url,
                headers=headers,
                messages=attempt_messages,
            )
            if turn.tool_calls:
                break
        assert turn is not None
        return turn

    async def _post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        messages: Sequence[Mapping[str, Any]],
    ) -> ModelTurn:
        payload = {
            "model": self._settings.model_id,
            "messages": list(messages),
            "tools": [designer_tool_schema()],
            "tool_choice": {
                "type": "function",
                "function": {"name": DESIGNER_TOOL_NAME},
            },
            "max_tokens": self._settings.model_max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.model_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=dict(headers))
        except httpx.HTTPError as exc:
            raise DesignerError(
                502,
                "model_route_unreachable",
                f"The model route could not be reached: {type(exc).__name__}",
            ) from exc

        if response.status_code >= 400:
            raise DesignerError(
                502,
                "model_route_error",
                f"The model route answered HTTP {response.status_code}.",
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DesignerError(
                502,
                "model_route_invalid_response",
                "The model route answered a body that is not JSON.",
            ) from exc

        choices = body.get("choices") or []
        if not choices:
            raise DesignerError(
                502,
                "model_route_empty_response",
                "The model route returned no choice.",
            )
        message = choices[0].get("message") or {}
        raw_calls = message.get("tool_calls") or []
        calls = [call for call in raw_calls if isinstance(call, Mapping)]
        text = message.get("content") if isinstance(message.get("content"), str) else ""

        return ModelTurn(
            text=text or "",
            tool_calls=tuple(calls),
            model_id=self._settings.model_id,
            route_kind=self.kind,
        )


class B14Route:
    """The product route, spoken through the B14 execution contract.

    #5536: the B14 execution contract now carries a tool channel. The route
    declares ``generateSandboxedUi``, sends the caller's turn to B14, and
    reads the model's tool call out of the answer. The same transport protocol
    the B62 product uses is spoken here, so no second client is introduced.

    The route selects no model: the model id comes from configuration, and B14
    owns the routing decision. When the routed model cannot serve a tool
    call, B14 refuses the request before execution and this route reports
    that refusal as it is.
    """

    kind = "b14"

    def __init__(self, settings: Settings, transport: Any | None = None) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def supports_tool_calls(self) -> bool:
        return True

    async def generate(self, request: ModelRequest) -> ModelTurn:
        if self._transport is None or not self._settings.b14_base_url:
            raise DesignerError(
                503,
                "b14_route_not_bound",
                "The B14 route is not bound in this process. It is reached "
                "through a service binding in the Worker runtime.",
            )
        if not self._settings.b14_model_id:
            # The retired automatic route is not a default, and this app does
            # not choose models: an unset model id is a deployment
            # configuration error, refused before any request is built.
            raise DesignerError(
                503,
                "b14_route_model_not_configured",
                "DESIGNER_B14_MODEL_ID is not configured. Set it to one "
                "registered Business 14 model.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt}
        ]
        messages.extend(_history_messages(request.history))
        messages.append({"role": "user", "content": request.user_prompt})

        url = self._settings.b14_base_url.rstrip("/") + B14_CHAT_COMPLETIONS_PATH
        payload = {
            "model": self._settings.b14_model_id,
            "messages": messages,
            "tools": [designer_tool_schema()],
            "tool_choice": {
                "type": "function",
                "function": {"name": DESIGNER_TOOL_NAME},
            },
            "max_tokens": self._settings.model_max_tokens,
        }

        turn: ModelTurn | None = None
        for attempt in range(self._settings.model_tool_retries + 1):
            attempt_payload = dict(payload)
            if attempt:
                # A model that answered in prose did not produce a preview.
                # The app asks once more, explicitly, and reports the retry.
                attempt_payload["messages"] = [
                    *messages[:-1],
                    {
                        "role": "user",
                        "content": (
                            request.user_prompt
                            + "\n\nCall the generateSandboxedUi tool now. Do not "
                            "answer with text only."
                        ),
                    },
                ]
            turn = await self._post(url=url, payload=attempt_payload)
            if turn.tool_calls:
                break
        assert turn is not None
        return turn

    async def _post(self, *, url: str, payload: Mapping[str, Any]) -> ModelTurn:
        post_json = getattr(self._transport, "post_json", None)
        if not callable(post_json):
            raise DesignerError(
                503,
                "b14_route_not_bound",
                "The B14 route is not bound in this process. It is reached "
                "through a service binding in the Worker runtime.",
            )
        try:
            status_code, body = await post_json(url, dict(payload))
        except DesignerError:
            raise
        except Exception as exc:
            raise DesignerError(
                502,
                "model_route_unreachable",
                f"The model route could not be reached: {type(exc).__name__}",
            ) from exc

        if status_code >= 400:
            raise DesignerError(
                502,
                "model_route_error",
                f"The model route answered HTTP {status_code}.",
            )

        if isinstance(body, (bytes, bytearray)):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DesignerError(
                    502,
                    "model_route_invalid_response",
                    "The model route answered a body that is not UTF-8 text.",
                ) from exc
        try:
            parsed = json.loads(body) if isinstance(body, str) else body
        except ValueError as exc:
            raise DesignerError(
                502,
                "model_route_invalid_response",
                "The model route answered a body that is not JSON.",
            ) from exc

        if not isinstance(parsed, Mapping):
            raise DesignerError(
                502,
                "model_route_invalid_response",
                "The model route answered a body that is not a JSON object.",
            )

        choices = parsed.get("choices") or []
        if not choices:
            raise DesignerError(
                502,
                "model_route_empty_response",
                "The model route returned no choice.",
            )
        first = choices[0] if isinstance(choices[0], Mapping) else {}
        message = first.get("message")
        message = message if isinstance(message, Mapping) else {}
        raw_calls = message.get("tool_calls") or []
        calls = [call for call in raw_calls if isinstance(call, Mapping)]
        text = message.get("content") if isinstance(message.get("content"), str) else ""

        return ModelTurn(
            text=text or "",
            tool_calls=tuple(calls),
            model_id=str(parsed.get("model") or self._settings.b14_model_id or ""),
            route_kind=self.kind,
        )


def build_model_route(settings: Settings) -> ModelRoute:
    """Choose the configured route.

    The choice is configuration, not a code decision: the route kind comes
    from ``DESIGNER_MODEL_ROUTE`` and the model id comes from the same place.
    """

    if settings.model_route == "b14":
        return B14Route(settings)
    return OpenAICompatibleRoute(settings)
