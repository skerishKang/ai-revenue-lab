"""Bounded trusted Agent/Skill transport over Core orchestration (#1749 E4).

Caller identity/input parsing is isolated in ``agent_skill_wire``; server-issued
approval lifecycle is isolated in ``agent_skill_continuation_service``.  This
service remains a thin composition layer over Core OrchestrationRunner,
AgentPlanExecutor, BoundedAgentRuntime and ToolRuntime.  It creates no parallel
Agent runtime, Tool authority, approval state machine, or Provider router.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import asyncio
import json
import secrets
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext, IdempotencyConflictError
from padiem_ai_core.orchestration import OrchestrationError, OrchestrationRequest, OrchestrationRunner
from padiem_ai_core.logical_execution_identity import canonical_logical_execution_fingerprint
from padiem_ai_core.agent_durable_lease import AgentDurableLeaseError
from padiem_ai_core.skill_registry import SkillRegistryError
from padiem_ai_core.skill_runtime_adapter import SkillRuntimeAdapterError

from app.agent_skill_authority import EngineAgentSkillAuthorityError, EngineAgentSkillBinding
from app.agent_durable_d1 import (
    DEFAULT_EXPIRED_SWEEP_LIMIT,
    AgentRunCancelOutcome,
    D1AgentRunLedger,
    agent_run_owner_scope,
)
from app.agent_skill_continuation_service import AgentSkillContinuationCoordinator
from app.agent_skill_projection import project_agent_skill_result
from app.agent_skill_wire import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    AGENT_SKILL_RUN_CANCEL_PATH,
    AGENT_SKILL_RUN_PATH,
    AGENT_SKILL_RUN_RECOVERY_PATH,
    AGENT_SKILL_RUN_STATUS_PATH,
    AUTHORITY_SHAPED_KEYS,
    TRUSTED_AGENT_SKILL_ALLOWED,
    TRUSTED_AGENT_SKILL_REQUIRED,
    TrustedAgentSkillWireRequest,
    TrustedAgentRunControlTarget,
    TrustedAgentRunRecoveryRequest,
    build_trusted_agent_run_control,
    build_trusted_agent_run_recovery,
    build_trusted_agent_skill_request,
    execution_request_with_trace,
    parse_tool_arguments,
)
from app.orchestration_continuation import ContinuationStore
from app.service import MAX_REQUEST_BODY_BYTES, ServiceContractError, ServiceResponse, _service_error
from app.tool_projection import EngineToolProjectionError


class AgentRunCancelledError(RuntimeError):
    """An owner-requested cancel fenced this run before its next dispatch.

    Not an approval, not a rollback claim: any external side effect that may
    already have happened stays ``side_effect_uncertain`` in the D1 ledger.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__("Agent run was cancelled by its owner")
        self.code = "agent_run_cancelled"
        self.run_id = run_id


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
        agent_run_ledger: D1AgentRunLedger | None = None,
        agent_run_recovery_enabled: bool = False,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if binding_resolver is not None and not callable(binding_resolver):
            raise ValueError("binding_resolver must be callable")
        if type(agent_run_recovery_enabled) is not bool:
            raise ValueError("agent_run_recovery_enabled must be a boolean")
        self._runtime_factory = runtime_factory
        self._binding_resolver = binding_resolver
        self._idempotency_adapter = idempotency_adapter
        if agent_run_ledger is not None and not isinstance(agent_run_ledger, D1AgentRunLedger):
            raise ValueError("trusted D1 Agent ledger required")
        self._agent_run_ledger = agent_run_ledger
        # #4194 B: the expired-lease sweep is a deployment-gated maintenance
        # call, never implicitly enabled by an unmarked composition.
        self._agent_run_recovery_enabled = (
            agent_run_recovery_enabled and agent_run_ledger is not None
        )
        self._continuation = AgentSkillContinuationCoordinator(
            runtime_factory=runtime_factory,
            binding_resolver=self._resolve_binding,
            approval_decision_verifier=approval_decision_verifier,
            continuation_store=continuation_store,
            idempotency_adapter=idempotency_adapter,
            agent_run_ledger=agent_run_ledger,
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


    async def _run_trusted_agent(self, request: OrchestrationRequest):
        """Opt-in D1 fencing for already-authenticated Agent/Skill execution.

        The separate D1 provisioning gate must be activated explicitly.
        """
        ledger = self._agent_run_ledger
        if ledger is None:
            return await OrchestrationRunner(
                runtime=self._runtime_factory(request.app_id),
                idempotency=self._idempotency_adapter,
            ).run(request)
        if not request.subject_id or request.agent_plan is None:
            raise AgentDurableLeaseError("trusted Agent subject and plan required")
        # One derivation shared with the run-control surface (#4194 A).
        scope = agent_run_owner_scope(request.app_id, request.subject_id)
        fingerprint = canonical_logical_execution_fingerprint(
            app_id=request.app_id, request=request.execution_request,
            context=request.context, subject_id=request.subject_id,
            plan=request.agent_plan, recovery_policy=request.recovery_policy,
            max_retries=request.max_retries, require_evidence=request.require_evidence,
            require_verification=request.require_verification,
        )
        lease = await ledger.start(
            run_id="arun_" + secrets.token_hex(16),
            owner_scope=scope, request_fingerprint=fingerprint,
            worker_id="eng_" + secrets.token_hex(12), lease_seconds=120,
        )
        stopped = asyncio.Event()
        main_task = asyncio.current_task()

        async def renew() -> None:
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=30)
                    return
                except asyncio.TimeoutError:
                    try:
                        active = await ledger.heartbeat(lease, lease_seconds=120)
                    except Exception:
                        active = False
                    if not active:
                        # An owner-requested cancel is a *requested* stop, not a
                        # lease accident: stop renewing and let the existing
                        # dispatch guard fence the run so the caller receives a
                        # truthful "cancelled" outcome instead of an aborted
                        # request. Every other lease loss keeps the original
                        # fail-closed task cancellation.
                        try:
                            current = await ledger.status_for_owner(
                                run_id=lease.run_id, owner_scope=lease.owner_scope,
                            )
                        except Exception:
                            current = None
                        if current is not None and current.state in {
                            "cancelled", "needs_review",
                        }:
                            stop_reason["source"] = "owner_cancel"
                            return
                        if main_task is not None:
                            main_task.cancel()
                        return

        stop_reason: dict[str, str] = {}
        heartbeat_task = asyncio.create_task(renew())
        try:
            bound_request = replace(request, trusted_agent_bridge_run_id=lease.run_id)
            try:
                result = await OrchestrationRunner(
                    runtime=self._runtime_factory(request.app_id),
                    idempotency=self._idempotency_adapter,
                    agent_run_guard=ledger.execution_guard(lease),
                    agent_checkpoint_hook=lambda step: ledger.checkpoint(lease, completed_step=step),
                ).run(bound_request)
            except OrchestrationError as exc:
                if exc.code != "agent_run_fenced":
                    raise
                # Owner cancel vs lease accident is decided from server state,
                # not from a local flag: the durable row is authoritative.
                owner_cancelled = stop_reason.get("source") == "owner_cancel"
                if not owner_cancelled:
                    try:
                        current = await ledger.status_for_owner(
                            run_id=lease.run_id, owner_scope=lease.owner_scope,
                        )
                    except Exception:
                        current = None
                    owner_cancelled = current is not None and current.state in {
                        "cancelled", "needs_review",
                    }
                if not owner_cancelled:
                    raise
                raise AgentRunCancelledError(lease.run_id) from exc
            terminal_state = "awaiting_approval" if result.approval_pause else "completed"
            if not await ledger.finish(lease, state=terminal_state):
                raise AgentDurableLeaseError("Agent run lease was lost")
            return result
        except AgentRunCancelledError:
            raise
        except BaseException:
            try:
                await ledger.finish(lease, state="failed")
            except Exception:
                pass  # Unknown side effects stay uncertain; never replay.
            raise
        finally:
            stopped.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

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
            result = await self._run_trusted_agent(request)
        except AgentRunCancelledError as exc:
            # The cancel request itself already reported the honest state; the
            # in-flight run caller gets the same truthful terminal signal.
            return _service_error(
                exc.code,
                "Agent run was cancelled by its owner before the next dispatch.",
                status_code=409,
                metadata={"run_id": exc.run_id, "requires_reconciliation": True},
            )
        except AgentDurableLeaseError:
            return _service_error("agent_run_lease_unavailable", "Trusted Agent run storage is unavailable.", status_code=503)
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

    def _run_control_owner_scope(
        self, payload: Any,
    ) -> tuple[TrustedAgentRunControlTarget, str] | ServiceResponse:
        """Resolve an owner scope from trusted authority, never from the caller.

        The caller supplies server-issued identifiers only. app_id must match
        the authenticated application, the Agent identity must exist in this
        application's trusted binding, and the owner scope is derived from the
        server-owned subject exactly as the run path derives it.
        """
        if self._agent_run_ledger is None:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
            )
        app_id = payload.get("app_id") if isinstance(payload, Mapping) else None
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error(
                "invalid_request", "app_id must be a non-empty string.", status_code=400,
            )
        try:
            binding = self._resolve_binding(app_id)
            target = build_trusted_agent_run_control(payload, binding=binding)
            subject_id = binding.resolve_identity(agent_id=target.agent_id)
            owner_scope = agent_run_owner_scope(target.app_id, subject_id)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAgentSkillAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except AgentDurableLeaseError:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
            )
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_request", "Agent run control fields are invalid.", status_code=400,
            )
        return target, owner_scope

    async def status_payload(self, payload: Any) -> ServiceResponse:
        """Owner-scoped state read for one already-issued Agent run (#4194 A)."""
        resolved = self._run_control_owner_scope(payload)
        if isinstance(resolved, ServiceResponse):
            return resolved
        target, owner_scope = resolved
        ledger = self._agent_run_ledger
        if ledger is None:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
            )
        try:
            view = await ledger.status_for_owner(
                run_id=target.run_id, owner_scope=owner_scope,
            )
        except AgentDurableLeaseError:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
                metadata={"operation": "status", "reason": "d1_unavailable"},
            )
        if view is None:
            # Unknown and foreign runs are deliberately indistinguishable.
            return _service_error(
                "agent_run_not_found",
                "No Agent run is visible to this authenticated application and subject.",
                status_code=404,
            )
        return ServiceResponse(
            status_code=200,
            body={"ok": True, "run": view.to_public_dict()},
        )

    async def cancel_running_payload(self, payload: Any) -> ServiceResponse:
        """Owner-scoped cancel of a running/paused Agent run (#4194 A).

        Reuses the existing D1 lease fencing: the cancel revokes the lease, so
        the next dispatch guard of the in-flight run refuses. It is not a
        rollback; a run that already left the pre-dispatch safety boundary is
        reported as ``needs_review`` and flagged for reconciliation.
        """
        resolved = self._run_control_owner_scope(payload)
        if isinstance(resolved, ServiceResponse):
            return resolved
        target, owner_scope = resolved
        ledger = self._agent_run_ledger
        if ledger is None:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
            )
        try:
            outcome = await ledger.cancel_for_owner(
                run_id=target.run_id, owner_scope=owner_scope,
            )
        except AgentDurableLeaseError:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
                metadata={"operation": "cancel", "reason": "d1_unavailable"},
            )
        if outcome is None:
            return _service_error(
                "agent_run_not_found",
                "No Agent run is visible to this authenticated application and subject.",
                status_code=404,
            )
        assert isinstance(outcome, AgentRunCancelOutcome)
        public = outcome.to_public_dict()
        if not outcome.changed and outcome.state.state != "cancelled":
            return _service_error(
                "agent_run_already_terminal",
                "Agent run already reached a terminal state; no cancel was applied.",
                status_code=409,
                metadata={"run_state": outcome.state.state, "run": public},
            )
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "run": public,
                "reason": target.reason,
                "interrupt_signal": "dispatch_fence",
            },
        )

    async def recovery_payload(self, payload: Any) -> ServiceResponse:
        """Deployment-gated expired-lease sweep; never re-executes work (#4194 B)."""
        ledger = self._agent_run_ledger
        if not self._agent_run_recovery_enabled or ledger is None:
            return _service_error(
                "agent_run_recovery_unavailable",
                "Trusted Agent run recovery is not enabled for this deployment.",
                status_code=503,
            )
        app_id = payload.get("app_id") if isinstance(payload, Mapping) else None
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error(
                "invalid_request", "app_id must be a non-empty string.", status_code=400,
            )
        try:
            binding = self._resolve_binding(app_id)
            request = build_trusted_agent_run_recovery(payload, binding=binding)
            # Reuse the same server-derived owner scope as dispatch and control,
            # so the sweep can never touch another owner's expired runs.
            owner_scope = agent_run_owner_scope(
                request.app_id, binding.resolve_identity(agent_id=request.agent_id),
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAgentSkillAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except AgentDurableLeaseError:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
            )
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_request", "Agent run recovery fields are invalid.", status_code=400,
            )
        try:
            expired_seen = await ledger.count_expired_runs(owner_scope=owner_scope)
            quarantined = 0
            if not request.dry_run:
                quarantined = await ledger.quarantine_expired(
                    limit=DEFAULT_EXPIRED_SWEEP_LIMIT, owner_scope=owner_scope,
                )
        except AgentDurableLeaseError:
            return _service_error(
                "agent_run_lease_unavailable",
                "Trusted Agent run storage is unavailable.",
                status_code=503,
                metadata={"operation": "expired_lease_sweep", "reason": "d1_unavailable"},
            )
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "recovery": {
                    "mode": "expired_leases",
                    "dry_run": request.dry_run,
                    "expired_seen": expired_seen,
                    "quarantined": quarantined,
                    "limit": DEFAULT_EXPIRED_SWEEP_LIMIT,
                    "auto_replay": False,
                    "tool_re_execution": False,
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
        if path not in {
            AGENT_SKILL_RUN_PATH,
            AGENT_SKILL_RESUME_PATH,
            AGENT_SKILL_CANCEL_PATH,
            AGENT_SKILL_RUN_STATUS_PATH,
            AGENT_SKILL_RUN_CANCEL_PATH,
            AGENT_SKILL_RUN_RECOVERY_PATH,
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
        if path == AGENT_SKILL_RUN_STATUS_PATH:
            return await self.status_payload(payload)
        if path == AGENT_SKILL_RUN_CANCEL_PATH:
            return await self.cancel_running_payload(payload)
        if path == AGENT_SKILL_RUN_RECOVERY_PATH:
            return await self.recovery_payload(payload)
        return await self.run_payload(payload)


# Compatibility re-exports retained for the E4A import surface.
__all__ = [
    "AGENT_SKILL_RUN_PATH",
    "AGENT_SKILL_RESUME_PATH",
    "AGENT_SKILL_CANCEL_PATH",
    "AGENT_SKILL_RUN_STATUS_PATH",
    "AGENT_SKILL_RUN_CANCEL_PATH",
    "AGENT_SKILL_RUN_RECOVERY_PATH",
    "AUTHORITY_SHAPED_KEYS",
    "TRUSTED_AGENT_SKILL_ALLOWED",
    "TRUSTED_AGENT_SKILL_REQUIRED",
    "TrustedAgentSkillWireRequest",
    "TrustedAgentRunControlTarget",
    "TrustedAgentRunRecoveryRequest",
    "build_trusted_agent_run_control",
    "build_trusted_agent_run_recovery",
    "build_trusted_agent_skill_request",
    "AgentRunCancelledError",
    "AgentSkillEngineService",
]
