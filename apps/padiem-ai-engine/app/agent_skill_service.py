"""Bounded trusted Agent/Skill transport over Core orchestration (#1749 E4A).

The caller selects identities and supplies user input only. Every authority-
bearing object is injected through ``EngineAgentSkillBinding``. Execution goes
through the existing Core ``OrchestrationRunner`` / ``AgentPlanExecutor`` /
``ToolRuntime`` path; this module does not implement a second Agent loop, Tool
authority, Provider router, approval state machine, or Skill compiler.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re
import secrets
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext, IdempotencyConflictError
from padiem_ai_core.execution_runtime import ExecutionRequest
from padiem_ai_core.orchestration import (
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationRunner,
)
from padiem_ai_core.skill_registry import SkillRegistryError
from padiem_ai_core.skill_runtime_adapter import SkillRuntimeAdapterError
from padiem_ai_core.tool_runtime import MAX_TOOL_ARGUMENT_BYTES

from app.agent_skill_authority import (
    EngineAgentSkillAuthorityError,
    EngineAgentSkillBinding,
    TrustedAgentSkillSelection,
)
from app.agent_skill_projection import project_agent_skill_result
from app.execution_context_wire import parse_execution_context
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _service_error,
)
from app.tool_projection import MAX_WIRE_TOOL_ARGUMENTS_BYTES, EngineToolProjectionError, json_size

AGENT_SKILL_RUN_PATH = "/internal/v1/agent-skill/run"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Deliberately narrower than the general orchestration wire. Agent/Skill
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
            # This is the server-resolved compiled Core profile. No caller
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


def _execution_request_with_trace(
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


def _parse_tool_arguments(value: Any) -> dict[str, dict[str, Any]]:
    """Parse non-authority per-step arguments for a trusted server plan."""

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
        if not isinstance(key, str) or not _SAFE_ID_RE.fullmatch(key):
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


class AgentSkillEngineService:
    """Thin Engine transport that projects trusted Core Agent/Skill execution."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        binding_resolver: Callable[[str], EngineAgentSkillBinding | None] | None = None,
        idempotency_adapter: Any | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if binding_resolver is not None and not callable(binding_resolver):
            raise ValueError("binding_resolver must be callable")
        self._runtime_factory = runtime_factory
        self._binding_resolver = binding_resolver
        self._idempotency_adapter = idempotency_adapter

    def _resolve_binding(self, app_id: str) -> EngineAgentSkillBinding:
        if self._binding_resolver is None:
            raise EngineAgentSkillAuthorityError(
                "agent_skill_runtime_unavailable",
                "Trusted Agent/Skill runtime authority is unavailable.",
                status_code=503,
            )
        try:
            binding = self._binding_resolver(app_id)
        except Exception as exc:
            raise EngineAgentSkillAuthorityError(
                "agent_skill_runtime_unavailable",
                "Trusted Agent/Skill runtime authority resolution failed.",
                status_code=503,
            ) from exc
        if not isinstance(binding, EngineAgentSkillBinding) or binding.app_id != app_id:
            raise EngineAgentSkillAuthorityError(
                "agent_skill_runtime_unavailable",
                "Trusted Agent/Skill runtime authority is unavailable for this application.",
                status_code=503,
            )
        return binding

    async def run_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error(
                "invalid_request",
                "Request body must be an object.",
                status_code=400,
            )
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error(
                "invalid_request",
                "app_id must be a non-empty string.",
                status_code=400,
            )
        app_id = app_id.strip()

        try:
            binding = self._resolve_binding(app_id)
            wire = build_trusted_agent_skill_request(payload, binding=binding)
            exec_req = wire.execution_request
            context = wire.context
            if context is None:
                trace_id = exec_req.trace_id or f"agtr_{secrets.token_hex(12)}"
                exec_req = _execution_request_with_trace(exec_req, trace_id)
                context = ExecutionContext(trace_id=trace_id)

            selection = wire.selection
            authority = selection.authority
            orch_req = OrchestrationRequest(
                execution_request=exec_req,
                context=context,
                app_id=app_id,
                # Subject authority is server binding state, never caller JSON.
                subject_id=selection.subject_id,
                agent_definition=authority.definition,
                agent_plan=selection.plan,
                compiled_agent_profile=authority.compiled,
                skill_id=selection.skill_id,
                skill_registry=selection.skill_registry,
                skill_installations=selection.skill_installations,
                skill_runtime_policy=selection.skill_runtime_policy,
                tool_registry=binding.tool_binding.registry,
                tool_resource_policy=binding.tool_binding.resource_policy,
                tool_authorization=authority.authorization,
                tool_runtime=binding.tool_binding.tool_runtime,
                tool_arguments=_parse_tool_arguments(wire.raw_tool_arguments),
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAgentSkillAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_request",
                "Agent/Skill request fields are invalid.",
                status_code=400,
            )

        try:
            runtime = self._runtime_factory(app_id)
            result = await OrchestrationRunner(
                runtime=runtime,
                idempotency=self._idempotency_adapter,
            ).run(orch_req)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except SkillRegistryError as exc:
            # Unknown, uninstalled or disabled Skill selection is an authority
            # failure, not an internal error and never auto-activates anything.
            return _service_error(exc.code, exc.safe_message, status_code=403)
        except SkillRuntimeAdapterError as exc:
            return _service_error(
                "skill_runtime_policy_rejected",
                str(exc),
                status_code=403,
            )
        except OrchestrationError as exc:
            status_code = 403 if exc.code in {
                "authorization_denied",
                "authority_widening_rejected",
                "capability_missing",
            } else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except Exception:
            return _service_error(
                "engine_internal_error",
                "Agent/Skill orchestration failed.",
                status_code=500,
            )

        try:
            projection = project_agent_skill_result(result, selection=wire.selection)
        except (TypeError, ValueError):
            return _service_error(
                "invalid_agent_skill_result",
                "Agent/Skill execution returned an invalid public projection.",
                status_code=500,
            )
        return ServiceResponse(
            status_code=200 if result.approval_pause is None else 202,
            body={"ok": True, "agent_skill": projection},
        )

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != AGENT_SKILL_RUN_PATH:
            return _service_error(
                "not_found",
                "Internal Engine route not found.",
                status_code=404,
            )
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )
        return await self.run_payload(payload)
