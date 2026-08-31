import pytest

from padiem_ai_core.skill_package import (
    ApprovalHook,
    ReusableSkillPackage,
    SkillExecutionBudget,
    SkillPackageError,
    effective_allowed_tool_ids,
    effective_connector_ids,
    missing_required_capabilities,
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
        "execution_budget": SkillExecutionBudget(max_steps=6, max_tool_calls=4, max_wall_seconds=90),
        "approval_hooks": (ApprovalHook.BEFORE_CONNECTOR_WRITE,),
        "entitlement_ref": "entitlement:skills.research",
    }
    values.update(overrides)
    return ReusableSkillPackage(**values)


def test_skill_id_uses_frozen_grammar() -> None:
    package = make_package()
    assert package.skill_id == "skill:padiem:research_digest@1"

    with pytest.raises(SkillPackageError):
        make_package(skill_id="research_digest")


def test_package_can_only_narrow_tool_permissions() -> None:
    package = make_package()
    granted = {
        "tool:padiem:web_search@1",
        "tool:padiem:send_email@1",
    }
    assert effective_allowed_tool_ids(package, granted) == (
        "tool:padiem:web_search@1",
    )
    assert "tool:padiem:send_email@1" not in effective_allowed_tool_ids(package, granted)


def test_package_cannot_create_connector_authorization() -> None:
    package = make_package()
    assert effective_connector_ids(package, frozenset()) == ()
    assert effective_connector_ids(
        package,
        frozenset({"connector:google:drive@1"}),
    ) == ("connector:google:drive@1",)


def test_missing_capabilities_are_fail_closed_inputs() -> None:
    package = make_package()
    assert missing_required_capabilities(package, {"web_search"}) == (
        "structured_output",
    )


def test_duplicate_tools_and_connectors_fail_closed() -> None:
    with pytest.raises(SkillPackageError):
        make_package(
            allowed_tool_ids=(
                "tool:padiem:web_search@1",
                "tool:padiem:web_search@1",
            )
        )

    with pytest.raises(SkillPackageError):
        make_package(
            connector_requirement_ids=(
                "connector:google:drive@1",
                "connector:google:drive@1",
            )
        )


def test_budget_is_bounded() -> None:
    with pytest.raises(SkillPackageError):
        SkillExecutionBudget(max_steps=0)

    with pytest.raises(SkillPackageError):
        SkillExecutionBudget(max_wall_seconds=10_000)


def test_approval_hook_must_be_typed_and_unique() -> None:
    with pytest.raises(SkillPackageError):
        make_package(approval_hooks=("before_connector_write",))

    with pytest.raises(SkillPackageError):
        make_package(
            approval_hooks=(
                ApprovalHook.BEFORE_CONNECTOR_WRITE,
                ApprovalHook.BEFORE_CONNECTOR_WRITE,
            )
        )


def test_package_has_no_self_approval_or_grant_fields() -> None:
    package = make_package()
    assert not hasattr(package, "approved")
    assert not hasattr(package, "granted_tools")
    assert not hasattr(package, "oauth_token")
    assert not hasattr(package, "provider_credential")
