"""B14 explicit tier registry contract v1 (#2088 ACT-1).

Additive, network-free, execution-free data contract that maps the three
user-visible Padiem tiers to explicit ``provider_id`` + ``model_id`` +
``route_id`` selections.

Owner policy encoded here (docs/product/B14_Padiem_Chat_2026-09-04.md, #2088):

* AUTO_PROVIDER_SELECTION = NO
* AUTO_MODEL_SELECTION = NO
* USER_VISIBLE_AUTO_LABEL = NO
* SILENT_FALLBACK = NO
* USER_VISIBLE_LABELS = "Padiem Plus" / "Padiem Pro" / "Padiem Max"

Every executable tier route names one fixed provider route; unverified
candidates are carried as data-only entries and can never be resolved as
executable. Credential fields hold *binding names only* (platform secret
identifiers), never secret values.

This module imports nothing outside the standard library and performs no
I/O at import time, so importing it cannot trigger provider registration,
network calls, or credential reads. It is not wired into the gateway,
router core, or routing policy in this change; wiring is a separate
reviewed step (#2088 ACT-3 gate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = "b14.tier_registry.v1"
POLICY_ID = "explicit_tier_selection_v1"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CREDENTIAL_BINDING_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_FORBIDDEN_VISIBLE_TOKENS = ("auto", "fallback")


class TierRegistryError(ValueError):
    """Raised when the registry violates the #2088 contract (fail closed)."""


class TierLabel(str, Enum):
    PLUS = "Padiem Plus"
    PRO = "Padiem Pro"
    MAX = "Padiem Max"


class RouteStatus(str, Enum):
    EXECUTABLE = "executable"
    CANDIDATE_DATA_ONLY = "candidate_data_only"
    HOLD_AS_DATA_ONLY = "hold_as_data_only"


class CredentialMode(str, Enum):
    ANONYMOUS = "anonymous"
    PLATFORM_SECRET_BINDING = "platform_secret_binding"


@dataclass(frozen=True, slots=True)
class TierRoute:
    route_id: str
    status: RouteStatus
    model_family: str
    provider_id: str | None = None
    model_id: str | None = None
    upstream_model: str | None = None
    credential_mode: CredentialMode = CredentialMode.ANONYMOUS
    credential_binding: str | None = None
    hold_reason: str | None = None
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class TierDefinition:
    label: TierLabel
    routes: tuple[TierRoute, ...]
    silent_fallback_allowed: bool = False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TierRegistryError(message)


def _validate_route(route: TierRoute, tier: TierLabel) -> None:
    where = f"{tier.value}/{route.route_id}"
    _require(bool(_SAFE_ID_RE.match(route.route_id)), f"{where}: unsafe route_id")
    _require(bool(route.model_family), f"{where}: model_family is required")
    if route.status is RouteStatus.EXECUTABLE:
        _require(
            route.provider_id is not None and bool(_SAFE_ID_RE.match(route.provider_id)),
            f"{where}: executable route requires an explicit provider_id",
        )
        _require(
            route.model_id is not None and bool(_SAFE_ID_RE.match(route.model_id)),
            f"{where}: executable route requires an explicit model_id",
        )
        _require(bool(route.evidence), f"{where}: executable route requires evidence")
    else:
        _require(
            bool(route.hold_reason),
            f"{where}: data-only route requires an explicit hold/candidate reason",
        )
    for value in (route.provider_id, route.model_id, route.upstream_model):
        if value is not None:
            _require(bool(_SAFE_ID_RE.match(value)), f"{where}: unsafe identifier {value!r}")
    if route.credential_mode is CredentialMode.PLATFORM_SECRET_BINDING:
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


def validate_tier_registry(tiers: tuple[TierDefinition, ...]) -> None:
    labels = [tier.label for tier in tiers]
    _require(
        sorted(label.value for label in labels) == sorted(tier.value for tier in TierLabel),
        "registry must define exactly the three Padiem tier labels",
    )
    _require(len(set(labels)) == len(labels), "duplicate tier label in registry")
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
        active = [r for r in tier.routes if r.status is RouteStatus.EXECUTABLE]
        _require(len(active) <= 1, f"{tier.label.value}: at most one executable route")
        for route in tier.routes:
            _validate_route(route, tier.label)
        if tier.label is TierLabel.MAX:
            _require(not active, "Padiem Max must not expose an executable route")
            held = {
                route.model_family
                for route in tier.routes
                if route.status is RouteStatus.HOLD_AS_DATA_ONLY
            }
            _require(
                {"qwen", "glm"} <= held,
                "Padiem Max must hold qwen and glm as data-only pending evidence",
            )


TIER_REGISTRY: tuple[TierDefinition, ...] = (
    TierDefinition(
        label=TierLabel.PLUS,
        routes=(
            TierRoute(
                route_id="plus.kilo-laguna-s-2.1-free.v1",
                status=RouteStatus.EXECUTABLE,
                model_family="poolside-laguna",
                provider_id="kilo",
                model_id="kilo/poolside-laguna-s-2.1-free",
                upstream_model="poolside/laguna-s-2.1:free",
                credential_mode=CredentialMode.ANONYMOUS,
                evidence=(
                    "app/pilot/kilo_provider.py KILO_LAGUNA_MODEL_ID (#956 explicit-only "
                    "free route); current Padiem Chat Plus mapping "
                    "apps/padiem-chat/app/model_policy.py (read-only reference)"
                ),
            ),
            TierRoute(
                route_id="plus.sensenova-6.8-flash-lite.v1",
                status=RouteStatus.CANDIDATE_DATA_ONLY,
                model_family="sensenova",
                provider_id="sensenova",
                model_id="sensenova/sensenova-6.8-flash-lite",
                upstream_model="sensenova-6.8-flash-lite",
                credential_mode=CredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_SENSENOVA_API_KEY",
                hold_reason=(
                    "owner-approved candidate for Plus; not promoted to the active Plus "
                    "route by an explicit selection decision yet"
                ),
                evidence="app/pilot/sensenova_provider.py (#955 registration)",
            ),
            TierRoute(
                route_id="plus.poolside-laguna-direct.v1",
                status=RouteStatus.CANDIDATE_DATA_ONLY,
                model_family="poolside-laguna",
                provider_id="poolside",
                model_id="poolside/laguna-s-2.1",
                upstream_model="poolside/laguna-s-2.1",
                credential_mode=CredentialMode.PLATFORM_SECRET_BINDING,
                credential_binding="PADIEM_POOLSIDE_API_KEY",
                hold_reason=(
                    "direct Poolside route kept as Plus candidate data only; the active "
                    "Plus route stays the single explicit selection above"
                ),
                evidence="app/pilot/poolside_provider.py (#954 registration)",
            ),
        ),
    ),
    TierDefinition(
        label=TierLabel.PRO,
        routes=(
            TierRoute(
                route_id="pro.kilo-minimax-m3-free.v1",
                status=RouteStatus.EXECUTABLE,
                model_family="minimax-m3",
                provider_id="kilo",
                model_id="kilo/minimax-minimax-m3-free",
                upstream_model="minimax/minimax-m3:free",
                credential_mode=CredentialMode.ANONYMOUS,
                evidence=(
                    "app/pilot/kilo_provider.py KILO_MINIMAX_M3_MODEL_ID (#956 explicit-only "
                    "free route); current Padiem Chat Pro default "
                    "apps/padiem-chat/app/model_policy.py (read-only reference)"
                ),
            ),
            TierRoute(
                route_id="pro.kilo-nemotron-3-ultra-free.v1",
                status=RouteStatus.CANDIDATE_DATA_ONLY,
                model_family="nemotron-3-ultra",
                provider_id="kilo",
                model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
                credential_mode=CredentialMode.ANONYMOUS,
                hold_reason=(
                    "kept as Pro candidate data only; free availability is a dated snapshot "
                    "and promotion requires an explicit owner selection"
                ),
                evidence="app/pilot/kilo_provider.py KILO_NEMOTRON_MODEL_ID (#956)",
            ),
        ),
    ),
    TierDefinition(
        label=TierLabel.MAX,
        routes=(
            TierRoute(
                route_id="max.qwen.hold.v1",
                status=RouteStatus.HOLD_AS_DATA_ONLY,
                model_family="qwen",
                hold_reason=(
                    "no B14 provider registration or route evidence exists for any Qwen "
                    "model; Padiem Max stays unbound pending explicit evidence (#1397)"
                ),
            ),
            TierRoute(
                route_id="max.glm.hold.v1",
                status=RouteStatus.HOLD_AS_DATA_ONLY,
                model_family="glm",
                hold_reason=(
                    "zai/glm-5.2 appears only in the B60 reference registry; no B14 route "
                    "evidence exists; Padiem Max stays unbound pending explicit evidence"
                ),
            ),
        ),
    ),
)

validate_tier_registry(TIER_REGISTRY)


def get_tier(label: TierLabel) -> TierDefinition:
    for tier in TIER_REGISTRY:
        if tier.label is label:
            return tier
    raise TierRegistryError(f"unknown tier label: {label!r}")


def active_route_for(label: TierLabel) -> TierRoute | None:
    tier = get_tier(label)
    for route in tier.routes:
        if route.status is RouteStatus.EXECUTABLE:
            return route
    return None
