from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
AUTO_B14_MODEL_ID = "b14/auto"

# Product tiers are intentionally decoupled from upstream model/provider names.
# LOW/MEDIUM/HIGH remain internal compatibility identifiers only; users see
# Padiem Plus / Padiem Pro / Padiem Max.
LOW_B14_MODEL_ID = "kilo/poolside-laguna-s-2.1-free"
MEDIUM_B14_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
HIGH_B14_MODEL_ID = "kilo/tencent-hy3-free"

PADIEM_PLUS = "Padiem Plus"
PADIEM_PRO = "Padiem Pro"
PADIEM_MAX = "Padiem Max"

# Compatibility alias retained for the first Kilo/Nemotron test lane.
KILO_B14_MODEL_ID = MEDIUM_B14_MODEL_ID

# Historical sentinel retained for older adapters/tests that import it. It is
# not part of the active three-tier mapping.
UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"

PROFILE_MODEL_IDS: dict[str, str] = {
    "low": LOW_B14_MODEL_ID,
    "medium": MEDIUM_B14_MODEL_ID,
    "high": HIGH_B14_MODEL_ID,
}

PRODUCT_TIER_NAMES: dict[str, str] = {
    LOW_B14_MODEL_ID: PADIEM_PLUS,
    MEDIUM_B14_MODEL_ID: PADIEM_PRO,
    HIGH_B14_MODEL_ID: PADIEM_MAX,
}

# Initial free-preview mapping. This is deliberately replaceable: the Padiem
# tier is the product identity; the concrete upstream model may change after
# benchmark/availability review without renaming the tier.
#
#   Padiem Plus -> Kilo-hosted Poolside Laguna S 2.1 free
#   Padiem Pro  -> Kilo-hosted NVIDIA Nemotron 3 Ultra free (default)
#   Padiem Max  -> Kilo-hosted Tencent Hy3 free
#
# `b14/auto` and provider-side `kilo-auto/free` remain disabled.
DEFAULT_B14_MODEL_ID = PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]

# Slash selectors are hidden/operator test controls. Normal UI can later expose
# the product tier names without exposing provider/model identities.
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
# can change independently of the Padiem product tier.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    LOW_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    MEDIUM_B14_MODEL_ID: frozenset({"chat", "long_context"}),
    HIGH_B14_MODEL_ID: frozenset({"chat", "reasoning", "long_context"}),
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
    """Return the user-facing Padiem tier for an approved exact model route."""
    try:
        return PRODUCT_TIER_NAMES[model_id]
    except KeyError as exc:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.") from exc


def resolve_model_policy(messages: list[dict[str, str]]) -> ResolvedModelPolicy:
    """Resolve ordinary B62 chat to one of the three Padiem product tiers.

    Ordinary chat defaults to Padiem Pro. Hidden ``/plus``, ``/pro`` and
    ``/max`` selectors are available for bounded owner testing and are stripped
    from the user message before B14 dispatch. Provider/model identities are not
    part of the browser-facing product contract. Unknown aliases fail closed.
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

    out[user_index]["content"] = remainder.strip()
    profile = next(
        (profile_id for profile_id, candidate in PROFILE_MODEL_IDS.items() if candidate == model_id),
        DEFAULT_CHAT_PROFILE,
    )
    return ResolvedModelPolicy(model_id, out, alias=alias, profile=profile)


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether the model ID is an approved concrete B62 tier mapping."""
    return model_id in PRODUCT_TIER_NAMES


def model_policy_is_executable(model_id: str) -> bool:
    """Return whether B62 may dispatch this exact product-tier route to B14."""
    return model_profile_is_assigned(model_id)
