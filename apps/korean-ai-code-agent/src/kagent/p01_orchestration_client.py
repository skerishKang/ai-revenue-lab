"""#1914: B54 P01 orchestration port over the Engine-owned first-party client.

The Engine remains the orchestration authority. This module only maps a trusted
`OrchestrationRequest` (as built by `P01RequestFactory`) onto the client wire
contract and reconstructs the response through the Core-owned public parser
(`orchestration_result_from_public`). Anything the wire cannot carry losslessly
is rejected fail-closed here, before Claw can project it: a silently dropped
approval pause or plan would let a paused run be reported as completed.

Claw pins only the executable Padiem v1 product-tier routes (derived from the
shared declaration contract, #2212) through this port; any other provider,
model, fallback order, or credential fails closed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from padiem_ai_core.orchestration_events import (
    OrchestrationEvent,
    OrchestrationEventError,
    OrchestrationEventKind,
    orchestration_event_from_public,
)

from padiem_ai_core import (
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationResult,
    orchestration_result_from_public,
)
from padiem_ai_engine_client import PadiemAiEngineClientError
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)

from .p01_adapter import (
    P01AdapterError,
    P01DispatchClass,
    validate_explicit_b14_model_id,
    P01_FAILURE_DETAIL_AUTHENTICATION,
    P01_FAILURE_DETAIL_AUTHORIZATION,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_DOWNSTREAM,
    P01_FAILURE_DETAIL_ENGINE_ADMISSION,
    P01_FAILURE_DETAIL_PROVIDER_AUTHORIZATION,
    P01_FAILURE_DETAIL_PROVIDER_BAD_RESPONSE,
    P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED,
    P01_FAILURE_DETAIL_PROVIDER_REQUEST_REJECTED,
    P01_FAILURE_DETAIL_PROVIDER_SERVER_ERROR,
    P01_FAILURE_DETAIL_PROVIDER_TIMEOUT,
    P01_FAILURE_DETAIL_PROVIDER_UNAVAILABLE,
    P01_FAILURE_DETAIL_TRANSPORT,
)
from .p01_approval_pause_transport import (
    EngineApprovalPauseWireError,
    P01PausedWireResult,
    split_engine_approval_pause_wire,
)


def _padiem_executable_route_ids() -> frozenset[str]:
    """Model IDs of the executable Padiem v1 tiers, derived from the shared
    declaration contract (#2099 SOT). B14 stays the execution authority: a
    route unregistered there still fails closed at dispatch. A successor-pending Plus HOLD may make this set empty; that is an import-safe
    state and never authorizes a dispatch."""
    ids: set[str] = set()
    for label in (ProductTierLabel.PLUS, ProductTierLabel.PRO):
        try:
            route = active_route_for(label)
        except ProductTierRoutesError as exc:
            raise P01AdapterError(
                "invalid_product_tier",
                f"제품 등급 라우트 계약이 무효합니다: {exc}",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            ) from exc
        if route is not None and route.model_id is not None:
            ids.add(route.model_id)
    # Zero executable routes is a valid model-selection HOLD state (#3568).
    # Importing Claw/KAgent must remain safe so non-model features still work.
    # Actual execution fails closed earlier in P01RequestFactory/_agent_profile
    # with tier_hold before any Engine/B14/provider dispatch.
    return frozenset(ids)


# Padiem v1 executable routes are the *implicit* product-tier authority.
# #3554 adds a bounded explicit user-choice lane (max_retries=0), not an
# alternate provider catalog: B14 alone resolves/denies the exact model ID.
# All additional authority fields or implicit/auto choices remain forbidden.
PADIEM_EXECUTABLE_MODEL_IDS = _padiem_executable_route_ids()


def _registered_b14_candidate_syntax(value: object) -> bool:
    """Only syntax-check explicit user choice; B14 owns catalog resolution.

    The P01 wire admits this path only with max_retries=0 and a single model.
    A nonregistered exact ID is rejected by B14, never replaced by fallback.
    """
    try:
        validate_explicit_b14_model_id(value)
        return True
    except P01AdapterError:
        return False


# The Engine client is injected structurally (any object exposing async
# ``orchestrate(request)``); production uses ``PadiemAiEngineClient``.
_ENGINE_MAX_RETRIES_DEFAULT = 3

_ENGINE_AUTHENTICATION_CODES = frozenset(
    {"service_authentication_failed", "invalid_service_credential"}
)
_ENGINE_AUTHORIZATION_CODES = frozenset({"service_app_not_authorized"})
_ENGINE_TRANSPORT_CODES = frozenset(
    {"invalid_engine_response", "engine_http_error", "invalid_engine_transport"}
)
# Bounded Engine/B14 model-execution failure codes (#3566 evidence rule).
# The Engine's orchestrate boundary already bounds these to an enumerated
# `code`; retaining the exact class keeps the terminal evidence load-bearing
# without forwarding any message, prompt, or provider payload.
_ENGINE_PROVIDER_SERVER_ERROR_CODES = frozenset({"upstream_server_error"})
_ENGINE_PROVIDER_TIMEOUT_CODES = frozenset({"upstream_timeout"})
_ENGINE_PROVIDER_RATE_LIMITED_CODES = frozenset({"upstream_rate_limited"})
_ENGINE_PROVIDER_UNAVAILABLE_CODES = frozenset({"upstream_unavailable"})
_ENGINE_PROVIDER_AUTHORIZATION_CODES = frozenset({"upstream_auth_error"})
_ENGINE_PROVIDER_REQUEST_REJECTED_CODES = frozenset({"upstream_request_error"})
_ENGINE_PROVIDER_BAD_RESPONSE_CODES = frozenset(
    {"malformed_upstream", "empty_upstream_answer", "upstream_response_too_large"}
)
# Engine trusted-admission denial codes (#3655 canary evidence rule). These
# are the enumerated fail-closed codes raised by the Engine's admission gate
# (apps/padiem-ai-engine/app/execution_admission.py); retaining the admission
# class lets the final canary record ENGINE_ADMISSION_RESULT=DENIED instead
# of collapsing it into the downstream bucket.
_ENGINE_ADMISSION_CODES = frozenset(
    {
        "missing_entitlement",
        "entitlement_denied",
        "entitlement_expired",
        "entitlement_app_mismatch",
        "entitlement_subject_mismatch",
        "invalid_admission",
        "invalid_admission_request",
    }
)


def _engine_failure_detail(code: object) -> str:
    if code in _ENGINE_AUTHENTICATION_CODES:
        return P01_FAILURE_DETAIL_AUTHENTICATION
    if code in _ENGINE_AUTHORIZATION_CODES:
        return P01_FAILURE_DETAIL_AUTHORIZATION
    if code in _ENGINE_TRANSPORT_CODES:
        return P01_FAILURE_DETAIL_TRANSPORT
    if code in _ENGINE_ADMISSION_CODES:
        return P01_FAILURE_DETAIL_ENGINE_ADMISSION
    if code in _ENGINE_PROVIDER_SERVER_ERROR_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_SERVER_ERROR
    if code in _ENGINE_PROVIDER_TIMEOUT_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_TIMEOUT
    if code in _ENGINE_PROVIDER_RATE_LIMITED_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED
    if code in _ENGINE_PROVIDER_UNAVAILABLE_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_UNAVAILABLE
    if code in _ENGINE_PROVIDER_AUTHORIZATION_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_AUTHORIZATION
    if code in _ENGINE_PROVIDER_REQUEST_REJECTED_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_REQUEST_REJECTED
    if code in _ENGINE_PROVIDER_BAD_RESPONSE_CODES:
        return P01_FAILURE_DETAIL_PROVIDER_BAD_RESPONSE
    return P01_FAILURE_DETAIL_DOWNSTREAM

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

    def __init__(self, client: Any, *, allow_subject_identity: bool = False) -> None:
        if not callable(getattr(client, "orchestrate", None)):
            raise P01AdapterError(
                "invalid_engine_client",
                "Engine client must expose async orchestrate(request).",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if not isinstance(allow_subject_identity, bool):
            raise P01AdapterError(
                "invalid_subject_lane",
                "P01 subject identity lane must be a boolean.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        self._client = client
        # #3382: the reviewed canonical USER lane relaxes the blanket subject
        # rejection for a bounded canonical subject only; the default lane
        # keeps rejecting subject identity exactly as before.
        self._allow_subject_identity = allow_subject_identity

    def enable_subject_identity(self, allowed: bool) -> None:
        if not isinstance(allowed, bool):
            raise P01AdapterError(
                "invalid_subject_lane",
                "P01 subject identity lane must be a boolean.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        self._allow_subject_identity = allowed

    async def run(
        self, request: OrchestrationRequest
    ) -> OrchestrationResult | P01PausedWireResult:
        payload = self._build_payload(request)
        try:
            raw = await self._client.orchestrate(payload)
        except PadiemAiEngineClientError as exc:
            # The Engine call was attempted; the provider-side state is ambiguous.
            # Conservative UNKNOWN: never refundable under the #830 invariant.
            raise P01AdapterError(
                "p01_engine_request_failed",
                "P01 orchestration failed at the Engine boundary.",
                dispatch_class=P01DispatchClass.UNKNOWN,
                failure_detail=_engine_failure_detail(exc.code),
            ) from exc
        try:
            # #2946: Engine approval-pause keys are projected out here so the
            # generic Core public parser can reconstruct the result unchanged.
            # The parser itself stays fail-closed and is never weakened.
            core_payload, approval_pause_wire = split_engine_approval_pause_wire(raw)
        except EngineApprovalPauseWireError as exc:
            raise P01AdapterError(
                exc.code,
                "P01 orchestration result carries an unusable Engine approval-pause wire.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from exc
        try:
            result = orchestration_result_from_public(core_payload)
        except OrchestrationError as exc:
            # A wire response was received, so execution was dispatched.
            raise P01AdapterError(
                exc.code,
                "P01 orchestration result carries data the public projection cannot reconstruct.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            ) from exc
        self._validate_correlation(request, result)
        if approval_pause_wire is not None:
            return P01PausedWireResult(result=result, wire=approval_pause_wire)
        return result


    async def run_stream(
        self,
        request: OrchestrationRequest,
        *,
        on_event: Callable[[OrchestrationEvent], Awaitable[None]] | None = None,
    ) -> OrchestrationResult | P01PausedWireResult:
        """Opt-in, canonical P01 Engine event consumer (#3930).

        Only intermediate events may reach an observer before completion. A
        terminal event is withheld until the Engine's EOF-validated result,
        Core reconstruction and full event-sequence equivalence all succeed.
        This method does not activate streaming in the existing run() lane.
        """
        payload = self._build_payload(request)
        stream_method = getattr(self._client, "stream_orchestration", None)
        if not callable(stream_method):
            raise P01AdapterError(
                "p01_engine_stream_unavailable",
                "Engine streaming is not configured for this P01 client.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        stream_events: list[OrchestrationEvent] = []
        stream_run_id: str | None = None
        terminal_raw: dict[str, Any] | None = None
        terminal_kinds = frozenset({
            OrchestrationEventKind.RUN_COMPLETED,
            OrchestrationEventKind.RUN_FAILED,
            OrchestrationEventKind.RUN_CANCELLED,
            OrchestrationEventKind.APPROVAL_PAUSED,
        })

        def fail(code: str) -> P01AdapterError:
            return P01AdapterError(
                code,
                "Engine streaming lifecycle did not match canonical P01 evidence.",
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )

        try:
            async for record in stream_method(payload):
                if not isinstance(record, dict) or len(record) != 1:
                    raise fail("p01_stream_invalid_record")
                if "event" in record and terminal_raw is None:
                    try:
                        event = orchestration_event_from_public(record["event"])
                    except (OrchestrationEventError, ValueError, TypeError) as exc:
                        raise fail("p01_stream_invalid_event") from exc
                    if len(stream_events) >= 128:
                        raise fail("p01_stream_event_budget")
                    if not stream_events:
                        if event.sequence != 1 or event.kind is not OrchestrationEventKind.RUN_STARTED:
                            raise fail("p01_stream_missing_start")
                        stream_run_id = event.run_id
                    else:
                        prior = stream_events[-1]
                        if (
                            event.sequence != prior.sequence + 1
                            or any(event.event_id == e.event_id for e in stream_events)
                            or prior.kind in terminal_kinds
                        ):
                            raise fail("p01_stream_sequence_violation")
                    if (
                        event.run_id != stream_run_id
                        or event.app_id != request.app_id
                        or event.trace_id != request.context.trace_id
                    ):
                        raise fail("p01_stream_correlation_mismatch")
                    stream_events.append(event)
                    if on_event is not None and event.kind not in terminal_kinds:
                        await on_event(event)
                elif "orchestration" in record and terminal_raw is None:
                    if not stream_events or stream_events[-1].kind not in terminal_kinds:
                        raise fail("p01_stream_missing_terminal_event")
                    if not isinstance(record["orchestration"], dict):
                        raise fail("p01_stream_invalid_result")
                    terminal_raw = record["orchestration"]
                else:
                    raise fail("p01_stream_trailing_record")
        except P01AdapterError:
            raise
        except PadiemAiEngineClientError as exc:
            # An Engine request that reached its transport is UNKNOWN,
            # never refunded or automatically retried after a partial stream.
            raise P01AdapterError(
                "p01_engine_stream_failed",
                "Engine streaming failed before a verified terminal result.",
                dispatch_class=P01DispatchClass.UNKNOWN,
                failure_detail=_engine_failure_detail(exc.code),
            ) from exc
        except Exception as exc:
            raise P01AdapterError(
                "p01_engine_stream_failed",
                "Engine streaming ended without safe P01 verification.",
                dispatch_class=P01DispatchClass.UNKNOWN,
                failure_detail=P01_FAILURE_DETAIL_TRANSPORT,
            ) from exc

        if terminal_raw is None:
            raise fail("p01_stream_missing_result")
        try:
            core_payload, approval_pause_wire = split_engine_approval_pause_wire(terminal_raw)
            result = orchestration_result_from_public(core_payload)
        except (EngineApprovalPauseWireError, OrchestrationError) as exc:
            raise fail("p01_stream_invalid_result") from exc
        self._validate_correlation(request, result)
        if (
            len(result.events) != len(stream_events)
            or any(actual.to_public_dict() != streamed.to_public_dict()
                   for actual, streamed in zip(result.events, stream_events))
        ):
            raise fail("p01_stream_event_result_mismatch")
        if on_event is not None:
            await on_event(stream_events[-1])
        if approval_pause_wire is not None:
            return P01PausedWireResult(result=result, wire=approval_pause_wire)
        return result

    def _build_payload(self, request: OrchestrationRequest) -> dict[str, Any]:
        if not isinstance(request, OrchestrationRequest):
            raise P01AdapterError(
                "invalid_p01_request",
                "P01 port requires a canonical OrchestrationRequest.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        client_app_id = getattr(self._client, "app_id", None)
        if client_app_id is not None and client_app_id != request.app_id:
            raise P01AdapterError(
                "p01_app_id_mismatch",
                "Engine client app identity does not match the P01 request.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        self._reject_unsupported_authority(request)

        execution = request.execution_request
        agent = execution.agent
        model_policy = dict(agent.model_policy)
        model_retries = model_policy.get("max_retries")
        # #3382/#3566: the only extra model_policy authority the P01 wire
        # accepts is the single-dispatch retry budget `max_retries=0` (the
        # Claw one-shot canary contract: PROVIDER_CALL_COUNT_MAX=1, RETRY=0).
        # Any other retry budget is authority widening and fails closed.
        valid_model_policy = (
            not model_policy
            or (
                set(model_policy) == {"model"}
                and model_policy["model"] in PADIEM_EXECUTABLE_MODEL_IDS
            )
            or (
                set(model_policy) == {"model", "max_retries"}
                and (
                    model_policy["model"] in PADIEM_EXECUTABLE_MODEL_IDS
                    or _registered_b14_candidate_syntax(model_policy["model"])
                )
                and isinstance(model_retries, int)
                and not isinstance(model_retries, bool)
                and model_retries == 0
            )
        )
        if (
            not valid_model_policy
            or agent.allowed_tools
            or agent.context_policy
            or agent.output_contract
            or agent.max_steps != 1
        ):
            raise P01AdapterError(
                "p01_authority_pinning",
                "P01 agent profile carries routing or tool authority the Engine wire cannot accept.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
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
                "model_policy": model_policy,
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
        # #3382: the canonical USER lane carries the server-resolved subject on
        # the Engine wire. The Engine's own admission contract validates the
        # subject shape and revalidates it against Control Plane Identity.
        if request.subject_id is not None:
            payload["subject_id"] = request.subject_id
        return payload

    def _reject_unsupported_authority(self, request: OrchestrationRequest) -> None:
        if request.subject_id is not None and not self._allow_subject_identity:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not carry a subject identity.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if request.subject_id is not None:
            # #3382: reuse the shared canonical subject validator from
            # p01_adapter.py — the same grammar the factory uses, so a subject
            # that bypasses the factory still fails closed on shape.
            from kagent.p01_adapter import validate_canonical_subject_id

            validate_canonical_subject_id(request.subject_id)
        for name in _NULLABLE_AUTHORITY_FIELDS:
            if getattr(request, name) is not None:
                raise P01AdapterError(
                    "p01_authority_field_unsupported",
                    f"P01 requests must not carry the {name} authority field.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )
        for name in _EMPTY_AUTHORITY_FIELDS:
            if getattr(request, name):
                raise P01AdapterError(
                    "p01_authority_field_unsupported",
                    f"P01 requests must not carry {name} payload.",
                    dispatch_class=P01DispatchClass.NOT_DISPATCHED,
                )
        if request.require_evidence or request.require_verification:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not require evidence or verification the projection cannot carry.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if request.max_retries != _ENGINE_MAX_RETRIES_DEFAULT:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must keep the canonical Engine retry budget.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        if request.context.idempotency_key is not None:
            raise P01AdapterError(
                "p01_authority_field_unsupported",
                "P01 requests must not carry an idempotency key.",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
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
                dispatch_class=P01DispatchClass.DISPATCHED,
                failure_detail=P01_FAILURE_DETAIL_CONTRACT,
            )


__all__ = ["P01EngineOrchestrationClient", "PadiemAiEngineClientError"]
