"""Declarative bounded-Agent contract for Padiem AI Core.

An Agent definition composes already-authorized Core capabilities. It cannot
mint permissions, connector scopes, entitlements, approvals, or child agents.
This v1 contract intentionally forbids sub-agent delegation; bounded runtime
orchestration can be implemented later against trusted server state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


_AGENT_ID_RE = re.compile(r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_SKILL_ID_RE = re.compile(r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_TOOL_ID_RE = re.compile(r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_CONNECTOR_ID_RE = re.compile(r"^connector:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")

MAX_DESCRIPTION_CHARS = 1_000
MAX_INSTRUCTION_CHARS = 12_000
MAX_SKILL_IDS = 32
MAX_TOOL_IDS = 64
MAX_CONNECTOR_IDS = 32
MAX_CAPABILITIES = 32
MAX_APPROVAL_CHECKPOINTS = 16


class AgentDefinitionError(ValueError):
    """Raised when an Agent definition violates a bounded contract."""


class AgentApprovalCheckpoint(str, Enum):
    BEFORE_EXTERNAL_SIDE_EFFECT = "before_external_side_effect"
    BEFORE_HIGH_RISK_TOOL = "before_high_risk_tool"
    BEFORE_CONNECTOR_WRITE = "before_connector_write"
    BEFORE_LONG_RUNNING_CONTINUATION = "before_long_running_continuation"


class AgentTerminalReason(str, Enum):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    MAX_TOOL_CALLS = "max_tool_calls"
    MAX_SKILL_CALLS = "max_skill_calls"
    MAX_WALL_TIME = "max_wall_time"
    APPROVAL_REQUIRED = "approval_required"
    CAPABILITY_MISSING = "capability_missing"
    AUTHORIZATION_DENIED = "authorization_denied"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentExecutionBudget:
    max_steps: int = 12
    max_tool_calls: int = 12
    max_skill_calls: int = 8
    max_wall_seconds: int = 180

    def __post_init__(self) -> None:
        limits = {
            "max_steps": (self.max_steps, 1, 64),
            "max_tool_calls": (self.max_tool_calls, 0, 128),
            "max_skill_calls": (self.max_skill_calls, 0, 64),
            "max_wall_seconds": (self.max_wall_seconds, 1, 3_600),
        }
        for name, (value, minimum, maximum) in limits.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise AgentDefinitionError(f"{name} must be an integer")
            if value < minimum or value > maximum:
                raise AgentDefinitionError(
                    f"{name} must be between {minimum} and {maximum}"
                )


def _bounded_text(name: str, value: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise AgentDefinitionError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise AgentDefinitionError(f"{name} is required")
    if len(normalized) > maximum:
        raise AgentDefinitionError(f"{name} exceeds {maximum} characters")
    return normalized


def _safe_ref(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise AgentDefinitionError(f"{name} must be a bounded safe reference")
    return value


def _validate_unique_ids(
    name: str,
    values: tuple[str, ...],
    *,
    maximum: int,
    pattern: re.Pattern[str],
) -> None:
    if not isinstance(values, tuple):
        raise AgentDefinitionError(f"{name} must be a tuple")
    if len(values) > maximum:
        raise AgentDefinitionError(f"{name} exceeds maximum size {maximum}")
    if len(values) != len(set(values)):
        raise AgentDefinitionError(f"{name} contains duplicates")
    if any(not isinstance(value, str) or not pattern.fullmatch(value) for value in values):
        raise AgentDefinitionError(f"{name} contains an invalid id")


@dataclass(frozen=True, slots=True)
class BoundedAgentDefinition:
    agent_id: str
    publisher_id: str
    description: str
    instruction: str
    skill_package_ids: tuple[str, ...] = ()
    allowed_tool_ids: tuple[str, ...] = ()
    connector_requirement_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    context_policy_ref: str = "context:default"
    model_policy_ref: str = "model:auto"
    execution_budget: AgentExecutionBudget = field(default_factory=AgentExecutionBudget)
    approval_checkpoints: tuple[AgentApprovalCheckpoint, ...] = ()
    entitlement_ref: str | None = None
    allow_subagents: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not _AGENT_ID_RE.fullmatch(self.agent_id):
            raise AgentDefinitionError("agent_id must match agent:<owner>:<id>@<major>")
        object.__setattr__(self, "publisher_id", _safe_ref("publisher_id", self.publisher_id))
        object.__setattr__(
            self,
            "description",
            _bounded_text("description", self.description, maximum=MAX_DESCRIPTION_CHARS),
        )
        object.__setattr__(
            self,
            "instruction",
            _bounded_text("instruction", self.instruction, maximum=MAX_INSTRUCTION_CHARS),
        )

        _validate_unique_ids(
            "skill_package_ids",
            self.skill_package_ids,
            maximum=MAX_SKILL_IDS,
            pattern=_SKILL_ID_RE,
        )
        _validate_unique_ids(
            "allowed_tool_ids",
            self.allowed_tool_ids,
            maximum=MAX_TOOL_IDS,
            pattern=_TOOL_ID_RE,
        )
        _validate_unique_ids(
            "connector_requirement_ids",
            self.connector_requirement_ids,
            maximum=MAX_CONNECTOR_IDS,
            pattern=_CONNECTOR_ID_RE,
        )

        if not isinstance(self.required_capabilities, tuple):
            raise AgentDefinitionError("required_capabilities must be a tuple")
        if len(self.required_capabilities) > MAX_CAPABILITIES:
            raise AgentDefinitionError("required_capabilities exceeds maximum size")
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise AgentDefinitionError("required_capabilities contains duplicates")
        if any(
            not isinstance(value, str) or not _CAPABILITY_RE.fullmatch(value)
            for value in self.required_capabilities
        ):
            raise AgentDefinitionError("required_capabilities contains invalid capability id")

        object.__setattr__(
            self,
            "context_policy_ref",
            _safe_ref("context_policy_ref", self.context_policy_ref),
        )
        object.__setattr__(
            self,
            "model_policy_ref",
            _safe_ref("model_policy_ref", self.model_policy_ref),
        )

        if not isinstance(self.execution_budget, AgentExecutionBudget):
            raise AgentDefinitionError("execution_budget must be AgentExecutionBudget")

        if not isinstance(self.approval_checkpoints, tuple):
            raise AgentDefinitionError("approval_checkpoints must be a tuple")
        if len(self.approval_checkpoints) > MAX_APPROVAL_CHECKPOINTS:
            raise AgentDefinitionError("approval_checkpoints exceeds maximum size")
        if len(self.approval_checkpoints) != len(set(self.approval_checkpoints)):
            raise AgentDefinitionError("approval_checkpoints contains duplicates")
        if any(
            not isinstance(value, AgentApprovalCheckpoint)
            for value in self.approval_checkpoints
        ):
            raise AgentDefinitionError("approval_checkpoints contains invalid checkpoint")

        if self.entitlement_ref is not None:
            object.__setattr__(
                self,
                "entitlement_ref",
                _safe_ref("entitlement_ref", self.entitlement_ref),
            )

        if not isinstance(self.allow_subagents, bool):
            raise AgentDefinitionError("allow_subagents must be boolean")
        if self.allow_subagents:
            raise AgentDefinitionError(
                "sub-agent delegation is not supported by bounded Agent contract v1"
            )


def effective_agent_tool_ids(
    definition: BoundedAgentDefinition,
    trusted_granted_tool_ids: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Agent declarations can narrow trusted tool authority, never widen it."""
    return tuple(
        tool_id
        for tool_id in definition.allowed_tool_ids
        if tool_id in trusted_granted_tool_ids
    )


def effective_agent_connector_ids(
    definition: BoundedAgentDefinition,
    trusted_connected_connector_ids: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Agent connector requirements do not create OAuth/account authority."""
    return tuple(
        connector_id
        for connector_id in definition.connector_requirement_ids
        if connector_id in trusted_connected_connector_ids
    )


def missing_agent_capabilities(
    definition: BoundedAgentDefinition,
    trusted_capabilities: set[str] | frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        capability
        for capability in definition.required_capabilities
        if capability not in trusted_capabilities
    )
