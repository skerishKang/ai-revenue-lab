"""Trusted runtime adapter for reusable Padiem AI Core Skills.

A reusable Skill package is declarative metadata. It can request capabilities,
declare tools/connectors, and point at policy contracts, but it cannot grant
itself permissions or choose Provider credentials/routes. This adapter compiles
one package against trusted server-resolved runtime state into the existing
AgentProfile contract used by Core execution/orchestration.

The adapter deliberately does not execute tools, install packages, resolve
OAuth, or mutate entitlement state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .agent_profile_adapter import ToolRuntimeBinding
from .contracts import AgentProfile
from .skill_package import ReusableSkillPackage, missing_required_capabilities


class SkillRuntimeAdapterError(ValueError):
    """Raised when trusted runtime state cannot faithfully compile a Skill."""


@dataclass(frozen=True, slots=True)
class TrustedSkillRuntimePolicy:
    """Server-resolved policy used to compile a declarative Skill package."""

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
    available_capabilities: frozenset[str] = frozenset()
    satisfied_entitlement_refs: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name in (
            "context_policy_ref",
            "model_policy_ref",
            "output_contract_ref",
            "task_type",
            "optimize_for",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SkillRuntimeAdapterError(f"{name} must be a non-empty string")

        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise SkillRuntimeAdapterError("max_tokens must be a positive integer")
        if (
            isinstance(self.max_steps_cap, bool)
            or not isinstance(self.max_steps_cap, int)
            or not 1 <= self.max_steps_cap <= 100
        ):
            raise SkillRuntimeAdapterError("max_steps_cap must be between 1 and 100")

        if not isinstance(self.tool_bindings, tuple):
            raise SkillRuntimeAdapterError("tool_bindings must be a tuple")
        if any(not isinstance(binding, ToolRuntimeBinding) for binding in self.tool_bindings):
            raise SkillRuntimeAdapterError("tool_bindings contains an invalid binding")
        canonical_ids = [binding.canonical_tool_id for binding in self.tool_bindings]
        runtime_ids = [binding.runtime_tool_id for binding in self.tool_bindings]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise SkillRuntimeAdapterError(
                "tool_bindings contains duplicate canonical IDs"
            )
        if len(runtime_ids) != len(set(runtime_ids)):
            raise SkillRuntimeAdapterError("tool_bindings contains duplicate runtime IDs")

        for name in (
            "connected_connector_ids",
            "available_capabilities",
            "satisfied_entitlement_refs",
        ):
            value = getattr(self, name)
            if not isinstance(value, frozenset) or any(
                not isinstance(item, str) for item in value
            ):
                raise SkillRuntimeAdapterError(
                    f"{name} must be a frozenset of strings"
                )

        for name in ("context_policy", "model_policy", "output_contract"):
            if not isinstance(getattr(self, name), Mapping):
                raise SkillRuntimeAdapterError(f"{name} must be a mapping")


@dataclass(frozen=True, slots=True)
class CompiledSkillProfile:
    """Legacy-safe Core runtime profile paired with its canonical Skill ID."""

    canonical_skill_id: str
    runtime_profile: AgentProfile

    def __post_init__(self) -> None:
        if (
            not isinstance(self.canonical_skill_id, str)
            or not self.canonical_skill_id.strip()
        ):
            raise SkillRuntimeAdapterError("canonical_skill_id is required")
        if not isinstance(self.runtime_profile, AgentProfile):
            raise SkillRuntimeAdapterError("runtime_profile must be AgentProfile")


def runtime_profile_id_for_skill(canonical_skill_id: str) -> str:
    """Return a deterministic legacy-safe AgentProfile ID for a canonical Skill."""

    if not isinstance(canonical_skill_id, str) or not canonical_skill_id.strip():
        raise SkillRuntimeAdapterError("canonical_skill_id is required")
    digest = hashlib.sha256(canonical_skill_id.encode("utf-8")).hexdigest()[:24]
    return f"skill-runtime:{digest}"


def compile_skill_profile(
    package: ReusableSkillPackage,
    policy: TrustedSkillRuntimePolicy,
) -> CompiledSkillProfile:
    """Compile a declarative Skill into the existing AgentProfile contract.

    All authority-bearing state is supplied by ``policy``. The package may
    narrow available tools by declaration, but cannot mint a runtime binding,
    connector authorization, capability, entitlement, or Provider route.
    """

    if not isinstance(package, ReusableSkillPackage):
        raise SkillRuntimeAdapterError("package must be ReusableSkillPackage")
    if not isinstance(policy, TrustedSkillRuntimePolicy):
        raise SkillRuntimeAdapterError("policy must be TrustedSkillRuntimePolicy")

    expected_refs = (
        ("context_policy_ref", package.context_policy_ref, policy.context_policy_ref),
        ("model_policy_ref", package.model_policy_ref, policy.model_policy_ref),
        ("output_contract_ref", package.output_contract_ref, policy.output_contract_ref),
    )
    for name, declared, resolved in expected_refs:
        if declared != resolved:
            raise SkillRuntimeAdapterError(
                f"trusted {name} does not match Skill package declaration"
            )

    missing_capabilities = missing_required_capabilities(
        package,
        policy.available_capabilities,
    )
    if missing_capabilities:
        raise SkillRuntimeAdapterError(
            "required capabilities are unavailable: "
            + ",".join(missing_capabilities)
        )

    missing_connectors = tuple(
        connector_id
        for connector_id in package.connector_requirement_ids
        if connector_id not in policy.connected_connector_ids
    )
    if missing_connectors:
        raise SkillRuntimeAdapterError(
            "required connectors are not connected: " + ",".join(missing_connectors)
        )

    if (
        package.entitlement_ref is not None
        and package.entitlement_ref not in policy.satisfied_entitlement_refs
    ):
        raise SkillRuntimeAdapterError("required entitlement is not satisfied")

    runtime_binding_by_canonical = {
        binding.canonical_tool_id: binding.runtime_tool_id
        for binding in policy.tool_bindings
    }
    allowed_runtime_tools = tuple(
        runtime_binding_by_canonical[canonical_tool_id]
        for canonical_tool_id in package.allowed_tool_ids
        if canonical_tool_id in runtime_binding_by_canonical
    )

    profile = AgentProfile(
        id=runtime_profile_id_for_skill(package.skill_id),
        title=package.skill_id,
        description=package.description,
        system_instruction=package.instruction,
        task_type=policy.task_type,
        optimize_for=policy.optimize_for,
        max_tokens=policy.max_tokens,
        allowed_tools=allowed_runtime_tools,
        required_capabilities=package.required_capabilities,
        context_policy=policy.context_policy,
        model_policy=policy.model_policy,
        max_steps=min(package.execution_budget.max_steps, policy.max_steps_cap),
        output_contract=policy.output_contract,
    )
    return CompiledSkillProfile(
        canonical_skill_id=package.skill_id,
        runtime_profile=profile,
    )
