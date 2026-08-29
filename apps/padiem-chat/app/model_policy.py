from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
LOW_B14_MODEL_ID = "poolside/laguna-xs-2.1"
MEDIUM_B14_MODEL_ID = "poolside/laguna-s-2.1"
HIGH_B14_MODEL_ID = "opencode-zen/muse-spark-1.2-contributor-free"
HIGH_CONTRIBUTOR_ACK_VERSION = "contributor-v1"

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

# Historical slash syntax remains a compatibility alias for MEDIUM. LOW/HIGH
# public selection is carried by the guarded request profile, never by a user
# prompt command and never by B14 auto-routing.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": MEDIUM_B14_MODEL_ID,
}

MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    LOW_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    MEDIUM_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
    HIGH_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
}

_REQUEST_PROFILE: ContextVar[str] = ContextVar(
    "padiem_chat_request_profile",
    default=DEFAULT_CHAT_PROFILE,
)


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


def _normalized_profile(profile: str) -> str:
    if not isinstance(profile, str):
        raise ModelPolicyError("invalid_profile", "AI 품질 설정 형식이 올바르지 않습니다.")
    normalized = profile.strip().lower()
    if normalized not in PROFILE_MODEL_IDS:
        raise ModelPolicyError("unknown_profile", "지원하지 않는 AI 품질 설정입니다.")
    return normalized


def model_id_for_profile(profile: str) -> str:
    """Return the exact B14 model assigned to a Padiem product profile."""
    return PROFILE_MODEL_IDS[_normalized_profile(profile)]


def profile_requires_contributor_warning(profile: str) -> bool:
    """HIGH currently uses a Contributor route whose data policy needs warning."""
    return isinstance(profile, str) and profile.strip().lower() == "high"


def validate_public_profile_selection(profile: str | None, acknowledgement: str | None) -> str:
    """Validate browser-owned profile assertion before any B14/Core dispatch."""
    normalized = DEFAULT_CHAT_PROFILE if profile is None else _normalized_profile(profile)
    if normalized == "high":
        if acknowledgement is None:
            raise ModelPolicyError(
                "high_contributor_ack_required",
                "HIGH를 사용하려면 Contributor 데이터 처리 안내를 확인하고 동의해 주세요.",
            )
        if acknowledgement != HIGH_CONTRIBUTOR_ACK_VERSION:
            raise ModelPolicyError(
                "invalid_high_contributor_ack",
                "HIGH 동의 정보를 확인할 수 없습니다. 안내를 다시 확인해 주세요.",
            )
    elif acknowledgement not in (None, ""):
        raise ModelPolicyError(
            "unexpected_high_contributor_ack",
            "HIGH 동의 정보는 HIGH 선택에서만 사용할 수 있습니다.",
        )
    return normalized


def set_request_profile(profile: str) -> Token[str]:
    """Bind one validated product profile to the current async request context."""
    return _REQUEST_PROFILE.set(_normalized_profile(profile))


def reset_request_profile(token: Token[str]) -> None:
    _REQUEST_PROFILE.reset(token)


def current_request_profile() -> str:
    return _REQUEST_PROFILE.get()


def _latest_user_index(messages: list[dict[str, str]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None


def resolve_model_policy(messages: list[dict[str, str]]) -> ResolvedModelPolicy:
    """Resolve B62's request-scoped product profile to an exact manual model.

    Without a guarded profile assertion this remains MEDIUM. LOW and HIGH are
    never selected automatically and B62 never delegates profile choice to
    b14/auto. The historical ``/poolside`` prefix remains MEDIUM-only.
    """
    selected_profile = current_request_profile()
    selected_model = model_id_for_profile(selected_profile)
    out = [dict(message) for message in messages]
    user_index = _latest_user_index(out)
    if user_index is None:
        return ResolvedModelPolicy(selected_model, out, profile=selected_profile)

    content = out[user_index].get("content", "")
    stripped = content.lstrip()
    if not stripped.startswith("/"):
        return ResolvedModelPolicy(selected_model, out, profile=selected_profile)

    token, separator, remainder = stripped.partition(" ")
    alias = token.lower()
    model_id = MODEL_ALIASES.get(alias)
    if model_id is None:
        raise ModelPolicyError(
            "unknown_model_alias",
            "현재 지원하지 않는 모델 명령입니다. AI 품질 선택 메뉴를 사용해 주세요.",
        )
    if selected_profile != DEFAULT_CHAT_PROFILE:
        raise ModelPolicyError(
            "profile_alias_conflict",
            "AI 품질 선택과 모델 명령을 함께 사용할 수 없습니다.",
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
        profile=DEFAULT_CHAT_PROFILE,
    )


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether an exact model belongs to the owner-approved P5 profiles."""
    return model_id in PROFILE_MODEL_IDS.values()
