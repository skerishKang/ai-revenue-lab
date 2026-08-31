from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True, init=False)
class ToolPresentationDescriptor:
    """B62 UI metadata for a canonical Core tool.

    Execution, approval, auth, resource ceilings, and handler registration are
    intentionally absent. The historical ToolSpec name is an alias below.
    """

    canonical_tool_id: str
    label: str
    description: str
    icon: str | None
    visible: bool
    order: int

    def __init__(
        self,
        canonical_tool_id: str | None = None,
        label: str | None = None,
        description: str | None = None,
        user_visible: bool = False,
        *,
        id: str | None = None,
        title: str | None = None,
        icon: str | None = None,
        visible: bool | None = None,
        order: int = 0,
    ) -> None:
        resolved_id = canonical_tool_id if canonical_tool_id is not None else id
        resolved_label = label if label is not None else title
        if not isinstance(resolved_id, str) or not resolved_id.strip():
            raise ValueError("canonical_tool_id must be a non-empty string")
        if not isinstance(resolved_label, str) or not resolved_label.strip():
            raise ValueError("label must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise ValueError("order must be a non-negative integer")
        resolved_visible = user_visible if visible is None else visible
        if not isinstance(resolved_visible, bool):
            raise ValueError("visible must be a boolean")
        object.__setattr__(self, "canonical_tool_id", resolved_id.strip())
        object.__setattr__(self, "label", resolved_label.strip())
        object.__setattr__(self, "description", description.strip())
        object.__setattr__(self, "icon", icon)
        object.__setattr__(self, "visible", resolved_visible)
        object.__setattr__(self, "order", order)

    @property
    def id(self) -> str:
        """Historical identifier accessor; execution authority remains Core."""
        return self.canonical_tool_id

    @property
    def title(self) -> str:
        """Historical label accessor."""
        return self.label

    @property
    def user_visible(self) -> bool:
        """Historical visibility accessor."""
        return self.visible

    def to_public_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "canonical_tool_id": self.canonical_tool_id,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "visible": self.visible,
            "order": self.order,
        }


# Compatibility name retained for B62 callers and persisted request vocabulary.
ToolSpec = ToolPresentationDescriptor

_TOOL_PRESENTATIONS = (
    ToolPresentationDescriptor(
        canonical_tool_id="web_search",
        label="웹 검색",
        description="웹에서 관련 출처를 찾고 구조화된 Evidence로 반환합니다.",
        order=10,
    ),
    ToolPresentationDescriptor(
        canonical_tool_id="web_fetch",
        label="웹 페이지 읽기",
        description="알려진 공개 URL 한 개를 읽고 구조화된 Evidence로 반환합니다.",
        order=20,
    ),
    ToolPresentationDescriptor(
        canonical_tool_id="deep_research",
        label="심층 리서치",
        description="최대 세 번의 검색과 제한된 페이지 읽기를 거쳐 근거를 종합합니다.",
        order=30,
    ),
)

if len({tool.canonical_tool_id for tool in _TOOL_PRESENTATIONS}) != len(_TOOL_PRESENTATIONS):
    raise RuntimeError("duplicate Padiem Chat tool presentation id")

TOOL_PRESENTATION_REGISTRY = MappingProxyType({tool.canonical_tool_id: tool for tool in _TOOL_PRESENTATIONS})
TOOL_REGISTRY = TOOL_PRESENTATION_REGISTRY


def get_tool_presentation(tool_id: str) -> ToolPresentationDescriptor:
    try:
        return TOOL_PRESENTATION_REGISTRY[tool_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 도구입니다.") from exc


def get_tool(tool_id: str) -> ToolPresentationDescriptor:
    """Compatibility lookup for the historical B62 tool API."""
    return get_tool_presentation(tool_id)
