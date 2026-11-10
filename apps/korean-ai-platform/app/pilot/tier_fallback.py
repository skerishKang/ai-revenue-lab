"""B14 owner-pinned default and ordered fallback roster per validated product tier.

Free's Google primary uses its owner-pinned recovery chain on recoverable
429, 5xx, and timeout failures. Other grades retain their own model routes.

Owner decision 2026-10-25: the test-phase Plus/Pro/Max/admin lanes use
Google with the same ordered backups as the shared Control Plane.
Free retains its primary and uses Gemma 4 31B as its first recovery model per Owner instruction 2026-11-04.

Owner decision 2026-11-04: Plus/Pro/Max/admin insert TokenHarbor DeepSeek as
the first fallback, then Kilo Crouton Alpha and OpenRouter Crouton Alpha,
keeping Gemma as the last. Free inserts Kilo Crouton Alpha as its first
fallback and OpenRouter Crouton Alpha as its second, ahead of Gemma and
Gemini 3.5.
"""
#: Empty declarations, kept as names for the importers (#7241 3단계). The
#: effective answers below always come from the private registry document: a
#: host without one serves no tier at all rather than a repository default.
TIER_DEFAULT_B14_MODEL = ""
TIER_FALLBACK_B14_MODELS: dict[str, tuple[str, ...]] = {}

_ROSTER_GRADES = ("free", "plus", "pro", "max", "admin")


def _private_registry():
    """The private registry when the host switched to it, else ``None``."""
    from .model_registry_file import private_registry_enabled, private_registry_snapshot
    if not private_registry_enabled():
        return None
    load = private_registry_snapshot()
    return load.registry if load is not None else None


def effective_tier_default() -> str:
    """Free's primary, read from the private registry document.

    No switch, or an unusable document, answers an empty identity: the roster
    never falls back to a repository default (#7241 3단계).
    """
    registry = _private_registry()
    if registry is None:
        return ""
    tier = registry.tiers.get("free")
    return tier["primary"] if tier else ""


def effective_tier_fallback() -> dict:
    """Per-grade roster, in the shape this module always had.

    The free grade keeps its fallbacks without the primary, because the router
    compares the request to the default first; every other grade keeps the
    primary at the head. With the switch on and an unusable document the answer
    is empty, which the callers already treat as an unsupported tier.
    """
    registry = _private_registry()
    if registry is None:
        return {}
    rosters = {}
    for grade in _ROSTER_GRADES:
        tier = registry.tiers.get(grade)
        if tier is None:
            continue
        rosters[grade] = (tuple(tier["fallback"]) if grade == "free"
                          else (tier["primary"], *tier["fallback"]))
    return rosters
