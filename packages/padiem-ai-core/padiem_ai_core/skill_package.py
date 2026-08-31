"""Reusable Skill package contract for Padiem AI Core.

This module defines declarative package metadata only. A Skill package may
request capabilities and declare tool/connector allowlists, but it never
grants itself permissions, entitlements, connector scopes, or approvals.
Runtime authorization must intersect package declarations with trusted server
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


_SKILL_ID_RE = re.compile(r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_TOOL_ID_RE = re.compile(r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_CONNECTOR_ID_RE = re.compile(r"^connector:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

MAX_DESCRIPTION_CHARS = 1_000
MAX_INSTRUCTION_CHARS = 12_000
MAX_REQUIRED_CAPABILITIES = 32
MAX_ALLOWED_TOOLS = 64
MAX_CONNECTOR_REQUIREMENTS = 32
MAX_APPROVAL_HOOKS = 16


class SkillPackageError(ValueError):
    """Raised when a reusable Skill package violates the frozen contract."""


class ApprovalHook(str, Enum):
    BEFORE_EXTERNAL_SIDE_EFFECT = "before_external_side_effect"
    BEFORE_HIGH_RISK_TOOL = "before_high_risk_tool"
    BEFORE_CONNECTOR_WRITE = "before_connector_write"
    BEFORE_LONG_RUNNING_AGENT = "before_long_running_agent"


def _require_non_empty_text(name: str, value: str, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise SkillPackageError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SkillPackageError(f"{name} is required")
    if len(normalized) > max_chars:
        raise SkillPackageError(f"{name} exceeds {max_chars} characters")
    return normalized


def _require_safe_ref(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise SkillPackageError(f"{name} must be a bounded safe reference")
    return value


def _unique_tuple(name: str, values: tuple[str, ...], *, maximum: int) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise SkillPackageError(f"{name} must be a tuple")
    if len(values) > maximum:
        raise SkillPackageError(f"{name} exceeds maximum size {maximum}")
    if len(values) != len(set(values)):
        raise SkillPackageError(f"{name} contains duplicates")
    return values


@dataclass(frozen=True, slots=True)
class SkillExecutionBudget:
    max_steps: int = 8
    max_tool_calls: int = 8
    max_wall_seconds: int = 120

    def __post_init__(self) -> None:
        limits = {
            "max_steps": (self.max_steps, 1, 64),
            "max_tool_calls": (self.max_tool_calls, 0, 128),
            "max_wall_seconds": (self.max_wall_seconds, 1, 3_600),
        }
        for name, (value, minimum, maximum) in limits.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise SkillPackageError(f"{name} must be an integer")
            if value < minimum or value > maximum:
                raise SkillPackageError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class ReusableSkillPackage:
    """Declarative, versioned reusable Skill package.

    The package is intentionally unable to assert that requested tools,
    connectors, entitlements, or approvals are actually granted. Consumers
    must intersect these declarations with trusted authorization state.
    """

    skill_id: str
    publisher_id: str
    description: str
    instruction: str
    input_contract_ref: str
    output_contract_ref: str
    required_capabilities: tuple[str, ...] = ()
    allowed_tool_ids: tuple[str, ...] = ()
    connector_requirement_ids: tuple[str, ...] = ()
    context_policy_ref: str = "context:default"
    model_policy_ref: str = "model:auto"
    execution_budget: SkillExecutionBudget = SkillExecutionBudget()
    approval_hooks: tuple[ApprovalHook, ...] = ()
    entitlement_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.skill_id, str) or not _SKILL_ID_RE.fullmatch(self.skill_id):
            raise SkillPackageError("skill_id must match skill:<owner>:<id>@<major>")
        object.__setattr__(
            self,
            "publisher_id",
            _require_safe_ref("publisher_id", self.publisher_id),
        )
        object.__setattr__(
            self,
            "description",
            _require_non_empty_text(
                "description",
                self.description,
                max_chars=MAX_DESCRIPTION_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "instruction",
            _require_non_empty_text(
                "instruction",
                self.instruction,
                max_chars=MAX_INSTRUCTION_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "input_contract_ref",
            _require_safe_ref("input_contract_ref", self.input_contract_ref),
        )
        object.__setattr__(
            self,
            "output_contract_ref",
            _require_safe_ref("output_contract_ref", self.output_contract_ref),
        )
        object.__setattr__(
            self,
            "context_policy_ref",
            _require_safe_ref("context_policy_ref", self.context_policy_ref),
        )
        object.__setattr__(
            self,
            "model_policy_ref",
            _require_safe_ref("model_policy_ref", self.model_policy_ref),
        )

        capabilities = _unique_tuple(
            "required_capabilities",
            self.required_capabilities,
            maximum=MAX_REQUIRED_CAPABILITIES,
        )
        if any(not _CAPABILITY_RE.fullmatch(value) for value in capabilities):
            raise SkillPackageError("required_capabilities contains invalid capability id")

        tools = _unique_tuple(
            "allowed_tool_ids",
            self.allowed_tool_ids,
            maximum=MAX_ALLOWED_TOOLS,
        )
        if any(not _TOOL_ID_RE.fullmatch(value) for value in tools):
            raise SkillPackageError("allowed_tool_ids contains invalid tool id")

        connectors = _unique_tuple(
            "connector_requirement_ids",
            self.connector_requirement_ids,
            maximum=MAX_CONNECTOR_REQUIREMENTS,
        )
        if any(not _CONNECTOR_ID_RE.fullmatch(value) for value in connectors):
            raise SkillPackageError("connector_requirement_ids contains invalid connector id")

        if not isinstance(self.execution_budget, SkillExecutionBudget):
            raise SkillPackageError("execution_budget must be SkillExecutionBudget")

        if not isinstance(self.approval_hooks, tuple):
            raise SkillPackageError("approval_hooks must be a tuple")
        if len(self.approval_hooks) > MAX_APPROVAL_HOOKS:
            raise SkillPackageError("approval_hooks exceeds maximum size")
        if len(self.approval_hooks) != len(set(self.approval_hooks)):
            raise SkillPackageError("approval_hooks contains duplicates")
        if any(not isinstance(value, ApprovalHook) for value in self.approval_hooks):
            raise SkillPackageError("approval_hooks contains invalid hook")

        if self.entitlement_ref is not None:
            object.__setattr__(
                self,
                "entitlement_ref",
                _require_safe_ref("entitlement_ref", self.entitlement_ref),
            )


def effective_allowed_tool_ids(
    package: ReusableSkillPackage,
    trusted_granted_tool_ids: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Intersect package allowlist with trusted server grants.

    A package can narrow permissions but can never widen them.
    """

    return tuple(
        tool_id for tool_id in package.allowed_tool_ids if tool_id in trusted_granted_tool_ids
    )


def effective_connector_ids(
    package: ReusableSkillPackage,
    trusted_connected_connector_ids: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Intersect connector requirements with trusted connected accounts."""

    return tuple(
        connector_id
        for connector_id in package.connector_requirement_ids
        if connector_id in trusted_connected_connector_ids
    )


def missing_required_capabilities(
    package: ReusableSkillPackage,
    trusted_capabilities: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Return package requirements absent from trusted capability state."""

    return tuple(
        capability
        for capability in package.required_capabilities
        if capability not in trusted_capabilities
    )
