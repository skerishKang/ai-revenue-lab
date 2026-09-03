"""Trusted execution-admission enforcement for Engine orchestration runs.

This service is source-only and product-neutral. It composes the accepted
canonical idempotency/continuation service with the #1241 trusted admission gate,
persisting the validated run admission into any approval continuation issued by
that admitted execution and enforcing fresh non-widening resume admission before
any continuation claim or Core resume.

It is intentionally not wired into the active Worker until a trusted server
adapter is injected via Worker composition (CONTROL_PLANE_LIVE_ADAPTER = NOT_DONE).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from padiem_ai_core import (
    ExecutionContext,
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
from app.execution_admission import ExecutionAdmissionError, ExecutionAdmissionRequest
from app.execution_admission_gate import resolve_and_require_trusted_admission
from app.execution_admission_resume import (
    ORCHESTRATION_RESUME_CAPABILITY,
    OriginalAdmissionBinding,
    require_non_widening_resume_admission,
)
from app.idempotency_identity import (
    reset_canonical_idempotency_fingerprint,
    set_canonical_idempotency_fingerprint,
)
from app.orchestration_idempotency_service import (
    CanonicalIdempotencyOrchestrationEngineService,
    _initial_execution_fingerprint,
)
from app.orchestration_identity_service import (
    _ORCHESTRATE_ALLOWED_FIELDS,
    _RESUME_ALLOWED_FIELDS,
    _reject_unknown_fields,
)
from app.orchestration_service import (
    _parse_agent_plan,
    _parse_approval_decision_submission,
    _parse_continuation_ref,
    _parse_orchestration_options,
    _parse_recovery_policy,
)
from app.service import (
    ServiceContractError,
    _service_error,
    build_execution_request,
)


ORCHESTRATION_RUN_CAPABILITY = "orchestration.run"


_ACTIVE_ORIGINAL_ADMISSION: ContextVar[OriginalAdmissionBinding | None] = ContextVar(
    "padiem_engine_active_original_admission",
    default=None,
)


def _run_admission_request(payload: Any) -> ExecutionAdmissionRequest | None:
    """Build a server-owned admission query only for an otherwise parseable run.

    The request fingerprint is the canonical material logical-execution identity
    from #1235/#1594. Client entitlement/plan/credit/allow fields are not inputs
    and remain rejected by the Engine orchestration wire contract.
    """

    if not isinstance(payload, Mapping):
        return None
    try:
        _reject_unknown_fields(payload, allowed=_ORCHESTRATE_ALLOWED_FIELDS)
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return None
        _, _, _, subject_id, _, _ = _parse_orchestration_options(payload)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return None
        return ExecutionAdmissionRequest(
            app_id=app_id,
            subject_id=subject_id,
            capability=ORCHESTRATION_RUN_CAPABILITY,
            request_fingerprint=fingerprint,
        )
    except (ServiceContractError, ExecutionAdmissionError, TypeError, ValueError):
        return None


def _resume_admission_request(payload: Any) -> ExecutionAdmissionRequest | None:
    """Build a server-owned resume admission query from validated resume wire data."""

    if not isinstance(payload, Mapping):
        return None
    try:
        _reject_unknown_fields(payload, allowed=_RESUME_ALLOWED_FIELDS)
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return None
        _, _, _, subject_id, _, _ = _parse_orchestration_options(payload)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return None
        return ExecutionAdmissionRequest(
            app_id=app_id,
            subject_id=subject_id,
            capability=ORCHESTRATION_RESUME_CAPABILITY,
            request_fingerprint=fingerprint,
        )
    except (ServiceContractError, ExecutionAdmissionError, TypeError, ValueError):
        return None


def _loose_run_would_execute(payload: Any) -> bool:
    """Detect whether the identity service would reach Core for this payload.

    The admission service uses strict parsing for its fingerprint, while the
    underlying identity service historically coerces ``max_retries`` via ``int()``
    and evidence flags via ``bool()`` without validating ``subject_id``. When
    strict admission binding cannot be built but loose validation would still
    execute Core, delegating to ``super()`` would bypass trusted admission.
    This helper detects that bypass case so the caller can fail closed.
    """

    try:
        if not isinstance(payload, Mapping):
            return False
        _reject_unknown_fields(payload, allowed=_ORCHESTRATE_ALLOWED_FIELDS)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return False
        _, exec_req, ctx = build_execution_request(
            {
                k: payload[k]
                for k in (
                    "app_id",
                    "agent",
                    "messages",
                    "session_id",
                    "additional_system_context",
                    "trace_id",
                    "execution_context",
                )
                if k in payload
            }
        )
        if ctx is None:
            # Super fills a default context and continues toward Core.
            pass
        # Loose plan/recovery parsing mirrors IdentityBoundOrchestrationEngineService.
        _parse_agent_plan(payload.get("agent_plan"))
        _parse_recovery_policy(payload.get("recovery_policy"))
        int(payload.get("max_retries", 3))
        bool(payload.get("require_evidence", False))
        bool(payload.get("require_verification", False))
        return True
    except Exception:
        return False


class AdmissionBoundOrchestrationEngineService(CanonicalIdempotencyOrchestrationEngineService):
    """Require trusted server admission before orchestration run and resume."""

    def __init__(self, *args: Any, admission_adapter: Any | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._admission_adapter = admission_adapter

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
        from app.continuation_identity import build_continuation_execution_identity as _build_identity

        identity = _build_identity(
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
        original = _ACTIVE_ORIGINAL_ADMISSION.get()
        if not isinstance(original, OriginalAdmissionBinding):
            # Admission-aware Worker activation must never issue a new unbound
            # approval continuation. Fail closed instead of silently dropping
            # required original-admission evidence.
            await self._abort_idempotency(
                app_id=request.app_id,
                context=result.context,
                reason="continuation_issue_failed",
            )
            raise ServiceContractError(
                "entitlement_unavailable",
                "Trusted execution admission is required to issue an approval continuation.",
                status_code=503,
            )
        try:
            body["continuation_ref"] = await self._continuation_call(
                "issue",
                app_id=request.app_id,
                pause=pause,
                execution_identity=identity,
                original_admission=original,
            )
        except ServiceContractError:
            await self._abort_idempotency(
                app_id=request.app_id,
                context=result.context,
                reason="continuation_issue_failed",
            )
            raise
        return body

    async def orchestrate_payload(self, payload: Any):
        # Preserve the existing wire-validation response for malformed/unsupported
        # requests rather than masking contract errors behind entitlement status.
        admission_request = _run_admission_request(payload)
        if admission_request is None:
            if _loose_run_would_execute(payload):
                # Strict admission binding failed but the underlying service
                # would still execute Core (e.g. non-bool evidence flag, bool
                # max_retries, or unsafe identifier). Fail closed instead of
                # running without trusted admission.
                return _service_error(
                    "entitlement_request_mismatch",
                    "Trusted execution admission is not bound to this orchestration request.",
                    status_code=403,
                )
            return await super().orchestrate_payload(payload)

        try:
            admission = await resolve_and_require_trusted_admission(
                adapter=self._admission_adapter,
                request=admission_request,
            )
            # The generic admission contract allows an unbound decision for less
            # sensitive capabilities. Engine orchestration does not: admission
            # must explicitly bind the canonical server-derived logical request.
            if (
                admission_request.request_fingerprint is None
                or admission.request_fingerprint != admission_request.request_fingerprint
            ):
                raise ExecutionAdmissionError(
                    "entitlement_request_mismatch",
                    "Trusted execution admission is not bound to this orchestration request.",
                    status_code=403,
                )
            try:
                binding = OriginalAdmissionBinding.from_run_admission(admission)
            except ExecutionAdmissionError as exc:
                raise exc
        except ExecutionAdmissionError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
                retryable=exc.status_code >= 500,
            )

        token: Token[OriginalAdmissionBinding | None] = _ACTIVE_ORIGINAL_ADMISSION.set(binding)
        try:
            return await super().orchestrate_payload(payload)
        finally:
            _ACTIVE_ORIGINAL_ADMISSION.reset(token)

    async def resume_payload(self, payload: Any):  # noqa: C901 - lifecycle gate must stay linear
        """Resume only with fresh non-widening trusted admission before claim."""
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
            _, exec_req, ctx = build_execution_request(
                {
                    k: payload[k]
                    for k in (
                        "app_id",
                        "agent",
                        "messages",
                        "session_id",
                        "additional_system_context",
                        "trace_id",
                        "execution_context",
                    )
                    if k in payload
                }
            )
            if ctx is None:
                ctx = ExecutionContext(
                    trace_id=exec_req.trace_id or record.pause.trace_id or "orch_resume_trace"
                )
            plan = _parse_agent_plan(payload.get("agent_plan"))
            rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
            try:
                max_retries = int(payload.get("max_retries", 3))
            except (TypeError, ValueError):
                raise ServiceContractError(
                    "invalid_max_retries", "max_retries must be an integer."
                ) from None
            if isinstance(max_retries, bool) or not 0 <= max_retries <= 10:
                raise ServiceContractError(
                    "invalid_max_retries", "max_retries must be between 0 and 10."
                )
            require_evidence = payload.get("require_evidence", False)
            require_verification = payload.get("require_verification", False)
            if not isinstance(require_evidence, bool) or not isinstance(require_verification, bool):
                raise ServiceContractError(
                    "invalid_request", "Resume evidence flags must be booleans.", status_code=400
                )
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
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError):
            return _service_error("invalid_request", "Resume request is invalid.", status_code=400)

        # Admission-aware gate: stored original run admission is required.
        original = record.original_admission
        if not isinstance(original, OriginalAdmissionBinding):
            return _service_error(
                "missing_entitlement",
                "Trusted execution admission is required to resume this continuation.",
                status_code=403,
            )

        resume_request = _resume_admission_request(payload)
        if resume_request is None:
            return _service_error(
                "invalid_request", "Resume request fields are invalid.", status_code=400
            )

        try:
            current = await resolve_and_require_trusted_admission(
                adapter=self._admission_adapter,
                request=resume_request,
            )
            require_non_widening_resume_admission(
                original=original,
                current=current,
                expected_request_fingerprint=resume_request.request_fingerprint,  # type: ignore[arg-type]
            )
            # The non-widening rule already requires the current resume decision
            # to bind the same canonical fingerprint as the original run. Keep an
            # explicit guard so a future rule relaxation cannot silently widen the
            # paused execution via a mismatched stored binding.
            if original.request_fingerprint != resume_request.request_fingerprint:
                raise ExecutionAdmissionError(
                    "continuation_admission_mismatch",
                    "Paused execution admission does not match the continuation request identity.",
                    status_code=409,
                )
        except ExecutionAdmissionError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
                retryable=exc.status_code >= 500,
            )

        # Pre-mutation validation for remaining resume fields and decision
        # verification happens before claim; failures leave ACTIVE unclaimed.
        try:
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
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        # Fingerprint-scoped Core idempotency (mirrors CanonicalIdempotency service).
        fingerprint_token: Token[str | None] | None = None
        try:
            if resume_request.request_fingerprint is not None:
                fingerprint_token = set_canonical_idempotency_fingerprint(
                    resume_request.request_fingerprint
                )
        except ValueError:
            return _service_error(
                "invalid_request", "Resume request fields are invalid.", status_code=400
            )

        try:
            try:
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

            claim_token = record.claim_token
            assert claim_token is not None
            original_token = _ACTIVE_ORIGINAL_ADMISSION.set(original)
            try:
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
                        return _service_error(
                            state_exc.code, state_exc.safe_message, status_code=state_exc.status_code
                        )
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
                        return _service_error(
                            state_exc.code, state_exc.safe_message, status_code=state_exc.status_code
                        )
                    return _service_error(
                        "engine_internal_error", "Orchestration resumption failed.", status_code=500
                    )

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
                from app.service import ServiceResponse as _ServiceResponse

                return _ServiceResponse(
                    status_code=200, body={"ok": True, "orchestration": orchestration_body}
                )
            finally:
                _ACTIVE_ORIGINAL_ADMISSION.reset(original_token)
        finally:
            if fingerprint_token is not None:
                reset_canonical_idempotency_fingerprint(fingerprint_token)
