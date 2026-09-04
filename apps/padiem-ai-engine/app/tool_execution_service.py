"""Bounded, versioned Engine tool execution/continuation transport (#1746).

The Engine performs transport, trusted-binding lookup and safe projection only:

* tool authority comes exclusively from the server-provisioned
  :class:`~app.tool_projection.EngineToolBinding` — caller JSON never mints a
  ``ToolAuthorizationContext`` (``CALLER_JSON != TOOL_AUTHORITY``,
  ``MODEL_OUTPUT != TOOL_AUTHORITY``);
* execution goes through the existing Core ``ToolRuntime.execute()`` with the
  existing fail-closed gates (registration, agent/owner/scope checks, schema
  validation, approval blocking, per-spec timeout, bounded output);
* approval-required results become an approval pause via the existing Core
  bridge ``approval_pause_from_tool_error`` — never self-granted. Continuation
  is structurally non-widening: resume accepts only
  ``{app_id, continuation_ref, decision}`` and re-executes exactly the
  server-held paused invocation after Core's ``resolve_approval_pause`` and
  identity checks. Without a real server-side grant, a resumed attempt re-hits
  the Core approval gate and executes zero handler calls;
* timeout remains an independent terminal outcome (``tool_timeout``/HTTP 504),
  cancellation remains an independent terminal condition (asyncio cancellation
  propagates without being converted to a timeout or internal error response;
  cancelled continuations are distinguishable from denied/expired ones);
* only Core-safe event fields and the redacted bounded output projection from
  ``app.tool_projection`` cross this boundary; raw tool arguments never echo
  back (PRIVATE_TOOL_ARGUMENT_LEAK = 0).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import inspect
import json
import secrets
from typing import Any

from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalPause,
    VerifiedApprovalDecision,
    approval_pause_from_tool_error,
    resolve_approval_pause,
    ContinuationStatus,
)
from padiem_ai_core.tool_lifecycle import ToolLifecycleEvent, ToolLifecycleKind
from padiem_ai_core.tool_runtime import ToolExecutionResult, ToolInvocation, ToolRuntimeError

from app.orchestration_service import (
    ApprovalDecisionVerifier,
    ContinuationRecord,
    ContinuationStore,
    _parse_approval_decision_submission,
    _parse_cancel_reason,
)
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _service_error,
)
from app.tool_projection import (
    MAX_PENDING_TOOL_CONTINUATIONS,
    TOOL_CANCEL_PATH,
    TOOL_EXECUTE_PATH,
    TOOL_RESUME_PATH,
    ENGINE_TOOL_CONTRACT_VERSION,
    EngineToolBinding,
    EngineToolProjectionError,
    TrustedToolAuthority,
    json_size,
    parse_tool_continuation_ref,
    parse_tool_execution_request,
    project_core_tool_lifecycle,
    project_redacted_tool_output,
)

_APPROVAL_PAUSE_SECONDS = 900
_ENGINE_TIMEOUT_GRACE_SECONDS = 1.0

_APPROVAL_BLOCK_CODES = frozenset(
    {
        "tool_user_confirmation_required",
        "tool_external_authorization_required",
    }
)

_TOOL_ERROR_STATUS: dict[str, int] = {
    "tool_not_registered": 403,
    "tool_agent_mismatch": 403,
    "tool_not_allowed": 403,
    "tool_owner_mismatch": 403,
    "tool_auth_scope_missing": 403,
    "invalid_tool_arguments": 400,
    "tool_timeout": 504,
    "tool_execution_failed": 500,
    "invalid_tool_output": 500,
}

_TOOL_CANCEL_ALLOWED = frozenset({"app_id", "continuation_ref", "reason"})
_TOOL_RESUME_ALLOWED = frozenset({"app_id", "continuation_ref", "decision"})


@dataclass(frozen=True, slots=True)
class _PendingToolContinuation:
    """Server-side only state; raw invocation arguments never cross the wire."""

    app_id: str
    canonical_agent_id: str
    canonical_tool_id: str
    invocation: ToolInvocation


class ToolExecutionEngineService:
    """Pure-Python internal handler projecting Core ToolRuntime through Engine."""

    def __init__(
        self,
        *,
        tool_binding_resolver: Callable[[str], EngineToolBinding | None] | None = None,
        approval_decision_verifier: ApprovalDecisionVerifier | None = None,
        continuation_store: ContinuationStore | None = None,
    ) -> None:
        if tool_binding_resolver is not None and not callable(tool_binding_resolver):
            raise ValueError("tool_binding_resolver must be callable")
        if approval_decision_verifier is not None and not callable(
            getattr(approval_decision_verifier, "verify", None)
        ):
            raise ValueError("approval_decision_verifier must provide verify()")
        if continuation_store is not None:
            for method in ("issue", "resolve", "claim", "commit", "release"):
                if not callable(getattr(continuation_store, method, None)):
                    raise ValueError(f"continuation_store must provide {method}()")
            self._supports_atomic_cancel = all(
                callable(getattr(continuation_store, m, None))
                for m in ("claim_cancel", "commit_cancel", "release_cancel")
            )
        else:
            self._supports_atomic_cancel = False
        self._tool_binding_resolver = tool_binding_resolver
        self._approval_decision_verifier = approval_decision_verifier
        self._continuation_store = continuation_store
        self._continuation_store_is_explicit = continuation_store is not None
        self._pending: dict[str, _PendingToolContinuation] = {}

    # ------------------------------------------------------------------
    # transport helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}:{secrets.token_hex(12)}"

    async def _continuation_call(self, method: str, **kwargs: Any) -> Any:
        if self._continuation_store is None:
            raise ServiceContractError(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
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

    def _resolve_binding(self, app_id: str) -> EngineToolBinding:
        if self._tool_binding_resolver is None:
            raise EngineToolProjectionError(
                "tool_runtime_unavailable",
                "The Engine Tool runtime is not provisioned for this deployment.",
                status_code=503,
            )
        try:
            binding = self._tool_binding_resolver(app_id)
        except Exception as exc:
            raise EngineToolProjectionError(
                "tool_runtime_unavailable",
                "The Engine Tool runtime binding resolver failed.",
                status_code=503,
            ) from exc
        if binding is None or binding.app_id != app_id:
            raise EngineToolProjectionError(
                "tool_runtime_unavailable",
                "The Engine Tool runtime is not provisioned for this application.",
                status_code=503,
            )
        return binding

    def _error_from_tool_runtime(
        self,
        exc: ToolRuntimeError,
        *,
        canonical_tool_id: str,
        run_id: str,
    ) -> ServiceResponse:
        status_code = _TOOL_ERROR_STATUS.get(exc.code, 403)
        metadata: dict[str, Any] = {"tool_id": canonical_tool_id}
        if exc.event is not None:
            try:
                lifecycle = project_core_tool_lifecycle(
                    exc.event,
                    run_id=run_id,
                    event_id=self._new_id("evt"),
                    sequence=1,
                    canonical_tool_id=canonical_tool_id,
                    error_code=exc.code,
                )
                metadata["terminal_state"] = lifecycle.kind.value
            except EngineToolProjectionError:
                metadata["terminal_state"] = "failed"
            metadata["tool_event"] = exc.event.to_public_dict()
        return _service_error(
            exc.code,
            exc.safe_message,
            status_code=status_code,
            metadata=metadata,
        )

    async def _execute_via_core(
        self,
        *,
        binding: EngineToolBinding,
        authority: TrustedToolAuthority,
        canonical_tool_id: str,
        invocation: ToolInvocation,
        effective_timeout_seconds: float,
        run_id: str,
    ) -> tuple[ServiceResponse | None, ToolExecutionResult | None, ToolRuntimeError | None]:
        """Single Core ToolRuntime chokepoint shared by execute and resume.

        Returns ``(response, result, runtime_error)``; an approval-class
        ``runtime_error`` lets the caller choose the pause vs. fail-closed
        projection. Only genuine Core ``ToolEvent`` values reach the public
        lifecycle projection here.
        """
        try:
            result = await asyncio.wait_for(
                binding.tool_runtime.execute(
                    invocation,
                    authority.compiled.runtime_profile,
                    authority.authorization,
                ),
                timeout=effective_timeout_seconds + _ENGINE_TIMEOUT_GRACE_SECONDS,
            )
        except ToolRuntimeError as exc:
            if exc.code in _APPROVAL_BLOCK_CODES:
                return None, None, exc
            return self._error_from_tool_runtime(
                exc,
                canonical_tool_id=canonical_tool_id,
                run_id=run_id,
            ), None, None
        except asyncio.TimeoutError:
            return (
                _service_error(
                    "tool_timeout",
                    "The tool did not finish within its effective resource bound.",
                    status_code=504,
                    metadata={
                        "tool_id": canonical_tool_id,
                        "terminal_state": "timed_out",
                    },
                ),
                None,
                None,
            )
        except asyncio.CancelledError:
            # Cancellation is a distinct terminal condition: propagate without
            # converting it into a timeout or internal error response.
            raise
        except Exception:
            return (
                _service_error(
                    "engine_internal_error",
                    "Padiem AI Engine tool execution failed.",
                    status_code=500,
                ),
                None,
                None,
            )

        redacted_output, truncated = project_redacted_tool_output(result.output_copy())
        lifecycle = project_core_tool_lifecycle(
            result.event,
            run_id=run_id,
            event_id=self._new_id("evt"),
            sequence=1,
            canonical_tool_id=canonical_tool_id,
        )
        return (
            ServiceResponse(
                status_code=200,
                body={
                    "ok": True,
                    "tool": {
                        "contract_version": ENGINE_TOOL_CONTRACT_VERSION,
                        "agent_id": authority.canonical_agent_id,
                        "canonical_tool_id": canonical_tool_id,
                        "run_id": run_id,
                        "status": "completed",
                        "output": redacted_output,
                        "output_truncated": truncated,
                        "event": result.event.to_public_dict(),
                        "lifecycle": [lifecycle.to_public_dict()],
                    },
                },
            ),
            result,
            None,
        )

    async def _issue_pause(
        self,
        *,
        exc: ToolRuntimeError,
        app_id: str,
        authority: TrustedToolAuthority,
        canonical_tool_id: str,
        invocation: ToolInvocation,
        run_id: str,
    ) -> ServiceResponse | None:
        """Translate one genuine Core approval block into a server continuation.

        Returns ``None`` when the trusted continuation infrastructure is not
        provisioned so callers fail closed without executing anything.
        """
        if self._approval_decision_verifier is None or not self._continuation_store_is_explicit:
            return None
        if len(self._pending) >= MAX_PENDING_TOOL_CONTINUATIONS:
            raise ServiceContractError(
                "tool_continuation_capacity_exceeded",
                "Tool approval continuation capacity is exhausted.",
                status_code=503,
            )
        created_at = datetime.now(timezone.utc)
        # Reuse the existing Core bridge that converts only genuine
        # ToolRuntime approval blocks into Agent pauses.
        pause = approval_pause_from_tool_error(
            exc,
            pause_id=self._new_id("pause"),
            run_id=run_id,
            agent_runtime_id=authority.compiled.runtime_profile.id,
            invocation=invocation,
            step_index=1,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=_APPROVAL_PAUSE_SECONDS),
        )
        if pause is None:
            return None
        self._pending[pause.pause_id] = _PendingToolContinuation(
            app_id=app_id,
            canonical_agent_id=authority.canonical_agent_id,
            canonical_tool_id=canonical_tool_id,
            invocation=invocation,
        )
        try:
            continuation_ref = await self._continuation_call(
                "issue",
                app_id=app_id,
                pause=pause,
                plan_id=None,
                request_fingerprint=f"toolinv:{pause.invocation_sha256}",
            )
        except ServiceContractError:
            self._pending.pop(pause.pause_id, None)
            raise
        return ServiceResponse(
            status_code=202,
            body={
                "ok": True,
                "tool": {
                    "contract_version": ENGINE_TOOL_CONTRACT_VERSION,
                    "agent_id": authority.canonical_agent_id,
                    "canonical_tool_id": canonical_tool_id,
                    "run_id": run_id,
                    "status": "paused",
                    "continuation_ref": continuation_ref,
                    "approval_pause": pause.to_public_dict(),
                },
            },
        )

    def _prepare_invocation(
        self, payload: Mapping[str, Any]
    ) -> tuple[EngineToolBinding, TrustedToolAuthority, str, ToolInvocation, float, str]:
        wire = parse_tool_execution_request(payload)
        binding = self._resolve_binding(wire.app_id)
        authority = binding.resolve_authority(wire.agent_id)
        entry = binding.resolve_tool(wire.tool_id)
        effective = binding.effective_resources(entry)
        if json_size(wire.arguments) > effective.argument_bytes:
            raise EngineToolProjectionError(
                "tool_arguments_too_large",
                "Tool arguments exceed the effective resource bound.",
            )
        try:
            invocation = ToolInvocation(tool_id=entry.runtime_tool_id, arguments=wire.arguments)
        except (TypeError, ValueError) as exc:
            raise EngineToolProjectionError(
                "invalid_tool_arguments",
                "Tool arguments violate the invocation contract.",
            ) from exc
        run_id = self._new_id("torun")
        return binding, authority, wire.tool_id, invocation, effective.timeout_seconds, run_id

    # ------------------------------------------------------------------
    # public payload handlers
    # ------------------------------------------------------------------

    async def execute_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        try:
            binding, authority, canonical_tool_id, invocation, timeout, run_id = (
                self._prepare_invocation(payload)
            )
            response, result, runtime_error = await self._execute_via_core(
                binding=binding,
                authority=authority,
                canonical_tool_id=canonical_tool_id,
                invocation=invocation,
                effective_timeout_seconds=timeout,
                run_id=run_id,
            )
            if runtime_error is not None:
                pause_response = await self._issue_pause(
                    exc=runtime_error,
                    app_id=binding.app_id,
                    authority=authority,
                    canonical_tool_id=canonical_tool_id,
                    invocation=invocation,
                    run_id=run_id,
                )
                if pause_response is not None:
                    return pause_response
                # Continuation infrastructure unavailable: fail closed. The
                # approval-required tool still executed zero times and no
                # self-grant path exists.
                return _service_error(
                    "approval_verification_unavailable",
                    "Approval continuation requires trusted verification and an explicit continuation store.",
                    status_code=503,
                    metadata={"tool_id": canonical_tool_id, "terminal_state": "paused_unavailable"},
                )
            assert response is not None
            return response
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        data = dict(payload)
        if set(data) - _TOOL_RESUME_ALLOWED:
            return _service_error(
                "invalid_tool_request",
                "Tool continuation accepts only app_id, continuation_ref and decision.",
                status_code=400,
            )
        if not self._continuation_store_is_explicit or self._approval_decision_verifier is None:
            return _service_error(
                "approval_verification_unavailable",
                "Tool continuation requires trusted verification and an explicit continuation store.",
                status_code=503,
            )
        app_id = data.get("app_id")
        try:
            if not isinstance(app_id, str) or not app_id:
                raise EngineToolProjectionError(
                    "invalid_tool_request",
                    "app_id must be a non-empty string.",
                )
            continuation_ref = parse_tool_continuation_ref(data.get("continuation_ref"))
            record = await self._continuation_call(
                "resolve", app_id=app_id, continuation_ref=continuation_ref
            )
            if not isinstance(record, ContinuationRecord):
                raise ServiceContractError(
                    "continuation_store_unavailable",
                    "Approval continuation storage returned an invalid record.",
                    status_code=503,
                )
            submission = _parse_approval_decision_submission(data.get("decision"))
            if submission.pause_id != record.pause.pause_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "decision does not match the server-issued continuation.",
                    status_code=409,
                )
            pending = self._pending.get(record.pause.pause_id)
            if pending is None or pending.app_id != app_id:
                # Without the original server-held invocation a continuation
                # cannot run; callers cannot supply a replacement tool or args.
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "The original tool invocation is not available for this continuation.",
                    status_code=409,
                )
            decision = await self._verify_decision(submission, pause=record.pause, app_id=app_id)
            if (
                decision.decision_id != submission.decision_id
                or decision.pause_id != submission.pause_id
                or decision.outcome is not submission.outcome
                or decision.decided_at != submission.decided_at
            ):
                raise ServiceContractError(
                    "invalid_verified_decision",
                    "Verified decision does not match the submitted decision.",
                    status_code=422,
                )
            state = resolve_approval_pause(
                record.pause,
                decision,
                now=datetime.now(timezone.utc),
            )
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (AgentApprovalError, TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_decision",
                "Approval decision resolution failed.",
                status_code=409,
            )

        if state.status is ContinuationStatus.DENIED:
            return await self._consume_denied(app_id, continuation_ref, record)
        if state.status is not ContinuationStatus.RESUMABLE:
            return _service_error(
                "continuation_expired",
                "The approval continuation is not resumable.",
                status_code=409,
                metadata={"terminal_state": "expired"},
            )

        claimed = await self._continuation_call(
            "claim", app_id=app_id, continuation_ref=continuation_ref
        )
        if not isinstance(claimed, ContinuationRecord) or claimed.claim_token is None:
            return _service_error(
                "continuation_claim_failed",
                "Continuation claim did not return a valid claim token.",
                status_code=503,
            )
        token = claimed.claim_token

        try:
            binding = self._resolve_binding(app_id)
            authority = binding.resolve_authority(pending.canonical_agent_id)
            entry = binding.resolve_tool(pending.canonical_tool_id)
            effective = binding.effective_resources(entry)
            if entry.runtime_tool_id != pending.invocation.tool_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "The paused invocation no longer matches the trusted binding.",
                    status_code=409,
                )
            response, result, runtime_error = await self._execute_via_core(
                binding=binding,
                authority=authority,
                canonical_tool_id=pending.canonical_tool_id,
                invocation=pending.invocation,
                effective_timeout_seconds=effective.timeout_seconds,
                run_id=record.pause.run_id,
            )
        except EngineToolProjectionError as exc:
            await self._release_quietly(app_id, continuation_ref, token)
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ServiceContractError as exc:
            await self._release_quietly(app_id, continuation_ref, token)
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except asyncio.CancelledError:
            await self._release_quietly(app_id, continuation_ref, token)
            raise
        except Exception:
            await self._release_quietly(app_id, continuation_ref, token)
            return _service_error(
                "engine_internal_error",
                "Padiem AI Engine tool resumption failed.",
                status_code=500,
            )

        if runtime_error is not None:
            # The caller asserted approval on the wire but the trusted
            # server-side authority was never granted: the Core approval gate
            # fires again and zero handler calls happened. Release the claim so
            # the continuation remains valid only for a genuine grant.
            await self._release_quietly(app_id, continuation_ref, token)
            return self._error_from_tool_runtime(
                runtime_error,
                canonical_tool_id=pending.canonical_tool_id,
                run_id=record.pause.run_id,
            )
        if result is None:
            await self._release_quietly(app_id, continuation_ref, token)
            assert response is not None
            return response

        try:
            await self._continuation_call(
                "commit",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=token,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        self._pending.pop(record.pause.pause_id, None)
        assert response is not None
        body = dict(response.body)
        tool_body = dict(body.get("tool") or {})
        tool_body["continuation_ref"] = continuation_ref
        body["tool"] = tool_body
        return ServiceResponse(status_code=response.status_code, body=body)

    async def _consume_denied(
        self, app_id: str, continuation_ref: str, record: ContinuationRecord
    ) -> ServiceResponse:
        claimed = await self._continuation_call(
            "claim", app_id=app_id, continuation_ref=continuation_ref
        )
        if not isinstance(claimed, ContinuationRecord) or claimed.claim_token is None:
            return _service_error(
                "continuation_claim_failed",
                "Continuation claim failed.",
                status_code=503,
            )
        try:
            await self._continuation_call(
                "commit",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=claimed.claim_token,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        self._pending.pop(record.pause.pause_id, None)
        return _service_error(
            "approval_denied",
            "Approval decision was denied.",
            status_code=409,
            metadata={"terminal_state": "denied"},
        )

    async def _release_quietly(self, app_id: str, continuation_ref: str, claim_token: str) -> None:
        try:
            await self._continuation_call(
                "release",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=claim_token,
            )
        except ServiceContractError:
            pass

    async def _verify_decision(
        self,
        submission: Any,
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision:
        verifier = self._approval_decision_verifier
        assert verifier is not None
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

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        data = dict(payload)
        if set(data) - _TOOL_CANCEL_ALLOWED:
            return _service_error(
                "invalid_tool_request",
                "Tool cancellation accepts only app_id, continuation_ref and reason.",
                status_code=400,
            )
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        if not self._supports_atomic_cancel:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage does not support atomic cancellation.",
                status_code=503,
            )
        try:
            app_id = data.get("app_id")
            if not isinstance(app_id, str) or not app_id:
                raise EngineToolProjectionError(
                    "invalid_tool_request",
                    "app_id must be a non-empty string.",
                )
            continuation_ref = parse_tool_continuation_ref(data.get("continuation_ref"))
            reason = _parse_cancel_reason(data.get("reason", "user_cancelled"))
            record = await self._continuation_call(
                "resolve", app_id=app_id, continuation_ref=continuation_ref
            )
            if not isinstance(record, ContinuationRecord):
                raise ServiceContractError(
                    "continuation_store_unavailable",
                    "Approval continuation storage returned an invalid record.",
                    status_code=503,
                )
        except EngineToolProjectionError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_request", "Cancellation request fields are invalid.", status_code=400)

        claimed = await self._continuation_call(
            "claim_cancel", app_id=app_id, continuation_ref=continuation_ref, reason=reason
        )
        if not isinstance(claimed, ContinuationRecord) or claimed.state != "cancelling":
            return _service_error(
                "continuation_cancel_claim_failed",
                "Continuation cancel claim did not commit.",
                status_code=503,
            )
        claim_token = claimed.claim_token
        assert claim_token is not None
        try:
            committed = await self._continuation_call(
                "commit_cancel",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=claim_token,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        if not isinstance(committed, ContinuationRecord) or committed.state != "cancelled":
            return _service_error(
                "continuation_cancel_commit_failed",
                "Continuation cancel commit did not persist.",
                status_code=503,
            )
        pending = self._pending.pop(record.pause.pause_id, None)
        lifecycle: list[dict[str, Any]] = []
        if pending is not None:
            # Cancellation of a paused tool is a genuine continuation-state
            # transition committed in trusted storage — never synthetic model
            # output.
            lifecycle.append(
                ToolLifecycleEvent(
                    event_id=self._new_id("evt"),
                    run_id=record.pause.run_id,
                    kind=ToolLifecycleKind.CANCELLED,
                    tool_id=pending.canonical_tool_id,
                    sequence=1,
                ).to_public_dict()
            )
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "status": "cancelled",
                "continuation_ref": continuation_ref,
                "tool": {
                    "contract_version": ENGINE_TOOL_CONTRACT_VERSION,
                    "tool_id": pending.canonical_tool_id if pending is not None else None,
                    "terminal_state": "cancelled",
                    "lifecycle": lifecycle,
                },
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
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path not in {TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH}:
            return _service_error("not_found", "Tool runtime route not found.", status_code=404)
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
        if path == TOOL_EXECUTE_PATH:
            return await self.execute_payload(payload)
        if path == TOOL_RESUME_PATH:
            return await self.resume_payload(payload)
        return await self.cancel_payload(payload)
