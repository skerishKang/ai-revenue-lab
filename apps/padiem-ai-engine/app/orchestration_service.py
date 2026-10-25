"""Language-neutral unified orchestration service contract for Padiem AI Engine.

Exposes bounded, product-neutral orchestration execution, approval continuation
resumption, and cancellation over the internal Engine transport.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import inspect
import json
import re
import secrets
from typing import Any, Awaitable, Protocol

from padiem_ai_core import (
    AgentPlan,
    AgentPlanStep,
    AgentPlannerError,
    AgentProfile,
    AgentRecoveryPolicy,
    AgentRecoveryError,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    BoundedAgentDefinition,
    CompiledAgentProfile,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    OrchestrationError,
    OrchestrationEvent,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationResumeRequest,
    OrchestrationRunner,
    ToolAuthorizationContext,
    VerifiedApprovalDecision,
    request_fingerprint,
)
from padiem_ai_core.agent_approval import tool_invocation_digest
from padiem_ai_core.contracts import ErrorClass
from padiem_ai_core.execution_runtime import ExecutionRuntimeError
from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.tool_runtime import ToolInvocation

from app.execution_context_wire import parse_execution_context
from app.hark_office_p01_receipt import (
    ApprovedOfficeReadReceiptSink,
    prepare_approved_office_read_receipt,
)
from app.tool_projection import (
    EngineToolBinding,
    EngineToolProjectionError,
    json_size,
)
from app.service import (
    MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _require_exact_object,
    _service_error,
    build_execution_request,
)

from app.orchestration_continuation import (
    ContinuationRecord,
    ContinuationStore,
    InMemoryContinuationStore,
)

# #5015: the only plan agents whose tool arguments carry a PC execution target.
# The target is a closed property: no other argument may ride along.
_PC_PLAN_AGENT_IDS = frozenset({
    "agent:padiem:claw-pc-query@1",
    "agent:padiem:chat-pc-query@1",
})

# S13-5 Phase 1: the orchestrate route mirrors the AGENT-SKILL continuation
# lifecycle plane by reusing the S13-4 projection rather than re-deriving it.
from app.agent_skill_continuation_projection import (
    ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
    project_agent_lifecycle_events,
)

# Compatibility surface: the wire contract moved to app.orchestration_wire
# in #1792 R2B-2; these re-exports preserve every existing import site.
from app.orchestration_wire import (  # noqa: E402
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATION_STREAM_PATH,
    _SAFE_ID_RE,
    _IDENTIFIER_RE,
    _AGENT_ID_RE,
    _MAX_ORCHESTRATION_RETRIES,
    _MAX_AGENT_STEP_RETRIES,
    _MAX_CANCEL_REASON_LEN,
    _EXEC_FIELDS,
    _ORCHESTRATION_OPTIONS,
    _ORCHESTRATION_RESUME_OPTIONS,
    _ORCHESTRATE_ALLOWED,
    _RESUME_ALLOWED,
    _CANCEL_ALLOWED,
    _AGENT_PLAN_ALLOWED,
    _PLAN_STEP_ALLOWED,
    _RECOVERY_ALLOWED,
    ApprovalDecisionSubmission,
    _parse_max_retries,
    _parse_max_retries_per_step,
    _parse_subject_id,
    _require_strict_bool,
    _parse_retryable_driver_codes,
    _parse_plan_step,
    _parse_agent_plan,
    _parse_recovery_policy,
    _parse_cancel_reason,
    _parse_orchestration_options,
    _parse_required_timestamp,
    _required_text,
    _parse_approval_decision_submission,
    _parse_continuation_ref,
)

def _server_generated_trace_id() -> str:
    """Return a bounded opaque trace ID for a new logical orchestration run."""
    return f"tr_{secrets.token_urlsafe(24)}"


def _orchestration_lifecycle_block(
    *,
    record: ContinuationRecord | None,
    transition: str,
    events: Sequence[Any],
) -> dict[str, Any] | None:
    """S13-5 Phase 1: additive continuation lifecycle block for the orchestrate route.

    The AGENT-SKILL route publishes the continuation lifecycle plane from
    ``app.agent_skill_continuation_projection``.  The orchestrate route names the
    same facts here by reusing that projection, so both routes speak one lifecycle
    contract.  Nothing is re-derived: the event kinds, their ordering and their
    ids all come from the shared projection.

    ``task_id``/``trace_id`` follow the rule documented on
    ``project_agent_continuation_result``: the paused run identity when the record
    carries it, otherwise the first public run event.  When there is no continuation
    record there is no lifecycle to name, so the caller must omit the block entirely
    -- the Engine never invents events, ids, timestamps or state.
    """

    if record is None:
        return None
    public_events = [event.to_public_dict() for event in events]
    task_id = record.pause.run_id or (
        public_events[0].get("run_id") if public_events else None
    )
    trace_id = record.pause.trace_id or (
        public_events[0].get("trace_id") if public_events else None
    )
    return {
        "continuation_id": record.continuation_ref,
        # S13-5 Phase 1: internal consumption only.  The additive sibling key is
        # the whole compatibility surface; see docs/operations/AGENT_CONTINUATION_CONTRACT.md.
        "lifecycle_contract_version": ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
        "lifecycle_events": project_agent_lifecycle_events(
            continuation_id=record.continuation_ref,
            transition=transition,
            task_id=task_id,
            trace_id=trace_id,
            events=events,
        ),
    }


def _execution_request_with_trace(request: ExecutionRequest, trace_id: str) -> ExecutionRequest:
    """Copy an ExecutionRequest while binding a server-selected trace_id."""
    return ExecutionRequest(
        agent=request.agent,
        messages=request.messages,
        session_id=request.session_id,
        additional_system_context=request.additional_system_context,
        trace_id=trace_id,
    )


class ApprovalDecisionVerifier(Protocol):
    """Trusted adapter that authenticates a product/control-plane decision."""

    def verify(
        self,
        submission: "ApprovalDecisionSubmission",
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision | Awaitable[VerifiedApprovalDecision]: ...


_DEFAULT_CONTINUATION_STORE = InMemoryContinuationStore()


def bind_verified_approval_to_tool_authorization(
    authorization: ToolAuthorizationContext,
    *,
    pause: ApprovalPause,
    decision: VerifiedApprovalDecision,
) -> ToolAuthorizationContext:
    """Apply only the exact verified pause delta to server-owned Tool authority.

    Core intentionally resolves continuation lifecycle without minting Tool
    authorization.  The Engine is the trusted boundary that already owns the
    base ToolAuthorizationContext, so it may narrow-copy that context after a
    verified APPROVED decision.  Caller JSON never contributes any authority
    list or scope here.
    """
    if not isinstance(authorization, ToolAuthorizationContext):
        raise ServiceContractError(
            "invalid_verified_decision",
            "Trusted tool authorization is invalid.",
            status_code=422,
        )
    if not isinstance(pause, ApprovalPause) or not isinstance(
        decision, VerifiedApprovalDecision
    ):
        raise ServiceContractError(
            "invalid_verified_decision",
            "Verified approval context is invalid.",
            status_code=422,
        )
    if decision.pause_id != pause.pause_id:
        raise ServiceContractError(
            "approval_decision_mismatch",
            "Verified approval decision does not match the paused continuation.",
            status_code=409,
        )
    if decision.outcome is not ApprovalOutcome.APPROVED:
        return authorization

    confirmed = authorization.user_confirmed_tools
    external = authorization.externally_authorized_tools
    if pause.requirement is ApprovalRequirement.USER_CONFIRMATION:
        confirmed = tuple(dict.fromkeys((*confirmed, pause.tool_id)))
    elif pause.requirement is ApprovalRequirement.EXTERNAL_AUTHORIZATION:
        external = tuple(dict.fromkeys((*external, pause.tool_id)))
    else:
        raise ServiceContractError(
            "invalid_verified_decision",
            "Approval pause requirement is unsupported.",
            status_code=422,
        )

    return ToolAuthorizationContext(
        app_id=authorization.app_id,
        agent_id=authorization.agent_id,
        granted_auth_scopes=authorization.granted_auth_scopes,
        user_confirmed_tools=confirmed,
        externally_authorized_tools=external,
    )


# ---------------------------------------------------------------------------
# Orchestration NDJSON stream (#1962)
# ---------------------------------------------------------------------------
ORCHESTRATION_NDJSON_CONTENT_TYPE = "application/x-ndjson; charset=utf-8"


@dataclass(frozen=True, slots=True)
class PreparedOrchestrationStream:
    """A primed orchestration run whose lifecycle events stream as NDJSON.

    Mirrors ``PreparedStream`` in ``app.streaming_service``: all wire
    validation happens before HTTP 200 commits and the first lifecycle event
    (or an immediate run failure) is resolved during preparation.
    """

    first_event: OrchestrationEvent
    queue: asyncio.Queue[OrchestrationEvent]
    task: asyncio.Task[OrchestrationResult]
    app_id: str
    request_fingerprint_value: str | None = None
    pc_progress: bool = False
    pc_turn: bool = False


PC_STREAM_HEARTBEAT_SECONDS = 10.0


def _encode_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _stream_event_line(event: OrchestrationEvent | dict[str, Any]) -> str:
    if isinstance(event, dict) and set(event) in ({"pc_progress"}, {"text_delta"}):
        return _encode_line({"ok": True, **event})
    return _encode_line({"ok": True, "event": event.to_public_dict()})


def _stream_result_line(orchestration_body: dict[str, Any]) -> str:
    return _encode_line({"ok": True, "orchestration": orchestration_body})


def _stream_error_line(response: ServiceResponse) -> str:
    return _encode_line(dict(response.body))


def _execution_request_fingerprint(*, app_id: str, request: ExecutionRequest) -> str:
    return request_fingerprint(
        {
            "app_id": app_id,
            "agent_id": request.agent.id,
            "messages": [message for message in request.messages],
        }
    )


# ---------------------------------------------------------------------------
# B14 (model-service) execution failure mapping (#1932, Slice C)
# ---------------------------------------------------------------------------
# Core delivers B14 model-execution failures as ExecutionRuntimeError. These
# must surface to callers as 4xx model-level errors (preserving the safe code
# and retryable flag) instead of being swallowed by the generic
# engine_internal_error 500 path. Genuine engine-internal failures
# (ErrorClass.INTERNAL_ERROR with non-upstream codes such as
# execution_failed / invalid_execution_result) stay 500 so real engine faults
# remain visible. No upstream response body is forwarded: only the safe code,
# status, and message are emitted.

_B14_MODEL_ERROR_CLASSES = frozenset(
    {
        ErrorClass.PROVIDER_TIMEOUT,
        ErrorClass.PROVIDER_RATE_LIMIT,
        ErrorClass.AUTH_ERROR,
        ErrorClass.PROVIDER_BAD_RESPONSE,
        ErrorClass.INPUT_ERROR,
    }
)

# Fail-closed public message for every B14/model-execution failure. The Engine
# public boundary never forwards an ExecutionRuntimeError.safe_message verbatim:
# even though the ordinary Core B14 transport already canonicalizes the upstream
# detail via _safe_message_for_b14(code), the mapper must not trust an arbitrary
# internal safe_message string. One stable bounded message is emitted for all
# B14/model failures; the safe code, status, and retryable carry the class.
_B14_MODEL_ERROR_PUBLIC_MESSAGE = "Model execution failed."


def _is_b14_model_error(exc: ExecutionRuntimeError) -> bool:
    """True when exc is a B14/model-service execution failure (not engine-internal)."""
    if exc.metadata.error_class in _B14_MODEL_ERROR_CLASSES:
        return True
    # 5xx upstream (upstream_server_error / upstream_unavailable) is mapped to
    # ErrorClass.INTERNAL_ERROR by Core but is still a B14-origin model failure.
    return exc.code.startswith("upstream_")


def _b14_model_error_status(exc: ExecutionRuntimeError) -> int:
    """Map a B14 model-execution failure to a 4xx model-level status code."""
    error_class = exc.metadata.error_class
    if error_class == ErrorClass.PROVIDER_RATE_LIMIT:
        return 429
    if error_class == ErrorClass.AUTH_ERROR:
        return 403
    if error_class == ErrorClass.PROVIDER_TIMEOUT:
        return 429
    if error_class == ErrorClass.PROVIDER_BAD_RESPONSE:
        return 422
    if error_class == ErrorClass.INPUT_ERROR:
        return 400
    # INTERNAL_ERROR bucket reached via the upstream_ prefix (5xx upstream).
    return 429


_PC_QUERY_STREAM_AGENT_IDS = frozenset({
    "agent:padiem:claw-pc-query@1",
    "agent:padiem:chat-pc-query@1",
})
_PC_QUERY_STREAM_APP_IDS = frozenset({"b54-padiem-claw", "padiem-chat"})

# #5015: the PC execution target is a wire field only for one exact product
# app/agent pair and one of the canonical PC plan shapes. Every other
# payload keeps tool_arguments an unsupported field.
_PC_QUERY_APP_AGENT_PAIRS = {
    "b54-padiem-claw": "agent:padiem:claw-pc-query@1",
    "padiem-chat": "agent:padiem:chat-pc-query@1",
}
_PC_QUERY_PLAN_SHAPES = (
    (("query_drives", "claw.pc.query_drives"),),
    (("list_files", "claw.pc.list_files"),),
    (("list_files", "claw.pc.list_files"), ("read_file", "claw.pc.read_file")),
)


def _pc_query_plan_pair(app_id: Any, plan: Any) -> bool:
    """True only when the presenting product owns the PC agent in the plan."""
    expected = (
        _PC_QUERY_APP_AGENT_PAIRS.get(app_id) if isinstance(app_id, str) else None
    )
    return expected is not None and getattr(plan, "agent_id", None) == expected


def _canonical_pc_plan(app_id: Any, plan: Any) -> AgentPlan | None:
    """The canonical PC plan of one product identity, or None.

    The product/agent pair and the exact canonical step shape are both
    required, so a caller can never declare itself PC-eligible.

    The selected-PC hint is deliberately not part of this test. The trusted PC
    tool authority belongs to the canonical plan, not to the presence of one
    optional wire field: the product adapters also send the canonical PC plan
    without a hint when the owner has no explicit selection and the Broker
    resolves the pinned target from the owner scope. The plan decides whether
    the PC tool authority applies; the hint only names the target.
    """
    if plan is None or not _pc_query_plan_pair(app_id, plan):
        return None
    shape = tuple(
        (step.step_id, getattr(step, "tool_id", None)) for step in plan.steps
    )
    return plan if shape in _PC_QUERY_PLAN_SHAPES else None


def _pc_tool_arguments_gate(payload: Any) -> AgentPlan | None:
    """Return the PC plan that may carry ``tool_arguments``, or None.

    The condition is derived from the payload itself — product pair plus exact
    canonical plan shape — so a caller can never declare itself PC-eligible. A
    plan that fails to parse is not gated; its real contract error still
    surfaces from the shared parser in the service body.
    """
    if not isinstance(payload, Mapping) or "tool_arguments" not in payload:
        return None
    try:
        plan = _parse_agent_plan(payload.get("agent_plan"))
    except (TypeError, ValueError):
        return None
    return _canonical_pc_plan(payload.get("app_id"), plan)


def _validated_pc_declared_plan(payload: Any) -> str | None:
    """An optional request interpretation, never server authority."""
    if not isinstance(payload, Mapping) or "declared_plan" not in payload:
        return None
    declared = payload["declared_plan"]
    if not isinstance(declared, str) or declared not in {"files_list", "files", "query_drives"}:
        raise ServiceContractError(
            "invalid_plan", "declared_plan must name a supported PC request scope.", status_code=422,
        )
    plan = _parse_agent_plan(payload.get("agent_plan"))
    if _canonical_pc_plan(payload.get("app_id"), plan) is None:
        raise ServiceContractError(
            "invalid_plan", "declared_plan requires a canonical product PC plan.", status_code=422,
        )
    return declared


def _validated_pc_tool_arguments(
    payload: Any,
) -> dict[str, dict[str, Any]] | None:
    """Parse and validate the closed PC target for a gated payload.

    Returns None for a payload that is not a PC run; raises the existing
    ``invalid_tool_arguments`` contract error for a gated payload whose target
    is malformed, so no second, laxer parser can accept a different device.
    """
    plan = _pc_tool_arguments_gate(payload)
    if plan is None:
        return None
    parsed = OrchestrationEngineService._parse_tool_arguments(
        payload.get("tool_arguments")
    )
    OrchestrationEngineService._validate_pc_plan_tool_arguments(plan, parsed)
    return parsed


def _pc_query_selected_device(tool_arguments: Any) -> str | None:
    """The server-provided device hint for the PC tool plan, never model text."""
    if not isinstance(tool_arguments, dict):
        return None
    for target_key in ("query_drives", "files", "files_list"):
        if set(tool_arguments) != {target_key}:
            continue
        target = tool_arguments.get(target_key)
        if not isinstance(target, dict) or set(target) != {"device_id"}:
            return None
        device = target.get("device_id")
        if is_pc_device_id(device):
            return device
    return None


def _pc_query_stream_owner(app_id: str, request: Any) -> tuple[str, str, str, str | None] | None:
    """Trusted owner binding for the streaming PC tool driver (#5015).

    Only the exact canonical PC-query plan under its own product identity may
    carry an owner. Every other stream keeps the context unset, exactly as the
    non-stream admission lane leaves it for non-PC-query work.
    """
    plan = getattr(request, "agent_plan", None)
    subject_id = getattr(request, "subject_id", None)
    session_id = getattr(getattr(request, "execution_request", None), "session_id", None)
    if (
        app_id not in _PC_QUERY_STREAM_APP_IDS
        or not isinstance(subject_id, str)
        or not subject_id
        or not isinstance(session_id, str)
        or not session_id
        or plan is None
        or getattr(plan, "agent_id", None) not in _PC_QUERY_STREAM_AGENT_IDS
    ):
        return None
    return (
        subject_id, session_id, app_id,
        _pc_query_selected_device(getattr(request, "tool_arguments", None)),
    )


class OrchestrationEngineService:
    """Pure-Python internal request handler for Unified Orchestration Pipeline."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        b14_service_bound: bool,
        idempotency_adapter: Any | None = None,
        approval_decision_verifier: ApprovalDecisionVerifier | None = None,
        continuation_store: ContinuationStore | None = None,
        tool_binding_resolver: Callable[[str], EngineToolBinding | None] | None = None,
        approved_office_read_sink: ApprovedOfficeReadReceiptSink | None = None,
        desktop_step_driver_factory: Callable[[str], Any] | None = None,
        pc_query_step_driver_factory: Callable[[str], Any] | None = None,
        pc_streaming_runtime_factory: Any | None = None,
        pc_tools_capability: Any | None = None,
        tool_result_ledger_factory: Callable[[str, str | None], Any] | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if tool_binding_resolver is not None and not callable(tool_binding_resolver):
            raise ValueError("tool_binding_resolver must be callable")
        if approved_office_read_sink is not None and not callable(
            getattr(approved_office_read_sink, "record_verified_office_read", None)
        ):
            raise ValueError("approved_office_read_sink must provide record_verified_office_read")
        if approval_decision_verifier is not None and not callable(getattr(approval_decision_verifier, "verify", None)):
            raise ValueError("approval_decision_verifier must provide verify()")
        if tool_result_ledger_factory is not None and not callable(tool_result_ledger_factory):
            raise ValueError("tool_result_ledger_factory must be callable")
        if continuation_store is not None:
            for method in ("issue", "resolve", "claim", "commit", "release", "cancel"):
                if not callable(getattr(continuation_store, method, None)):
                    raise ValueError(f"continuation_store must provide {method}()")
            # Atomic cancel capability is optional for backward compatibility;
            # remember whether the store supports the claim/commit/release_cancel lifecycle
            # so cancel_payload can fail fast with a deterministic 503 instead of
            # AttributeError -> continuation_store_unavailable at call time.
            self._continuation_store_supports_atomic_cancel = all(
                callable(getattr(continuation_store, m, None))
                for m in ("claim_cancel", "commit_cancel", "release_cancel")
            )
        else:
            # Default in-memory store always supports atomic cancel
            self._continuation_store_supports_atomic_cancel = True
        self._runtime_factory = runtime_factory
        self._pc_streaming_runtime_factory = pc_streaming_runtime_factory
        self._pc_tools_capability = pc_tools_capability
        # #4379: the durable ledger owns the tool payloads. The runtime keeps
        # only references, so a long run does not retain every tool output in
        # the Worker.
        self._tool_result_ledger_factory = tool_result_ledger_factory
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter
        self._approval_decision_verifier = approval_decision_verifier
        self._continuation_store = continuation_store or _DEFAULT_CONTINUATION_STORE
        self._continuation_store_is_explicit = continuation_store is not None
        self._tool_binding_resolver = tool_binding_resolver
        self._desktop_step_driver_factory = desktop_step_driver_factory
        self._pc_query_step_driver_factory = pc_query_step_driver_factory
        # Never composed by the shipping Engine Worker unless an explicitly
        # trusted private durable sink is provided. No browser-facing endpoint.
        self._approved_office_read_sink = approved_office_read_sink

    # ------------------------------------------------------------------
    # Trusted tool-runtime attachment (#1746)
    # ------------------------------------------------------------------

    def _runtime_for_payload(self, app_id, payload):
        runtime = self._runtime_factory(app_id)
        if "pc_tools" not in payload:
            return runtime
        from app.pc_tools_turn import PcToolsTurnRuntime
        return PcToolsTurnRuntime(self, payload, runtime)

    def _resolve_tool_binding(self, app_id: str) -> EngineToolBinding | None:
        """Look up the server-provisioned binding; callers never supply one."""
        if self._tool_binding_resolver is None:
            return None
        try:
            binding = self._tool_binding_resolver(app_id)
        except Exception as exc:
            raise EngineToolProjectionError(
                "tool_runtime_unavailable",
                "The Engine Tool runtime binding resolver failed.",
                status_code=503,
            ) from exc
        if binding is None:
            return None
        if binding.app_id != app_id:
            raise EngineToolProjectionError(
                "tool_runtime_unavailable",
                "The Engine Tool runtime binding does not match this application.",
                status_code=503,
            )
        return binding

    @staticmethod
    def _parse_tool_arguments(value: Any) -> dict[str, dict[str, Any]]:
        """Parse untrusted per-step argument data; it never carries authority."""
        if value is None:
            return {}
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Mapping):
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments must be an object keyed by plan step id.",
            )
        if len(value) > 64:
            raise ServiceContractError(
                "invalid_tool_arguments",
                "tool_arguments contains too many entries.",
            )
        parsed: dict[str, dict[str, Any]] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _IDENTIFIER_RE.fullmatch(key):
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
                json_size(arguments)
            except EngineToolProjectionError:
                raise ServiceContractError(
                    "invalid_tool_arguments",
                    "tool_arguments must contain JSON-compatible values only.",
                ) from None
            # #4379: the orchestration wire carries no PADIEM byte total for
            # tool arguments. The JSON shape and the step identifier rules stay.
            parsed[key] = arguments
        return parsed

    @staticmethod
    def _validate_pc_plan_tool_arguments(
        plan: AgentPlan, parsed: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """A PC plan may carry exactly one closed property: ``device_id``.

        Anything else is refused instead of being silently dropped, so a
        caller can never widen the tool arguments or make the Engine execute
        on a target the answer context did not name.
        """
        if plan.agent_id not in _PC_PLAN_AGENT_IDS:
            return
        step_ids = {step.step_id for step in plan.steps}
        shape = tuple(
            (step.step_id, getattr(step, "tool_id", None))
            for step in plan.steps
        )
        if shape == (("list_files", "claw.pc.list_files"),):
            step_ids = {"files_list"}
        elif shape == (
            ("list_files", "claw.pc.list_files"),
            ("read_file", "claw.pc.read_file"),
        ):
            # One shared target binds the whole model-selected list/read loop.
            # It is metadata, not a third executable plan step.
            step_ids = {"files"}
        for step_id, entry in parsed.items():
            if (
                step_id not in step_ids
                or not isinstance(entry, Mapping)
                or set(entry) != {"device_id"}
            ):
                raise ServiceContractError(
                    "invalid_tool_arguments",
                    "PC plan tool arguments must contain only a device_id.",
                )
            device_id = entry.get("device_id")
            if not is_pc_device_id(device_id):
                raise ServiceContractError(
                    "invalid_tool_arguments",
                    "PC plan device target is invalid.",
                )

    def _tool_request_kwargs(
        self,
        *,
        app_id: str,
        plan: AgentPlan | None,
        raw_tool_arguments: Any,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Attach trusted tool authority to a Core request when provisioned.

        Without a server binding, no tool authority is attached at all and a
        plan can never execute tools; a caller cannot fabricate the fields.
        """
        if raw_tool_arguments is not None and plan is None:
            raise ServiceContractError(
                "tool_arguments_without_plan",
                "tool_arguments requires an agent_plan.",
            )
        if plan is None:
            return {}
        binding = self._resolve_tool_binding(app_id)
        if binding is None:
            if raw_tool_arguments is not None:
                raise ServiceContractError(
                    "tool_runtime_unavailable",
                    "Tool arguments require a provisioned trusted tool runtime binding.",
                    status_code=503,
                )
            return {}
        authority = binding.resolve_authority(plan.agent_id)
        parsed_tool_arguments = self._parse_tool_arguments(raw_tool_arguments)
        self._validate_pc_plan_tool_arguments(plan, parsed_tool_arguments)
        kwargs: dict[str, Any] = {
            "agent_definition": authority.definition,
            "compiled_agent_profile": authority.compiled,
            "tool_authorization": authority.authorization,
            "tool_runtime": binding.tool_runtime,
            "tool_arguments": parsed_tool_arguments,
        }
        if not resume:
            # OrchestrationResumeRequest has no tool_registry / resource_policy
            # fields; Core's resume executor drives tools through the runtime.
            kwargs["tool_registry"] = binding.registry
            kwargs["tool_resource_policy"] = binding.resource_policy
        return kwargs

    def _attach_pc_query_step_driver(
        self,
        *,
        app_id: str,
        orch_req: OrchestrationRequest,
        exec_req: ExecutionRequest,
        declared_plan: str | None = None,
        initial_decision: Mapping[str, Any] | None = None,
    ) -> OrchestrationRequest | ServiceResponse:
        """Bind the owner-selected step driver to the exact product PC plan.

        Without it Core falls back to the plan-backed driver, which invents a
        ``query`` argument that the closed PC tool schema rejects, so the PC
        plan could never execute. Any other plan is returned untouched.
        """
        if not _pc_query_plan_pair(app_id, orch_req.agent_plan):
            return orch_req
        if self._pc_query_step_driver_factory is None or not orch_req.subject_id:
            return _service_error(
                "pc_query_model_unavailable",
                "Owner-bound PC query model runtime unavailable.",
                status_code=503,
            )
        model_id = exec_req.agent.model_policy.get("model")
        if not isinstance(model_id, str) or not model_id:
            label = "Claw" if app_id == "b54-padiem-claw" else "Chat"
            return _service_error(
                "pc_query_model_unavailable",
                f"Resolved {label} model is unavailable.",
                status_code=503,
            )
        tool_arguments = orch_req.tool_arguments
        shape = tuple(
            (step.step_id, getattr(step, "tool_id", None))
            for step in orch_req.agent_plan.steps
        )
        ceiling = {
            (("query_drives", "claw.pc.query_drives"),): "query_drives",
            (("list_files", "claw.pc.list_files"),): "files_list",
            (("list_files", "claw.pc.list_files"),
             ("read_file", "claw.pc.read_file")): "files",
        }.get(shape)
        if ceiling is not None:
            # The admitted plan fixes the ceiling even when the owner has no
            # explicit device hint. This internal marker is never a target or
            # a grant; owner resolution still uses the original request.
            tool_arguments = {ceiling: dict(
                (tool_arguments or {}).get(ceiling, {}),
            )}
        driver_options = {"initial_decision": initial_decision} if initial_decision is not None else {}
        driver = self._pc_query_step_driver_factory(
                model_id, exec_req.agent.model_policy,
                exec_req.agent.task_type, exec_req.agent.optimize_for,
                tool_arguments=tool_arguments, **driver_options,
        )
        configure_scope = getattr(driver, "configure_request_scope", None)
        if callable(configure_scope):
            # Keep legacy driver calls identical when no declaration is sent.
            scope_options = {"declared_plan": declared_plan} if declared_plan is not None else {}
            configure_scope(orch_req.tool_authorization,
                ceiling_tool_ids=frozenset(step.tool_id for step in orch_req.agent_plan.steps),
                request_context=exec_req.additional_system_context, **scope_options)
        elif declared_plan is not None:
            return _service_error(
                "pc_query_model_unavailable", "PC request scope admission is unavailable.",
                status_code=503,
            )
        return replace(orch_req, agent_step_driver=driver)

    @staticmethod
    def _assert_resumed_invocation_matches(
        plan: AgentPlan,
        pause: ApprovalPause,
        tool_arguments: Mapping[str, Any],
    ) -> None:
        """Fail closed unless the paused invocation is resumed byte-identical."""
        step_index = pause.step_index - 1
        if not 0 <= step_index < len(plan.steps):
            raise ServiceContractError(
                "continuation_identity_mismatch",
                "resumed plan does not align with the paused step.",
                status_code=409,
            )
        step = plan.steps[step_index]
        if step.tool_id != pause.tool_id:
            raise ServiceContractError(
                "continuation_identity_mismatch",
                "resumed plan step does not match the paused tool.",
                status_code=409,
            )
        arguments = dict(tool_arguments.get(step.step_id, {}) or {})
        if not arguments and step.objective:
            arguments["query"] = step.objective
        try:
            candidate = ToolInvocation(tool_id=step.tool_id, arguments=arguments)
        except (TypeError, ValueError):
            raise ServiceContractError(
                "continuation_identity_mismatch",
                "resumed invocation does not satisfy the tool invocation contract.",
                status_code=409,
            ) from None
        if tool_invocation_digest(candidate) != pause.invocation_sha256:
            raise ServiceContractError(
                "continuation_identity_mismatch",
                "resumed invocation does not match the paused invocation.",
                status_code=409,
            )

    async def _continuation_call(self, method: str, **kwargs: Any) -> Any:
        try:
            result = getattr(self._continuation_store, method)(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except ServiceContractError:
            raise
        except Exception as exc:
            raise ServiceContractError(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            ) from exc

    async def _release_claim(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None:
        await self._continuation_call(
            "release",
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
        )

    async def _commit_claim(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None:
        await self._continuation_call(
            "commit",
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
        )

    async def _abort_idempotency(self, *, app_id: str, context: ExecutionContext, reason: str) -> None:
        if context.idempotency_key is None or self._idempotency_adapter is None:
            return
        try:
            if callable(getattr(self._idempotency_adapter, "abort", None)):
                result = self._idempotency_adapter.abort(
                    app_id=app_id,
                    idempotency_key=context.idempotency_key,
                    reason=reason,
                )
            elif callable(getattr(self._idempotency_adapter, "release", None)):
                result = self._idempotency_adapter.release(
                    app_id=app_id,
                    idempotency_key=context.idempotency_key,
                )
            else:
                return
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    async def _verify_decision(
        self,
        submission: ApprovalDecisionSubmission,
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision:
        verifier = self._approval_decision_verifier
        if verifier is None:
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Approval decision verification is unavailable.",
                status_code=503,
            )
        verified = verifier.verify(submission, pause=pause, app_id=app_id)
        if inspect.isawaitable(verified):
            verified = await verified
        if not isinstance(verified, VerifiedApprovalDecision):
            raise ServiceContractError(
                "invalid_verified_decision",
                "Approval decision verification failed.",
                status_code=422,
            )
        return verified

    async def _orchestration_body(
        self,
        result: OrchestrationResult,
        *,
        app_id: str,
        request_fingerprint_value: str | None = None,
    ) -> dict[str, Any]:
        body = result.to_public_dict()
        # #1745: Core's OrchestrationResult.to_public_dict evidence block is
        # forwarded unmodified. Orchestration reuses the same canonical Evidence
        # model (Core citation authority behind app.evidence_projection) and the
        # Engine never forks a second orchestration-specific evidence shape.
        pause = result.approval_pause
        if pause is not None:
            if self._approval_decision_verifier is None or not self._continuation_store_is_explicit:
                await self._abort_idempotency(
                    app_id=app_id,
                    context=result.context,
                    reason="approval_continuation_unavailable",
                )
                raise ServiceContractError(
                    "approval_verification_unavailable",
                    "Approval continuation requires trusted verification and an explicit continuation store.",
                    status_code=503,
                )
            plan_id = result.plan.agent_id if result.plan is not None else pause.plan_id
            if pause.trace_id is None:
                await self._abort_idempotency(
                    app_id=app_id,
                    context=result.context,
                    reason="invalid_continuation",
                )
                raise ServiceContractError(
                    "invalid_continuation",
                    "Approval pause is missing trusted continuation identity.",
                    status_code=500,
                )
            try:
                body["continuation_ref"] = await self._continuation_call(
                    "issue",
                    app_id=app_id,
                    pause=pause,
                    plan_id=plan_id,
                    idempotency_key=result.context.idempotency_key,
                    request_fingerprint=request_fingerprint_value,
                )
            except ServiceContractError:
                await self._abort_idempotency(
                    app_id=app_id,
                    context=result.context,
                    reason="continuation_issue_failed",
                )
                raise
        return body

    @staticmethod
    def _orchestration_run_error_response(exc: BaseException) -> ServiceResponse | None:
        """Map a run-time orchestration failure to the bounded error envelope.

        Shared by the JSON orchestrate route and the NDJSON stream so both
        surface byte-identical error codes and retryability.
        """
        if isinstance(exc, IdempotencyConflictError):
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        if isinstance(exc, OrchestrationError):
            if exc.code in {"authorization_denied", "missing_approval_authorization", "capability_missing"}:
                return _service_error(exc.code, exc.safe_message, status_code=403)
            status_code = 422 if exc.code in {"invalid_plan", "authority_widening_rejected"} else 400
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        if isinstance(exc, EngineToolProjectionError):
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        if isinstance(exc, ExecutionRuntimeError):
            if _is_b14_model_error(exc):
                return _service_error(
                    exc.code,
                    _B14_MODEL_ERROR_PUBLIC_MESSAGE,
                    status_code=_b14_model_error_status(exc),
                    retryable=exc.retryable,
                )
            return _service_error("engine_internal_error", "Orchestration execution failed.", status_code=500)
        return None

    def _orchestrate_request_from_payload(
        self,
        payload: Any,
    ) -> tuple[str, OrchestrationRequest, ExecutionRequest, str] | ServiceResponse:
        """Validate untrusted wire input and build a bounded OrchestrationRequest.

        Returns either the built request with its logical fingerprint, or a
        ServiceResponse describing the contract failure. Shared by the JSON
        orchestrate route and the NDJSON orchestration stream route so both
        enforce the identical wire contract.
        """
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )

        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)

        extra = set(payload) - _ORCHESTRATE_ALLOWED
        if extra:
            return _service_error("invalid_request", "Request contains unsupported fields.", status_code=400)

        exec_payload = {
            k: payload[k]
            for k in ("app_id", "agent", "messages", "session_id", "additional_system_context", "trace_id", "execution_context")
            if k in payload
        }
        try:
            _validated_pc_declared_plan(payload)
            from app.pc_tools_turn import parse_pc_tools
            parse_pc_tools(payload)
            _, exec_req, ctx = build_execution_request(exec_payload)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        if ctx is None:
            trace_id = exec_req.trace_id or _server_generated_trace_id()
            exec_req = _execution_request_with_trace(exec_req, trace_id)
            ctx = ExecutionContext(trace_id=trace_id)

        try:
            plan, rec_policy, max_retries, subject_id, require_evidence, require_verification = (
                _parse_orchestration_options(payload)
            )
            tool_kwargs = self._tool_request_kwargs(
                app_id=app_id,
                plan=plan,
                raw_tool_arguments=payload.get("tool_arguments"),
            )
            orch_req = OrchestrationRequest(
                execution_request=exec_req,
                context=ctx,
                app_id=app_id,
                subject_id=subject_id,
                agent_plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
                require_evidence=require_evidence,
                require_verification=require_verification,
                **tool_kwargs,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (AgentPlannerError, AgentRecoveryError, OrchestrationError) as exc:
            return _service_error(exc.code, exc.safe_message, status_code=400)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Orchestration request fields are invalid.", status_code=400)

        return app_id, orch_req, exec_req, _execution_request_fingerprint(app_id=app_id, request=exec_req)

    def _tool_result_ledger(self, app_id: str, subject_id: str | None) -> Any | None:
        """The durable ledger for one run, or None when the host has no store.

        The ledger is owner-scoped, so a reference from another subject can
        never resolve this run's payload.
        """
        if self._tool_result_ledger_factory is None:
            return None
        try:
            return self._tool_result_ledger_factory(app_id, subject_id)
        except Exception:
            return None

    async def orchestrate_payload(
        self, payload: Any, *, trusted_office_run_id: str | None = None,
    ) -> ServiceResponse:
        """Execute public input or a server-owned exact Office Broker run.

        The keyword is private Python composition only; it is never parsed
        from the Engine HTTP JSON payload or accepted as a model argument.
        """
        built = self._orchestrate_request_from_payload(payload)
        if isinstance(built, ServiceResponse):
            return built
        app_id, orch_req, exec_req, request_fingerprint_value = built
        if (app_id == "b54-padiem-claw"
            and orch_req.agent_plan is not None
            and orch_req.agent_plan.agent_id == "agent:padiem:claw-desktop@1"):
            if (self._desktop_step_driver_factory is None
                or not orch_req.subject_id):
                return _service_error(
                    "desktop_model_unavailable",
                    "Owner-bound desktop model runtime unavailable.",
                    status_code=503,
                )
            model_id = exec_req.agent.model_policy.get("model")
            if not isinstance(model_id, str) or not model_id:
                return _service_error(
                    "desktop_model_unavailable",
                    "Resolved Claw model is unavailable.",
                    status_code=503,
                )
            orch_req = replace(
                orch_req,
                agent_step_driver=self._desktop_step_driver_factory(
                    model_id, exec_req.agent.model_policy,
                    exec_req.agent.task_type, exec_req.agent.optimize_for,
                ),
            )
        attached = self._attach_pc_query_step_driver(
            app_id=app_id, orch_req=orch_req, exec_req=exec_req,
            declared_plan=payload.get("declared_plan"),
        )
        if isinstance(attached, ServiceResponse):
            return attached
        orch_req = attached
        if trusted_office_run_id is not None:
            # No ordinary app may select the Core Agent pause run id. The
            # first-party owner/Broker authority must provide this exact
            # server-owned identity; the caller\u0027s arguments cannot replace it.
            from app.hark_office_p01_tool_binding import APP_ID, LIST_TOOL_ID, READ_TOOL_ID
            plan = orch_req.agent_plan
            args = getattr(orch_req, "tool_arguments", None)
            if (app_id != APP_ID
                    or type(trusted_office_run_id) is not str
                    or plan is None or len(plan.steps) != 1
                    or plan.steps[0].tool_id not in (LIST_TOOL_ID, READ_TOOL_ID)
                    or not isinstance(args, Mapping) or len(args) != 1):
                return _service_error("invalid_request", "Trusted Office run identity is invalid.", status_code=400)
            only_args = next(iter(args.values()))
            if (not isinstance(only_args, Mapping)
                    or only_args.get("run_id") != trusted_office_run_id):
                return _service_error("office_run_identity_mismatch", "Office command run identity mismatch.", status_code=409)
            try:
                orch_req = replace(orch_req, trusted_agent_bridge_run_id=trusted_office_run_id)
            except (ValueError, TypeError):
                return _service_error("invalid_request", "Trusted Office run identity is invalid.", status_code=400)

        try:
            runtime = self._runtime_for_payload(app_id, payload)
            runner = OrchestrationRunner(
                runtime=runtime, idempotency=self._idempotency_adapter,
                agent_result_ledger=self._tool_result_ledger(
                    app_id, getattr(orch_req, "subject_id", None),
                ),
            )
            result = await runner.run(orch_req)
        except (IdempotencyConflictError, OrchestrationError, EngineToolProjectionError, ExecutionRuntimeError) as exc:
            response = self._orchestration_run_error_response(exc)
            if response is not None:
                return response
            raise
        except Exception:
            return _service_error("engine_internal_error", "Orchestration execution failed.", status_code=500)
        try:
            orchestration_body = await self._orchestration_body(
                result,
                app_id=app_id,
                request_fingerprint_value=request_fingerprint_value,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "orchestration": orchestration_body,
            },
        )

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        """Resume only a server-issued continuation with a verified decision."""
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        extra = set(payload) - _RESUME_ALLOWED
        if extra:
            return _service_error("invalid_request", "Request contains unsupported fields.", status_code=400)
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = await self._continuation_call(
                "resolve",
                app_id=app_id,
                continuation_ref=continuation_ref,
            )
            if not isinstance(record, ContinuationRecord):
                raise ServiceContractError(
                    "continuation_store_unavailable",
                    "Approval continuation storage returned an invalid record.",
                    status_code=503,
                )
            submission = _parse_approval_decision_submission(payload.get("decision"))
            if submission.pause_id != record.pause.pause_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "decision does not match the server-issued continuation.",
                    status_code=409,
                )
            _, exec_req, ctx = build_execution_request({
                k: payload[k]
                for k in ("app_id", "agent", "messages", "session_id", "additional_system_context", "trace_id", "execution_context")
                if k in payload
            })
            plan = _parse_agent_plan(payload.get("agent_plan"))
            if record.plan_id is not None:
                if plan is None or plan.agent_id != record.plan_id:
                    raise ServiceContractError("continuation_identity_mismatch", "agent plan does not match the server-issued continuation.", status_code=409)
            elif plan is not None:
                raise ServiceContractError("continuation_identity_mismatch", "unexpected agent plan does not match the server-issued continuation.", status_code=409)
            if exec_req.agent.id != record.pause.agent_runtime_id:
                raise ServiceContractError("continuation_identity_mismatch", "agent runtime does not match the server-issued continuation.", status_code=409)
            if ctx is None:
                if record.pause.trace_id is None:
                    raise ServiceContractError(
                        "continuation_identity_mismatch",
                        "server-issued continuation is missing trace identity.",
                        status_code=409,
                    )
                trace_id = exec_req.trace_id or record.pause.trace_id
                exec_req = _execution_request_with_trace(exec_req, trace_id)
                ctx = ExecutionContext(trace_id=trace_id)
            if ctx.trace_id != record.pause.trace_id:
                raise ServiceContractError("continuation_identity_mismatch", "trace_id does not match the server-issued continuation.", status_code=409)
            request_fp = _execution_request_fingerprint(app_id=app_id, request=exec_req)
            if record.idempotency_key is not None:
                if self._idempotency_adapter is None:
                    raise ServiceContractError(
                        "idempotency_unavailable",
                        "The trusted idempotency adapter is unavailable for continuation resume.",
                        status_code=503,
                    )
                if ctx.idempotency_key != record.idempotency_key:
                    raise ServiceContractError(
                        "idempotency_conflict",
                        "Idempotency key does not match the server-issued continuation.",
                        status_code=409,
                    )
                if record.request_fingerprint is None or request_fp != record.request_fingerprint:
                    raise ServiceContractError(
                        "idempotency_conflict",
                        "Execution request does not match the server-issued continuation.",
                        status_code=409,
                    )
            elif ctx.idempotency_key is not None:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Unexpected idempotency key does not match the server-issued continuation.",
                    status_code=409,
                )
            decision = await self._verify_decision(submission, pause=record.pause, app_id=app_id)
            if (
                decision.decision_id != submission.decision_id
                or decision.pause_id != submission.pause_id
                or decision.outcome is not submission.outcome
                or decision.decided_at != submission.decided_at
            ):
                raise ServiceContractError("invalid_verified_decision", "Verified decision does not match the submitted decision.", status_code=422)
            # Pre-mutation validation: parse the remaining orchestration fields
            # and construct the resume request BEFORE claiming the continuation.
            # A rejection here leaves the continuation ACTIVE and unclaimed.
            rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
            max_retries = _parse_max_retries(payload.get("max_retries", 3))
            subject_id = _parse_subject_id(payload.get("subject_id"))
            tool_kwargs = self._tool_request_kwargs(
                app_id=app_id,
                plan=plan,
                raw_tool_arguments=payload.get("tool_arguments"),
                resume=True,
            )
            base_tool_authorization = tool_kwargs.get("tool_authorization")
            if base_tool_authorization is not None:
                tool_kwargs["tool_authorization"] = (
                    bind_verified_approval_to_tool_authorization(
                        base_tool_authorization,
                        pause=record.pause,
                        decision=decision,
                    )
                )
            if (
                plan is not None
                and "tool_runtime" in tool_kwargs
                and record.plan_id is not None
            ):
                # Continuation non-widening: the wire may only resume the exact
                # invocation that produced the server-issued pause.
                self._assert_resumed_invocation_matches(
                    plan,
                    record.pause,
                    tool_kwargs.get("tool_arguments") or {},
                )
            resume_req = OrchestrationResumeRequest(
                pause=record.pause,
                decision=decision,
                execution_request=exec_req,
                context=ctx,
                app_id=app_id,
                subject_id=subject_id,
                agent_plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
                **tool_kwargs,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (AgentPlannerError, AgentRecoveryError, OrchestrationError) as exc:
            return _service_error(exc.code, exc.safe_message, status_code=400)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Resume request fields are invalid.", status_code=400)

        try:
            claimed_record = await self._continuation_call(
                "claim",
                app_id=app_id,
                continuation_ref=record.continuation_ref,
            )
            if not isinstance(claimed_record, ContinuationRecord) or claimed_record.claim_token is None:
                raise ServiceContractError(
                    "continuation_claim_failed",
                    "Continuation claim did not return a valid claim token.",
                    status_code=503,
                )
            record = claimed_record
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        claim_token = record.claim_token
        assert claim_token is not None

        try:
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(
                runtime=runtime, idempotency=self._idempotency_adapter,
                agent_result_ledger=self._tool_result_ledger(
                    app_id, getattr(resume_req, "subject_id", None),
                ),
            )
            result = await runner.resume(resume_req)
        except OrchestrationError as exc:
            if exc.code == "approval_denied":
                try:
                    await self._commit_claim(
                        app_id=app_id,
                        continuation_ref=record.continuation_ref,
                        claim_token=claim_token,
                    )
                except ServiceContractError as commit_exc:
                    return _service_error(commit_exc.code, commit_exc.safe_message, status_code=commit_exc.status_code)
            else:
                try:
                    await self._release_claim(
                        app_id=app_id,
                        continuation_ref=record.continuation_ref,
                        claim_token=claim_token,
                    )
                except ServiceContractError as release_exc:
                    return _service_error(release_exc.code, release_exc.safe_message, status_code=release_exc.status_code)
            if exc.code in {"missing_approval_authorization", "authorization_denied"}:
                return _service_error(exc.code, exc.safe_message, status_code=403)
            status_code = 409 if exc.code in {"continuation_expired", "approval_denied", "continuation_identity_mismatch"} else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except ExecutionRuntimeError as exc:
            try:
                await self._release_claim(
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError as release_exc:
                return _service_error(release_exc.code, release_exc.safe_message, status_code=release_exc.status_code)
            if _is_b14_model_error(exc):
                return _service_error(
                    exc.code,
                    _B14_MODEL_ERROR_PUBLIC_MESSAGE,
                    status_code=_b14_model_error_status(exc),
                    retryable=exc.retryable,
                )
            return _service_error("engine_internal_error", "Orchestration resumption failed.", status_code=500)
        except asyncio.CancelledError:
            try:
                await self._release_claim(
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            raise
        except Exception:
            try:
                await self._release_claim(
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError as release_exc:
                return _service_error(release_exc.code, release_exc.safe_message, status_code=release_exc.status_code)
            return _service_error("engine_internal_error", "Orchestration resumption failed.", status_code=500)

        try:
            await self._commit_claim(
                app_id=app_id,
                continuation_ref=record.continuation_ref,
                claim_token=claim_token,
            )
        except ServiceContractError as commit_exc:
            return _service_error(commit_exc.code, commit_exc.safe_message, status_code=commit_exc.status_code)

        # #3580: only AFTER the Engine has verified an actual first-party
        # decision, completed the registered ToolRuntime confirmation, and
        # atomically CONSUMED the continuation may a PRIVATE durable sink
        # receive the immutable canonical Office READ receipt. There is no
        # browser/wire field to supply the decision or invoke this sink.
        if self._approved_office_read_sink is not None:
            try:
                receipt = prepare_approved_office_read_receipt(
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    pause=record.pause,
                    decision=decision,
                    tool_arguments=tool_kwargs.get("tool_arguments"),
                    execution_status=result.execution_result.metadata.status,
                )
                if receipt is not None:
                    persisted = self._approved_office_read_sink.record_verified_office_read(receipt)
                    if inspect.isawaitable(persisted):
                        persisted = await persisted
                    if persisted is not True:
                        raise ValueError("trusted Office receipt not persisted")
            except Exception:
                # Continuation is already consumed; never return success or
                # dispatch a local file operation when durable evidence
                # recording is unknown. Owner must start a fresh operation.
                return _service_error(
                    "office_approval_receipt_unavailable",
                    "Verified Office authorization receipt was not persisted.",
                    status_code=503,
                )
        try:
            orchestration_body = await self._orchestration_body(
                result,
                app_id=app_id,
                request_fingerprint_value=request_fp,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        body: dict[str, Any] = {
            "ok": True,
            "orchestration": orchestration_body,
        }
        # S13-5 Phase 1: additive lifecycle mirror.  The sibling key is added only
        # when a real continuation record backed this resume; every pre-existing key
        # and shape above stays untouched.
        lifecycle_block = _orchestration_lifecycle_block(
            record=record,
            transition="resume",
            events=result.events,
        )
        if lifecycle_block is not None:
            body["continuation"] = lifecycle_block
        return ServiceResponse(status_code=200, body=body)

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        """Cancel only a server-issued continuation."""
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        extra = set(payload) - _CANCEL_ALLOWED
        if extra:
            return _service_error("invalid_request", "Request contains unsupported fields.", status_code=400)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        if not getattr(self, "_continuation_store_supports_atomic_cancel", True):
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage does not support atomic cancellation.",
                status_code=503,
            )
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = await self._continuation_call(
                "resolve",
                app_id=app_id,
                continuation_ref=continuation_ref,
            )
            if not isinstance(record, ContinuationRecord):
                raise ServiceContractError(
                    "continuation_store_unavailable",
                    "Approval continuation storage returned an invalid record.",
                    status_code=503,
                )
            if record.pause.trace_id is None:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "server-issued continuation is missing trace identity.",
                    status_code=409,
                )
            # Pre-mutation validation: validate the cancel reason before any
            # continuation state change so malformed input never mutates state.
            reason = _parse_cancel_reason(payload.get("reason", "user_cancelled"))
            trace_id = record.pause.trace_id
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Cancellation request fields are invalid.", status_code=400)

        try:
            claimed_record = await self._continuation_call(
                "claim_cancel",
                app_id=app_id,
                continuation_ref=record.continuation_ref,
                reason=reason,
            )
            if not isinstance(claimed_record, ContinuationRecord) or claimed_record.state != "cancelling":
                raise ServiceContractError(
                    "continuation_cancel_claim_failed",
                    "Continuation cancel claim did not commit.",
                    status_code=503,
                )
            claim_token = claimed_record.claim_token
            assert claim_token is not None
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Cancellation request fields are invalid.", status_code=400)

        try:
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime)
            events = runner.cancel_pause(claimed_record.pause, trace_id=trace_id, reason=reason)
        except ServiceContractError as exc:
            try:
                await self._continuation_call(
                    "release_cancel",
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ExecutionRuntimeError as exc:
            try:
                await self._continuation_call(
                    "release_cancel",
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            if _is_b14_model_error(exc):
                return _service_error(
                    exc.code,
                    _B14_MODEL_ERROR_PUBLIC_MESSAGE,
                    status_code=_b14_model_error_status(exc),
                    retryable=exc.retryable,
                )
            return _service_error("engine_internal_error", "Cancellation failed.", status_code=500)
        except Exception:
            try:
                await self._continuation_call(
                    "release_cancel",
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            return _service_error("engine_internal_error", "Cancellation failed.", status_code=500)

        try:
            committed = await self._continuation_call(
                "commit_cancel",
                app_id=app_id,
                continuation_ref=record.continuation_ref,
                claim_token=claim_token,
            )
            if not isinstance(committed, ContinuationRecord) or committed.state != "cancelled":
                raise ServiceContractError(
                    "continuation_cancel_commit_failed",
                    "Continuation cancel commit did not persist.",
                    status_code=503,
                )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        body: dict[str, Any] = {
            "ok": True,
            "status": "cancelled",
            "events": [e.to_public_dict() for e in events],
        }
        # S13-5 Phase 1: additive lifecycle mirror for the cancel transition.  The
        # pre-existing keys and shapes are unchanged.
        lifecycle_block = _orchestration_lifecycle_block(
            record=record,
            transition="cancel",
            events=events,
        )
        if lifecycle_block is not None:
            body["continuation"] = lifecycle_block
        return ServiceResponse(status_code=200, body=body)

    async def prepare_stream(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
        pc_progress: bool = False,
    ) -> PreparedOrchestrationStream | ServiceResponse:
        """Validate and prime an orchestration stream before HTTP 200 commits.

        Mirrors the NDJSON streaming contract used by ``StreamingEngineService``:
        every wire validation runs here so route-level failures surface as
        normal JSON error responses, and the first lifecycle event (or an
        immediate run failure) is awaited before the caller starts writing.
        """

        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != ORCHESTRATION_STREAM_PATH:
            return _service_error("not_found", "Orchestration route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _service_error("unsupported_media_type", "Content-Type must be application/json.", status_code=415)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        # #4139: worker.py already admits these two model routes at the
        # Engine's existing model request budget, so the inner guard has to
        # be the same budget. At 128 KiB a model request between the two was
        # read whole and then refused here, which made the outer budget
        # fictional. Non-model routes keep MAX_REQUEST_BODY_BYTES.
        if (
            MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES is not None
            and len(raw) > MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES
        ):
            return _service_error("request_too_large", "Request body exceeds the safety limit.", status_code=413)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)

        built = self._orchestrate_request_from_payload(payload)
        if isinstance(built, ServiceResponse):
            return built
        app_id, orch_req, exec_req, request_fingerprint_value = built

        # #5015: the streaming lane must compose the same owner-bound PC query
        # step driver as the non-stream execute() lane. Without it the Core
        # falls back to the plan-backed driver, which injects a `query`
        # argument the drive tool schema rejects (invalid_tool_arguments).
        plan = orch_req.agent_plan
        if plan is not None and orch_req.subject_id and _pc_query_plan_pair(app_id, plan):
            if self._pc_query_step_driver_factory is None:
                return _service_error(
                    "pc_query_model_unavailable",
                    "Owner-bound PC query model runtime unavailable.",
                    status_code=503,
                )
            stream_model_id = exec_req.agent.model_policy.get("model")
            if not isinstance(stream_model_id, str) or not stream_model_id:
                return _service_error(
                    "pc_query_model_unavailable",
                    "Resolved model is unavailable.",
                    status_code=503,
                )
            attached = self._attach_pc_query_step_driver(
                app_id=app_id, orch_req=orch_req, exec_req=exec_req,
                declared_plan=payload.get("declared_plan"),
            )
            if isinstance(attached, ServiceResponse):
                return attached
            orch_req = attached

        # The synchronous sink receives events in emission order (Core's emit
        # closures deliver synchronously); an unbounded asyncio.Queue never
        # suspends on put_nowait, so ordering and liveness are preserved.
        queue: asyncio.Queue[OrchestrationEvent] = asyncio.Queue()
        runner = OrchestrationRunner(
            runtime=self._runtime_for_payload(app_id, payload),
            idempotency=self._idempotency_adapter,
            event_sink=queue.put_nowait,
        )
        # #5015: the streaming lane runs the Core runner directly, so it never
        # passes through the admission wrapper that sets the tool-owner
        # context for the non-stream lane. The PC drive tool handler fails
        # closed without it (pc_query_admission_required) and no Chat dispatch
        # is ever created. Bind the owner only for the exact canonical
        # PC-query plan; every other stream keeps the unset default.
        from app.claw_pc_query_step_driver import _PC_QUERY_OWNER, _PC_PROGRESS_SINK
        from kagent.pc_query_adapter import PC_QUERY_RUN_SCOPE

        declared_identity_token = None
        if "declared_plan" in payload:
            # The stream task needs the same material replay identity as JSON.
            # Leave the legacy context untouched when this field is absent.
            from app.orchestration_idempotency_service import _initial_execution_fingerprint
            from app.idempotency_identity import (
                set_canonical_idempotency_fingerprint,
                reset_canonical_idempotency_fingerprint,
            )
            declared_fingerprint = _initial_execution_fingerprint(payload)
            if declared_fingerprint is None:
                return _service_error("invalid_plan", "PC request scope identity is invalid.", status_code=422)
            request_fingerprint_value = declared_fingerprint
            declared_identity_token = set_canonical_idempotency_fingerprint(declared_fingerprint)
        pc_owner_token = _PC_QUERY_OWNER.set(_pc_query_stream_owner(app_id, orch_req))
        pc_scope_token = PC_QUERY_RUN_SCOPE.set(getattr(orch_req.agent_step_driver, "scope_state", None))
        pc_turn = _canonical_pc_plan(app_id, plan) is not None or "pc_tools" in payload
        pc_stream = pc_progress is True and pc_turn
        from app.pc_tools_turn import _PC_TURN_STREAM_SINK
        turn_sink_token = _PC_TURN_STREAM_SINK.set(queue.put_nowait if pc_stream else None)
        progress_token = _PC_PROGRESS_SINK.set(
            (lambda item: queue.put_nowait({"pc_progress": item}))
            if pc_stream else None
        )
        try:
            task = asyncio.create_task(runner.run(orch_req))
        finally:
            _PC_TURN_STREAM_SINK.reset(turn_sink_token)
            _PC_PROGRESS_SINK.reset(progress_token)
            _PC_QUERY_OWNER.reset(pc_owner_token)
            PC_QUERY_RUN_SCOPE.reset(pc_scope_token)
            if declared_identity_token is not None:
                reset_canonical_idempotency_fingerprint(declared_identity_token)
        first_event_task = asyncio.ensure_future(queue.get())
        done, _pending = await asyncio.wait(
            {first_event_task, task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done and first_event_task in done:
            # The queue consumer observed the first event in the same turn the
            # run completed; that observed event is the first visible
            # lifecycle event and any remaining queued events stream after it.
            return PreparedOrchestrationStream(
                first_event=first_event_task.result(),
                queue=queue,
                task=task,
                app_id=app_id,
                request_fingerprint_value=request_fingerprint_value,
                pc_progress=pc_stream,
                pc_turn=pc_turn,
            )
        if task in done:
            if first_event_task not in done:
                first_event_task.cancel()
                try:
                    await first_event_task
                except (asyncio.CancelledError, Exception):
                    pass
            # A run can complete (or fail) in the same event-loop turn that
            # produces its first event, before the queue consumer ever runs.
            # A populated queue is a valid stream: the first queued event is
            # the first visible lifecycle event and the task result/exception
            # settles in iter_ndjson exactly like a slow run.
            if not queue.empty():
                return PreparedOrchestrationStream(
                    first_event=queue.get_nowait(),
                    queue=queue,
                    task=task,
                    app_id=app_id,
                    request_fingerprint_value=request_fingerprint_value,
                    pc_progress=pc_stream,
                    pc_turn=pc_turn,
                )
            try:
                await task
            except asyncio.CancelledError:
                raise
            except (IdempotencyConflictError, OrchestrationError, EngineToolProjectionError, ExecutionRuntimeError) as exc:
                response = self._orchestration_run_error_response(exc)
                if response is not None:
                    return response
                return _service_error("engine_internal_error", "Orchestration streaming failed.", status_code=500)
            except Exception:
                return _service_error("engine_internal_error", "Orchestration streaming failed.", status_code=500)
            # A run that ends before its first lifecycle event violates the
            # orchestration event contract: the RUN_STARTED event is always
            # emitted synchronously at the start of a valid run.
            return _service_error(
                "malformed_upstream",
                "Orchestration run ended before producing a lifecycle event.",
                status_code=502,
            )
        return PreparedOrchestrationStream(
            first_event=first_event_task.result(),
            queue=queue,
            task=task,
            app_id=app_id,
            request_fingerprint_value=request_fingerprint_value,
            pc_progress=pc_stream,
            pc_turn=pc_turn,
        )

    async def iter_ndjson(self, prepared: PreparedOrchestrationStream) -> AsyncIterator[str]:
        """Emit one public orchestration event per line, then the settled result line.

        The terminal NDJSON line carries the same orchestration body as the
        non-stream ``/internal/v1/orchestrate`` route (including a
        ``continuation_ref`` when the run paused for approval), so stream and
        non-stream consumers settle on identical semantics.
        """

        if not isinstance(prepared, PreparedOrchestrationStream):
            raise ValueError("prepared must be PreparedOrchestrationStream")
        pc_turn = prepared.pc_turn or prepared.pc_progress

        def failure_line(exc: BaseException, stage: str) -> str:
            # Error conversion/encoding is itself fallible. Keep one literal,
            # serializable fallback outside those operations; never send raw
            # exception messages or tool/model arguments to the client.
            fallback = _service_error(
                "engine_internal_error", "Orchestration streaming failed.", status_code=500,
                metadata={"stage": stage} if pc_turn else None,
            )
            try:
                if isinstance(exc, ServiceContractError):
                    response = _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
                elif isinstance(exc, asyncio.CancelledError):
                    response = _service_error("pc_turn_cancelled", "PC turn was cancelled.", status_code=500)
                else:
                    response = self._orchestration_run_error_response(exc) or fallback
                body = dict(response.body)
                if pc_turn:
                    error = dict(body["error"])
                    error["metadata"] = {**(error.get("metadata") or {}), "stage": stage}
                    body["error"] = error
                return _encode_line(body)
            except Exception:
                return _stream_error_line(fallback)

        started = asyncio.get_running_loop().time()
        stage = "pc_stream_event"
        try:
            yield _stream_event_line(prepared.first_event)
            while not prepared.task.done():
                event_task = asyncio.ensure_future(prepared.queue.get())
                done, _pending = await asyncio.wait(
                    {event_task, prepared.task},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=PC_STREAM_HEARTBEAT_SECONDS if prepared.pc_progress else None,
                )
                if not done:
                    event_task.cancel()
                    try:
                        await event_task
                    except asyncio.CancelledError:
                        pass
                    # Transport liveness only. No Core event/sink/progress call.
                    yield _encode_line({"ok": True, "heartbeat": {
                        "run_id": prepared.first_event.run_id,
                        "trace_id": prepared.first_event.trace_id,
                        "elapsed_ms": max(0, int(
                            (asyncio.get_running_loop().time() - started) * 1000
                        )),
                    }})
                    continue
                if event_task in done:
                    yield _stream_event_line(event_task.result())
                if prepared.task in done and event_task not in done:
                    event_task.cancel()
            while not prepared.queue.empty():
                yield _stream_event_line(prepared.queue.get_nowait())
            stage = "pc_stream_run"
            result = prepared.task.result()
            stage = "pc_stream_result"
            orchestration_body = await self._orchestration_body(
                result,
                app_id=prepared.app_id,
                request_fingerprint_value=prepared.request_fingerprint_value,
            )
            yield _stream_result_line(orchestration_body)
        except asyncio.CancelledError as exc:
            # A cancelled producer must settle the still-connected PC stream.
            # Cancellation of the consumer/disconnect still propagates and the
            # finally block cleans up the producer; never write to a closed peer.
            consumer = asyncio.current_task()
            if pc_turn and prepared.task.cancelled() and not consumer.cancelling():
                yield failure_line(exc, stage)
            else:
                raise
        except Exception as exc:
            yield failure_line(exc, stage)
        finally:
            pending_event = locals().get("event_task")
            if pending_event is not None and not pending_event.done():
                pending_event.cancel()
                try:
                    await pending_event
                except asyncio.CancelledError:
                    pass
            if not prepared.task.done():
                prepared.task.cancel()
                try:
                    await prepared.task
                except (asyncio.CancelledError, Exception):
                    pass

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        """Route and handle incoming orchestration requests."""
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path not in {ORCHESTRATE_PATH, ORCHESTRATE_RESUME_PATH, ORCHESTRATE_CANCEL_PATH}:
            return _service_error("not_found", "Orchestration route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _service_error("unsupported_media_type", "Content-Type must be application/json.", status_code=415)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        # #4139: worker.py already admits these two model routes at the
        # Engine's existing model request budget, so the inner guard has to
        # be the same budget. At 128 KiB a model request between the two was
        # read whole and then refused here, which made the outer budget
        # fictional. Non-model routes keep MAX_REQUEST_BODY_BYTES.
        if (
            MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES is not None
            and len(raw) > MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES
        ):
            return _service_error("request_too_large", "Request body exceeds the safety limit.", status_code=413)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)

        if path == ORCHESTRATE_PATH:
            return await self.orchestrate_payload(payload)
        if path == ORCHESTRATE_RESUME_PATH:
            return await self.resume_payload(payload)
        return await self.cancel_payload(payload)
