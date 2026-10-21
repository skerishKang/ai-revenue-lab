"""The model route: where a Designer turn is executed.

Two routes exist and they are deliberately different in kind.

``OpenAICompatibleRoute``
    Speaks an OpenAI-compatible chat-completions contract with tool calling.
    This is the route the local end-to-end run uses, because the tool channel
    is what the generative-UI contract needs.

``B14Route``
    Speaks PADIEM's B14 execution contract through the same transport protocol
    the B62 product uses. B14's execution request is an *answer-only* contract
    today: it carries an agent profile and messages and returns an answer. It
    has no tool-call channel, so the generative-UI contract cannot be expressed
    over it yet. This route therefore reports that gap exactly instead of
    pretending to work, and the app surfaces the gap in its status.

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


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """What one model turn needs."""

    system_prompt: str
    user_prompt: str
    history: tuple[Mapping[str, str], ...] = ()
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
        for entry in request.history:
            role = entry.get("role")
            content = entry.get("content")
            if isinstance(role, str) and isinstance(content, str):
                messages.append({"role": role, "content": content})
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

    The B14 execution request carries an agent profile and messages and returns
    an answer. It has no tool-call channel, so the generative-UI contract cannot
    be expressed over it today. The route reports that gap rather than
    approximating it, so an operator sees the real state of the binding.
    """

    kind = "b14"

    def __init__(self, settings: Settings, transport: Any | None = None) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def supports_tool_calls(self) -> bool:
        return False

    async def generate(self, request: ModelRequest) -> ModelTurn:
        if self._transport is None or not self._settings.b14_base_url:
            raise DesignerError(
                503,
                "b14_route_not_bound",
                "The B14 route is not bound in this process. It is reached "
                "through a service binding in the Worker runtime.",
            )
        raise DesignerError(
            501,
            "b14_tool_channel_unavailable",
            "The B14 execution contract is answer-only today and carries no "
            "tool-call channel, so the generateSandboxedUi contract cannot be "
            "expressed over it yet. The interface is in place; the tool channel "
            "is the missing piece.",
        )


def build_model_route(settings: Settings) -> ModelRoute:
    """Choose the configured route.

    The choice is configuration, not a code decision: the route kind comes
    from ``DESIGNER_MODEL_ROUTE`` and the model id comes from the same place.
    """

    if settings.model_route == "b14":
        return B14Route(settings)
    return OpenAICompatibleRoute(settings)
