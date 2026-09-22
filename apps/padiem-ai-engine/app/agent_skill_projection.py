"""Product-safe Agent/Skill result projection for Engine (#1749 E4A).

Only explicit Core lifecycle state crosses this boundary.  Planner objectives,
raw Tool arguments/results, compiled policy bodies, connector grants,
entitlement state, Provider routing credentials and hidden reasoning are never
projected.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.orchestration import OrchestrationResult

from app.agent_skill_authority import TrustedAgentSkillSelection

ENGINE_AGENT_SKILL_CONTRACT_FAMILY = "padiem.engine.agent-skill"
ENGINE_AGENT_SKILL_CONTRACT_MAJOR = 1
ENGINE_AGENT_SKILL_CONTRACT_VERSION = (
    f"{ENGINE_AGENT_SKILL_CONTRACT_FAMILY}/{ENGINE_AGENT_SKILL_CONTRACT_MAJOR}.0"
)

# The bounded Agent *task* contract (#2786 S13-3b) is deliberately additive: it
# names what a caller already had to infer from the lifecycle block.  No new
# identifier is minted here -- ``task_id`` is the canonical run id the runner
# already emits on every orchestration event.
ENGINE_AGENT_TASK_CONTRACT_FAMILY = "padiem.engine.agent-task"
ENGINE_AGENT_TASK_CONTRACT_MAJOR = 1
ENGINE_AGENT_TASK_CONTRACT_VERSION = (
    f"{ENGINE_AGENT_TASK_CONTRACT_FAMILY}/{ENGINE_AGENT_TASK_CONTRACT_MAJOR}.0"
)


def _agent_task_contract(
    result: OrchestrationResult,
    *,
    selection: TrustedAgentSkillSelection,
    execution_status: str | None,
    public_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the bounded task-contract block (additive, no new authority)."""

    execution = result.execution_result
    definition = selection.authority.definition
    task_id = public_events[0].get("run_id") if public_events else None
    trace_id = public_events[0].get("trace_id") if public_events else None
    terminal_kind = public_events[-1].get("kind") if public_events else None
    return {
        "task_contract_version": ENGINE_AGENT_TASK_CONTRACT_VERSION,
        # TASK_ID: canonical alias of the runner's run id, never a new id.
        "task_id": task_id,
        # OWNER_IDENTITY: trusted binding state only; the caller identity that
        # transported the request is deliberately not projected here.
        "owner_identity": {"subject_id": selection.subject_id},
        # CAPABILITY_REQUIRED: the trusted agent definition's requirement, not a
        # caller-supplied claim.
        "capability_required": list(definition.required_capabilities),
        "execution_status": execution_status,
        # RESULT_REFERENCE: a bounded pointer to the produced result. Raw tool
        # arguments/results and answer text stay where they already are.
        "result_reference": {
            "run_id": task_id,
            "answer_present": execution.answer is not None,
            "resolved_tool_ids": list(result.resolved_tool_ids),
            "tool_event_count": len(execution.metadata.tool_events),
        },
        # AUDIT_EVENT: the in-response evidence chain (durable audit storage is a
        # later stage). The event list itself is already projected above.
        "audit_event": {
            "trace_id": trace_id,
            "event_count": len(public_events),
            "terminal_kind": terminal_kind,
        },
    }


def project_agent_skill_result(
    result: OrchestrationResult,
    *,
    selection: TrustedAgentSkillSelection,
) -> dict[str, Any]:
    """Return bounded public state derived only from explicit Core results."""

    if not isinstance(result, OrchestrationResult):
        raise TypeError("result must be OrchestrationResult")
    if not isinstance(selection, TrustedAgentSkillSelection):
        raise TypeError("selection must be TrustedAgentSkillSelection")

    execution = result.execution_result
    pause = result.approval_pause
    public_events = [event.to_public_dict() for event in result.events]
    execution_state = (
        result.execution_state.value if result.execution_state is not None else None
    )
    execution_status = (
        execution_state if execution_state is not None else execution.metadata.status.value
    )
    return {
        "contract_version": ENGINE_AGENT_SKILL_CONTRACT_VERSION,
        "agent_id": selection.authority.canonical_agent_id,
        "skill_id": selection.skill_id,
        "run_status": execution.metadata.status.value,
        "answer": execution.answer,
        # Planning is normalized to identity/count only.  Step objectives and
        # any planner scratchpad never cross this projection.
        "plan": {
            "agent_id": result.plan.agent_id,
            "step_count": len(result.plan.steps),
        }
        if result.plan is not None
        else None,
        "activated_skill": result.activated_skill.to_public_dict()
        if result.activated_skill is not None
        else None,
        "resolved_tool_ids": list(result.resolved_tool_ids),
        "events": public_events,
        # Core ToolEvent public dictionaries contain lifecycle metadata, not raw
        # invocation arguments.  Do not project ToolExecutionResult outputs.
        "tool_events": [
            event.to_public_dict() for event in execution.metadata.tool_events
        ],
        "approval_pause": pause.to_public_dict() if pause is not None else None,
        "execution_state": execution_state,
        "state_transitions": [
            transition.to_public_dict() for transition in result.state_transitions
        ],
        # Additive task contract (#2786 S13-3b).  Existing keys keep their exact
        # previous meaning; nothing here widens authority, mints an identifier or
        # projects new Core data.
        **_agent_task_contract(
            result,
            selection=selection,
            execution_status=execution_status,
            public_events=public_events,
        ),
    }
