from __future__ import annotations

from types import MappingProxyType

import pytest

from app.tool_presentations import ToolPresentationDescriptor, get_tool_presentation
from app.tools import TOOL_REGISTRY, ToolSpec, get_tool


def test_b62_registry_is_product_only_immutable_tool_presentation():
    assert isinstance(TOOL_REGISTRY, MappingProxyType)
    assert tuple(TOOL_REGISTRY) == ("web_search", "web_fetch", "deep_research")

    for tool in TOOL_REGISTRY.values():
        assert isinstance(tool, ToolPresentationDescriptor)
        assert not hasattr(tool, "owner")
        assert not hasattr(tool, "side_effect")
        assert not hasattr(tool, "approval_policy")
        assert not hasattr(tool, "auth_scope")
        assert not hasattr(tool, "timeout_seconds")
        assert tool.canonical_tool_id == tool.id
        assert tool.label == tool.title
        assert tool.user_visible is False

    with pytest.raises(TypeError):
        TOOL_REGISTRY["evil"] = get_tool("web_search")  # type: ignore[index]


def test_historical_toolspec_constructor_and_lookup_remain_compatible_without_execution_authority():
    tool = ToolSpec("compat_tool", "호환 도구", "호환 설명", True)

    assert ToolSpec is ToolPresentationDescriptor
    assert isinstance(tool, ToolPresentationDescriptor)
    assert tool.canonical_tool_id == "compat_tool"
    assert tool.id == "compat_tool"
    assert tool.label == "호환 도구"
    assert tool.title == "호환 도구"
    assert tool.description == "호환 설명"
    assert tool.user_visible is True
    assert get_tool_presentation("web_search") is get_tool("web_search")
    with pytest.raises(ValueError, match="지원하지 않는 도구"):
        get_tool("unknown")
