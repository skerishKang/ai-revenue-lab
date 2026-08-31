"""Bounded parent-to-child Agent delegation contracts for P01.

Delegation is authority-preserving: a child Agent may inherit or narrow the
parent's tools, capabilities, and execution budgets, but can never widen them.
This module only defines deterministic authorization/identity semantics; actual
execution remains owned by the existing bounded Agent runtime and ToolRuntime.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from .agent_definition import BoundedAgentDefinition
from .agent_profile_adapter import CompiledAgentProfile

MAX_DELEGATION_DEPTH = 4
MAX_CHILDREN_PER_PARENT = 8
MAX_DELEGATION_REASON_CHARS = 1_000
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_ID_RE = re.compile(r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_TOOL_ID_RE = re.compile(r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class AgentDelegationError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_IDENTIFIER_RE.fullmatch(code):
            raise ValueError("delegation error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise AgentDelegationError("invalid_agent_delegation", f"{name} must be a string")
    if value.startswith("agent:") or (("agent" in name) and "@" in value):
        if not _AGENT_ID_RE.fullmatch(value):
            raise AgentDelegationError("invalid_agent_delegation", f"{name} must match canonical Agent id grammar")
        return value
    if value.startswith("tool:"):
        if not _TOOL_ID_RE.fullmatch(value):
            raise AgentDelegationError("invalid_agent_delegation", f"{name} must match canonical Tool id grammar")
        return value
    if not _SAFE_TAG_RE.fullmatch(value):
        raise AgentDelegationError("invalid_agent_delegation", f"{name} must be a bounded safe identifier")
    return value


def _bounded_reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentDelegationError("invalid_agent_delegation", "reason must be a non-empty string")
    result = value.strip()
    if len(result) > MAX_DELEGATION_REASON_CHARS:
        raise AgentDelegationError("delegation_budget_exceeded", "reason exceeds the bounded delegation limit")
    return result


def delegation_fingerprint(
    *,
    parent_agent_id: str,
    child_agent_id: str,
    allowed_tools: tuple[str, ...],
    capabilities: tuple[str, ...],
    max_steps: int,
    max_tool_calls: int,
    max_wall_seconds: int,
) -> str:
    payload = {
        "parent_agent_id": parent_agent_id,
        "child_agent_id": child_agent_id,
        "allowed_tools": list(allowed_tools),
        "capabilities": list(capabilities),
        "max_steps": max_steps,
        "max_tool_calls": max_tool_calls,
        "max_wall_seconds": max_wall_seconds,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AgentDelegationRequest:
    delegation_id: str
    parent_agent_id: str
    child_agent_id: str
    reason: str
    allowed_tools: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    max_steps: int = 1
    max_tool_calls: int = 0
    max_wall_seconds: int = 60
    depth: int = 1

    def __post_init__(self) -> None:
        for name in ("delegation_id", "parent_agent_id", "child_agent_id"):
            object.__setattr__(self, name, _identifier(name, getattr(self, name)))
        object.__setattr__(self, "reason", _bounded_reason(self.reason))
        for name in ("allowed_tools", "capabilities"):
            values = getattr(self, name)
            if isinstance(values, (str, bytes)):
                raise AgentDelegationError("invalid_agent_delegation", f"{name} must be a tuple")
            normalized = tuple(_identifier(f"{name} item", value) for value in values)
            if len(set(normalized)) != len(normalized):
                raise AgentDelegationError("invalid_agent_delegation", f"{name} must not contain duplicates")
            object.__setattr__(self, name, normalized)
        bounds = (
            ("max_steps", self.max_steps, 1, 64),
            ("max_tool_calls", self.max_tool_calls, 0, 64),
            ("max_wall_seconds", self.max_wall_seconds, 1, 3_600),
            ("depth", self.depth, 1, MAX_DELEGATION_DEPTH),
        )
        for name, value, low, high in bounds:
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise AgentDelegationError("delegation_budget_exceeded", f"{name} must be between {low} and {high}")

    @property
    def fingerprint(self) -> str:
        return delegation_fingerprint(
            parent_agent_id=self.parent_agent_id,
            child_agent_id=self.child_agent_id,
            allowed_tools=self.allowed_tools,
            capabilities=self.capabilities,
            max_steps=self.max_steps,
            max_tool_calls=self.max_tool_calls,
            max_wall_seconds=self.max_wall_seconds,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "parent_agent_id": self.parent_agent_id,
            "child_agent_id": self.child_agent_id,
            "reason": self.reason,
            "allowed_tools": list(self.allowed_tools),
            "capabilities": list(self.capabilities),
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_wall_seconds": self.max_wall_seconds,
            "depth": self.depth,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class DelegatedAgentAuthority:
    delegation: AgentDelegationRequest
    authorized_tool_ids: tuple[str, ...]
    authorized_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.delegation, AgentDelegationRequest):
            raise AgentDelegationError("invalid_agent_delegation", "delegation must be AgentDelegationRequest")
        for name in ("authorized_tool_ids", "authorized_capabilities"):
            values = getattr(self, name)
            if isinstance(values, (str, bytes)):
                raise AgentDelegationError("invalid_agent_delegation", f"{name} must be a tuple")
            normalized = tuple(_identifier(f"{name} item", value) for value in values)
            object.__setattr__(self, name, normalized)
            if set(normalized) != set(getattr(self.delegation, "allowed_tools" if name == "authorized_tool_ids" else "capabilities")):
                raise AgentDelegationError("delegation_authority_mismatch", "authorized child authority must exactly match the delegated bounded scope")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "delegation": self.delegation.to_public_dict(),
            "authorized_tool_ids": list(self.authorized_tool_ids),
            "authorized_capabilities": list(self.authorized_capabilities),
        }


def authorize_agent_delegation(
    request: AgentDelegationRequest,
    *,
    parent_definition: BoundedAgentDefinition,
    parent_profile: CompiledAgentProfile,
    child_definition: BoundedAgentDefinition,
    child_profile: CompiledAgentProfile,
    children_already_delegated: int = 0,
) -> DelegatedAgentAuthority:
    """Allow only inherited-or-narrower Agent authority."""
    if not isinstance(request, AgentDelegationRequest):
        raise AgentDelegationError("invalid_agent_delegation", "request must be AgentDelegationRequest")
    if not isinstance(parent_definition, BoundedAgentDefinition) or not isinstance(child_definition, BoundedAgentDefinition):
        raise AgentDelegationError("invalid_agent_delegation_context", "definitions must be BoundedAgentDefinition")
    if not isinstance(parent_profile, CompiledAgentProfile) or not isinstance(child_profile, CompiledAgentProfile):
        raise AgentDelegationError("invalid_agent_delegation_context", "profiles must be CompiledAgentProfile")
    if request.parent_agent_id != parent_definition.agent_id or parent_profile.canonical_agent_id != parent_definition.agent_id:
        raise AgentDelegationError("delegation_parent_identity_mismatch", "parent identity does not match trusted parent definition/profile")
    if request.child_agent_id != child_definition.agent_id or child_profile.canonical_agent_id != child_definition.agent_id:
        raise AgentDelegationError("delegation_child_identity_mismatch", "child identity does not match trusted child definition/profile")
    if children_already_delegated < 0 or children_already_delegated >= MAX_CHILDREN_PER_PARENT:
        raise AgentDelegationError("delegation_budget_exceeded", "parent child delegation budget exhausted")
    if request.depth > MAX_DELEGATION_DEPTH:
        raise AgentDelegationError("delegation_budget_exceeded", "delegation depth exceeds the trusted maximum")

    parent_tools = frozenset(parent_profile.runtime_profile.allowed_tools)
    child_tools = frozenset(child_profile.runtime_profile.allowed_tools)
    requested_tools = frozenset(request.allowed_tools)
    if not requested_tools <= parent_tools or not child_tools <= parent_tools or not requested_tools <= child_tools:
        raise AgentDelegationError("delegation_tool_widening", "child tool authority must be inherited from or narrower than the parent")

    parent_caps = frozenset(parent_definition.required_capabilities)
    child_caps = frozenset(child_definition.required_capabilities)
    requested_caps = frozenset(request.capabilities)
    if not requested_caps <= parent_caps or not child_caps <= parent_caps:
        raise AgentDelegationError("delegation_capability_widening", "child capabilities must be inherited from or narrower than the parent")

    parent_budget = parent_definition.execution_budget
    child_budget = child_definition.execution_budget
    if request.max_steps > parent_budget.max_steps or request.max_tool_calls > parent_budget.max_tool_calls or request.max_wall_seconds > parent_budget.max_wall_seconds:
        raise AgentDelegationError("delegation_budget_widening", "delegated execution budget exceeds parent budget")
    if child_budget.max_steps > parent_budget.max_steps or child_budget.max_tool_calls > parent_budget.max_tool_calls or child_budget.max_wall_seconds > parent_budget.max_wall_seconds:
        raise AgentDelegationError("delegation_budget_widening", "child execution budget exceeds parent budget")

    return DelegatedAgentAuthority(
        delegation=request,
        authorized_tool_ids=tuple(sorted(request.allowed_tools)),
        authorized_capabilities=tuple(sorted(request.capabilities)),
    )
