"""B66 per-model reasoning-level capability contract (#3906).

Authority boundary
------------------
B14 owns the model registry and the provider-native parameter contract. That
authority is source-merged on ``main`` as
``apps/korean-ai-platform/app/pilot/model_native_parameters.py`` (#3977 /
PR #3984). It documents, for an **exact served model ID only**, which optional
native request fields exist and which values are accepted user overrides.

This module NEVER infers a capability from a model name, a family, an alias or
a substring. A model that the B14 authority does not list keeps the provider
default only, so an unverified option can never be offered to a customer or
sent to a paid provider.

Omission is the default
-----------------------
``default`` is not an upstream value. It means "send no reasoning argument at
all and let the provider apply its own default". An absent field behaves
identically, so the pre-#3906 request layout is preserved byte for byte.

Transport gate
--------------
Producing ``{"reasoning_effort": ...}`` is not yet the same as transmitting it.
The shared Core transport that carries validated native model parameters
(``packages/padiem-ai-core``) is owned by B14/#3977 and is opt-in. Until that
Core contract is present, an explicit non-default level cannot reach the wire,
so it is refused with an explainable 4xx **before** dispatch instead of being
silently dropped. The capability is injected by whoever owns the Core
transport and fails closed when absent; B66 never assumes it.
"""

from __future__ import annotations

import re
from typing import Any

# The single reasoning option that is safe for every registered model.
# It is not an upstream parameter value: it means "send no reasoning argument
# and let the provider apply its own default".
DEFAULT_REASONING_LEVEL = "default"

# Human-facing, stable identifier for the closed default option.
DEFAULT_REASONING_LABEL = "기본(제공자 기본값)"

# Labels for the B14-documented override vocabulary. The VALUE is the exact
# string B14 accepts; the label only explains it to the customer.
_LEVEL_ORDER: tuple[str, ...] = ("minimal", "low", "medium", "high")
_LEVEL_LABELS: dict[str, str] = {
    "minimal": "최소",
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
}

# Exact served-model-ID capability, mirroring the B14 authority module
# ``_SUPPORTED[model_id]["reasoning_effort"]``. Keys are whole IDs on purpose:
# no family/alias/substring matching is permitted.
#
# A test asserts this table equals the B14 source table, so a B14 change that
# is not propagated here fails CI instead of silently diverging.
_VERIFIED_REASONING_EFFORT: dict[str, frozenset[str]] = {
    "google/gemini-3.1-flash-lite": frozenset({"minimal", "low", "medium", "high"}),
    "google/gemini-3.5-flash-lite": frozenset({"minimal", "low", "medium", "high"}),
    "atria/Atria-Dawn-Preview": frozenset({"low", "medium", "high"}),
}

# Bounded, provider-agnostic vocabulary of selectable level identifiers.
_KNOWN_LEVELS: frozenset[str] = frozenset({DEFAULT_REASONING_LEVEL}) | frozenset(
    level for levels in _VERIFIED_REASONING_EFFORT.values() for level in levels
)

# Exact grammar for an incoming level identifier, matching the model_id
# character class already enforced by the B66 quote routes.
_SAFE_LEVEL = re.compile(r"[a-z0-9-]{1,32}\Z")


def is_supported_reasoning_level(value: object) -> bool:
    """Return True only for a known, well-formed level identifier."""
    return (
        isinstance(value, str)
        and _SAFE_LEVEL.fullmatch(value) is not None
        and value in _KNOWN_LEVELS
    )


def reasoning_levels_for_model(model_id: object) -> frozenset[str]:
    """Selectable reasoning levels for one exact model ID.

    The result is the provider default plus only the values the B14 authority
    documents for that exact ID. An unknown or unlisted model gets the default
    alone, so no unverified option is ever shown or selectable.
    """
    if not isinstance(model_id, str) or not model_id:
        return frozenset()
    return frozenset({DEFAULT_REASONING_LEVEL}) | _VERIFIED_REASONING_EFFORT.get(
        model_id, frozenset()
    )


def verified_reasoning_levels_for_model(model_id: object) -> frozenset[str]:
    """Non-default levels proven for the exact model ID (empty when none)."""
    if not isinstance(model_id, str) or not model_id:
        return frozenset()
    return _VERIFIED_REASONING_EFFORT.get(model_id, frozenset())


def reasoning_options_for_model(
    model_id: object, *, transport_supported: bool | None = None
) -> list[dict[str, str]]:
    """UI-ready options the customer may actually choose, right now.

    An option is listed only when it is verified for the exact model AND the
    shared Core can carry it today (``transport_supported``). Advertising a
    level the runtime would have to refuse would break the promise that a
    selectable value is honoured. The default option is always listed: it
    needs no transport.
    """
    verified = [
        level for level in _LEVEL_ORDER
        if level in verified_reasoning_levels_for_model(model_id)
    ]
    if verified and transport_supported is not True:
        verified = []
    return [{"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}] + [
        {"value": level, "label": _LEVEL_LABELS[level]} for level in verified
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
    """Map an accepted level to its validated B14 request arguments.

    ``default`` and an omitted field contribute NO provider argument, so the
    request layout is identical to the pre-#3906 behaviour. A verified
    non-default level contributes exactly the documented B14-native field and
    nothing else: no temperature, no token budget, no alias or invented key.
    """
    if level is None:
        return {}
    validate_reasoning_level(model_id, level)
    if level == DEFAULT_REASONING_LEVEL:
        return {}
    return {"reasoning_effort": level}


def reasoning_transport_available(
    model_id: object, *, transport_supported: bool | None = None
) -> bool:
    """True only when an explicit level could actually reach B14 as-is.

    ``transport_supported`` is supplied by whoever owns the shared Core
    transport (the injected B14 executor, or the Worker state flag) and fails
    closed when it is absent. B66 never imports the Core package to decide
    this, and never assumes support.
    """
    return bool(verified_reasoning_levels_for_model(model_id)) and (
        transport_supported is True
    )
