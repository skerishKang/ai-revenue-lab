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
        "events": [event.to_public_dict() for event in result.events],
        # Core ToolEvent public dictionaries contain lifecycle metadata, not raw
        # invocation arguments.  Do not project ToolExecutionResult outputs.
        "tool_events": [
            event.to_public_dict() for event in execution.metadata.tool_events
        ],
        "approval_pause": pause.to_public_dict() if pause is not None else None,
        "execution_state": result.execution_state.value
        if result.execution_state is not None
        else None,
        "state_transitions": [
            transition.to_public_dict() for transition in result.state_transitions
        ],
    }
