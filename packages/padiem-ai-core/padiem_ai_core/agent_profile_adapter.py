"""Trusted adapter from canonical Agent definitions to existing AgentProfile.

The existing ``AgentProfile`` + Tool Runtime remains execution authority. This
adapter prevents the new canonical Agent contract from becoming a second tool
runtime or from smuggling canonical package IDs directly into legacy runtime
identifier fields that use a different grammar.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .agent_definition import BoundedAgentDefinition, missing_agent_capabilities
from .contracts import AgentProfile


class AgentProfileCompilationError(ValueError):
    """Raised when trusted runtime policy cannot faithfully compile an Agent."""


@dataclass(frozen=True, slots=True)
class ToolRuntimeBinding:
    """Trusted mapping from canonical Tool ID to existing runtime ToolSpec ID."""

    canonical_tool_id: str
    runtime_tool_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_tool_id, str) or not self.canonical_tool_id.strip():
            raise AgentProfileCompilationError("canonical_tool_id is required")
        if not isinstance(self.runtime_tool_id, str) or not self.runtime_tool_id.strip():
            raise AgentProfileCompilationError("runtime_tool_id is required")


@dataclass(frozen=True, slots=True)
class TrustedAgentRuntimePolicy:
    """Server-resolved runtime policy; none of these fields are browser claims."""

    context_policy_ref: str
    model_policy_ref: str
    output_contract_ref: str
    task_type: str
    optimize_for: str
    max_tokens: int
    max_steps_cap: int
    context_policy: Mapping[str, Any]
    model_policy: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    tool_bindings: tuple[ToolRuntimeBinding, ...] = ()
    connected_connector_ids: frozenset[str] = frozenset()
    active_skill_package_ids: frozenset[str] = frozenset()
    available_capabilities: frozenset[str] = frozenset()
    satisfied_entitlement_refs: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens <= 0:
            raise AgentProfileCompilationError("max_tokens must be a positive integer")
        if isinstance(self.max_steps_cap, bool) or not isinstance(self.max_steps_cap, int) or not 1 <= self.max_steps_cap <= 100:
            raise AgentProfileCompilationError("max_steps_cap must be between 1 and 100")
        if not isinstance(self.tool_bindings, tuple):
            raise AgentProfileCompilationError("tool_bindings must be a tuple")
        if any(not isinstance(binding, ToolRuntimeBinding) for binding in self.tool_bindings):
            raise AgentProfileCompilationError("tool_bindings contains an invalid binding")
        canonical_ids = [binding.canonical_tool_id for binding in self.tool_bindings]
        runtime_ids = [binding.runtime_tool_id for binding in self.tool_bindings]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise AgentProfileCompilationError("tool_bindings contains duplicate canonical IDs")
        if len(runtime_ids) != len(set(runtime_ids)):
            raise AgentProfileCompilationError("tool_bindings contains duplicate runtime IDs")
        for name, value in (
            ("connected_connector_ids", self.connected_connector_ids),
            ("active_skill_package_ids", self.active_skill_package_ids),
            ("available_capabilities", self.available_capabilities),
            ("satisfied_entitlement_refs", self.satisfied_entitlement_refs),
        ):
            if not isinstance(value, frozenset) or any(not isinstance(item, str) for item in value):
                raise AgentProfileCompilationError(f"{name} must be a frozenset of strings")


@dataclass(frozen=True, slots=True)
class CompiledAgentProfile:
    canonical_agent_id: str
    runtime_profile: AgentProfile


def runtime_profile_id_for_agent(canonical_agent_id: str) -> str:
    """Return deterministic legacy-safe runtime ID while preserving canonical ID separately."""
    digest = hashlib.sha256(canonical_agent_id.encode("utf-8")).hexdigest()[:24]
    return f"agent-runtime:{digest}"


def compile_agent_profile(
    definition: BoundedAgentDefinition,
    policy: TrustedAgentRuntimePolicy,
) -> CompiledAgentProfile:
    """Compile canonical Agent metadata into the existing Core AgentProfile.

    Tool bindings, connector availability, skill availability, capabilities,
    entitlement satisfaction and resolved policies all come from trusted server
    state. Missing trusted dependencies fail closed rather than being silently
    invented by the Agent definition.
    """

    if not isinstance(definition, BoundedAgentDefinition):
        raise AgentProfileCompilationError("definition must be BoundedAgentDefinition")
    if not isinstance(policy, TrustedAgentRuntimePolicy):
        raise AgentProfileCompilationError("policy must be TrustedAgentRuntimePolicy")

    expected_refs = (
        ("context_policy_ref", definition.context_policy_ref, policy.context_policy_ref),
        ("model_policy_ref", definition.model_policy_ref, policy.model_policy_ref),
        ("output_contract_ref", definition.output_contract_ref, policy.output_contract_ref),
    )
    for name, declared, resolved in expected_refs:
        if declared != resolved:
            raise AgentProfileCompilationError(
                f"trusted {name} does not match canonical Agent declaration"
            )

    missing_capabilities = missing_agent_capabilities(
        definition,
        policy.available_capabilities,
    )
    if missing_capabilities:
        raise AgentProfileCompilationError(
            "required capabilities are unavailable: " + ",".join(missing_capabilities)
        )

    missing_connectors = tuple(
        connector_id
        for connector_id in definition.connector_requirement_ids
        if connector_id not in policy.connected_connector_ids
    )
    if missing_connectors:
        raise AgentProfileCompilationError(
            "required connectors are not connected: " + ",".join(missing_connectors)
        )

    missing_skills = tuple(
        skill_id
        for skill_id in definition.skill_package_ids
        if skill_id not in policy.active_skill_package_ids
    )
    if missing_skills:
        raise AgentProfileCompilationError(
            "required Skill packages are not active: " + ",".join(missing_skills)
        )

    if (
        definition.entitlement_ref is not None
        and definition.entitlement_ref not in policy.satisfied_entitlement_refs
    ):
        raise AgentProfileCompilationError("required entitlement is not satisfied")

    runtime_binding_by_canonical = {
        binding.canonical_tool_id: binding.runtime_tool_id
        for binding in policy.tool_bindings
    }
    allowed_runtime_tools = tuple(
        runtime_binding_by_canonical[canonical_tool_id]
        for canonical_tool_id in definition.allowed_tool_ids
        if canonical_tool_id in runtime_binding_by_canonical
    )

    profile = AgentProfile(
        id=runtime_profile_id_for_agent(definition.agent_id),
        title=definition.title,
        description=definition.description,
        system_instruction=definition.instruction,
        task_type=policy.task_type,
        optimize_for=policy.optimize_for,
        max_tokens=policy.max_tokens,
        allowed_tools=allowed_runtime_tools,
        required_capabilities=definition.required_capabilities,
        context_policy=policy.context_policy,
        model_policy=policy.model_policy,
        max_steps=min(definition.execution_budget.max_steps, policy.max_steps_cap),
        output_contract=policy.output_contract,
    )
    return CompiledAgentProfile(
        canonical_agent_id=definition.agent_id,
        runtime_profile=profile,
    )
