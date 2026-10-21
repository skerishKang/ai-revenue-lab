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
    tier resolver. apps/korean-ai-platform/app/pilot/tier_registry_v1.py
    is a separate legacy governance projection, not the live route.

Credential fields carry binding NAMES only (platform secret identifiers),
never secret values. This module performs no I/O or provider dispatch;
Chat and Claw read its route definitions and B14 separately owns
registration, upstream execution and recoverable-error failover.
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

FREE_PRIMARY_B14_MODEL_ID = "google/gemini-3.1-flash-lite"
FREE_FALLBACK_B14_MODEL_ID = "google/gemma-4-26b-a4b-it"
# #5009: Plus/Pro/Max default. Registered and enabled in B14
# (b14_models.json) and already the verified administrator-only Chat model,
# so the provider path is proven; the per-grade provider live call is still
# pending and tracked by each route's evidence.
MUSE_B14_MODEL_ID = "opencode-go/muse-spark-1.3-contributor"
MUSE_B14_UPSTREAM_MODEL = "muse-spark-1.3-contributor"
# #2505 (owner decision 2026-10-21): an OpenCode Go free model is never an
# execution candidate, so it leaves every designated per-grade roster. The
# paid OpenCode Go model stays; only the free family is excluded.
TIER_FALLBACK_B14_MODELS = {
    "max": ("opencode-go/muse-spark-1.3-contributor",),
    "pro": ("google/gemma-4-31b-it",),
    "plus": ("google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
    "free": ("google/gemma-4-26b-a4b-it", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it"),
}

# Owner decision 2026-10-21 (#2505): OpenCode Go free models are not execution
# candidates. The provider prefix and the ``-free`` suffix identify the
# family; no other provider's free model is affected by this decision.
FREE_CANDIDATE_PROVIDER = "opencode-go"


def is_free_execution_candidate(model_id: str | None) -> bool:
    """Whether one model identity is an excluded free execution candidate.

    Used by the shared grade route contract so an administrator can never
    bind an excluded free model to a grade, and so a stored row can never
    serve one either.
    """
    if not isinstance(model_id, str) or not model_id:
        return False
    provider, separator, tail = model_id.strip().casefold().partition("/")
    return bool(separator) and provider == FREE_CANDIDATE_PROVIDER and tail.endswith("-free")


# A declared grade's fallback is a specific owner choice, not b14/auto or
# permission for an unrelated/paid model. B14 verifies live registration,
# credentials and eligible 429/5xx/timeout before any failover.
OWNER_PINNED_TIER_FALLBACK_ON_RECOVERABLE_ERROR = True

class ProductTierLabel(str, Enum):
    FREE = "Padiem Free"
    PLUS = "Padiem Plus"
    PRO = "Padiem Pro"
    MAX = "Padiem Max"

class ProductRouteStatus(str, Enum):
    EXECUTABLE = "executable"
    HOLD_AS_DATA_ONLY = "hold_as_data_only"
    RETIRED_AS_DATA_ONLY = "retired_as_data_only"

class ProductCredentialMode(str, Enum):
    ANONYMOUS = "anonymous"
    PLATFORM_SECRET_BINDING = "platform_secret_binding"

# Historical HOLD sentinels are identity markers, not active B14 model IDs.
# Current executable routes below select Google for Free and Muse for the
# paid tiers; historical HOLD choices remain only in the Git history.
PLUS_HOLD_MODEL_ID = "padiem-profile/plus-hold"
PRO_HOLD_MODEL_ID = "padiem-profile/pro-hold"
MAX_HOLD_MODEL_ID = "padiem-profile/max-hold"

# Retired upstream free lanes (#2094 gateway-list evidence, #2096/#2097
# repair + unregistration). They may never appear as an executable product
# route in any consumer.
RETIRED_PRODUCT_MODEL_IDS = frozenset(
    {
        "kilo/minimax-minimax-m3-free",
        "kilo/tencent-hy3-free",
    }
)

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

PRODUCT_TIER_ROUTES: tuple[ProductTierDefinition, ...] = (
    ProductTierDefinition(
        label=ProductTierLabel.FREE,
        routes=(ProductTierRoute(
            route_id="free.gemini-3.1-flash-lite.v1",
            status=ProductRouteStatus.EXECUTABLE,
            model_family="gemini-3.1-flash-lite",
            provider_id="google",
            model_id=FREE_PRIMARY_B14_MODEL_ID,
            upstream_model="gemini-3.1-flash-lite",
            credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
            credential_binding="PADIEM_B14_CREDENTIAL_03",
            evidence="Owner Free Google model priority decision 2026-10-20.",
        ),),
    ),
    *(
        ProductTierDefinition(
            label=label,
            routes=(ProductTierRoute(
                route_id=f"{label.value.split()[-1].lower()}.muse-spark.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="muse-spark",
                provider_id="opencode-go",
                model_id=MUSE_B14_MODEL_ID,
                upstream_model=MUSE_B14_UPSTREAM_MODEL,
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_B14_CREDENTIAL_11",
                evidence="Owner Plus/Pro/Max Muse primary decision #5009.",
            ),),
        )
        for label in (ProductTierLabel.PLUS, ProductTierLabel.PRO, ProductTierLabel.MAX)
    ),
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
