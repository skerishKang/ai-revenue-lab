from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
AUTO_B14_MODEL_ID = "b14/auto"
LOW_B14_MODEL_ID = "padiem-profile/low-unassigned"
MEDIUM_B14_MODEL_ID = "poolside/laguna-s-2.1"
HIGH_B14_MODEL_ID = "padiem-profile/high-paid-unassigned"

# Compatibility sentinel retained for older tests/adapters that still import it.
# MEDIUM itself is now explicitly assigned to Poolside Laguna S 2.1.
UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"

PROFILE_MODEL_IDS: dict[str, str] = {
    "low": LOW_B14_MODEL_ID,
    "medium": MEDIUM_B14_MODEL_ID,
    "high": HIGH_B14_MODEL_ID,
}

# Owner policy for the current rollout:
#   LOW    -> unassigned
#   MEDIUM -> Poolside Laguna S 2.1 (the only executable B62 profile today)
#   HIGH   -> paid tier, concrete model not assigned yet
# Auto is a product presentation concept; it must not delegate ordinary B62 chat
# to unconstrained B14 Auto while only MEDIUM has an approved model mapping.
DEFAULT_B14_MODEL_ID = PROFILE_MODEL_IDS[DEFAULT_CHAT_PROFILE]

# Historical slash syntax remains supported only for the currently approved
# Poolside route. Other provider/model aliases fail closed before B14 dispatch.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": MEDIUM_B14_MODEL_ID,
}

# B62 claims only the capabilities already accepted for the exact Laguna model.
# Pricing/free status is intentionally not encoded as a durable capability.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    LOW_B14_MODEL_ID: frozenset(),
    MEDIUM_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
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


def resolve_model_policy(messages: list[dict[str, str]]) -> ResolvedModelPolicy:
    """Resolve the current B62 profile to its exact approved B14 model.

    Ordinary text chat currently runs the MEDIUM profile, mapped exactly to
    ``poolside/laguna-s-2.1``. LOW remains unassigned and HIGH remains a paid
    tier without a concrete model. ``b14/auto`` is deliberately not used by the
    current B62 rollout. A legacy ``/poolside`` prefix strips the command and
    resolves to the same exact MEDIUM model. Unknown aliases fail closed.
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
            "현재 별도 모델 선택은 지원하지 않습니다. 질문만 입력해 주세요.",
        )
    if not separator or not remainder.strip():
        raise ModelPolicyError(
            "model_alias_requires_prompt",
            "모델 선택 뒤에 질문을 입력해 주세요.",
        )

    out[user_index]["content"] = remainder.strip()
    return ResolvedModelPolicy(model_id, out, alias=alias)


def model_supports(model_id: str, capability: str) -> bool:
    return capability in MODEL_CAPABILITIES.get(model_id, frozenset())


def model_profile_is_assigned(model_id: str) -> bool:
    """Return whether the model ID is an approved concrete B62 profile mapping."""
    return model_id not in {
        AUTO_B14_MODEL_ID,
        LOW_B14_MODEL_ID,
        HIGH_B14_MODEL_ID,
        UNASSIGNED_B14_MODEL_ID,
    }


def model_policy_is_executable(model_id: str) -> bool:
    """Return whether B62 may dispatch this policy to B14 today.

    The current rollout permits only concrete profile mappings. In particular,
    unconstrained ``b14/auto`` is not an executable B62 policy.
    """
    return model_profile_is_assigned(model_id)
