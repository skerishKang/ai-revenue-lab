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

FREE_PRIMARY_B14_MODEL_ID = "opencode-go/cat-jam-free"
FREE_FALLBACK_B14_MODEL_ID = "google/gemini-3.1-flash-lite"
TIER_FALLBACK_B14_MODELS = {
    "free": FREE_FALLBACK_B14_MODEL_ID,
    "plus": "google/gemini-3.5-flash-lite",
    "pro": "opencode-go/muse-spark-1.2-contributor",
    "max": "opencode-go/muse-spark-1.3-contributor",
}

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
# The active Free/Plus/Pro/Max primary routes below use Cat Jam. Retaining old
# HOLD entries documents retired choices; it does not disable a current grade.
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
        if tier.label is ProductTierLabel.PLUS and not active:
            held_ids = {
                route.model_id
                for route in tier.routes
                if route.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
            }
            _require(
                PLUS_HOLD_MODEL_ID in held_ids,
                "Padiem Plus without an executable route must expose the Plus hold identity",
            )
        if tier.label is ProductTierLabel.MAX:
            # Owner replaced Max HOLD with Cat Jam; preserve historic HOLD entries.
            held = {
                route.model_family
                for route in tier.routes
                if route.status is ProductRouteStatus.HOLD_AS_DATA_ONLY
            }
            _require(
                {"qwen", "glm"} <= held,
                "Max historical qwen and glm entries must remain data-only",
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
        label=ProductTierLabel.FREE,
        routes=(ProductTierRoute(
            route_id="free.cat-jam.v1", status=ProductRouteStatus.EXECUTABLE,
            model_family="cat-jam", provider_id="opencode-go",
            model_id=FREE_PRIMARY_B14_MODEL_ID, upstream_model="cat-jam-free",
            credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
            credential_binding="PADIEM_OPENCODE_API_KEY",
            evidence="B14 live Cat Jam response and owner Free model decision 2026-10-15.",
        ),),
    ),
    ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(
            ProductTierRoute(
                route_id="plus.cat-jam.v1", status=ProductRouteStatus.EXECUTABLE,
                model_family="cat-jam", provider_id="opencode-go",
                model_id=FREE_PRIMARY_B14_MODEL_ID, upstream_model="cat-jam-free",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_OPENCODE_API_KEY",
                evidence="Owner exact 4-tier Cat Jam primary decision, 2026-10-15.",
            ),
            ProductTierRoute(
                route_id="plus.hold.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="plus",
                model_id=PLUS_HOLD_MODEL_ID,
                hold_reason=(
                    "Historical #3568: the Space Bunny free route ended, so Plus was held "
                    "pending another primary at that time. This retained HOLD identity "
                    "does not block the currently executable Plus Cat Jam route."
                ),
                evidence="#3568 model-independent successor-pending hold.",
            ),
            ProductTierRoute(
                route_id="plus.space-bunny-alpha.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="space-bunny-alpha",
                provider_id="kilo",
                model_id="kilo/stealth-space-bunny-alpha",
                upstream_model="stealth/space-bunny-alpha",
                credential_mode=ProductCredentialMode.ANONYMOUS,
                hold_reason=(
                    "Historical #3568: the Space Bunny free lane is no longer used "
                    "for Padiem/Claw execution. Retained as inactive history, "
                    "not as a designated grade fallback."
                ),
                evidence=(
                    "Historical owner decision #3209 / #3143 and Production evidence in "
                    "#3566; execution disabled by #3568."
                ),
            ),
            ProductTierRoute(
                route_id="plus.agnes-3.0-flash.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="agnes-3.0-flash",
                provider_id="agnes-ai",
                model_id="agnes-ai/agnes-3.0-flash",
                upstream_model="agnes-3.0-flash",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_AGNES_API_KEY",
                hold_reason=(
                    "Superseded as the active Padiem Plus route by owner decision "
                    "#3209 (Space Bunny Alpha). Retained as historical data only; "
                    "the Agnes provider registration itself is preserved, but it is not "
                    "a designated current grade fallback."
                ),
                evidence=(
                    "Historical Plus route; B14 app/pilot/agnes_provider.py "
                    "registration (#2133) preserved."
                ),
            ),
            ProductTierRoute(
                route_id="plus.poolside-laguna-direct.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="poolside-laguna",
                provider_id="poolside",
                model_id="poolside/laguna-s-2.1",
                upstream_model="poolside/laguna-s-2.1",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_POOLSIDE_API_KEY",
                hold_reason=(
                    "Poolside Laguna was a historical fixed-chain candidate; it is "
                    "retained as inactive tier history, not as a current "
                    "owner-designated grade fallback."
                ),
                evidence=(
                    "B14 app/pilot/poolside_provider.py registration (#954)."
                ),
            ),
        ),
    ),
    ProductTierDefinition(
        label=ProductTierLabel.PRO,
        routes=(
            ProductTierRoute(
                route_id="pro.cat-jam.v1", status=ProductRouteStatus.EXECUTABLE,
                model_family="cat-jam", provider_id="opencode-go",
                model_id=FREE_PRIMARY_B14_MODEL_ID, upstream_model="cat-jam-free",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_OPENCODE_API_KEY",
                evidence="Owner exact 4-tier Cat Jam primary decision, 2026-10-15.",
            ),
            ProductTierRoute(
                route_id="pro.hold.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="pro",
                model_id=PRO_HOLD_MODEL_ID,
                hold_reason=(
                    "Historical #2601: the prior B.AI-backed Pro route was disabled "
                    "pending a replacement. This retained HOLD identity does not "
                    "block the currently executable Pro Cat Jam route."
                ),
                evidence="#2601 temporary Plus-only product posture.",
            ),
            ProductTierRoute(
                route_id="pro.b-ai-qwen3.8-flash.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="qwen3.8-flash",
                provider_id="b-ai",
                model_id="b-ai/qwen3.8-flash",
                upstream_model="qwen3.8-flash",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_B_AI_API_KEY",
                hold_reason=(
                    "Temporarily removed from executable Padiem Pro by owner decision #2601 "
                    "after provider/model instability. Retained as historical route data only."
                ),
                evidence=(
                    "Historical owner selection #2571 and B14 registration #2133; "
                    "execution disabled by #2601."
                ),
            ),
            ProductTierRoute(
                route_id="pro.kilo-nemotron-3-ultra-free.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="nemotron-3-ultra",
                provider_id="kilo",
                model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
                credential_mode=ProductCredentialMode.ANONYMOUS,
                hold_reason=(
                    "Superseded as the active Padiem Pro route by owner decision #2571. "
                    "Retained as historical data only, not as a current grade fallback."
                ),
                evidence=(
                    "Historical B14 Kilo Nemotron lane (#956/#2096/#2099); replaced by "
                    "B.AI Qwen3.8-Flash selection on 2026-09-16."
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
                route_id="max.cat-jam.v1", status=ProductRouteStatus.EXECUTABLE,
                model_family="cat-jam", provider_id="opencode-go",
                model_id=FREE_PRIMARY_B14_MODEL_ID, upstream_model="cat-jam-free",
                credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_OPENCODE_API_KEY",
                evidence="Owner exact 4-tier Cat Jam primary decision, 2026-10-15.",
            ),
            ProductTierRoute(
                route_id="max.hold.qwen.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="qwen",
                model_id=MAX_HOLD_MODEL_ID,
                hold_reason=(
                    "Historical Max Qwen HOLD placeholder: the older B.AI Pro route was "
                    "not a Max selection. Max now has a separately executable "
                    "Cat Jam primary; this Qwen entry remains inactive history."
                ),
            ),
            ProductTierRoute(
                route_id="max.hold.glm.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="glm",
                hold_reason=(
                    "Historical Max GLM HOLD placeholder: zai/glm-5.2 appears only "
                    "in the B60 reference registry, not the executable Max route. "
                    "Max now uses its separately declared Cat Jam primary."
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
