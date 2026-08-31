"""Identity-bound orchestration service wiring for approval continuations.

This service keeps the existing Engine wire contract but replaces the legacy
partial continuation fingerprint with one canonical execution identity. Identity
comparison occurs before approval verification, continuation claim, or Core
resume execution.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from padiem_ai_core import (
    ExecutionContext,
    IdempotencyConflictError,
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationResumeRequest,
    OrchestrationRunner,
)

from app.continuation_binding import IdentityBoundContinuationRecord
from app.continuation_identity import (
    build_continuation_execution_identity,
    continuation_identity_matches,
)
from app.orchestration_service import (
    OrchestrationEngineService,
    _parse_agent_plan,
    _parse_approval_decision_submission,
    _parse_continuation_ref,
    _parse_recovery_policy,
)
from app.service import ServiceContractError, ServiceResponse, _service_error, build_execution_request


_ORCHESTRATE_ALLOWED_FIELDS = frozenset(
    {
        "app_id",
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
        "subject_id",
        "agent_plan",
        "recovery_policy",
        "max_retries",
        "require_evidence",
        "require_verification",
    }
)
_RESUME_ALLOWED_FIELDS = _ORCHESTRATE_ALLOWED_FIELDS | {"continuation_ref", "decision"}


def _reject_unknown_fields(payload: Mapping[str, Any], *, allowed: frozenset[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ServiceContractError(
            "unsupported_orchestration_field",
            "Request contains unsupported orchestration fields.",
            status_code=400,
        )


class IdentityBoundOrchestrationEngineService(OrchestrationEngineService):
    """OrchestrationEngineService with full continuation execution binding."""

    async def _identity_orchestration_body(
        self,
        result: Any,
        *,
        request: OrchestrationRequest,
    ) -> dict[str, Any]:
        body = result.to_public_dict()
        pause = result.approval_pause
        if pause is None:
            return body
        if self._approval_decision_verifier is None or not self._continuation_store_is_explicit:
            await self._abort_idempotency(
                app_id=request.app_id,
                context=result.context,
                reason="approval_continuation_unavailable",
            )
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Approval continuation requires trusted verification and an explicit continuation store.",
                status_code=503,
            )
        if pause.trace_id is None:
            await self._abort_idempotency(
                app_id=request.app_id,
                context=result.context,
                reason="invalid_continuation",
            )
            raise ServiceContractError(
                "invalid_continuation",
                "Approval pause is missing trusted continuation identity.",
                status_code=500,
            )
        identity = build_continuation_execution_identity(
            app_id=request.app_id,
            request=request.execution_request,
            context=result.context,
            subject_id=request.subject_id,
            plan=result.plan if result.plan is not None else request.agent_plan,
            recovery_policy=request.recovery_policy,
            max_retries=request.max_retries,
            require_evidence=request.require_evidence,
            require_verification=request.require_verification,
        )
        try:
            body["continuation_ref"] = await self._continuation_call(
                "issue",
                app_id=request.app_id,
                pause=pause,
                execution_identity=identity,
            )
        except ServiceContractError:
            await self._abort_idempotency(
                app_id=request.app_id,
                context=result.context,
                reason="continuation_issue_failed",
            )
            raise
        return body

    async def orchestrate_payload(self, payload: Any) -> ServiceResponse:
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        try:
            _reject_unknown_fields(payload, allowed=_ORCHESTRATE_ALLOWED_FIELDS)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        try:
            _, exec_req, ctx = build_execution_request({
                k: payload[k]
                for k in (
                    "app_id", "agent", "messages", "session_id",
                    "additional_system_context", "trace_id", "execution_context",
                )
                if k in payload
            })
            if ctx is None:
                ctx = ExecutionContext(trace_id=exec_req.trace_id or "orch_trace")
            plan = _parse_agent_plan(payload.get("agent_plan"))
            rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
            max_retries = int(payload.get("max_retries", 3))
            require_evidence = bool(payload.get("require_evidence", False))
            require_verification = bool(payload.get("require_verification", False))
            orch_req = OrchestrationRequest(
                execution_request=exec_req,
                context=ctx,
                app_id=app_id,
                subject_id=payload.get("subject_id"),
                agent_plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
                require_evidence=require_evidence,
                require_verification=require_verification,
            )
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.run(orch_req)
        except IdempotencyConflictError:
            return _service_error(
                "idempotency_conflict",
                "Idempotency key is already bound to a different execution request.",
                status_code=409,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except OrchestrationError as exc:
            status_code = 422 if exc.code in {"invalid_plan", "authority_widening_rejected"} else 400
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except (TypeError, ValueError):
            return _service_error("invalid_request", "Orchestration request is invalid.", status_code=400)
        except Exception:
            return _service_error("engine_internal_error", "Orchestration execution failed.", status_code=500)
        try:
            orchestration_body = await self._identity_orchestration_body(result, request=orch_req)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        return ServiceResponse(status_code=200, body={"ok": True, "orchestration": orchestration_body})

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        try:
            _reject_unknown_fields(payload, allowed=_RESUME_ALLOWED_FIELDS)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        if not self._continuation_store_is_explicit:
            return _service_error(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = await self._continuation_call(
                "resolve", app_id=app_id, continuation_ref=continuation_ref
            )
            if not isinstance(record, IdentityBoundContinuationRecord):
                raise ServiceContractError(
                    "continuation_store_unavailable",
                    "Approval continuation storage returned an invalid identity-bound record.",
                    status_code=503,
                )
            submission = _parse_approval_decision_submission(payload.get("decision"))
            if submission.pause_id != record.pause.pause_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Decision does not match the server-issued continuation.",
                    status_code=409,
                )
            _, exec_req, ctx = build_execution_request({
                k: payload[k]
                for k in (
                    "app_id", "agent", "messages", "session_id",
                    "additional_system_context", "trace_id", "execution_context",
                )
                if k in payload
            })
            if ctx is None:
                ctx = ExecutionContext(
                    trace_id=exec_req.trace_id or record.pause.trace_id or "orch_resume_trace"
                )
            plan = _parse_agent_plan(payload.get("agent_plan"))
            rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
            max_retries = int(payload.get("max_retries", 3))
            require_evidence = bool(payload.get("require_evidence", False))
            require_verification = bool(payload.get("require_verification", False))
            candidate_identity = build_continuation_execution_identity(
                app_id=app_id,
                request=exec_req,
                context=ctx,
                subject_id=payload.get("subject_id"),
                plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
                require_evidence=require_evidence,
                require_verification=require_verification,
            )
            if not continuation_identity_matches(record.execution_identity, candidate_identity):
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Resume execution identity does not match the server-issued continuation.",
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
            claimed_record = await self._continuation_call(
                "claim", app_id=app_id, continuation_ref=record.continuation_ref
            )
            if (
                not isinstance(claimed_record, IdentityBoundContinuationRecord)
                or claimed_record.claim_token is None
            ):
                raise ServiceContractError(
                    "continuation_claim_failed",
                    "Continuation claim did not return a valid claim token.",
                    status_code=503,
                )
            record = claimed_record
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError):
            return _service_error("invalid_request", "Resume request is invalid.", status_code=400)

        claim_token = record.claim_token
        assert claim_token is not None
        try:
            resume_req = OrchestrationResumeRequest(
                pause=record.pause,
                decision=decision,
                execution_request=exec_req,
                context=ctx,
                app_id=app_id,
                subject_id=payload.get("subject_id"),
                agent_plan=plan,
                recovery_policy=rec_policy,
                max_retries=max_retries,
                require_evidence=require_evidence,
                require_verification=require_verification,
            )
            runtime = self._runtime_factory(app_id)
            runner = OrchestrationRunner(runtime=runtime, idempotency=self._idempotency_adapter)
            result = await runner.resume(resume_req)
        except OrchestrationError as exc:
            method = "commit" if exc.code == "approval_denied" else "release"
            try:
                await self._continuation_call(
                    method,
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError as state_exc:
                return _service_error(state_exc.code, state_exc.safe_message, status_code=state_exc.status_code)
            status_code = 409 if exc.code in {
                "continuation_expired", "approval_denied", "continuation_identity_mismatch"
            } else 422
            return _service_error(exc.code, exc.safe_message, status_code=status_code)
        except asyncio.CancelledError:
            try:
                await self._continuation_call(
                    "release",
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            raise
        except Exception:
            try:
                await self._continuation_call(
                    "release",
                    app_id=app_id,
                    continuation_ref=record.continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError as state_exc:
                return _service_error(state_exc.code, state_exc.safe_message, status_code=state_exc.status_code)
            return _service_error("engine_internal_error", "Orchestration resumption failed.", status_code=500)

        try:
            await self._continuation_call(
                "commit",
                app_id=app_id,
                continuation_ref=record.continuation_ref,
                claim_token=claim_token,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        try:
            orchestration_body = await self._identity_orchestration_body(
                result,
                request=OrchestrationRequest(
                    execution_request=exec_req,
                    context=ctx,
                    app_id=app_id,
                    subject_id=payload.get("subject_id"),
                    agent_plan=plan,
                    recovery_policy=rec_policy,
                    max_retries=max_retries,
                    require_evidence=require_evidence,
                    require_verification=require_verification,
                ),
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        return ServiceResponse(status_code=200, body={"ok": True, "orchestration": orchestration_body})
