import pytest

from padiem_ai_core.agent_profile_adapter import ToolRuntimeBinding
from padiem_ai_core.skill_activation import compile_enabled_skill
from padiem_ai_core.skill_package import ReusableSkillPackage
from padiem_ai_core.skill_registry import (
    SkillInstallation,
    SkillInstallationSnapshot,
    SkillInstallStatus,
    SkillRegistryError,
    SkillRegistrySnapshot,
)
from padiem_ai_core.skill_runtime_adapter import (
    SkillRuntimeAdapterError,
    TrustedSkillRuntimePolicy,
)


SKILL_ID = "skill:padiem:research_digest@1"


def package() -> ReusableSkillPackage:
    return ReusableSkillPackage(
        skill_id=SKILL_ID,
        publisher_id="publisher:padiem",
        description="Create a bounded research digest.",
        instruction="Use only approved sources and tools.",
        input_contract_ref="io:research_input@1",
        output_contract_ref="io:research_digest@1",
        required_capabilities=("web_search",),
        allowed_tool_ids=("tool:padiem:web_search@1",),
        connector_requirement_ids=("connector:google:drive@1",),
        context_policy_ref="context:reference_only@1",
        model_policy_ref="model:auto@1",
        entitlement_ref="entitlement:skills.research",
    )


def registry() -> SkillRegistrySnapshot:
    return SkillRegistrySnapshot.from_packages((package(),))


def installations(status=SkillInstallStatus.ENABLED) -> SkillInstallationSnapshot:
    return SkillInstallationSnapshot.from_installations(
        (
            SkillInstallation(
                app_id="b62",
                subject_id="user_1",
                skill_id=SKILL_ID,
                status=status,
            ),
        )
    )


def runtime_policy(**overrides) -> TrustedSkillRuntimePolicy:
    values = {
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "output_contract_ref": "io:research_digest@1",
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
        "available_capabilities": frozenset({"web_search"}),
        "satisfied_entitlement_refs": frozenset({"entitlement:skills.research"}),
    }
    values.update(overrides)
    return TrustedSkillRuntimePolicy(**values)


def test_enabled_skill_compiles_only_through_trusted_runtime_policy() -> None:
    activated = compile_enabled_skill(
        registry=registry(),
        installations=installations(),
        app_id="b62",
        subject_id="user_1",
        skill_id=SKILL_ID,
        runtime_policy=runtime_policy(),
    )

    assert activated.compiled.canonical_skill_id == SKILL_ID
    assert activated.compiled.runtime_profile.allowed_tools == ("web.search",)


def test_enablement_does_not_create_missing_tool_binding() -> None:
    activated = compile_enabled_skill(
        registry=registry(),
        installations=installations(),
        app_id="b62",
        subject_id="user_1",
        skill_id=SKILL_ID,
        runtime_policy=runtime_policy(tool_bindings=()),
    )

    assert activated.compiled.runtime_profile.allowed_tools == ()


def test_enablement_cannot_satisfy_missing_capability() -> None:
    with pytest.raises(SkillRuntimeAdapterError):
        compile_enabled_skill(
            registry=registry(),
            installations=installations(),
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
            runtime_policy=runtime_policy(available_capabilities=frozenset()),
        )


def test_enablement_cannot_satisfy_missing_connector_authorization() -> None:
    with pytest.raises(SkillRuntimeAdapterError):
        compile_enabled_skill(
            registry=registry(),
            installations=installations(),
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
            runtime_policy=runtime_policy(connected_connector_ids=frozenset()),
        )


def test_enablement_cannot_satisfy_missing_entitlement() -> None:
    with pytest.raises(SkillRuntimeAdapterError):
        compile_enabled_skill(
            registry=registry(),
            installations=installations(),
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
            runtime_policy=runtime_policy(satisfied_entitlement_refs=frozenset()),
        )


def test_disabled_skill_never_reaches_runtime_compilation() -> None:
    with pytest.raises(SkillRegistryError) as exc_info:
        compile_enabled_skill(
            registry=registry(),
            installations=installations(SkillInstallStatus.DISABLED),
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
            runtime_policy=runtime_policy(),
        )

    assert exc_info.value.code == "skill_not_enabled"


def test_activation_public_projection_omits_runtime_authority_details() -> None:
    activated = compile_enabled_skill(
        registry=registry(),
        installations=installations(),
        app_id="b62",
        subject_id="user_1",
        skill_id=SKILL_ID,
        runtime_policy=runtime_policy(),
    )
    public = activated.to_public_dict()

    assert public["skill_id"] == SKILL_ID
    assert public["runtime_profile_id"].startswith("skill-runtime:")
    for forbidden in (
        "allowed_tools",
        "connected_connector_ids",
        "satisfied_entitlement_refs",
        "tool_bindings",
        "model_policy",
    ):
        assert forbidden not in public
