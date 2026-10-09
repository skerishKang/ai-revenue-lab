"""B66 per-model reasoning-level capability contract (#3906).

Ownership boundary
------------------
Which reasoning level a model may be offered is NOT a B66 decision. It is B14
verified capability metadata, merged by #3977 in
``apps/korean-ai-platform/app/pilot/model_native_parameters.py`` (``_SUPPORTED``),
which in turn cites the manufacturer model card plus the exact serving provider's
official accepted fields.

``VERIFIED_REASONING_EFFORT`` below is a **pinned mirror** of that authority. The
test suite loads the B14 file and fails if the two disagree, so a capability
cannot change on the B14 side without this mirror being updated in the same
review. B66 never infers a level from a model family, an alias, or a guess: a
model absent from the mirror offers the provider default only.

Wire contract
-------------
The chosen level travels to B14 as the provider-native ``reasoning_effort``
request field (the #3984 gateway allow-list). ``default`` is deliberately NOT an
upstream value: it means "send no reasoning argument", so the served provider
applies its own default and the request keeps its pre-#3906 shape. An
unsupported level is rejected with an explainable 4xx and is never downgraded,
substituted or silently dropped.
"""

from __future__ import annotations

from typing import Any

# The non-upstream sentinel: "let the provider apply its own reasoning default".
DEFAULT_REASONING_LEVEL = "default"

# Human-facing, stable identifier for the default option.
DEFAULT_REASONING_LABEL = "기본(제공자 기본값)"

# The single wire name for the upstream option. Kept here so the name is
# single-sourced across the API contract, the boundary and the tests.
REASONING_EFFORT_FIELD = "reasoning_effort"

# Pinned mirror of B14 verified capability (`_SUPPORTED[*]['reasoning_effort']`).
# Order is the documented presentation order, not alphabetical.
VERIFIED_REASONING_EFFORT: dict[str, tuple[str, ...]] = {
    "google/gemini-3.1-flash-lite": ("minimal", "low", "medium", "high"),
    "google/gemini-3.5-flash-lite": ("minimal", "low", "medium", "high"),
    "atria/Atria-Dawn-Preview": ("low", "medium", "high"),
}

# Presentation order for the verified levels, and their Korean labels. A label
# is UI copy only; it is never sent upstream.
_REASONING_LEVEL_ORDER: tuple[str, ...] = ("minimal", "low", "medium", "high")
_REASONING_LEVEL_LABELS: dict[str, str] = {
    "minimal": "최소",
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
}

# Well-formed, provider-documented vocabulary, independent of any one model.
# Exact grammar for an incoming level identifier, matching the model_id
# character class already enforced by the B66 quote routes.
_SAFE_LEVEL = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_KNOWN_LEVELS: frozenset[str] = frozenset({DEFAULT_REASONING_LEVEL}) | frozenset(
    level for levels in VERIFIED_REASONING_EFFORT.values() for level in levels
)


def is_supported_reasoning_level(value: object) -> bool:
    """True only for a known, well-formed level identifier.

    Membership here is vocabulary membership, not a capability promise: a model
    still has to list the level in :func:`reasoning_levels_for_model` before the
    customer may select it.
    """
    return (
        isinstance(value, str)
        and len(value) <= 32
        and set(value) <= _SAFE_LEVEL
        and value in _KNOWN_LEVELS
    )


def reasoning_levels_for_model(model_id: object) -> frozenset[str]:
    """Selectable reasoning levels for one exact registered model ID.

    The provider default is always selectable. Verified levels come only from
    the pinned B14 capability mirror, so an unverified model keeps exactly one
    option and can never be offered a level B14 has not attested.
    """
    if not isinstance(model_id, str) or not model_id:
        return frozenset()
    verified = VERIFIED_REASONING_EFFORT.get(model_id, ())
    return frozenset({DEFAULT_REASONING_LEVEL}) | frozenset(verified)


def reasoning_options_for_model(model_id: object) -> list[dict[str, str]]:
    """UI-ready ordered options: the default first, then verified levels."""
    levels = reasoning_levels_for_model(model_id)
    options = [{"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}]
    for level in _REASONING_LEVEL_ORDER:
        if level in levels:
            options.append({"value": level, "label": _REASONING_LEVEL_LABELS[level]})
    return options


def validate_reasoning_level(
    model_id: object, requested: object
) -> str | None:
    """Validate an explicit request for one model, fail closed.

    Returns the accepted level, or ``None`` when the request omitted the field
    (fully backward compatible with existing callers). Raises ``ValueError``
    with an explainable code when the value is unsupported for THIS model, so
    the caller can answer 4xx instead of substituting another level.
    """
    if requested is None:
        return None
    if not is_supported_reasoning_level(requested):
        raise ValueError("unsupported_reasoning_level")
    if requested not in reasoning_levels_for_model(model_id):
        # Documented vocabulary, but this model does not offer it.
        raise ValueError("unsupported_reasoning_level")
    return requested


def reasoning_parameter_for_request(
    model_id: object, level: object
) -> dict[str, Any]:
    """Map an accepted level to its upstream request arguments.

    This is the ONLY place that names the upstream reasoning field. The default
    and an omitted level contribute NO argument, so the request byte layout is
    identical to the pre-#3906 behaviour and the provider keeps its own default.
    """
    if level is None or level == DEFAULT_REASONING_LEVEL:
        return {}
    validate_reasoning_level(model_id, level)
    return {REASONING_EFFORT_FIELD: level}
