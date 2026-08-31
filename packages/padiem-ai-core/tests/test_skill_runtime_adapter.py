import pytest

from padiem_ai_core.agent_profile_adapter import ToolRuntimeBinding
from padiem_ai_core.skill_package import (
    ApprovalHook,
    ReusableSkillPackage,
    SkillExecutionBudget,
)
from padiem_ai_core.skill_runtime_adapter import (
    SkillRuntimeAdapterError,
    TrustedSkillRuntimePolicy,
    compile_skill_profile,
    runtime_profile_id_for_skill,
)


def make_package(**overrides):
    values = {
        "skill_id": "skill:padiem:research_digest@1",
        "publisher_id": "publisher:padiem",
        "description": "Summarize a bounded set of research sources.",
        "instruction": "Use only supplied references and return a concise digest.",
        "input_contract_ref": "io:research_sources@1",
        "output_contract_ref": "io:research_digest@1",
        "required_capabilities": ("web_search", "structured_output"),
        "allowed_tool_ids": (
            "tool:padiem:web_search@1",
            "tool:padiem:read_document@1",
        ),
        "connector_requirement_ids": ("connector:google:drive@1",),
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": SkillExecutionBudget(
            max_steps=6,
            max_tool_calls=4,
            max_wall_seconds=90,
        ),
        "approval_hooks": (ApprovalHook.BEFORE_CONNECTOR_WRITE,),
        "entitlement_ref": "entitlement:skills.research",
    }
    values.update(overrides)
    return ReusableSkillPackage(**values)


def make_policy(**overrides):
    values = {
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "output_contract_ref": "io:research_digest@1",
        "task_type": "document",
        "optimize_for": "balanced",
        "max_tokens": 1200,
        "max_steps_cap": 4,
        "context_policy": {"mode": "reference_only"},
        "model_policy": {"model": "b14/auto"},
        "output_contract": {"type": "text"},
        "tool_bindings": (
            ToolRuntimeBinding(
                canonical_tool_id="tool:padiem:web_search@1",
                runtime_tool_id="web.search",
            ),
        ),
        "connected_connector_ids": frozenset({"connector:google:drive@1"}),
        "available_capabilities": frozenset(
            {"web_search", "structured_output", "chat"}
        ),
        "satisfied_entitlement_refs": frozenset(
            {"entitlement:skills.research"}
        ),
    }
    values.update(overrides)
    return TrustedSkillRuntimePolicy(**values)


def test_compile_skill_profile_uses_trusted_runtime_policy_and_bounds_steps() -> None:
    package = make_package()
    compiled = compile_skill_profile(package, make_policy())

    assert compiled.canonical_skill_id == package.skill_id
    assert compiled.runtime_profile.id == runtime_profile_id_for_skill(package.skill_id)
    assert compiled.runtime_profile.system_instruction == package.instruction
    assert compiled.runtime_profile.task_type == "document"
    assert compiled.runtime_profile.optimize_for == "balanced"
    assert compiled.runtime_profile.max_steps == 4
    assert compiled.runtime_profile.allowed_tools == ("web.search",)
    assert "tool:padiem:web_search@1" not in compiled.runtime_profile.allowed_tools
    assert "tool:padiem:read_document@1" not in compiled.runtime_profile.allowed_tools


def test_skill_package_cannot_mint_unbound_tool_authority() -> None:
    compiled = compile_skill_profile(
        make_package(),
        make_policy(tool_bindings=()),
    )
    assert compiled.runtime_profile.allowed_tools == ()


def test_compile_skill_profile_fails_closed_on_missing_capability() -> None:
    policy = make_policy(available_capabilities=frozenset({"web_search"}))
    with pytest.raises(SkillRuntimeAdapterError, match="required capabilities"):
        compile_skill_profile(make_package(), policy)


def test_compile_skill_profile_fails_closed_on_missing_connector() -> None:
    policy = make_policy(connected_connector_ids=frozenset())
    with pytest.raises(SkillRuntimeAdapterError, match="required connectors"):
        compile_skill_profile(make_package(), policy)


def test_compile_skill_profile_fails_closed_on_missing_entitlement() -> None:
    policy = make_policy(satisfied_entitlement_refs=frozenset())
    with pytest.raises(SkillRuntimeAdapterError, match="entitlement"):
        compile_skill_profile(make_package(), policy)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context_policy_ref", "context:other@1"),
        ("model_policy_ref", "model:other@1"),
        ("output_contract_ref", "io:other@1"),
    ],
)
def test_compile_skill_profile_rejects_trusted_policy_reference_drift(
    field: str,
    value: str,
) -> None:
    policy = make_policy(**{field: value})
    with pytest.raises(SkillRuntimeAdapterError, match=field):
        compile_skill_profile(make_package(), policy)


def test_runtime_profile_id_is_deterministic_and_legacy_safe() -> None:
    first = runtime_profile_id_for_skill("skill:padiem:research_digest@1")
    second = runtime_profile_id_for_skill("skill:padiem:research_digest@1")
    other = runtime_profile_id_for_skill("skill:padiem:research_digest@2")

    assert first == second
    assert first.startswith("skill-runtime:")
    assert first != other
    assert len(first) < 128


def test_trusted_skill_policy_rejects_duplicate_runtime_bindings() -> None:
    with pytest.raises(SkillRuntimeAdapterError, match="duplicate runtime IDs"):
        make_policy(
            tool_bindings=(
                ToolRuntimeBinding(
                    canonical_tool_id="tool:padiem:web_search@1",
                    runtime_tool_id="shared.runtime",
                ),
                ToolRuntimeBinding(
                    canonical_tool_id="tool:padiem:read_document@1",
                    runtime_tool_id="shared.runtime",
                ),
            )
        )
