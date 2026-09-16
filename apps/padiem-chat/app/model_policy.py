from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from padiem_control_plane.product_tier_routes import (
    RETIRED_PRODUCT_MODEL_IDS,
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)
from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID as _CONTRACT_MAX_HOLD_MODEL_ID,
)

# #2099 STEP-2: the Plus/Pro/Max route IDs are no longer literals owned here.
# They are derived from the neutral shared declaration contract
# (padiem_control_plane.product_tier_routes), which Chat and — from #2100 —
# Claw consume as their single product-side source of truth. Business 14's
# catalog remains the final execution authority: a contract route that B14
# unregisters fails closed at dispatch time.

def _contract_route_id(label: ProductTierLabel) -> str:
    try:
        route = active_route_for(label)
    except ProductTierRoutesError as exc:  # fail closed before any dispatch
        raise RuntimeError(f"product tier route contract is invalid: {exc}") from exc
    if route is None or not route.model_id:
        raise RuntimeError(f"product tier route contract has no executable route for {label.value}")
    return route.model_id


DEFAULT_CHAT_PROFILE = "medium"
AUTO_B14_MODEL_ID = "b14/auto"

TIER_ID_TO_LABEL: dict[str, ProductTierLabel] = {
    "plus": ProductTierLabel.PLUS,
    "pro": ProductTierLabel.PRO,
    "max": ProductTierLabel.MAX,
}
TIER_ID_TO_PROFILE: dict[str, str] = {
    "plus": "low",
    "pro": "medium",
    "max": "high",
}

_REQUEST_TIER_ID: ContextVar[str | None] = ContextVar(
    "padiem_request_tier_id",
    default=None,
)

# Product tiers are intentionally decoupled from upstream model/provider names.
# LOW/MEDIUM/HIGH remain internal compatibility identifiers only; users see
# Padiem Plus / Padiem Pro / Padiem Max.
LOW_B14_MODEL_ID = _contract_route_id(ProductTierLabel.PLUS)
MEDIUM_B14_MODEL_ID = _contract_route_id(ProductTierLabel.PRO)
MAX_HOLD_MODEL_ID = _CONTRACT_MAX_HOLD_MODEL_ID

# Kilo Gateway free lanes that are no longer offered upstream. Re-checked
# against the public Gateway model list on 2026-09-08: neither
# ``minimax/minimax-m3:free`` nor ``tencent/hy3:free`` is listed anymore, so
# both product routes are retired and must never back an executable tier.
# (#2094: the stale minimax default caused every Pro/default chat failure.
# #2099 STEP-2: the set itself is declared once in the shared contract.)
RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)
# Compatibility name retained for consumers that reason in low/medium/high
# profiles. High currently names the Max product tier but is deliberately not
# an executable B14 route until #1397 approves a replacement.
HIGH_B14_MODEL_ID = MAX_HOLD_MODEL_ID

PADIEM_PLUS = "Padiem Plus"
PADIEM_PRO = "Padiem Pro"
PADIEM_MAX = "Padiem Max"

# Compatibility alias retained for the Kilo free test lane.
KILO_B14_MODEL_ID = MEDIUM_B14_MODEL_ID

# Historical sentinel retained for older adapters/tests that import it. It is
# not part of the active product-tier mapping.
UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"

PROFILE_MODEL_IDS: dict[str, str] = {
    "low": LOW_B14_MODEL_ID,
    "medium": MEDIUM_B14_MODEL_ID,
    "high": HIGH_B14_MODEL_ID,
}

# Product identity and route executability are separate on purpose. A Padiem
# tier may remain user-visible while its backing route is temporarily HOLD.
PRODUCT_TIER_NAMES: dict[str, str] = {
    LOW_B14_MODEL_ID: PADIEM_PLUS,
    MEDIUM_B14_MODEL_ID: PADIEM_PRO,
    HIGH_B14_MODEL_ID: PADIEM_MAX,
}
EXECUTABLE_B14_MODEL_IDS = frozenset({LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID})

# Current source posture after owner remap #2571. Route identities remain
# derived from the shared control-plane contract:
#
#   Padiem Plus -> direct SenseNova 6.8 Flash Lite
#   Padiem Pro  -> B.AI Qwen3.8 Flash
#   Padiem Max  -> HOLD
#
# The historical Kilo lanes are not product fallbacks. `b14/auto` and
# provider-side auto/fallback behavior remain disabled for product routing.
DEFAULT_B14_MODEL_ID = PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]

# Slash selectors are hidden/operator test controls. Normal UI can later expose
# the product tier names without exposing provider/model identities. `/max`
# resolves to the Max product identity but fails closed before B14 while HOLD.
MODEL_ALIASES: dict[str, str] = {
    "/plus": LOW_B14_MODEL_ID,
    "/pro": MEDIUM_B14_MODEL_ID,
    "/max": HIGH_B14_MODEL_ID,
    # Temporary compatibility selectors from the earlier test lane.
    "/kilo": MEDIUM_B14_MODEL_ID,
    "/poolside": LOW_B14_MODEL_ID,
}

# Product capability claims remain conservative. Free/promotional status is not
# encoded as a durable B62 capability because upstream zero-cost availability
# can change independently of the Padiem product tier. HOLD has no executable
# capabilities.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    LOW_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    MEDIUM_B14_MODEL_ID: frozenset({"chat", "long_context"}),
    HIGH_B14_MODEL_ID: frozenset(),
    AUTO_B14_MODEL_ID: frozenset(),
    UNASSIGNED_B14_MODEL_ID: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ResolvedModelPolicy:
    model_id: str
    messages: list[dict[str, str]]
    alias: str | None = None
    profile: str = DEFAULT_CHAT_PROFILE


class ModelPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _latest_user_index(messages: list[dict[str, str]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def product_tier_name(model_id: str) -> str:
    """Return the user-facing Padiem tier for a known product-tier identity."""
    try:
        return PRODUCT_TIER_NAMES[model_id]
    except KeyError as exc:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.") from exc


def resolve_tier_policy(
    messages: list[dict[str, str]],
    tier_id: str,
    *,
    require_executable: bool = True,
) -> ResolvedModelPolicy:
    """Resolve a browser-facing Plus/Pro/Max tier through the shared contract.

    Browser callers send only the bounded tier id. Provider/model authority
    remains server-side in the shared product-tier declaration.
    """

    if not isinstance(tier_id, str):
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    normalized = tier_id.strip().lower()
    label = TIER_ID_TO_LABEL.get(normalized)
    if label is None:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")

    try:
        route = active_route_for(label)
    except ProductTierRoutesError as exc:
        raise ModelPolicyError(
            "invalid_product_tier",
            "AI 등급 설정을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    if route is None or not route.model_id:
        if require_executable:
            raise ModelPolicyError(
                "tier_unavailable",
                "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.",
            )
        model_id = MAX_HOLD_MODEL_ID if label is ProductTierLabel.MAX else ""
    else:
        model_id = route.model_id

    return ResolvedModelPolicy(
        model_id=model_id,
        messages=[dict(message) for message in messages],
        profile=TIER_ID_TO_PROFILE[normalized],
    )


def resolve_request_model_policy(
    messages: list[dict[str, str]],
    *,
    require_executable: bool = True,
) -> ResolvedModelPolicy:
    """Resolve the request-scoped browser tier, then fall back to legacy policy."""

    tier_id = _REQUEST_TIER_ID.get()
    if tier_id is not None:
        return resolve_tier_policy(
            messages,
            tier_id,
            require_executable=require_executable,
        )
    return resolve_model_policy(messages, require_executable=require_executable)


@contextmanager
def request_tier_context(tier_id: str | None):
    """Temporarily bind a validated browser tier for this async request task."""

    if tier_id is None:
        yield
        return
    if not isinstance(tier_id, str):
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    normalized = tier_id.strip().lower()
    if normalized not in TIER_ID_TO_LABEL:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    token = _REQUEST_TIER_ID.set(normalized)
    try:
        yield
    finally:
        _REQUEST_TIER_ID.reset(token)


def resolve_model_policy(
    messages: list[dict[str, str]],
    *,
    require_executable: bool = True,
) -> ResolvedModelPolicy:
    """Resolve ordinary B62 chat to a Padiem product tier.

    Ordinary chat defaults to executable Padiem Pro. Hidden ``/plus``, ``/pro``
    and ``/max`` selectors are owner/test controls. Callers that only need to
    recognize product identity may set ``require_executable=False``; every path
    that can reach B14 execution must retain the default fail-closed gate.
    """
    out = [dict(message) for message in messages]
    user_index = _latest_user_index(out)
    if user_index is None:
        return ResolvedModelPolicy(DEFAULT_B14_MODEL_ID, out)

    content = out[user_index].get("content", "")
    stripped = content.lstrip()
    if not stripped.startswith("/"):
        return ResolvedModelPolicy(DEFAULT_B14_MODEL_ID, out)

    token, separator, remainder = stripped.partition(" ")
    alias = token.lower()
    model_id = MODEL_ALIASES.get(alias)
    if model_id is None:
        raise ModelPolicyError(
            "unknown_model_alias",
            "현재 지원하지 않는 AI 등급입니다. 질문만 입력하거나 지원되는 등급을 선택해 주세요.",
        )
    if not separator or not remainder.strip():
        raise ModelPolicyError(
            "model_alias_requires_prompt",
            "AI 등급 선택 뒤에 질문을 입력해 주세요.",
        )
    if require_executable and not model_policy_is_executable(model_id):
        raise ModelPolicyError(
            "tier_unavailable",
            "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.",
        )

    out[user_index]["content"] = remainder.strip()
    profile = next(
        (profile_id for profile_id, candidate in PROFILE_MODEL_IDS.items() if candidate == model_id),
        DEFAULT_CHAT_PROFILE,
    )
    return ResolvedModelPolicy(model_id, out, alias=alias, profile=profile)


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether the identifier belongs to a known Padiem product tier."""
    return model_id in PRODUCT_TIER_NAMES


def model_policy_is_executable(model_id: str) -> bool:
    """Return whether B62 may dispatch this exact product-tier route to B14."""
    return model_id in EXECUTABLE_B14_MODEL_IDS
