"""Language-neutral unified orchestration service contract for Padiem AI Engine.

Exposes bounded, product-neutral orchestration execution, approval continuation
resumption, and cancellation over the internal Engine transport.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
from padiem_ai_core.tool_runtime import MAX_TOOL_ARGUMENT_BYTES, ToolInvocation

from app.execution_context_wire import parse_execution_context
from app.tool_projection import (
    MAX_WIRE_TOOL_ARGUMENTS_BYTES,
    EngineToolBinding,
    EngineToolProjectionError,
    json_size,
)
from app.service import (
    MAX_REQUEST_BODY_BYTES,
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

# Compatibility surface: the wire contract moved to app.orchestration_wire
# in #1792 R2B-2; these re-exports preserve every existing import site.
from app.orchestration_wire import (  # noqa: E402
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    ORCHESTRATE_CANCEL_PATH,
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


def _execution_request_fingerprint(*, app_id: str, request: ExecutionRequest) -> str:
    return request_fingerprint(
        {
            "app_id": app_id,
            "agent_id": request.agent.id,
            "messages": [message for message in request.messages],
        }
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
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if tool_binding_resolver is not None and not callable(tool_binding_resolver):
            raise ValueError("tool_binding_resolver must be callable")
        if approval_decision_verifier is not None and not callable(getattr(approval_decision_verifier, "verify", None)):
            raise ValueError("approval_decision_verifier must provide verify()")
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
        self._b14_service_bound = bool(b14_service_bound)
        self._idempotency_adapter = idempotency_adapter
        self._approval_decision_verifier = approval_decision_verifier
        self._continuation_store = continuation_store or _DEFAULT_CONTINUATION_STORE
        self._continuation_store_is_explicit = continuation_store is not None
        self._tool_binding_resolver = tool_binding_resolver

    # ------------------------------------------------------------------
    # Trusted tool-runtime attachment (#1746)
    # ------------------------------------------------------------------

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
        total = 0
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
                "tool_arguments exceed the bounded orchestration argument budget.",
            )
        return parsed

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
        kwargs: dict[str, Any] = {
            "agent_definition": authority.definition,
            "compiled_agent_profile": authority.compiled,
            "tool_authorization": authority.authorization,
            "tool_runtime": binding.tool_runtime,
            "tool_arguments": self._parse_tool_arguments(raw_tool_arguments),
        }
        if not resume:
            # OrchestrationResumeRequest has no tool_registry / resource_policy
            # fields; Core's resume executor drives tools through the runtime.
            kwargs["tool_registry"] = binding.registry
            kwargs["tool_resource_policy"] = binding.resource_policy
        return kwargs

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

    async def orchestrate_payload(self, payload: Any) -> ServiceResponse:
        """Execute an orchestration request through OrchestrationRunner."""
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

        try:
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.run(orch_req)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except OrchestrationError as exc:
            if exc.code in {"authorization_denied", "missing_approval_authorization", "capability_missing"}:
                return _service_error(exc.code, exc.safe_message, status_code=403)
            status_code = 422 if exc.code in {"invalid_plan", "authority_widening_rejected"} else 400
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except Exception:
            return _service_error("engine_internal_error", "Orchestration execution failed.", status_code=500)
        try:
            orchestration_body = await self._orchestration_body(
                result,
                app_id=app_id,
                request_fingerprint_value=_execution_request_fingerprint(app_id=app_id, request=exec_req),
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
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
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

        try:
            orchestration_body = await self._orchestration_body(
                result,
                app_id=app_id,
                request_fingerprint_value=request_fp,
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

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "status": "cancelled",
                "events": [e.to_public_dict() for e in events],
            },
        )

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
        if len(raw) > MAX_REQUEST_BODY_BYTES:
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
