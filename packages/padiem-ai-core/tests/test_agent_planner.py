import pytest

from padiem_ai_core.agent_definition import (
    AgentExecutionBudget,
    BoundedAgentDefinition,
)
from padiem_ai_core.agent_planner import (
    MAX_AGENT_PLAN_INPUT_CHARS,
    AgentPlan,
    AgentPlannerError,
    AgentPlanStep,
    validate_agent_plan,
    validate_agent_plan_input,
)
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)


def definition(**overrides):
    values = {
        "agent_id": "agent:padiem:research_assistant@1",
        "publisher_id": "publisher:padiem",
        "title": "Research Assistant",
        "description": "A bounded research assistant.",
        "instruction": "Use only approved capabilities.",
        "output_contract_ref": "io:research_answer@1",
        "allowed_tool_ids": ("tool:padiem:web_search@1",),
        "required_capabilities": ("web_search",),
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": AgentExecutionBudget(
            max_steps=10,
            max_tool_calls=4,
            max_skill_calls=0,
            max_wall_seconds=180,
        ),
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def compiled(active_definition=None, **overrides):
    active_definition = active_definition or definition()
    values = {
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "output_contract_ref": "io:research_answer@1",
        "task_type": "research",
        "optimize_for": "balanced",
        "max_tokens": 4096,
        "max_steps_cap": 6,
        "context_policy": {"reference_only": True},
        "model_policy": {"profile": "auto"},
        "output_contract": {"type": "object"},
        "tool_bindings": (
            ToolRuntimeBinding(
                canonical_tool_id="tool:padiem:web_search@1",
                runtime_tool_id="web.search",
            ),
        ),
        "available_capabilities": frozenset({"web_search"}),
    }
    values.update(overrides)
    return compile_agent_profile(
        active_definition,
        TrustedAgentRuntimePolicy(**values),
    )


def test_valid_plan_uses_only_compiled_runtime_tool_ids() -> None:
    active_definition = definition()
    active_compiled = compiled(active_definition)
    plan = AgentPlan(
        agent_id=active_definition.agent_id,
        steps=(
            AgentPlanStep(
                step_id="step_1",
                objective="Find bounded source material.",
                tool_id="web.search",
            ),
            AgentPlanStep(
                step_id="step_2",
                objective="Produce the requested answer from accepted evidence.",
                depends_on=("step_1",),
            ),
        ),
    )

    assert validate_agent_plan(
        plan,
        definition=active_definition,
        compiled_profile=active_compiled,
    ) is plan


def test_plan_cannot_reference_tool_outside_compiled_authority() -> None:
    active_definition = definition()
    plan = AgentPlan(
        agent_id=active_definition.agent_id,
        steps=(
            AgentPlanStep(
                step_id="step_1",
                objective="Attempt an ungranted action.",
                tool_id="filesystem.write",
            ),
        ),
    )

    with pytest.raises(AgentPlannerError) as exc_info:
        validate_agent_plan(
            plan,
            definition=active_definition,
            compiled_profile=compiled(active_definition),
        )

    assert exc_info.value.code == "agent_plan_tool_not_allowed"


def test_plan_identity_must_match_definition_and_compiled_profile() -> None:
    active_definition = definition()
    plan = AgentPlan(
        agent_id="agent:padiem:other@1",
        steps=(AgentPlanStep(step_id="step_1", objective="Do work."),),
    )

    with pytest.raises(AgentPlannerError) as exc_info:
        validate_agent_plan(
            plan,
            definition=active_definition,
            compiled_profile=compiled(active_definition),
        )

    assert exc_info.value.code == "agent_plan_identity_mismatch"


def test_plan_dependencies_must_point_backward_and_cannot_form_forward_cycle() -> None:
    with pytest.raises(AgentPlannerError) as exc_info:
        AgentPlan(
            agent_id="agent:padiem:research_assistant@1",
            steps=(
                AgentPlanStep(
                    step_id="step_1",
                    objective="First.",
                    depends_on=("step_2",),
                ),
                AgentPlanStep(step_id="step_2", objective="Second."),
            ),
        )

    assert exc_info.value.code == "invalid_agent_plan"


def test_plan_step_cannot_depend_on_itself() -> None:
    with pytest.raises(AgentPlannerError) as exc_info:
        AgentPlanStep(
            step_id="step_1",
            objective="Invalid self dependency.",
            depends_on=("step_1",),
        )

    assert exc_info.value.code == "invalid_agent_plan"


def test_plan_step_count_is_capped_by_compiled_runtime_budget() -> None:
    active_definition = definition()
    steps = tuple(
        AgentPlanStep(step_id=f"step_{index}", objective=f"Step {index}.")
        for index in range(1, 8)
    )
    plan = AgentPlan(agent_id=active_definition.agent_id, steps=steps)

    with pytest.raises(AgentPlannerError) as exc_info:
        validate_agent_plan(
            plan,
            definition=active_definition,
            compiled_profile=compiled(active_definition, max_steps_cap=6),
        )

    assert exc_info.value.code == "agent_plan_budget_exceeded"


def test_planned_tool_calls_are_capped_by_definition_budget() -> None:
    active_definition = definition(
        execution_budget=AgentExecutionBudget(
            max_steps=4,
            max_tool_calls=1,
            max_skill_calls=0,
            max_wall_seconds=180,
        )
    )
    plan = AgentPlan(
        agent_id=active_definition.agent_id,
        steps=(
            AgentPlanStep(step_id="step_1", objective="Search once.", tool_id="web.search"),
            AgentPlanStep(step_id="step_2", objective="Search twice.", tool_id="web.search"),
        ),
    )

    with pytest.raises(AgentPlannerError) as exc_info:
        validate_agent_plan(
            plan,
            definition=active_definition,
            compiled_profile=compiled(active_definition),
        )

    assert exc_info.value.code == "agent_plan_budget_exceeded"


def test_public_plan_has_no_tool_arguments_or_authorization_fields() -> None:
    plan = AgentPlan(
        agent_id="agent:padiem:research_assistant@1",
        steps=(
            AgentPlanStep(
                step_id="step_1",
                objective="Search approved sources.",
                tool_id="web.search",
            ),
        ),
    )
    public = plan.to_public_dict()

    assert public["steps"][0] == {
        "step_id": "step_1",
        "objective": "Search approved sources.",
        "tool_id": "web.search",
        "depends_on": [],
    }
    assert "arguments" not in public["steps"][0]
    assert "authorization" not in public["steps"][0]
    assert "reasoning" not in public["steps"][0]


def test_planner_input_is_bounded_without_hidden_reasoning_contract() -> None:
    assert validate_agent_plan_input("  Do the task.  ") == "Do the task."

    with pytest.raises(AgentPlannerError) as exc_info:
        validate_agent_plan_input("x" * (MAX_AGENT_PLAN_INPUT_CHARS + 1))

    assert exc_info.value.code == "agent_plan_budget_exceeded"
