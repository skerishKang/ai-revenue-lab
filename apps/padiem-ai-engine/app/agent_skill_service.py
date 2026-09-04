"""Bounded caller selection for trusted Agent/Skill orchestration (#1749 E4A).

The caller selects identities and supplies user input only.  Every authority-
bearing object is injected through ``EngineAgentSkillBinding``.  This module
constructs a Core ``ExecutionRequest`` from the already-compiled trusted Agent
profile; it never compiles profiles or grants tools itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from padiem_ai_core import ExecutionContext, ExecutionRequest

from app.agent_skill_authority import (
    EngineAgentSkillAuthorityError,
    EngineAgentSkillBinding,
    TrustedAgentSkillSelection,
)
from app.execution_context_wire import parse_execution_context
from app.service import ServiceContractError

# Deliberately narrower than the general orchestration wire.  Agent/Skill
# authority selection does not accept a caller-authored AgentProfile, plan,
# recovery policy, subject identity, entitlement, registry or Provider route.
TRUSTED_AGENT_SKILL_REQUIRED = frozenset({"app_id", "agent_id", "messages"})
TRUSTED_AGENT_SKILL_ALLOWED = TRUSTED_AGENT_SKILL_REQUIRED | frozenset(
    {"skill_id", "session_id", "trace_id", "execution_context", "tool_arguments"}
)

_AUTHORITY_SHAPED_KEYS = frozenset(
    {
        "agent",
        "agent_plan",
        "compiled_profile",
        "compiled_agent_profile",
        "tool_bindings",
        "tool_authorization",
        "authorization",
        "connector_grants",
        "connected_connector_ids",
        "entitlement",
        "entitlements",
        "entitlement_ref",
        "policy",
        "policies",
        "context_policy",
        "model_policy",
        "output_contract",
        "provider",
        "provider_route",
        "subject_id",
        "skill_registry",
        "skill_installations",
        "skill_runtime_policy",
        "recovery_policy",
    }
)


@dataclass(frozen=True, slots=True)
class TrustedAgentSkillWireRequest:
    app_id: str
    execution_request: ExecutionRequest
    context: ExecutionContext | None
    selection: TrustedAgentSkillSelection
    raw_tool_arguments: Any = None


def build_trusted_agent_skill_request(
    payload: Any,
    *,
    binding: EngineAgentSkillBinding,
) -> TrustedAgentSkillWireRequest:
    """Parse one identity-only request and attach server-trusted authority."""

    if not isinstance(payload, Mapping):
        raise ServiceContractError("invalid_request", "Request body must be an object.")
    data = dict(payload)
    attempted_authority = set(data) & _AUTHORITY_SHAPED_KEYS
    if attempted_authority:
        raise ServiceContractError(
            "caller_agent_authority_not_allowed",
            "Caller input may select Agent/Skill identities but cannot supply runtime authority.",
        )
    unknown = set(data) - TRUSTED_AGENT_SKILL_ALLOWED
    if unknown:
        raise ServiceContractError(
            "invalid_request",
            "Trusted Agent/Skill request contains unsupported fields.",
        )
    missing = TRUSTED_AGENT_SKILL_REQUIRED - set(data)
    if missing:
        raise ServiceContractError(
            "invalid_request",
            "Trusted Agent/Skill request is missing required fields.",
        )

    app_id = data.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        raise ServiceContractError("invalid_request", "app_id must be a non-empty string.")
    app_id = app_id.strip()
    if binding.app_id != app_id:
        raise EngineAgentSkillAuthorityError(
            "agent_skill_binding_unavailable",
            "Trusted Agent/Skill authority does not match this application.",
            status_code=503,
        )

    agent_id = data.get("agent_id")
    skill_id = data.get("skill_id")
    selection = binding.resolve(agent_id=agent_id, skill_id=skill_id)

    try:
        context = parse_execution_context(data.get("execution_context"))
    except (TypeError, ValueError, OverflowError):
        raise ServiceContractError(
            "invalid_execution_context",
            "Execution context fields are invalid.",
        ) from None
    explicit_trace = data.get("trace_id")
    if context is not None and explicit_trace is not None and explicit_trace != context.trace_id:
        raise ServiceContractError(
            "trace_id_conflict",
            "trace_id conflicts with execution_context.trace_id.",
        )
    trace_id = context.trace_id if context is not None else explicit_trace

    try:
        execution_request = ExecutionRequest(
            # This is the server-resolved compiled Core profile.  No caller
            # profile fields participate in this construction.
            agent=selection.authority.compiled.runtime_profile,
            messages=data.get("messages"),
            session_id=data.get("session_id"),
            trace_id=trace_id,
        )
    except (TypeError, ValueError, OverflowError):
        raise ServiceContractError(
            "invalid_request",
            "Agent/Skill input is invalid for the Core execution contract.",
        ) from None

    return TrustedAgentSkillWireRequest(
        app_id=app_id,
        execution_request=execution_request,
        context=context,
        selection=selection,
        raw_tool_arguments=data.get("tool_arguments"),
    )
