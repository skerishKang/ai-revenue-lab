from __future__ import annotations

from padiem_ai_core import AgentProfile

from app.skills import Skill, get_skill, skill_public_metadata
from app.task_modes import TaskMode, get_task_mode, task_mode_public_metadata


def test_b62_task_modes_are_product_presets_and_skill_is_compatibility_alias():
    mode = get_task_mode("explain")

    assert isinstance(mode, TaskMode)
    assert Skill is TaskMode
    assert get_skill("explain") is mode
    assert isinstance(mode, AgentProfile)
    assert mode.short_description == "어려운 내용을 쉬운 말과 예시로 풉니다."
    assert mode.description == mode.short_description
    assert mode.allowed_tools == ()
    assert mode.required_capabilities == ()
    assert mode.max_steps == 1
    assert task_mode_public_metadata(mode) == {"id": "explain", "title": "쉽게 설명"}


def test_historical_skill_constructor_and_public_metadata_stay_compatible():
    mode = Skill(
        "compat_skill",
        "호환 작업",
        "호환 설명",
        "서버 소유 시스템 지침",
        "general",
        "korean",
        321,
    )

    assert isinstance(mode, TaskMode)
    assert isinstance(mode, AgentProfile)
    assert mode.id == "compat_skill"
    assert mode.title == "호환 작업"
    assert mode.short_description == "호환 설명"
    assert mode.system_instruction == "서버 소유 시스템 지침"
    assert mode.task_type == "general"
    assert mode.optimize_for == "korean"
    assert mode.max_tokens == 321
    assert skill_public_metadata(mode) == {"id": "compat_skill", "title": "호환 작업"}
    assert "system_instruction" not in mode.to_public_dict()
