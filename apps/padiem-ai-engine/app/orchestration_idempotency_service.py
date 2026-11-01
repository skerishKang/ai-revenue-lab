"""Identity-bound Engine service with canonical idempotency fingerprinting.

The canonical Worker consumes this service so durable replay identity covers the
same material execution fields protected by approval continuation identity while
keeping observability identifiers outside replay equality.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext, request_fingerprint

from app.idempotency_identity import (
    canonical_logical_execution_fingerprint,
    reset_canonical_idempotency_fingerprint,
    set_canonical_idempotency_fingerprint,
    wrap_idempotency_adapter,
)
from app.orchestration_identity_service import IdentityBoundOrchestrationEngineService
from app.orchestration_service import (
    _parse_orchestration_options,
    _validated_pc_tool_arguments,
    _validated_pc_declared_plan,
    _validated_pc_action_context,
    _validated_pc_delegation,
)
from app.service import build_execution_request


def pc_tool_target_fingerprint(
    tool_arguments: Mapping[str, Mapping[str, Any]] | None,
) -> str | None:
    """Bind a validated PC execution target into a replay-safe digest.

    Only server-validated arguments reach this function, so the digest changes
    exactly when the execution would run against a different PC.

    Target-less identity policy (#5015), stated here because nothing else in
    this repository carries a target on a continuation:

    * No target means *no extension*, never a match. ``None`` shortens the
      digest; it is not compared against another ``None`` to decide that two
      executions target the same PC.
    * A paused execution carries no target field. ``ContinuationExecutionIdentity``
      and ``execution_request_identity_payload`` stay in their pre-#5015 shape, so
      every continuation — PC or not — keeps the digest form it was created with.
      The one authority that proves a resumed execution runs on the same PC is the
      server-issued pause: ``tool_invocation_digest(invocation)`` hashes the exact
      ``{device_id}`` arguments, and ``_assert_resumed_invocation_matches`` refuses
      anything else.
    * A PC run that ever paused would store a target-bearing run digest while the
      closed resume wire can only produce a target-free one, so
      ``require_non_widening_resume_admission`` answers 409. That is fail-closed by
      design; opening the resume wire would have to extend the digest too.
    * A malformed target yields no fingerprint at all instead of a weaker
      target-free one, so an invalid request can never be replayed as a
      target-less sibling under the same key.
    """
    if not tool_arguments:
        return None
    return request_fingerprint(
        {
            "pc_tool_target": {
                step_id: dict(arguments)
                for step_id, arguments in sorted(tool_arguments.items())
            }
        }
    )


def _initial_execution_fingerprint(payload: Any) -> str | None:
    """Derive material logical-execution identity for a valid wire request.

    Invalid requests are deliberately left to the existing service contract
    parser; returning ``None`` here must never turn validation failures into
    successful execution.

    #5015: a validated PC execution target is material to the execution, so a
    durable replay keyed only to the logical fields could hand a caller back
    another PC's result under the same idempotency key. The target therefore
    extends the digest, and an invalid target leaves no fingerprint at all.
    """
    if not isinstance(payload, Mapping):
        return None
    app_id = payload.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        return None
    try:
        _, exec_req, ctx = build_execution_request(
            {
                key: payload[key]
                for key in (
                    "app_id",
                    "agent",
                    "messages",
                    "session_id",
                    "additional_system_context",
                    "trace_id",
                    "execution_context",
                )
                if key in payload
            }
        )
        if ctx is None:
            ctx = ExecutionContext(trace_id=exec_req.trace_id or "orch_trace")
        (
            plan,
            recovery_policy,
            max_retries,
            subject_id,
            require_evidence,
            require_verification,
        ) = _parse_orchestration_options(payload)
        logical = canonical_logical_execution_fingerprint(
            app_id=app_id,
            request=exec_req,
            context=ctx,
            subject_id=subject_id,
            plan=plan,
            recovery_policy=recovery_policy,
            max_retries=max_retries,
            require_evidence=require_evidence,
            require_verification=require_verification,
        )
    except Exception:
        return None
    try:
        target = _validated_pc_tool_arguments(payload)
        declared_plan = _validated_pc_declared_plan(payload)
        action_context = _validated_pc_action_context(payload)
        delegation = _validated_pc_delegation(payload)
    except Exception:
        return None
    from app.pc_tools_turn import parse_pc_tools
    try:
        pc_tools = parse_pc_tools(payload)
    except Exception:
        return None
    if pc_tools is not None:
        logical = request_fingerprint({"logical_execution": logical, "pc_tools": pc_tools})
    if action_context is not None:
        # Role/provenance changes alter whether a destructive call may run.
        # They must not replay a result admitted under different evidence.
        logical = request_fingerprint(
            {"logical_execution": logical, "pc_action_context": action_context}
        )
    if delegation is not None:
        # A revoked rule or an unavailable settings store cannot reuse an
        # answer that was admitted under a different owner policy.
        logical = request_fingerprint(
            {"logical_execution": logical, "pc_delegation": delegation}
        )
    if declared_plan is not None:
        # A different requested scope must never replay another run's result.
        # Omission keeps the exact legacy fingerprint.
        logical = request_fingerprint(
            {"logical_execution": logical, "pc_declared_plan": declared_plan}
        )
    if target is None:
        return logical
    target_digest = pc_tool_target_fingerprint(target)
    if target_digest is None:
        return logical
    return request_fingerprint(
        {"logical_execution": logical, "pc_tool_target": target_digest}
    )


class CanonicalIdempotencyOrchestrationEngineService(IdentityBoundOrchestrationEngineService):
    """Identity-bound service with durable replay keyed to material semantics."""

    def __init__(self, *args: Any, idempotency_adapter: Any | None = None, **kwargs: Any) -> None:
        super().__init__(
            *args,
            idempotency_adapter=wrap_idempotency_adapter(idempotency_adapter),
            **kwargs,
        )

    async def orchestrate_payload(self, payload: Any):
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return await super().orchestrate_payload(payload)
        token = set_canonical_idempotency_fingerprint(fingerprint)
        try:
            return await super().orchestrate_payload(payload)
        finally:
            reset_canonical_idempotency_fingerprint(token)

    async def resume_payload(self, payload: Any):
        # Resume still passes the parent service's exact continuation-identity
        # comparison before Core executes. The durable idempotency layer uses the
        # same material field classification but excludes trace/key metadata.
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return await super().resume_payload(payload)
        token = set_canonical_idempotency_fingerprint(fingerprint)
        try:
            return await super().resume_payload(payload)
        finally:
            reset_canonical_idempotency_fingerprint(token)
