"""Server-issued Agent/Skill approval continuation transport (#1749 E4B).

This is transport glue around existing Core approval/resume/cancel semantics and
the existing Engine ContinuationStore/decision verifier contracts.  It creates
no parallel state machine and never treats an approval decision as Tool
authority: a trusted ToolAuthorizationContext must independently contain the
single permitted approval delta before Core resume can execute.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import inspect
from typing import Any

from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision
from padiem_ai_core.execution_context import ExecutionContext
from padiem_ai_core.orchestration import OrchestrationError, OrchestrationResumeRequest, OrchestrationRunner

from app.agent_skill_authority import EngineAgentSkillBinding
from app.agent_skill_continuation import (
    AgentSkillContinuationError,
    AgentSkillContinuationFingerprint,
    assert_resume_identity,
    issue_fingerprint,
)
from app.agent_skill_projection import project_agent_skill_result
from app.agent_skill_wire import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    build_trusted_agent_skill_request,
    execution_request_with_trace,
    parse_tool_arguments,
)
from app.orchestration_continuation import ContinuationRecord, ContinuationStore
from app.orchestration_wire import (
    _parse_approval_decision_submission,
    _parse_cancel_reason,
    _parse_continuation_ref,
)
from app.service import ServiceContractError, ServiceResponse, _service_error


class AgentSkillContinuationCoordinator:
    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        binding_resolver: Callable[[str], EngineAgentSkillBinding],
        approval_decision_verifier: Any | None = None,
        continuation_store: ContinuationStore | None = None,
        idempotency_adapter: Any | None = None,
    ) -> None:
        if not callable(runtime_factory) or not callable(binding_resolver):
            raise ValueError("runtime_factory and binding_resolver must be callable")
        if approval_decision_verifier is not None and not callable(
            getattr(approval_decision_verifier, "verify", None)
        ):
            raise ValueError("approval_decision_verifier must provide verify()")
        if continuation_store is not None:
            for name in ("issue", "resolve", "claim", "commit", "release"):
                if not callable(getattr(continuation_store, name, None)):
                    raise ValueError(f"continuation_store must provide {name}()")
        self._runtime_factory = runtime_factory
        self._binding_resolver = binding_resolver
        self._verifier = approval_decision_verifier
        self._store = continuation_store
        self._idempotency = idempotency_adapter
        self._atomic_cancel = continuation_store is not None and all(
            callable(getattr(continuation_store, name, None))
            for name in ("claim_cancel", "commit_cancel", "release_cancel")
        )

    @property
    def available(self) -> bool:
        return self._store is not None and self._verifier is not None

    async def _store_call(self, method: str, **kwargs: Any) -> Any:
        if self._store is None:
            raise ServiceContractError(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            )
        try:
            result = getattr(self._store, method)(**kwargs)
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

    async def _verify(self, submission: Any, *, record: ContinuationRecord) -> VerifiedApprovalDecision:
        if self._verifier is None:
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Approval decision verification is unavailable.",
                status_code=503,
            )
        try:
            verified = self._verifier.verify(
                submission,
                pause=record.pause,
                app_id=record.app_id,
            )
            if inspect.isawaitable(verified):
                verified = await verified
        except ServiceContractError:
            raise
        except Exception as exc:
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Approval decision verification failed.",
                status_code=503,
            ) from exc
        if not isinstance(verified, VerifiedApprovalDecision):
            raise ServiceContractError(
                "invalid_verified_decision",
                "Approval decision verification returned invalid evidence.",
                status_code=422,
            )
        if (
            verified.decision_id != submission.decision_id
            or verified.pause_id != submission.pause_id
            or verified.outcome is not submission.outcome
            or verified.decided_at != submission.decided_at
        ):
            raise ServiceContractError(
                "invalid_verified_decision",
                "Verified decision does not match the submitted decision.",
                status_code=422,
            )
        return verified

    async def _abort_idempotency(self, *, app_id: str, context: ExecutionContext, reason: str) -> None:
        if context.idempotency_key is None or self._idempotency is None:
            return
        try:
            if callable(getattr(self._idempotency, "abort", None)):
                result = self._idempotency.abort(
                    app_id=app_id,
                    idempotency_key=context.idempotency_key,
                    reason=reason,
                )
            elif callable(getattr(self._idempotency, "release", None)):
                result = self._idempotency.release(
                    app_id=app_id,
                    idempotency_key=context.idempotency_key,
                )
            else:
                return
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    async def issue(
        self,
        *,
        app_id: str,
        binding: EngineAgentSkillBinding,
        wire: Any,
        execution_request: Any,
        context: ExecutionContext,
        tool_arguments: Mapping[str, Mapping[str, Any]],
        pause: Any,
    ) -> str:
        if not self.available:
            await self._abort_idempotency(
                app_id=app_id,
                context=context,
                reason="approval_continuation_unavailable",
            )
            raise ServiceContractError(
                "approval_verification_unavailable",
                "Agent/Skill approval continuation requires trusted verification and durable storage.",
                status_code=503,
            )
        if pause.trace_id is None or pause.trace_id != context.trace_id:
            raise ServiceContractError(
                "invalid_continuation",
                "Approval pause is missing trusted trace identity.",
                status_code=500,
            )
        try:
            fingerprint = issue_fingerprint(
                binding=binding,
                selection=wire.selection,
                execution_request=execution_request,
                context=context,
                tool_arguments=tool_arguments,
                pause=pause,
            ).encode()
            return await self._store_call(
                "issue",
                app_id=app_id,
                pause=pause,
                plan_id=wire.selection.plan.agent_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=fingerprint,
            )
        except AgentSkillContinuationError as exc:
            await self._abort_idempotency(app_id=app_id, context=context, reason=exc.code)
            raise ServiceContractError(exc.code, exc.safe_message, status_code=exc.status_code) from exc
        except ServiceContractError:
            await self._abort_idempotency(
                app_id=app_id,
                context=context,
                reason="continuation_issue_failed",
            )
            raise

    async def resume_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        if not self.available:
            return _service_error(
                "continuation_store_unavailable",
                "Agent/Skill approval continuation is unavailable.",
                status_code=503,
            )
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        app_id = app_id.strip()

        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = await self._store_call("resolve", app_id=app_id, continuation_ref=continuation_ref)
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
                    "Decision does not match the server-issued continuation.",
                    status_code=409,
                )
            run_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"continuation_ref", "decision"}
            }
            if "trace_id" not in run_payload and "execution_context" not in run_payload:
                if record.pause.trace_id is None:
                    raise ServiceContractError(
                        "continuation_identity_mismatch",
                        "Continuation is missing trusted trace identity.",
                        status_code=409,
                    )
                run_payload["trace_id"] = record.pause.trace_id

            binding = self._binding_resolver(app_id)
            wire = build_trusted_agent_skill_request(run_payload, binding=binding)
            execution_request = wire.execution_request
            context = wire.context
            if context is None:
                trace_id = execution_request.trace_id or record.pause.trace_id
                if trace_id is None:
                    raise ServiceContractError(
                        "continuation_identity_mismatch",
                        "Resume input is missing trusted trace identity.",
                        status_code=409,
                    )
                execution_request = execution_request_with_trace(execution_request, trace_id)
                context = ExecutionContext(trace_id=trace_id)
            if context.trace_id != record.pause.trace_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Resume trace does not match the server-issued continuation.",
                    status_code=409,
                )
            if record.plan_id != wire.selection.plan.agent_id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Resume Agent does not match the server-issued continuation.",
                    status_code=409,
                )
            if record.pause.agent_runtime_id != wire.selection.authority.compiled.runtime_profile.id:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Resume runtime identity does not match the server-issued continuation.",
                    status_code=409,
                )
            if record.idempotency_key != context.idempotency_key:
                raise ServiceContractError(
                    "idempotency_conflict",
                    "Idempotency identity does not match the server-issued continuation.",
                    status_code=409,
                )

            tool_arguments = parse_tool_arguments(wire.raw_tool_arguments)
            stored = AgentSkillContinuationFingerprint.decode(record.request_fingerprint)
            decision = await self._verify(submission, record=record)
            assert_resume_identity(
                stored=stored,
                binding=binding,
                selection=wire.selection,
                execution_request=execution_request,
                context=context,
                tool_arguments=tool_arguments,
                pause=record.pause,
                approved=decision.outcome is ApprovalOutcome.APPROVED,
            )
            resume_request = OrchestrationResumeRequest(
                pause=record.pause,
                decision=decision,
                execution_request=execution_request,
                context=context,
                app_id=app_id,
                subject_id=wire.selection.subject_id,
                agent_definition=wire.selection.authority.definition,
                compiled_agent_profile=wire.selection.authority.compiled,
                agent_plan=wire.selection.plan,
                tool_authorization=wire.selection.authority.authorization,
                tool_runtime=binding.tool_binding.tool_runtime,
                tool_arguments=tool_arguments,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except AgentSkillContinuationError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except Exception as exc:
            code = getattr(exc, "code", None)
            message = getattr(exc, "safe_message", None)
            if isinstance(code, str) and isinstance(message, str):
                return _service_error(code, message, status_code=403)
            return _service_error("invalid_request", "Agent/Skill resume fields are invalid.", status_code=400)

        try:
            claimed = await self._store_call("claim", app_id=app_id, continuation_ref=continuation_ref)
            if not isinstance(claimed, ContinuationRecord) or claimed.claim_token is None:
                raise ServiceContractError(
                    "continuation_claim_failed",
                    "Continuation claim did not return a valid claim token.",
                    status_code=503,
                )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        claim_token = claimed.claim_token
        assert claim_token is not None
        try:
            result = await OrchestrationRunner(
                runtime=self._runtime_factory(app_id),
                idempotency=self._idempotency,
            ).resume(resume_request)
        except OrchestrationError as exc:
            method = "commit" if exc.code == "approval_denied" else "release"
            try:
                await self._store_call(
                    method,
                    app_id=app_id,
                    continuation_ref=continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError as store_exc:
                return _service_error(store_exc.code, store_exc.safe_message, status_code=store_exc.status_code)
            status = 403 if exc.code in {"missing_approval_authorization", "authorization_denied", "authority_widening_rejected"} else 409 if exc.code in {"approval_denied", "continuation_expired", "continuation_identity_mismatch"} else 422
            return _service_error(exc.code, exc.safe_message, status_code=status)
        except asyncio.CancelledError:
            try:
                await self._store_call(
                    "release",
                    app_id=app_id,
                    continuation_ref=continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            raise
        except Exception:
            try:
                await self._store_call(
                    "release",
                    app_id=app_id,
                    continuation_ref=continuation_ref,
                    claim_token=claim_token,
                )
            except ServiceContractError:
                pass
            return _service_error("engine_internal_error", "Agent/Skill resumption failed.", status_code=500)

        try:
            await self._store_call(
                "commit",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=claim_token,
            )
            projection = project_agent_skill_result(result, selection=wire.selection)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError):
            return _service_error(
                "invalid_agent_skill_result",
                "Agent/Skill resume returned an invalid public projection.",
                status_code=500,
            )
        return ServiceResponse(status_code=200, body={"ok": True, "agent_skill": projection})

    async def cancel_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)
        if self._store is None or not self._atomic_cancel:
            return _service_error(
                "continuation_store_unavailable",
                "Agent/Skill continuation storage does not support atomic cancellation.",
                status_code=503,
            )
        if set(payload) - {"app_id", "continuation_ref", "reason"}:
            return _service_error("invalid_request", "Cancellation contains unsupported fields.", status_code=400)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        app_id = app_id.strip()
        try:
            continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
            record = await self._store_call("resolve", app_id=app_id, continuation_ref=continuation_ref)
            if not isinstance(record, ContinuationRecord) or record.pause.trace_id is None:
                raise ServiceContractError(
                    "continuation_identity_mismatch",
                    "Continuation is missing trusted identity.",
                    status_code=409,
                )
            reason = _parse_cancel_reason(payload.get("reason", "user_cancelled"))
            claimed = await self._store_call(
                "claim_cancel",
                app_id=app_id,
                continuation_ref=continuation_ref,
                reason=reason,
            )
            if not isinstance(claimed, ContinuationRecord) or claimed.claim_token is None:
                raise ServiceContractError(
                    "continuation_cancel_claim_failed",
                    "Continuation cancel claim failed.",
                    status_code=503,
                )
            events = OrchestrationRunner(runtime=self._runtime_factory(app_id)).cancel_pause(
                claimed.pause,
                trace_id=claimed.pause.trace_id,
                reason=reason,
            )
            committed = await self._store_call(
                "commit_cancel",
                app_id=app_id,
                continuation_ref=continuation_ref,
                claim_token=claimed.claim_token,
            )
            if not isinstance(committed, ContinuationRecord) or committed.state != "cancelled":
                raise ServiceContractError(
                    "continuation_cancel_commit_failed",
                    "Continuation cancellation did not persist.",
                    status_code=503,
                )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except OrchestrationError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=409)
        except Exception:
            return _service_error("engine_internal_error", "Agent/Skill cancellation failed.", status_code=500)
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "status": "cancelled",
                "events": [event.to_public_dict() for event in events],
            },
        )
