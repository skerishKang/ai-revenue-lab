"""Bounded trusted Agent/Skill transport over Core orchestration (#1749 E4).

Caller identity/input parsing is isolated in ``agent_skill_wire``; server-issued
approval lifecycle is isolated in ``agent_skill_continuation_service``.  This
service remains a thin composition layer over Core OrchestrationRunner,
AgentPlanExecutor, BoundedAgentRuntime and ToolRuntime.  It creates no parallel
Agent runtime, Tool authority, approval state machine, or Provider router.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import secrets
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext, IdempotencyConflictError
from padiem_ai_core.orchestration import OrchestrationError, OrchestrationRequest, OrchestrationRunner
from padiem_ai_core.skill_registry import SkillRegistryError
from padiem_ai_core.skill_runtime_adapter import SkillRuntimeAdapterError

from app.agent_skill_authority import EngineAgentSkillAuthorityError, EngineAgentSkillBinding
from app.agent_skill_continuation_service import AgentSkillContinuationCoordinator
from app.agent_skill_projection import project_agent_skill_result
from app.agent_skill_wire import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    AGENT_SKILL_RUN_PATH,
    AUTHORITY_SHAPED_KEYS,
    TRUSTED_AGENT_SKILL_ALLOWED,
    TRUSTED_AGENT_SKILL_REQUIRED,
    TrustedAgentSkillWireRequest,
    build_trusted_agent_skill_request,
    execution_request_with_trace,
    parse_tool_arguments,
)
from app.orchestration_continuation import ContinuationStore
from app.service import MAX_REQUEST_BODY_BYTES, ServiceContractError, ServiceResponse, _service_error
from app.tool_projection import EngineToolProjectionError


class AgentSkillEngineService:
    """Thin Engine transport for trusted Core Agent/Skill execution lifecycle."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        binding_resolver: Callable[[str], EngineAgentSkillBinding | None] | None = None,
        idempotency_adapter: Any | None = None,
        approval_decision_verifier: Any | None = None,
        continuation_store: ContinuationStore | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if binding_resolver is not None and not callable(binding_resolver):
            raise ValueError("binding_resolver must be callable")
        self._runtime_factory = runtime_factory
        self._binding_resolver = binding_resolver
        self._idempotency_adapter = idempotency_adapter
        self._continuation = AgentSkillContinuationCoordinator(
            runtime_factory=runtime_factory,
            binding_resolver=self._resolve_binding,
            approval_decision_verifier=approval_decision_verifier,
            continuation_store=continuation_store,
            idempotency_adapter=idempotency_adapter,
        )

    def _resolve_binding(self, app_id: str) -> EngineAgentSkillBinding:
        if self._binding_resolver is None:
            raise EngineAgentSkillAuthorityError(
                "agent_skill_runtime_unavailable",
                "Trusted Agent/Skill runtime authority is unavailable.",
                status_code=503,
            )
        try:
            binding = self._binding_resolver(app_id)
        except EngineAgentSkillAuthorityError:
            raise
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
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        app_id = app_id.strip()

        try:
            binding = self._resolve_binding(app_id)
            wire = build_trusted_agent_skill_request(payload, binding=binding)
            execution_request = wire.execution_request
            context = wire.context
            if context is None:
                trace_id = execution_request.trace_id or f"agtr_{secrets.token_hex(12)}"
                execution_request = execution_request_with_trace(execution_request, trace_id)
                context = ExecutionContext(trace_id=trace_id)
            tool_arguments = parse_tool_arguments(wire.raw_tool_arguments)
            authority = wire.selection.authority
            request = OrchestrationRequest(
                execution_request=execution_request,
                context=context,
                app_id=app_id,
                subject_id=wire.selection.subject_id,
                agent_definition=authority.definition,
                agent_plan=wire.selection.plan,
                compiled_agent_profile=authority.compiled,
                skill_id=wire.selection.skill_id,
                skill_registry=wire.selection.skill_registry,
                skill_installations=wire.selection.skill_installations,
                skill_runtime_policy=wire.selection.skill_runtime_policy,
                tool_registry=binding.tool_binding.registry,
                tool_resource_policy=binding.tool_binding.resource_policy,
                tool_authorization=authority.authorization,
                tool_runtime=binding.tool_binding.tool_runtime,
                tool_arguments=tool_arguments,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAgentSkillAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Agent/Skill request fields are invalid.", status_code=400)

        try:
            result = await OrchestrationRunner(
                runtime=self._runtime_factory(app_id),
                idempotency=self._idempotency_adapter,
            ).run(request)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except SkillRegistryError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=403)
        except SkillRuntimeAdapterError as exc:
            return _service_error("skill_runtime_policy_rejected", str(exc), status_code=403)
        except OrchestrationError as exc:
            status_code = 403 if exc.code in {
                "authorization_denied",
                "authority_widening_rejected",
                "capability_missing",
            } else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except Exception:
            return _service_error("engine_internal_error", "Agent/Skill orchestration failed.", status_code=500)

        try:
            projection = project_agent_skill_result(result, selection=wire.selection)
            if result.approval_pause is None:
                return ServiceResponse(
                    status_code=200,
                    body={"ok": True, "agent_skill": projection},
                )
            continuation_ref = await self._continuation.issue(
                app_id=app_id,
                binding=binding,
                wire=wire,
                execution_request=execution_request,
                context=context,
                tool_arguments=tool_arguments,
                pause=result.approval_pause,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError):
            return _service_error(
                "invalid_agent_skill_result",
                "Agent/Skill execution returned an invalid public projection.",
                status_code=500,
            )
        return ServiceResponse(
            status_code=202,
            body={
                "ok": True,
                "agent_skill": projection,
                "continuation_ref": continuation_ref,
            },
        )

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        return await self._continuation.resume_payload(payload)

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        return await self._continuation.cancel_payload(payload)

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path not in {
            AGENT_SKILL_RUN_PATH,
            AGENT_SKILL_RESUME_PATH,
            AGENT_SKILL_CANCEL_PATH,
        }:
            return _service_error("not_found", "Internal Engine route not found.", status_code=404)
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
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)
        if path == AGENT_SKILL_RESUME_PATH:
            return await self.resume_payload(payload)
        if path == AGENT_SKILL_CANCEL_PATH:
            return await self.cancel_payload(payload)
        return await self.run_payload(payload)


# Compatibility re-exports retained for the E4A import surface.
__all__ = [
    "AGENT_SKILL_RUN_PATH",
    "AGENT_SKILL_RESUME_PATH",
    "AGENT_SKILL_CANCEL_PATH",
    "AUTHORITY_SHAPED_KEYS",
    "TRUSTED_AGENT_SKILL_ALLOWED",
    "TRUSTED_AGENT_SKILL_REQUIRED",
    "TrustedAgentSkillWireRequest",
    "build_trusted_agent_skill_request",
    "AgentSkillEngineService",
]
