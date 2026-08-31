from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChatMode(str, Enum):
    """B62 user-facing execution modes.

    These values are product semantics only. They do not identify a Provider,
    B14 catalog model, route, credential, or paid entitlement.
    """

    AUTO = "auto"
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


DEFAULT_CHAT_MODE = ChatMode.AUTO


@dataclass(frozen=True, slots=True)
class ChatModeDescriptor:
    mode: ChatMode
    label: str
    description: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "id": self.mode.value,
            "label": self.label,
            "description": self.description,
        }


CHAT_MODE_CATALOG: tuple[ChatModeDescriptor, ...] = (
    ChatModeDescriptor(
        mode=ChatMode.AUTO,
        label="자동",
        description="질문에 맞는 처리 방식을 자동으로 선택합니다.",
    ),
    ChatModeDescriptor(
        mode=ChatMode.FAST,
        label="빠르게",
        description="빠른 응답을 우선하는 모드입니다.",
    ),
    ChatModeDescriptor(
        mode=ChatMode.BALANCED,
        label="균형",
        description="속도와 답변 품질의 균형을 우선합니다.",
    ),
    ChatModeDescriptor(
        mode=ChatMode.DEEP,
        label="깊게",
        description="더 깊은 검토가 필요한 작업을 위한 모드입니다.",
    ),
)

_CHAT_MODE_BY_ID = {item.mode.value: item for item in CHAT_MODE_CATALOG}


class ChatModeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(message)


def resolve_chat_mode(value: str | None) -> ChatMode:
    """Resolve a B62 mode without assigning any Provider/model route."""

    if value is None or not value.strip():
        return DEFAULT_CHAT_MODE
    normalized = value.strip().lower()
    try:
        return ChatMode(normalized)
    except ValueError as exc:
        raise ChatModeError(
            "unknown_chat_mode",
            "지원하지 않는 대화 모드입니다.",
        ) from exc


def list_chat_modes() -> list[dict[str, str]]:
    """Return only provider-neutral product metadata safe for the browser."""

    return [item.to_public_dict() for item in CHAT_MODE_CATALOG]


def chat_modes_api_payload() -> dict[str, object]:
    """Build the read-only browser payload without claiming runtime mappings.

    The catalog can describe future B62 product modes before they are executable.
    `accepted_request_mode_ids` is intentionally authoritative for the current
    browser request contract, which still accepts only `auto`.
    """

    return {
        "default_mode": DEFAULT_CHAT_MODE.value,
        "accepted_request_mode_ids": [DEFAULT_CHAT_MODE.value],
        "modes": list_chat_modes(),
    }


def get_chat_mode_descriptor(mode: ChatMode | str) -> ChatModeDescriptor:
    resolved = mode if isinstance(mode, ChatMode) else resolve_chat_mode(mode)
    return _CHAT_MODE_BY_ID[resolved.value]
