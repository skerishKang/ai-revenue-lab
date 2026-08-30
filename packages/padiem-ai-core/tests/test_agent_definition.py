import pytest

from padiem_ai_core.agent_definition import (
    AgentApprovalCheckpoint,
    AgentDefinitionError,
    AgentExecutionBudget,
    BoundedAgentDefinition,
    effective_agent_connector_ids,
    effective_agent_tool_ids,
    missing_agent_capabilities,
)


def make_agent(**overrides):
    values = {
        "agent_id": "agent:padiem:research_assistant@1",
        "publisher_id": "publisher:padiem",
        "title": "Research Assistant",
        "description": "A bounded research assistant.",
        "instruction": "Use approved skills and tools to produce a bounded research answer.",
        "output_contract_ref": "io:research_answer@1",
        "skill_package_ids": ("skill:padiem:research_digest@1",),
        "allowed_tool_ids": (
            "tool:padiem:web_search@1",
            "tool:padiem:read_document@1",
        ),
        "connector_requirement_ids": ("connector:google:drive@1",),
        "required_capabilities": ("web_search", "structured_output"),
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": AgentExecutionBudget(
            max_steps=10,
            max_tool_calls=6,
            max_skill_calls=4,
            max_wall_seconds=120,
        ),
        "approval_checkpoints": (AgentApprovalCheckpoint.BEFORE_CONNECTOR_WRITE,),
        "entitlement_ref": "entitlement:agents.research",
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def test_agent_id_uses_frozen_grammar() -> None:
    assert make_agent().agent_id == "agent:padiem:research_assistant@1"
    with pytest.raises(AgentDefinitionError):
        make_agent(agent_id="research_assistant")


def test_runtime_facing_metadata_is_explicit() -> None:
    agent = make_agent()
    assert agent.title == "Research Assistant"
    assert agent.output_contract_ref == "io:research_answer@1"


def test_agent_tool_declarations_cannot_widen_trusted_grants() -> None:
    agent = make_agent()
    trusted = {
        "tool:padiem:web_search@1",
        "tool:padiem:send_email@1",
    }
    assert effective_agent_tool_ids(agent, trusted) == (
        "tool:padiem:web_search@1",
    )
    assert "tool:padiem:send_email@1" not in effective_agent_tool_ids(agent, trusted)


def test_agent_connector_requirement_does_not_create_connection() -> None:
    agent = make_agent()
    assert effective_agent_connector_ids(agent, frozenset()) == ()
    assert effective_agent_connector_ids(
        agent,
        frozenset({"connector:google:drive@1"}),
    ) == ("connector:google:drive@1",)


def test_missing_capability_is_explicit_fail_closed_input() -> None:
    agent = make_agent()
    assert missing_agent_capabilities(agent, {"web_search"}) == (
        "structured_output",
    )


def test_subagents_are_forbidden_in_v1() -> None:
    with pytest.raises(AgentDefinitionError):
        make_agent(allow_subagents=True)


def test_budget_is_bounded() -> None:
    with pytest.raises(AgentDefinitionError):
        AgentExecutionBudget(max_steps=0)
    with pytest.raises(AgentDefinitionError):
        AgentExecutionBudget(max_skill_calls=65)
    with pytest.raises(AgentDefinitionError):
        AgentExecutionBudget(max_wall_seconds=3601)


def test_duplicate_ids_fail_closed() -> None:
    with pytest.raises(AgentDefinitionError):
        make_agent(
            skill_package_ids=(
                "skill:padiem:research_digest@1",
                "skill:padiem:research_digest@1",
            )
        )

    with pytest.raises(AgentDefinitionError):
        make_agent(
            allowed_tool_ids=(
                "tool:padiem:web_search@1",
                "tool:padiem:web_search@1",
            )
        )


def test_approval_checkpoints_are_typed_and_unique() -> None:
    with pytest.raises(AgentDefinitionError):
        make_agent(approval_checkpoints=("before_connector_write",))
    with pytest.raises(AgentDefinitionError):
        make_agent(
            approval_checkpoints=(
                AgentApprovalCheckpoint.BEFORE_CONNECTOR_WRITE,
                AgentApprovalCheckpoint.BEFORE_CONNECTOR_WRITE,
            )
        )


def test_agent_has_no_self_authorization_or_credential_fields() -> None:
    agent = make_agent()
    assert not hasattr(agent, "approved")
    assert not hasattr(agent, "granted_tools")
    assert not hasattr(agent, "oauth_token")
    assert not hasattr(agent, "provider_credential")
    assert not hasattr(agent, "child_agent_ids")
