"""#6838: B14 decides reasoning effort per model; no value lives in the public registry.

The public ``b14_models.json`` carries no per-model reasoning value (#6828).
This module owns the field vocabulary and the reading rule only. Values arrive
through the Owner overlay (``b14_models.overrides.json``, #6712):

    "reasoning": {"supported": true, "values": ["low", "medium", "high"],
                  "default": "high", "thought_summary": true}

Rules
-----
* A model without the block is unsupported: no reasoning option is sent.
* A supported model sends its ``default``. An omitted ``default`` resolves to
  the deepest accepted value, so "supported" always means "as deep as this
  model goes" rather than an invented middle setting.
* ``supported: false`` must not carry values or a default.
* ``thought_summary`` (thought-summary stream) turns on streamed thinking
  summaries for the model. It is honoured only on a supported model: an
  unsupported model may not declare it, and an omitted key defaults to off.
* The platform path never forwards a caller's value. BYOK is the exception and
  passes the customer's own choice through unchanged.

Nothing here reads or prints a model or provider name; a value is a level
identifier only.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

REASONING_FIELD = "reasoning_effort"
REASONING_BLOCK = "reasoning"
# Shallow to deep. An omitted default resolves to the last accepted value.
REASONING_LEVELS = ("minimal", "low", "medium", "high")
_LEVEL_INDEX = {level: index for index, level in enumerate(REASONING_LEVELS)}
_BLOCK_KEYS = frozenset({"supported", "values", "default", "thought_summary"})


class ReasoningPolicyError(ValueError):
    """The Owner overlay declared a reasoning block this code cannot honour."""


def deepest(values: Any) -> str | None:
    """The deepest level in ``values``, or None when it holds no known level."""
    levels = [
        level for level in values or ()
        if isinstance(level, str) and level in _LEVEL_INDEX
    ]
    if not levels:
        return None
    return max(levels, key=lambda level: _LEVEL_INDEX[level])


def normalize_policy(raw: Any) -> tuple[bool, tuple[str, ...], str | None, bool]:
    """Return ``(supported, values, default, thought_summary)`` for one block.

    Fails closed: anything this code cannot honour is an error rather than a
    silently ignored option.
    """
    if not isinstance(raw, dict):
        raise ReasoningPolicyError("reasoning must be an object")
    if set(raw) - _BLOCK_KEYS:
        raise ReasoningPolicyError("reasoning: unexpected keys")
    supported = raw.get("supported", False)
    if not isinstance(supported, bool):
        raise ReasoningPolicyError("reasoning.supported must be a boolean")
    thought_summary = raw.get("thought_summary", False)
    if not isinstance(thought_summary, bool):
        raise ReasoningPolicyError("reasoning.thought_summary must be a boolean")
    if not supported:
        if raw.get("values") or raw.get("default"):
            raise ReasoningPolicyError("reasoning: unsupported model declares values")
        if thought_summary:
            raise ReasoningPolicyError(
                "reasoning: unsupported model declares thought_summary"
            )
        return (False, (), None, False)
    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise ReasoningPolicyError("reasoning.values must be a non-empty list")
    if not all(isinstance(value, str) and value in _LEVEL_INDEX for value in values):
        raise ReasoningPolicyError("reasoning.values holds an unknown level")
    if len(set(values)) != len(values):
        raise ReasoningPolicyError("reasoning.values repeats a level")
    default = raw.get("default")
    if default is None:
        default = deepest(values)
    elif not isinstance(default, str) or default not in values:
        raise ReasoningPolicyError("reasoning.default must be one of values")
    return (True, tuple(values), default, thought_summary)


def reasoning_effort_for_model(model_id: str | None) -> str | None:
    """The level B14 sends for this model, or None when it declares no support."""
    if not model_id:
        return None
    from .catalog import CATALOG_BY_ID

    model = CATALOG_BY_ID.get(model_id)
    if model is None or not getattr(model, "reasoning_supported", False):
        return None
    value = getattr(model, "reasoning_default", None)
    if isinstance(value, str) and value in _LEVEL_INDEX:
        return value
    return None


def thought_summary_enabled_for_model(model_id: str | None) -> bool:
    """Whether the Owner turned on streamed thinking summaries for this model.

    A thought request is a bonus, never a dependency of the answer: an absent
    catalog row, an unsupported model, and an overlay that omits the key all
    mean the same thing — nothing is put on the wire.
    """
    if not model_id:
        return False
    from .catalog import CATALOG_BY_ID

    model = CATALOG_BY_ID.get(model_id)
    if model is None or not getattr(model, "reasoning_supported", False):
        return False
    return getattr(model, "thought_summary_enabled", False) is True


def strip_reasoning(
    model_parameters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Drop a caller-supplied reasoning value from a platform request.

    Every other model-native option keeps its existing validation path; only
    the reasoning choice is B14's to make on this lane.
    """
    if not model_parameters or REASONING_FIELD not in model_parameters:
        return model_parameters
    return {
        key: value for key, value in model_parameters.items()
        if key != REASONING_FIELD
    } or None


def rejects_reasoning_effort(body: bytes) -> bool:
    """True only for a request-level rejection that names the option."""
    text = body.decode("utf-8", "replace").lower()
    return "reasoning_effort" in text or "reasoning effort" in text


def rejects_thought_summary(body: bytes) -> bool:
    """True only for a request-level rejection that names the thought request.

    Same discipline as ``rejects_reasoning_effort``: a stricter endpoint is
    retried once without the option, and nothing else re-sends the request.
    """
    text = body.decode("utf-8", "replace").lower()
    return "include_thoughts" in text or "thinking_config" in text


# What this request actually put on the wire, per model. A fallback therefore
# records the second model's own decision, not the first one's.
_SENT: ContextVar[dict[str, str | None]] = ContextVar("b14_sent_reasoning", default={})


def note_sent_reasoning(model_id: str | None, level: str | None) -> None:
    """Remember the level this request sent for ``model_id`` (None = none)."""
    if not model_id:
        return
    _SENT.set({**_SENT.get(), model_id: level})


def sent_reasoning_effort(model_id: str | None) -> str | None:
    """What was actually sent this request, else the registry's decision."""
    if model_id and model_id in _SENT.get():
        return _SENT.get()[model_id]
    return reasoning_effort_for_model(model_id)
