"""Product-safe Agent/Skill continuation projection for Engine (#2786 S13-4 Phase 1).

The execution lifecycle contract for an approval continuation.  It is a pure
projection: it names facts the coordinator already established (the server-issued
continuation reference, the paused run identity, the trusted owner, the state
before and after the resume, whether the verified approval delta was applied).

It never invents state, never widens authority and never exposes authority
material: approval decisions, claim tokens, store-internal fingerprints and the
transport caller identity stay inside the Engine.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.orchestration import OrchestrationResult

from app.agent_skill_authority import TrustedAgentSkillSelection
from app.orchestration_continuation import ContinuationRecord

ENGINE_AGENT_CONTINUATION_CONTRACT_FAMILY = "padiem.engine.agent-continuation"
ENGINE_AGENT_CONTINUATION_CONTRACT_MAJOR = 1
ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION = (
    f"{ENGINE_AGENT_CONTINUATION_CONTRACT_FAMILY}/{ENGINE_AGENT_CONTINUATION_CONTRACT_MAJOR}.0"
)


def project_agent_continuation_result(
    result: OrchestrationResult,
    *,
    selection: TrustedAgentSkillSelection,
    record: ContinuationRecord,
    approval_delta_applied: bool,
) -> dict[str, Any]:
    """Return the bounded continuation block for a resumed run.

    ``approval_delta_applied`` is asserted by the caller: the Engine only reaches
    this projection after a verified approval decision was applied to the paused
    run, so it is recorded rather than derived from request input.
    """

    if not isinstance(result, OrchestrationResult):
        raise TypeError("result must be OrchestrationResult")
    if not isinstance(selection, TrustedAgentSkillSelection):
        raise TypeError("selection must be TrustedAgentSkillSelection")
    if not isinstance(record, ContinuationRecord):
        raise TypeError("record must be ContinuationRecord")

    execution = result.execution_result
    public_events = [event.to_public_dict() for event in result.events]
    resumed_state = (
        result.execution_state.value
        if result.execution_state is not None
        else execution.metadata.status.value
    )
    task_id = record.pause.run_id or (
        public_events[0].get("run_id") if public_events else None
    )
    trace_id = record.pause.trace_id or (
        public_events[0].get("trace_id") if public_events else None
    )
    definition = selection.authority.definition

    return {
        "continuation_contract_version": ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION,
        # CONTINUATION_ID: the server-issued continuation reference.  Phase 1 keeps
        # it on the continuation responses only (no run-response exposure).
        "continuation_id": record.continuation_ref,
        # TASK_ID: canonical alias of the paused run id, same rule as the task contract.
        "task_id": task_id,
        # OWNER_IDENTITY: trusted binding state; the transport caller is not projected.
        "owner_identity": {"subject_id": selection.subject_id},
        "current_state": record.state,
        "resume_target_state": resumed_state,
        # RESUME_AUTHORITY: a summary only.  The authority material itself (the
        # decided delta, its references and the verified decision) never crosses.
        "resume_authority": {
            "approval_delta_applied": bool(approval_delta_applied),
            "capability_required": list(definition.required_capabilities),
        },
        "audit_event": {
            "trace_id": trace_id,
            "event_count": len(public_events),
            "terminal_kind": public_events[-1].get("kind") if public_events else None,
        },
    }
