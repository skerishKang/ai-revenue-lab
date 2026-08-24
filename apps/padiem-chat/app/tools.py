from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: str
    title: str
    description: str
    user_visible: bool = False


_TOOL_SPECS = (
    ToolSpec(
        id="web_search",
        title="웹 검색",
        description="웹에서 관련 출처를 찾고 구조화된 Evidence로 반환합니다.",
    ),
    ToolSpec(
        id="web_fetch",
        title="웹 페이지 읽기",
        description="알려진 공개 URL 한 개를 읽고 구조화된 Evidence로 반환합니다.",
    ),
)

if len({tool.id for tool in _TOOL_SPECS}) != len(_TOOL_SPECS):
    raise RuntimeError("duplicate Padiem Chat tool id")

TOOL_REGISTRY = MappingProxyType({tool.id: tool for tool in _TOOL_SPECS})


def get_tool(tool_id: str) -> ToolSpec:
    try:
        return TOOL_REGISTRY[tool_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 도구입니다.") from exc
