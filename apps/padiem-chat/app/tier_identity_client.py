from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from .attachments import ImageAttachment
from .b14_client import B14Client, ChatRuntimeError, ChatStreamEvent
from .model_policy import (
    ADMIN_B14_MODEL_ID,
    ModelPolicyError,
    current_request_tier_id,
    model_policy_is_request_executable,
    product_tier_name,
    resolve_request_model_policy,
)
from .task_modes import TaskMode, get_task_mode, task_mode_public_metadata

# Product identity is handled deterministically at the Padiem boundary instead
# of adding a hidden system message to every ordinary user prompt. This keeps
# normal conversation content untouched while preventing provider/model names
# from being exposed when a user directly asks what AI/model is serving them.
_SELF_IDENTITY_PATTERNS = (
    re.compile(r"(?:너|넌|당신|너는|당신은).{0,16}(?:무슨|어떤|뭔|뭐).{0,8}(?:모델|ai|인공지능)", re.IGNORECASE),
    re.compile(r"(?:무슨|어떤|뭔).{0,8}(?:모델|ai|인공지능).{0,12}(?:이야|인가|입니까|예요|세요|쓰고|사용)", re.IGNORECASE),
    re.compile(r"(?:기반|파운데이션|foundation|underlying).{0,10}(?:모델|model)", re.IGNORECASE),
    re.compile(r"(?:provider|프로바이더|제공자).{0,12}(?:뭐|무엇|어디|which|what)", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:ai|model)\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+model\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+model\s+(?:is\s+this|are\s+you\s+using)\b", re.IGNORECASE),
)

_UNDERLYING_DETAIL_MARKERS = (
    "기반 모델",
    "파운데이션",
    "foundation model",
    "underlying model",
    "provider",
    "프로바이더",
    "제공자",
    "실제 모델",
    "원래 모델",
)

_TIER_UNAVAILABLE_MESSAGE = "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요."


def _verified_admin_exact_dispatch(policy_model_id: str) -> bool:
    """Allow the one verified administrator-only Chat dispatch.

    The Chat route proves the global model admin before binding this tier, so
    the executability gate below must not reject the pinned admin model. Every
    other model keeps the product-tier executability rule unchanged.
    """
    return (
        policy_model_id == ADMIN_B14_MODEL_ID
        and current_request_tier_id() == "admin"
    )


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


# #5009: one upstream model may back several grades (Muse Spark backs
# Plus/Pro/Max), so a model id alone can no longer name the product tier.
# The request profile bound by resolve_tier_policy carries the grade.
_PROFILE_TIER_NAMES = {
    "free": "Padiem Free",
    "low": "Padiem Plus",
    "medium": "Padiem Pro",
    "high": "Padiem Max",
}


def tier_identity_answer(
    messages: list[dict[str, str]], model_id: str, profile: str = "free"
) -> str | None:
    """Return a local product-identity answer without asserting route availability."""
    text = _latest_user_text(messages).strip()
    if not text or not any(pattern.search(text) for pattern in _SELF_IDENTITY_PATTERNS):
        return None
    tier = None
    if profile in _PROFILE_TIER_NAMES:
        tier = _PROFILE_TIER_NAMES.get(profile)
    if tier is None:
        try:
            tier = product_tier_name(model_id)
        except ModelPolicyError:
            return None

    lowered = text.lower()
    if any(marker in lowered for marker in _UNDERLYING_DETAIL_MARKERS):
        return (
            f"저는 {tier}입니다. "
            "Padiem Chat에서는 내부 라우팅에 사용되는 제공자나 기반 모델 정보는 공개하지 않습니다."
        )
    return f"저는 {tier}입니다."


class PadiemTierB14Client(B14Client):
    """B14 client with deterministic Padiem-tier self-identification.

    A held product tier may still answer what product identity it represents,
    but ordinary execution is rejected before the base B14 client. This keeps
    product identity stable while preventing a dead/volatile route from being
    called merely because the tier name still exists.
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: TaskMode | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[ImageAttachment, ...] = (),
    ) -> dict[str, Any]:
        policy = resolve_request_model_policy(messages, require_executable=False)
        answer = None if attachments else tier_identity_answer(policy.messages, policy.model_id, policy.profile)
        if answer is not None:
            resolved_skill = skill or get_task_mode()
            return {
                "answer": answer,
                "request_id": "padiem_tier_identity",
                "runtime": "padiem",
                "route": {"mode": "manual", "model": policy.model_id, "provider": None},
                "skill": task_mode_public_metadata(resolved_skill),
            }
        if (
            self.settings.runtime_mode != "mock"
            and not model_policy_is_request_executable(policy.model_id)
            and not _verified_admin_exact_dispatch(policy.model_id)
        ):
            raise ChatRuntimeError(422, "tier_unavailable", _TIER_UNAVAILABLE_MESSAGE)
        return await super().complete(
            messages,
            skill=skill,
            additional_system_context=additional_system_context,
            attachments=attachments,
        )

    async def stream_text_auto(
        self,
        messages: list[dict[str, str]],
        *,
        skill: TaskMode | None = None,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        policy = resolve_request_model_policy(messages, require_executable=False)
        answer = tier_identity_answer(policy.messages, policy.model_id, policy.profile)
        if answer is not None:
            yield ChatStreamEvent(delta_content=answer)
            yield ChatStreamEvent(done=True)
            return
        if (
            self.settings.runtime_mode != "mock"
            and not model_policy_is_request_executable(policy.model_id)
            and not _verified_admin_exact_dispatch(policy.model_id)
        ):
            raise ChatRuntimeError(422, "tier_unavailable", _TIER_UNAVAILABLE_MESSAGE)

        stream = super().stream_text_auto(
            messages,
            skill=skill,
            additional_system_context=additional_system_context,
        )
        try:
            async for event in stream:
                yield event
        finally:
            try:
                await stream.aclose()
            except Exception:
                pass
