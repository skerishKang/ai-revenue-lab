import pytest

from padiem_ai_core.skill_package import ReusableSkillPackage, SkillExecutionBudget
from padiem_ai_core.skill_registry import (
    RegisteredSkill,
    SkillInstallation,
    SkillInstallationSnapshot,
    SkillInstallStatus,
    SkillRegistryError,
    SkillRegistrySnapshot,
    resolve_enabled_skill,
)


SKILL_ID = "skill:padiem:research_digest@1"


def package(**overrides) -> ReusableSkillPackage:
    values = {
        "skill_id": SKILL_ID,
        "publisher_id": "publisher:padiem",
        "description": "Create a bounded research digest.",
        "instruction": "Use only approved sources and tools.",
        "input_contract_ref": "io:research_input@1",
        "output_contract_ref": "io:research_digest@1",
        "required_capabilities": ("web_search",),
        "allowed_tool_ids": ("tool:padiem:web_search@1",),
        "connector_requirement_ids": ("connector:google:drive@1",),
        "context_policy_ref": "context:reference_only@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": SkillExecutionBudget(max_steps=4, max_tool_calls=2),
        "entitlement_ref": "entitlement:skills.research",
    }
    values.update(overrides)
    return ReusableSkillPackage(**values)


def installation(
    status: SkillInstallStatus = SkillInstallStatus.ENABLED,
    *,
    app_id: str = "b62",
    subject_id: str = "user_1",
    skill_id: str = SKILL_ID,
) -> SkillInstallation:
    return SkillInstallation(
        app_id=app_id,
        subject_id=subject_id,
        skill_id=skill_id,
        status=status,
    )


def test_registry_snapshot_is_deterministic_and_resolves_exact_major_id() -> None:
    second = package(
        skill_id="skill:padiem:summarize@2",
        description="Summarize bounded input.",
        allowed_tool_ids=(),
        connector_requirement_ids=(),
        required_capabilities=(),
        entitlement_ref=None,
    )
    registry = SkillRegistrySnapshot.from_packages((second, package()))

    assert registry.skill_ids == (
        "skill:padiem:research_digest@1",
        "skill:padiem:summarize@2",
    )
    assert registry.get(SKILL_ID).package.skill_id == SKILL_ID


def test_same_canonical_major_id_with_different_content_is_conflict() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))

    with pytest.raises(SkillRegistryError) as exc_info:
        registry.with_package(package(description="Changed package content."))

    assert exc_info.value.code == "skill_registry_version_conflict"


def test_idempotent_reregistration_of_exact_package_returns_same_snapshot() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))

    assert registry.with_package(package()) is registry


def test_registry_rejects_duplicate_exact_id_even_when_content_matches() -> None:
    with pytest.raises(SkillRegistryError) as exc_info:
        SkillRegistrySnapshot.from_packages((package(), package()))

    assert exc_info.value.code == "duplicate_skill_registry_id"


def test_registered_skill_fingerprint_is_bound_to_package_content() -> None:
    registered = RegisteredSkill.from_package(package())

    with pytest.raises(SkillRegistryError) as exc_info:
        RegisteredSkill(package=package(description="Changed."), fingerprint=registered.fingerprint)

    assert exc_info.value.code == "skill_registry_fingerprint_mismatch"


def test_enabled_installation_resolves_declarative_package_only() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))
    states = SkillInstallationSnapshot.from_installations((installation(),))

    resolved = resolve_enabled_skill(
        registry=registry,
        installations=states,
        app_id="b62",
        subject_id="user_1",
        skill_id=SKILL_ID,
    )

    assert resolved == package()
    assert not hasattr(resolved, "granted_tools")
    assert not hasattr(resolved, "access_token")
    assert not hasattr(resolved, "provider_credentials")


def test_installed_but_not_enabled_skill_fails_closed() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))
    states = SkillInstallationSnapshot.from_installations(
        (installation(SkillInstallStatus.INSTALLED),)
    )

    with pytest.raises(SkillRegistryError) as exc_info:
        resolve_enabled_skill(
            registry=registry,
            installations=states,
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
        )

    assert exc_info.value.code == "skill_not_enabled"


def test_disabled_skill_fails_closed() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))
    states = SkillInstallationSnapshot.from_installations(
        (installation(SkillInstallStatus.DISABLED),)
    )

    with pytest.raises(SkillRegistryError) as exc_info:
        resolve_enabled_skill(
            registry=registry,
            installations=states,
            app_id="b62",
            subject_id="user_1",
            skill_id=SKILL_ID,
        )

    assert exc_info.value.code == "skill_not_enabled"


def test_installation_state_is_scoped_by_app_and_subject() -> None:
    registry = SkillRegistrySnapshot.from_packages((package(),))
    states = SkillInstallationSnapshot.from_installations((installation(),))

    with pytest.raises(SkillRegistryError) as exc_info:
        resolve_enabled_skill(
            registry=registry,
            installations=states,
            app_id="storymemory",
            subject_id="user_1",
            skill_id=SKILL_ID,
        )

    assert exc_info.value.code == "skill_not_installed"


def test_installation_snapshot_rejects_duplicate_state_key() -> None:
    with pytest.raises(SkillRegistryError) as exc_info:
        SkillInstallationSnapshot.from_installations((installation(), installation()))

    assert exc_info.value.code == "duplicate_skill_installation"


def test_installation_public_state_contains_no_authority_or_secret_fields() -> None:
    public = installation().to_public_dict()

    assert public == {
        "app_id": "b62",
        "subject_id": "user_1",
        "skill_id": SKILL_ID,
        "status": "enabled",
        "enabled": True,
    }
    for forbidden in (
        "granted_tools",
        "connector_tokens",
        "entitlements",
        "approved_tools",
        "provider_credentials",
    ):
        assert forbidden not in public


def test_unregistered_skill_cannot_be_resolved_even_if_state_claims_enabled() -> None:
    other_id = "skill:padiem:other@1"
    registry = SkillRegistrySnapshot.from_packages((package(),))
    states = SkillInstallationSnapshot.from_installations(
        (installation(skill_id=other_id),)
    )

    with pytest.raises(SkillRegistryError) as exc_info:
        resolve_enabled_skill(
            registry=registry,
            installations=states,
            app_id="b62",
            subject_id="user_1",
            skill_id=other_id,
        )

    assert exc_info.value.code == "skill_not_registered"
