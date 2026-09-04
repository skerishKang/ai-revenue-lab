"""Trusted Agent/Skill authority binding for Engine orchestration (#1749 E4A).

This module contains server-owned authority only.  Caller JSON may select a
canonical Agent/Skill identity, but it cannot construct a compiled profile,
ToolAuthorizationContext, registry, connector/entitlement grant, policy body,
or Provider route.

Agent execution reuses the exact #1746 EngineToolBinding authority and Core
AgentPlan validation. Skill activation remains Core authority through
``compile_enabled_skill`` inside ``OrchestrationRunner``; this binding supplies
only the trusted registry/installation/policy inputs required by that Core gate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re

from padiem_ai_core.agent_planner import AgentPlan, AgentPlannerError, validate_agent_plan
from padiem_ai_core.skill_registry import SkillInstallationSnapshot, SkillRegistrySnapshot
from padiem_ai_core.skill_runtime_adapter import TrustedSkillRuntimePolicy

from app.tool_projection import EngineToolBinding, EngineToolProjectionError, TrustedToolAuthority

_CANONICAL_AGENT_ID_RE = re.compile(
    r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_CANONICAL_SKILL_ID_RE = re.compile(
    r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_BOUND_AGENT_PLANS = 64


class EngineAgentSkillAuthorityError(ValueError):
    """Fail-closed trusted-binding error with a Product-safe message."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("agent/skill authority error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TrustedAgentSkillSelection:
    """Resolved server authority for one bounded Agent and optional Skill."""

    authority: TrustedToolAuthority
    plan: AgentPlan
    subject_id: str
    skill_id: str | None = None
    skill_registry: SkillRegistrySnapshot | None = None
    skill_installations: SkillInstallationSnapshot | None = None
    skill_runtime_policy: TrustedSkillRuntimePolicy | None = None


@dataclass(frozen=True, slots=True)
class EngineAgentSkillBinding:
    """Server-provisioned Agent/Skill identity and activation authority.

    ``tool_binding`` is the existing #1746 authority.  This type does not copy
    its registry/runtime/authorization semantics; it delegates Agent resolution
    to ``EngineToolBinding.resolve_authority`` and passes the same Core values
    through to orchestration.

    ``subject_id`` is trusted binding state, deliberately not a request field.
    A future Control Plane/session integration may select a different binding,
    but the caller cannot self-assert another subject through this wire.
    """

    app_id: str
    subject_id: str
    tool_binding: EngineToolBinding
    agent_plans: Mapping[str, AgentPlan]
    skill_registry: SkillRegistrySnapshot | None = None
    skill_installations: SkillInstallationSnapshot | None = None
    skill_runtime_policy_resolver: Callable[[str], TrustedSkillRuntimePolicy | None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.app_id, str) or not _SAFE_ID_RE.fullmatch(self.app_id):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent/Skill binding app_id is invalid.",
                status_code=503,
            )
        if not isinstance(self.subject_id, str) or not _SAFE_ID_RE.fullmatch(self.subject_id):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent/Skill binding subject identity is invalid.",
                status_code=503,
            )
        if not isinstance(self.tool_binding, EngineToolBinding):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent/Skill binding must reuse an EngineToolBinding.",
                status_code=503,
            )
        if self.tool_binding.app_id != self.app_id:
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent/Skill binding does not match Tool authority application scope.",
                status_code=503,
            )
        if isinstance(self.agent_plans, (str, bytes)) or not isinstance(self.agent_plans, Mapping):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent plans must be a trusted mapping.",
                status_code=503,
            )
        plans = dict(self.agent_plans)
        if len(plans) > MAX_BOUND_AGENT_PLANS:
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Agent plan binding exceeds the bounded authority count.",
                status_code=503,
            )
        for agent_id, plan in plans.items():
            if not isinstance(agent_id, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(agent_id):
                raise EngineAgentSkillAuthorityError(
                    "invalid_agent_skill_binding",
                    "Agent plan keys must be canonical Agent identities.",
                    status_code=503,
                )
            if not isinstance(plan, AgentPlan) or plan.agent_id != agent_id:
                raise EngineAgentSkillAuthorityError(
                    "invalid_agent_skill_binding",
                    "Trusted Agent plan identity does not match its binding key.",
                    status_code=503,
                )
        if self.skill_registry is not None and not isinstance(self.skill_registry, SkillRegistrySnapshot):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Skill registry binding is invalid.",
                status_code=503,
            )
        if self.skill_installations is not None and not isinstance(
            self.skill_installations, SkillInstallationSnapshot
        ):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Skill installation binding is invalid.",
                status_code=503,
            )
        if self.skill_runtime_policy_resolver is not None and not callable(
            self.skill_runtime_policy_resolver
        ):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "Skill runtime policy resolver must be callable.",
                status_code=503,
            )

    def resolve(
        self,
        *,
        agent_id: str,
        skill_id: str | None = None,
    ) -> TrustedAgentSkillSelection:
        """Resolve exact trusted Agent/Skill authority without widening it."""

        if not isinstance(agent_id, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(agent_id):
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_selection",
                "agent_id must be a canonical versioned Agent identity.",
            )
        try:
            authority = self.tool_binding.resolve_authority(agent_id)
        except EngineToolProjectionError as exc:
            raise EngineAgentSkillAuthorityError(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
            ) from exc

        plan = dict(self.agent_plans).get(agent_id)
        if plan is None:
            raise EngineAgentSkillAuthorityError(
                "agent_plan_unavailable",
                "The selected Agent has no trusted bounded execution plan.",
                status_code=503,
            )
        try:
            validate_agent_plan(
                plan,
                definition=authority.definition,
                compiled_profile=authority.compiled,
            )
        except AgentPlannerError as exc:
            raise EngineAgentSkillAuthorityError(
                "invalid_agent_skill_binding",
                "The trusted Agent plan failed Core validation.",
                status_code=503,
            ) from exc

        if skill_id is None:
            return TrustedAgentSkillSelection(
                authority=authority,
                plan=plan,
                subject_id=self.subject_id,
            )
        if not isinstance(skill_id, str) or not _CANONICAL_SKILL_ID_RE.fullmatch(skill_id):
            raise EngineAgentSkillAuthorityError(
                "invalid_skill_selection",
                "skill_id must be a canonical versioned Skill identity.",
            )
        if skill_id not in authority.definition.skill_package_ids:
            raise EngineAgentSkillAuthorityError(
                "skill_not_allowed",
                "The selected Skill is not declared by the trusted Agent definition.",
                status_code=403,
            )
        if (
            self.skill_registry is None
            or self.skill_installations is None
            or self.skill_runtime_policy_resolver is None
        ):
            raise EngineAgentSkillAuthorityError(
                "skill_runtime_unavailable",
                "Trusted Skill activation authority is unavailable.",
                status_code=503,
            )
        try:
            policy = self.skill_runtime_policy_resolver(skill_id)
        except Exception as exc:
            raise EngineAgentSkillAuthorityError(
                "skill_runtime_unavailable",
                "Trusted Skill runtime policy resolution failed.",
                status_code=503,
            ) from exc
        if not isinstance(policy, TrustedSkillRuntimePolicy):
            raise EngineAgentSkillAuthorityError(
                "skill_runtime_unavailable",
                "Trusted Skill runtime policy is unavailable.",
                status_code=503,
            )
        return TrustedAgentSkillSelection(
            authority=authority,
            plan=plan,
            subject_id=self.subject_id,
            skill_id=skill_id,
            skill_registry=self.skill_registry,
            skill_installations=self.skill_installations,
            skill_runtime_policy=policy,
        )
