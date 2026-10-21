from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from padiem_control_plane.product_tier_routes import (
    RETIRED_PRODUCT_MODEL_IDS,
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
    FREE_PRIMARY_B14_MODEL_ID,
    FREE_FALLBACK_B14_MODEL_ID,
)
from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID as _CONTRACT_MAX_HOLD_MODEL_ID,
    PLUS_HOLD_MODEL_ID as _CONTRACT_PLUS_HOLD_MODEL_ID,
    PRO_HOLD_MODEL_ID as _CONTRACT_PRO_HOLD_MODEL_ID,
)

# #2099 STEP-2: the Plus/Pro/Max route IDs are no longer literals owned here.
# They are derived from the neutral shared declaration contract
# (padiem_control_plane.product_tier_routes), which Chat and — from #2100 —
# Claw consume as their single product-side source of truth. Business 14's
# catalog remains the final execution authority: a contract route that B14
# unregisters fails closed at dispatch time.

def _contract_route_or_hold_id(
    label: ProductTierLabel,
    hold_model_id: str,
) -> str:
    try:
        route = active_route_for(label)
    except ProductTierRoutesError as exc:  # fail closed before any dispatch
        raise RuntimeError(f"product tier route contract is invalid: {exc}") from exc
    if route is None or not route.model_id:
        return hold_model_id
    return route.model_id


def _contract_executable_ids() -> frozenset[str]:
    model_ids: set[str] = set()
    for label in ProductTierLabel:
        try:
            route = active_route_for(label)
        except ProductTierRoutesError as exc:
            raise RuntimeError(f"product tier route contract is invalid: {exc}") from exc
        if route is not None and route.model_id:
            model_ids.add(route.model_id)
    return frozenset(model_ids)


DEFAULT_CHAT_PROFILE = "free"
# The Free, Plus, Pro and Max primary model is declared per tier in the
# shared Control Plane. A shared upstream model ID does not grant a higher
# membership tier; the request's verified tier remains authoritative.
FREE_B14_MODEL_ID = FREE_PRIMARY_B14_MODEL_ID
PADIEM_FREE = "Padiem Free"
AUTO_B14_MODEL_ID = "b14/auto"
# Administrator-only exact model, provisioned by the verified global model
# admin gate in member_grade_access/chat_routes — never part of the Free..
# Max product-tier routes, aliases, or the shared declaration.
ADMIN_B14_MODEL_ID = "opencode-go/muse-spark-1.3-contributor"

TIER_ID_TO_LABEL: dict[str, ProductTierLabel] = {
    "plus": ProductTierLabel.PLUS,
    "pro": ProductTierLabel.PRO,
    "max": ProductTierLabel.MAX,
}

# #5223: the administrator lane is NOT a member grade. It is the separately
# authorized exact model above, granted by the operator admin authority, and it
# never appears in the Free..Max product-tier routes.
ADMIN_TIER_ID = "admin"

# #5223: the browser-supplied grade -> the product transport profile. ONE map
# for every Claw lane. #5229 showed that a lane carrying its own copy of this
# map refused a valid administrator with ``422 invalid_tier``, so the map lives
# with the grade vocabulary and the lanes resolve it through
# ``resolve_claw_execution_grade``.
TIER_TRANSPORT_LABEL_BY_ID: dict[str, ProductTierLabel] = {
    "free": ProductTierLabel.FREE,
    "plus": ProductTierLabel.PLUS,
    "pro": ProductTierLabel.PRO,
    "max": ProductTierLabel.MAX,
}


@dataclass(frozen=True)
class ClawExecutionGrade:
    """The resolved grade of one Claw execution request.

    ``admin_lane`` marks the separately authorized administrator lane. Its
    authority is the operator admin store, never the browser-supplied grade.
    ``product_tier`` is the transport profile the P01 wire carries; it is not
    an entitlement and never widens a membership.
    """

    tier_id: str
    admin_lane: bool
    product_tier: ProductTierLabel


def resolve_claw_execution_grade(raw_tier: Any) -> ClawExecutionGrade | None:
    """Resolve a browser-supplied grade for a Claw execution lane.

    Returns ``None`` for a grade that does not exist, so the caller refuses it
    with the one existing ``422 invalid_tier`` contract. Every Claw lane
    resolves the grade here, so the lanes cannot drift apart again.
    """

    if not isinstance(raw_tier, str):
        return None
    tier_id = raw_tier.strip().lower()
    if tier_id == ADMIN_TIER_ID:
        # P01 transports only member-tier enums. The administrator lane uses
        # the existing PLUS transport profile and the exact administrator
        # model, exactly like the composer lane.
        return ClawExecutionGrade(tier_id, True, ProductTierLabel.PLUS)
    product_tier = TIER_TRANSPORT_LABEL_BY_ID.get(tier_id)
    if product_tier is None:
        return None
    return ClawExecutionGrade(tier_id, False, product_tier)
TIER_ID_TO_PROFILE: dict[str, str] = {
    "free": "free",
    "plus": "low",
    "pro": "medium",
    "max": "high",
}

_REQUEST_TIER_ID: ContextVar[str | None] = ContextVar(
    "padiem_request_tier_id",
    default=None,
)
# #4428: an exact model resolved from the central per-tier route for THIS
# request task. It replaces only the static primary of the matching grade and
# is never used to grant a higher membership tier.
_REQUEST_ROUTE_MODEL: ContextVar[str | None] = ContextVar(
    "padiem_request_route_model",
    default=None,
)


def _request_route_override(tier_id: str) -> str | None:
    model_id = _REQUEST_ROUTE_MODEL.get()
    if _REQUEST_TIER_ID.get() != tier_id:
        return None
    return model_id if isinstance(model_id, str) and model_id else None


def current_request_tier_id() -> str | None:
    """Return the normalized request-scoped tier bound for this async task."""
    tier = _REQUEST_TIER_ID.get()
    if not isinstance(tier, str) or not tier:
        return None
    return tier


def current_request_route_model() -> str | None:
    """Return the exact model the central per-tier route bound to this task.

    #4428/#5108: the value is set only by the server-side central route
    resolution for the SAME validated grade. The stored route was validated
    against the live B14 catalog (registered + live-ready) when the
    administrator applied it, so it never widens the model set beyond an
    owner-allowed, live-ready model, and it never grants a higher tier.
    """
    tier = _REQUEST_TIER_ID.get()
    if not isinstance(tier, str) or not tier:
        return None
    model_id = _REQUEST_ROUTE_MODEL.get()
    return model_id if isinstance(model_id, str) and model_id else None

# Product tiers are intentionally decoupled from upstream model/provider names.
# LOW/MEDIUM/HIGH remain internal compatibility identifiers only; users see
# Padiem Plus / Padiem Pro / Padiem Max.
LOW_B14_MODEL_ID = _contract_route_or_hold_id(
    ProductTierLabel.PLUS,
    _CONTRACT_PLUS_HOLD_MODEL_ID,
)
MEDIUM_B14_MODEL_ID = _contract_route_or_hold_id(ProductTierLabel.PRO, _CONTRACT_PRO_HOLD_MODEL_ID)
MAX_HOLD_MODEL_ID = _contract_route_or_hold_id(ProductTierLabel.MAX, _CONTRACT_MAX_HOLD_MODEL_ID)

# Kilo Gateway free lanes that are no longer offered upstream. Re-checked
# against the public Gateway model list on 2026-09-08: neither
# ``minimax/minimax-m3:free`` nor ``tencent/hy3:free`` is listed anymore, so
# both product routes are retired and must never back an executable tier.
# (#2094: the stale minimax default caused every Pro/default chat failure.
# #2099 STEP-2: the set itself is declared once in the shared contract.)
RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)
# Compatibility name retained for callers using low/medium/high profiles.
# High resolves to Max's current active route, not its historical HOLD ID.
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
    "free": FREE_B14_MODEL_ID,
    "low": LOW_B14_MODEL_ID,
    "medium": MEDIUM_B14_MODEL_ID,
    "high": HIGH_B14_MODEL_ID,
}

# Product identity and route executability are separate. Retained HOLD
# sentinels are historical identities; active grades resolve via their routes.
PRODUCT_TIER_NAMES: dict[str, str] = {
    # Product identity cannot be recovered from a shared upstream model ID.
    FREE_B14_MODEL_ID: PADIEM_FREE,
    _CONTRACT_PLUS_HOLD_MODEL_ID: PADIEM_PLUS,
    _CONTRACT_PRO_HOLD_MODEL_ID: PADIEM_PRO,
    _CONTRACT_MAX_HOLD_MODEL_ID: PADIEM_MAX,
}
# All four grades resolve an active primary in the shared declaration.
# Whether a caller may use a grade is decided by server-validated membership,
# not by this model-ID set or by the upstream provider name.
EXECUTABLE_B14_MODEL_IDS = _contract_executable_ids() | frozenset({FREE_B14_MODEL_ID})

# The default Chat request uses the Free tier. Each grade resolves its primary
# through the shared declaration. B14 may automatically
# try the exact owner-pinned backup for the verified grade on recoverable
# provider failures; arbitrary `b14/auto` selection remains disabled.
# Retired Space Bunny metadata is not an executable fallback.
DEFAULT_B14_MODEL_ID = PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]

# Slash aliases remain compatibility/test inputs. The browser's tier picker
# uses a separately validated server-side tier; an alias cannot grant that
# entitlement. `/max` resolves to Max's active route when authorized.
MODEL_ALIASES: dict[str, str] = {
    "/plus": LOW_B14_MODEL_ID,
    "/pro": MEDIUM_B14_MODEL_ID,
    "/max": HIGH_B14_MODEL_ID,
    # Legacy `/kilo` test alias; it now resolves through the Pro tier route.
    "/kilo": MEDIUM_B14_MODEL_ID,
    # There is deliberately no "/poolside" key. Poolside Laguna is HOLD_AS_DATA_ONLY in the
    # canonical shared declaration, so an alias naming it could only ever dispatch a
    # different provider under a Poolside label. Unknown provider aliases fail closed as
    # unknown_model_alias, and Poolside becomes selectable only when an owner gives it an
    # executable tier route in that declaration — not by inventing a hold identity here.
}

# These entries describe reported model capabilities, not tier entitlement or
# provider availability. A fallback entry does not grant model execution.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    FREE_B14_MODEL_ID: frozenset({"chat", "coding"}),
    FREE_FALLBACK_B14_MODEL_ID: frozenset({"chat", "image"}),
    "google/gemini-3.5-flash-lite": frozenset({"chat", "image"}),
    "opencode-go/muse-spark-1.2-contributor": frozenset({"chat", "coding"}),
    "opencode-go/muse-spark-1.3-contributor": frozenset({"chat", "coding"}),
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


def _strip_hidden_tier_alias(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove an owner/test slash alias from the user message before dispatch.

    The slash selector remains a compatibility/test surface. It never grants
    product identity or dispatch tier by itself when a server-validated browser
    tier is present; this only keeps provider-bound prompt content clean.
    """
    out = [dict(message) for message in messages]
    index = _latest_user_index(out)
    if index is None:
        return out
    content = out[index].get("content", "")
    stripped = content.lstrip() if isinstance(content, str) else ""
    if not stripped.startswith("/"):
        return out
    token, separator, remainder = stripped.partition(" ")
    if token.lower() not in MODEL_ALIASES or not separator or not remainder.strip():
        return out
    out[index]["content"] = remainder.strip()
    return out


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
    if normalized == "free":
        # No paid-member entitlement needed: caller authentication and usage
        # controls are enforced by the actual Chat route before provider dispatch.
        override = _request_route_override("free")
        return ResolvedModelPolicy(
            model_id=override or FREE_B14_MODEL_ID,
            messages=_strip_hidden_tier_alias(messages),
            profile="free",
        )
    if normalized == "admin":
        # Verified global model admins only; entitlement is proven by the
        # Chat route's central admin gate before provider dispatch. The exact
        # administrator model is pinned here and never routed via b14/auto.
        return ResolvedModelPolicy(
            model_id=ADMIN_B14_MODEL_ID,
            messages=_strip_hidden_tier_alias(messages),
            profile="high",
        )
    label = TIER_ID_TO_LABEL.get(normalized)
    if label is None:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")

    override = _request_route_override(normalized)
    if override is not None:
        # Validated against the live B14 catalog when the administrator applied
        # the central route; B14 still rejects an unavailable exact model.
        return ResolvedModelPolicy(
            model_id=override,
            messages=_strip_hidden_tier_alias(messages),
            profile=TIER_ID_TO_PROFILE[normalized],
        )

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
        if label is ProductTierLabel.PLUS:
            model_id = LOW_B14_MODEL_ID
        elif label is ProductTierLabel.PRO:
            model_id = MEDIUM_B14_MODEL_ID
        elif label is ProductTierLabel.MAX:
            model_id = MAX_HOLD_MODEL_ID
        else:  # pragma: no cover - exhaustive enum guard
            model_id = ""
    else:
        model_id = route.model_id

    return ResolvedModelPolicy(
        model_id=model_id,
        messages=_strip_hidden_tier_alias(messages),
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
def request_tier_context(tier_id: str | None, *, model_id: str | None = None):
    """Temporarily bind a validated browser tier for this async request task.

    ``model_id`` carries an exact central route primary for the same grade. It
    is never accepted from browser input; callers pass only a server-resolved,
    catalog-validated model ID.
    """

    if tier_id is None:
        yield
        return
    if not isinstance(tier_id, str):
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    normalized = tier_id.strip().lower()
    if normalized != "free" and normalized != "admin" and normalized not in TIER_ID_TO_LABEL:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    if model_id is not None and (
        not isinstance(model_id, str) or not model_id or len(model_id) > 256
    ):
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    tier_token = _REQUEST_TIER_ID.set(normalized)
    model_token = _REQUEST_ROUTE_MODEL.set(model_id)
    try:
        yield
    finally:
        _REQUEST_ROUTE_MODEL.reset(model_token)
        _REQUEST_TIER_ID.reset(tier_token)


def resolve_model_policy(
    messages: list[dict[str, str]],
    *,
    require_executable: bool = True,
) -> ResolvedModelPolicy:
    """Resolve ordinary B62 chat to a Padiem product tier.

    Ordinary chat defaults to the Free product tier. Hidden ``/plus``, ``/pro``
    and ``/max`` selectors are compatibility/test controls and cannot grant
    membership. Callers that only need to recognize a tier may set
    ``require_executable=False``; dispatch retains the fail-closed route gate.
    """
    out = [dict(message) for message in messages]
    user_index = _latest_user_index(out)
    if user_index is None:
        if require_executable and not model_policy_is_executable(DEFAULT_B14_MODEL_ID):
            raise ModelPolicyError(
                "tier_unavailable",
                "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.",
            )
        return ResolvedModelPolicy(DEFAULT_B14_MODEL_ID, out)

    content = out[user_index].get("content", "")
    stripped = content.lstrip()
    if not stripped.startswith("/"):
        if require_executable and not model_policy_is_executable(DEFAULT_B14_MODEL_ID):
            raise ModelPolicyError(
                "tier_unavailable",
                "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.",
            )
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
    # Derive the grade from the explicit alias, never by reverse-mapping a
    # shared upstream model ID; one model may serve more than one grade.
    profile = {"/plus": "low", "/pro": "medium", "/max": "high", "/kilo": "medium"}[alias]
    return ResolvedModelPolicy(model_id, out, alias=alias, profile=profile)


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether the identifier belongs to a known Padiem product tier."""
    return model_id in PRODUCT_TIER_NAMES


def model_policy_is_executable(model_id: str) -> bool:
    """Return whether B62 may dispatch this exact product-tier route to B14."""
    return model_id in EXECUTABLE_B14_MODEL_IDS


def model_policy_is_request_executable(model_id: str) -> bool:
    """Return whether B62 may dispatch this exact model for THIS request.

    Two sources are executable:
    * the shared product-tier declaration (``model_policy_is_executable``);
    * the exact model the administrator applied to the bound grade through the
      signed central Preview->Apply route contract. That stored route is
      validated against the live B14 catalog (registered + live-ready) at apply
      time, so honouring it executes an owner-allowed, live-ready model and
      never widens the product's model set.

    #5108: without the second source an applied central route was rejected by
    the Chat pre-dispatch gate with ``model_profile_unassigned``, so the
    administrator's applied decision never reached a real Chat request.
    """
    if model_policy_is_executable(model_id):
        return True
    return current_request_route_model() == model_id
