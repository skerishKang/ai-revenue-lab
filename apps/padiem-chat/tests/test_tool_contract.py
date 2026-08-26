from __future__ import annotations

from types import MappingProxyType

import pytest

from padiem_ai_core import ApprovalPolicy, ToolSideEffect, ToolSpec as CoreToolSpec

from app.tools import TOOL_REGISTRY, ToolSpec, get_tool


def test_b62_tool_registry_keeps_exact_ids_and_core_read_only_policy():
    assert isinstance(TOOL_REGISTRY, MappingProxyType)
    assert tuple(TOOL_REGISTRY) == ("web_search", "web_fetch", "deep_research")

    for tool in TOOL_REGISTRY.values():
        assert isinstance(tool, ToolSpec)
        assert isinstance(tool, CoreToolSpec)
        assert tool.owner == "padiem-chat"
        assert tool.side_effect is ToolSideEffect.READ
        assert tool.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert dict(tool.input_schema) == {}
        assert dict(tool.output_contract) == {}
        assert tool.auth_scope == ()
        assert tool.timeout_seconds == 30.0
        assert tool.user_visible is False


def test_b62_toolspec_historical_constructor_and_lookup_behavior_are_preserved():
    tool = ToolSpec("compat_tool", "호환 도구", "호환 설명", True)

    assert isinstance(tool, CoreToolSpec)
    assert tool.id == "compat_tool"
    assert tool.title == "호환 도구"
    assert tool.description == "호환 설명"
    assert tool.user_visible is True
    assert tool.owner == "padiem-chat"
    assert tool.side_effect is ToolSideEffect.READ
    assert tool.approval_policy is ApprovalPolicy.NOT_REQUIRED

    assert get_tool("web_search").title == "웹 검색"
    with pytest.raises(ValueError, match="지원하지 않는 도구"):
        get_tool("unknown")
