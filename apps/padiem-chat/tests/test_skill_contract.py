from __future__ import annotations

from padiem_ai_core import AgentProfile

from app.skills import Skill, get_skill, skill_public_metadata


def test_b62_skill_is_core_agent_profile_with_short_description_compatibility():
    skill = get_skill("explain")

    assert isinstance(skill, Skill)
    assert isinstance(skill, AgentProfile)
    assert skill.short_description == "어려운 내용을 쉬운 말과 예시로 풉니다."
    assert skill.description == skill.short_description
    assert skill.allowed_tools == ()
    assert skill.required_capabilities == ()
    assert skill.max_steps == 1


def test_b62_skill_historical_constructor_and_public_metadata_stay_product_owned():
    skill = Skill(
        "compat_skill",
        "호환 작업",
        "호환 설명",
        "서버 소유 시스템 지침",
        "general",
        "korean",
        321,
    )

    assert isinstance(skill, AgentProfile)
    assert skill.id == "compat_skill"
    assert skill.title == "호환 작업"
    assert skill.short_description == "호환 설명"
    assert skill.system_instruction == "서버 소유 시스템 지침"
    assert skill.task_type == "general"
    assert skill.optimize_for == "korean"
    assert skill.max_tokens == 321
    assert skill_public_metadata(skill) == {"id": "compat_skill", "title": "호환 작업"}
    assert "system_instruction" not in skill.to_public_dict()
