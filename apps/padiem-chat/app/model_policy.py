from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHAT_PROFILE = "medium"
UNASSIGNED_B14_MODEL_ID = "padiem-profile/medium-unassigned"
MEDIUM_B14_MODEL_ID = "google/gemini-2.5-flash"

# B62 owns the public MEDIUM product profile. P5 selected one exact executable
# B14 model for that profile; provider/model identity remains a server-side
# implementation detail and is not part of the browser contract.
DEFAULT_B14_MODEL_ID = MEDIUM_B14_MODEL_ID

# Historical slash syntax remains parseable only as a compatibility no-op. It
# resolves to the same MEDIUM product profile and therefore never restores
# Poolside, Agnes, or any other historical Provider selection.
MODEL_ALIASES: dict[str, str] = {
    "/poolside": MEDIUM_B14_MODEL_ID,
}

# B62 intentionally claims only the product capability enabled in this slice.
# The B14 catalog may know that the exact model supports more capabilities, but
# those capabilities do not become B62 product features implicitly.
MODEL_CAPABILITIES: dict[str, frozenset[str]] = {
    UNASSIGNED_B14_MODEL_ID: frozenset(),
    MEDIUM_B14_MODEL_ID: frozenset({"chat"}),
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
    """Resolve B62's public MEDIUM profile to its approved exact B14 model.

    The browser still selects only a Padiem product profile. B62 resolves that
    profile server-side to the exact B14 model approved in P5. A legacy
    ``/poolside`` prefix is accepted only as a compatibility no-op and maps to
    the same MEDIUM model; it never restores Poolside routing. Unknown slash
    commands continue to fail closed.
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
    """Return whether B62 has an executable model mapped to its profile."""
    return model_id != UNASSIGNED_B14_MODEL_ID
