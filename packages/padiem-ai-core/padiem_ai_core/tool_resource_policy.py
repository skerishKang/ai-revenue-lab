"""Server-owned narrowing resource policy for P01 Tool execution.

This module never executes a handler and never replaces ToolRuntime. It resolves
an effective resource ceiling that is the intersection of the existing ToolSpec
limits and a trusted server policy. A policy can only make an invocation smaller
or shorter; it cannot widen ToolSpec authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .contracts import ToolSpec
from .tool_runtime import MAX_TOOL_ARGUMENT_BYTES, MAX_TOOL_OUTPUT_BYTES

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ToolResourcePolicyError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("tool resource policy error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class ToolResourcePolicy:
    """Trusted server ceilings that can only narrow a ToolSpec."""

    max_argument_bytes: int = MAX_TOOL_ARGUMENT_BYTES
    max_output_bytes: int = MAX_TOOL_OUTPUT_BYTES
    max_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if isinstance(self.max_argument_bytes, bool) or not isinstance(self.max_argument_bytes, int) or not 1 <= self.max_argument_bytes <= MAX_TOOL_ARGUMENT_BYTES:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "max_argument_bytes is outside the bounded ToolRuntime range")
        if isinstance(self.max_output_bytes, bool) or not isinstance(self.max_output_bytes, int) or not 1 <= self.max_output_bytes <= MAX_TOOL_OUTPUT_BYTES:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "max_output_bytes is outside the bounded ToolRuntime range")
        if isinstance(self.max_timeout_seconds, bool) or not isinstance(self.max_timeout_seconds, (int, float)) or not 0 < self.max_timeout_seconds <= 300:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "max_timeout_seconds is outside the bounded ToolSpec range")


@dataclass(frozen=True, slots=True)
class EffectiveToolResources:
    tool_id: str
    argument_bytes: int
    output_bytes: int
    timeout_seconds: float
    narrowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not _IDENTIFIER_RE.fullmatch(self.tool_id):
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "tool_id must be a bounded safe identifier")
        if isinstance(self.argument_bytes, bool) or not isinstance(self.argument_bytes, int) or self.argument_bytes < 1:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "argument_bytes must be positive")
        if isinstance(self.output_bytes, bool) or not isinstance(self.output_bytes, int) or self.output_bytes < 1:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "output_bytes must be positive")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "timeout_seconds must be positive")
        if not isinstance(self.narrowed, bool):
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "narrowed must be boolean")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "argument_bytes": self.argument_bytes,
            "output_bytes": self.output_bytes,
            "timeout_seconds": self.timeout_seconds,
            "narrowed": self.narrowed,
        }


def resolve_tool_resources(spec: ToolSpec, policy: ToolResourcePolicy | None = None) -> EffectiveToolResources:
    """Intersect a ToolSpec with trusted server resource ceilings."""
    if not isinstance(spec, ToolSpec):
        raise ToolResourcePolicyError("invalid_tool_resource_spec", "spec must be ToolSpec")
    active = policy or ToolResourcePolicy()

    argument_bytes = min(MAX_TOOL_ARGUMENT_BYTES, active.max_argument_bytes)
    output_bytes = min(MAX_TOOL_OUTPUT_BYTES, active.max_output_bytes)
    timeout_seconds = min(float(spec.timeout_seconds), float(active.max_timeout_seconds))

    if argument_bytes < 1 or output_bytes < 1 or timeout_seconds <= 0:
        raise ToolResourcePolicyError("invalid_effective_resources", "effective Tool resources are invalid")

    return EffectiveToolResources(
        tool_id=spec.id,
        argument_bytes=argument_bytes,
        output_bytes=output_bytes,
        timeout_seconds=timeout_seconds,
        narrowed=(
            argument_bytes < MAX_TOOL_ARGUMENT_BYTES
            or output_bytes < MAX_TOOL_OUTPUT_BYTES
            or timeout_seconds < float(spec.timeout_seconds)
        ),
    )
