"""#1914: B54 P01 orchestration port over the Engine-owned first-party client.

The Engine remains the orchestration authority. This module only maps a trusted
`OrchestrationRequest` (as built by `P01RequestFactory`) onto the client wire
contract and reconstructs the response through the Core-owned public parser
(`orchestration_result_from_public`). Anything the wire cannot carry losslessly
is rejected fail-closed here, before Claw can project it: a silently dropped
approval pause or plan would let a paused run be reported as completed.

Claw never pins a provider, model, fallback order, or credential through this
port; the conservative B54 agent profile is the only accepted request shape.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core import (
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationResult,
    orchestration_result_from_public,
)
from padiem_ai_engine_client import PadiemAiEngineClientError

from .p01_adapter import P01AdapterError

# The Engine client is injected structurally (any object exposing async
# ``orchestrate(request)``); production uses ``PadiemAiEngineClient``.
_ENGINE_MAX_RETRIES_DEFAULT = 3

# OrchestrationRequest fields that carry authority the public wire cannot
# round-trip losslessly. A non-default value here would be silently dropped on
# the way out or fabricated on the way back, so the port refuses the request.
_NULLABLE_AUTHORITY_FIELDS = (
    "memory_authorization",
    "memory_read_policy",
    "agent_definition",
    "agent_planner",
    "agent_plan",
    "compiled_agent_profile",
    "skill_id",
    "skill_registry",
    "skill_installations",
    "skill_runtime_policy",
    "tool_registry",
    "connector_registry",
    "tool_resource_policy",
    "tool_authorization",
    "tool_runtime",
    "tool_arguments",
    "evidence_validator",
    "verification_policy",
    "recovery_policy",
)
_EMPTY_AUTHORITY_FIELDS = (
    "memory_items",
    "evidence_sources",
    "evidence_claims",
    "evidence_links",
)


class P01EngineOrchestrationClient:
    """`P01OrchestrationPort` implementation backed by the Engine client."""

    def __init__(self, client: Any) -> None:
        if not callable(getattr(client, "orchestrate", None)):
            raise P01AdapterError(
                "invalid_engine_client",
                "Engine client must expose async orchestrate(request).",
            )
        self._client = client

    async def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        payload = self._build_payload(request)
        try:
            raw = await self._client.orchestrate(payload)
        except PadiemAiEngineClientError as exc:
            raise P01AdapterError(
                "p01_engine_request_failed",
                "P01 orchestration failed at the Engine boundary.",
            ) from exc
        try:
            result = orchestration_result_from_public(raw)
        except OrchestrationError as exc:
            raise P01AdapterError(
                exc.code,
                "P01 orchestration result carries data the public projection cannot reconstruct.",
            ) from exc
        self._validate_correlation(request, result)
        return result

    def _build_payload(self, request: OrchestrationRequest) -> dict[str, Any]:
        if not isinstance(request, OrchestrationRequest):
            raise P01AdapterError(
                "invalid_p01_request",
                "P01 port requires a canonical OrchestrationRequest.",
            )
        client_app_id = getattr(self._client, "app_id", None)
        if client_app_id is not None and client_app_id != request.app_id:
            raise P01AdapterError(
                "p01_app_id_mismatch",
                "Engine client app identity does not match the P01 request.",
            )
        self._reject_unsupported_authority(request)

        execution = request.execution_request
        agent = execution.agent
        if (
            agent.model_policy
            or agent.allowed_tools
            or agent.context_policy
            or agent.output_contract
            or agent.max_steps != 1
        ):
            raise P01AdapterError(
                "p01_authority_pinning",
                "P01 agent profile carries routing or tool authority the Engine wire cannot accept.",
            )
        payload: dict[str, Any] = {
            "agent": {
                "id": agent.id,
                "title": agent.title,
                "description": agent.description,
                "system_instruction": agent.system_instruction,
                "task_type": agent.task_type,
                "optimize_for": agent.optimize_for,
                "max_tokens": agent.max_tokens,
                "required_capabilities": list(agent.required_capabilities),
                "model_policy": {},
            },
            "messages": [dict(message) for message in execution.messages],
            "trace_id": execution.trace_id,
            "execution_context": {
                "trace_id": request.context.trace_id,
                "timeout_seconds": request.context.timeout_seconds,
            },
        }
        if execution.session_id is not None:
            payload["session_id"] = execution.session_id
        if execution.additional_system_context is not None:
            payload["additional_system_context"] = execution.additional_system_context
        return payload

    @staticmethod
    def _reject_unsupported_authority(request: OrchestrationRequest) -> None:
        if request.subject_id is not None:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not carry a subject identity.",
            )
        for name in _NULLABLE_AUTHORITY_FIELDS:
            if getattr(request, name) is not None:
                raise P01AdapterError(
                    "p01_authority_field_unsupported",
                    f"P01 requests must not carry the {name} authority field.",
                )
        for name in _EMPTY_AUTHORITY_FIELDS:
            if getattr(request, name):
                raise P01AdapterError(
                    "p01_authority_field_unsupported",
                    f"P01 requests must not carry {name} payload.",
                )
        if request.require_evidence or request.require_verification:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not require evidence or verification the projection cannot carry.",
            )
        if request.max_retries != _ENGINE_MAX_RETRIES_DEFAULT:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must keep the canonical Engine retry budget.",
            )
        if request.context.idempotency_key is not None:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not carry an idempotency key.",
            )

    @staticmethod
    def _validate_correlation(
        request: OrchestrationRequest,
        result: OrchestrationResult,
    ) -> None:
        metadata = result.execution_result.metadata
        if (
            result.app_id != request.app_id
            or result.context.trace_id != request.context.trace_id
            or metadata.trace_id != request.context.trace_id
            or metadata.app_id != request.app_id
            or metadata.agent_id != request.execution_request.agent.id
            or metadata.session_id != request.execution_request.session_id
        ):
            raise P01AdapterError(
                "p01_result_correlation_mismatch",
                "P01 orchestration result does not match the request correlation.",
            )


__all__ = ["P01EngineOrchestrationClient", "PadiemAiEngineClientError"]
