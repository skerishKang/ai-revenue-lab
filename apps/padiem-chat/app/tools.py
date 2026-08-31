"""Compatibility aliases for the historical B62 ToolSpec API."""

from .tool_presentations import (
    TOOL_PRESENTATION_REGISTRY,
    TOOL_REGISTRY,
    ToolPresentationDescriptor,
    ToolSpec,
    get_tool,
    get_tool_presentation,
)

__all__ = [
    "TOOL_PRESENTATION_REGISTRY",
    "TOOL_REGISTRY",
    "ToolPresentationDescriptor",
    "ToolSpec",
    "get_tool",
    "get_tool_presentation",
]
