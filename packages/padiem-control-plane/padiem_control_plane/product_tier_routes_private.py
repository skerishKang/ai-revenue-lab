"""#6828 2단계 ② — product tier routes read from the private registry.

``product_tier_routes`` stays the pure, side-effect-free DECLARATION (the CI
contract forbids it from touching the environment or the filesystem). This
module is the switch-aware reader beside it:

* the host did not set ``PADIEM_MODELS_REGISTRY`` → the declaration answers,
  exactly as before;
* the host set it → the private document's ``tiers`` answer, and a document
  that cannot be used declares no executable route at all (fail-closed). The
  declaration's own values are never used in that mode.

Both this module and B14 read the SAME converted document through
``models_registry`` (``install_document`` for B14, ``tier_roster`` here), so a
grade and its roster cannot disagree between the two products.
"""
from __future__ import annotations

from .models_registry import load_snapshot, private_switch_enabled
from .product_tier_routes import (
    PRODUCT_TIER_ROUTES,
    ProductCredentialMode,
    ProductRouteStatus,
    ProductTierDefinition,
    ProductTierLabel,
    ProductTierRoute,
    validate_product_tier_routes,
)

_GRADES = (
    (ProductTierLabel.FREE, "free"),
    (ProductTierLabel.PLUS, "plus"),
    (ProductTierLabel.PRO, "pro"),
    (ProductTierLabel.MAX, "max"),
    (ProductTierLabel.ADMIN, "admin"),
)


def private_registry():
    """The private registry when the host switched to it, else ``None``."""
    if not private_switch_enabled():
        return None
    load = load_snapshot()
    return load.registry if load.ready else None


def routes_from_registry(registry) -> tuple[ProductTierDefinition, ...]:
    """Declare every grade from one private registry document.

    The executable route for a grade is its ``primary``; the credential is the
    provider's binding NAME, never a value. A grade the document does not name
    is declared without routes.
    """
    models = {row["id"]: row for row in registry.models}
    definitions = []
    for label, grade in _GRADES:
        tier = registry.tiers.get(grade)
        if tier is None:
            definitions.append(ProductTierDefinition(label=label, routes=()))
            continue
        model_id = tier["primary"]
        row = models[model_id]
        provider_id = row["provider_id"]
        definitions.append(ProductTierDefinition(label=label, routes=(ProductTierRoute(
            route_id=grade + ".private.v1",
            status=ProductRouteStatus.EXECUTABLE,
            model_family=provider_id,
            provider_id=provider_id,
            model_id=model_id,
            upstream_model=row["upstream_model"],
            credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
            credential_binding=registry.providers[provider_id]["credential_binding"],
            evidence="Private model registry (#6828 2 stage 2).",
        ),)))
    declared = tuple(definitions)
    validate_product_tier_routes(declared)
    return declared


def fail_closed_routes() -> tuple[ProductTierDefinition, ...]:
    """Switch on, document unusable: no grade has an executable route."""
    return tuple(
        ProductTierDefinition(label=label, routes=()) for label, _ in _GRADES)


def effective_product_tier_routes() -> tuple[ProductTierDefinition, ...]:
    if not private_switch_enabled():
        return PRODUCT_TIER_ROUTES
    registry = private_registry()
    if registry is None:
        return fail_closed_routes()
    return routes_from_registry(registry)


def effective_active_route_for(label: ProductTierLabel) -> ProductTierRoute | None:
    for tier in effective_product_tier_routes():
        if tier.label is label:
            for route in tier.routes:
                if route.status is ProductRouteStatus.EXECUTABLE:
                    return route
            return None
    return None


def _tier(grade: str):
    registry = private_registry()
    return registry.tiers.get(grade) if registry is not None else None


def free_primary_model_id() -> str:
    """The free grade's primary, from the private registry only.

    An unusable or absent private document answers an empty identity, so no
    caller can dispatch on a value that once shipped in the repository.
    """
    tier = _tier("free")
    return tier["primary"] if tier else ""


def free_fallback_model_id() -> str:
    """The free grade's first declared recovery model, or ``""."""
    tier = _tier("free")
    fallback = tier["fallback"] if tier else ()
    return fallback[0] if fallback else ""


def free_lane_model_ids() -> tuple[str, ...]:
    """Every model the private document designates for the free lane.

    The primary followed by its ordered recovery roster. Empty when no
    usable private document declares a free tier, so an explicit free-lane
    selection fails closed instead of matching a repository value.
    """
    tier = _tier("free")
    if tier is None:
        return ()
    return (tier["primary"], *tier["fallback"])


def paid_primary_model_id() -> str:
    """The paid grades' shared primary, from the private registry only."""
    tier = _tier("plus")
    return tier["primary"] if tier else ""


def tier_fallback_rosters() -> dict[str, tuple[str, ...]]:
    """Per-grade rosters in the shape the historical constant had.

    The free grade lists its fallbacks without the primary, because the
    router compares the request to the default first; every other grade
    keeps the primary at the head. Without a usable private document the
    answer is empty, which every caller treats as an unsupported tier.
    """
    registry = private_registry()
    if registry is None:
        return {}
    rosters: dict[str, tuple[str, ...]] = {}
    for grade in ("free", "plus", "pro", "max", "admin"):
        tier = registry.tiers.get(grade)
        if tier is None:
            continue
        rosters[grade] = (tuple(tier["fallback"]) if grade == "free"
                          else (tier["primary"], *tier["fallback"]))
    return rosters


__all__ = [
    "effective_active_route_for",
    "effective_product_tier_routes",
    "fail_closed_routes",
    "free_fallback_model_id",
    "free_lane_model_ids",
    "free_primary_model_id",
    "paid_primary_model_id",
    "private_registry",
    "routes_from_registry",
    "tier_fallback_rosters",
]


def free_candidate_providers() -> frozenset[str]:
    """The deployment's excluded free-candidate provider IDs (private env)."""
    import os

    raw = os.environ.get("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "")
    return frozenset(
        part.strip().casefold() for part in raw.split(",") if part.strip()
    )


def effective_is_free_execution_candidate(model_id: str | None) -> bool:
    """Switch-aware free-candidate refusal used by every runtime consumer."""
    from padiem_control_plane.product_tier_routes import is_free_execution_candidate

    return is_free_execution_candidate(
        model_id, excluded_providers=free_candidate_providers()
    )
