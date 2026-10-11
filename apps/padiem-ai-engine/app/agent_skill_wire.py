"""Bounded Agent/Skill wire contract for Engine (#1749 E4A/E4B).

Caller data selects canonical identities and supplies bounded execution input.
It never carries compiled profiles, Tool/connector grants, entitlement or
policy authority, subject authority, Provider routing, or continuation state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
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
from app.orchestration_wire import _parse_agent_plan, _parse_cancel_reason
from app.service import ServiceContractError
from app.tool_projection import MAX_WIRE_TOOL_ARGUMENTS_BYTES, EngineToolProjectionError, json_size

AGENT_SKILL_RUN_PATH = "/internal/v1/agent-skill/run"
AGENT_SKILL_RESUME_PATH = "/internal/v1/agent-skill/resume"
AGENT_SKILL_CANCEL_PATH = "/internal/v1/agent-skill/cancel"
# #4194: owner-scoped control of an already-issued run (never an approval or
# authority surface). Same authenticated internal caller boundary as run/resume.
AGENT_SKILL_RUN_STATUS_PATH = "/internal/v1/agent-skill/run-status"
AGENT_SKILL_RUN_CANCEL_PATH = "/internal/v1/agent-skill/run-cancel"
AGENT_SKILL_RUN_RECOVERY_PATH = "/internal/v1/agent-skill/run-recovery"

_SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
_AGENT_RUN_ID_RE = re.compile(r"arun_[0-9a-f]{32}\Z")
# Same canonical Agent identity contract the trusted Tool projection enforces.
_CANONICAL_AGENT_ID_RE = re.compile(
    r"agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*\Z"
)

TRUSTED_AGENT_SKILL_REQUIRED = frozenset({"app_id", "agent_id", "messages"})
TRUSTED_AGENT_SKILL_ALLOWED = TRUSTED_AGENT_SKILL_REQUIRED | frozenset(
    {"skill_id", "session_id", "trace_id", "execution_context", "tool_arguments", "agent_plan"}
)

AUTHORITY_SHAPED_KEYS = frozenset(
    {
        "agent",
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

    try:
        agent_plan = _parse_agent_plan(data.get("agent_plan"))
    except ServiceContractError:
        raise
    selection = binding.resolve(
        agent_id=data.get("agent_id"),
        plan=agent_plan,
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


AGENT_RUN_CONTROL_REQUIRED = frozenset({"app_id", "agent_id", "run_id"})
AGENT_RUN_CONTROL_ALLOWED = AGENT_RUN_CONTROL_REQUIRED | frozenset({"reason"})
AGENT_RUN_RECOVERY_REQUIRED = frozenset({"app_id", "agent_id"})
AGENT_RUN_RECOVERY_ALLOWED = AGENT_RUN_RECOVERY_REQUIRED | frozenset({"dry_run"})


@dataclass(frozen=True, slots=True)
class TrustedAgentRunControlTarget:
    """Caller may only name an already-issued run; never owner/workspace/plan."""

    app_id: str
    agent_id: str
    run_id: str
    reason: str = "user_cancelled"


@dataclass(frozen=True, slots=True)
class TrustedAgentRunRecoveryRequest:
    app_id: str
    agent_id: str
    dry_run: bool = False


def _customer_app_id(value: Any, *, binding: EngineAgentSkillBinding) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceContractError("invalid_request", "app_id must be a non-empty string.")
    app_id = value.strip()
    if binding.app_id != app_id:
        raise EngineAgentSkillAuthorityError(
            "agent_skill_binding_unavailable",
            "Trusted Agent/Skill authority does not match this application.",
            status_code=503,
        )
    return app_id


def _customer_agent_id(value: Any) -> str:
    """Caller may only name a canonical Agent identity; authority is resolved."""
    if not isinstance(value, str) or not _CANONICAL_AGENT_ID_RE.fullmatch(value):
        raise ServiceContractError(
            "invalid_agent_selection",
            "agent_id must be a bounded canonical Agent identity.",
        )
    return value


def _server_run_id(value: Any) -> str:
    if not isinstance(value, str) or not _AGENT_RUN_ID_RE.fullmatch(value):
        raise ServiceContractError(
            "invalid_agent_run_id",
            "run_id must be a server-issued Agent run identity.",
        )
    return value


def _exact_run_control_mapping(
    payload: Any, *, allowed: frozenset[str], required: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ServiceContractError("invalid_request", "Request body must be an object.")
    data = dict(payload)
    if set(data) & AUTHORITY_SHAPED_KEYS:
        raise ServiceContractError(
            "caller_agent_authority_not_allowed",
            "Caller input may name an issued run but cannot supply runtime authority.",
        )
    if set(data) - allowed:
        raise ServiceContractError(
            "invalid_request",
            "Trusted Agent run control contains unsupported fields.",
        )
    if required - set(data):
        raise ServiceContractError(
            "invalid_request",
            "Trusted Agent run control is missing required fields.",
        )
    return data


def build_trusted_agent_run_control(
    payload: Any,
    *,
    binding: EngineAgentSkillBinding,
) -> TrustedAgentRunControlTarget:
    """Parse an owner-scoped status/cancel target for one issued run.

    The caller supplies only server-issued identifiers; the owner scope is
    resolved from the trusted binding by the service, never from this payload.
    """
    data = _exact_run_control_mapping(
        payload, allowed=AGENT_RUN_CONTROL_ALLOWED, required=AGENT_RUN_CONTROL_REQUIRED,
    )
    return TrustedAgentRunControlTarget(
        app_id=_customer_app_id(data.get("app_id"), binding=binding),
        agent_id=_customer_agent_id(data.get("agent_id")),
        run_id=_server_run_id(data.get("run_id")),
        reason=_parse_cancel_reason(data.get("reason", "user_cancelled")),
    )


def build_trusted_agent_run_recovery(
    payload: Any,
    *,
    binding: EngineAgentSkillBinding,
) -> TrustedAgentRunRecoveryRequest:
    """Parse the expired-lease recovery request; a preview is explicit."""
    data = _exact_run_control_mapping(
        payload, allowed=AGENT_RUN_RECOVERY_ALLOWED, required=AGENT_RUN_RECOVERY_REQUIRED,
    )
    dry_run = data.get("dry_run", False)
    if type(dry_run) is not bool:
        raise ServiceContractError("invalid_request", "dry_run must be a boolean.")
    return TrustedAgentRunRecoveryRequest(
        app_id=_customer_app_id(data.get("app_id"), binding=binding),
        agent_id=_customer_agent_id(data.get("agent_id")),
        dry_run=dry_run,
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
