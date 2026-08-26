from __future__ import annotations

from types import MappingProxyType

from padiem_ai_core import (
    ApprovalPolicy,
    ToolSideEffect,
    ToolSpec as CoreToolSpec,
)


class ToolSpec(CoreToolSpec):
    """B62 read-only tool metadata backed by the shared Core ToolSpec contract."""

    __slots__ = ()

    def __init__(
        self,
        id: str,
        title: str,
        description: str,
        user_visible: bool = False,
    ) -> None:
        CoreToolSpec.__init__(
            self,
            id=id,
            title=title,
            description=description,
            owner="padiem-chat",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={},
            output_contract={},
            auth_scope=(),
            timeout_seconds=30.0,
            user_visible=user_visible,
        )


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
    ToolSpec(
        id="deep_research",
        title="심층 리서치",
        description="최대 세 번의 검색과 제한된 페이지 읽기를 거쳐 근거를 종합합니다.",
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
