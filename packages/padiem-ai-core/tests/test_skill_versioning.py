import pytest

from padiem_ai_core.skill_versioning import (
    SkillCompatibility,
    SkillMigrationMap,
    SkillVersionError,
    evaluate_skill_compatibility,
    parse_skill_major,
)


def test_parse_skill_major_uses_frozen_identity_grammar() -> None:
    assert parse_skill_major("skill:padiem:research@3") == 3


def test_same_major_is_compatible() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@2",
        required_skill_id="skill:padiem:research@2",
    )
    assert decision.status is SkillCompatibility.COMPATIBLE
    assert decision.migration_target_major is None


def test_missing_trusted_migration_path_is_incompatible() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@1",
        required_skill_id="skill:padiem:research@2",
    )
    assert decision.status is SkillCompatibility.INCOMPATIBLE
    assert decision.reason == "no_trusted_migration_path"


def test_trusted_migration_edge_requires_explicit_server_mapping() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@1",
        required_skill_id="skill:padiem:research@2",
        migration_map=SkillMigrationMap({1: 2}),
    )
    assert decision.status is SkillCompatibility.MIGRATION_REQUIRED
    assert decision.migration_target_major == 2
    assert decision.reason == "trusted_migration_edge_declared"


def test_migration_map_does_not_chain_implicitly() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@1",
        required_skill_id="skill:padiem:research@3",
        migration_map=SkillMigrationMap({1: 2, 2: 3}),
    )
    assert decision.status is SkillCompatibility.INCOMPATIBLE
    assert decision.migration_target_major is None


def test_different_skill_identity_is_incompatible_even_with_same_major() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@2",
        required_skill_id="skill:other:research@2",
    )
    assert decision.status is SkillCompatibility.INCOMPATIBLE
    assert decision.reason == "skill_identity_changed"


def test_invalid_skill_id_fails_closed() -> None:
    with pytest.raises(SkillVersionError):
        parse_skill_major("skill:padiem:research@0")
    with pytest.raises(SkillVersionError):
        evaluate_skill_compatibility(
            installed_skill_id="research@1",
            required_skill_id="skill:padiem:research@1",
        )


def test_migration_edges_cannot_be_self_edges() -> None:
    with pytest.raises(SkillVersionError):
        SkillMigrationMap({1: 1})


def test_public_decision_contains_no_execution_authority() -> None:
    decision = evaluate_skill_compatibility(
        installed_skill_id="skill:padiem:research@1",
        required_skill_id="skill:padiem:research@2",
        migration_map=SkillMigrationMap({1: 2}),
    )
    public = decision.to_public_dict()
    assert "authorization" not in public
    assert "tool_grants" not in public
    assert "credentials" not in public
