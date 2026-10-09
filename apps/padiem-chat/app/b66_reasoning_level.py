"""B66 per-model reasoning-level capability contract (#3906).

Ownership boundary
------------------
B14 owns the model registry and is responsible for the official per-model
inference/reasoning parameter implementation (#3977). That issue is still
OPEN and no upstream JSON field has been agreed or verified, therefore this
module MUST NOT guess a provider parameter name, a value vocabulary, or a
mapping for any model. Inventing one would silently send an unsupported
argument to a paid provider request.

Fail-closed default
-------------------
Because no model has a *verified* non-default reasoning level yet, every
model currently exposes exactly one selectable option: ``default``, which
means "use the provider's own default" and is transmitted as an explicit
absence of any reasoning argument. Any other requested value is rejected
with an explainable 4xx error and is never downgraded, substituted, or
dropped silently. That preserves the user's explicit choice semantics.

Single integration seam
-----------------------
:func:`reasoning_levels_for_model` is the ONLY place that needs to change
when #3977 lands a verified per-model capability contract. Everything else
in B66 (API validation, UI rendering, request propagation) already consumes
this seam, so the switch is a contract replacement rather than a codebase
rewrite. Until then it deliberately returns the closed default set.
"""

from __future__ import annotations

from typing import Any

# The single reasoning option that is safe for every registered model today.
# It is not an upstream parameter value: it means "send no reasoning
# argument and let the provider apply its own default".
DEFAULT_REASONING_LEVEL = "default"

# Human-facing, stable identifier for the closed default option.
DEFAULT_REASONING_LABEL = "기본(제공자 기본값)"

# Bounded, provider-agnostic vocabulary of selectable level identifiers.
# Intentionally minimal: only the fail-closed default exists until #3977
# supplies verified per-model values.
_KNOWN_LEVELS: frozenset[str] = frozenset({DEFAULT_REASONING_LEVEL})

# Exact grammar for an incoming level identifier, matching the model_id
# character class already enforced by the B66 quote routes.
_SAFE_LEVEL = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def is_supported_reasoning_level(value: object) -> bool:
    """Return True only for a known, well-formed level identifier."""
    return (
        isinstance(value, str)
        and len(value) <= 32
        and set(value) <= _SAFE_LEVEL
        and value in _KNOWN_LEVELS
    )


def reasoning_levels_for_model(model_id: object) -> frozenset[str]:
    """Selectable reasoning levels for one exact model ID.

    #3977 integration point: replace the closed default with the verified
    per-model capability set once B14 publishes and attests it. A model with
    no confirmed capability set keeps only ``default`` so that unverified
    options are never offered to the customer.
    """
    if not isinstance(model_id, str) or not model_id:
        return frozenset()
    return frozenset({DEFAULT_REASONING_LEVEL})


def reasoning_options_for_model(model_id: object) -> list[dict[str, str]]:
    """UI-ready ordered options: always the default first, stable order."""
    return [
        {"value": level, "label": DEFAULT_REASONING_LABEL}
        for level in sorted(reasoning_levels_for_model(model_id))
    ]


def validate_reasoning_level(
    model_id: object, requested: object
) -> str | None:
    """Validate an explicit request for one model, fail closed.

    Returns the accepted level, or ``None`` when the request omitted the
    field (fully backward compatible with existing callers). Raises
    ``ValueError`` with an explainable code when the value is unsupported,
    so the caller can answer 4xx instead of substituting another level.
    """
    if requested is None:
        return None
    if not is_supported_reasoning_level(requested):
        raise ValueError("unsupported_reasoning_level")
    if requested not in reasoning_levels_for_model(model_id):
        # Well-formed vocabulary, but this model does not offer it.
        raise ValueError("unsupported_reasoning_level")
    return requested


def reasoning_parameter_for_request(
    model_id: object, level: object
) -> dict[str, Any]:
    """Map an accepted level to its upstream request arguments.

    The fail-closed default deliberately contributes NO provider argument,
    so the request byte layout for an unspecified level is identical to the
    pre-#3906 behaviour. When #3977 verifies real provider parameters, this
    function becomes the single place that emits them; no other B66 code
    should ever construct a provider reasoning argument.
    """
    if level is None:
        return {}
    validate_reasoning_level(model_id, level)
    return {}
