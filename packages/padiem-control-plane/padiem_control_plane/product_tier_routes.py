"""Shared Plus/Pro/Max product-tier route declaration contract v1 (#2099 STEP-1).

Stdlib-only, network-free, execution-free data contract — the canonical
DECLARATION of which explicit provider route backs each user-visible Padiem
product tier. It is intentionally owned by the neutral control-plane package
so Chat (#2099 STEP-2) and Claw (#2100) consume the SAME single source without
any cross-app import of another product's internals.

Owner policy encoded here (#2085):

* AUTO_PROVIDER_SELECTION = NO
* AUTO_MODEL_SELECTION = NO
* USER_VISIBLE_AUTO_LABEL = NO
* SILENT_FALLBACK = NO
* USER_VISIBLE_LABELS = "Padiem Plus" / "Padiem Pro" / "Padiem Max"

Separation of duties (#2099 ACT-0 decision):
  - This contract DECLARES the product mapping (provider_id + model_id +
    credential_mode + status + retirement/hold reasons).
  - The Business 14 catalog (apps/korean-ai-platform/app/pilot/catalog.py plus
    provider registration modules) remains the final EXECUTION authority: a
    declared route can only run if B14 has it registered and not retired.
    Retired model IDs here mirror B14's RETIRED_KILO_FREE_MODEL_IDS and Chat's
    RETIRED_B14_MODEL_IDS; STEP-1 pins all three in agreement via parity
    tests. Migration of consumers is sequenced in #2099 STEP-2/STEP-3;
    apps/korean-ai-platform/app/pilot/tier_registry_v1.py is a legacy
    governance projection and stays runtime-unwired.

Credential fields carry binding NAMES only (platform secret identifiers),
never secret values. This module performs no I/O, no imports outside the
standard library, and is not wired into any gateway/router/policy runtime.
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

class ProductTierLabel(str, Enum):
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

# Product-level sentinel for the Padiem Max tier (#1397 evidence pending). It
# mirrors apps/padiem-chat/app/model_policy.py MAX_HOLD_MODEL_ID verbatim and
# is deliberately NOT a B14 catalog model ID.
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
        "contract must define exactly the three Padiem tier labels",
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
            f"{tier.label.value}: silent fallback is forbidden by owner policy",
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
        if tier.label is ProductTierLabel.MAX:
            _require(not active, "Padiem Max must not expose an executable route")
            held = {
                route.model_family
                for route in tier.routes
                if route.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
            }
            _require(
                {"qwen", "glm"} <= held,
                "Padiem Max must hold qwen and glm as data-only pending evidence (#1397)",
            )
            _require(
                all(
                    r.model_id in (None, MAX_HOLD_MODEL_ID)
                    for r in tier.routes
                    if r.model_id is not None and r.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
                ),
                "Padiem Max hold routes may only name the Max hold sentinel",
            )

PRODUCT_TIER_ROUTES: tuple[ProductTierDefinition, ...] = (
    ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(
            ProductTierRoute(
                route_id="plus.kilo-laguna-s-2.1-free.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="poolside-laguna",
                provider_id="kilo",
                model_id="kilo/poolside-laguna-s-2.1-free",
                upstream_model="poolside/laguna-s-2.1:free",
                credential_mode=ProductCredentialMode.ANONYMOUS,
                evidence=(
                    "B14 catalog: apps/korean-ai-platform/app/pilot/kilo_provider.py "
                    "KILO_LAGUNA_MODEL_ID (#956; listed on the 2026-09-08 Kilo Gateway "
                    "model list); Chat LOW route apps/padiem-chat/app/model_policy.py"
                ),
            ),
        ),
    ),
    ProductTierDefinition(
        label=ProductTierLabel.PRO,
        routes=(
            ProductTierRoute(
                route_id="pro.kilo-nemotron-3-ultra-free.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="nemotron-3-ultra",
                provider_id="kilo",
                model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
                credential_mode=ProductCredentialMode.ANONYMOUS,
                evidence=(
                    "B14 catalog: apps/korean-ai-platform/app/pilot/kilo_provider.py "
                    "KILO_NEMOTRON_MODEL_ID (#956; listed on the 2026-09-08 Kilo Gateway "
                    "model list); #2096 Chat default/Pro repair; fixed_chain_v1 position 2 (#2097)"
                ),
            ),
            ProductTierRoute(
                route_id="pro.kilo-minimax-m3-free.retired.v1",
                status=ProductRouteStatus.RETIRED_AS_DATA_ONLY,
                model_family="minimax-m3",
                provider_id="kilo",
                model_id="kilo/minimax-minimax-m3-free",
                upstream_model="minimax/minimax-m3:free",
                credential_mode=ProductCredentialMode.ANONYMOUS,
                retired_reason=(
                    "RETIRED: Kilo Gateway removed minimax/minimax-m3:free from its free "
                    "model list (verified 2026-09-08, #2094); unregistered from the B14 "
                    "executable catalog and fixed_chain_v1 in #2097; never re-executable "
                    "without a fresh explicit owner selection with gateway evidence."
                ),
                evidence="#2094 default-route failure root cause (historical #1442 candidate)",
            ),
        ),
    ),
    ProductTierDefinition(
        label=ProductTierLabel.MAX,
        routes=(
            ProductTierRoute(
                route_id="max.hold.qwen.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="qwen",
                model_id=MAX_HOLD_MODEL_ID,
                hold_reason=(
                    "no B14 provider registration or route evidence exists for any Qwen "
                    "model; Padiem Max stays unbound pending explicit evidence (#1397)"
                ),
            ),
            ProductTierRoute(
                route_id="max.hold.glm.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="glm",
                hold_reason=(
                    "zai/glm-5.2 appears only in the B60 reference registry; no B14 route "
                    "evidence exists; Padiem Max stays unbound pending explicit evidence"
                ),
            ),
        ),
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
