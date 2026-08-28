from __future__ import annotations

from dataclasses import dataclass


DEFAULT_B14_MODEL_ID = "poolside/laguna-s-2.1"

# B62 owns a deliberately tiny consumer allowlist. Do not derive this from the
# broader B14 catalog: adding another model is an explicit product-owner action.
# Agnes is intentionally absent while its active rollout is suspended.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": DEFAULT_B14_MODEL_ID,
}

MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    DEFAULT_B14_MODEL_ID: frozenset({"chat", "coding", "long_context"}),
}


@dataclass(frozen=True, slots=True)
class ResolvedModelPolicy:
    model_id: str
    messages: list[dict[str, str]]
    alias: str | None = None


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
    """Resolve B62's exact B14 model without consulting B14 auto/catalog APIs.

    Ordinary chat uses the configured B62 default. A leading slash token is
    treated as an explicit B62 model alias. Unknown aliases fail closed before
    any B14/provider call rather than falling through to the broader B14 catalog.
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
            "지원하지 않는 모델 선택입니다. 현재는 기본 모델 또는 /poolside를 사용해 주세요.",
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
