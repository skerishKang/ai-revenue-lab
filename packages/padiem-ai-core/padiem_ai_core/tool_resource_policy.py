"""Server-owned narrowing resource policy for P01 Tool execution.

This module never executes a handler and never replaces ToolRuntime. It resolves
the effective resources of a tool: the ToolSpec timeout, plus any narrowing the
trusted server policy declares for that one tool. A policy can only make an
invocation smaller or shorter; it cannot widen ToolSpec authority, and it
carries no platform-wide size total (#4379).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .contracts import ToolSpec

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
    """Trusted server narrowing that can only make an invocation smaller.

    #4379: the policy carries no PADIEM aggregate ceiling. ``None`` means the
    tool keeps the whole size the caller asks for. An explicit integer narrows
    that one tool, which is a caller choice and not a platform-wide total.
    """

    max_argument_bytes: int | None = None
    max_output_bytes: int | None = None
    max_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_argument_bytes", self.max_argument_bytes),
            ("max_output_bytes", self.max_output_bytes),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolResourcePolicyError(
                    "invalid_tool_resource_policy",
                    f"{name} must be a positive integer",
                )
        if self.max_timeout_seconds is not None and (
            isinstance(self.max_timeout_seconds, bool)
            or not isinstance(self.max_timeout_seconds, (int, float))
            or not 0 < self.max_timeout_seconds
        ):
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "max_timeout_seconds must be a positive number or None")


@dataclass(frozen=True, slots=True)
class EffectiveToolResources:
    tool_id: str
    argument_bytes: int | None
    output_bytes: int | None
    timeout_seconds: float | None
    narrowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not _IDENTIFIER_RE.fullmatch(self.tool_id):
            raise ToolResourcePolicyError("invalid_tool_resource_policy", "tool_id must be a bounded safe identifier")
        for name, value in (
            ("argument_bytes", self.argument_bytes),
            ("output_bytes", self.output_bytes),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolResourcePolicyError(
                    "invalid_tool_resource_policy", f"{name} must be positive"
                )
        if self.timeout_seconds is not None and (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
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
    """Resolve the effective resources of one Tool.

    #4379: the result carries no PADIEM aggregate byte ceiling. The trusted
    policy may still narrow one tool. The default introduces no fixed turn
    deadline; None in both the spec and policy remains None.
    """
    if not isinstance(spec, ToolSpec):
        raise ToolResourcePolicyError("invalid_tool_resource_spec", "spec must be ToolSpec")
    active = policy or ToolResourcePolicy()

    argument_bytes = active.max_argument_bytes
    output_bytes = active.max_output_bytes
    spec_timeout = None if spec.timeout_seconds is None else float(spec.timeout_seconds)
    policy_timeout = active.max_timeout_seconds
    declared = [value for value in (spec_timeout, policy_timeout) if value is not None]
    timeout_seconds = min(declared) if declared else None

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ToolResourcePolicyError("invalid_effective_resources", "effective Tool resources are invalid")

    return EffectiveToolResources(
        tool_id=spec.id,
        argument_bytes=argument_bytes,
        output_bytes=output_bytes,
        timeout_seconds=timeout_seconds,
        narrowed=(
            argument_bytes is not None
            or output_bytes is not None
            or (
                timeout_seconds is not None
                and (spec_timeout is None or timeout_seconds < spec_timeout)
            )
        ),
    )
