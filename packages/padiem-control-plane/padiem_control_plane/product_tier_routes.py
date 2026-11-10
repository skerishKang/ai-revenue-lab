"""Shared Free/Plus/Pro/Max product-tier route declaration contract v1.

Stdlib-only, network-free, execution-free data contract — the canonical
DECLARATION of which explicit provider route backs each user-visible Padiem
product tier. It is intentionally owned by the neutral control-plane package
so Chat (#2099 STEP-2) and Claw (#2100) consume the SAME single source without
any cross-app import of another product's internals.

Owner policy encoded here (#2085):

* AUTO_PROVIDER_SELECTION = NO
* AUTO_MODEL_SELECTION = NO
* USER_VISIBLE_AUTO_LABEL = NO
* UNRESTRICTED_SILENT_MODEL_SUBSTITUTION = NO
* OWNER_PINNED_TIER_FALLBACK = YES, on recoverable provider failures only
* USER_VISIBLE_LABELS = "Padiem Plus" / "Padiem Pro" / "Padiem Max"

Separation of duties (#2099 ACT-0 decision):
  - This contract DECLARES the product mapping (provider_id + model_id +
    credential_mode + status + retirement/hold reasons).
  - The Business 14 catalog (apps/korean-ai-platform/app/pilot/catalog.py plus
    provider registration modules) remains the final EXECUTION authority: a
    declared route can only run if B14 has it registered and not retired.
    Retired model IDs here mirror B14's RETIRED_KILO_FREE_MODEL_IDS and Chat's
    RETIRED_B14_MODEL_IDS; STEP-1 pins all three in agreement via parity
    tests. Chat and Claw now consume these declarations through the shared
    tier resolver. This module is the single product-tier route authority;
    no second tier registry is maintained anywhere else.

Credential fields carry binding NAMES only (platform secret identifiers),
never secret values. This module performs no I/O or provider dispatch;
Chat and Claw read its route definitions and B14 separately owns
registration, upstream execution and recoverable-error failover.

#6828 3단계: the repository ships no model or provider value. This
declaration carries the tier STRUCTURE only — every grade is declared without
an executable route, so a host that has not switched to the private registry
(``PADIEM_MODELS_REGISTRY``) or whose document is unusable has nothing to
dispatch (fail closed). The switch-aware reader beside this module
(``product_tier_routes_private``) resolves the real routes from the private
registry and is the consumer-facing answer; the legacy per-name helpers live
there too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

PRODUCT_TIER_POLICY_VERSION = "padiem.product_tier_routes.v1"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CREDENTIAL_BINDING_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_FORBIDDEN_VISIBLE_TOKENS = ("auto", "fallback")

class ProductTierRoutesError(ValueError):
    """Raised when the contract violates the #2085/#2099 policy (fail closed)."""

# Owner decision 2026-10-21 (#2505): one provider family's free models are
# not execution candidates. The ``-free`` suffix identifies the family; the
# rule is provider-agnostic so the repository carries no provider name.


def is_free_execution_candidate(
    model_id: str | None,
    *,
    excluded_providers: frozenset[str] = frozenset(),
) -> bool:
    """Whether one model identity is an excluded free execution candidate.

    Used by the shared grade route contract so an administrator can never
    bind an excluded free model to a grade, and so a stored row can never
    serve one either.

    #6828 3단계: the excluded provider set is deployment data, not a public
    repository value. The contract stays pure: callers pass the deployment's
    excluded provider IDs (the private reader loads them from the
    ``PADIEM_B14_FREE_CANDIDATE_PROVIDERS`` env variable). An empty set
    excludes nothing, so a free-suffixed direct-pilot lane keeps working.
    """
    if not isinstance(model_id, str) or not model_id:
        return False
    provider, separator, tail = model_id.strip().casefold().partition("/")
    if not separator or not tail.endswith("-free"):
        return False
    return provider in (excluded_providers or frozenset())


class ProductTierLabel(str, Enum):
    FREE = "Padiem Free"
    PLUS = "Padiem Plus"
    PRO = "Padiem Pro"
    MAX = "Padiem Max"
    ADMIN = "Padiem 관리자"

class ProductRouteStatus(str, Enum):
    EXECUTABLE = "executable"
    HOLD_AS_DATA_ONLY = "hold_as_data_only"
    RETIRED_AS_DATA_ONLY = "retired_as_data_only"

# One shared primary-route switch for a separately approved hold return is
# decided in the private registry; the repository carries no route values.

class ProductCredentialMode(str, Enum):
    ANONYMOUS = "anonymous"
    PLATFORM_SECRET_BINDING = "platform_secret_binding"

# Historical HOLD sentinels are identity markers, not active B14 model IDs.
PLUS_HOLD_MODEL_ID = "padiem-profile/plus-hold"
PRO_HOLD_MODEL_ID = "padiem-profile/pro-hold"
MAX_HOLD_MODEL_ID = "padiem-profile/max-hold"

# Retired upstream free lanes (#2094 gateway-list evidence, #2096/#2097
# repair + unregistration). They may never appear as an executable product
# route in any consumer. The repository carries no model value: retirement
# authority is the B14 catalog's retired list read from the private registry,
# so this set stays empty here and the route validator's check is a
# belt-and-braces guard that costs nothing when empty.
RETIRED_PRODUCT_MODEL_IDS = frozenset()

@dataclass(frozen=True, slots=True)
class ProductTierRoute:
    route_id: str
    status: ProductRouteStatus
    model_family: str
    provider_id: str | None = None
    model_id: str | None = None
    upstream_model: str | None = None
    credential_mode: ProductCredentialMode = ProductCredentialMode.ANONYMOUS
    credential_binding: str | None = None
    hold_reason: str | None = None
    retired_reason: str | None = None
    evidence: str | None = None

@dataclass(frozen=True, slots=True)
class ProductTierDefinition:
    label: ProductTierLabel
    routes: tuple[ProductTierRoute, ...]
    # False forbids arbitrary/unlisted substitutions, NOT the separately
    # owner-pinned per-grade provider-failure recovery roster below.
    silent_fallback_allowed: bool = False
    policy_version: str = PRODUCT_TIER_POLICY_VERSION

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProductTierRoutesError(message)

def _validate_route(route: ProductTierRoute, tier: ProductTierLabel) -> None:
    where = f"{tier.value}/{route.route_id}"
    _require(bool(_SAFE_ID_RE.match(route.route_id)), f"{where}: unsafe route_id")
    _require(bool(route.model_family), f"{where}: model_family is required")
    if route.status is ProductRouteStatus.EXECUTABLE:
        _require(
            route.provider_id is not None and bool(_SAFE_ID_RE.match(route.provider_id)),
            f"{where}: executable route requires an explicit provider_id",
        )
        _require(
            route.model_id is not None and bool(_SAFE_ID_RE.match(route.model_id)),
            f"{where}: executable route requires an explicit model_id",
        )
        _require(bool(route.evidence), f"{where}: executable route requires evidence")
        _require(
            route.model_id not in RETIRED_PRODUCT_MODEL_IDS,
            f"{where}: retired model may never be executable",
        )
        _require(
            not is_free_execution_candidate(route.model_id),
            f"{where}: an excluded free model may never be executable",
        )
    else:
        documented = (route.hold_reason or "") + (route.retired_reason or "")
        _require(
            bool(documented.strip()),
            f"{where}: non-executable route requires an explicit hold/retirement reason",
        )
        if route.status is ProductRouteStatus.RETIRED_AS_DATA_ONLY:
            _require(
                route.model_id in RETIRED_PRODUCT_MODEL_IDS,
                f"{where}: retired route entries must name a retired model id",
            )
    for value in (route.provider_id, route.model_id, route.upstream_model):
        if value is not None:
            _require(bool(_SAFE_ID_RE.match(value)), f"{where}: unsafe identifier {value!r}")
    if route.credential_mode is ProductCredentialMode.PLATFORM_SECRET_BINDING:
        _require(
            route.credential_binding is not None
            and bool(_CREDENTIAL_BINDING_RE.match(route.credential_binding)),
            f"{where}: credential_binding must be a platform secret binding name",
        )
    else:
        _require(
            route.credential_binding is None,
            f"{where}: anonymous routes must not carry a credential binding",
        )

def validate_product_tier_routes(tiers: tuple[ProductTierDefinition, ...]) -> None:
    labels = [tier.label for tier in tiers]
    _require(
        sorted(label.value for label in labels) == sorted(tier.value for tier in ProductTierLabel),
        "contract must define all Padiem tier labels",
    )
    _require(len(set(labels)) == len(labels), "duplicate tier label in contract")
    for tier in tiers:
        for token in _FORBIDDEN_VISIBLE_TOKENS:
            _require(
                token not in tier.label.value.lower(),
                f"user-visible tier label must not contain {token!r}",
            )
        _require(
            tier.silent_fallback_allowed is False,
            f"{tier.label.value}: unlisted silent fallback is forbidden; owner-pinned grade backup remains allowed",
        )
        _require(
            tier.policy_version == PRODUCT_TIER_POLICY_VERSION,
            f"{tier.label.value}: unsupported policy version {tier.policy_version!r}",
        )
        active = [r for r in tier.routes if r.status is ProductRouteStatus.EXECUTABLE]
        _require(len(active) <= 1, f"{tier.label.value}: at most one executable route")
        for route in tier.routes:
            _validate_route(route, tier.label)
            for token in _FORBIDDEN_VISIBLE_TOKENS:
                _require(
                    token not in route.route_id.lower(),
                    f"{tier.label.value}: route_id must not contain {token!r}",
                )

# --- value-free declaration (#6828 3단계) ---
#
# The declaration itself carries no model or provider value: every grade is
# declared without an executable route, so a host that has not switched to
# the private registry — or whose document is unusable — has nothing to
# dispatch. The switch-aware reader beside this module
# (``product_tier_routes_private``) resolves the real routes from
# ``PADIEM_MODELS_REGISTRY`` and is the consumer-facing answer.
PRODUCT_TIER_ROUTES: tuple[ProductTierDefinition, ...] = tuple(
    ProductTierDefinition(label=label, routes=()) for label in ProductTierLabel
)
validate_product_tier_routes(PRODUCT_TIER_ROUTES)

def get_tier(label: ProductTierLabel) -> ProductTierDefinition:
    for tier in PRODUCT_TIER_ROUTES:
        if tier.label is label:
            return tier
    raise ProductTierRoutesError(f"unknown product tier {label!r}")

def active_route_for(label: ProductTierLabel) -> ProductTierRoute | None:
    for route in get_tier(label).routes:
        if route.status is ProductRouteStatus.EXECUTABLE:
            return route
    return None
