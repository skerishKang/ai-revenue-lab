import pytest

from padiem_ai_core.agent_definition import (
    AgentExecutionBudget,
    BoundedAgentDefinition,
)
from padiem_ai_core.agent_profile_adapter import (
    AgentProfileCompilationError,
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
    runtime_profile_id_for_agent,
)


def definition(**overrides):
    values = {
        "agent_id": "agent:padiem:research_assistant@1",
        "publisher_id": "publisher:padiem",
        "title": "Research Assistant",
        "description": "A bounded research assistant.",
        "instruction": "Use only approved capabilities.",
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
        "execution_budget": AgentExecutionBudget(max_steps=10),
        "entitlement_ref": "entitlement:agents.research",
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def policy(**overrides):
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
        "connected_connector_ids": frozenset({"connector:google:drive@1"}),
        "active_skill_package_ids": frozenset({"skill:padiem:research_digest@1"}),
        "available_capabilities": frozenset({"web_search", "structured_output"}),
        "satisfied_entitlement_refs": frozenset({"entitlement:agents.research"}),
    }
    values.update(overrides)
    return TrustedAgentRuntimePolicy(**values)


def test_compile_preserves_existing_agent_profile_authority() -> None:
    compiled = compile_agent_profile(definition(), policy())
    profile = compiled.runtime_profile

    assert compiled.canonical_agent_id == "agent:padiem:research_assistant@1"
    assert profile.id == runtime_profile_id_for_agent(compiled.canonical_agent_id)
    assert "@" not in profile.id
    assert profile.title == "Research Assistant"
    assert profile.allowed_tools == ("web.search",)
    assert profile.max_steps == 6
    assert profile.system_instruction == "Use only approved capabilities."


def test_unbound_canonical_tool_is_not_granted_to_runtime() -> None:
    compiled = compile_agent_profile(definition(), policy())
    assert compiled.runtime_profile.allowed_tools == ("web.search",)
    assert "read_document" not in compiled.runtime_profile.allowed_tools


def test_missing_connector_fails_closed() -> None:
    with pytest.raises(AgentProfileCompilationError):
        compile_agent_profile(
            definition(),
            policy(connected_connector_ids=frozenset()),
        )


def test_missing_skill_package_fails_closed() -> None:
    with pytest.raises(AgentProfileCompilationError):
        compile_agent_profile(
            definition(),
            policy(active_skill_package_ids=frozenset()),
        )


def test_missing_entitlement_fails_closed() -> None:
    with pytest.raises(AgentProfileCompilationError):
        compile_agent_profile(
            definition(),
            policy(satisfied_entitlement_refs=frozenset()),
        )


def test_missing_capability_fails_closed() -> None:
    with pytest.raises(AgentProfileCompilationError):
        compile_agent_profile(
            definition(),
            policy(available_capabilities=frozenset({"web_search"})),
        )


def test_policy_reference_mismatch_fails_closed() -> None:
    with pytest.raises(AgentProfileCompilationError):
        compile_agent_profile(
            definition(),
            policy(model_policy_ref="model:other@1"),
        )


def test_runtime_profile_id_is_deterministic_and_legacy_safe() -> None:
    first = runtime_profile_id_for_agent("agent:padiem:research_assistant@1")
    second = runtime_profile_id_for_agent("agent:padiem:research_assistant@1")
    different = runtime_profile_id_for_agent("agent:padiem:research_assistant@2")
    assert first == second
    assert first != different
    assert first.startswith("agent-runtime:")
    assert len(first) < 128


def test_duplicate_runtime_bindings_fail_closed() -> None:
    duplicate = (
        ToolRuntimeBinding("tool:padiem:web_search@1", "web.search"),
        ToolRuntimeBinding("tool:padiem:read_document@1", "web.search"),
    )
    with pytest.raises(AgentProfileCompilationError):
        policy(tool_bindings=duplicate)
