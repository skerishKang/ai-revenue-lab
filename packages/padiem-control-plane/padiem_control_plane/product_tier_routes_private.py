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


__all__ = [
    "effective_active_route_for",
    "effective_product_tier_routes",
    "fail_closed_routes",
    "private_registry",
    "routes_from_registry",
]
