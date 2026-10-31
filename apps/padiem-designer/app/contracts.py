"""The Designer contracts: a generated UI, a turn, and the interaction state.

The tool name, the parameter order and the channel names come from the pinned
MIT upstream ``CopilotKit/OpenIntelligentUI`` release. Reusing them keeps this
app compatible with the upstream renderer contract instead of inventing a
second one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: The upstream tool name. The upstream runtime and the upstream renderer both
#: look for exactly this name, so keeping it is what makes the reuse real.
DESIGNER_TOOL_NAME = "generateSandboxedUi"

#: The upstream parameter order. The upstream system prompt makes the order
#: load-bearing, so the same order is used here.
DESIGNER_TOOL_PARAMETERS: tuple[str, ...] = (
    "initialHeight",
    "placeholderMessages",
    "css",
    "html",
    "jsFunctions",
    "jsExpressions",
)

#: Longest accepted generated HTML.
MAX_GENERATED_HTML_CHARS = 200_000
#: Longest accepted generated CSS.
MAX_GENERATED_CSS_CHARS = 120_000
#: Longest accepted generated JavaScript.
MAX_GENERATED_JS_CHARS = 120_000
#: Longest accepted prompt.
MAX_PROMPT_CHARS = 8_000
#: Longest accepted single interaction-state value.
MAX_STATE_VALUE_CHARS = 4_000
#: Most interaction-state values one turn may carry.
MAX_STATE_VALUES = 200


class DesignerError(Exception):
    """A Designer request the app refuses to serve."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GeneratedUi:
    """One generated interactive UI.

    ``html`` carries body markup only, ``css`` carries every style, and
    ``js_functions`` plus ``js_expressions`` carry the behaviour. The split is
    the upstream contract: a style block inside ``html`` and a monolithic
    inline script are both refused upstream, and they are refused here too.
    """

    html: str
    css: str = ""
    js_functions: str = ""
    js_expressions: tuple[str, ...] = ()
    initial_height: int | None = None
    placeholder_messages: tuple[str, ...] = ()
    title: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "html": self.html,
            "css": self.css,
            "jsFunctions": self.js_functions,
            "jsExpressions": list(self.js_expressions),
            "initialHeight": self.initial_height,
            "placeholderMessages": list(self.placeholder_messages),
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class InteractionState:
    """What the user did inside the generated UI.

    ``values`` holds the control values the sandbox captured. ``prompt`` is the
    text the generated UI asked the assistant to act on, if it asked.
    """

    values: Mapping[str, str] = field(default_factory=dict)
    prompt: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {"values": dict(self.values), "prompt": self.prompt}

    def is_empty(self) -> bool:
        return not self.values and not self.prompt


@dataclass(frozen=True, slots=True)
class UiRequest:
    """One Designer turn request."""

    prompt: str
    history: tuple[Mapping[str, str], ...] = ()
    interaction_state: InteractionState = field(default_factory=InteractionState)
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> "UiRequest":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise DesignerError(400, "prompt_required", "A prompt is required.")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise DesignerError(413, "prompt_too_long", "The prompt is too long.")

        raw_history = payload.get("history") or []
        if not isinstance(raw_history, Sequence) or isinstance(raw_history, (str, bytes)):
            raise DesignerError(400, "history_invalid", "The history must be a list.")
        history: list[Mapping[str, str]] = []
        for entry in raw_history:
            if not isinstance(entry, Mapping):
                raise DesignerError(400, "history_invalid", "A history entry must be an object.")
            role = entry.get("role")
            content = entry.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                raise DesignerError(400, "history_invalid", "A history entry needs a role and content.")
            history.append({"role": role, "content": content[:MAX_PROMPT_CHARS]})

        raw_state = payload.get("interaction_state")
        state = InteractionState()
        if isinstance(raw_state, Mapping):
            raw_values = raw_state.get("values") or {}
            if isinstance(raw_values, Mapping):
                values: dict[str, str] = {}
                for key, value in list(raw_values.items())[:MAX_STATE_VALUES]:
                    if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
                        continue
                    values[key[:120]] = str(value)[:MAX_STATE_VALUE_CHARS]
                state = InteractionState(
                    values=values,
                    prompt=(raw_state.get("prompt") or None)
                    if isinstance(raw_state.get("prompt"), str)
                    else None,
                )

        return UiRequest(
            prompt=prompt.strip(),
            history=tuple(history),
            interaction_state=state,
        )


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One model turn: text plus the tool calls the model asked for."""

    text: str
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    model_id: str = ""
    route_kind: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "modelId": self.model_id,
            "routeKind": self.route_kind,
            "toolCallCount": len(self.tool_calls),
        }


@dataclass(frozen=True, slots=True)
class UiTurnResult:
    """The answer to one Designer turn."""

    text: str
    ui: GeneratedUi | None
    model_id: str
    route_kind: str
    tool_called: bool
    context_sent: Mapping[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "ui": self.ui.to_public_dict() if self.ui is not None else None,
            "modelId": self.model_id,
            "routeKind": self.route_kind,
            "toolCalled": self.tool_called,
            "contextSent": dict(self.context_sent),
        }
