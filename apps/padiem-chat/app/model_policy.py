from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
AUTO_B14_MODEL_ID = "b14/auto"

# Product tiers are intentionally decoupled from upstream model/provider names.
# LOW/MEDIUM/HIGH remain internal compatibility identifiers only; users see
# Padiem Plus / Padiem Pro / Padiem Max.
LOW_B14_MODEL_ID = "kilo/poolside-laguna-s-2.1-free"
MEDIUM_B14_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
MAX_HOLD_MODEL_ID = "padiem-profile/max-hold"
# Compatibility name retained for consumers that reason in low/medium/high
# profiles. High currently names the Max product tier but is deliberately not
# an executable B14 route until #1397 approves a replacement.
HIGH_B14_MODEL_ID = MAX_HOLD_MODEL_ID

PADIEM_PLUS = "Padiem Plus"
PADIEM_PRO = "Padiem Pro"
PADIEM_MAX = "Padiem Max"

# Compatibility alias retained for the first Kilo/Nemotron test lane.
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

# Current source posture after bounded activation/benchmark evidence:
#
#   Padiem Plus -> Kilo-hosted Poolside Laguna S 2.1 free
#   Padiem Pro  -> Kilo-hosted NVIDIA Nemotron 3 Ultra free (default)
#   Padiem Max  -> HOLD (Hy3 is inactive after HTTP 404; no replacement is
#                  auto-promoted from volatile free availability)
#
# `b14/auto` and provider-side `kilo-auto/free` remain disabled.
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
