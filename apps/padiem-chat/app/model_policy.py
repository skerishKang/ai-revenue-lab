from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
LOW_B14_MODEL_ID = "poolside/laguna-xs-2.1"
MEDIUM_B14_MODEL_ID = "poolside/laguna-s-2.1"
HIGH_B14_MODEL_ID = "opencode-zen/muse-spark-1.2-contributor-free"

PROFILE_MODEL_IDS: dict[str, str] = {
    "low": LOW_B14_MODEL_ID,
    "medium": MEDIUM_B14_MODEL_ID,
    "high": HIGH_B14_MODEL_ID,
}

# Compatibility name retained for existing B62/Core call sites. The default
# product profile is MEDIUM, which the owner explicitly assigned to Poolside
# Laguna S 2.1 in P5 (#1083). B62 still never delegates profile choice to
# b14/auto.
DEFAULT_B14_MODEL_ID = MEDIUM_B14_MODEL_ID

# Historical slash syntax remains as a compatibility alias for MEDIUM. LOW/HIGH
# are intentionally not exposed as slash commands yet: HIGH requires a visible
# Contributor-data warning/acknowledgement before public selection is enabled.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": MEDIUM_B14_MODEL_ID,
}

MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    LOW_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    MEDIUM_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    HIGH_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
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


def model_id_for_profile(profile: str) -> str:
    """Return the exact B14 model assigned to a Padiem product profile."""
    if not isinstance(profile, str):
        raise ModelPolicyError("invalid_profile", "AI 품질 설정 형식이 올바르지 않습니다.")
    normalized = profile.strip().lower()
    model_id = PROFILE_MODEL_IDS.get(normalized)
    if model_id is None:
        raise ModelPolicyError("unknown_profile", "지원하지 않는 AI 품질 설정입니다.")
    return model_id


def profile_requires_contributor_warning(profile: str) -> bool:
    """HIGH currently uses a Contributor route whose data policy needs warning."""
    return isinstance(profile, str) and profile.strip().lower() == "high"


def _latest_user_index(messages: list[dict[str, str]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def resolve_model_policy(messages: list[dict[str, str]]) -> ResolvedModelPolicy:
    """Resolve B62's current default MEDIUM product profile.

    P5 assigns concrete LOW/MEDIUM/HIGH models, but public LOW/HIGH selection is
    intentionally deferred until the accepted UI lane can present the HIGH
    Contributor warning. Ordinary chat therefore uses MEDIUM. The historical
    ``/poolside`` prefix remains a MEDIUM compatibility alias.
    """
    out = [dict(message) for message in messages]
    user_index = _latest_user_index(out)
    if user_index is None:
        return ResolvedModelPolicy(MEDIUM_B14_MODEL_ID, out)

    content = out[user_index].get("content", "")
    stripped = content.lstrip()
    if not stripped.startswith("/"):
        return ResolvedModelPolicy(MEDIUM_B14_MODEL_ID, out)

    token, separator, remainder = stripped.partition(" ")
    alias = token.lower()
    model_id = MODEL_ALIASES.get(alias)
    if model_id is None:
        raise ModelPolicyError(
            "unknown_model_alias",
            "현재 별도 모델 선택은 지원하지 않습니다. 질문만 입력해 주세요.",
        )
    if not separator or not remainder.strip():
        raise ModelPolicyError(
            "model_alias_requires_prompt",
            "모델 선택 뒤에 질문을 입력해 주세요.",
        )

    out[user_index]["content"] = remainder.strip()
    return ResolvedModelPolicy(
        model_id,
        out,
        alias=alias,
        profile="medium",
    )


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether an exact model belongs to the owner-approved P5 profiles."""
    return model_id in PROFILE_MODEL_IDS.values()
