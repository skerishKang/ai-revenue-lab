"""Bounded Agent/Skill wire contract for Engine (#1749 E4A/E4B).

Caller data selects canonical identities and supplies bounded execution input.
It never carries compiled profiles, Tool/connector grants, entitlement or
policy authority, subject authority, Provider routing, or continuation state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext
from padiem_ai_core.execution_runtime import ExecutionRequest
from padiem_ai_core.tool_runtime import MAX_TOOL_ARGUMENT_BYTES

from app.agent_skill_authority import (
    EngineAgentSkillAuthorityError,
    EngineAgentSkillBinding,
    TrustedAgentSkillSelection,
)
from app.execution_context_wire import parse_execution_context
from app.service import ServiceContractError
from app.tool_projection import MAX_WIRE_TOOL_ARGUMENTS_BYTES, EngineToolProjectionError, json_size

AGENT_SKILL_RUN_PATH = "/internal/v1/agent-skill/run"
AGENT_SKILL_RESUME_PATH = "/internal/v1/agent-skill/resume"
AGENT_SKILL_CANCEL_PATH = "/internal/v1/agent-skill/cancel"

_SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")

TRUSTED_AGENT_SKILL_REQUIRED = frozenset({"app_id", "agent_id", "messages"})
TRUSTED_AGENT_SKILL_ALLOWED = TRUSTED_AGENT_SKILL_REQUIRED | frozenset(
    {"skill_id", "session_id", "trace_id", "execution_context", "tool_arguments"}
)

AUTHORITY_SHAPED_KEYS = frozenset(
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


def _bounded_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(ch in _SAFE_ID_CHARS for ch in value)
    )


def build_trusted_agent_skill_request(
    payload: Any,
    *,
    binding: EngineAgentSkillBinding,
) -> TrustedAgentSkillWireRequest:
    if not isinstance(payload, Mapping):
        raise ServiceContractError("invalid_request", "Request body must be an object.")
    data = dict(payload)
    if set(data) & AUTHORITY_SHAPED_KEYS:
        raise ServiceContractError(
            "caller_agent_authority_not_allowed",
            "Caller input may select Agent/Skill identities but cannot supply runtime authority.",
        )
    if set(data) - TRUSTED_AGENT_SKILL_ALLOWED:
        raise ServiceContractError(
            "invalid_request",
            "Trusted Agent/Skill request contains unsupported fields.",
        )
    if TRUSTED_AGENT_SKILL_REQUIRED - set(data):
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

    selection = binding.resolve(
        agent_id=data.get("agent_id"),
        skill_id=data.get("skill_id"),
    )
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


def execution_request_with_trace(
    request: ExecutionRequest,
    trace_id: str,
) -> ExecutionRequest:
    return ExecutionRequest(
        agent=request.agent,
        messages=request.messages,
        session_id=request.session_id,
        additional_system_context=request.additional_system_context,
        trace_id=trace_id,
    )


def parse_tool_arguments(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Mapping):
        raise ServiceContractError(
            "invalid_tool_arguments",
            "tool_arguments must be an object keyed by trusted plan step id.",
        )
    if len(value) > 64:
        raise ServiceContractError(
            "invalid_tool_arguments",
            "tool_arguments contains too many entries.",
        )
    parsed: dict[str, dict[str, Any]] = {}
    total = 0
    for key, item in value.items():
        if not _bounded_identifier(key):
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments keys must be bounded safe step identifiers.",
            )
        if isinstance(item, (str, bytes, bytearray)) or not isinstance(item, Mapping):
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments values must be objects.",
            )
        arguments = dict(item)
        try:
            size = json_size(arguments)
        except EngineToolProjectionError:
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments must contain JSON-compatible values only.",
            ) from None
        if size > MAX_TOOL_ARGUMENT_BYTES:
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments step entry exceeds the bounded argument size.",
            )
        total += size
        parsed[key] = arguments
    if total > MAX_WIRE_TOOL_ARGUMENTS_BYTES:
        raise ServiceContractError(
            "tool_arguments_too_large",
            "tool_arguments exceed the bounded Agent/Skill argument budget.",
        )
    return parsed
