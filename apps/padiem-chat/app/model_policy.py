from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
AUTO_B14_MODEL_ID = "b14/auto"
UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"

# B62 Auto is executable because it delegates route choice to the B14 router.
# It is not a concrete Provider/model assignment and must never be interpreted
# as one. Fast/Balanced/Deep remain separately unassigned until accepted mapping.
DEFAULT_B14_MODEL_ID = AUTO_B14_MODEL_ID

# Historical slash syntax remains parseable only as a compatibility no-op. It
# resolves to B14 Auto and therefore does not select Poolside, Agnes, or any
# other concrete Provider/model.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": AUTO_B14_MODEL_ID,
}

# B62 does not claim concrete model capabilities for router-owned Auto or for an
# unassigned product profile. Capability truth remains B14-owned at dispatch.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
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
    """Resolve B62's default Auto policy without selecting a Provider/model.

    Ordinary text chat delegates route choice to B14 by using ``b14/auto``.
    This does not assign a concrete model to B62 and does not expose Provider
    identity in the product contract. A legacy ``/poolside`` prefix remains a
    compatibility no-op: it strips the prefix but still delegates to B14 Auto.
    Unknown slash commands continue to fail closed.
    """
    out = [dict(message) for message in messages]
    user_index = _latest_user_index(out)
    if user_index is None:
        return ResolvedModelPolicy(AUTO_B14_MODEL_ID, out)

    content = out[user_index].get("content", "")
    stripped = content.lstrip()
    if not stripped.startswith("/"):
        return ResolvedModelPolicy(AUTO_B14_MODEL_ID, out)

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
    """Return whether B62 has a concrete executable model mapped to its profile."""
    return model_id not in {AUTO_B14_MODEL_ID, UNASSIGNED_B14_MODEL_ID}


def model_policy_is_executable(model_id: str) -> bool:
    """Return whether the policy has a safe execution path without B62 routing.

    ``b14/auto`` is executable because B14 remains the route authority. An
    unassigned product-profile sentinel is not executable.
    """
    return model_id == AUTO_B14_MODEL_ID or model_profile_is_assigned(model_id)
