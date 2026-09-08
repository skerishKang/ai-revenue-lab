"""Fail-closed continuation identity for Agent/Skill projection (#1749 E4B).

Continuation is not new Agent state.  This module binds one server-issued Core
approval pause to the exact prior caller intent and trusted Agent/Skill/Tool
runtime authority.  Resume may change Tool authorization only by the single
approval grant represented by that pause; scopes, unrelated Tool grants,
Agent/Skill identity, plan, registry, resource ceilings and policy authority
must remain byte-equivalent at the fingerprint boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement, tool_invocation_digest
from padiem_ai_core.execution_context import ExecutionContext, request_fingerprint
from padiem_ai_core.skill_activation import compile_enabled_skill
from padiem_ai_core.skill_registry import SkillRegistryError
from padiem_ai_core.skill_runtime_adapter import SkillRuntimeAdapterError
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolInvocation

from app.agent_skill_authority import EngineAgentSkillBinding, TrustedAgentSkillSelection

_FINGERPRINT_VERSION = "ags-cont-v1"


class AgentSkillContinuationError(ValueError):
    def __init__(self, code: str, safe_message: str, *, status_code: int = 409) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class AgentSkillContinuationFingerprint:
    intent: str
    base_authority: str
    approved_authority: str

    def encode(self) -> str:
        return f"{_FINGERPRINT_VERSION}:{self.intent}:{self.base_authority}:{self.approved_authority}"

    @classmethod
    def decode(cls, value: str | None) -> "AgentSkillContinuationFingerprint":
        if not isinstance(value, str):
            raise AgentSkillContinuationError(
                "continuation_identity_mismatch",
                "Continuation identity evidence is unavailable.",
            )
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != _FINGERPRINT_VERSION:
            raise AgentSkillContinuationError(
                "continuation_identity_mismatch",
                "Continuation identity evidence is invalid.",
            )
        for digest in parts[1:]:
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise AgentSkillContinuationError(
                    "continuation_identity_mismatch",
                    "Continuation identity evidence is invalid.",
                )
        return cls(intent=parts[1], base_authority=parts[2], approved_authority=parts[3])


def _mapping_hash(value: Mapping[str, Any]) -> str:
    try:
        return request_fingerprint({"policy": dict(value)})
    except (TypeError, ValueError) as exc:
        raise AgentSkillContinuationError(
            "agent_skill_runtime_unavailable",
            "Trusted Agent/Skill policy authority is not fingerprintable.",
            status_code=503,
        ) from exc


def _authorization_payload(authorization: ToolAuthorizationContext) -> dict[str, Any]:
    return {
        "app_id": authorization.app_id,
        "agent_id": authorization.agent_id,
        "granted_auth_scopes": list(authorization.granted_auth_scopes),
        "user_confirmed_tools": list(authorization.user_confirmed_tools),
        "externally_authorized_tools": list(authorization.externally_authorized_tools),
    }


def _with_expected_pause_grant(
    authorization: ToolAuthorizationContext,
    pause: ApprovalPause,
) -> ToolAuthorizationContext:
    confirmed = set(authorization.user_confirmed_tools)
    external = set(authorization.externally_authorized_tools)
    if pause.requirement is ApprovalRequirement.USER_CONFIRMATION:
        confirmed.add(pause.tool_id)
    elif pause.requirement is ApprovalRequirement.EXTERNAL_AUTHORIZATION:
        external.add(pause.tool_id)
    else:
        raise AgentSkillContinuationError(
            "invalid_continuation",
            "Approval pause requirement is not resumable.",
        )
    return ToolAuthorizationContext(
        app_id=authorization.app_id,
        agent_id=authorization.agent_id,
        granted_auth_scopes=tuple(sorted(authorization.granted_auth_scopes)),
        user_confirmed_tools=tuple(sorted(confirmed)),
        externally_authorized_tools=tuple(sorted(external)),
    )


def trusted_authority_hash(
    binding: EngineAgentSkillBinding,
    selection: TrustedAgentSkillSelection,
    *,
    authorization: ToolAuthorizationContext | None = None,
) -> str:
    """Hash exact server authority without persisting private policy bodies."""

    authority = selection.authority
    definition = authority.definition
    profile = authority.compiled.runtime_profile
    active_authorization = authorization or authority.authorization
    resource = binding.tool_binding.resource_policy

    skill_payload: dict[str, Any] | None = None
    if selection.skill_id is not None:
        if (
            selection.skill_registry is None
            or selection.skill_installations is None
            or selection.skill_runtime_policy is None
        ):
            raise AgentSkillContinuationError(
                "skill_runtime_unavailable",
                "Trusted Skill activation authority is unavailable.",
                status_code=503,
            )
        try:
            registry_entry = selection.skill_registry.get(selection.skill_id)
            installation = selection.skill_installations.get(
                app_id=binding.app_id,
                subject_id=selection.subject_id,
                skill_id=selection.skill_id,
            )
            # Re-run the existing Core activation gate so a Skill disabled or
            # de-authorized after pause cannot resume using stale authority.
            activated = compile_enabled_skill(
                registry=selection.skill_registry,
                installations=selection.skill_installations,
                app_id=binding.app_id,
                subject_id=selection.subject_id,
                skill_id=selection.skill_id,
                runtime_policy=selection.skill_runtime_policy,
            )
        except (SkillRegistryError, SkillRuntimeAdapterError) as exc:
            code = getattr(exc, "code", "skill_runtime_policy_rejected")
            message = getattr(exc, "safe_message", str(exc))
            raise AgentSkillContinuationError(code, message, status_code=403) from exc

        skill_profile = activated.compiled.runtime_profile
        for runtime_tool_id in skill_profile.allowed_tools:
            if runtime_tool_id not in profile.allowed_tools:
                raise AgentSkillContinuationError(
                    "authority_widening_rejected",
                    "Skill authority would widen the trusted Agent Tool scope.",
                    status_code=403,
                )
        policy = selection.skill_runtime_policy
        skill_payload = {
            "skill_id": selection.skill_id,
            "registry_fingerprint": registry_entry.fingerprint,
            "installation_status": installation.status.value,
            "runtime_profile_id": skill_profile.id,
            "allowed_tools": list(skill_profile.allowed_tools),
            "context_policy_ref": policy.context_policy_ref,
            "model_policy_ref": policy.model_policy_ref,
            "output_contract_ref": policy.output_contract_ref,
            "max_steps_cap": policy.max_steps_cap,
            "tool_bindings": [
                [item.canonical_tool_id, item.runtime_tool_id]
                for item in policy.tool_bindings
            ],
            "connected_connector_ids": sorted(policy.connected_connector_ids),
            "available_capabilities": sorted(policy.available_capabilities),
            "satisfied_entitlement_refs": sorted(policy.satisfied_entitlement_refs),
            "context_policy_hash": _mapping_hash(policy.context_policy),
            "model_policy_hash": _mapping_hash(policy.model_policy),
            "output_contract_hash": _mapping_hash(policy.output_contract),
        }

    payload = {
        "app_id": binding.app_id,
        "subject_id": selection.subject_id,
        "agent_id": authority.canonical_agent_id,
        "definition": {
            "publisher_id": definition.publisher_id,
            "skill_package_ids": list(definition.skill_package_ids),
            "allowed_tool_ids": list(definition.allowed_tool_ids),
            "connector_requirement_ids": list(definition.connector_requirement_ids),
            "required_capabilities": list(definition.required_capabilities),
            "context_policy_ref": definition.context_policy_ref,
            "model_policy_ref": definition.model_policy_ref,
            "output_contract_ref": definition.output_contract_ref,
            "entitlement_ref": definition.entitlement_ref,
            "execution_budget": {
                "max_steps": definition.execution_budget.max_steps,
                "max_tool_calls": definition.execution_budget.max_tool_calls,
                "max_skill_calls": definition.execution_budget.max_skill_calls,
                "max_wall_seconds": definition.execution_budget.max_wall_seconds,
            },
            "approval_checkpoints": [item.value for item in definition.approval_checkpoints],
        },
        "compiled_profile": {
            "id": profile.id,
            "allowed_tools": list(profile.allowed_tools),
            "required_capabilities": list(profile.required_capabilities),
            "max_steps": profile.max_steps,
            "context_policy_hash": _mapping_hash(profile.context_policy),
            "model_policy_hash": _mapping_hash(profile.model_policy),
            "output_contract_hash": _mapping_hash(profile.output_contract),
        },
        "authorization": _authorization_payload(active_authorization),
        "plan": {
            "agent_id": selection.plan.agent_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "objective": step.objective,
                    "tool_id": step.tool_id,
                    "depends_on": list(step.depends_on),
                }
                for step in selection.plan.steps
            ],
        },
        "tool_registry": [
            [entry.canonical_tool_id, entry.runtime_tool_id, entry.fingerprint]
            for entry in binding.tool_binding.registry.entries
        ],
        "tool_resource_policy": None
        if resource is None
        else {
            "max_argument_bytes": resource.max_argument_bytes,
            "max_output_bytes": resource.max_output_bytes,
            "max_timeout_seconds": resource.max_timeout_seconds,
        },
        "skill": skill_payload,
    }
    try:
        return request_fingerprint(payload)
    except (TypeError, ValueError) as exc:
        raise AgentSkillContinuationError(
            "agent_skill_runtime_unavailable",
            "Trusted Agent/Skill authority could not be fingerprinted.",
            status_code=503,
        ) from exc


def caller_intent_hash(
    *,
    execution_request: Any,
    context: ExecutionContext,
    selection: TrustedAgentSkillSelection,
    tool_arguments: Mapping[str, Mapping[str, Any]],
) -> str:
    """Hash normalized input plus selected identities; no private bytes are returned."""

    try:
        return request_fingerprint(
            {
                "app_id": selection.authority.authorization.app_id,
                "agent_id": selection.authority.canonical_agent_id,
                "skill_id": selection.skill_id,
                "subject_id": selection.subject_id,
                "messages": list(execution_request.messages),
                "session_id": execution_request.session_id,
                "trace_id": context.trace_id,
                "timeout_seconds": context.timeout_seconds,
                "idempotency_key": context.idempotency_key,
                "tool_arguments": dict(tool_arguments),
            }
        )
    except (TypeError, ValueError) as exc:
        raise AgentSkillContinuationError(
            "invalid_request",
            "Agent/Skill continuation input could not be fingerprinted.",
            status_code=400,
        ) from exc


def issue_fingerprint(
    *,
    binding: EngineAgentSkillBinding,
    selection: TrustedAgentSkillSelection,
    execution_request: Any,
    context: ExecutionContext,
    tool_arguments: Mapping[str, Mapping[str, Any]],
    pause: ApprovalPause,
) -> AgentSkillContinuationFingerprint:
    base = trusted_authority_hash(binding, selection)
    approved = trusted_authority_hash(
        binding,
        selection,
        authorization=_with_expected_pause_grant(selection.authority.authorization, pause),
    )
    return AgentSkillContinuationFingerprint(
        intent=caller_intent_hash(
            execution_request=execution_request,
            context=context,
            selection=selection,
            tool_arguments=tool_arguments,
        ),
        base_authority=base,
        approved_authority=approved,
    )


def assert_resume_identity(
    *,
    stored: AgentSkillContinuationFingerprint,
    binding: EngineAgentSkillBinding,
    selection: TrustedAgentSkillSelection,
    execution_request: Any,
    context: ExecutionContext,
    tool_arguments: Mapping[str, Mapping[str, Any]],
    pause: ApprovalPause,
    approved: bool,
) -> None:
    current_intent = caller_intent_hash(
        execution_request=execution_request,
        context=context,
        selection=selection,
        tool_arguments=tool_arguments,
    )
    if current_intent != stored.intent:
        raise AgentSkillContinuationError(
            "continuation_identity_mismatch",
            "Resume input does not match the server-issued continuation.",
        )

    current_authority = trusted_authority_hash(binding, selection)
    expected = stored.approved_authority if approved else stored.base_authority
    if current_authority != expected:
        raise AgentSkillContinuationError(
            "continuation_authority_mismatch",
            "Resume authority does not exactly match the permitted continuation authority.",
        )

    step_index = pause.step_index - 1
    if not 0 <= step_index < len(selection.plan.steps):
        raise AgentSkillContinuationError(
            "continuation_identity_mismatch",
            "Paused step does not exist in the trusted Agent plan.",
        )
    step = selection.plan.steps[step_index]
    if step.tool_id != pause.tool_id:
        raise AgentSkillContinuationError(
            "continuation_identity_mismatch",
            "Paused Tool does not match the trusted Agent plan.",
        )
    arguments = dict(tool_arguments.get(step.step_id, {}) or {})
    if not arguments and step.objective:
        arguments["query"] = step.objective
    try:
        invocation = ToolInvocation(tool_id=step.tool_id, arguments=arguments)
    except (TypeError, ValueError) as exc:
        raise AgentSkillContinuationError(
            "continuation_identity_mismatch",
            "Resumed Tool invocation is invalid.",
        ) from exc
    if tool_invocation_digest(invocation) != pause.invocation_sha256:
        raise AgentSkillContinuationError(
            "continuation_identity_mismatch",
            "Resumed Tool invocation differs from the paused invocation.",
        )
