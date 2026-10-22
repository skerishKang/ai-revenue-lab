from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from .attachments import ImageAttachment
from .b14_client import B14Client, ChatRuntimeError, ChatStreamEvent
from .model_policy import (
    ADMIN_B14_MODEL_ID,
    current_request_tier_id,
    current_verified_member_grade,
    model_policy_is_request_executable,
    resolve_request_model_policy,
)
from .task_modes import TaskMode, get_task_mode, task_mode_public_metadata

# Product identity is handled deterministically at the Padiem boundary instead
# of adding a hidden system message to every ordinary user prompt. This keeps
# normal conversation content untouched while preventing provider/model names
# from being exposed when a user directly asks what AI/model is serving them.
_SELF_IDENTITY_PATTERNS = (
    re.compile(r"(?:너|넌|당신|너는|당신은).{0,8}(?:누구|정체)", re.IGNORECASE),
    re.compile(r"(?:너|넌|당신|너는|당신은).{0,16}(?:무슨|어떤|뭔|뭐).{0,8}(?:모델|ai|인공지능)", re.IGNORECASE),
    re.compile(r"(?:무슨|어떤|뭔|어느).{0,8}(?:모델|ai|인공지능).{0,16}(?:이야|야|인가|입니까|예요|세요|쓰니|쓰나|쓰고|씁니까|사용|회사)", re.IGNORECASE),
    re.compile(r"(?:모델|언어모델)\s*(?:뭐|무엇|어떤|알려|말해)", re.IGNORECASE),
    re.compile(r"(?:기반|파운데이션|foundation|underlying).{0,10}(?:모델|model)", re.IGNORECASE),
    re.compile(r"(?:provider|프로바이더|제공자).{0,12}(?:뭐|무엇|어디|which|what)", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:ai|model)\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+model\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+model\s+(?:is\s+this|are\s+you\s+using)\b", re.IGNORECASE),
    re.compile(r"(?:내|나의|제|나는|저는).{0,8}(?:회원)?\s*등급.{0,8}(?:뭐|무엇|어떤|인가|이야|예요)?", re.IGNORECASE),
)


def is_padiem_identity_question(text: str) -> bool:
    """Whether a user turn asks for the assistant's identity or tier."""
    return isinstance(text, str) and any(pattern.search(text.strip()) for pattern in _SELF_IDENTITY_PATTERNS)

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


_TIER_LABELS = {
    "free": "PADIEM Free",
    "plus": "PADIEM Plus",
    "pro": "PADIEM Pro",
    "max": "PADIEM Max",
}


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


def tier_identity_answer(
    messages: list[dict[str, str]], model_id: str, profile: str = "free"
) -> str | None:
    text = _latest_user_text(messages).strip()
    if not is_padiem_identity_question(text):
        return None
    # Request tier is bound only after server-side authorization. It names the
    # selected execution mode, which may differ from the account's membership.
    tier_id = current_request_tier_id()
    tier = _TIER_LABELS.get(tier_id) if tier_id else None
    identity = f"PADIEM Chat의 {tier} 모드" if tier else "PADIEM Chat AI"
    lowered = text.lower()
    if any(marker in lowered for marker in _UNDERLYING_DETAIL_MARKERS):
        return f"저는 {identity}입니다. 기반 모델과 공급자 정보는 안내하지 않습니다."
    if "등급" in text and tier:
        member_grade = current_verified_member_grade()
        verified_label = _TIER_LABELS.get(member_grade) if member_grade else None
        return f"현재 회원 등급은 {verified_label}입니다." if verified_label else "현재 회원 등급을 확인할 수 없습니다."
    return f"저는 {identity}입니다."


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
